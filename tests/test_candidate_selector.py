from pathlib import Path
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.candidate_selector import select_candidates


def _sheet_xml(rows):
    row_xml = []
    for row_number, cells in rows.items():
        cell_xml = []
        for col, value in cells.items():
            if isinstance(value, tuple):
                raw_value, style_index = value
                cell_xml.append(f'<c r="{col}{row_number}" s="{style_index}"><v>{raw_value}</v></c>')
            else:
                cell_xml.append(
                    f'<c r="{col}{row_number}" t="inlineStr"><is><t>{value}</t></is></c>'
                )
        row_xml.append(f'<row r="{row_number}">{"".join(cell_xml)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        "</worksheet>"
    )


def _write_minimal_workbook(path: Path):
    rows = {
        1: {"A": "Header"},
        2: {
            "A": "28g",
            "B": "未上架",
            "C": "123456",
            "D": "未上架",
            "E": "9.90",
            "F": "18.80",
            "G": "27.50",
            "V": ("0.039", "1"),
            "W": ("8", "2"),
            "X": ("2.5", "2"),
            "Y": ("9", "2"),
            "Z": "1.2",
            "AB": "SKU-001",
            "AC": "Toothpaste",
            "AD": "BrandA",
            "AO": "88",
        },
        3: {
            "A": "50g",
            "B": "987654",
            "E": "10.90",
            "F": "20.80",
            "G": "30.50",
            "Z": "2.5",
            "AB": "SKU-002",
            "AC": "Listed product",
            "AD": "BrandB",
            "AO": "12",
        },
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "")
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="马来西亚商品信息表2026" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        zf.writestr("xl/worksheets/sheet1.xml", _sheet_xml(rows))
        zf.writestr(
            "xl/styles.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<numFmts count="2">'
            '<numFmt numFmtId="176" formatCode="0.00_ "/>'
            '<numFmt numFmtId="182" formatCode="0_ "/>'
            '</numFmts>'
            '<cellXfs count="3">'
            '<xf numFmtId="0"/>'
            '<xf numFmtId="176" applyNumberFormat="1"/>'
            '<xf numFmtId="182" applyNumberFormat="1"/>'
            '</cellXfs>'
            '</styleSheet>',
        )


class CandidateSelectorTests(unittest.TestCase):
    def test_select_candidates_keeps_workbook_order_and_required_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "listing.xlsx"
            _write_minimal_workbook(workbook)

            result = select_candidates(
                store_name="Shopee-MY-Store-C",
                count=3,
                workbook_path=workbook,
                config_dir=ROOT / "config",
            )

        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertEqual(candidate.row, 2)
        self.assertEqual(candidate.sku_spec, "28g")
        self.assertEqual(candidate.price_1box, "9.90")
        self.assertEqual(candidate.price_2box, "18.80")
        self.assertEqual(candidate.price_3box, "27.50")
        self.assertEqual(candidate.sales_rank_15d_avg, "1.2")
        self.assertEqual(candidate.sku_code, "SKU-001")
        self.assertEqual(candidate.product_name, "Toothpaste")
        self.assertEqual(candidate.brand, "BrandA")
        self.assertEqual(candidate.overseas_available_stock, "88")
        self.assertEqual(candidate.package_weight_kg, "0.04")
        self.assertEqual(candidate.package_length_cm, "8")
        self.assertEqual(candidate.package_width_cm, "3")
        self.assertEqual(candidate.package_height_cm, "9")
        self.assertEqual(result.status_column, "B")
        self.assertEqual(result.total_unlisted, 1)

    def test_manual_sku_selects_matching_row_and_loads_its_workbook_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "listing.xlsx"
            _write_minimal_workbook(workbook)

            result = select_candidates(
                store_name="Shopee-MY-Store-C",
                count=1,
                workbook_path=workbook,
                config_dir=ROOT / "config",
                requested_sku_code=" sku-002 ",
            )

        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertEqual(candidate.row, 3)
        self.assertEqual(candidate.sku_code, "SKU-002")
        self.assertEqual(candidate.product_name, "Listed product")
        self.assertEqual(candidate.brand, "BrandB")
        self.assertEqual(candidate.price_1box, "10.90")
        self.assertEqual(candidate.overseas_available_stock, "12")


if __name__ == "__main__":
    unittest.main()
