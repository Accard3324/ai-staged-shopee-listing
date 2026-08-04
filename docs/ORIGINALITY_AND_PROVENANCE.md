# Originality and provenance

## Public maintainer identity

- GitHub account: [`vip-jiekaixu`](https://github.com/vip-jiekaixu)
- Intended public repository: [https://github.com/vip-jiekaixu/ai-staged-shopee-listing](https://github.com/vip-jiekaixu/ai-staged-shopee-listing)
- Initial public version: `v0.1.0`

The first public GitHub commit and release timestamps—not private file dates—are the authoritative public disclosure record.

## Authorship statement

GitHub user `vip-jiekaixu` states that this repository is an independently developed implementation of an **AI-staging plus deterministic-execution** workflow for Shopee listing operations.

For this project, that method means the combined sequence below:

1. Read product facts and candidate status from an operational workbook.
2. Analyze product assets with AI before browser execution.
3. Separate objective image facts from image-selection judgment.
4. Generate and edit judgment-heavy listing content, including search terms, titles, and detail-page descriptions.
5. Let an operator review and approve the generated content.
6. Freeze approved content into a schema-validated listing packet.
7. Use fixed program components, rather than a live general-purpose agent, to fill the authenticated Shopee form.
8. Stop at explicit validation gates and save as delisted.
9. Verify the platform result, write the product ID back, and retain audit artifacts.

In version `0.1.0`, AI-assisted image analysis and selection, title generation, and description generation are implemented. Generation of new product images or main images is a planned capability and is not represented as implemented in this release.

The originality claim applies to `vip-jiekaixu`'s implementation and documented formulation of this combined workflow. It does not claim ownership of AI copy generation, browser automation, product drafts, RPA, CDP, or e-commerce listing automation as broad ideas.

## Core workflow proposition

The specific proposition publicly documented by this project is:

> AI first prepares the product-listing material that requires interpretation or customization. After human review, deterministic software uses the approved packet to operate the authenticated seller backend and complete routine listing fields through a fixed, testable workflow.

The project presents this as a practical alternative to using a live general-purpose agent or skill for every field of every SKU. The goal is to reduce repeated context loading and token use, improve repeatability, preserve reviewability, and stop safely at validation gates.

## Development chronology

The following dates come from private local development records. They describe project history but are not independently verifiable public timestamps:

- 2026-07-06 — conversion of an operational Shopee skill workflow into a local application began.
- 2026-07-10 — end-to-end Save and Delist execution and result evidence were recorded locally.
- 2026-07-14 — verified product-ID write-back was added.
- 2026-07-23 — one-click orchestration, bounded AI stages, per-image objective/selection separation, and retry controls were integrated.
- 2026-07-28 — additional model routing and local credential handling were integrated.
- 2026-07-31 — missing/zero stock fallback and regression coverage were added.
- 2026-08-02 — the sanitized open-source release and this provenance record were prepared.
- 2026-08-04 — public identity and GitHub publication metadata were finalized for the release package.

The authoritative public disclosure date must be the date shown by the first public GitHub commit/release or another independent archive. Do not backdate the public release.

## What GitHub can prove

A public repository can provide strong, practical evidence that:

- a specific set of files was publicly available no later than a visible commit/release date;
- GitHub account `vip-jiekaixu` published or controlled that repository;
- later changes have a traceable history;
- a signed commit or tag matches the holder of the signing key;
- a release attachment matches a published SHA-256 digest.

GitHub alone cannot prove that:

- no one anywhere had the same or a similar idea earlier;
- the method is patentable or does not infringe another patent;
- the publisher is the legal author of every copied third-party component;
- a local file creation date is genuine;
- an OpenAI program application creates exclusivity or confidentiality.

## Recommended public wording

> This project is GitHub user `vip-jiekaixu`'s independently developed and publicly documented implementation of an AI-staging/deterministic-execution workflow for Shopee listings. The first public commit and release are the record of public disclosure. This statement claims independent implementation and publication timing, not unverified worldwide novelty.

## Publication evidence checklist

1. Publish the complete sanitized source; do not upload `.env`, workbooks, business outputs, or credentials.
2. Use GitHub account `vip-jiekaixu` consistently in GitHub, the commit, and `CITATION.cff`.
3. Create a signed commit if signing is already configured; otherwise do not claim cryptographic signing.
4. Create an annotated or signed `v0.1.0` tag.
5. Create a GitHub Release with the source archive and its separate `.sha256` file.
6. Preserve the Release URL and screenshots of the public timestamps.
7. Archive the release through an independent service such as Zenodo and retain its DOI.
8. Preserve private development evidence separately; publish only material that contains no secrets or third-party confidential information.

## Important legal boundary

This file is a provenance record, not legal advice, a patent opinion, or a freedom-to-operate analysis. If commercial exclusivity or a patent claim matters, consult a qualified intellectual-property professional before broad disclosure because public release can affect patent rights in some jurisdictions.
