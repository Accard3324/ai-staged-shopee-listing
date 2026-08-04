from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Dict, Iterable

from ...browser.cdp_client import CdpClient
from .image_uploader import set_file_input_files


def video_upload_status_script() -> str:
    return r"""
(() => {
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const norm = text => String(text || "").replace(/\s+/g, " ").trim();
  const inputs = [...document.querySelectorAll('input[type="file"]')];
  const videoInput = inputs.find(input => /video|mp4/i.test(input.accept || ""));
  const scope = document.querySelector('[data-product-edit-field-unique-id="video"]')
    || videoInput?.closest(".edit-row,[class*='edit-row'],section")
    || [...document.querySelectorAll(".edit-row,[class*='edit-row'],section")].find(item => /商品影片|Product Video/i.test(norm(item.innerText)));
  const scopeText = norm(scope?.innerText || "");
  const previewNodes = scope ? [...scope.querySelectorAll("video,.video-container img,[class*='video-preview'] img,[class*='video-cover'] img")].filter(visible) : [];
  const hasDuration = /\b\d{2}:\d{2}\b/.test(scopeText);
  const progress = scopeText.match(/(?:^|\s)(\d{1,3})%(?:\s|$)/);
  const processing = /上传中|处理中|正在处理|Uploading|Processing/i.test(scopeText) || !!(progress && Number(progress[1]) < 100);
  const failed = /上传失败|处理失败|格式错误|Upload failed|Processing failed|Invalid video/i.test(scopeText);
  const addOnly = /添加影片|Add Video/i.test(scopeText) && previewNodes.length === 0;
  return {
    hasVideoArea: !!scope,
    inputIndex: videoInput ? inputs.indexOf(videoInput) : -1,
    inputAccept: videoInput?.accept || "",
    scopeText,
    previewCount: previewNodes.length,
    processing,
    failed,
    hasDuration,
    progressPercent: progress ? Number(progress[1]) : null,
    uploaded: !!scope && !failed && !processing && !addOnly && hasDuration && previewNodes.length > 0,
    editModalVisible: [...document.querySelectorAll(".local-edit-video-container,.eds-modal__box,[role='dialog']")]
      .filter(visible).some(item => /影片|视频|Video/i.test(norm(item.innerText)))
  };
})()
"""


def video_modal_confirm_script() -> str:
    return r"""
(() => {
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const norm = text => String(text || "").replace(/\s+/g, " ").trim();
  const dialogs = [...document.querySelectorAll(".local-edit-video-container,.eds-modal__box,[role='dialog']")].filter(visible);
  if (!dialogs.length) return { found: false, confirmed: false };
  const dialog = dialogs.find(item => /影片|视频|Video/i.test(norm(item.innerText))) || dialogs[dialogs.length - 1];
  const button = [...dialog.querySelectorAll("button")].filter(visible)
    .find(item => /^(完成|确认|保存|Done|Confirm|Save)$/i.test(norm(item.innerText)) && !item.disabled);
  if (!button) return { found: true, confirmed: false, buttons: [...dialog.querySelectorAll("button")].filter(visible).map(item => norm(item.innerText)) };
  button.click();
  return { found: true, confirmed: true, text: norm(button.innerText) };
})()
"""


def upload_product_video(client: CdpClient, paths: Iterable[str], timeout_seconds: int = 120) -> Dict[str, Any]:
    videos = [str(Path(path)) for path in paths if str(path)]
    if not videos:
        return {"ok": True, "required": False, "action": "no_video_in_asset_manifest"}
    video = videos[0]
    if not Path(video).is_file():
        raise RuntimeError(f"Product video file not found: {video}")
    before = client.evaluate(video_upload_status_script()).get("result", {}).get("value", {})
    if before.get("uploaded"):
        return {"ok": True, "required": True, "action": "already_uploaded", "status": before, "file": video}
    input_index = int(before.get("inputIndex", -1))
    if input_index < 0:
        raise RuntimeError(f"The Step 2 product-video upload control was not found: {before}")
    set_file_input_files(client, input_index, [video])
    time.sleep(2)
    modal = client.evaluate(video_modal_confirm_script()).get("result", {}).get("value", {})
    deadline = time.time() + timeout_seconds
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        last = client.evaluate(video_upload_status_script()).get("result", {}).get("value", {})
        if last.get("failed"):
            raise RuntimeError(f"Product video upload or processing failed: {last}")
        if last.get("uploaded"):
            return {"ok": True, "required": True, "action": "uploaded", "file": video, "modal": modal, "status": last}
        if last.get("editModalVisible") and not modal.get("confirmed"):
            modal = client.evaluate(video_modal_confirm_script()).get("result", {}).get("value", {})
        time.sleep(2)
    raise RuntimeError(f"Product video upload and processing did not finish within {timeout_seconds} seconds: {last}")


VIDEO_UPLOAD_STATUS_SCRIPT = video_upload_status_script()
