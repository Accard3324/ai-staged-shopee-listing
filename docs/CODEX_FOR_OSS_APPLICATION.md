# Codex for Open Source application worksheet

Verified against the official program, application, and terms pages on 2026-08-04:

- [Codex for Open Source program](https://developers.openai.com/community/codex-for-oss)
- [Application form](https://openai.com/form/codex-for-oss/)
- [Program terms](https://learn.chatgpt.com/docs/codex-for-oss-terms)


## Repository identity

- GitHub maintainer: `vip-jiekaixu`
- Intended public repository: `https://github.com/vip-jiekaixu/ai-staged-shopee-listing`
- Maintainer role: primary maintainer

## What the program currently evaluates

The official pages say maintainers of active open-source projects may apply. OpenAI looks at repository usage, ecosystem importance, evidence of active maintenance, and whether the applicant is a primary or core maintainer. The form requires a public GitHub profile, a public repository URL, maintainer role, a repository-qualification explanation (maximum 500 characters), an OpenAI Organization ID, an API-credit use explanation (maximum 500 characters), and an optional final note (maximum 500 characters).

Selected maintainers may receive six months of ChatGPT Pro with Codex, API credits for core open-source maintainer workflows, and conditional Codex Security access. Selection is discretionary and submission does not guarantee benefits.

## Honest readiness assessment

| Signal | Current release evidence | Remaining gap |
| --- | --- | --- |
| Public open-source repository | Sanitized source, Apache-2.0 license, governance files, CI workflow | Must actually be published to a public GitHub repository. |
| Primary/core maintainer | The publisher will be the primary maintainer | GitHub profile must be public and affiliation verifiable. |
| Active maintenance | Changelog, tests, issue/PR guidance, security policy | Continue public issue triage and releases after launch. |
| Meaningful usage/adoption | Practical end-to-end workflow and regression suite | A new repository has no verified stars, downloads, external users, or contributors yet. Do not invent them. |
| Ecosystem importance | Open reference implementation for an under-served Shopee/Ziniao workflow | Demonstrate reuse beyond one private store configuration. |
| API-credit use | Public eval, regression, review, and maintainer plan below | Keep credits for OSS maintenance, not private store operating costs. |

The largest current weakness is adoption evidence. The official page says an important project may still apply even if it does not neatly fit the criteria, but a brand-new private-to-public repository is not automatically a strong candidate.

## Before applying

1. Publish the repository and pass CI on the default branch.
2. Create a tagged release and enable Issues, Discussions, and private vulnerability reporting.
3. Confirm `CITATION.cff`, the Git commit identity, and the public profile consistently identify `vip-jiekaixu`.
4. Add screenshots or a short demo only after checking that they contain no store, SKU, credential, or customer data.
5. Obtain at least a small amount of verifiable external use: independent setup reports, issues, pull requests, stars, forks, or release downloads.
6. Record actual metrics on the day of application; do not use projections as facts.
7. Explain why the project matters beyond one company: reproducible AI-to-program handoff, safety gates, Windows accessibility, and support for sellers without an official API integration.

## Draft form answers

Replace bracketed text with verified facts. Keep each final answer within the form's 500-character limit.

### Why does this repository qualify?

> This project open-sources a local-first, AI-staged and deterministic Shopee listing workflow for small cross-border commerce teams. It turns product assets into a reviewable listing packet, then uses tested browser steps, stop gates, Save-and-Delist verification, and workbook write-back. It offers a reproducible alternative to running a general AI agent live for every field. Verified adoption: [add current metrics].

### How will you use API credits for your project?

> API credits will support open-source maintenance: regression-testing AI schemas and providers, evaluating title/description quality on consented synthetic fixtures, triaging issues, reviewing pull requests, and validating releases. Credits will not fund private store operations or unrelated production listings. Public eval summaries, tests, and fixes will be contributed back to the repository.

### Anything else we should know?

> Codex helped turn an operational workflow into a tested local application and will support issue triage, Windows compatibility, security review, contributor docs, and safe refactoring. The repository is new, so we will not claim adoption metrics we do not have. We are applying based on practical value for an under-served Shopee ecosystem and will provide current public maintenance evidence.

## Originality is not an application criterion

The program page focuses on maintenance, usage, importance, and OSS workflows—not on being the first to invent an idea. The program terms also state that OpenAI may receive or support similar or identical submissions, provides no exclusivity, and does not treat the application as confidential. Do not submit trade secrets or rely on the application as an originality certificate.

