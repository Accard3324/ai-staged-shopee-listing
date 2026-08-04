from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZIP_DEFLATED, ZipFile

from .config_manager import load_app_config, normalize_key
from .workbook_reader import cell_value, ns, read_shared_strings, workbook_sheets


STORE_SHEET_MAP = {
    "Shopee-MY-Store-B": "StoreBListings",
    "Shopee-MY-Store-A": "StoreAListings",
    "Shopee-MY-Store-C": "StoreCListings",
}

_WORKBOOK_WRITE_LOCK = threading.RLock()


class WorkbookInUseError(RuntimeError):
    pass


@dataclass(frozen=True)
class ListingWorkbookUpdate:
    workbook_path: str
    sheet_name: str
    row_number: int
    product_id: str
    sku_code: str
    appended: bool
    write_mode: str = "closed_file"
    spreadsheet_app: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "workbook_path": self.workbook_path,
            "sheet_name": self.sheet_name,
            "row_number": self.row_number,
            "product_id": self.product_id,
            "sku_code": self.sku_code,
            "appended": self.appended,
            "write_mode": self.write_mode,
            "spreadsheet_app": self.spreadsheet_app,
        }


def sheet_for_store(store_name: str) -> str:
    normalized = str(store_name or "").strip().casefold()
    try:
        config = load_app_config()
        canonical_key = config.aliases.get(normalize_key(store_name))
        if canonical_key in config.stores:
            configured_sheet = config.stores[canonical_key].listing_sheet
            if configured_sheet:
                return configured_sheet
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        pass
    for known_store, sheet_name in STORE_SHEET_MAP.items():
        if known_store.casefold() == normalized:
            return sheet_name
    known = ", ".join(STORE_SHEET_MAP)
    raise ValueError(f"Unsupported store: {store_name}. Supported stores: {known}")


def append_listing_record(
    workbook_path: Path,
    store_name: str,
    sku_code: object,
    product_id: object,
) -> ListingWorkbookUpdate:
    with _WORKBOOK_WRITE_LOCK:
        workbook, target_sheet, sku, product = _validated_record(
            workbook_path,
            store_name,
            sku_code,
            product_id,
        )
        if _workbook_is_locked(workbook):
            live_result = _append_to_open_workbook(workbook, target_sheet, sku, product)
            if live_result is not None:
                return live_result
            raise RuntimeError(
                "The listing workbook is open in Excel/WPS, but the app could not connect to that window. "
                "Make sure the app and Excel/WPS run with the same permission level, then retry Step 15."
            )
        try:
            return _append_listing_record(workbook, store_name, sku, product)
        except WorkbookInUseError:
            live_result = _append_to_open_workbook(workbook, target_sheet, sku, product)
            if live_result is not None:
                return live_result
            raise RuntimeError(
                "The listing workbook became locked by Excel/WPS during write-back, and the app could not connect to that window. "
                "Make sure the app and Excel/WPS run with the same permission level, then retry Step 15."
            )


def _validated_record(
    workbook_path: Path,
    store_name: str,
    sku_code: object,
    product_id: object,
) -> tuple[Path, str, str, str]:
    workbook = Path(workbook_path)
    sku = str(sku_code or "").strip()
    product = str(product_id or "").strip()
    if not sku:
        raise ValueError("The SKU code cannot be empty.")
    if not product:
        raise ValueError("The product ID cannot be empty.")
    if not workbook.is_file():
        raise FileNotFoundError(f"Listing workbook not found: {workbook}")
    return workbook, sheet_for_store(store_name), sku, product


def _workbook_is_locked(workbook: Path) -> bool:
    if os.name != "nt":
        return False
    try:
        with workbook.open("r+b"):
            return False
    except PermissionError:
        return True


_OPEN_WORKBOOK_POWERSHELL = r"""
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding

$targetPath = [System.IO.Path]::GetFullPath($env:SHOPEE_WORKBOOK_PATH).TrimEnd('\')
$sheetName = $env:SHOPEE_SHEET_NAME
$skuCode = $env:SHOPEE_SKU_CODE
$productId = $env:SHOPEE_PRODUCT_ID
$application = $null
$workbook = $null
$applicationName = ""

foreach ($candidate in @(
    @{ ProgId = "Excel.Application"; Name = "Microsoft Excel/WPS" },
    @{ ProgId = "ket.Application"; Name = "WPS Spreadsheets" }
)) {
    try {
        $currentApp = [Runtime.InteropServices.Marshal]::GetActiveObject($candidate.ProgId)
    } catch {
        continue
    }
    foreach ($currentBook in $currentApp.Workbooks) {
        try {
            $currentPath = [System.IO.Path]::GetFullPath([string]$currentBook.FullName).TrimEnd('\')
            if ([string]::Equals($currentPath, $targetPath, [System.StringComparison]::OrdinalIgnoreCase)) {
                $application = $currentApp
                $workbook = $currentBook
                $applicationName = $candidate.Name
                break
            }
        } catch {
            continue
        }
    }
    if ($null -ne $workbook) {
        break
    }
}

if ($null -eq $workbook) {
    @{ status = "not_open" } | ConvertTo-Json -Compress
    exit 0
}

try {
    $sheet = $workbook.Worksheets.Item($sheetName)
    $usedRange = $sheet.UsedRange
    $lastRow = [Math]::Max(
        1,
        [int]$usedRange.Row + [int]$usedRange.Rows.Count - 1
    )
    $existingRow = 0
    $values = $sheet.Range("A1:E$lastRow").Value2
    for ($row = 1; $row -le $lastRow; $row++) {
        $existingProduct = [string]$values.GetValue($row, 1)
        $existingSku = [string]$values.GetValue($row, 5)
        if ($existingProduct.Trim() -eq $productId -and $existingSku.Trim() -eq $skuCode) {
            $existingRow = $row
            break
        }
    }

    $appended = $false
    if ($existingRow -gt 0) {
        $targetRow = $existingRow
    } else {
        $targetRow = $lastRow + 1
        $sourceA = $sheet.Cells.Item($lastRow, 1)
        $sourceE = $sheet.Cells.Item($lastRow, 5)
        $targetA = $sheet.Cells.Item($targetRow, 1)
        $targetE = $sheet.Cells.Item($targetRow, 5)
        try { $sourceA.Copy($targetA) } catch {}
        try { $sourceE.Copy($targetE) } catch {}
        if ($productId -match '^\d{1,15}$') {
            $targetA.Value2 = [double]$productId
        } else {
            $targetA.Value2 = $productId
        }
        $targetE.Value2 = $skuCode
        try { $application.CutCopyMode = $false } catch {}
        $appended = $true
    }

    try {
        $application.CalculateFullRebuild()
    } catch {
        try {
            $application.CalculateFull()
        } catch {
            try { $workbook.Calculate() } catch {}
        }
    }
    $workbook.Save()

    $savedProduct = [string]$sheet.Cells.Item($targetRow, 1).Value2
    $savedSku = [string]$sheet.Cells.Item($targetRow, 5).Value2
    if ($savedProduct.Trim() -ne $productId -or $savedSku.Trim() -ne $skuCode) {
        throw "Read-back mismatch after save: column A or E does not contain the target value"
    }

    @{
        status = "ok"
        row_number = $targetRow
        appended = $appended
        application = $applicationName
    } | ConvertTo-Json -Compress
} catch {
    @{
        status = "error"
        message = $_.Exception.Message
    } | ConvertTo-Json -Compress
}
"""


def _append_to_open_workbook(
    workbook: Path,
    target_sheet: str,
    sku_code: str,
    product_id: str,
) -> ListingWorkbookUpdate | None:
    if os.name != "nt":
        return None

    environment = os.environ.copy()
    environment.update(
        {
            "SHOPEE_WORKBOOK_PATH": str(workbook.resolve()),
            "SHOPEE_SHEET_NAME": target_sheet,
            "SHOPEE_SKU_CODE": sku_code,
            "SHOPEE_PRODUCT_ID": product_id,
        }
    )
    encoded = base64.b64encode(_OPEN_WORKBOOK_POWERSHELL.encode("utf-16le")).decode("ascii")
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            env=environment,
            capture_output=True,
            timeout=90,
            check=False,
            creationflags=creation_flags,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Unable to connect to the open Excel/WPS workbook: {exc}") from exc

    stdout = completed.stdout.decode("utf-8-sig", errors="replace")
    response: dict[str, object] | None = None
    for line in reversed([item.strip() for item in stdout.splitlines() if item.strip()]):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            response = parsed
            break
    if response is None:
        stderr = completed.stderr.decode("utf-8-sig", errors="replace").strip()
        detail = stderr or stdout.strip() or f"PowerShell exit code {completed.returncode}"
        raise RuntimeError(f"Unable to connect to the open Excel/WPS workbook: {detail}")

    status = str(response.get("status", "")).strip()
    if status == "not_open":
        return None
    if status != "ok":
        detail = str(response.get("message", "")).strip() or "no specific reason returned"
        raise RuntimeError(f"Unable to write to the open Excel/WPS workbook: {detail}")

    return ListingWorkbookUpdate(
        workbook_path=str(workbook),
        sheet_name=target_sheet,
        row_number=int(response.get("row_number", 0)),
        product_id=product_id,
        sku_code=sku_code,
        appended=bool(response.get("appended", False)),
        write_mode="open_workbook",
        spreadsheet_app=str(response.get("application", "")).strip(),
    )


def _append_listing_record(
    workbook_path: Path,
    store_name: str,
    sku_code: object,
    product_id: object,
) -> ListingWorkbookUpdate:
    workbook, target_sheet, sku, product = _validated_record(
        workbook_path,
        store_name,
        sku_code,
        product_id,
    )
    replacements: dict[str, bytes] = {}
    expected_hashes: dict[str, bytes] = {}
    result: ListingWorkbookUpdate | None = None

    try:
        with ZipFile(workbook, "r") as source:
            workbook_xml_path = "xl/workbook.xml"
            workbook_xml = source.read(workbook_xml_path)
            recalculation_xml = _force_full_recalculation(workbook_xml)
            if recalculation_xml != workbook_xml:
                replacements[workbook_xml_path] = recalculation_xml
                expected_hashes[workbook_xml_path] = hashlib.sha256(workbook_xml).digest()

            sheets = dict(workbook_sheets(source))
            target_path = sheets.get(target_sheet, "")
            if not target_path:
                available = ", ".join(sheets)
                raise RuntimeError(f'Sheet "{target_sheet}" was not found. Available sheets: {available}')
            shared_strings = read_shared_strings(source)
            original_xml = source.read(target_path)
            root = ET.fromstring(original_xml)
            sheet_data = root.find(ns("sheetData"))
            if sheet_data is None:
                raise RuntimeError(f'Sheet "{target_sheet}" has no sheetData element, so rows cannot be appended safely.')

            existing = _find_existing_pair(sheet_data, shared_strings, product, sku)
            if existing:
                result = ListingWorkbookUpdate(str(workbook), target_sheet, existing, product, sku, False)
            else:
                rows = list(sheet_data.findall(ns("row")))
                last_row = max((_row_number(row) for row in rows), default=0)
                next_row = last_row + 1
                new_row_xml = _build_row_xml(sheet_data, next_row, product, sku)
                replacement_xml = _append_row_xml(original_xml, new_row_xml, next_row)
                replacements[target_path] = replacement_xml
                expected_hashes[target_path] = hashlib.sha256(original_xml).digest()
                result = ListingWorkbookUpdate(str(workbook), target_sheet, next_row, product, sku, True)
    except PermissionError as exc:
        raise WorkbookInUseError("Unable to read the listing workbook because Excel/WPS is using the file.") from exc

    if result is None:
        raise RuntimeError("No workbook write-back result was generated.")
    if replacements:
        _replace_workbook_entries(workbook, replacements, expected_hashes)
    return result


def _find_existing_pair(sheet_data: ET.Element, shared_strings: list[str], product_id: str, sku_code: str) -> int:
    for row in sheet_data.findall(ns("row")):
        values: dict[str, str] = {}
        for cell in row.findall(ns("c")):
            ref = cell.attrib.get("r", "")
            column = re.sub(r"\d", "", ref).upper()
            if column in {"A", "E"}:
                values[column] = str(cell_value(cell, shared_strings)).strip()
        if values.get("A") == product_id and values.get("E") == sku_code:
            return _row_number(row)
    return 0


def _row_number(row: ET.Element) -> int:
    try:
        return int(row.attrib.get("r", "0"))
    except ValueError:
        return 0


def _build_row_xml(sheet_data: ET.Element, row_number: int, product_id: str, sku_code: str) -> bytes:
    rows = list(sheet_data.findall(ns("row")))
    row_attrs = dict(rows[-1].attrib) if rows else {}
    row_attrs["r"] = str(row_number)
    safe_row_attrs = {key: value for key, value in row_attrs.items() if "}" not in key}
    row_start = "<row" + _attributes_xml(safe_row_attrs) + ">"

    product_attrs = _cell_attributes(sheet_data, "A", row_number)
    if product_id.isdigit() and len(product_id) <= 15:
        product_xml = f"<c{_attributes_xml(product_attrs)}><v>{escape(product_id)}</v></c>"
    else:
        product_attrs["t"] = "inlineStr"
        product_xml = f"<c{_attributes_xml(product_attrs)}><is><t>{escape(product_id)}</t></is></c>"

    sku_attrs = _cell_attributes(sheet_data, "E", row_number)
    sku_attrs["t"] = "inlineStr"
    sku_xml = f"<c{_attributes_xml(sku_attrs)}><is><t>{escape(sku_code)}</t></is></c>"
    return f"{row_start}{product_xml}{sku_xml}</row>".encode("utf-8")


def _cell_attributes(sheet_data: ET.Element, column: str, row_number: int) -> dict[str, str]:
    attrs = {"r": f"{column}{row_number}"}
    for row in reversed(sheet_data.findall(ns("row"))):
        for cell in row.findall(ns("c")):
            if re.sub(r"\d", "", cell.attrib.get("r", "")).upper() == column:
                style = cell.attrib.get("s")
                if style:
                    attrs["s"] = style
                return attrs
    return attrs


def _attributes_xml(attributes: dict[str, str]) -> str:
    return "".join(f" {key}={quoteattr(str(value))}" for key, value in attributes.items())


def _append_row_xml(worksheet_xml: bytes, row_xml: bytes, row_number: int) -> bytes:
    closing = list(re.finditer(rb"</(?:[A-Za-z_][A-Za-z0-9_.-]*:)?sheetData\s*>", worksheet_xml))
    if len(closing) != 1:
        raise RuntimeError("The target sheet has an invalid sheetData closing tag; the original file was not modified.")

    dimension_pattern = re.compile(
        rb"(<(?:[A-Za-z_][A-Za-z0-9_.-]*:)?dimension\b[^>]*?\bref\s*=\s*)([\"'])([^\"']+)([\"'])",
        re.IGNORECASE,
    )

    def replace_dimension(match: re.Match[bytes]) -> bytes:
        if match.group(2) != match.group(4):
            return match.group(0)
        current = match.group(3).decode("ascii", errors="ignore")
        start, separator, end = current.partition(":")
        end_ref = end if separator else start
        end_col_match = re.match(r"([A-Z]+)", end_ref.upper())
        end_col = end_col_match.group(1) if end_col_match else "E"
        new_ref = f"{start}:{end_col}{row_number}".encode("ascii")
        return match.group(1) + match.group(2) + new_ref + match.group(4)

    updated, _ = dimension_pattern.subn(replace_dimension, worksheet_xml, count=1)
    closing_match = re.search(rb"</(?:[A-Za-z_][A-Za-z0-9_.-]*:)?sheetData\s*>", updated)
    if closing_match is None:
        raise RuntimeError("The target sheet has no sheetData closing tag; the original file was not modified.")
    return updated[: closing_match.start()] + row_xml + updated[closing_match.start() :]


def _force_full_recalculation(workbook_xml: bytes) -> bytes:
    calc_pattern = re.compile(
        rb"<(?:(?:[A-Za-z_][A-Za-z0-9_.-]*):)?calcPr\b[^>]*?/?>",
        re.IGNORECASE,
    )
    calc_match = calc_pattern.search(workbook_xml)
    if calc_match:
        calc_tag = calc_match.group(0)
        for name, value in (
            (b"calcId", b"0"),
            (b"calcMode", b"auto"),
            (b"fullCalcOnLoad", b"1"),
            (b"forceFullCalc", b"1"),
        ):
            calc_tag = _set_xml_attribute(calc_tag, name, value)
        return workbook_xml[: calc_match.start()] + calc_tag + workbook_xml[calc_match.end() :]

    closing = re.search(
        rb"</(?:(?:[A-Za-z_][A-Za-z0-9_.-]*):)?workbook\s*>",
        workbook_xml,
        re.IGNORECASE,
    )
    if closing is None:
        raise RuntimeError("The workbook has no workbook closing tag, so automatic formula recalculation cannot be enabled.")
    calc_tag = b'<calcPr calcId="0" calcMode="auto" fullCalcOnLoad="1" forceFullCalc="1"/>'
    return workbook_xml[: closing.start()] + calc_tag + workbook_xml[closing.start() :]


def _set_xml_attribute(tag: bytes, name: bytes, value: bytes) -> bytes:
    attribute_pattern = re.compile(
        rb"(\b" + re.escape(name) + rb"\s*=\s*)([\"'])(.*?)(\2)",
        re.IGNORECASE,
    )
    if attribute_pattern.search(tag):
        return attribute_pattern.sub(
            lambda match: match.group(1) + match.group(2) + value + match.group(4),
            tag,
            count=1,
        )
    insertion = tag.rfind(b"/>")
    if insertion < 0:
        insertion = tag.rfind(b">")
    if insertion < 0:
        raise RuntimeError("The workbook calculation-properties tag is invalid, so automatic formula recalculation cannot be enabled.")
    return tag[:insertion] + b" " + name + b'="' + value + b'"' + tag[insertion:]


def _replace_workbook_entries(
    workbook: Path,
    replacements: dict[str, bytes],
    expected_hashes: dict[str, bytes],
) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{workbook.stem}_",
            suffix=".tmp.xlsx",
            dir=workbook.parent,
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)

        source_stat = _file_signature(workbook)
        with ZipFile(workbook, "r") as source, ZipFile(temp_path, "w", ZIP_DEFLATED, allowZip64=True) as output:
            output.comment = source.comment
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename in replacements:
                    if hashlib.sha256(data).digest() != expected_hashes[info.filename]:
                        raise RuntimeError("Another application modified the workbook during write-back. Retry the write; the original file was not modified.")
                    data = replacements[info.filename]
                output.writestr(info, data)

        with ZipFile(temp_path, "r") as verification:
            if verification.testzip() is not None:
                raise RuntimeError("Temporary workbook validation failed after write-back; the original file was not modified.")
            for target_path in replacements:
                ET.fromstring(verification.read(target_path))

        if _file_signature(workbook) != source_stat:
            raise RuntimeError("Another application modified the workbook during write-back. Retry the write; the original file was not modified.")
        os.chmod(temp_path, workbook.stat().st_mode)
        try:
            os.replace(temp_path, workbook)
        except PermissionError as exc:
            raise WorkbookInUseError("Unable to save the listing workbook because Excel/WPS is using the file; the original file was not modified.") from exc
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def _file_signature(path: Path) -> tuple[int, int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ino
