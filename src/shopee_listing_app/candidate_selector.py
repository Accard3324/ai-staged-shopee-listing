from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .config_manager import load_app_config
from .workbook_reader import norm_text, read_workbook_rows


@dataclass(frozen=True)
class CandidateSKU:
    row: int
    sku_spec: str
    store_status: str
    price_1box: object
    price_2box: object
    price_3box: object
    sales_rank_15d_avg: object
    sku_code: object
    product_name: object
    brand: object
    overseas_available_stock: object
    package_weight_kg: object = ""
    package_length_cm: object = ""
    package_width_cm: object = ""
    package_height_cm: object = ""

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateSelectionResult:
    workbook: str
    sheet: str
    store: str
    status_column: str
    requested_count: int
    returned_count: int
    total_unlisted: int
    candidates: List[CandidateSKU]

    def to_dict(self) -> Dict[str, object]:
        return {
            "workbook": self.workbook,
            "sheet": self.sheet,
            "store": self.store,
            "status_column": self.status_column,
            "requested_count": self.requested_count,
            "returned_count": self.returned_count,
            "total_unlisted": self.total_unlisted,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def select_candidates(
    store_name: str,
    count: int,
    workbook_path: Optional[Path] = None,
    config_dir: Optional[Path] = None,
    store_col: Optional[str] = None,
    requested_sku_code: Optional[str] = None,
) -> CandidateSelectionResult:
    if count < 1:
        raise ValueError("count must be >= 1")

    config = load_app_config(config_dir)
    store = config.store(store_name)
    status_col = (store_col or store.status_column).upper()
    workbook = Path(workbook_path) if workbook_path else Path(config.workbook.path)
    field_columns = config.workbook.field_columns
    package_columns = {
        field_columns["package_weight_kg"],
        field_columns["package_length_cm"],
        field_columns["package_width_cm"],
        field_columns["package_height_cm"],
    }
    sheet_name, rows = read_workbook_rows(
        workbook,
        config.workbook.sheet_prefix,
        formatted_columns=package_columns,
    )
    candidates: List[CandidateSKU] = []
    total_unlisted = 0
    requested_sku = norm_text(requested_sku_code)

    def build_candidate(row_number: int, row: Dict[str, object], status: str) -> CandidateSKU:
        return CandidateSKU(
            row=row_number,
            sku_spec=norm_text(row.get(field_columns["sku_spec"])),
            store_status=status,
            price_1box=row.get(field_columns["price_1box"], ""),
            price_2box=row.get(field_columns["price_2box"], ""),
            price_3box=row.get(field_columns["price_3box"], ""),
            sales_rank_15d_avg=row.get(field_columns["sales_rank_15d_avg"], ""),
            sku_code=row.get(field_columns["sku_code"], ""),
            product_name=row.get(field_columns["product_name"], ""),
            brand=row.get(field_columns["brand"], ""),
            overseas_available_stock=row.get(field_columns["overseas_available_stock"], ""),
            package_weight_kg=row.get(field_columns["package_weight_kg"], ""),
            package_length_cm=row.get(field_columns["package_length_cm"], ""),
            package_width_cm=row.get(field_columns["package_width_cm"], ""),
            package_height_cm=row.get(field_columns["package_height_cm"], ""),
        )

    for row_number in sorted(rows):
        row = rows[row_number]
        sku_spec = norm_text(row.get(field_columns["sku_spec"]))
        status = norm_text(row.get(status_col))
        row_sku_code = norm_text(row.get(field_columns["sku_code"]))

        if requested_sku:
            if row_sku_code.casefold() == requested_sku.casefold():
                candidates.append(build_candidate(row_number, row, status))
                break
            continue

        if status != config.workbook.unlisted_status or not sku_spec:
            continue

        total_unlisted += 1
        if len(candidates) >= count:
            continue

        candidates.append(build_candidate(row_number, row, status))

    return CandidateSelectionResult(
        workbook=str(workbook),
        sheet=sheet_name,
        store=store.name,
        status_column=status_col,
        requested_count=count,
        returned_count=len(candidates),
        total_unlisted=total_unlisted,
        candidates=candidates,
    )


def candidates_markdown(result: CandidateSelectionResult) -> str:
    lines = [
        f"Workbook: `{result.workbook}`",
        f"Sheet: `{result.sheet}`",
        f"Store: `{result.store}` (status column {result.status_column})",
        f"Returned: {result.returned_count} of {result.total_unlisted} unlisted rows",
        "",
        "| Row | SKU code (AB) | SKU/spec (A) | Product name (AC) | Brand (AD) | Stock AO | Weight V | L/W/H W/X/Y | 1box E | 2box F | 3box G | Z rank |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in result.candidates:
        lines.append(
            f"| {item.row} | {norm_text(item.sku_code)} | {norm_text(item.sku_spec)} | "
            f"{norm_text(item.product_name)} | {norm_text(item.brand)} | "
            f"{norm_text(item.overseas_available_stock)} | {norm_text(item.package_weight_kg)} | "
            f"{norm_text(item.package_length_cm)}/{norm_text(item.package_width_cm)}/{norm_text(item.package_height_cm)} | "
            f"{norm_text(item.price_1box)} | "
            f"{norm_text(item.price_2box)} | {norm_text(item.price_3box)} | "
            f"{norm_text(item.sales_rank_15d_avg)} |"
        )
    return "\n".join(lines)
