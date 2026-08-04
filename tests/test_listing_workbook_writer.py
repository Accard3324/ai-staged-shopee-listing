from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.listing_workbook_writer import (  # noqa: E402
    _WORKBOOK_WRITE_LOCK,
    ListingWorkbookUpdate,
    append_listing_record,
    sheet_for_store,
)
from shopee_listing_app.workbook_reader import cell_value, ns, read_shared_strings, workbook_sheets  # noqa: E402


TARGET_SHEETS = ["StoreBListings", "StoreAListings", "StoreCListings"]


def sheet_xml(last_row: int = 2) -> bytes:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:O{last_row}"/>
  <sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>商品ID</t></is></c><c r="E1" t="inlineStr"><is><t>SKU编码</t></is></c></row>
    <row r="{last_row}" ht="15.75" spans="1:5"><c r="A{last_row}" s="5"><v>111111</v></c><c r="E{last_row}" s="6" t="inlineStr"><is><t>OLD-SKU</t></is></c></row>
  </sheetData>
  <pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>
</worksheet>'''.encode("utf-8")


def create_workbook(
    path: Path,
    last_row: int = 2,
    first_sheet_xml: bytes | None = None,
    calc_pr: str = '<calcPr calcId="191029"/>',
) -> None:
    workbook_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="StoreBListings" sheetId="1" r:id="rId1"/>
    <sheet name="StoreAListings" sheetId="2" r:id="rId2"/>
    <sheet name="StoreCListings" sheetId="3" r:id="rId3"/>
  </sheets>
  {calc_pr}
</workbook>'''
    rels_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/>
</Relationships>'''
    with ZipFile(path, "w", ZIP_DEFLATED) as zf:
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        zf.writestr("xl/worksheets/sheet1.xml", first_sheet_xml or sheet_xml(last_row))
        zf.writestr("xl/worksheets/sheet2.xml", sheet_xml(last_row))
        zf.writestr("xl/worksheets/sheet3.xml", sheet_xml(last_row))
        zf.writestr("docProps/custom.bin", b"must stay unchanged")


def read_pair(path: Path, sheet_name: str, row_number: int) -> tuple[str, str, dict[str, str]]:
    with ZipFile(path) as zf:
        sheet_path = dict(workbook_sheets(zf))[sheet_name]
        root = ET.fromstring(zf.read(sheet_path))
        shared = read_shared_strings(zf)
        row = next(item for item in root.iter(ns("row")) if item.attrib.get("r") == str(row_number))
        values = {}
        attrs = {}
        for cell in row.findall(ns("c")):
            ref = cell.attrib["r"]
            values[ref[0]] = str(cell_value(cell, shared))
            attrs[ref[0]] = cell.attrib.get("s", "")
        return values.get("A", ""), values.get("E", ""), attrs


class ListingWorkbookWriterTests(unittest.TestCase):
    def test_required_store_names_map_to_their_target_sheets(self):
        self.assertEqual(sheet_for_store("Shopee-MY-Store-B"), "StoreBListings")
        self.assertEqual(sheet_for_store("Shopee-MY-Store-A"), "StoreAListings")
        self.assertEqual(sheet_for_store("Shopee-MY-Store-C"), "StoreCListings")

    def test_custom_store_uses_its_saved_listing_sheet(self):
        configured = type(
            "ConfiguredStores",
            (),
            {
                "aliases": {"my custom store": "my custom store"},
                "stores": {
                    "my custom store": type(
                        "Store",
                        (),
                        {"listing_sheet": "StoreAListings"},
                    )()
                },
            },
        )()
        with patch(
            "shopee_listing_app.listing_workbook_writer.load_app_config",
            return_value=configured,
        ):
            self.assertEqual(sheet_for_store("My Custom Store"), "StoreAListings")

    def test_append_uses_a_new_row_and_preserves_existing_data_and_other_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "【上架货品表】【马来】.xlsx"
            create_workbook(workbook, last_row=5)
            with ZipFile(workbook) as zf:
                untouched_before = zf.read("xl/worksheets/sheet2.xml")
                custom_before = zf.read("docProps/custom.bin")

            result = append_listing_record(
                workbook,
                store_name="Shopee-MY-Store-B",
                sku_code="NEW-SKU-001",
                product_id="52613167535",
            )

            self.assertTrue(result.appended)
            self.assertEqual(result.sheet_name, "StoreBListings")
            self.assertEqual(result.row_number, 6)
            self.assertEqual(read_pair(workbook, "StoreBListings", 5)[:2], ("111111", "OLD-SKU"))
            self.assertEqual(read_pair(workbook, "StoreBListings", 6)[:2], ("52613167535", "NEW-SKU-001"))
            self.assertEqual(read_pair(workbook, "StoreBListings", 6)[2], {"A": "5", "E": "6"})
            with ZipFile(workbook) as zf:
                self.assertEqual(zf.read("xl/worksheets/sheet2.xml"), untouched_before)
                self.assertEqual(zf.read("docProps/custom.bin"), custom_before)
                root = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
                self.assertEqual(root.find(ns("dimension")).attrib["ref"], "A1:O6")
                workbook_root = ET.fromstring(zf.read("xl/workbook.xml"))
                calc_pr = workbook_root.find(ns("calcPr"))
                self.assertEqual(
                    calc_pr.attrib,
                    {
                        "calcId": "0",
                        "calcMode": "auto",
                        "fullCalcOnLoad": "1",
                        "forceFullCalc": "1",
                    },
                )

    def test_missing_calculation_properties_are_added(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "workbook.xlsx"
            create_workbook(workbook, calc_pr="")

            append_listing_record(
                workbook,
                store_name="Shopee-MY-Store-B",
                sku_code="RECALC-SKU",
                product_id="52613167599",
            )

            with ZipFile(workbook) as zf:
                workbook_root = ET.fromstring(zf.read("xl/workbook.xml"))
            calc_pr = workbook_root.find(ns("calcPr"))
            self.assertIsNotNone(calc_pr)
            self.assertEqual(calc_pr.attrib["calcMode"], "auto")
            self.assertEqual(calc_pr.attrib["fullCalcOnLoad"], "1")
            self.assertEqual(calc_pr.attrib["forceFullCalc"], "1")

    def test_existing_record_still_repairs_recalculation_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "workbook.xlsx"
            create_workbook(workbook)

            result = append_listing_record(
                workbook,
                store_name="Shopee-MY-Store-B",
                sku_code="OLD-SKU",
                product_id="111111",
            )

            self.assertFalse(result.appended)
            with ZipFile(workbook) as zf:
                workbook_root = ET.fromstring(zf.read("xl/workbook.xml"))
            calc_pr = workbook_root.find(ns("calcPr"))
            self.assertEqual(calc_pr.attrib["calcMode"], "auto")
            self.assertEqual(calc_pr.attrib["fullCalcOnLoad"], "1")

    def test_same_product_and_sku_is_not_appended_twice(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "workbook.xlsx"
            create_workbook(workbook)
            first = append_listing_record(
                workbook,
                store_name="Shopee-MY-Store-A",
                sku_code="NEW-SKU-002",
                product_id="52613167536",
            )
            bytes_after_first = workbook.read_bytes()

            second = append_listing_record(
                workbook,
                store_name="Shopee-MY-Store-A",
                sku_code="NEW-SKU-002",
                product_id="52613167536",
            )

            self.assertTrue(first.appended)
            self.assertFalse(second.appended)
            self.assertEqual(second.row_number, first.row_number)
            self.assertEqual(workbook.read_bytes(), bytes_after_first)

    def test_unknown_store_and_blank_values_are_rejected_without_modifying_workbook(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "workbook.xlsx"
            create_workbook(workbook)
            original = workbook.read_bytes()

            with self.assertRaisesRegex(ValueError, "Unsupported store"):
                append_listing_record(workbook, "Unknown", "SKU", "123")
            with self.assertRaisesRegex(ValueError, "SKU"):
                append_listing_record(workbook, "Shopee-MY-Store-B", "", "123")
            with self.assertRaisesRegex(ValueError, "product ID"):
                append_listing_record(workbook, "Shopee-MY-Store-B", "SKU", "")

            self.assertEqual(workbook.read_bytes(), original)

    def test_complete_write_operation_is_serialized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "workbook.xlsx"
            create_workbook(workbook)
            completed = threading.Event()

            def write_record():
                append_listing_record(
                    workbook,
                    "Shopee-MY-Store-B",
                    "SERIAL-SKU",
                    "52613167537",
                )
                completed.set()

            _WORKBOOK_WRITE_LOCK.acquire()
            try:
                worker = threading.Thread(target=write_record)
                worker.start()
                self.assertFalse(completed.wait(0.05))
            finally:
                _WORKBOOK_WRITE_LOCK.release()

            worker.join(timeout=2)
            self.assertTrue(completed.is_set())
            self.assertEqual(read_pair(workbook, "StoreBListings", 3)[:2], ("52613167537", "SERIAL-SKU"))

    def test_excel_extension_namespaces_are_preserved_verbatim(self):
        complex_xml = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:x14ac="http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac" xmlns:xr="http://schemas.microsoft.com/office/spreadsheetml/2014/revision" mc:Ignorable="x14ac xr" xr:uid="{ABC}">
  <dimension ref="A1:O2"/><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>header</t></is></c></row><row r="2" x14ac:dyDescent="0.25"><c r="A2"><v>111111</v></c><c r="E2" t="inlineStr"><is><t>OLD-SKU</t></is></c></row></sheetData>
  <extLst><ext uri="keep-me"><x14ac:absPath url="D:\\data\\"/></ext></extLst>
</worksheet>'''
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "workbook.xlsx"
            create_workbook(workbook, first_sheet_xml=complex_xml)

            append_listing_record(
                workbook,
                "Shopee-MY-Store-B",
                "NEW-SKU",
                "52613167538",
            )

            with ZipFile(workbook) as zf:
                written = zf.read("xl/worksheets/sheet1.xml")
            self.assertIn(b'xmlns:x14ac="http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac"', written)
            self.assertIn(b'mc:Ignorable="x14ac xr"', written)
            self.assertIn(b'<x14ac:absPath url="D:\\data\\"/>', written)
            self.assertNotIn(b"ns1:", written)

    def test_replace_failure_keeps_original_bytes_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "workbook.xlsx"
            create_workbook(workbook)
            original = workbook.read_bytes()

            with patch(
                "shopee_listing_app.listing_workbook_writer.os.replace",
                side_effect=PermissionError("locked"),
            ), patch(
                "shopee_listing_app.listing_workbook_writer._append_to_open_workbook",
                return_value=None,
            ):
                with self.assertRaisesRegex(RuntimeError, "same permission level"):
                    append_listing_record(
                        workbook,
                        "Shopee-MY-Store-B",
                        "LOCKED-SKU",
                        "52613167539",
                    )

            self.assertEqual(workbook.read_bytes(), original)
            self.assertEqual(list(Path(temp_dir).glob("*.tmp.xlsx")), [])

    def test_locked_workbook_is_written_through_the_open_spreadsheet_and_saved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "workbook.xlsx"
            create_workbook(workbook)
            original = workbook.read_bytes()
            live_update = ListingWorkbookUpdate(
                workbook_path=str(workbook),
                sheet_name="StoreCListings",
                row_number=693,
                product_id="50814985445",
                sku_code="LA-B07-0075-01",
                appended=True,
                write_mode="open_workbook",
                spreadsheet_app="WPS 表格",
            )

            with patch(
                "shopee_listing_app.listing_workbook_writer._workbook_is_locked",
                return_value=True,
            ), patch(
                "shopee_listing_app.listing_workbook_writer._append_to_open_workbook",
                return_value=live_update,
            ) as live_writer:
                result = append_listing_record(
                    workbook,
                    "Shopee-MY-Store-C",
                    "LA-B07-0075-01",
                    "50814985445",
                )

            live_writer.assert_called_once_with(
                workbook,
                "StoreCListings",
                "LA-B07-0075-01",
                "50814985445",
            )
            self.assertEqual(result, live_update)
            self.assertEqual(result.to_dict()["write_mode"], "open_workbook")
            self.assertEqual(result.to_dict()["spreadsheet_app"], "WPS 表格")
            self.assertEqual(workbook.read_bytes(), original)

    def test_two_concurrent_records_are_both_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "workbook.xlsx"
            create_workbook(workbook)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(
                        append_listing_record,
                        workbook,
                        "Shopee-MY-Store-B",
                        f"CONCURRENT-SKU-{index}",
                        f"5261316754{index}",
                    )
                    for index in (0, 1)
                ]
                results = [future.result() for future in futures]

            self.assertEqual(sorted(result.row_number for result in results), [3, 4])
            pairs = {read_pair(workbook, "StoreBListings", row)[:2] for row in (3, 4)}
            self.assertEqual(
                pairs,
                {("52613167540", "CONCURRENT-SKU-0"), ("52613167541", "CONCURRENT-SKU-1")},
            )

    def test_external_change_during_rewrite_aborts_before_replace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "workbook.xlsx"
            create_workbook(workbook)
            original = workbook.read_bytes()

            with patch(
                "shopee_listing_app.listing_workbook_writer._file_signature",
                side_effect=[(100, 1, 1), (100, 2, 1)],
            ):
                with self.assertRaisesRegex(RuntimeError, "Another application modified"):
                    append_listing_record(
                        workbook,
                        "Shopee-MY-Store-B",
                        "CONFLICT-SKU",
                        "52613167542",
                    )

            self.assertEqual(workbook.read_bytes(), original)
            self.assertEqual(list(Path(temp_dir).glob("*.tmp.xlsx")), [])


if __name__ == "__main__":
    unittest.main()
