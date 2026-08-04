from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.asset_inspector import (
    BUNDLED_7ZR_EXE,
    BUNDLED_UNRAR_EXE,
    _find_external_extractor,
    inspect_assets,
    normalize_asset_path,
)


class AssetInspectorTests(unittest.TestCase):
    def test_normalizes_invisible_windows_path_characters(self):
        raw = "\u202a\ufeffC:\\Users\\ExampleUser\\Desktop\\商品图包\u200b"

        self.assertEqual(
            normalize_asset_path(raw),
            "C:\\Users\\ExampleUser\\Desktop\\商品图包",
        )

    def test_inspector_accepts_path_with_invisible_prefix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            asset_dir = root / "商品图包"
            asset_dir.mkdir()
            (asset_dir / "主图1.jpg").write_bytes(b"main-image")

            manifest = inspect_assets(
                Path("\u202a" + str(asset_dir)),
                output_dir=root / "out",
            )

            self.assertEqual(manifest.source_path, str(asset_dir))
            self.assertEqual(len(manifest.main_images), 1)

    def test_portable_archive_extractors_are_bundled_and_preferred(self):
        self.assertTrue(BUNDLED_UNRAR_EXE.is_file())
        self.assertTrue(BUNDLED_7ZR_EXE.is_file())
        with patch("shutil.which", return_value=None):
            self.assertEqual(_find_external_extractor(".rar"), str(BUNDLED_UNRAR_EXE))
            self.assertEqual(_find_external_extractor(".7z"), str(BUNDLED_7ZR_EXE))

    def test_rar_is_extracted_through_the_local_archive_tool(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "assets.rar"
            archive.write_bytes(b"rar")

            def fake_extract(_source, target):
                main = target / "main"
                main.mkdir(parents=True)
                (main / "from-rar.jpg").write_bytes(b"image")

            with patch("shopee_listing_app.asset_inspector._run_external_extractor", side_effect=fake_extract):
                manifest = inspect_assets(archive, output_dir=Path(temp_dir) / "out")

        self.assertTrue(manifest.main_images[0].endswith("from-rar.jpg"))

    def test_preferred_version_one_is_selected_inside_combined_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "assets.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("version 1/main/use-v1.jpg", "x")
                zf.writestr("version 2/main/use-v2.jpg", "x")

            manifest = inspect_assets(
                archive,
                output_dir=Path(temp_dir) / "out",
                preferred_version="v1",
            )

        self.assertIn("version 1", manifest.selected_root)
        self.assertTrue(manifest.main_images[0].endswith("use-v1.jpg"))

    def test_zip_with_version_two_is_selected_and_unsafe_images_are_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "assets.zip"
            output_dir = Path(temp_dir) / "out"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("version 1/main/old.jpg", "x")
                zf.writestr("version 2/main/buyer-main.jpg", "x")
                zf.writestr("version 2/detail/oem-factory.jpg", "x")
                zf.writestr("version 2/video/demo.mp4", "x")

            manifest = inspect_assets(archive, output_dir=output_dir)

        self.assertIn("version 2", manifest.selected_root)
        self.assertEqual(len(manifest.main_images), 1)
        self.assertEqual(len(manifest.videos), 1)
        self.assertEqual(manifest.unsafe_images[0]["file"].endswith("oem-factory.jpg"), True)

    def test_preserves_all_main_and_detail_candidates_and_uses_sku_as_information_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "assets"
            for folder, names in {
                "主图": ["main1.jpg", "main2.jpg"],
                "详情图": [f"detail{i}.jpg" for i in range(10)],
                "sku": ["sku1.jpg", "sku2.jpg"],
            }.items():
                path = root / folder
                path.mkdir(parents=True)
                for name in names:
                    (path / name).write_bytes(name.encode("utf-8"))

            manifest = inspect_assets(root, output_dir=Path(temp_dir) / "out")

        self.assertEqual(len(manifest.main_images), 2)
        self.assertEqual(len(manifest.detail_images), 10)
        self.assertEqual(len(manifest.english_images), 0)
        self.assertEqual(len(manifest.sku_images), 2)
        self.assertEqual(len(manifest.information_images), 12)

    def test_english_parameter_folder_is_recognized_as_english_information(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "assets"
            english = root / "英文参数"
            english.mkdir(parents=True)
            image = english / "英文参数图.jpg"
            image.write_bytes(b"english-parameter-image")

            manifest = inspect_assets(root, output_dir=Path(temp_dir) / "out")

        self.assertEqual(manifest.english_images, [str(image)])
        self.assertEqual(manifest.parameter_images, [])
        self.assertIn(str(image), manifest.information_images)

    def test_duplicate_images_are_excluded_by_file_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "assets"
            main = root / "main"
            details = root / "detail"
            main.mkdir(parents=True)
            details.mkdir(parents=True)
            (main / "main.jpg").write_bytes(b"same-image-content")
            (details / "duplicate.jpg").write_bytes(b"same-image-content")
            (details / "unique.jpg").write_bytes(b"unique-image-content")

            manifest = inspect_assets(root, output_dir=Path(temp_dir) / "out")

        self.assertEqual(len(manifest.main_images), 1)
        self.assertEqual(len(manifest.detail_images), 1)
        self.assertTrue(manifest.detail_images[0].endswith("unique.jpg"))
        self.assertEqual(len(manifest.unsafe_images), 1)
        self.assertIn("duplicate image", manifest.unsafe_images[0]["reason"])

    def test_inner_archive_from_manual_folder_extracts_only_into_work_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "桌面素材目录"
            output_dir = root / "软件任务缓存"
            source.mkdir()
            inner_archive = source / "SKU_package_common.zip"
            with zipfile.ZipFile(inner_archive, "w") as zf:
                zf.writestr("主图/main.jpg", b"main-image")

            manifest = inspect_assets(source, output_dir=output_dir)

            selected_root = Path(manifest.selected_root)
            self.assertTrue(selected_root.is_relative_to(output_dir))
            self.assertFalse((source / "SKU_package_common").exists())
            self.assertEqual(len(manifest.main_images), 1)


if __name__ == "__main__":
    unittest.main()
