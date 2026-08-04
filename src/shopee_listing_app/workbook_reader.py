from __future__ import annotations

import contextlib
import ctypes
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import posixpath
import re
import sys
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple
from xml.etree import ElementTree as ET

if sys.platform == "win32":
    import msvcrt
else:
    msvcrt = None


def norm_text(value: object) -> str:
    return str(value or "").replace("\u3000", " ").strip()


def col_to_index(col: str) -> int:
    total = 0
    for char in col.upper():
        if not ("A" <= char <= "Z"):
            raise ValueError(f"Invalid column: {col}")
        total = total * 26 + (ord(char) - ord("A") + 1)
    return total


def index_to_col(index: int) -> str:
    col = ""
    while index:
        index, rem = divmod(index - 1, 26)
        col = chr(ord("A") + rem) + col
    return col


def cell_ref_parts(cell_ref: str) -> Tuple[str, int]:
    match = re.match(r"([A-Z]+)([0-9]+)$", cell_ref.upper())
    if not match:
        raise ValueError(f"Invalid cell reference: {cell_ref}")
    return match.group(1), int(match.group(2))


def ns(tag: str) -> str:
    return f"{{http://schemas.openxmlformats.org/spreadsheetml/2006/main}}{tag}"


def rel_ns(tag: str) -> str:
    return f"{{http://schemas.openxmlformats.org/officeDocument/2006/relationships}}{tag}"


def package_rel_ns(tag: str) -> str:
    return f"{{http://schemas.openxmlformats.org/package/2006/relationships}}{tag}"


def read_xml(zf: zipfile.ZipFile, name: str) -> ET.Element:
    with zf.open(name) as handle:
        return ET.fromstring(handle.read())


@contextlib.contextmanager
def open_workbook_zip(workbook: Path) -> Iterable[zipfile.ZipFile]:
    """Open an XLSX read-only, including workbooks open in WPS/Excel on Windows."""

    if sys.platform != "win32":
        with zipfile.ZipFile(workbook) as zf:
            yield zf
        return

    generic_read = 0x80000000
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    open_existing = 3
    file_attribute_normal = 0x00000080
    invalid_handle_value = ctypes.c_void_p(-1).value

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateFileW(
        str(workbook),
        generic_read,
        file_share_read | file_share_write,
        None,
        open_existing,
        file_attribute_normal,
        None,
    )
    if handle == invalid_handle_value:
        raise OSError(ctypes.get_last_error(), f"Unable to open workbook: {workbook}")
    if msvcrt is None:
        raise RuntimeError("Windows shared workbook handle requires msvcrt")

    fd = msvcrt.open_osfhandle(handle, 0)
    with open(fd, "rb", closefd=True) as file_obj:
        with zipfile.ZipFile(file_obj) as zf:
            yield zf


def read_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = read_xml(zf, "xl/sharedStrings.xml")
    values: List[str] = []
    for si in root.findall(ns("si")):
        texts = [node.text or "" for node in si.iter(ns("t"))]
        values.append("".join(texts))
    return values


BUILTIN_NUMBER_FORMATS = {
    1: "0",
    2: "0.00",
    3: "#,##0",
    4: "#,##0.00",
    9: "0%",
    10: "0.00%",
}


def read_cell_number_formats(zf: zipfile.ZipFile) -> List[str]:
    if "xl/styles.xml" not in zf.namelist():
        return []
    root = read_xml(zf, "xl/styles.xml")
    custom_formats: Dict[int, str] = {}
    num_formats = root.find(ns("numFmts"))
    if num_formats is not None:
        for item in num_formats.findall(ns("numFmt")):
            try:
                format_id = int(item.attrib.get("numFmtId", ""))
            except ValueError:
                continue
            custom_formats[format_id] = item.attrib.get("formatCode", "")

    cell_formats = root.find(ns("cellXfs"))
    if cell_formats is None:
        return []
    result: List[str] = []
    for item in cell_formats.findall(ns("xf")):
        try:
            format_id = int(item.attrib.get("numFmtId", "0"))
        except ValueError:
            format_id = 0
        result.append(custom_formats.get(format_id, BUILTIN_NUMBER_FORMATS.get(format_id, "")))
    return result


def format_excel_number(raw: str, format_code: str) -> str | None:
    """Render simple Excel numeric formats without changing the stored value."""

    try:
        number = Decimal(raw)
    except InvalidOperation:
        return None
    code = str(format_code or "").split(";", 1)[0]
    code = re.sub(r'"[^"]*"', "", code)
    code = re.sub(r"\\.", "", code)
    code = re.sub(r"_.", "", code)
    code = re.sub(r"\*.", "", code)
    code = re.sub(r"\[[^\]]+\]", "", code)
    if not code or re.search(r"[dmyhs]|[Ee][+-]|/", code, flags=re.I):
        return None

    percent = "%" in code
    if percent:
        number *= 100
    decimal_match = re.search(r"\.([0#]+)", code)
    decimal_pattern = decimal_match.group(1) if decimal_match else ""
    decimal_places = len(decimal_pattern)
    required_places = decimal_pattern.count("0")
    quantizer = Decimal(1).scaleb(-decimal_places)
    rounded = number.quantize(quantizer, rounding=ROUND_HALF_UP)
    grouping = "," in code.split(".", 1)[0]
    rendered = f"{rounded:,.{decimal_places}f}" if grouping else f"{rounded:.{decimal_places}f}"
    if decimal_places > required_places and "." in rendered:
        integer_part, fractional_part = rendered.split(".", 1)
        optional_places = decimal_places - required_places
        while optional_places and fractional_part.endswith("0"):
            fractional_part = fractional_part[:-1]
            optional_places -= 1
        rendered = integer_part + (f".{fractional_part}" if fractional_part else "")
    return rendered + ("%" if percent else "")


def workbook_sheets(zf: zipfile.ZipFile) -> List[Tuple[str, str]]:
    workbook = read_xml(zf, "xl/workbook.xml")
    rels = read_xml(zf, "xl/_rels/workbook.xml.rels")

    rel_targets: Dict[str, str] = {}
    for rel in rels.findall(package_rel_ns("Relationship")):
        rel_id = rel.attrib.get("Id", "")
        target = rel.attrib.get("Target", "")
        if target.startswith("/"):
            normalized = target.lstrip("/")
        else:
            normalized = posixpath.normpath(posixpath.join("xl", target))
        rel_targets[rel_id] = normalized

    sheets = []
    sheets_node = workbook.find(ns("sheets"))
    if sheets_node is None:
        return sheets
    for sheet in sheets_node.findall(ns("sheet")):
        name = sheet.attrib.get("name", "")
        rel_id = sheet.attrib.get(rel_ns("id"), "")
        target = rel_targets.get(rel_id)
        if target:
            sheets.append((name, target))
    return sheets


def pick_sheet(sheets: Iterable[Tuple[str, str]], prefix: str) -> Tuple[str, str]:
    matches = [(name, path) for name, path in sheets if name.startswith(prefix)]
    if not matches:
        available = ", ".join(name for name, _ in sheets)
        raise RuntimeError(f"No sheet starts with {prefix!r}. Available sheets: {available}")
    return matches[-1]


def cell_value(cell: ET.Element, shared_strings: List[str], display_format: str = "") -> object:
    cell_type = cell.attrib.get("t")

    if cell_type == "inlineStr":
        inline = cell.find(ns("is"))
        if inline is None:
            return ""
        return "".join(node.text or "" for node in inline.iter(ns("t")))

    value_node = cell.find(ns("v"))
    if value_node is None:
        return ""
    raw = value_node.text or ""

    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError):
            return raw
    if cell_type in {"str", "b", "e"}:
        return raw
    if display_format:
        displayed = format_excel_number(raw, display_format)
        if displayed is not None:
            return displayed
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return float(raw)
    return raw


def read_rows(
    zf: zipfile.ZipFile,
    sheet_path: str,
    shared_strings: List[str],
    formatted_columns: Set[str] | None = None,
    cell_number_formats: List[str] | None = None,
) -> Dict[int, Dict[str, object]]:
    root = read_xml(zf, sheet_path)
    formatted = {column.upper() for column in (formatted_columns or set())}
    style_formats = cell_number_formats or []
    rows: Dict[int, Dict[str, object]] = {}
    for row in root.iter(ns("row")):
        row_index_raw = row.attrib.get("r")
        if not row_index_raw:
            continue
        row_index = int(row_index_raw)
        values: Dict[str, object] = {}
        for cell in row.findall(ns("c")):
            ref = cell.attrib.get("r")
            if not ref:
                continue
            col, _ = cell_ref_parts(ref)
            display_format = ""
            if col in formatted:
                try:
                    style_index = int(cell.attrib.get("s", "0"))
                    display_format = style_formats[style_index]
                except (ValueError, IndexError):
                    display_format = ""
            values[col] = cell_value(cell, shared_strings, display_format)
        rows[row_index] = values
    return rows


def read_workbook_rows(
    workbook: Path,
    sheet_prefix: str,
    formatted_columns: Iterable[str] | None = None,
) -> Tuple[str, Dict[int, Dict[str, object]]]:
    if not workbook.exists():
        raise RuntimeError(f"Workbook not found: {workbook}")
    with open_workbook_zip(workbook) as zf:
        shared_strings = read_shared_strings(zf)
        sheet_name, sheet_path = pick_sheet(workbook_sheets(zf), sheet_prefix)
        formatted = {column.upper() for column in (formatted_columns or [])}
        styles = read_cell_number_formats(zf) if formatted else []
        rows = read_rows(zf, sheet_path, shared_strings, formatted, styles)
    return sheet_name, rows
