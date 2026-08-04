# AI-Staged Shopee Listing App

A local-first, open-source reference implementation for preparing high-quality Shopee Malaysia listings with AI and then executing the approved listing with a fixed, testable program flow.

The central method is **AI staging, deterministic execution**.


Public maintainer and repository owner: [`@vip-jiekaixu`](https://github.com/vip-jiekaixu)

## Core workflow proposition

This project publicly documents a three-part workflow:

1. **AI prepares the judgment-heavy listing material before browser execution**—including image understanding and selection, search terms, product titles, and detail-page descriptions.
2. **The operator reviews and approves the prepared material**, which is frozen into a reusable, schema-validated listing packet.
3. **Deterministic software operates the authenticated seller backend** and fills routine product fields through a fixed, testable sequence with validation gates, Save-and-Delist verification, and workbook write-back.

This separation reduces repeated token use and avoids asking a live general-purpose agent to rediscover the same browser controls for every SKU. In version `0.1.0`, AI-assisted image analysis and selection, title generation, and description generation are implemented. Generation of new product images or main images remains planned and is not represented as implemented in this release.

```mermaid
flowchart LR
    A["Workbook + manually supplied product assets"] --> B["AI analysis and content staging"]
    B --> C["Human review and edits"]
    C --> D["Approved listing_draft.json"]
    D --> E["Deterministic CDP form runner"]
    E --> F["Pre-save checklist and stop gates"]
    F --> G["Save and Delist"]
    G --> H["Verify, write back, and preserve evidence"]
```

## Why this approach

General-purpose AI agents and skills are excellent at research, interpretation, and judgment. They are less efficient when every SKU requires the agent to reload rules, rediscover page controls, reason through routine fields, and spend tokens on repeated browser work.

This project separates the work:

- AI handles image understanding, search-term preparation, competitor-title analysis, title drafting, and description drafting.
- The operator reviews and edits the generated material before it is used.
- Deterministic code handles workbook input, schema checks, browser connection, field filling, pre-save gates, result verification, and workbook write-back.

| Concern | Full live-agent execution | This project |
| --- | --- | --- |
| AI scope | Reasoning throughout every run | Bounded content-preparation stages |
| Browser actions | Reinterpreted for each SKU | Fixed, regression-tested components |
| Retry cost | May repeat context and model work | Reuses cached analysis and an approved draft |
| Auditability | Mostly conversation history | JSON packet, checklist, reports, screenshots, and HTML |
| Failure behavior | Depends on the current agent state | Stops at a failed gate before saving |

## Implemented capabilities

- Select an unlisted SKU from a configurable Excel workbook.
- Add and persist a custom store name in Step 0 by reusing a selected store's workbook mapping.
- Load a manually supplied product asset pack from a local folder or ZIP, RAR, or 7Z archive.
- Analyze each image independently and keep objective image facts separate from image-selection judgments.
- Review and edit image choices, search terms, competitor-title analysis, the final title, and description content.
- Validate structured AI output and create a reusable `listing_draft.json` packet.
- Reuse an already authenticated Ziniao Browser session through Chrome DevTools Protocol without storing browser credentials in the repository.
- Fill Shopee Seller Centre fields for images, video, category, brand, certification, description, variations, prices, stock, SKU, GTIN, packaging, and logistics.
- Run a strict pre-save checklist, use **Save and Delist**, verify the unlisted result and product ID, and append the result to the workbook.
- Preserve failure evidence and resume from prepared artifacts instead of repeating all AI work.

Automatic asset-pack download is intentionally shown as **planned** and is not implemented in this release. AI product-image generation is also a roadmap item, not a current capability.

## AI defaults

The default provider is OpenAI and the default model for Steps 3, 5, 6, and 7 is the real model ID `gpt-5.6`. Step 0 defaults to `multimodal` mode.

The editable prompts for Steps 3, 5, 6, and 7 are intentionally blank in the public starter configuration. The application preserves a saved blank prompt instead of silently restoring hidden prompt text. Operators can enter and save their own prompts in the relevant step panels. The separate Shopee category-selection prompt remains populated because it belongs to a later deterministic page step.

The model selectors display real model IDs only:

- `gpt-5.6`
- `agnes-2.0-flash`
- `qwen/qwen3.5-397b-a17b`
- `minimaxai/minimax-m3`
- `z-ai/glm-5.2`

The current adapter uses OpenAI Chat Completions for compatibility with the existing structured JSON pipeline. See the official [OpenAI model catalog](https://developers.openai.com/api/docs/models), [`gpt-5.6-sol` model page](https://developers.openai.com/api/docs/models/gpt-5.6-sol), and [latest-model guidance](https://developers.openai.com/api/docs/guides/latest-model).

## Safety boundaries

- The automated path does **not** click “Save and Publish.”
- The repository contains no populated `.env` file and no real API key.
- Local keys belong only in an ignored `.env` file; password fields never reveal saved values.
- Browser credentials, private workbooks, business outputs, logs, screenshots, and authenticated browser data are excluded from source control.
- A failed validation or platform save stops the workflow before product-ID lookup and workbook write-back.
- External APIs remain subject to their own terms, availability, and pricing.

## Current scope

- Windows 10/11, 64-bit.
- Shopee Malaysia Seller Centre through Ziniao Browser.
- Python 3.10 or newer; application runtime code uses the Python standard library.
- English operator interface, documentation, and runtime messages; public starter prompts for Steps 3, 5, 6, and 7 are blank.
- Localized Shopee text is retained only inside page-recognition rules needed to operate Seller Centre safely.

This is an independent community project. It is not affiliated with, endorsed by, or an official product of Shopee, Ziniao, NVIDIA, Agnes AI, or OpenAI.

## Quick start

1. Clone or download this repository on Windows 10/11 64-bit.
2. Copy `.env.example` to `.env` and add your own `OPENAI_API_KEY`.
3. Edit `config/workbook.yaml` and `config/stores.yaml` for your workbook and stores.
4. Sign in to Ziniao Browser and open the intended Shopee store.
5. Double-click `start_app.bat`.
6. In Step 0, select an existing workbook mapping, enter the actual store name under **Custom Store Name**, and choose **Add and Save Store**.

Each store mapping in `config/stores.yaml` contains a source-workbook `status_column`, a result `listing_sheet`, and a `template_key`. A custom name inherits the selected store's source column and result sheet, is saved back to `config/stores.yaml`, and receives its own blank description template. If a store needs different workbook columns or a different write-back sheet, define that base mapping in the configuration before adding the name.

Check the runtime without opening the live workflow:

```text
start_app.bat --check
```

Run the offline test suite:

```powershell
py -3 -X utf8 -m unittest discover -s tests -p "test_*.py"
```

## Repository map

- `src/shopee_listing_app/` — application, AI adapters, CDP client, Shopee components, workbook logic, and reporting.
- `config/` — example store, workbook, prompt, and AI configuration.
- `prompts/` — blank starter files for the editable Step 3, 6, and 7 prompts; Step 5 is stored in `config/prompts.yaml`.
- `tests/` — offline regression tests with synthetic data.
- `tools/archive/` — separately licensed archive extraction utilities and notices.
- `docs/ARCHITECTURE.md` — design and trust boundaries.
- `docs/ORIGINALITY_AND_PROVENANCE.md` — authorship/publication record and limits of a “first” claim.
- `docs/CODEX_FOR_OSS_APPLICATION.md` — evidence-based Codex for Open Source application worksheet.
- `docs/RELEASE_NOTES_v0.1.0.md` — copy-ready text for the first GitHub Release.
- `ROADMAP.md` — planned work, kept separate from implemented features.

## Codex for Open Source readiness

The repository includes an Apache-2.0 license, contribution and security policies, a code of conduct, Windows CI, a citation file, architecture documentation, a provenance record, and a publication checklist. The application worksheet follows the official [Codex for Open Source program page](https://developers.openai.com/community/codex-for-oss), [application form](https://openai.com/form/codex-for-oss/), and [program terms](https://learn.chatgpt.com/docs/codex-for-oss-terms).

Program acceptance is discretionary. A new repository should not invent adoption metrics; public maintenance activity, reproducible releases, independent users, and real contributions are stronger evidence than an unsupported novelty claim.

## Originality and public record

This repository documents GitHub user [`@vip-jiekaixu`](https://github.com/vip-jiekaixu)'s independently developed implementation of the combined AI-staging/deterministic-execution workflow described here. A public GitHub commit, signed tag, release, checksum, and independent archive can establish that this exact source was publicly disclosed no later than those timestamps.

Those records do **not** prove that nobody in the world proposed a similar idea earlier. The defensible claim is independent implementation and a verifiable public disclosure date. See [Originality and provenance](docs/ORIGINALITY_AND_PROVENANCE.md) and [Preliminary prior-art search](docs/PRIOR_ART_SEARCH.md).

## Contributing and license

Issues and pull requests are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md), follow [SECURITY.md](SECURITY.md) for sensitive reports, and retain reproducible evidence for behavior-changing fixes.

The project source is licensed under the [Apache License 2.0](LICENSE). Bundled third-party files retain their own licenses; see [NOTICE](NOTICE).
