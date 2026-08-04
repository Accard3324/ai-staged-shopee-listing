from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Optional

from .ai_provider import get_ai_provider
from .asset_inspector import inspect_assets
from .candidate_selector import CandidateSKU, candidates_markdown, select_candidates
from .competitor_collector import collect_competitors, safe_filename
from .config_manager import PROJECT_ROOT, load_app_config
from .listing_builder import build_listing_draft
from .report_writer import ensure_output_dirs, timestamp, write_json, write_run_report
from .shopee.product_new_page import run_autofill_from_draft
from .ziniao_connector import discover_cdp_candidates


def main(argv: Optional[list[str]] = None) -> int:
    ensure_output_dirs(PROJECT_ROOT)
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001
        log_path = PROJECT_ROOT / "logs" / f"error_{timestamp()}.log"
        log_path.write_text(str(exc), encoding="utf-8")
        print(f"Run failed: {exc}", file=sys.stderr)
        print(f"Error log: {log_path}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Shopee automatic listing assistant")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("select-candidates", help="Select unlisted SKUs for a store")
    p.add_argument("--store", required=True)
    p.add_argument("--count", type=int, required=True)
    p.add_argument("--workbook")
    p.add_argument("--format", choices=["json", "md"], default="md")
    p.set_defaults(func=cmd_select_candidates)

    p = sub.add_parser("inspect-assets", help="Inspect an asset pack and generate asset_manifest.json")
    p.add_argument("--sku", required=True)
    p.add_argument("--asset-path", required=True)
    p.set_defaults(func=cmd_inspect_assets)

    p = sub.add_parser("collect-competitors", help="Load or cache competitor sources")
    p.add_argument("--sku", required=True)
    p.add_argument("--keyword", required=True)
    p.add_argument("--competitor-file")
    p.set_defaults(func=cmd_collect_competitors)

    p = sub.add_parser("generate-listing", help="Generate listing_draft.json from an SKU, assets, and competitors")
    p.add_argument("--store", required=True)
    p.add_argument("--candidate-json", required=True)
    p.add_argument("--asset-manifest", required=True)
    p.add_argument("--competitor-json")
    p.set_defaults(func=cmd_generate_listing)

    p = sub.add_parser("run", help="Run SKU selection, asset inspection, AI JSON, draft, and report generation")
    p.add_argument("--store", required=True)
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--asset-path")
    p.add_argument("--workbook")
    p.add_argument("--competitor-file")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("upload-draft", help="Reserved entry point for Shopee form filling")
    p.add_argument("--sku")
    p.add_argument("--draft")
    p.add_argument("--mode", choices=["dry_run", "fill_only", "save_delist"], default="dry_run")
    p.add_argument("--cdp-port", type=int)
    p.add_argument("--save-mode", choices=["delist"], default="delist")
    p.set_defaults(func=cmd_upload_draft)

    p = sub.add_parser("connect-ziniao", help="Discover Ziniao store-browser CDP ports")
    p.add_argument("--no-verify", action="store_true", help="Parse process command lines without requesting /json/version")
    p.set_defaults(func=cmd_connect_ziniao)

    return parser


def cmd_select_candidates(args: argparse.Namespace) -> int:
    result = select_candidates(
        store_name=args.store,
        count=args.count,
        workbook_path=Path(args.workbook) if args.workbook else None,
        config_dir=PROJECT_ROOT / "config",
    )
    out_path = PROJECT_ROOT / "outputs" / "candidates" / f"candidates_{timestamp()}.json"
    write_json(out_path, result.to_dict())
    if args.format == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(candidates_markdown(result))
    print(f"Candidate SKU file: {out_path}")
    return 0


def cmd_inspect_assets(args: argparse.Namespace) -> int:
    manifest = inspect_assets(Path(args.asset_path), PROJECT_ROOT / "outputs" / "asset_work" / safe_filename(args.sku))
    out_path = PROJECT_ROOT / "outputs" / "asset_manifests" / f"{safe_filename(args.sku)}_asset_manifest.json"
    write_json(out_path, manifest.to_dict())
    print(f"Asset inspection completed: {out_path}")
    return 0


def cmd_collect_competitors(args: argparse.Namespace) -> int:
    result = collect_competitors(
        sku_code=args.sku,
        keyword=args.keyword,
        cache_dir=PROJECT_ROOT / "outputs" / "competitor_sources",
        competitor_file=Path(args.competitor_file) if args.competitor_file else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_generate_listing(args: argparse.Namespace) -> int:
    config = load_app_config(PROJECT_ROOT / "config")
    store = config.store(args.store)
    candidate_payload = json.loads(Path(args.candidate_json).read_text(encoding="utf-8"))
    candidate = _candidate_from_payload(candidate_payload)
    asset_payload = json.loads(Path(args.asset_manifest).read_text(encoding="utf-8"))
    from .asset_inspector import AssetManifest

    asset_manifest = AssetManifest(**asset_payload)
    competitor_payload = (
        json.loads(Path(args.competitor_json).read_text(encoding="utf-8"))
        if args.competitor_json
        else {"sources": []}
    )
    provider = get_ai_provider(config.ai, PROJECT_ROOT / "prompts")
    ai_result = provider.generate_listing(candidate, asset_manifest, competitor_payload.get("sources", []))
    draft = build_listing_draft(
        candidate=candidate,
        store_name=store.name,
        template_key=store.template_key,
        description_template=config.description_template(store.template_key),
        asset_manifest=asset_manifest,
        competitors=competitor_payload.get("sources", []),
        ai_result=ai_result,
    )
    sku = safe_filename(str(candidate.sku_code))
    draft_path = PROJECT_ROOT / "outputs" / "listings" / f"{sku}_listing_draft.json"
    report_path = PROJECT_ROOT / "outputs" / "reports" / f"{sku}_report.md"
    write_json(draft_path, draft)
    write_run_report(report_path, draft)
    print(f"listing_draft.json：{draft_path}")
    print(f"Manual review report: {report_path}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = load_app_config(PROJECT_ROOT / "config")
    store = config.store(args.store)
    selection = select_candidates(
        store_name=args.store,
        count=args.count,
        workbook_path=Path(args.workbook) if args.workbook else None,
        config_dir=PROJECT_ROOT / "config",
    )
    if not selection.candidates:
        raise RuntimeError("No eligible unlisted SKU was found.")

    selection_path = PROJECT_ROOT / "outputs" / "candidates" / f"candidates_{timestamp()}.json"
    write_json(selection_path, selection.to_dict())
    print(f"Candidate SKU file: {selection_path}")

    for candidate in selection.candidates:
        sku = safe_filename(str(candidate.sku_code))
        asset_path = Path(args.asset_path) if args.asset_path else Path(input(_asset_prompt(candidate)).strip('" '))
        manifest = inspect_assets(asset_path, PROJECT_ROOT / "outputs" / "asset_work" / sku)
        manifest_path = PROJECT_ROOT / "outputs" / "asset_manifests" / f"{sku}_asset_manifest.json"
        write_json(manifest_path, manifest.to_dict())

        competitors = collect_competitors(
            sku_code=str(candidate.sku_code),
            keyword=f"{candidate.product_name} {candidate.sku_spec}",
            cache_dir=PROJECT_ROOT / "outputs" / "competitor_sources",
            competitor_file=Path(args.competitor_file) if args.competitor_file else None,
        )

        provider = get_ai_provider(config.ai, PROJECT_ROOT / "prompts")
        ai_result = provider.generate_listing(candidate, manifest, competitors.get("sources", []))
        draft = build_listing_draft(
            candidate=candidate,
            store_name=store.name,
            template_key=store.template_key,
            description_template=config.description_template(store.template_key),
            asset_manifest=manifest,
            competitors=competitors.get("sources", []),
            ai_result=ai_result,
        )
        draft_path = PROJECT_ROOT / "outputs" / "listings" / f"{sku}_listing_draft.json"
        report_path = PROJECT_ROOT / "outputs" / "reports" / f"{sku}_report.md"
        write_json(draft_path, draft)
        write_run_report(report_path, draft)
        print(f"SKU {candidate.sku_code} generated:")
        print(f"  listing_draft.json: {draft_path}")
        print(f"  Manual review report: {report_path}")
        return 0


def cmd_upload_draft(args: argparse.Namespace) -> int:
    draft_path = Path(args.draft) if args.draft else _draft_path_from_sku(args.sku)
    result = run_autofill_from_draft(draft_path, mode=args.mode, cdp_port=args.cdp_port)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


def cmd_connect_ziniao(args: argparse.Namespace) -> int:
    candidates = discover_cdp_candidates(verify=not args.no_verify)
    print(json.dumps([item.to_dict() for item in candidates], ensure_ascii=False, indent=2))
    if not candidates:
        print("No Ziniao store-browser CDP port was found. Start or switch to the target store in Ziniao first.")
    return 0


def _candidate_from_payload(payload: dict) -> CandidateSKU:
    if "candidates" in payload:
        if not payload["candidates"]:
            raise RuntimeError("candidate JSON has no candidates")
        payload = payload["candidates"][0]
    return CandidateSKU(**payload)


def _asset_prompt(candidate: CandidateSKU) -> str:
    return (
        f"Provide the local asset-pack archive or extracted folder for SKU {candidate.sku_code} "
        f"(variation: {candidate.sku_spec}; product: {candidate.product_name}; brand: {candidate.brand}): "
    )


def _draft_path_from_sku(sku: str | None) -> Path:
    listing_dir = PROJECT_ROOT / "outputs" / "listings"
    if sku:
        path = listing_dir / f"{safe_filename(str(sku))}_listing_draft.json"
        if path.exists():
            return path
        raise RuntimeError(f"No draft was found for the SKU: {path}")
    files = sorted(listing_dir.glob("*_listing_draft.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise RuntimeError("listing_draft.json was not found. Generate a listing draft first.")
    return files[0]
