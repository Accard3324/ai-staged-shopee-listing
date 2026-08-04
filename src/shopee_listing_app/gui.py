from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import threading
try:
    import tkinter as tk
    from tkinter import filedialog, ttk
except ModuleNotFoundError:
    tk = None
    filedialog = None
    ttk = None
from typing import Optional

from .ai_provider import get_ai_provider
from .asset_inspector import AssetManifest, inspect_assets
from .candidate_selector import CandidateSKU, CandidateSelectionResult, select_candidates
from .competitor_collector import collect_competitors, safe_filename
from .config_manager import PROJECT_ROOT, load_app_config
from .gui_state import build_initial_gui_state
from .listing_builder import build_listing_draft
from .report_writer import ensure_output_dirs, timestamp, write_json, write_run_report
from .ziniao_connector import discover_cdp_candidates


class ShopeeListingApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Shopee AI Listing Assistant")
        self.root.geometry("1080x760")
        self.config = load_app_config(PROJECT_ROOT / "config")
        state = build_initial_gui_state(PROJECT_ROOT / "config")

        self.store_var = tk.StringVar(value=state.stores[0] if state.stores else "")
        self.count_var = tk.StringVar(value="1")
        self.workbook_var = tk.StringVar(value=state.workbook_path)
        self.asset_path_var = tk.StringVar(value="")
        self.ai_provider_var = tk.StringVar(value=state.ai_provider)
        self.api_key_var = tk.StringVar(value=os.environ.get(self.config.ai.api_key_env, ""))
        self.ai_status_var = tk.StringVar(value=state.ai_status_text)

        self.sku_var = tk.StringVar(value="")
        self.product_name_var = tk.StringVar(value="")
        self.brand_var = tk.StringVar(value="")
        self.price_var = tk.StringVar(value="")
        self.stock_var = tk.StringVar(value="")
        self.title_var = tk.StringVar(value="")
        self.draft_path_var = tk.StringVar(value="")
        self.report_path_var = tk.StringVar(value="")

        self.selection: Optional[CandidateSelectionResult] = None
        self.current_candidate: Optional[CandidateSKU] = None
        self.asset_manifest: Optional[AssetManifest] = None
        self.competitors: dict[str, object] = {"sources": []}
        self.draft: Optional[dict[str, object]] = None

        ensure_output_dirs(PROJECT_ROOT)
        self._build_ui(state.stores)

    def _build_ui(self, stores: list[str]) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        settings = ttk.LabelFrame(outer, text="Basic Settings", padding=10)
        settings.pack(fill=tk.X)
        settings.columnconfigure(1, weight=1)

        ttk.Label(settings, text="Store").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Combobox(settings, textvariable=self.store_var, values=stores, state="readonly").grid(
            row=0, column=1, sticky=tk.EW, pady=4
        )
        ttk.Label(settings, text="Listing Count").grid(row=0, column=2, sticky=tk.W, padx=(12, 4))
        ttk.Entry(settings, textvariable=self.count_var, width=8).grid(row=0, column=3, sticky=tk.W)

        ttk.Label(settings, text="Product Workbook").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Entry(settings, textvariable=self.workbook_var).grid(row=1, column=1, sticky=tk.EW, pady=4)
        ttk.Button(settings, text="Choose Excel File", command=self.choose_workbook).grid(row=1, column=2, columnspan=2, sticky=tk.EW)

        ttk.Label(settings, text="Asset Pack").grid(row=2, column=0, sticky=tk.W, pady=4)
        ttk.Entry(settings, textvariable=self.asset_path_var).grid(row=2, column=1, sticky=tk.EW, pady=4)
        ttk.Button(settings, text="Choose ZIP", command=self.choose_asset_zip).grid(row=2, column=2, sticky=tk.EW)
        ttk.Button(settings, text="Choose Folder", command=self.choose_asset_folder).grid(row=2, column=3, sticky=tk.EW)

        ai = ttk.LabelFrame(outer, text="AI Configuration", padding=10)
        ai.pack(fill=tk.X, pady=(8, 0))
        ai.columnconfigure(1, weight=1)
        ttk.Label(ai, text="AI provider").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(ai, textvariable=self.ai_provider_var, width=18).grid(row=0, column=1, sticky=tk.W)
        ttk.Label(ai, text="API Key").grid(row=0, column=2, sticky=tk.W, padx=(12, 4))
        ttk.Entry(ai, textvariable=self.api_key_var, show="*", width=36).grid(row=0, column=3, sticky=tk.W)
        ttk.Label(ai, textvariable=self.ai_status_var, foreground="#a15c00").grid(row=1, column=0, columnspan=4, sticky=tk.W, pady=(6, 0))

        buttons = ttk.LabelFrame(outer, text="Actions", padding=10)
        buttons.pack(fill=tk.X, pady=(8, 0))
        labels = [
            ("1. Select Candidate SKU", self.select_candidates),
            ("2. Inspect Asset Pack", self.inspect_assets),
            ("3. Collect Competitors", self.collect_competitors),
            ("4. Generate Listing Draft", self.generate_listing),
            ("5. Open Output Folder", lambda: self.open_folder(PROJECT_ROOT / "outputs")),
            ("6. Open Log Folder", lambda: self.open_folder(PROJECT_ROOT / "logs")),
            ("7. Connect to Ziniao", self.connect_ziniao),
            ("8. Fill Shopee Form", self.auto_fill_shopee),
            ("9. Save and Delist", self.save_and_delist),
        ]
        for index, (label, command) in enumerate(labels):
            ttk.Button(buttons, text=label, command=command).grid(
                row=index // 3, column=index % 3, sticky=tk.EW, padx=4, pady=4
            )
            buttons.columnconfigure(index % 3, weight=1)

        results = ttk.LabelFrame(outer, text="Results", padding=10)
        results.pack(fill=tk.X, pady=(8, 0))
        results.columnconfigure(1, weight=1)
        result_rows = [
            ("SKU code", self.sku_var),
            ("Product Name", self.product_name_var),
            ("Brand", self.brand_var),
            ("Price E/F/G", self.price_var),
            ("AO Stock", self.stock_var),
            ("Generated Title", self.title_var),
            ("listing_draft.json", self.draft_path_var),
            ("Report Path", self.report_path_var),
        ]
        for row, (label, variable) in enumerate(result_rows):
            ttk.Label(results, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
            ttk.Entry(results, textvariable=variable).grid(row=row, column=1, sticky=tk.EW, pady=2)

        log_frame = ttk.LabelFrame(outer, text="Run Log", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.log_text = tk.Text(log_frame, height=14, wrap=tk.WORD)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log("Interface ready. Stage-one tools are available; Shopee form filling and Save and Delist remain planned for this legacy desktop interface.")

    def choose_workbook(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")])
        if path:
            self.workbook_var.set(path)

    def choose_asset_zip(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Zip files", "*.zip"), ("All files", "*.*")])
        if path:
            self.asset_path_var.set(path)

    def choose_asset_folder(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.asset_path_var.set(path)

    def select_candidates(self) -> None:
        self.run_task("Select Candidate SKU", self._select_candidates)

    def inspect_assets(self) -> None:
        self.run_task("Inspect Asset Pack", self._inspect_assets)

    def collect_competitors(self) -> None:
        self.run_task("Collect Competitors", self._collect_competitors)

    def generate_listing(self) -> None:
        self.run_task("Generate Listing Draft", self._generate_listing)

    def connect_ziniao(self) -> None:
        self.run_task("Connect to Ziniao", self._connect_ziniao)

    def auto_fill_shopee(self) -> None:
        self.run_task("Fill Shopee Form", self._auto_fill_shopee)

    def save_and_delist(self) -> None:
        self.run_task("Save and Delist", self._save_and_delist)

    def _select_candidates(self) -> None:
        count = int(self.count_var.get())
        self.selection = select_candidates(
            store_name=self.store_var.get(),
            count=count,
            workbook_path=Path(self.workbook_var.get()),
            config_dir=PROJECT_ROOT / "config",
        )
        if not self.selection.candidates:
            raise RuntimeError("No unlisted SKU was found.")
        self.current_candidate = self.selection.candidates[0]
        out_path = PROJECT_ROOT / "outputs" / "candidates" / f"gui_candidates_{timestamp()}.json"
        write_json(out_path, self.selection.to_dict())
        self._show_candidate(self.current_candidate)
        self.log_success(f"Candidate SKU selected: {self.current_candidate.sku_code}")
        self.log(f"Candidate file: {out_path}")

    def _inspect_assets(self) -> None:
        candidate = self._require_candidate()
        asset_path = self.asset_path_var.get().strip()
        if not asset_path:
            raise RuntimeError("Choose an asset-pack ZIP or folder first.")
        sku = safe_filename(str(candidate.sku_code))
        self.asset_manifest = inspect_assets(Path(asset_path), PROJECT_ROOT / "outputs" / "asset_work" / sku)
        manifest_path = PROJECT_ROOT / "outputs" / "asset_manifests" / f"{sku}_asset_manifest.json"
        write_json(manifest_path, self.asset_manifest.to_dict())
        self.log_success("Asset-pack inspection completed")
        self.log(f"Asset manifest: {manifest_path}")

    def _collect_competitors(self) -> None:
        candidate = self._require_candidate()
        self.competitors = collect_competitors(
            sku_code=str(candidate.sku_code),
            keyword=f"{candidate.product_name} {candidate.sku_spec}",
            cache_dir=PROJECT_ROOT / "outputs" / "competitor_sources",
        )
        warnings = self.competitors.get("warnings", [])
        self.log_success("Competitor-cache step completed")
        if warnings:
            self.log("Warnings: " + "; ".join(str(item) for item in warnings))

    def _generate_listing(self) -> None:
        candidate = self._require_candidate()
        if not self.asset_manifest:
            self._inspect_assets()
        if not self.competitors.get("sources"):
            self._collect_competitors()
        if self.api_key_var.get().strip():
            os.environ[self.config.ai.api_key_env] = self.api_key_var.get().strip()

        store = self.config.store(self.store_var.get())
        provider = get_ai_provider(self.config.ai, PROJECT_ROOT / "prompts")
        ai_result = provider.generate_listing(candidate, self.asset_manifest, self.competitors.get("sources", []))
        self.draft = build_listing_draft(
            candidate=candidate,
            store_name=store.name,
            template_key=store.template_key,
            description_template=self.config.description_template(store.template_key),
            asset_manifest=self.asset_manifest,
            competitors=self.competitors.get("sources", []),
            ai_result=ai_result,
        )
        sku = safe_filename(str(candidate.sku_code))
        draft_path = PROJECT_ROOT / "outputs" / "listings" / f"{sku}_listing_draft.json"
        report_path = PROJECT_ROOT / "outputs" / "reports" / f"{sku}_report.md"
        write_json(draft_path, self.draft)
        write_run_report(report_path, self.draft)
        self.title_var.set(str(self.draft["listing"]["title"]))
        self.draft_path_var.set(str(draft_path))
        self.report_path_var.set(str(report_path))
        self.log_success("Listing draft generated")
        self.log(f"listing_draft.json：{draft_path}")
        self.log(f"Report: {report_path}")

    def _connect_ziniao(self) -> None:
        candidates = discover_cdp_candidates(verify=True)
        if not candidates:
            self.log("No verified Ziniao store-browser CDP port was found. Start or switch to the target store in Ziniao first.")
            return
        for item in candidates:
            self.log_success(f"CDP port found: {item.port}; process: {item.name}; browser: {item.browser}")

    def _auto_fill_shopee(self) -> None:
        draft_path = self.draft_path_var.get().strip()
        if not draft_path:
            raise RuntimeError("Generate listing_draft.json first.")
        if not Path(draft_path).exists():
            raise RuntimeError(f"Draft file not found: {draft_path}")
        self.log("Draft loaded. Automated Shopee form filling remains planned for this legacy desktop interface.")

    def _save_and_delist(self) -> None:
        self.log("Save and Delist remains a planned entry point in this legacy desktop interface and does not click Shopee.")

    def _show_candidate(self, candidate: CandidateSKU) -> None:
        self.sku_var.set(str(candidate.sku_code))
        self.product_name_var.set(str(candidate.product_name))
        self.brand_var.set(str(candidate.brand))
        self.price_var.set(f"{candidate.price_1box} / {candidate.price_2box} / {candidate.price_3box}")
        self.stock_var.set(str(candidate.overseas_available_stock))

    def _require_candidate(self) -> CandidateSKU:
        if not self.current_candidate:
            self._select_candidates()
        if not self.current_candidate:
            raise RuntimeError("Select a candidate SKU first.")
        return self.current_candidate

    def run_task(self, label: str, func) -> None:
        def worker() -> None:
            try:
                self.log(f"Started: {label}")
                func()
            except Exception as exc:  # noqa: BLE001
                self.handle_error(label, exc)

        threading.Thread(target=worker, daemon=True).start()

    def handle_error(self, label: str, exc: Exception) -> None:
        log_path = PROJECT_ROOT / "logs" / f"gui_error_{timestamp()}.log"
        log_path.write_text(f"{label} failed: {exc}", encoding="utf-8")
        self.log_error(f"{label} failed: {exc}")
        self.log_error(f"Failure log: {log_path}")

    def log(self, message: str) -> None:
        self.root.after(0, lambda: self._append_log(message, ""))

    def log_success(self, message: str) -> None:
        self.root.after(0, lambda: self._append_log("Success: " + message, "success"))

    def log_error(self, message: str) -> None:
        self.root.after(0, lambda: self._append_log("Failure: " + message, "error"))

    def _append_log(self, message: str, tag: str) -> None:
        self.log_text.tag_config("success", foreground="#0a7f29")
        self.log_text.tag_config("error", foreground="#b00020")
        self.log_text.insert(tk.END, message + "\n", tag)
        self.log_text.see(tk.END)

    def open_folder(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            self.handle_error("Open Folder", exc)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Shopee AI Listing Assistant GUI")
    parser.add_argument("--check", action="store_true", help="Only verify that the GUI module can be imported")
    args = parser.parse_args(argv)
    if tk is None:
        from .web_gui import main as web_main

        return web_main(argv)
    if args.check:
        build_initial_gui_state(PROJECT_ROOT / "config")
        print("GUI check OK")
        return 0

    root = tk.Tk()
    ShopeeListingApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
