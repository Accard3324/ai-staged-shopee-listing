from __future__ import annotations

from html import escape
import json
import os

from .ai_provider import (
    AGNES_VISION_DEFAULT_MODEL,
    AI_EXECUTION_MODE_MULTIMODAL,
    AI_EXECUTION_MODE_VISION_TEXT,
    AI_MODEL_LABELS,
    MULTIMODAL_AI_MODELS,
    NVIDIA_MINIMAX_VISION_MODEL,
    NVIDIA_TEXT_DEFAULT_MODEL,
    NVIDIA_VISION_DEFAULT_MODEL,
    OPENAI_DEFAULT_MODEL,
    VISION_TEXT_AI_MODELS,
    model_reasoning_profile,
)
from .config_manager import PROJECT_ROOT, load_app_config
from .gui_state import GuiInitialState
from .prompt_config import DEFAULT_PROMPTS, load_prompt_config, parse_seo_keyword_count, seo_keyword_count_text


WORKFLOW_STEP_TITLES = (
    "Configuration",
    "Select SKU",
    "Load Asset Pack",
    "Analyze Images",
    "Confirm Listing Images",
    "Generate Search Terms",
    "Analyze Competitor Titles",
    "Generate Description",
    "Build Listing Draft",
    "Connect to Shopee",
    "Fill Shopee Step 1",
    "Fill Shopee Step 2",
    "Run Checklist",
    "Save and Delist",
    "Review Results",
    "Write Back to Workbook",
)


def build_linear_home_html(
    state: GuiInitialState,
    task_context: dict[str, object] | None = None,
) -> str:
    task_context = dict(task_context or {})
    task_id = str(task_context.get("task_id", "") or "")
    multi_group_id = str(task_context.get("multi_group_id", "") or "")
    multi_slot = int(task_context.get("multi_slot", 0) or 0)
    multi_count = int(task_context.get("multi_count", 0) or 0)
    multi_active = bool(task_id and multi_group_id and multi_slot and multi_count)
    multi_button_label = "Close Multi-Store Mode" if multi_active else "Multi-Store Mode"
    multi_header_text = (
        f"Multi-store task {multi_slot}/{multi_count} | Complete each step in order"
        if multi_active
        else "Complete each step in order"
    )
    task_context_json = json.dumps(
        {
            "task_id": task_id,
            "multi_group_id": multi_group_id,
            "multi_slot": multi_slot,
            "multi_count": multi_count,
            "active": multi_active,
        },
        ensure_ascii=False,
    )
    sidebar_step_links = "".join(
        (
            f'<button type="button" class="sidebar-step-button" data-sidebar-step="{number}" '
            f'onclick="goToWorkflowStep({number})">Step {number}: {escape(title)}</button>'
        )
        for number, title in enumerate(WORKFLOW_STEP_TITLES)
    )
    prompts = load_prompt_config(PROJECT_ROOT / "config" / "prompts.yaml")
    store_options = '<option value="" selected>Select a store</option>\n' + "\n".join(
        f'<option value="{escape(name)}">{escape(name)}</option>' for name in state.stores
    )
    app_config = load_app_config(PROJECT_ROOT / "config")
    try:
        full_workflow_auto_retry_count = int(
            os.environ.get("FULL_WORKFLOW_AUTO_RETRY_COUNT", "1")
        )
    except ValueError:
        full_workflow_auto_retry_count = 1
    full_workflow_auto_retry_count = min(
        5, max(1, full_workflow_auto_retry_count)
    )
    full_workflow_auto_retry_options = "".join(
        f'<option value="{count}"'
        f'{" selected" if count == full_workflow_auto_retry_count else ""}>'
        f"{count}</option>"
        for count in range(1, 6)
    )
    initial_store_name = ""
    initial_template_key = ""
    initial_template = ""
    if initial_store_name:
        try:
            initial_store = app_config.store(initial_store_name)
            initial_template_key = initial_store.template_key
            initial_template = app_config.description_template(initial_store.template_key)
        except KeyError:
            initial_template_key = ""
            initial_template = ""
    execution_mode = os.environ.get(
        "AI_EXECUTION_MODE",
        AI_EXECUTION_MODE_MULTIMODAL,
    ).strip().lower()
    if execution_mode not in {
        AI_EXECUTION_MODE_VISION_TEXT,
        AI_EXECUTION_MODE_MULTIMODAL,
    }:
        execution_mode = AI_EXECUTION_MODE_MULTIMODAL
    execution_mode_selected = {
        mode: " selected" if execution_mode == mode else ""
        for mode in (
            AI_EXECUTION_MODE_VISION_TEXT,
            AI_EXECUTION_MODE_MULTIMODAL,
        )
    }
    def saved_model(
        new_env_key: str,
        legacy_env_key: str,
        default_model: str,
    ) -> str:
        value = str(
            os.environ.get(new_env_key)
            or os.environ.get(legacy_env_key)
            or default_model
        ).strip().lower()
        aliases = {
            "agnes": AGNES_VISION_DEFAULT_MODEL,
            "glm": NVIDIA_TEXT_DEFAULT_MODEL,
            "glm-5.2": NVIDIA_TEXT_DEFAULT_MODEL,
            "m3": NVIDIA_MINIMAX_VISION_MODEL,
            "qwen": NVIDIA_VISION_DEFAULT_MODEL,
        }
        value = aliases.get(value, value)
        return value if value in VISION_TEXT_AI_MODELS else default_model

    vision_model = saved_model(
        "STEP3_AI_MODEL",
        "NVIDIA_VISION_MODEL",
        OPENAI_DEFAULT_MODEL,
    )
    if vision_model not in MULTIMODAL_AI_MODELS:
        vision_model = OPENAI_DEFAULT_MODEL
    step5_text_model = saved_model(
        "STEP5_AI_MODEL",
        "STEP5_TEXT_MODEL",
        OPENAI_DEFAULT_MODEL,
    )
    step6_text_model = saved_model(
        "STEP6_AI_MODEL",
        "STEP6_TEXT_MODEL",
        OPENAI_DEFAULT_MODEL,
    )
    step7_text_model = saved_model(
        "STEP7_AI_MODEL",
        "STEP7_TEXT_MODEL",
        OPENAI_DEFAULT_MODEL,
    )
    if execution_mode == AI_EXECUTION_MODE_MULTIMODAL:
        if step5_text_model not in MULTIMODAL_AI_MODELS:
            step5_text_model = OPENAI_DEFAULT_MODEL
        if step6_text_model not in MULTIMODAL_AI_MODELS:
            step6_text_model = OPENAI_DEFAULT_MODEL
        if step7_text_model not in MULTIMODAL_AI_MODELS:
            step7_text_model = OPENAI_DEFAULT_MODEL
    step_text_models = (
        MULTIMODAL_AI_MODELS
        if execution_mode == AI_EXECUTION_MODE_MULTIMODAL
        else VISION_TEXT_AI_MODELS
    )

    def render_model_options(
        selected_model: str,
        models: tuple[str, ...],
    ) -> str:
        return "".join(
            (
                f'<option value="{escape(model)}"'
                f'{" selected" if model == selected_model else ""}>'
                f"{escape(AI_MODEL_LABELS[model])}</option>"
            )
            for model in models
        )

    step3_model_options = render_model_options(
        vision_model,
        MULTIMODAL_AI_MODELS,
    )
    step5_model_options = render_model_options(step5_text_model, step_text_models)
    step6_model_options = render_model_options(step6_text_model, step_text_models)
    step7_model_options = render_model_options(step7_text_model, step_text_models)
    reasoning_profile_json = json.dumps(
        {
            model: {
                "label": AI_MODEL_LABELS[model],
                "vision": model_reasoning_profile(model, "vision"),
                "text": model_reasoning_profile(model, "text"),
            }
            for model in VISION_TEXT_AI_MODELS
        },
        ensure_ascii=False,
    )
    vision_thinking_mode = os.environ.get(
        "STEP3_THINKING_MODE",
        os.environ.get("NVIDIA_VISION_THINKING_MODE", "official_default"),
    ).strip().lower()
    if vision_thinking_mode in {"default", "model_default"}:
        vision_thinking_mode = "official_default"
    if vision_thinking_mode not in {"official_default", "adaptive", "enabled", "disabled"}:
        vision_thinking_mode = "official_default"
    vision_thinking_selected = {
        value: " selected" if vision_thinking_mode == value else ""
        for value in ("official_default", "adaptive", "enabled", "disabled")
    }
    vision_reasoning_strength = os.environ.get(
        "STEP3_REASONING_STRENGTH",
        os.environ.get("NVIDIA_VISION_REASONING_STRENGTH", "official_default"),
    ).strip().lower()
    if vision_reasoning_strength in {"default", "model_default"}:
        vision_reasoning_strength = "official_default"
    if vision_reasoning_strength not in {"official_default", "low", "medium", "high", "maximum"}:
        vision_reasoning_strength = "official_default"
    vision_strength_selected = {
        value: " selected" if vision_reasoning_strength == value else ""
        for value in ("official_default", "low", "medium", "high", "maximum")
    }
    step5_thinking_mode = os.environ.get(
        "STEP5_THINKING_MODE",
        os.environ.get("STEP5_TEXT_THINKING_MODE", "official_default"),
    ).strip().lower()
    if step5_thinking_mode not in {"official_default", "enabled", "disabled"}:
        step5_thinking_mode = "official_default"
    step6_thinking_mode = os.environ.get(
        "STEP6_THINKING_MODE",
        os.environ.get("STEP6_TEXT_THINKING_MODE", "official_default"),
    ).strip().lower()
    if step6_thinking_mode not in {"official_default", "enabled", "disabled"}:
        step6_thinking_mode = "official_default"
    step7_thinking_mode = os.environ.get(
        "STEP7_THINKING_MODE",
        os.environ.get("STEP7_TEXT_THINKING_MODE", "official_default"),
    ).strip().lower()
    if step7_thinking_mode not in {"official_default", "enabled", "disabled"}:
        step7_thinking_mode = "official_default"
    step5_reasoning_strength = os.environ.get(
        "STEP5_REASONING_STRENGTH",
        os.environ.get("STEP5_TEXT_REASONING_STRENGTH", "maximum"),
    ).strip().lower()
    if step5_reasoning_strength not in {"official_default", "low", "medium", "high", "maximum"}:
        step5_reasoning_strength = "maximum"
    step6_reasoning_strength = os.environ.get(
        "STEP6_REASONING_STRENGTH",
        os.environ.get("STEP6_TEXT_REASONING_STRENGTH", "maximum"),
    ).strip().lower()
    if step6_reasoning_strength not in {"official_default", "low", "medium", "high", "maximum"}:
        step6_reasoning_strength = "maximum"
    step7_reasoning_strength = os.environ.get(
        "STEP7_REASONING_STRENGTH",
        os.environ.get("STEP7_TEXT_REASONING_STRENGTH", "maximum"),
    ).strip().lower()
    if step7_reasoning_strength not in {"official_default", "low", "medium", "high", "maximum"}:
        step7_reasoning_strength = "maximum"
    step5_thinking_selected = {
        value: " selected" if step5_thinking_mode == value else ""
        for value in ("official_default", "enabled", "disabled")
    }
    step6_thinking_selected = {
        value: " selected" if step6_thinking_mode == value else ""
        for value in ("official_default", "enabled", "disabled")
    }
    step7_thinking_selected = {
        value: " selected" if step7_thinking_mode == value else ""
        for value in ("official_default", "enabled", "disabled")
    }
    step5_strength_selected = {
        value: " selected" if step5_reasoning_strength == value else ""
        for value in ("official_default", "low", "medium", "high", "maximum")
    }
    step7_strength_selected = {
        value: " selected" if step7_reasoning_strength == value else ""
        for value in ("official_default", "low", "medium", "high", "maximum")
    }
    step6_strength_selected = {
        value: " selected" if step6_reasoning_strength == value else ""
        for value in ("official_default", "low", "medium", "high", "maximum")
    }
    try:
        vision_concurrency = max(
            1,
            min(
                20,
                int(
                    os.environ.get("VISION_CONCURRENCY")
                    or os.environ.get("NVIDIA_VISION_CONCURRENCY", "8")
                    or "8"
                ),
            ),
        )
    except ValueError:
        vision_concurrency = 8
    serverchan_enabled = os.environ.get("SERVERCHAN_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    serverchan_checked = " checked" if serverchan_enabled else ""
    serverchan_configured = bool(os.environ.get("SERVERCHAN_SENDKEY", "").strip())
    serverchan_status = "Enabled; SendKey configured" if serverchan_enabled and serverchan_configured else (
        "SendKey configured; notifications disabled" if serverchan_configured else "Not configured"
    )
    wxpusher_enabled = os.environ.get("WXPUSHER_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    wxpusher_checked = " checked" if wxpusher_enabled else ""
    wxpusher_configured = bool(os.environ.get("WXPUSHER_SPT", "").strip())
    wxpusher_status = "Enabled; SPT configured" if wxpusher_enabled and wxpusher_configured else (
        "SPT configured; notifications disabled" if wxpusher_configured else "Not configured"
    )
    prompt = {key: escape(value) for key, value in prompts.items()}
    seo_count_label = seo_keyword_count_text(parse_seo_keyword_count(prompts.get("description_generation", "")))
    default_prompts_json = json.dumps(DEFAULT_PROMPTS, ensure_ascii=False)
    step9_description = "Locate and bind the correct Ziniao store window manually. Steps 9–13 remain locked to that window."
    step9_body = '''
    <div id="ziniao_binding_panel">
      <div id="ziniao_task_store" class="status-line">Current task store: use the store selected in Step 0 and the product loaded in Step 1</div>
      <label>Open Ziniao store window</label>
      <select id="ziniao_window_select"><option value="">Click Refresh Ziniao Windows</option></select>
      <div class="action-row">
        <button type="button" onclick="refreshZiniaoWindows()">Refresh Ziniao Windows</button>
        <button type="button" onclick="previewZiniaoWindow()">Locate Selected Window</button>
        <button type="button" class="primary-action" onclick="bindZiniaoWindow()">Bind to Current Task</button>
        <button type="button" onclick="unbindZiniaoWindow()">Unbind</button>
      </div>
      <div id="ziniao_binding_status" class="status-line">No window is bound. Step 9 and later form-filling actions are disabled until you bind one.</div>
    </div>
    <div id="connection_status" class="status-line">Not connected to Ziniao</div>
    <button class="primary-action" onclick="callApi('open-shopee-page')">Open and Control the Bound Shopee Page</button>
    <details><summary>DOM Probe and Debug Information</summary><button onclick="callApi('probe-shopee-page')">Probe Bound Page</button></details>
  '''
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Shopee AI Listing Assistant</title>
  <style>
    :root {{ --ink:#17212b; --muted:#5b6773; --line:#d7dde3; --soft:#f5f7f8; --brand:#087f5b; --brand-dark:#066848; --danger:#c92a2a; --warn:#9c5a00; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); background:#fff; font-family:"Microsoft YaHei",Arial,sans-serif; font-size:14px; letter-spacing:0; }}
    header {{ position:sticky; top:0; z-index:10; display:flex; align-items:center; justify-content:space-between; gap:16px; padding:14px 24px; background:#15202b; color:#fff; border-bottom:3px solid var(--brand); }}
    header h1 {{ margin:0; font-size:20px; }}
    header span {{ color:#cdd6df; font-size:13px; }}
    .header-actions {{ display:flex; align-items:center; justify-content:flex-end; gap:12px; }}
    .close-app-action {{ min-height:32px; padding:5px 10px; border-color:#ff8787; color:#fff; background:#c92a2a; font-size:13px; }}
    .close-app-action:hover {{ border-color:#ffa8a8; background:#a61e1e; }}
    main {{ max-width:1120px; margin:0 auto; padding:0 20px 48px; }}
    .workflow-step {{ padding:26px 0 30px; border-bottom:1px solid var(--line); }}
    .step-heading {{ display:grid; grid-template-columns:48px 1fr; gap:14px; align-items:start; margin-bottom:18px; }}
    .step-number {{ width:42px; height:42px; display:grid; place-items:center; background:#e7f5ef; color:var(--brand-dark); border:1px solid #9ed5c3; border-radius:6px; font-weight:700; font-size:16px; }}
    h2 {{ margin:0; font-size:18px; line-height:1.35; }}
    .step-heading p {{ margin:5px 0 0; color:var(--muted); line-height:1.55; }}
    .step-body {{ margin-left:62px; }}
    .grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px 18px; }}
    .wide {{ grid-column:1 / -1; }}
    label {{ display:block; margin-bottom:6px; color:#34414d; font-size:13px; font-weight:600; }}
    input,select,textarea {{ width:100%; border:1px solid #b9c2ca; border-radius:5px; background:#fff; padding:9px 10px; color:var(--ink); font:inherit; }}
    textarea {{ min-height:96px; resize:vertical; font-family:Consolas,"Microsoft YaHei",monospace; }}
    .description-editor {{ min-height:320px; line-height:1.55; }}
    button {{ min-height:40px; border:1px solid var(--brand); border-radius:5px; padding:8px 14px; background:#fff; color:var(--brand-dark); cursor:pointer; font:inherit; font-weight:600; }}
    button:hover {{ background:#edf8f4; }}
    button:disabled {{ cursor:not-allowed; opacity:.58; }}
    .action-row {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; }}
    .sku-action-row button {{ width:240px; min-width:240px; margin-top:16px; }}
    .store-mode-row {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; align-items:center; }}
    .store-mode-row button {{ white-space:nowrap; }}
    dialog {{ width:min(460px,calc(100vw - 32px)); border:1px solid var(--line); border-radius:6px; padding:20px; color:var(--ink); }}
    .credentials-dialog {{ width:min(760px,calc(100vw - 32px)); max-height:calc(100vh - 32px); overflow:auto; }}
    dialog::backdrop {{ background:rgba(23,33,43,.45); }}
    dialog h3 {{ margin:0 0 8px; font-size:18px; }}
    dialog p {{ color:var(--muted); line-height:1.55; }}
    .toggle-field label {{ min-height:40px; display:flex; align-items:center; gap:9px; margin:21px 0 0; }}
    .toggle-field input[type="checkbox"] {{ width:18px; height:18px; margin:0; }}
    .primary-action {{ display:inline-flex; align-items:center; justify-content:center; min-width:240px; margin-top:16px; background:var(--brand); color:#fff; }}
    .primary-action:hover {{ background:var(--brand-dark); }}
    .full-workflow-action {{ background:#d9480f; border-color:#d9480f; }}
    .full-workflow-action:hover {{ background:#b9380a; border-color:#b9380a; }}
    .pause-workflow-action {{ margin-top:16px; border-color:#9c5a00; color:#8a4f00; }}
    .pause-workflow-action:hover {{ background:#fff4e6; }}
    .small-actions {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }}
    .small-actions button {{ min-height:34px; padding:6px 10px; font-size:13px; }}
    .status-line {{ min-height:38px; margin-top:12px; padding:9px 11px; background:var(--soft); border-left:3px solid #91a0ad; color:#34414d; line-height:1.5; overflow-wrap:anywhere; }}
    .status {{ color:var(--warn); font-weight:600; }}
    .ok {{ color:#16834b; }}
    .err {{ color:var(--danger); }}
    details {{ margin-top:14px; border-top:1px dashed #c8d0d7; padding-top:10px; }}
    summary {{ cursor:pointer; color:#3f4d59; font-weight:600; }}
    details > .grid, details > textarea, details > pre {{ margin-top:12px; }}
    .version-switch {{ display:inline-grid; grid-template-columns:repeat(2,minmax(126px,1fr)); border:1px solid var(--brand); border-radius:5px; overflow:hidden; }}
    .version-switch button {{ border:0; border-radius:0; min-height:36px; }}
    .version-switch button + button {{ border-left:1px solid var(--brand); }}
    .version-switch button.active {{ background:var(--brand); color:#fff; }}
    .asset-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(132px,1fr)); gap:10px; margin-top:12px; }}
    .asset-item {{ border:1px solid var(--line); border-radius:5px; padding:7px; font-size:12px; overflow-wrap:anywhere; }}
    .asset-item img {{ width:100%; aspect-ratio:1; object-fit:cover; display:block; margin-bottom:6px; }}
    .asset-item.unsafe {{ border-color:var(--danger); background:#fff5f5; }}
    .progress-metrics {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:8px; margin-top:12px; }}
    .metric {{ background:var(--soft); padding:10px; border-bottom:2px solid #aab5bf; min-height:64px; }}
    .metric strong {{ display:block; margin-top:4px; font-size:17px; }}
    .analysis-list {{ display:grid; gap:6px; margin-top:12px; }}
    .analysis-row {{ display:grid; grid-template-columns:minmax(0,1fr) 110px; gap:10px; padding:8px 10px; border-bottom:1px solid #e2e7eb; }}
    .detail-image-list {{ display:grid; gap:4px; }}
    .detail-image-row {{ min-height:38px; display:grid; grid-template-columns:22px 20px minmax(0,1fr); align-items:center; gap:8px; padding:6px 8px; border:1px solid transparent; border-bottom-color:#e2e7eb; background:#fff; cursor:grab; }}
    .detail-image-row:hover {{ background:#f5f7f8; }}
    .detail-image-row.dragging {{ opacity:.45; }}
    .detail-image-row.drag-target {{ border-top-color:var(--brand); background:#edf8f4; }}
    .detail-image-row input[type="checkbox"] {{ width:18px; height:18px; margin:0; }}
    .workflow-retry-control {{ display:inline-flex; align-items:center; gap:6px; min-height:40px; padding:0 10px; border:1px solid #cbd5dc; background:#f7f9fa; }}
    .workflow-retry-control label {{ margin:0; white-space:nowrap; font-weight:600; }}
    .workflow-retry-control select {{ width:64px; min-height:32px; padding:4px 8px; }}
    .detail-drag-handle {{ color:#66727d; text-align:center; user-select:none; cursor:grab; }}
    .detail-image-name {{ min-width:0; line-height:1.4; overflow-wrap:anywhere; }}
    .reasoning-toolbar {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; align-items:end; margin-top:12px; }}
    .reasoning-output {{ min-height:160px; max-height:320px; overflow:auto; margin:10px 0 0; padding:12px; border:1px solid var(--line); border-radius:5px; background:#f8fafb; color:#27343f; font:13px/1.6 Consolas,"Microsoft YaHei",monospace; white-space:pre-wrap; overflow-wrap:anywhere; }}
    .template-editor {{ min-height:340px; margin-top:12px; font-family:Consolas,"Microsoft YaHei",monospace; font-size:13px; line-height:1.6; }}
    .result-list {{ display:grid; grid-template-columns:180px minmax(0,1fr); gap:8px 14px; margin-top:12px; }}
    .result-list div:nth-child(odd) {{ color:var(--muted); }}
    .check-list {{ margin:10px 0 0; padding-left:20px; line-height:1.8; columns:2; }}
    #log {{ max-height:220px; overflow:auto; white-space:pre-wrap; background:#17212b; color:#e8edf2; padding:12px; border-radius:5px; }}
    .workflow-sidebar {{ position:fixed; z-index:9; left:12px; top:72px; bottom:12px; width:284px; display:flex; flex-direction:column; border:1px solid var(--line); border-radius:6px; background:#fff; box-shadow:0 8px 24px rgba(23,33,43,.16); overflow:hidden; }}
    .sidebar-header {{ min-height:44px; display:flex; align-items:center; justify-content:space-between; gap:8px; padding:7px 8px 7px 12px; border-bottom:1px solid var(--line); background:#f5f7f8; }}
    .sidebar-header strong {{ font-size:15px; }}
    .sidebar-toggle {{ min-height:30px; padding:4px 9px; font-size:12px; }}
    .sidebar-body {{ min-height:0; flex:1; display:flex; flex-direction:column; }}
    .sidebar-step-list {{ min-height:220px; flex:1 1 62%; overflow:auto; padding:6px; }}
    .sidebar-step-button {{ width:100%; min-height:31px; display:block; border:0; border-left:3px solid transparent; border-radius:3px; padding:5px 8px; color:#34414d; text-align:left; font-size:12px; font-weight:600; }}
    .sidebar-step-button:hover {{ background:#edf8f4; }}
    .sidebar-step-button.active {{ border-left-color:var(--brand); background:#e7f5ef; color:var(--brand-dark); }}
    .sidebar-log-panel {{ min-height:190px; flex:0 1 38%; display:flex; flex-direction:column; border-top:1px solid var(--line); background:#17212b; }}
    .sidebar-log-title {{ padding:8px 10px; color:#fff; font-size:13px; font-weight:700; border-bottom:1px solid #34414d; }}
    #sidebar_log {{ min-height:0; flex:1; overflow:auto; padding:9px 10px; color:#e8edf2; font:12px/1.55 Consolas,"Microsoft YaHei",monospace; white-space:pre-wrap; overflow-wrap:anywhere; }}
    .workflow-sidebar.collapsed {{ width:54px; height:46px; bottom:auto; }}
    .workflow-sidebar.collapsed .sidebar-title,.workflow-sidebar.collapsed .sidebar-body {{ display:none; }}
    .workflow-sidebar.collapsed .sidebar-header {{ justify-content:center; padding:7px; border-bottom:0; }}
    .cache-cleanup-panel {{ margin-top:22px; padding-top:18px; border-top:1px dashed #c8d0d7; }}
    .cache-cleanup-panel h3 {{ margin:0 0 6px; font-size:15px; }}
    .danger-action {{ border-color:var(--danger); color:var(--danger); }}
    .danger-action:hover {{ background:#fff5f5; }}
    main {{ width:calc(100% - 332px); max-width:1120px; margin-left:316px; margin-right:16px; }}
    @media (max-width:760px) {{
      header {{ position:static; align-items:flex-start; flex-direction:column; padding:14px 16px; }}
      .header-actions {{ width:100%; justify-content:space-between; }}
      main {{ width:auto; margin:0; padding:0 70px 72px 14px; }}
      .step-heading {{ grid-template-columns:40px 1fr; gap:10px; }}
      .step-number {{ width:36px; height:36px; }}
      .step-body {{ margin-left:0; }}
      .grid,.progress-metrics {{ grid-template-columns:1fr; }}
      .check-list {{ columns:1; }}
      .action-row {{ flex-direction:column; align-items:stretch; }}
      .sku-action-row button {{ width:100%; min-width:0; }}
      .store-mode-row {{ grid-template-columns:1fr; }}
      .primary-action {{ width:100%; min-width:0; }}
      .result-list {{ grid-template-columns:1fr; }}
      .reasoning-toolbar {{ grid-template-columns:1fr; }}
    }}
    @media (max-width:1100px) {{
      .workflow-sidebar {{ top:auto; left:auto; right:8px; bottom:8px; width:54px; height:46px; }}
      .workflow-sidebar .sidebar-title,.workflow-sidebar .sidebar-body {{ display:none; }}
      .workflow-sidebar .sidebar-header {{ justify-content:center; padding:7px; border-bottom:0; }}
      .workflow-sidebar.mobile-open {{ top:66px; left:8px; right:auto; width:min(304px,calc(100vw - 16px)); height:auto; bottom:8px; }}
      .workflow-sidebar.mobile-open .sidebar-title,.workflow-sidebar.mobile-open .sidebar-body {{ display:flex; }}
      .workflow-sidebar.mobile-open .sidebar-title {{ display:block; }}
      .workflow-sidebar.mobile-open .sidebar-header {{ justify-content:space-between; padding:7px 8px 7px 12px; border-bottom:1px solid var(--line); }}
      main {{ width:auto; margin-left:0; margin-right:0; padding-right:70px; }}
    }}
  </style>
</head>
<body>
<header><h1>Shopee AI Listing Assistant</h1><div class="header-actions"><span>{escape(multi_header_text)}</span><button id="close_app_button" type="button" class="close-app-action" onclick="closeShopeeApp()">Close App</button></div></header>
<aside id="workflow_sidebar" class="workflow-sidebar" aria-label="Workflow navigation and live log">
  <div class="sidebar-header"><strong class="sidebar-title">Workflow</strong><button id="sidebar_toggle" type="button" class="sidebar-toggle" onclick="toggleWorkflowSidebar()">Collapse</button></div>
  <div class="sidebar-body">
    <nav class="sidebar-step-list" aria-label="Steps 0 through 15">{sidebar_step_links}</nav>
    <section class="sidebar-log-panel" aria-label="Live detailed log"><div class="sidebar-log-title">Live Log</div><div id="sidebar_log">Interface ready.</div></section>
  </div>
</aside>
<main>
  {_step(0, "Configuration", "Save the store, workbook, and AI settings.", f'''
    <div class="grid">
      <div class="wide"><label>Store</label><div class="store-mode-row"><select id="store" onchange="handleStoreSelectionChanged()">{store_options}</select><button id="multi_store_mode_button" type="button" onclick="toggleMultiStoreMode()">{multi_button_label}</button></div><div id="multi_store_mode_status" class="status-line">{escape(f"Multi-store mode: task {multi_slot}/{multi_count}" if multi_active else "Current mode: single-store listing")}</div></div>
      <div class="wide"><label>Custom Store Name</label><div class="store-mode-row"><input id="custom_store_name" maxlength="100" placeholder="Enter a store name"><button type="button" onclick="saveCustomStoreName()">Add and Save Store</button></div><div id="custom_store_status" class="status-line">The new name will reuse the selected store's workbook status column and write-back sheet.</div></div>
      <div class="wide"><label>Product Workbook Path</label><input id="workbook" value="{escape(state.workbook_path)}"></div>
      <div class="wide"><label>AI Execution Mode</label><select id="ai_execution_mode" onchange="updateAiExecutionModeControls()"><option value="vision_text"{execution_mode_selected[AI_EXECUTION_MODE_VISION_TEXT]}>Vision Model + Text Model</option><option value="multimodal"{execution_mode_selected[AI_EXECUTION_MODE_MULTIMODAL]}>Multimodal Model</option></select><div id="ai_execution_mode_status" class="status-line"></div></div>
      <div class="wide"><button type="button" onclick="byId('credentials_dialog').showModal()">Edit API Keys and Notification Tokens</button></div>
      <input id="ai_mode" type="hidden" value="openai">
      <input id="run_mode" type="hidden" value="save_delist">
    </div>
    <div class="action-row">
      <button class="primary-action" onclick="callApi('save-ai-settings')">Save Configuration</button>
      <button id="full_workflow_button" class="primary-action full-workflow-action" onclick="runFullWorkflow(this)">Run Full Listing Workflow</button>
      <button id="pause_full_workflow_button" class="pause-workflow-action" onclick="requestPauseFullWorkflow(this)" disabled>Stop Full Workflow</button>
      <div class="workflow-retry-control"><label for="full_workflow_auto_retry_count">Automatic retries after failure</label><select id="full_workflow_auto_retry_count">{full_workflow_auto_retry_options}</select><span>times</span></div>
    </div>
    <div id="full_workflow_status" class="status-line">Ready to run Steps 0–15. Stopping invalidates active requests immediately. Failed steps use the retry count above.</div>
    <div id="wechat_notification_status" class="status-line">Windows topmost alert: always enabled | WxPusher: {wxpusher_status} | ServerChan: {serverchan_status}</div>
  ''')}

  {_step(1, "Select SKU", "Load one unlisted item automatically or enter an SKU code manually. Product data always comes from the corresponding workbook row.", '''
    <input id="sku_selection_mode" type="hidden" value="auto">
    <label>Manual SKU Code (leave blank for automatic selection)</label><input id="manual_sku_code" placeholder="Enter an SKU code from the product workbook" oninput="updateSkuSelectionMode()">
    <div class="action-row sku-action-row"><button class="primary-action" onclick="selectSpecifiedSku()">Load Specified SKU</button><button onclick="selectAutomaticSku()">Select One Unlisted SKU Automatically</button></div>
    <div id="sku_selection_mode_status" class="status-line">Current mode: automatic unlisted SKU selection</div>
    <div class="result-list"><div>Current SKU Code</div><div id="sku_code">-</div><div>Product Name</div><div id="product_name">-</div><div>Brand</div><div id="brand">-</div><div>Price</div><div id="prices">-</div><div>AO Stock</div><div id="stock">-</div></div>
    <div id="sku_step_status" class="status-line">Waiting for SKU selection</div>
  ''')}

  {_step(2, "Load Asset Pack", "Provide a local asset-pack directory or archive. Automatic download is planned and is not available in this release.", '''
    <label>Manual Asset Pack Path</label><input id="asset_path" value="" autocomplete="off" placeholder="Enter a local directory or archive path">
    <div class="status-line">Automatic asset-pack download: planned</div>
    <button class="primary-action" onclick="callApi('inspect-assets')">Inspect Asset Pack</button>
    <div id="asset_download_status" class="status-line">No asset pack loaded</div>
    <div class="result-list"><div>Source</div><div id="asset_version_result">Manual path</div><div>Resolved Directory</div><div id="asset_download_dir">-</div><div>Detected Folders and Files</div><div id="asset_folder_summary">-</div></div>
  ''')}

  {_step(3, "Analyze Images", "Keep an independent result for each image and process images with the selected model at the configured concurrency. Failed items retry under the same limit.", f'''
    <div class="grid"><div><label>Step 3 Model</label><select id="vision_model" onchange="updateVisionThinkingControls()">{step3_model_options}</select></div><div><label>Vision Reasoning Mode</label><select id="vision_thinking_mode" onchange="updateVisionThinkingControls()"><option value="official_default"{vision_thinking_selected['official_default']}>Official Default</option><option value="adaptive"{vision_thinking_selected['adaptive']}>Adaptive</option><option value="enabled"{vision_thinking_selected['enabled']}>Enabled</option><option value="disabled"{vision_thinking_selected['disabled']}>Disabled</option></select></div><div><label>Vision Reasoning Effort</label><select id="vision_reasoning_strength" onchange="updateVisionThinkingControls()"><option value="official_default"{vision_strength_selected['official_default']}>Official Default</option><option value="low"{vision_strength_selected['low']}>Low</option><option value="medium"{vision_strength_selected['medium']}>Medium</option><option value="high"{vision_strength_selected['high']}>High</option><option value="maximum"{vision_strength_selected['maximum']}>Maximum</option></select></div></div>
    <div id="vision_reasoning_setting_status" class="status-line">Current: official model defaults</div>
    <label>Image Analysis Concurrency (1–20; default 8)</label><input id="vision_concurrency" type="number" min="1" max="20" step="1" value="{vision_concurrency}">
    <details id="image_analysis_prompt_panel"><summary>Image Analysis Prompt (English; editable)</summary><textarea id="prompt_image_analysis">{prompt['image_analysis']}</textarea><div class="small-actions"><button onclick="callApi('save-prompts')">Save Current Prompt</button></div></details>
    <div id="image_analysis_progress" class="status-line">Active: - | Completed: 0 / 0 | Successful: 0 | Failed: 0 | Rate-limit wait: No</div>
    <div class="progress-metrics"><div class="metric">Current File<strong id="image_progress_current">-</strong></div><div class="metric">Concurrency<strong id="image_progress_concurrency">{vision_concurrency}</strong></div><div class="metric">Completed<strong id="image_progress_completed">0 / 0</strong></div><div class="metric">Successful<strong id="image_progress_success">0</strong></div><div class="metric">Failed<strong id="image_progress_failed">0</strong></div><div class="metric">Cached<strong id="image_progress_cached">0</strong></div></div>
    <div id="per_image_analysis_results" class="analysis-list">Per-image analysis has not started</div>
    <button class="primary-action" onclick="callApi('analyze-images')">Analyze Images Individually</button>
    <details id="qwen_reasoning_panel"><summary>Live Vision Reasoning / Model Output</summary><div class="reasoning-toolbar"><div><label>Current Image</label><select id="qwen_reasoning_image" onchange="selectVisionReasoning()"></select></div><button type="button" onclick="clearReasoningDisplay('vision')">Clear Display</button></div><div id="qwen_reasoning_file" class="status-line">File: - | Model: - | Status: Waiting</div><pre id="qwen_reasoning_text" class="reasoning-output">Waiting for vision-model output</pre></details>
    <details><summary>Structured AI Output (JSON)</summary><div id="objective_record_editor"><label>Objective Image Record (editable; supplied to later text steps)</label><textarea id="ai_product_info"></textarea></div><label>Image-Selection Assessment (local selection only)</label><textarea id="ai_asset_analysis"></textarea></details>
  ''')}

  {_step(4, "Confirm Listing Images", "Manual selection has the highest priority. OEM/ODM risks are shown as warnings and do not block confirmation. Shopee allows up to nine product images in total.", '''
    <div id="asset_candidates" class="status-line">Load and analyze an asset pack first</div><div id="image_selection_summary" class="status-line">Image selection is not confirmed</div>
    <div class="grid"><div><label>Main Image</label><select id="selected_main_image" onchange="updateManualImageSelectionSummary()"></select></div><div><label>Detail Images (select up to 8; drag to reorder)</label><div id="selected_detail_images" class="detail-image-list"></div></div></div>
    <button class="primary-action" onclick="callApi('confirm-image-selection')">Confirm Image Selection</button>
  ''')}

  {_step(5, "Generate Search Terms", "Generate five core English search terms for finding competitor listings, with concise meanings in English.", f'''
    <div class="grid"><div><label>Step 5 Model</label><select id="keyword_text_model" onchange="updateKeywordThinkingControls()">{step5_model_options}</select></div><div><label>Search-Term Reasoning Mode</label><select id="keyword_thinking_mode" onchange="updateKeywordThinkingControls()"><option value="official_default"{step5_thinking_selected['official_default']}>Official Default</option><option value="enabled"{step5_thinking_selected['enabled']}>Enabled</option><option value="disabled"{step5_thinking_selected['disabled']}>Disabled</option></select></div><div><label>Search-Term Reasoning Effort</label><select id="keyword_reasoning_strength" onchange="updateKeywordThinkingControls()"><option value="official_default"{step5_strength_selected['official_default']}>Official Default</option><option value="low"{step5_strength_selected['low']}>Low</option><option value="medium"{step5_strength_selected['medium']}>Medium</option><option value="high"{step5_strength_selected['high']}>High</option><option value="maximum"{step5_strength_selected['maximum']}>Maximum</option></select></div></div>
    <div id="keyword_reasoning_setting_status" class="status-line">Current: gpt-5.6; official model defaults</div>
    <details id="keyword_prompt_panel"><summary>Search-Term Prompt</summary><textarea id="prompt_keyword_generation">{prompt['keyword_generation']}</textarea></details>
    <label>Generated Search Terms</label><textarea id="ai_keywords"></textarea>
    <button class="primary-action" onclick="callApi('generate-keywords')">Generate Competitor Search Terms</button>
    <details id="keyword_reasoning_panel"><summary>Live Search-Term Reasoning</summary><div class="reasoning-toolbar"><div id="keyword_reasoning_status" class="status-line">Status: Waiting</div><button type="button" onclick="clearReasoningDisplay('keywords')">Clear Display</button></div><pre id="keyword_reasoning_text" class="reasoning-output">Waiting for search-term model output</pre></details>
    <details><summary>Raw AI Output (JSON)</summary><pre id="keyword_raw_json">-</pre></details>
  ''')}

  {_step(6, "Analyze Competitor Titles", "Derive title keywords only from real competitor titles and verify claims against the asset evidence.", f'''
    <div class="grid"><div><label>Step 6 Model</label><select id="title_text_model" onchange="updateTitleThinkingControls()">{step6_model_options}</select></div><div><label>Title Reasoning Mode</label><select id="title_thinking_mode" onchange="updateTitleThinkingControls()"><option value="official_default"{step6_thinking_selected['official_default']}>Official Default</option><option value="enabled"{step6_thinking_selected['enabled']}>Enabled</option><option value="disabled"{step6_thinking_selected['disabled']}>Disabled</option></select></div><div><label>Title Reasoning Effort</label><select id="title_reasoning_strength" onchange="updateTitleThinkingControls()"><option value="official_default"{step6_strength_selected['official_default']}>Official Default</option><option value="low"{step6_strength_selected['low']}>Low</option><option value="medium"{step6_strength_selected['medium']}>Medium</option><option value="high"{step6_strength_selected['high']}>High</option><option value="maximum"{step6_strength_selected['maximum']}>Maximum</option></select></div></div>
    <div id="title_reasoning_setting_status" class="status-line">Current: gpt-5.6; official model defaults</div>
    <label>Competitor Inputs (one per line; title, URL, and sales are supported)</label><textarea id="manual_competitors" placeholder="Provide five real high-sales competitor listings when possible"></textarea>
    <label>Edit Listing Title</label><textarea id="ai_title"></textarea><div id="title_character_count" class="status-line">Title length: 0 / 120</div>
    <button class="primary-action" onclick="callApi('analyze-title')">Analyze Competitors and Generate Title</button>
    <details id="glm_reasoning_panel"><summary>Live Title Reasoning</summary><div class="reasoning-toolbar"><div id="glm_reasoning_status" class="status-line">Status: Waiting</div><button type="button" onclick="clearReasoningDisplay('title')">Clear Display</button></div><pre id="glm_reasoning_text" class="reasoning-output">Waiting for title-model output</pre></details>
    <details><summary>Advanced Prompt Editor</summary><textarea id="prompt_competitor_title_analysis">{prompt['competitor_title_analysis']}</textarea></details>
    <details><summary>Raw AI Output (JSON)</summary><textarea id="ai_title_analysis"></textarea></details>
  ''')}

  {_step(7, "Generate Description", f"Generate template placeholders, {seo_count_label}, a final hashtag line, and the complete description. The prompt controls the keyword count.", f'''
    <div class="grid"><div><label>Step 7 Model</label><select id="description_text_model" onchange="updateDescriptionThinkingControls()">{step7_model_options}</select></div><div><label>Description Reasoning Mode</label><select id="description_thinking_mode" onchange="updateDescriptionThinkingControls()"><option value="official_default"{step7_thinking_selected['official_default']}>Official Default</option><option value="enabled"{step7_thinking_selected['enabled']}>Enabled</option><option value="disabled"{step7_thinking_selected['disabled']}>Disabled</option></select></div><div><label>Description Reasoning Effort</label><select id="description_reasoning_strength" onchange="updateDescriptionThinkingControls()"><option value="official_default"{step7_strength_selected['official_default']}>Official Default</option><option value="low"{step7_strength_selected['low']}>Low</option><option value="medium"{step7_strength_selected['medium']}>Medium</option><option value="high"{step7_strength_selected['high']}>High</option><option value="maximum"{step7_strength_selected['maximum']}>Maximum</option></select></div></div>
    <div id="description_reasoning_setting_status" class="status-line">Current: gpt-5.6; official model defaults</div>
    <details id="description_prompt_panel"><summary>Description Prompt (editable)</summary><textarea id="prompt_description_generation">{prompt['description_generation']}</textarea><div class="small-actions"><button type="button" onclick="savePrompts()">Save Prompt</button><button type="button" onclick="resetPromptToDefault('description_generation')">Restore Default Prompt</button></div><div id="description_prompt_status" class="status-line">Prompt edits are saved automatically when generating, or you can save them now.</div></details>
    <details id="description_template_panel"><summary>Current Store Description Template (editable)</summary><div id="description_template_status" class="status-line">Current store template: {escape(initial_template_key) or '-'} (updates with the selected store)</div><textarea id="description_template_text" class="template-editor">{escape(initial_template)}</textarea><div class="small-actions"><button type="button" onclick="saveDescriptionTemplate()">Save Template</button><button type="button" onclick="refreshDescriptionTemplate()">Reload Current Template</button></div><div class="status-line">Templates are blank by default. A non-empty template must retain {{{{PAIN_POINTS}}}}, {{{{BENEFITS}}}}, {{{{SPECIFICATIONS}}}}, and {{{{USAGE}}}}. Empty templates can be saved.</div></details>
    <div class="grid"><div><label>PAIN_POINTS / BENEFITS / SPECIFICATIONS / USAGE</label><textarea id="ai_description_placeholders"></textarea></div><div><label>{seo_count_label} (count follows the prompt)</label><textarea id="ai_seo_keywords"></textarea></div><div class="wide"><label>Final Product Description (editable)</label><textarea id="ai_final_description" class="description-editor" oninput="updateDescriptionCount()"></textarea><div id="description_character_count" class="status-line">Description length: 0 / 3000</div><div id="description_build_error" class="status-line err" style="display:none"></div></div></div>
    <button class="primary-action" onclick="callApi('generate-description')">Generate Product Description</button>
    <details id="description_reasoning_panel"><summary>Live Text-Model Reasoning</summary><div class="reasoning-toolbar"><div id="description_reasoning_status" class="status-line">Status: Waiting</div><button type="button" onclick="clearReasoningDisplay('description')">Clear Display</button></div><pre id="description_reasoning_text" class="reasoning-output">Waiting for text-model output</pre></details>
    <details><summary>Raw AI Output (JSON)</summary><pre id="description_raw_json">-</pre></details>
  ''')}

  {_step(8, "Build Listing Draft", "Build the final draft from the confirmed images, title, and description.", '''
    <div class="result-list"><div>Final Title</div><div id="title">-</div><div>listing_draft.json</div><div id="draft_path">-</div></div>
    <button class="primary-action" onclick="callApi('confirm-ai-results')">Build Listing Draft</button><div id="draft_step_status" class="status-line">Draft not generated</div>
  ''')}

  {_step(9, "Connect to Shopee", step9_description, step9_body)}

  {_step(10, "Fill Shopee Step 1", "Upload product images, enter the title and item code, handle GTIN, and continue to Step 2.", '''
    <ul class="check-list"><li>Check images</li><li>Upload product images</li><li>Enter title</li><li>Enter item code</li><li>Handle GTIN</li><li>Click Next Step</li></ul>
    <button class="primary-action" onclick="callApi('execute-step1')">Fill Shopee Step 1</button><div id="step1_status" class="status-line">Waiting</div>
  ''')}

  {_step(11, "Fill Shopee Step 2", "Process category, brand, attributes, description, video, variations, dimensions, and logistics in dependency order.", f'''
    <ul class="check-list"><li>Category</li><li>Brand and attributes</li><li>Description</li><li>Video</li><li>Variations</li><li>Price, stock, and SKU</li><li>Variation images</li><li>Weight and dimensions</li><li>Logistics</li><li>Parent item code</li></ul>
    <button class="primary-action" onclick="callApi('execute-step2')">Fill Shopee Step 2</button><div id="step2_status" class="status-line">Waiting</div>
    <details><summary>Advanced Prompt Editor</summary><textarea id="prompt_category_selection">{prompt['category_selection']}</textarea></details>
  ''')}

  {_step(12, "Run Checklist", "Show each page-state check for reference. Checklist warnings do not block the manual Save and Delist action.", '''
    <div id="checklist_result" class="status-line">Pre-save checklist has not run</div><button class="primary-action" onclick="callApi('run-checklist')">Run Pre-Save Checklist</button>
  ''')}

  {_step(13, "Save and Delist", "Save and delist first, then wait for the specified SKU in the correct unlisted-products page and retrieve its product ID.", '''
    <div id="save_permission_status" class="status-line">Ready. Pre-save checklist results are advisory.</div>
    <div class="action-row">
      <button class="primary-action" onclick="callApi('save-delist')">Save and Delist</button>
      <button id="fetch_product_id_button" type="button" onclick="callApi('fetch-product-id')">Fetch Product ID</button>
    </div>
    <div id="fetch_product_id_status" class="status-line">After saving, the app opens the unlisted-products page and searches for the current SKU every 10 seconds, up to 6 attempts.</div>
  ''')}

  {_step(14, "Review Results", "Review the listing status, product ID, and final evidence files.", '''
    <div class="result-list"><div>Product ID</div><div id="product_id">-</div><div>Listing Status</div><div id="listing_status_result">-</div><div>Final Report</div><div id="report_path">-</div><div>Screenshot</div><div id="screenshot_path">-</div><div>HTML</div><div id="html_path">-</div><div>Log</div><div id="log_path">-</div></div>
    <button class="primary-action" onclick="callApi('open-final-report')">Open Final Report</button>
    <details><summary>Detailed Log</summary><div id="log">Interface ready.</div><textarea id="ai_warnings" readonly></textarea></details>
  ''')}

  {_step(15, "Write Back to Workbook", "Select the store-specific sheet and append the product ID in column A and SKU in column E without overwriting existing data.", '''
    <input id="listing_result_token" type="hidden" value="">
    <div class="result-list"><div>Target Sheet</div><div id="workbook_sheet">-</div><div>Written Row</div><div id="workbook_row">-</div></div>
    <div id="workbook_record_status" class="status-line">Waiting for Save and Delist</div>
    <button class="primary-action" onclick="recordListingResult()">Write Product ID and SKU</button>
    <div class="cache-cleanup-panel">
      <h3>Clear Completed-Product Cache</h3>
      <button type="button" class="danger-action" onclick="clearOldCache()">Clear Old Logs, Reports, and AI-Generated Results</button>
      <div id="cache_cleanup_status" class="status-line">API keys, store configuration, Ziniao bindings, application files, the workbook, and manually supplied asset packs are preserved.</div>
    </div>
  ''')}
</main>
<dialog id="credentials_dialog" class="credentials-dialog">
  <h3>API Keys and Notification Tokens</h3>
  <div class="grid">
    <div><label>OpenAI API Key</label><input id="openai_api_key" type="password" placeholder="Stored values are never displayed; enter a new value to update it"></div>
    <div><label>AGNES_API_KEY — agnes-2.0-flash</label><input id="agnes_vision_key" type="password" placeholder="Stored values are never displayed; enter a new value to update it"></div>
    <div><label>NVIDIA_VISION_API_KEY — qwen/qwen3.5-397b-a17b</label><input id="nvidia_vision_key" type="password" placeholder="Stored values are never displayed; enter a new value to update it"></div>
    <div><label>NVIDIA_MINIMAX_VISION_API_KEY — minimaxai/minimax-m3</label><input id="nvidia_minimax_vision_key" type="password" placeholder="Leave blank to reuse the other compatible API key"></div>
    <div><label>NVIDIA_TEXT_API_KEY — z-ai/glm-5.2</label><input id="nvidia_text_key" type="password" placeholder="Stored values are never displayed; enter a new value to update it"></div>
    <div><label>ZHIPU_API_KEY — optional</label><input id="api_key" type="password" placeholder="Stored values are never displayed; enter a new value to update it"></div>
    <div><label>ServerChan SendKey</label><input id="serverchan_sendkey" type="password" placeholder="Stored values are never displayed; enter a new SCT value to update it"></div>
    <div><label>WxPusher SPT</label><input id="wxpusher_spt" type="password" placeholder="Stored values are never displayed; enter an SPT_ token"></div>
    <div class="toggle-field"><label><input id="serverchan_enabled" type="checkbox"{serverchan_checked}> Send a personal WeChat notification when the full workflow fails</label></div>
    <div class="toggle-field"><label><input id="wxpusher_enabled" type="checkbox"{wxpusher_checked}> Enable free WxPusher notifications</label></div>
  </div>
  <div class="action-row"><button type="button" class="primary-action" onclick="saveCredentials()">Save Keys and Tokens</button><button type="button" onclick="byId('credentials_dialog').close()">Cancel</button></div>
</dialog>
<dialog id="multi_store_dialog">
  <h3>Multi-Store Mode</h3>
  <p>This page becomes the first task and opens the remaining tasks in separate pages. All pages share only the AI request quota and the same Excel workbook.</p>
  <label>Number of Concurrent Store Pages (2–5)</label>
  <select id="multi_store_count"><option value="2">2 store pages</option><option value="3">3 store pages</option><option value="4">4 store pages</option><option value="5">5 store pages</option></select>
  <div class="action-row"><button type="button" class="primary-action" onclick="launchMultiStoreMode()">Start Multi-Store Mode</button><button type="button" onclick="byId('multi_store_dialog').close()">Cancel</button></div>
</dialog>
<script>
const MULTI_CONTEXT={task_context_json};
const AI_MODEL_CATALOG={reasoning_profile_json};
const MULTIMODAL_AI_MODEL_IDS={json.dumps(list(MULTIMODAL_AI_MODELS), ensure_ascii=False)};
const VISION_TEXT_AI_MODEL_IDS={json.dumps(list(VISION_TEXT_AI_MODELS), ensure_ascii=False)};
const TASK_ID=MULTI_CONTEXT.task_id||'';
const MULTI_CHANNEL=MULTI_CONTEXT.active&&window.BroadcastChannel?new BroadcastChannel('shopee-multi-'+MULTI_CONTEXT.multi_group_id):null;
const UI_CLIENT_ID=(window.crypto&&typeof window.crypto.randomUUID==='function'?window.crypto.randomUUID():'ui_'+Date.now().toString(36)+'_'+Math.random().toString(36).slice(2)).replace(/[^A-Za-z0-9_-]/g,'_');
let uiClientClosed=false;
function byId(id) {{ return document.getElementById(id); }}
function value(id) {{ return byId(id)?.value || ''; }}
function checked(id) {{ return Boolean(byId(id)?.checked); }}
async function sendUiHeartbeat() {{
  if(uiClientClosed)return;
  try {{
    await fetch('/api/ui-heartbeat',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{client_id:UI_CLIENT_ID}}),cache:'no-store',keepalive:true}});
  }} catch(error) {{}}
}}
function notifyUiClientClosed() {{
  if(uiClientClosed)return;
  uiClientClosed=true;
  const body=JSON.stringify({{client_id:UI_CLIENT_ID}});
  if(navigator.sendBeacon) {{
    const blob=new Blob([body],{{type:'application/json'}});
    if(navigator.sendBeacon('/api/ui-client-close',blob))return;
  }}
  fetch('/api/ui-client-close',{{method:'POST',headers:{{'Content-Type':'application/json'}},body,keepalive:true}}).catch(()=>{{}});
}}
async function closeShopeeApp() {{
  if(!window.confirm('Close Shopee AI Listing Assistant? This stops the background process and all active single-store and multi-store tasks.'))return;
  const button=byId('close_app_button');
  if(button){{button.disabled=true;button.textContent='Closing';}}
  uiClientClosed=true;
  try {{
    const response=await fetch('/api/shutdown',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:'{{}}'}});
    const data=await response.json();
  if(!data.ok)throw new Error(data.message||'Unable to close the app');
  document.body.innerHTML='<main style="max-width:680px;margin:80px auto;padding:24px;font-family:Arial,sans-serif"><h2>App Closed</h2><p>The background process has exited. You can close this page.</p></main>';
    setTimeout(()=>window.close(),250);
  }} catch(error) {{
    uiClientClosed=false;
  if(button){{button.disabled=false;button.textContent='Close App';}}
  window.alert('Unable to close the app: '+error);
  }}
}}
window.addEventListener('pagehide',notifyUiClientClosed);
window.addEventListener('pageshow',event=>{{if(event.persisted){{uiClientClosed=false;sendUiHeartbeat();}}}});
sendUiHeartbeat();
setInterval(sendUiHeartbeat,5000);
function payload() {{
  return {{task_id:TASK_ID,multi_group_id:MULTI_CONTEXT.multi_group_id||'',store:value('store'),custom_store_name:value('custom_store_name').trim(),workbook:value('workbook'),cdp_port:value('ziniao_window_select'),manual_sku_code:value('manual_sku_code').trim(),sku_selection_mode:value('sku_selection_mode'),asset_path:value('asset_path'),listing_result_token:value('listing_result_token'),api_key:value('api_key'),openai_api_key:value('openai_api_key'),ai_mode:value('ai_mode'),ai_execution_mode:value('ai_execution_mode'),step3_model:value('vision_model'),vision_model:value('vision_model'),vision_thinking_mode:value('vision_thinking_mode'),vision_reasoning_strength:value('vision_reasoning_strength'),vision_concurrency:value('vision_concurrency'),full_workflow_auto_retry_count:value('full_workflow_auto_retry_count'),agnes_vision_key:value('agnes_vision_key'),nvidia_vision_key:value('nvidia_vision_key'),nvidia_minimax_vision_key:value('nvidia_minimax_vision_key'),nvidia_text_key:value('nvidia_text_key'),serverchan_enabled:checked('serverchan_enabled'),serverchan_sendkey:value('serverchan_sendkey'),wxpusher_enabled:checked('wxpusher_enabled'),wxpusher_spt:value('wxpusher_spt'),keyword_text_model:value('keyword_text_model'),keyword_thinking_mode:value('keyword_thinking_mode'),keyword_reasoning_strength:value('keyword_reasoning_strength'),title_text_model:value('title_text_model'),title_thinking_mode:value('title_thinking_mode'),title_reasoning_strength:value('title_reasoning_strength'),description_text_model:value('description_text_model'),description_thinking_mode:value('description_thinking_mode'),description_reasoning_strength:value('description_reasoning_strength'),run_mode:value('run_mode'),manual_competitors:value('manual_competitors'),prompts:Object.fromEntries(['image_analysis','description_generation','keyword_generation','competitor_title_analysis','category_selection'].map(key=>[key,value('prompt_'+key)])),selected_main_image:value('selected_main_image'),selected_detail_images:[...document.querySelectorAll('input[name="selected_detail_image"]:checked')].map(el=>el.value),description_template:value('description_template_text'),ai_asset_analysis:value('ai_asset_analysis'),ai_product_info:value('ai_product_info'),ai_keywords:value('ai_keywords'),ai_title_analysis:value('ai_title_analysis'),ai_title:value('ai_title'),ai_description_placeholders:value('ai_description_placeholders'),ai_seo_keywords:value('ai_seo_keywords'),ai_final_description:value('ai_final_description')}};
}}
function handleMultiModeClosed() {{ if(Number(MULTI_CONTEXT.multi_slot)===1){{window.location.replace('/');return;}}window.close();setTimeout(()=>window.location.replace('/'),250); }}
if(MULTI_CHANNEL)MULTI_CHANNEL.onmessage=event=>{{if(event.data?.type==='close')handleMultiModeClosed();}};
window.addEventListener('storage',event=>{{if(MULTI_CONTEXT.active&&event.key==='shopee_multi_close_'+MULTI_CONTEXT.multi_group_id)handleMultiModeClosed();}});
function toggleMultiStoreMode() {{ if(MULTI_CONTEXT.active){{closeMultiStoreMode();return;}}byId('multi_store_dialog').showModal(); }}
function replaceStoreOptions(stores,selectedStore) {{
  const select=byId('store');if(!select)return;
  const names=Array.isArray(stores)?stores:[];
  select.innerHTML='<option value="">Select a store</option>'+names.map(name=>'<option value="'+escapeHtml(name)+'">'+escapeHtml(name)+'</option>').join('');
  if(names.includes(selectedStore))select.value=selectedStore;
}}
async function saveCustomStoreName() {{
  const selectedStore=value('store').trim();
  const customStoreName=value('custom_store_name').trim();
  if(!selectedStore){{setContent('custom_store_status','Select an existing store first.');return;}}
  if(!customStoreName){{setContent('custom_store_status','Enter a custom store name.');return;}}
  setContent('custom_store_status','Saving the custom store name...');
  try {{
    const response=await fetch('/api/save-custom-store',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(payload())}});
    const data=await response.json();if(!data.ok)throw new Error(data.message||'Unable to save the custom store name');
    replaceStoreOptions(data.stores,data.saved_store);
    byId('custom_store_name').value='';
    setContent('custom_store_status',data.message||'Custom store name saved.');
    await handleStoreSelectionChanged();
  }} catch(error) {{setContent('custom_store_status','Unable to save the custom store name: '+error);log('Unable to save the custom store name: '+error,'err');}}
}}
async function launchMultiStoreMode() {{
  const count=Math.max(2,Math.min(5,Number(value('multi_store_count'))||2));
  const extraWindows=[];for(let index=1;index<count;index+=1)extraWindows.push(window.open('about:blank','_blank'));
  if(extraWindows.some(opened=>!opened)){{extraWindows.forEach(opened=>opened?.close());setContent('multi_store_mode_status','The browser blocked new pages. Allow pop-ups for this page and try again.');return;}}
  byId('multi_store_dialog').close();setContent('multi_store_mode_status','Creating '+count+' independent listing pages');
  try {{
    const response=await fetch('/api/start-multi-store-mode',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{multi_store_count:count}})}});
  const data=await response.json();if(!data.ok)throw new Error(data.message||'Unable to start multi-store mode');
    const urls=data.task_urls||[];
    extraWindows.forEach((opened,index)=>{{if(opened)opened.location.href=urls[index+1];}});
    window.location.assign(urls[0]);
  }} catch(error) {{ extraWindows.forEach(opened=>opened?.close());setContent('multi_store_mode_status','Start failed: '+error); }}
}}
async function closeMultiStoreMode() {{
  if(!MULTI_CONTEXT.active)return;
  setContent('multi_store_mode_status','Closing the complete multi-store task group');
  try {{
    const response=await fetch('/api/close-multi-store-mode',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{task_id:TASK_ID,multi_group_id:MULTI_CONTEXT.multi_group_id}})}});
  const data=await response.json();if(!data.ok)throw new Error(data.message||'Unable to close multi-store mode');
    if(MULTI_CHANNEL)MULTI_CHANNEL.postMessage({{type:'close'}});
    localStorage.setItem('shopee_multi_close_'+MULTI_CONTEXT.multi_group_id,String(Date.now()));
    handleMultiModeClosed();
  }} catch(error) {{ setContent('multi_store_mode_status','Close failed: '+error); }}
}}
const DEFAULT_PROMPTS={default_prompts_json};
function escapeHtml(raw) {{ const div=document.createElement('div'); div.textContent=String(raw||''); return div.innerHTML; }}
function setText(id,data) {{ const el=byId(id); if(el&&data!==undefined) el.value=typeof data==='string'?data:JSON.stringify(data,null,2); }}
function setContent(id,data) {{ const el=byId(id); if(el&&data!==undefined) el.textContent=data||'-'; }}
function log(message,cls) {{ for(const id of ['log','sidebar_log']){{const el=byId(id);if(!el)continue;el.innerHTML+='\\n'+(cls?'<span class="'+cls+'">'+escapeHtml(message)+'</span>':escapeHtml(message));el.scrollTop=el.scrollHeight;}} }}
function updateManualImageSelectionSummary(message) {{
  const detailCount=document.querySelectorAll('input[name="selected_detail_image"]:checked').length;
  const total=detailCount+(value('selected_main_image')?1:0);
  const suffix=message?' | '+message:' | Manual selection overrides AI risk assessments';
  setContent('image_selection_summary','Product images: '+total+' / 9 | Detail images: '+detailCount+' / 8'+suffix);
}}
function enforceDetailImageLimit(changed) {{
  const selected=[...document.querySelectorAll('input[name="selected_detail_image"]:checked')];
  if(selected.length>8) {{
    if(changed)changed.checked=false;
    updateManualImageSelectionSummary('You can select up to eight detail images. The latest image was not added.');
    return;
  }}
  updateManualImageSelectionSummary();
}}
let draggedDetailImageRow=null;
function renderDetailImageRows(detailAssets,selectedDetails) {{
  const selectedOrder=new Map(selectedDetails.map((path,index)=>[path,index]));
  const originalOrder=new Map(detailAssets.map((item,index)=>[item.path,index]));
  const ordered=[...detailAssets].sort((left,right)=>{{
    const leftSelected=selectedOrder.has(left.path),rightSelected=selectedOrder.has(right.path);
    if(leftSelected&&rightSelected)return selectedOrder.get(left.path)-selectedOrder.get(right.path);
    if(leftSelected)return -1;
    if(rightSelected)return 1;
    return originalOrder.get(left.path)-originalOrder.get(right.path);
  }});
  return ordered.map(item=>
    '<div class="detail-image-row" draggable="true" data-path="'+escapeHtml(item.path)+'" ondragstart="detailImageDragStart(event)" ondragover="detailImageDragOver(event)" ondrop="detailImageDrop(event)" ondragend="detailImageDragEnd(event)">'
    +'<span class="detail-drag-handle" title="Drag to change upload order" aria-hidden="true">⋮⋮</span>'
    +'<input type="checkbox" name="selected_detail_image" aria-label="Select '+escapeHtml(item.name)+'" onchange="enforceDetailImageLimit(this)" value="'+escapeHtml(item.path)+'"'+(selectedDetails.includes(item.path)?' checked':'')+'>'
    +'<span class="detail-image-name">'+escapeHtml(item.name)+'</span></div>'
  ).join('');
}}
function detailImageDragStart(event) {{
  draggedDetailImageRow=event.currentTarget;
  event.dataTransfer.effectAllowed='move';
  event.dataTransfer.setData('text/plain',draggedDetailImageRow.dataset.path||'');
  requestAnimationFrame(()=>draggedDetailImageRow?.classList.add('dragging'));
}}
function detailImageDragOver(event) {{
  event.preventDefault();
  const target=event.currentTarget;
  if(!draggedDetailImageRow||target===draggedDetailImageRow)return;
  const container=target.parentElement;
  const insertAfter=event.clientY>target.getBoundingClientRect().top+target.offsetHeight/2;
  container.insertBefore(draggedDetailImageRow,insertAfter?target.nextSibling:target);
  for(const row of container.querySelectorAll('.detail-image-row'))row.classList.remove('drag-target');
  target.classList.add('drag-target');
}}
function detailImageDrop(event) {{
  event.preventDefault();
  updateManualImageSelectionSummary('Detail-image upload order updated; images upload from top to bottom.');
  detailImageDragEnd(event);
}}
function detailImageDragEnd(event) {{
  const container=event.currentTarget?.parentElement||byId('selected_detail_images');
  draggedDetailImageRow?.classList.remove('dragging');
  for(const row of container?.querySelectorAll('.detail-image-row')||[])row.classList.remove('drag-target');
  draggedDetailImageRow=null;
}}
function goToWorkflowStep(number) {{ byId('workflow-step-'+number)?.scrollIntoView({{behavior:'smooth',block:'start'}});if(window.matchMedia('(max-width:1100px)').matches){{byId('workflow_sidebar')?.classList.remove('mobile-open');updateSidebarToggleLabel();}} }}
function updateSidebarToggleLabel() {{ const sidebar=byId('workflow_sidebar'),button=byId('sidebar_toggle');if(!sidebar||!button)return;const compact=window.matchMedia('(max-width:1100px)').matches;button.textContent=compact?(sidebar.classList.contains('mobile-open')?'Collapse':'Navigation'):(sidebar.classList.contains('collapsed')?'Expand':'Collapse'); }}
function toggleWorkflowSidebar() {{ const sidebar=byId('workflow_sidebar');if(!sidebar)return;if(window.matchMedia('(max-width:1100px)').matches)sidebar.classList.toggle('mobile-open');else sidebar.classList.toggle('collapsed');updateSidebarToggleLabel(); }}
function updateActiveSidebarStep() {{ let active=0;for(const section of document.querySelectorAll('.workflow-step')){{if(section.getBoundingClientRect().top<=150)active=Number(section.dataset.step||0);else break;}}if(window.innerHeight+window.scrollY>=document.documentElement.scrollHeight-2)active=15;for(const button of document.querySelectorAll('.sidebar-step-button')){{const selected=Number(button.dataset.sidebarStep)===active;button.classList.toggle('active',selected);if(selected)button.setAttribute('aria-current','step');else button.removeAttribute('aria-current');}} }}
window.addEventListener('scroll',updateActiveSidebarStep,{{passive:true}});
window.addEventListener('resize',()=>{{const sidebar=byId('workflow_sidebar');if(window.matchMedia('(max-width:1100px)').matches)sidebar?.classList.remove('collapsed');else sidebar?.classList.remove('mobile-open');updateSidebarToggleLabel();}});
function renderZiniaoWindows(windows,selectedPort) {{
  const select=byId('ziniao_window_select');if(!select)return;
  const previous=String(selectedPort||select.value||'');select.innerHTML='';
  const placeholder=new Option(windows?.length?'Select and locate a Ziniao window':'No connectable Ziniao windows found','');select.add(placeholder);
  for(const item of windows||[]) {{
    const suffix=item.available?'':(' (bound to '+(item.bound_owner_label||('task '+(item.bound_task_slot||'?')))+': '+(item.bound_store||'another store')+')');
    const option=new Option(String(item.label||('Port '+item.port))+suffix,String(item.port||''));
    option.disabled=!item.available;option.dataset.boundToCurrent=item.bound_to_current?'true':'false';select.add(option);
  }}
  if(previous&&[...select.options].some(option=>option.value===previous&&!option.disabled))select.value=previous;
}}
function updateZiniaoBindingResult(result) {{
  setContent('ziniao_task_store','Current task store: '+(result.cdp_bound_store_name||result.selected_store||value('store')||'-'));
  if(Array.isArray(result.ziniao_windows))renderZiniaoWindows(result.ziniao_windows,result.previewed_cdp_port||result.cdp_port);
  const confirmed=String(result.cdp_binding_confirmed||'').toLowerCase()==='true';
  const status=byId('ziniao_binding_status');
  if(status) {{
    status.dataset.boundStore=confirmed?String(result.cdp_bound_store_name||''):'';
    status.textContent=confirmed
    ?'Manually bound: '+(result.cdp_bound_store_name||'-')+' | Port '+(result.cdp_port||'-')+' | '+(result.cdp_bound_window_label||'Ziniao window')
    :'No window is bound. Step 9 and later form-filling actions are disabled.';
    status.className='status-line'+(confirmed?' ok':'');
  }}
  if(confirmed) {{
    const select=byId('ziniao_window_select');if(select&&result.cdp_port)select.value=String(result.cdp_port);
    setContent('connection_status','Ziniao window bound manually: '+(result.cdp_bound_store_name||'-')+' | Port '+(result.cdp_port||'-'));
  }} else {{
    setContent('connection_status','No Ziniao window is bound');
  }}
}}
function resetSkuDependentView() {{
  if(byId('asset_path'))byId('asset_path').value='';
  for(const id of ['manual_competitors','ai_asset_analysis','ai_product_info','ai_keywords','ai_title_analysis','ai_title','ai_description_placeholders','ai_seo_keywords','ai_final_description','ai_warnings'])setText(id,'');
  for(const id of ['selected_main_image','selected_detail_images']){{const el=byId(id);if(el)el.innerHTML='';}}
  const candidates=byId('asset_candidates');if(candidates){{candidates.className='status-line';candidates.textContent='Load the asset pack for the current SKU first';}}
  setContent('image_selection_summary','Image selection is not confirmed for the current SKU');
  setContent('asset_download_status','No asset pack loaded for the current SKU; the manual path was cleared');
  for(const id of ['asset_download_dir','asset_folder_summary','title','draft_path','report_path','screenshot_path','html_path','log_path','product_id','listing_status_result','workbook_sheet','workbook_row'])setContent(id,'');
  setContent('sku_step_status','New SKU loaded; previous product data cleared');
  setContent('draft_step_status','Draft not generated for the current SKU');
  setContent('step1_status','Waiting');
  setContent('step2_status','Waiting');
  setContent('checklist_result','Pre-save checklist has not run');
  setContent('save_permission_status','Ready. Pre-save checklist results are advisory.');
  setContent('fetch_product_id_status','Waiting for Save and Delist on the current SKU');
  setContent('workbook_record_status','Waiting for Save and Delist on the current SKU');
  setContent('keyword_raw_json','-');
  setContent('description_raw_json','-');
  if(byId('listing_result_token'))byId('listing_result_token').value='';
  const fetchButton=byId('fetch_product_id_button');if(fetchButton)fetchButton.textContent='Fetch Product ID';
  const buildError=byId('description_build_error');if(buildError){{buildError.textContent='';buildError.style.display='none';}}
  updateDescriptionCount();
}}
function updateResult(data) {{
  if(data.description_template)applyDescriptionTemplate(data.description_template);
  const result=data.result||{{}};
  if(String(result.sku_context_reset||'').toLowerCase()==='true')resetSkuDependentView();
  if(result.selected_store&&byId('store'))byId('store').value=result.selected_store;
  for(const key of ['sku_code','product_name','brand','prices','stock','title','asset_download_dir','draft_path','report_path','screenshot_path','html_path','log_path','product_id']) setContent(key,result[key]);
  setContent('listing_status_result',result.listing_status);
  if(result.workbook_record_status!==undefined)setContent('workbook_record_status',result.workbook_record_status);
  if(result.workbook_sheet!==undefined)setContent('workbook_sheet',result.workbook_sheet);
  if(result.workbook_row!==undefined)setContent('workbook_row',result.workbook_row);
  if(result.listing_result_token!==undefined&&byId('listing_result_token'))byId('listing_result_token').value=result.listing_result_token||'';
  if(result.product_id) {{
    setContent('fetch_product_id_status','Product ID fetched: '+result.product_id+' | SKU: '+(result.sku_code||byId('sku_code')?.textContent||'-'));
    const fetchButton=byId('fetch_product_id_button');if(fetchButton)fetchButton.textContent='Fetch Product ID Again';
  }} else if(result.listing_status==='Waiting for product ID') {{
    setContent('fetch_product_id_status','Save and Delist submitted. Click Fetch Product ID to open the unlisted-products page and wait for the current SKU.');
    const fetchButton=byId('fetch_product_id_button');if(fetchButton)fetchButton.textContent='Fetch Product ID';
  }}
  if(result.asset_path!==undefined&&byId('asset_path')&&String(result.asset_path||'').trim()) byId('asset_path').value=result.asset_path;
  if(result.asset_download_status!==undefined) setContent('asset_download_status',result.asset_download_status);
  if(result.asset_folder_summary!==undefined)setContent('asset_folder_summary',result.asset_folder_summary);
  if(result.step1_status)setContent('step1_status',result.step1_status);if(result.step2_status)setContent('step2_status',result.step2_status);if(result.cdp_port&&!MULTI_CONTEXT.active)setContent('connection_status','Controlling Ziniao CDP port: '+result.cdp_port);
  updateZiniaoBindingResult(result);
  if(result.checklist){{setContent('checklist_result',JSON.stringify(result.checklist,null,2));setContent('save_permission_status',result.checklist_can_save?'Pre-save checklist passed; Save and Delist is ready':'The checklist has warnings; manual Save and Delist remains available');}}
}}
function hasProductIdForWriteback() {{
  const token=value('listing_result_token').trim();
  const productId=String(byId('product_id')?.textContent||'').trim();
  return Boolean(token)&&/^\\d{{8,}}$/.test(productId);
}}
function isMissingProductIdFailure(error) {{
  return /product\\s*ID|item\\s*ID|write.?back|listing result/i.test(error?.message||String(error||''));
}}
function prepareProductIdRetry(message) {{
  const text=message||'No product ID has been fetched. Try again.';
  const button=byId('fetch_product_id_button');
  if(button)button.textContent='Retry Product ID Fetch';
  const status=byId('fetch_product_id_status');
  if(status){{status.textContent=text;status.className='status-line err';}}
  goToWorkflowStep(13);
}}
async function recordListingResult() {{
  if(!hasProductIdForWriteback()) {{
  const error=new Error('Step 15 paused: no product ID is available. Return to Step 13 and click Retry Product ID Fetch.');
    prepareProductIdRetry(error.message);
    await notifyActionFailure('record-listing-result',error,'manual_step');
    return null;
  }}
  return callApi('record-listing-result');
}}
function updateImageProgress(progress) {{
  progress=progress||{{}}; const completed=progress.completed||0,total=progress.total||0;
  const active=progress.active_files||[];setContent('image_progress_current',progress.current_file||'-');setContent('image_progress_concurrency',String(progress.concurrency_limit||progress.concurrency||value('vision_concurrency')||8)); setContent('image_progress_completed',completed+' / '+total); setContent('image_progress_success',String(progress.success||0)); setContent('image_progress_failed',String(progress.failed||0)); setContent('image_progress_cached',String(progress.cached||0));
  setContent('image_analysis_progress','Active: '+active.length+' | Latest file: '+(progress.current_file||'-')+' | Completed: '+completed+' / '+total+' | Successful: '+(progress.success||0)+' | Failed: '+(progress.failed||0)+' | Rate-limit wait: '+(progress.rate_limit_waiting?'Yes':'No'));
  const items=progress.items||[]; const list=byId('per_image_analysis_results'); if(list) list.innerHTML=items.map(item=>'<div class="analysis-row"><span>'+escapeHtml(item.file_name||item.file_path)+'</span><strong>'+escapeHtml(item.status)+'</strong></div>').join('')||'Per-image analysis has not started';
}}
let latestReasoning={{vision:{{items:[]}},keywords:{{}},title:{{}},description:{{}}}};let reasoningDisplayCleared={{vision:false,keywords:false,title:false,description:false}};
function reasoningStatusLabel(status) {{ return ({{idle:'Waiting',running:'Starting',switching:'Switching fallback model',model_failed:'Current model failed',retrying_full_response:'Incomplete stream; requesting a complete response',streaming:'Reasoning',completed:'Completed',cached:'Cached',disabled:'Reasoning disabled',failed:'Failed'}})[status]||status||'Waiting'; }}
function selectVisionReasoning() {{
  const selected=value('qwen_reasoning_image');const vision=latestReasoning.vision||{{}};const item=(vision.items||[]).find(entry=>entry.file_name===selected)||{{}};
  const displayLabel=item.display_mode==='model_output'?' | Display: live model output':(item.display_mode==='reasoning'?' | Display: reasoning output':'');setContent('qwen_reasoning_file','File: '+(item.file_name||vision.current_file||'-')+' | Model: '+(item.model||vision.model||'-')+' | Status: '+reasoningStatusLabel(item.status||vision.status)+displayLabel);
  let displayText=item.text||'';if(!displayText&&item.status==='cached')displayText='This image used a cached result; no historical reasoning is available.';if(!displayText&&item.status==='completed')displayText='The model returned no displayable reasoning text.';
  const output=byId('qwen_reasoning_text');if(output&&!reasoningDisplayCleared.vision)output.textContent=displayText||vision.text||'Waiting for vision-model output';
}}
function textReasoningStatus(state) {{
  const parts=['Status: '+reasoningStatusLabel(state.status)];
  if(state.model)parts.push('Model: '+state.model);
  if(state.display_mode==='model_output')parts.push('Display: live model output');
  else if(state.display_mode==='reasoning')parts.push('Display: reasoning output');
  return parts.join(' ｜ ');
}}
function textReasoningDisplayText(state,waitingText) {{
  if(state.text)return state.text;
  if(state.status==='completed')return 'The model returned no displayable reasoning text.';
  if(state.status==='cached')return 'Cached result used; no historical reasoning is available.';
  if(state.status==='disabled')return state.text||'Reasoning was disabled for this request; only the final result was generated.';
  return waitingText;
}}
function updateReasoning(reasoning) {{
  latestReasoning=reasoning||latestReasoning;const vision=latestReasoning.vision||{{}},keywords=latestReasoning.keywords||{{}},title=latestReasoning.title||{{}};const select=byId('qwen_reasoning_image');
  if(select){{const items=vision.items||[],selected=select.value;select.innerHTML=items.map(item=>'<option value="'+escapeHtml(item.file_name)+'">'+escapeHtml(item.file_name)+'</option>').join('');const selectedItem=items.find(item=>item.file_name===selected),currentItem=items.find(item=>item.file_name===vision.current_file),latestWithText=[...items].reverse().find(item=>item.text);const target=selectedItem?.text?selected:(currentItem?.text?vision.current_file:(latestWithText?.file_name||vision.current_file||selected));if(target)select.value=target;}}
  selectVisionReasoning();setContent('keyword_reasoning_status',textReasoningStatus(keywords));const keywordOutput=byId('keyword_reasoning_text');if(keywordOutput&&!reasoningDisplayCleared.keywords)keywordOutput.textContent=textReasoningDisplayText(keywords,'Waiting for search-term model output');
  setContent('glm_reasoning_status',textReasoningStatus(title));const output=byId('glm_reasoning_text');if(output&&!reasoningDisplayCleared.title)output.textContent=textReasoningDisplayText(title,'Waiting for title-model output');
  const description=latestReasoning.description||{{}};setContent('description_reasoning_status',textReasoningStatus(description));const descriptionOutput=byId('description_reasoning_text');if(descriptionOutput&&!reasoningDisplayCleared.description)descriptionOutput.textContent=textReasoningDisplayText(description,'Waiting for text-model output');
}}
function clearReasoningDisplay(kind) {{ reasoningDisplayCleared[kind]=true;if(kind==='vision'){{setContent('qwen_reasoning_text','Display cleared');}}else if(kind==='keywords'){{setContent('keyword_reasoning_text','Display cleared');}}else if(kind==='description'){{setContent('description_reasoning_text','Display cleared');}}else{{setContent('glm_reasoning_text','Display cleared');}} }}
function applyDescriptionTemplate(info) {{
  if(!info)return;
  const editor=byId('description_template_text');
  if(editor&&info.template!==undefined)editor.value=info.template||'';
  setContent('description_template_status','Current store template: '+(info.template_key||'-')+' | Store: '+(info.store_name||'-')+' | Template length: '+(info.template_length||(info.template||'').length));
}}
async function refreshDescriptionTemplate() {{
  const store=value('store');
  if(!store)return;
  try {{
    const response=await fetch('/api/get-description-template',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{store:store}})}});
    const data=await response.json();
    if(!data.ok)throw new Error(data.message||'Unable to load the description template');
    applyDescriptionTemplate(data.description_template);log('Current store description template loaded','ok');
  }} catch(error) {{ log('Unable to load the description template: '+error,'err');await notifyActionFailure('get-description-template',error,'manual_step'); }}
}}
async function saveDescriptionTemplate() {{
  const editor=byId('description_template_text');
  if(!editor)return;
  try {{
    const response=await fetch('/api/save-description-template',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{store:value('store'),description_template:editor.value}})}});
    const data=await response.json();
    if(!data.ok)throw new Error(data.message||'Unable to save the description template');
    applyDescriptionTemplate(data.description_template);log(data.message||'Description template saved','ok');await notifyActionSuccess('save-description-template',data,'manual_step');
  }} catch(error) {{ log('Unable to save the description template: '+error,'err');await notifyActionFailure('save-description-template',error,'manual_step'); }}
}}
async function savePrompts() {{
  try {{
    const response=await fetch('/api/save-prompts',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(payload())}});
    const data=await response.json();
    if(!data.ok)throw new Error(data.message||'Unable to save prompts');
    setContent('description_prompt_status','Prompts saved to config/prompts.yaml. Future generations use the updated prompts.');log(data.message||'Prompts saved','ok');await notifyActionSuccess('save-prompts',data,'manual_step');
  }} catch(error) {{ setContent('description_prompt_status','Unable to save prompts: '+error);log('Unable to save prompts: '+error,'err');await notifyActionFailure('save-prompts',error,'manual_step'); }}
}}
function resetPromptToDefault(key) {{
  const editor=byId('prompt_'+key);
  if(!editor||!(key in DEFAULT_PROMPTS))return;
  editor.value=DEFAULT_PROMPTS[key]||'';
  setContent('description_prompt_status','Default prompt restored locally but not saved. Save the prompt or generate to apply it.');
}}
function updateWorkbench(data) {{
  const workbench=data.workbench;if(!workbench)return; const prompts=workbench.prompts||{{}};for(const key of Object.keys(prompts))setText('prompt_'+key,prompts[key]);
  const buildError=byId('description_build_error');if(buildError){{const message=workbench.description_build_error||'';buildError.textContent=message;buildError.style.display=message?'':'none';}}
  const ai=workbench.ai_result||{{}}; const selection=ai.image_selection||{{}}; setText('ai_asset_analysis',{{main_image:selection.main_image||'',detail_images:selection.detail_images||[],unsafe_images:selection.unsafe_images||[],image_selection_assessments:ai.image_selection_assessments||[]}}); setText('ai_product_info',ai.product_info_from_images||{{}});setText('ai_keywords',ai.search_keywords||[]);setText('ai_title_analysis',{{competitor_analysis:ai.competitor_analysis||[],removed_keywords:ai.removed_keywords||[],reused_keywords:ai.title_keywords||[]}});setText('ai_title',ai.title||'');setText('ai_description_placeholders',ai.description_placeholders||{{}});setText('ai_seo_keywords',ai.seo_keywords||[]);setText('ai_final_description',workbench.final_description||'');setText('ai_warnings',(workbench.warnings||[]).join('\\n')); updateDescriptionCount(); updateImageProgress(workbench.image_analysis_progress||ai.analysis_progress||{{}});
  const competitorTitles=(ai.competitor_analysis||[]).map(item=>String(item?.source_title||'').trim()).filter(Boolean);if(competitorTitles.length&&!value('manual_competitors').trim())setText('manual_competitors',competitorTitles.join('\\n'));
  const assets=workbench.asset_candidates||[];const unsafeItems=selection.unsafe_images||[];const unsafeMap=new Map(unsafeItems.map(item=>[typeof item==='string'?item:item.file,typeof item==='string'?'AI risk warning':item.reason]));const selectedMain=workbench.confirmed_image_selection?.main_image||selection.main_image||assets.find(item=>item.kind==='main')?.path||'';const selectedDetailsRaw=workbench.confirmed_image_selection?.detail_images||selection.detail_images||assets.filter(item=>item.kind==='detail').map(item=>item.path);const selectedDetails=(Array.isArray(selectedDetailsRaw)?selectedDetailsRaw:[]).slice(0,8);
  const main=byId('selected_main_image');if(main)main.innerHTML=assets.filter(item=>item.kind==='main').map(item=>'<option value="'+escapeHtml(item.path)+'"'+(item.path===selectedMain?' selected':'')+'>'+escapeHtml(item.name)+'</option>').join('');const details=byId('selected_detail_images');if(details)details.innerHTML=renderDetailImageRows(assets.filter(item=>item.kind==='detail'),selectedDetails);const candidates=byId('asset_candidates');if(candidates){{candidates.className='asset-grid';candidates.innerHTML=assets.map(item=>'<div class="asset-item'+(unsafeMap.has(item.path)?' unsafe':'')+'"><img src="'+escapeHtml(assetPreviewUrl(item))+'"><div>'+escapeHtml(item.kind+': '+item.name)+'</div><div>'+escapeHtml(unsafeMap.get(item.path)||'')+'</div></div>').join('')||'No asset candidates';}}
  const summary=workbench.image_selection_summary||{{}};const confirmation=summary.ok?'Manually confirmed; manual selection overrides AI risk assessments':'Manual selection overrides AI risk assessments';setContent('image_selection_summary','Product images: '+(selectedDetails.length+(selectedMain?1:0))+' / 9 | Detail images: '+selectedDetails.length+' / 8 | OEM/ODM warnings: '+(unsafeItems.length?'Yes':'No')+' | '+confirmation);setContent('key_status',workbench.key_status);updateRuntimeStatus({{ai_status:workbench.ai_status,listing_status:workbench.listing_status}});updateReasoning(workbench.ai_reasoning||{{}});
}}
function assetPreviewUrl(item) {{
  const query=new URLSearchParams({{index:String(item.index),v:String(item.cache_key||'')}});
  if(TASK_ID)query.set('task_id',TASK_ID);
  return '/asset-image?'+query.toString();
}}
function updateRuntimeStatus(data) {{ const ai=data.ai_status||{{}},listing=data.listing_status||{{}}; const queueText=MULTI_CONTEXT.active?' | Global queued batches: '+(ai.batch_queue_length||0)+' | Page queue position: '+(ai.task_queue_position||0):'';const aiText=(ai.message||'Waiting for an AI task')+' | Requests in last 60 seconds: '+(ai.recent_60s_requests||0)+'/'+(ai.safe_requests_per_minute||40)+' | Estimated wait: '+(ai.estimated_wait_seconds||0)+' seconds'+queueText;setContent('ai_runtime_status',aiText);setContent('listing_runtime_status',listing.message||'Listing workflow has not started');if(listing.message)setContent('connection_status',listing.message); }}
function unicodeCharacterLength(text) {{ return Array.from(String(text||'')).length; }}
function updateDescriptionCount() {{ const length=unicodeCharacterLength(value('ai_final_description').trim());const el=byId('description_character_count');if(el){{el.textContent=length>3000?'Description length: '+length+' / 3000 ('+(length-3000)+' over; edit manually)':'Description length: '+length+' / 3000';el.className=length>3000?'status-line err':'status-line';}} const title=unicodeCharacterLength(value('ai_title').trim());setContent('title_character_count','Title length: '+title+' / 120'); }}
function selectedModelLabel(id) {{ const model=value(id);return AI_MODEL_CATALOG[model]?.label||model||'-'; }}
function formatToken(value) {{ return Number(value||0).toLocaleString('en-US'); }}
function replaceModelOptions(selectId,allowedModels,fallbackModel) {{
  const select=byId(selectId);if(!select)return;
  const current=select.value;const selected=allowedModels.includes(current)?current:fallbackModel;
  select.innerHTML=allowedModels.map(model=>'<option value="'+escapeHtml(model)+'">'+escapeHtml(AI_MODEL_CATALOG[model]?.label||model)+'</option>').join('');
  select.value=allowedModels.includes(selected)?selected:allowedModels[0];
}}
function updateReasoningStrengthOptions(modelId,strengthId,usage) {{
  const select=byId(strengthId);if(!select)return null;
  const current=select.value||'official_default';const profile=AI_MODEL_CATALOG[value(modelId)]?.[usage]||{{}};
  const labels={{official_default:'Official Default',low:'Low',medium:'Medium',high:'High',maximum:'Maximum'}};
  const order=['official_default','low','medium','high','maximum'];
  select.innerHTML=order.map(level=>{{const token=profile.budgets?.[level]||0;const note=level==='official_default'&&profile.official_default_note?', '+profile.official_default_note:'';return '<option value="'+level+'">'+labels[level]+' ('+(profile.metric||'request output limit')+' '+formatToken(token)+' tokens'+note+')</option>';}}).join('');
  select.value=order.includes(current)?current:'official_default';
  return profile;
}}
function reasoningTokenSummary(modelId,strengthId,usage) {{
  const profile=AI_MODEL_CATALOG[value(modelId)]?.[usage]||{{}};const strength=value(strengthId)||'official_default';
  const primary=(profile.metric||'request output limit')+' '+formatToken(profile.budgets?.[strength])+' tokens';
  const output=Number(profile.output_budgets?.[strength]||0),budget=Number(profile.budgets?.[strength]||0);
  return primary+((profile.metric==='reasoning budget'&&output)?'; complete output limit '+formatToken(output)+' tokens':'');
}}
function updateStepThinkingControls(modelId,thinkingId,strengthId,statusId,usage) {{
  updateReasoningStrengthOptions(modelId,strengthId,usage);
  const mode=value(thinkingId)||'official_default';const strength=byId(strengthId);if(strength)strength.disabled=mode==='disabled';
  const modeText=mode==='disabled'?'Reasoning disabled':mode==='enabled'?'Reasoning enabled':mode==='adaptive'?'Adaptive reasoning':'Official reasoning default';
  const tokenText=mode==='disabled'?'No reasoning budget':reasoningTokenSummary(modelId,strengthId,usage);
  setContent(statusId,'Current: '+selectedModelLabel(modelId)+'; '+modeText+'; '+tokenText);
}}
function updateAiExecutionModeControls() {{
  const multimodal=value('ai_execution_mode')==='multimodal';const allowed=multimodal?MULTIMODAL_AI_MODEL_IDS:VISION_TEXT_AI_MODEL_IDS;
  replaceModelOptions('vision_model',MULTIMODAL_AI_MODEL_IDS,'gpt-5.6');
  replaceModelOptions('keyword_text_model',allowed,'gpt-5.6');
  replaceModelOptions('title_text_model',allowed,'gpt-5.6');
  replaceModelOptions('description_text_model',allowed,'gpt-5.6');
  const objectiveEditor=byId('objective_record_editor');if(objectiveEditor)objectiveEditor.style.display=multimodal?'none':'';
  setContent('ai_execution_mode_status',multimodal?'Current: multimodal model. Step 3 selects and orders images; Steps 5–7 read product images directly.':'Current: vision model + text model. Step 3 provides an objective image record to Steps 5–7.');
  updateVisionThinkingControls();updateKeywordThinkingControls();updateTitleThinkingControls();updateDescriptionThinkingControls();
}}
function updateVisionThinkingControls() {{ updateStepThinkingControls('vision_model','vision_thinking_mode','vision_reasoning_strength','vision_reasoning_setting_status','vision'); }}
function updateSkuSelectionMode() {{ const manual=value('manual_sku_code').trim();if(byId('sku_selection_mode'))byId('sku_selection_mode').value=manual?'manual':'auto';setContent('sku_selection_mode_status',manual?'Current mode: load the specified SKU from the workbook':'Current mode: automatic unlisted SKU selection'); }}
function selectSpecifiedSku() {{ if(byId('sku_selection_mode'))byId('sku_selection_mode').value='manual';callApi('select-candidates'); }}
function selectAutomaticSku() {{ if(byId('manual_sku_code'))byId('manual_sku_code').value='';updateSkuSelectionMode();callApi('select-candidates'); }}
function updateKeywordThinkingControls() {{ updateStepThinkingControls('keyword_text_model','keyword_thinking_mode','keyword_reasoning_strength','keyword_reasoning_setting_status','text'); }}
function updateTitleThinkingControls() {{ updateStepThinkingControls('title_text_model','title_thinking_mode','title_reasoning_strength','title_reasoning_setting_status','text'); }}
function updateDescriptionThinkingControls() {{ updateStepThinkingControls('description_text_model','description_thinking_mode','description_reasoning_strength','description_reasoning_setting_status','text'); }}
async function refreshRuntimeStatus() {{ const response=await fetch('/api/ai-status',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{task_id:TASK_ID}})}});const data=await response.json();updateRuntimeStatus(data);if(data.asset_download_status!==undefined)setContent('asset_download_status',data.asset_download_status);if(data.image_analysis_progress)updateImageProgress(data.image_analysis_progress);if(data.ai_reasoning)updateReasoning(data.ai_reasoning); }}
async function restoreTaskView() {{ try{{const response=await fetch('/api/load-prompts',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{task_id:TASK_ID}})}});const data=await response.json();if(data.ok){{updateResult(data);updateWorkbench(data);}}}}catch(error){{log('Unable to restore the current task view: '+error,'err');}} }}
async function runZiniaoBindingAction(action,manualBindingNotice=false) {{
  const activeButton=document.activeElement instanceof HTMLButtonElement?document.activeElement:null;
  if(activeButton)activeButton.disabled=true;
  try {{
    const data=await executeApiAction(action);
    setContent('ziniao_binding_status',data.message||'Ziniao window action completed');
    updateResult(data);
    if(manualBindingNotice)await notifyActionSuccess(action,data,'manual_step',FULL_WORKFLOW_STEPS[9]);
    return data;
  }} catch(error) {{
    const message=error?.message||String(error);
    const status=byId('ziniao_binding_status');if(status){{status.textContent='Operation failed: '+message;status.className='status-line err';}}
    if(manualBindingNotice&&!isCancelledActionError(error))await notifyActionFailure(action,error,'manual_step',FULL_WORKFLOW_STEPS[9]);
    return null;
  }} finally {{if(activeButton)activeButton.disabled=false;}}
}}
async function refreshZiniaoWindows() {{ return runZiniaoBindingAction('list-ziniao-windows'); }}
async function previewZiniaoWindow() {{
  if(!value('ziniao_window_select')){{setContent('ziniao_binding_status','Select a Ziniao store window first');return null;}}
  return runZiniaoBindingAction('preview-ziniao-window');
}}
async function bindZiniaoWindow() {{
  if(!value('ziniao_window_select')){{
    const error=new Error('Select and locate a Ziniao store window first');
    setContent('ziniao_binding_status',error.message);
    await notifyActionFailure('bind-ziniao-window',error,'manual_step',FULL_WORKFLOW_STEPS[9]);
    return null;
  }}
  return runZiniaoBindingAction('bind-ziniao-window',true);
}}
async function unbindZiniaoWindow() {{ return runZiniaoBindingAction('unbind-ziniao-window'); }}
async function autoBindZiniaoWindowForSelectedStore() {{
  const selectedStore=value('store').trim();
  if(!selectedStore)return null;
  setContent('ziniao_binding_status','Matching and binding a Ziniao window by store name: '+selectedStore);
  try {{
    const data=await executeApiAction('auto-bind-ziniao-window');
    setContent('ziniao_binding_status',data.message||'Automatic Step 9 binding completed');
    return data;
  }} catch(error) {{
    if(isCancelledActionError(error))return null;
    const message=error?.message||String(error);
    const status=byId('ziniao_binding_status');if(status){{status.textContent='Automatic binding failed: '+message;status.className='status-line err';}}
    await notifyActionFailure('auto-bind-ziniao-window',error,'automatic_store_binding',FULL_WORKFLOW_STEPS[9]);
    return null;
  }}
}}
async function handleStoreSelectionChanged() {{
  refreshDescriptionTemplate();
  const selectedStore=value('store').trim();
  setContent('ziniao_task_store','Current task store: '+(selectedStore||'not selected'));
  const status=byId('ziniao_binding_status');const boundStore=status?.dataset.boundStore||'';
  if(boundStore&&boundStore!==selectedStore) {{
    await unbindZiniaoWindow();
    setContent('ziniao_binding_status','The store changed. The previous Ziniao window was unbound; bind the correct window again.');
  }}
  if(selectedStore)await autoBindZiniaoWindowForSelectedStore();
}}
const FULL_WORKFLOW_STEPS=[
  {{number:0,action:'save-ai-settings',label:'Save Configuration'}},
  {{number:1,action:'select-candidates',label:'Select Unlisted SKU'}},
  {{number:2,action:'inspect-assets',label:'Inspect Manual Asset Pack'}},
  {{number:3,action:'analyze-images',label:'Analyze Images'}},
  {{number:4,action:'confirm-image-selection',label:'Confirm Listing Images'}},
  {{number:5,action:'generate-keywords',label:'Generate Search Terms'}},
  {{number:6,action:'analyze-title',label:'Analyze Competitors and Generate Title'}},
  {{number:7,action:'generate-description',label:'Generate Description'}},
  {{number:8,action:'confirm-ai-results',label:'Build Listing Draft'}},
  {{number:9,action:'open-shopee-page',label:'Connect to Shopee'}},
  {{number:10,action:'execute-step1',label:'Fill Shopee Step 1'}},
  {{number:11,action:'execute-step2',label:'Fill Shopee Step 2'}},
  {{number:12,action:'run-checklist',label:'Run Pre-Save Checklist'}},
  {{number:13,action:'save-delist',label:'Save and Delist'}},
  {{number:'13-ID',action:'fetch-product-id',label:'Fetch Product ID by SKU'}},
  {{number:14,action:'',label:'Review Results and Report'}},
  {{number:15,action:'record-listing-result',label:'Write Product ID and SKU to Workbook'}}
];
let fullWorkflowRunning=false;
let fullWorkflowResumeIndex=0;
let fullWorkflowPauseRequested=false;
let fullWorkflowCompletedSteps=new Set();
let fullWorkflowParallelPromises=new Map();
let fullWorkflowCurrentStepIndex=-1;
let fullWorkflowUserCancelled=false;
const activeActionRequests=new Map();
function setFullWorkflowStatus(message,kind) {{ const el=byId('full_workflow_status');if(!el)return;el.textContent=message;el.className='status-line'+(kind?' '+kind:''); }}
function resetFullWorkflowResume() {{ cancelOneClickActionRequests();fullWorkflowParallelPromises.clear();fullWorkflowResumeIndex=0;fullWorkflowPauseRequested=false;fullWorkflowCurrentStepIndex=-1;fullWorkflowUserCancelled=false;fullWorkflowCompletedSteps.clear();const button=byId('full_workflow_button');if(button)button.textContent='Run Full Listing Workflow';const pauseButton=byId('pause_full_workflow_button');if(pauseButton){{pauseButton.disabled=true;pauseButton.textContent='Stop Full Workflow';}} }}
function newActionRequestId() {{ return (globalThis.crypto?.randomUUID?.()||('request_'+Date.now()+'_'+Math.random().toString(16).slice(2))).replaceAll('-','_'); }}
function actionButtonFor(action,preferred) {{
  if(preferred instanceof HTMLButtonElement)return preferred;
  const exact="callApi('"+action+"')";
  return [...document.querySelectorAll('button')].find(button=>(button.getAttribute('onclick')||'').includes(exact))||null;
}}
function markActionButtonRunning(button,requestId) {{
  if(!button)return;
  if(!button.dataset.idleLabel)button.dataset.idleLabel=button.textContent;
  button.dataset.activeRequestId=requestId;
  button.disabled=false;
  button.textContent='Retry: '+button.dataset.idleLabel;
  button.title='Click again to interrupt this wait immediately and use only the new request result.';
}}
function restoreActionButton(button,requestId) {{
  if(!button||button.dataset.activeRequestId!==requestId)return;
  button.textContent=button.dataset.idleLabel||button.textContent;
  button.title='';
  delete button.dataset.activeRequestId;
}}
function cancelledActionError(message,superseded=true) {{
  const error=new Error(message||'Request stopped');
  error.cancelled=true;error.superseded=superseded;
  return error;
}}
function isCancelledActionError(error) {{ return Boolean(error?.cancelled)||error?.name==='AbortError'; }}
async function notifyServerActionCancellation(entry) {{
  try {{
    await fetch('/api/cancel-action',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{task_id:TASK_ID,target_action:entry.action,target_request_id:entry.requestId}})}});
  }} catch(_error) {{}}
}}
function cancelActiveActionEntry(entry,reason) {{
  if(!entry)return;
  entry.cancelReason=reason||'Request stopped';
  entry.controller.abort();
  void notifyServerActionCancellation(entry);
}}
function cancelOneClickActionRequests() {{
  let count=0;
  for(const entry of [...activeActionRequests.values()]) {{
    if(entry.source!=='one_click')continue;
      count+=1;cancelActiveActionEntry(entry,'The full workflow was stopped manually');
  }}
  return count;
}}
function requestPauseFullWorkflow(button) {{
  if(!fullWorkflowRunning){{setFullWorkflowStatus('The full workflow is not running.','status');return;}}
  fullWorkflowPauseRequested=true;fullWorkflowUserCancelled=true;
  const cancelledCount=cancelOneClickActionRequests();
  if(button){{button.disabled=true;button.textContent='Stopping';}}
  const step=FULL_WORKFLOW_STEPS[fullWorkflowCurrentStepIndex]||null;
  setFullWorkflowStatus('Stopping '+(step?('Step '+step.number+': '+step.label):'the current step')+' immediately; no AI timeout wait is required.','status');
  log('Full workflow stopped manually; '+cancelledCount+' pending requests were invalidated.','ok');
}}
function stepForAction(action) {{ return FULL_WORKFLOW_STEPS.find(step=>step.action===action)||{{number:'',label:action||'Unknown action',action:action||''}}; }}
async function notifyActionFailure(action,error,failureSource,stepOverride) {{
  const step=stepOverride||stepForAction(action);
  const failureMessage=error?.message||String(error||'Unknown error');
  try {{
    const response=await fetch('/api/send-workflow-failure',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{store:value('store'),failed_step_number:step.number,failed_step_label:step.label,failed_action:step.action||action,failure_source:failureSource||'manual_step',error_message:failureMessage}})}});
    const notice=await response.json();
      setContent('wechat_notification_status',notice.message||'Failure-notification status unknown');
    const reminderOk=Boolean(notice.popup_shown)||Boolean(notice.notification_sent);
      log((reminderOk?'Failure notification: ':'Failure notification call failed: ')+(notice.message||''),reminderOk?'ok':'err');
  }} catch(noticeError) {{
    setContent('wechat_notification_status','The Windows alert or messaging notification failed; the original operation error is unchanged.');
    log('Failure notification call failed: '+noticeError,'err');
  }}
}}
async function notifyActionSuccess(action,data,successSource,stepOverride) {{
  const step=stepOverride||stepForAction(action);
  try {{
    const response=await fetch('/api/send-action-success',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{store:value('store'),step_number:step.number,step_label:step.label,action:step.action||action,success_source:successSource||'manual_step',summary:data?.message||'Operation completed successfully'}})}});
    const notice=await response.json();
    if(!notice.ok)throw new Error(notice.message||'Completion notification call failed');
    log('Completion notification: '+(notice.message||'Windows topmost completion alert shown'),'ok');
  }} catch(noticeError) {{
    log('Completion notification call failed: '+noticeError,'err');
  }}
}}
async function executeApiAction(action,preferredButton=null) {{
  log('Started: '+action);
  if(action==='analyze-images')reasoningDisplayCleared.vision=false;
  if(action==='generate-keywords')reasoningDisplayCleared.keywords=false;
  if(action==='analyze-title')reasoningDisplayCleared.title=false;
  if(action==='generate-description')reasoningDisplayCleared.description=false;
  let actionEntry=null;
  try {{
    const requestPayload=payload();
    if(action==='confirm-ai-results') {{
      const finalDescription=String(requestPayload.ai_final_description||'').trim();
      const finalDescriptionLength=unicodeCharacterLength(finalDescription);
    if(!finalDescription)throw new Error('The final product description cannot be empty.');
    if(finalDescriptionLength>3000)throw new Error('Step 8 was not submitted: the final description is '+finalDescriptionLength+' characters. Edit it to 3,000 characters or fewer; the app will not compress or alter it automatically.');
      requestPayload.ai_final_description=finalDescription;
      requestPayload.ai_final_description_length=finalDescriptionLength;
    }}
    requestPayload.workflow_source=fullWorkflowRunning?'one_click':'manual_step';
    const previous=activeActionRequests.get(action);
    if(previous) {{
    cancelActiveActionEntry(previous,'Superseded by a new retry for the same step');
    log('The previous '+action+' request was interrupted; only the new retry result will be used.','ok');
    }}
    const requestId=newActionRequestId();
    const controller=new AbortController();
    const actionButton=requestPayload.workflow_source==='manual_step'
      ?actionButtonFor(action,preferredButton)
      :null;
    const entry={{action,requestId,controller,button:actionButton,source:requestPayload.workflow_source,cancelReason:''}};
    actionEntry=entry;
    activeActionRequests.set(action,entry);
    markActionButtonRunning(actionButton,requestId);
    requestPayload._request_id=requestId;
    let response;
    try {{
      response=await fetch('/api/'+action,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(requestPayload),signal:controller.signal}});
    }} catch(error) {{
    if(error?.name==='AbortError')throw cancelledActionError(entry.cancelReason||'Request stopped');
      throw error;
    }}
    const data=await response.json();
    if(activeActionRequests.get(action)?.requestId!==requestId)throw cancelledActionError('The old request was superseded by a new retry');
    if(data.cancelled||data.superseded)throw cancelledActionError(data.message||'The old request was invalidated');
    log((data.ok?'Success: ':'Failure: ')+(data.message||action),data.ok?'ok':'err');
    if(data.notification_sent!==undefined)setContent('wechat_notification_status',data.message||'Notification status updated');
    updateResult(data);updateWorkbench(data);
    if(data.image_analysis_progress)updateImageProgress(data.image_analysis_progress);
    if(!data.ok){{const error=new Error(data.message||('Step failed: '+action));error.apiFailure=true;throw error;}}
    return data;
  }} catch(error) {{
    if(!isCancelledActionError(error)&&!error.apiFailure)log('Failure: '+error,'err');
    throw error;
  }} finally {{
    const entry=activeActionRequests.get(action);
    if(actionEntry&&entry&&entry.requestId===actionEntry.requestId) {{
      activeActionRequests.delete(action);
      restoreActionButton(entry.button,entry.requestId);
    }}
  }}
}}
function configuredFullWorkflowRetryCount() {{
  const parsed=Number.parseInt(value('full_workflow_auto_retry_count')||'1',10);
  return Number.isFinite(parsed)?Math.min(5,Math.max(1,parsed)):1;
}}
function currentDescriptionValidation() {{
  const text=String(value('ai_final_description')||'').trim();
  const length=unicodeCharacterLength(text);
  return {{text,length,ok:Boolean(text)&&length<=3000}};
}}
async function executeFullWorkflowStepWithRetry(step,actionOverride='') {{
  const action=actionOverride||step.action;
  const retryLimit=configuredFullWorkflowRetryCount();
  let retryAttempt=0;
  while(true) {{
    if(fullWorkflowUserCancelled)throw cancelledActionError('The full workflow was stopped manually');
    try {{
      return await executeApiAction(action);
    }} catch(error) {{
      if(fullWorkflowUserCancelled||isCancelledActionError(error))throw error;
      if(retryAttempt>=retryLimit)throw error;
      retryAttempt+=1;
      const failureMessage=error?.message||String(error);
      setFullWorkflowStatus(
        'Step '+step.number+' failed. Automatic retry '+retryAttempt+'/'+retryLimit+': '+failureMessage,
        'status'
      );
      log(
        'Step '+step.number+' automatic retry '+retryAttempt+'/'+retryLimit+': '+failureMessage,
        'ok'
      );
      await new Promise(resolve=>window.setTimeout(resolve,800));
      if(fullWorkflowUserCancelled)throw cancelledActionError('The full workflow was stopped manually');
    }}
  }}
}}
function parallelWorkflowError(error,stepIndex) {{
  const normalized=error instanceof Error?error:new Error(String(error||'Parallel step failed'));
  normalized.parallelStepIndex=stepIndex;
  return normalized;
}}
function startOrReuseParallelWorkflowStep(stepIndex) {{
  const step=FULL_WORKFLOW_STEPS[stepIndex];
  const existing=fullWorkflowParallelPromises.get(step.number);
  if(existing)return existing;
  let trackedPromise=null;
  trackedPromise=(async()=>{{
    try {{
      const data=await executeFullWorkflowStepWithRetry(step);
      fullWorkflowCompletedSteps.add(step.number);
      return data;
    }} catch(error) {{
      const normalized=parallelWorkflowError(error,stepIndex);
      if(!fullWorkflowUserCancelled&&!isCancelledActionError(normalized)) {{
        normalized.parallelFailureNotified=true;
        setFullWorkflowStatus(
          'Step '+step.number+' exhausted its automatic retries and stopped. The other parallel step continues independently. Click Run Full Listing Workflow again to retry only Step '+step.number+'.',
          'err'
        );
        log('Step '+step.number+' failed independently and will be handled without waiting for the other parallel step.','err');
        void notifyActionFailure(step.action,normalized,'one_click',step);
      }}
      throw normalized;
    }} finally {{
      if(fullWorkflowParallelPromises.get(step.number)===trackedPromise)fullWorkflowParallelPromises.delete(step.number);
    }}
  }})();
  fullWorkflowParallelPromises.set(step.number,trackedPromise);
  return trackedPromise;
}}
async function waitForRunningParallelWorkflowSteps() {{
  const pending=[];
  for(const stepIndex of [6,7]) {{
    const step=FULL_WORKFLOW_STEPS[stepIndex];
    if(fullWorkflowCompletedSteps.has(step.number))continue;
    const running=fullWorkflowParallelPromises.get(step.number);
    if(!running)throw parallelWorkflowError(new Error('Step '+step.number+' has not completed successfully. Retry that step first.'),stepIndex);
    pending.push(running);
  }}
  await Promise.all(pending);
}}
async function ensureDescriptionReadyForStep8() {{
  let validation=currentDescriptionValidation();
  if(validation.ok)return;
  const descriptionStep=FULL_WORKFLOW_STEPS[7];
  fullWorkflowCompletedSteps.delete(descriptionStep.number);
  const reason=!validation.text
    ?'the final product description is empty'
    :'the final product description is '+validation.length+' characters, exceeding the 3,000-character limit';
  setFullWorkflowStatus(
    'Step 8 precheck failed because '+reason+'. Returning to Step 7 to regenerate the description.',
    'status'
  );
  log('Step 8 detected that '+reason+'; returning to Step 7 automatically.','ok');
  await executeFullWorkflowStepWithRetry(descriptionStep);
  fullWorkflowCompletedSteps.add(descriptionStep.number);
  validation=currentDescriptionValidation();
  if(!validation.ok) {{
    throw new Error(
      !validation.text
        ?'The final description is still empty after retrying Step 7. Edit it manually.'
        :'The final description is still '+validation.length+' characters after retrying Step 7. Edit it to 3,000 characters or fewer.'
    );
  }}
}}
async function callApi(action) {{
  if(fullWorkflowRunning){{log('The full listing workflow is already running. Wait for the active workflow to finish.','err');return;}}
  const activeButton=document.activeElement instanceof HTMLButtonElement?document.activeElement:null;
  const timer=setInterval(refreshRuntimeStatus,1000);
  try {{
    const data=await executeApiAction(action,activeButton);
    if(action==='select-candidates')resetFullWorkflowResume();
    if(action==='fetch-product-id')setContent('fetch_product_id_status',data.message||'Product ID fetched');
    await notifyActionSuccess(action,data,'manual_step');
    return data;
  }} catch(error) {{
    if(isCancelledActionError(error)){{log('The old request was stopped; the new retry request is active.','ok');return null;}}
    if(action==='fetch-product-id'||(action==='record-listing-result'&&isMissingProductIdFailure(error))) {{
      prepareProductIdRetry(error.message||String(error));
    }}
    await notifyActionFailure(action,error,'manual_step');
    return null;
  }} finally {{clearInterval(timer);}}
}}
async function saveCredentials() {{
  const data=await callApi('save-ai-settings');
  if(data?.ok)byId('credentials_dialog').close();
}}
async function clearOldCache() {{
  const confirmed=window.confirm('This clears old app-generated logs, reports, screenshots, titles, descriptions, and AI results.\\n\\nIt preserves API keys, store configuration, Ziniao bindings, application files, the workbook, and manually supplied asset packs.\\n\\nContinue?');
  if(!confirmed)return;
  setContent('cache_cleanup_status','Cleaning generated cache files...');
  const data=await callApi('cleanup-cache');
  if(data?.ok){{setContent('cache_cleanup_status',data.message||'Cache cleanup completed');window.setTimeout(()=>window.location.reload(),900);}}
}}
async function runFullWorkflow(button) {{
  if(fullWorkflowRunning)return;
  if(button)button.disabled=true;
  setFullWorkflowStatus('Verifying the manual binding between this task and the Ziniao store window','status');
  try {{
    await executeFullWorkflowStepWithRetry(FULL_WORKFLOW_STEPS[9],'validate-ziniao-binding');
  }} catch(error) {{
    setFullWorkflowStatus('The full workflow did not start. Go to Step 9, locate the correct Ziniao store window, and confirm the binding. '+(error?.message||error),'err');
    await notifyActionFailure('open-shopee-page',error,'one_click',FULL_WORKFLOW_STEPS[9]);
    if(button)button.disabled=false;
    return;
  }}
  fullWorkflowRunning=true;
  fullWorkflowPauseRequested=false;
  fullWorkflowUserCancelled=false;
  if(button)button.disabled=true;
  const pauseButton=byId('pause_full_workflow_button');if(pauseButton){{pauseButton.disabled=false;pauseButton.textContent='Stop Full Workflow';}}
  const mode=byId('run_mode');if(mode)mode.value='save_delist';
  if(fullWorkflowResumeIndex<0||fullWorkflowResumeIndex>=FULL_WORKFLOW_STEPS.length)fullWorkflowResumeIndex=0;
  const startIndex=fullWorkflowResumeIndex;
  const startStep=FULL_WORKFLOW_STEPS[startIndex];
  setFullWorkflowStatus(startIndex>0?'Retrying from failed Step '+startStep.number+' and continuing.':'Full listing workflow started in Save and Delist mode.','status');
  const timer=setInterval(refreshRuntimeStatus,1000);
  let currentStep=null;
  let currentStepIndex=startIndex;
  let paused=false;
  try {{
    for(let index=startIndex;index<FULL_WORKFLOW_STEPS.length;index+=1) {{
      const step=FULL_WORKFLOW_STEPS[index];
      if(fullWorkflowCompletedSteps.has(step.number)){{fullWorkflowResumeIndex=index+1;continue;}}
      currentStep=step;
      currentStepIndex=index;
      fullWorkflowCurrentStepIndex=index;
      if(index===6) {{
        setFullWorkflowStatus('Prechecking Step 6/15: confirming that real competitor titles were supplied','status');
        await executeFullWorkflowStepWithRetry(FULL_WORKFLOW_STEPS[6],'validate-competitors');
        const parallelIndexes=[6,7].filter(stepIndex=>!fullWorkflowCompletedSteps.has(FULL_WORKFLOW_STEPS[stepIndex].number));
        setFullWorkflowStatus('Running Steps 6/15 and 7/15 in parallel: generating the title and description','status');
        try {{
          await Promise.all(
            parallelIndexes.map(stepIndex=>startOrReuseParallelWorkflowStep(stepIndex))
          );
        }} catch(error) {{
          const failedStepIndex=Number.isInteger(error?.parallelStepIndex)?error.parallelStepIndex:index;
          currentStepIndex=failedStepIndex;
          currentStep=FULL_WORKFLOW_STEPS[failedStepIndex];
          throw error;
        }}
        fullWorkflowResumeIndex=8;
        if(fullWorkflowPauseRequested) {{
          paused=true;
          if(button)button.textContent='Continue Full Workflow';
          setFullWorkflowStatus('Full workflow paused after Steps 6 and 7 completed. Click Continue Full Workflow to resume at Step 8.','status');
          log('Full workflow paused; the next run resumes at Step 8.','ok');
          break;
        }}
        index=7;
        continue;
      }}
      setFullWorkflowStatus('Running Step '+step.number+'/15: '+step.label,'status');
      if(step.number===8) {{
        try {{
          await waitForRunningParallelWorkflowSteps();
        }} catch(error) {{
          const failedStepIndex=Number.isInteger(error?.parallelStepIndex)?error.parallelStepIndex:index;
          currentStepIndex=failedStepIndex;
          currentStep=FULL_WORKFLOW_STEPS[failedStepIndex];
          throw error;
        }}
        await ensureDescriptionReadyForStep8();
      }}
      if(step.number===15&&!hasProductIdForWriteback()) {{
        const fetchIndex=FULL_WORKFLOW_STEPS.findIndex(item=>item.action==='fetch-product-id');
        const fetchStep=FULL_WORKFLOW_STEPS[fetchIndex];
        fullWorkflowCompletedSteps.delete(fetchStep.number);
        currentStepIndex=fetchIndex;
        currentStep=fetchStep;
        prepareProductIdRetry('Step 15 paused: no product ID is available. Return to Step 13 and retry the fetch.');
        throw new Error('A product ID is required before Step 15 can write back to the workbook.');
      }}
      if(step.action)await executeFullWorkflowStepWithRetry(step);
      else log('Success: Step 14 final results and report were generated and displayed','ok');
      fullWorkflowCompletedSteps.add(step.number);
      fullWorkflowResumeIndex=index+1;
      if(fullWorkflowPauseRequested&&fullWorkflowResumeIndex<FULL_WORKFLOW_STEPS.length) {{
        const nextStep=FULL_WORKFLOW_STEPS[fullWorkflowResumeIndex];
        paused=true;
        if(button)button.textContent='Continue Full Workflow';
        setFullWorkflowStatus('Full workflow paused after Step '+step.number+'. Click Continue Full Workflow to resume at Step '+nextStep.number+'.','status');
        log('Full workflow paused; the next run resumes at Step '+nextStep.number+'.','ok');
        break;
      }}
    }}
    if(paused)return;
    resetFullWorkflowResume();
    setFullWorkflowStatus('Full listing workflow completed: Steps 0–15 all succeeded.','ok');
    await notifyActionSuccess('',{{message:'Steps 0–15 all succeeded'}},'one_click',{{number:'0–15',label:'All steps completed',action:''}});
  }} catch(error) {{
    if(currentStep?.number===15&&isMissingProductIdFailure(error)) {{
      const fetchIndex=FULL_WORKFLOW_STEPS.findIndex(item=>item.action==='fetch-product-id');
      currentStepIndex=fetchIndex;
      currentStep=FULL_WORKFLOW_STEPS[fetchIndex];
      fullWorkflowCompletedSteps.delete(currentStep.number);
      prepareProductIdRetry('Step 15 has no product ID to write. Return to Step 13 and retry the fetch.');
    }}
    fullWorkflowResumeIndex=currentStepIndex;
    const failureMessage=error.message||String(error);
    if(button)button.textContent='Retry Step '+(currentStep?.number??'')+' and Continue';
    if(fullWorkflowUserCancelled||isCancelledActionError(error)) {{
      setFullWorkflowStatus('Step '+(currentStep?.number??'')+' stopped immediately. The old request result is invalid; click again to restart this step and continue.','status');
      log('Full workflow stopped; the next run starts a new request for Step '+(currentStep?.number??'')+'.','ok');
    }} else {{
      setFullWorkflowStatus('Step '+(currentStep?.number??'')+' failed: '+failureMessage+'. Correct the issue and click again to retry this step.','err');
      if(!error?.parallelFailureNotified)await notifyActionFailure(currentStep?.action||'',error,'one_click',currentStep);
    }}
  }} finally {{
    clearInterval(timer);fullWorkflowRunning=false;fullWorkflowPauseRequested=false;fullWorkflowCurrentStepIndex=-1;fullWorkflowUserCancelled=false;if(button)button.disabled=false;if(pauseButton){{pauseButton.disabled=true;pauseButton.textContent='Stop Full Workflow';}}
  }}
}}
updateAiExecutionModeControls();
async function initializeTaskPage() {{
  if(byId('asset_path'))byId('asset_path').value='';
  await restoreTaskView();
  setContent('ziniao_task_store','Current task store: '+value('store'));
  await refreshZiniaoWindows();
  updateSidebarToggleLabel();
  updateActiveSidebarStep();
}}
initializeTaskPage();
</script>
</body></html>"""


def _step(number: int, title: str, description: str, body: str) -> str:
    return f'''<section id="workflow-step-{number}" class="workflow-step" data-step="{number}"><div class="step-heading"><div class="step-number">{number}</div><div><h2>Step {number}: {title}</h2><p>{description}</p></div></div><div class="step-body">{body}</div></section>'''
