# v0.1.0 — First public release

This is the first public source release of **AI-Staged Shopee Listing App**, maintained by GitHub user [`@vip-jiekaixu`](https://github.com/vip-jiekaixu).

## Core method

The project separates listing work into three stages:

1. AI prepares judgment-heavy listing material before browser execution, including image analysis and selection, search terms, product titles, and detail-page descriptions.
2. An operator reviews and approves the prepared material.
3. Deterministic software uses the approved listing packet to operate the authenticated Shopee seller backend through a fixed, testable workflow.

This approach is intended to reduce repeated token use, improve repeatability, preserve audit evidence, and stop safely at validation gates.

## Implemented in v0.1.0

- Local-first Windows workflow for Shopee Malaysia through an authenticated Ziniao Browser session.
- AI-assisted image analysis and selection.
- Editable search-term, competitor-title, title, and description stages.
- Schema-validated reusable `listing_draft.json`.
- Deterministic form filling, pre-save checks, Save and Delist, result verification, and workbook write-back.
- Offline regression tests and GitHub Actions CI.
- Sanitized example configuration with no real credentials or business data.
- Apache-2.0 source license and retained third-party notices.

## Planned, not implemented

- Automatic product asset download.
- Generation of new product images or main images.

## Originality and public record

This release is `vip-jiekaixu`'s independently developed and publicly documented implementation of the combined AI-staging/deterministic-execution workflow described in the repository. The GitHub commit and release timestamps establish the public disclosure date for this exact source and formulation. They do not prove unverified worldwide novelty.

See `docs/ORIGINALITY_AND_PROVENANCE.md` and `docs/PRIOR_ART_SEARCH.md`.

## Verification

Attach the release ZIP and its `.sha256` file. After downloading, verify that the SHA-256 digest matches before using the archive.
