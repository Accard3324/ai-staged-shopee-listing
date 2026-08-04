# Release audit — 2026-08-04

## Scope

This audit covers only the isolated open-source release copy prepared for public GitHub publication.

## Requested release changes

| Requirement | Verified release state |
| --- | --- |
| Keep the operational edition separate | This source release is an independent directory with no runtime, workbook, business output, or populated `.env`. |
| Remove API keys | `.env` is absent; every credential field in `.env.example` is blank; known secret-prefix scans report no match. |
| Use real model IDs | Selectors show `gpt-5.6`, `agnes-2.0-flash`, `qwen/qwen3.5-397b-a17b`, `minimaxai/minimax-m3`, and `z-ai/glm-5.2`. |
| Remove the retired external CLI/API integration | No source, test, configuration, documentation, action, executable, or string reference remains. |
| Manual asset path only | Step 2 accepts a local folder/archive path; automatic download is labeled planned and has no action handler. |
| Add OpenAI and make it the default | `AI_PROVIDER=openai`; Steps 3, 5, 6, and 7 default to `gpt-5.6`; OpenAI text and multimodal request tests pass. |
| Default Step 0 to multimodal | Both configuration and rendered UI select `multimodal` by default. |
| Clear Step 3/5/6/7 prompts | The four saved defaults, code fallbacks, and corresponding prompt files are blank; an explicit blank value is preserved at runtime. |
| Clear store-description templates | Every bundled `description_templates` value is blank, new custom stores start with a blank template, and the interface can save an empty template. |
| Add and save custom store names | Step 0 accepts a custom name, persists it in `config/stores.yaml`, and reuses the selected store's source status column and result sheet. |
| English interface | Rendered operator copy, launchers, documentation, and runtime messages are English. Blank starter prompts contain no localized copy. |
| Public identity | `CITATION.cff`, `NOTICE`, README, provenance, and publication instructions identify GitHub account `vip-jiekaixu` and repository `https://github.com/vip-jiekaixu/ai-staged-shopee-listing`. |

Localized Shopee text remains only in deterministic page-recognition patterns and synthetic compatibility fixtures. Those strings identify controls shown by Seller Centre and are not application-interface copy.

## Included

- Application source under `src/`.
- Offline regression tests under `tests/`.
- Sanitized example configuration with blank AI-stage prompts and blank store-description templates.
- English Windows launchers and project-local Python setup script.
- 7zr and UnRAR archive tools with their existing license and metadata files.
- Apache-2.0 license, governance, security, provenance, contribution, CI, architecture, and Codex for Open Source preparation documents.

## Excluded

- Populated `.env` files and credential values.
- Private Python runtimes and virtual environments.
- Real workbooks, store configuration, product assets, logs, screenshots, HTML snapshots, AI caches, listing drafts, and result files.
- Automatic asset-download code and executables.
- Live-AI acceptance scripts tied to private assets or credentials.

## Verification results

- Python import and offline regression suite: `Ran 209 tests ... OK`.
- Web GUI structural smoke check: `Web GUI check OK`.
- English launcher smoke check: `start_app.bat --check` passed with the bundled validation runtime.
- Rendered workflow check: all Steps 0–15 are present in order, Step 0 selects multimodal mode, every AI stage defaults to `gpt-5.6`, and no Han character is present.
- Prompt/template check: Step 3/5/6/7 prompt values and all bundled description templates are empty; legacy prompt files are zero bytes.
- Custom-store check: persistence is idempotent, the selected status-column/result-sheet mapping is retained, and the new template is blank.
- Removed-integration scan: no match in source, tests, configuration, prompts, launchers, or documentation.
- Secret-prefix and private-key scan: no match.
- Repository-root check: no `.env`, runtime directory, virtual environment, workbook, business report, screenshot, or HTML snapshot is included.

## Remaining limits

- Verification is offline and structural; it does not contact OpenAI, perform a real Shopee listing, or use an authenticated browser account.
- Custom store names inherit the selected store mapping. A different workbook status column or result sheet must be configured explicitly.
- Marketplace selectors can require maintenance after Shopee Seller Centre changes.
- The prior-art report is preliminary, not a patent opinion or proof of worldwide novelty.
- The publisher must review the staged Git files, confirm the intended repository URL, and explicitly choose public visibility before publishing.
