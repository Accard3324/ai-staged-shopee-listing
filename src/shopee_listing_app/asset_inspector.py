from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Dict, List, Optional
import unicodedata
import zipfile

from .config_manager import PROJECT_ROOT


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z"}
UNSAFE_IMAGE_WORDS = ["oem", "odm"]
BUNDLED_UNRAR_DIR = PROJECT_ROOT / "tools" / "archive" / "unrar" / "windows-amd64"
BUNDLED_UNRAR_EXE = BUNDLED_UNRAR_DIR / "UnRAR.exe"
BUNDLED_UNRAR_METADATA = BUNDLED_UNRAR_DIR / "UnRAR.json"
BUNDLED_7ZR_DIR = PROJECT_ROOT / "tools" / "archive" / "7zip" / "windows"
BUNDLED_7ZR_EXE = BUNDLED_7ZR_DIR / "7zr.exe"
BUNDLED_7ZR_METADATA = BUNDLED_7ZR_DIR / "7zr.json"


@dataclass(frozen=True)
class AssetManifest:
    source_path: str
    extracted_root: str
    selected_root: str
    main_images: List[str] = field(default_factory=list)
    detail_images: List[str] = field(default_factory=list)
    english_images: List[str] = field(default_factory=list)
    parameter_images: List[str] = field(default_factory=list)
    sku_images: List[str] = field(default_factory=list)
    information_images: List[str] = field(default_factory=list)
    videos: List[str] = field(default_factory=list)
    unsafe_images: List[Dict[str, str]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def inspect_assets(
    asset_path: Path,
    output_dir: Optional[Path] = None,
    preferred_version: str = "v2",
) -> AssetManifest:
    source = Path(normalize_asset_path(asset_path))
    if not source.exists():
        raise RuntimeError(f"Asset path not found: {source}")

    work_dir = Path(output_dir) if output_dir else Path("outputs") / "asset_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    warnings: List[str] = []
    if source.is_file():
        if source.suffix.lower() not in ARCHIVE_EXTENSIONS:
            raise RuntimeError("The asset pack must be a .zip, .rar, or .7z archive, or an extracted folder.")
        extracted_root = _extract_archive_to_unique_dir(source, work_dir)
    else:
        extracted_root = source

    selected_root = _select_version_root(extracted_root, preferred_version)
    selected_root, inner_warnings = _extract_inner_zip_if_present(
        selected_root,
        work_dir,
    )
    selected_root = _select_version_root(selected_root, preferred_version)
    warnings.extend(inner_warnings)

    main_images: List[str] = []
    detail_images: List[str] = []
    english_images: List[str] = []
    parameter_images: List[str] = []
    sku_images: List[str] = []
    videos: List[str] = []
    unsafe_images: List[Dict[str, str]] = []
    seen_image_hashes: Dict[str, str] = {}

    files = [path for path in selected_root.rglob("*") if path.is_file()]
    for file_path in sorted(
        files,
        key=lambda path: _asset_inspection_order(path, selected_root),
    ):
        suffix = file_path.suffix.lower()
        rel = str(file_path.relative_to(selected_root))
        name_key = rel.lower()
        if suffix in IMAGE_EXTENSIONS:
            if _is_unsafe_image_name(name_key):
                unsafe_images.append({"file": str(file_path), "reason": "OEM/ODM text in filename/path"})
                continue
            digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
            if digest in seen_image_hashes:
                unsafe_images.append(
                    {
                        "file": str(file_path),
                        "reason": f"duplicate image; kept: {seen_image_hashes[digest]}",
                    }
                )
                continue
            seen_image_hashes[digest] = str(file_path)
            if any(token in name_key for token in ["sku", "规格", "sku图"]):
                sku_images.append(str(file_path))
            elif any(
                token in name_key
                for token in [
                    "英文素材",
                    "英文参数",
                    "english material",
                    "english_material",
                    "english parameter",
                    "english_parameter",
                ]
            ):
                english_images.append(str(file_path))
            elif any(token in name_key for token in ["详情图", "详情页", "detail"]):
                detail_images.append(str(file_path))
            elif any(token in name_key for token in ["param", "spec", "参数", "规格参数"]):
                parameter_images.append(str(file_path))
            elif any(token in name_key for token in ["main", "主图", "cover"]):
                main_images.append(str(file_path))
            else:
                detail_images.append(str(file_path))
        elif suffix in VIDEO_EXTENSIONS:
            videos.append(str(file_path))
        elif suffix in {".rar", ".7z"}:
            warnings.append(f"Inner archive needs manual extraction: {file_path}")

    if not main_images and detail_images:
        main_images.append(detail_images.pop(0))
        warnings.append("No explicit main image folder found; first detail image was used as main image candidate.")

    if len(main_images) + len(detail_images) > 9:
        warnings.append("More than 9 image candidates were preserved; final selection must use 1 main image and at most 8 detail images.")

    information_images = list(
        dict.fromkeys([*detail_images, *english_images, *parameter_images, *sku_images])
    )

    return AssetManifest(
        source_path=str(source),
        extracted_root=str(extracted_root),
        selected_root=str(selected_root),
        main_images=main_images,
        detail_images=detail_images,
        english_images=english_images,
        parameter_images=parameter_images,
        sku_images=sku_images,
        information_images=information_images,
        videos=videos,
        unsafe_images=unsafe_images,
        warnings=warnings,
    )


def normalize_asset_path(value: object) -> str:
    """Clean invisible formatting characters commonly introduced by Windows copy/paste."""
    text = str(value or "").strip().strip("\"'")
    return "".join(character for character in text if unicodedata.category(character) != "Cf").strip()


def _extract_zip_to_unique_dir(archive: Path, output_dir: Path) -> Path:
    target = _unique_extract_target(output_dir, archive.stem)
    target.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(target)
    return target


def _extract_archive_to_unique_dir(archive: Path, output_dir: Path) -> Path:
    if archive.suffix.lower() == ".zip":
        return _extract_zip_to_unique_dir(archive, output_dir)
    target = _unique_extract_target(output_dir, archive.stem)
    target.mkdir(parents=True, exist_ok=False)
    _run_external_extractor(archive, target)
    return target


def _run_external_extractor(archive: Path, target: Path) -> None:
    suffix = archive.suffix.lower()
    extractor = _find_external_extractor(suffix)
    if not extractor:
        raise RuntimeError(f"Unable to extract {suffix} automatically. Install 7-Zip or WinRAR and try again.")
    name = Path(extractor).name.lower()
    if name == "unrar.exe" or name == "unrar":
        command = [extractor, "x", "-y", "-idq", str(archive), str(target) + "\\"]
    elif name.startswith("7z"):
        command = [extractor, "x", "-y", f"-o{target}", str(archive)]
    else:
        command = [extractor, "x", "-ibck", "-inul", "-o+", str(archive), str(target) + "\\"]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        timeout=180,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Asset-pack extraction failed: {archive.name} (exit code {completed.returncode})")


def _find_external_extractor(suffix: str) -> str:
    if suffix == ".rar" and (BUNDLED_UNRAR_EXE.exists() or BUNDLED_UNRAR_METADATA.exists()):
        return _verify_bundled_unrar()
    if suffix == ".7z" and (BUNDLED_7ZR_EXE.exists() or BUNDLED_7ZR_METADATA.exists()):
        return _verify_bundled_7zr()
    names = ["7z.exe", "7zz.exe", "7z", "7zz"]
    common_paths = [Path("C:/Program Files/7-Zip/7z.exe")]
    if suffix == ".rar":
        names = ["UnRAR.exe", "unrar", *names]
        common_paths = [Path("C:/Program Files/WinRAR/UnRAR.exe"), *common_paths]
    else:
        names.extend(["WinRAR.exe"])
        common_paths.append(Path("C:/Program Files/WinRAR/WinRAR.exe"))
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for path in common_paths:
        if path.is_file():
            return str(path)
    return ""


def _verify_bundled_unrar() -> str:
    if not BUNDLED_UNRAR_EXE.is_file() or not BUNDLED_UNRAR_METADATA.is_file():
        raise RuntimeError("The application is incomplete: the bundled RAR extraction component is missing.")
    try:
        metadata = json.loads(BUNDLED_UNRAR_METADATA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Bundled RAR extraction metadata is damaged. Copy a complete application package again.") from exc
    expected_size = int(metadata.get("size") or 0)
    expected_hash = str(metadata.get("sha256") or "").strip().lower()
    if BUNDLED_UNRAR_EXE.stat().st_size != expected_size or len(expected_hash) != 64:
        raise RuntimeError("The bundled RAR extraction component is damaged. Copy a complete application package again.")
    digest = hashlib.sha256(BUNDLED_UNRAR_EXE.read_bytes()).hexdigest()
    if digest != expected_hash:
        raise RuntimeError("The bundled RAR extraction component is damaged. Copy a complete application package again.")
    return str(BUNDLED_UNRAR_EXE)


def _verify_bundled_7zr() -> str:
    if not BUNDLED_7ZR_EXE.is_file() or not BUNDLED_7ZR_METADATA.is_file():
        raise RuntimeError("The application is incomplete: the bundled 7Z extraction component is missing.")
    try:
        metadata = json.loads(BUNDLED_7ZR_METADATA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Bundled 7Z extraction metadata is damaged. Copy a complete application package again.") from exc
    expected_size = int(metadata.get("size") or 0)
    expected_hash = str(metadata.get("sha256") or "").strip().lower()
    if BUNDLED_7ZR_EXE.stat().st_size != expected_size or len(expected_hash) != 64:
        raise RuntimeError("The bundled 7Z extraction component is damaged. Copy a complete application package again.")
    digest = hashlib.sha256(BUNDLED_7ZR_EXE.read_bytes()).hexdigest()
    if digest != expected_hash:
        raise RuntimeError("The bundled 7Z extraction component is damaged. Copy a complete application package again.")
    return str(BUNDLED_7ZR_EXE)


def _unique_extract_target(output_dir: Path, stem: str) -> Path:
    target = output_dir / stem
    index = 1
    while target.exists():
        target = output_dir / f"{stem}_{int(time.time())}_{index}"
        index += 1
    return target


def _select_version_root(root: Path, preferred_version: str = "v2") -> Path:
    directories = [path for path in root.iterdir() if path.is_dir()]
    versions = {
        "v1": [path for path in directories if re.search(r"(?:\bversion\s*1\b|\bv1\b|版本\s*1)", path.name, re.I)],
        "v2": [path for path in directories if re.search(r"(?:\bversion\s*2\b|\bv2\b|版本\s*2)", path.name, re.I)],
    }
    preferred = preferred_version if preferred_version in versions else "v2"
    fallback = "v1" if preferred == "v2" else "v2"
    if versions[preferred]:
        return sorted(versions[preferred])[-1]
    if versions[fallback]:
        return sorted(versions[fallback])[-1]
    return root


def _extract_inner_zip_if_present(
    root: Path,
    output_dir: Optional[Path] = None,
) -> tuple[Path, List[str]]:
    warnings: List[str] = []
    inner_archives = [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in ARCHIVE_EXTENSIONS]
    if not inner_archives:
        return root, warnings
    archive = sorted(inner_archives)[0]
    extraction_root = Path(output_dir) if output_dir else archive.parent
    extraction_root.mkdir(parents=True, exist_ok=True)
    target = _extract_archive_to_unique_dir(archive, extraction_root)
    warnings.append(f"Inner archive extracted before inspection: {archive}")
    return target, warnings


def _is_unsafe_image_name(name_key: str) -> bool:
    return any(word.lower() in name_key for word in UNSAFE_IMAGE_WORDS)


def _asset_inspection_order(file_path: Path, root: Path) -> tuple[int, str]:
    """Keep the main-image copy when identical files occur in multiple folders."""
    name_key = str(file_path.relative_to(root)).lower()
    if file_path.suffix.lower() not in IMAGE_EXTENSIONS:
        return 10, name_key
    if any(token in name_key for token in ["sku", "规格", "sku图"]):
        return 4, name_key
    if any(token in name_key for token in ["英文素材", "english material", "english_material"]):
        return 3, name_key
    if any(token in name_key for token in ["详情图", "详情页", "detail"]):
        return 1, name_key
    if any(token in name_key for token in ["param", "spec", "参数", "规格参数"]):
        return 3, name_key
    if any(token in name_key for token in ["main", "主图", "cover"]):
        return 0, name_key
    return 2, name_key
