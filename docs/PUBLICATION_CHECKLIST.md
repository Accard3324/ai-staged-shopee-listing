# Public GitHub release checklist

## 1. Confirmed public identity and license

- Public GitHub owner: `vip-jiekaixu`
- Public repository name: `ai-staged-shopee-listing`
- Repository URL: `https://github.com/vip-jiekaixu/ai-staged-shopee-listing`
- `CITATION.cff` uses `vip-jiekaixu` as the public author identity.
- The intended source license is Apache-2.0.
- Third-party archive utility licenses and `NOTICE` must remain unchanged except for the project's own copyright identity.

## 2. Review the disclosure boundary

Confirm the repository contains none of the following:

- `.env`, API keys, tokens, cookies, OAuth records, or browser profiles;
- real Excel workbooks, customer data, product exports, or private store configuration;
- downloaded product images/videos;
- logs, screenshots, HTML snapshots, or generated listing JSON from real operations.

## 3. Create the public repository

Create an empty **public** GitHub repository named:

```text
ai-staged-shopee-listing
```

From the sanitized release directory:

```powershell
git init
git branch -M main
git add .
git status
git commit -m "Public disclosure: AI-staged deterministic Shopee listing workflow"
git remote add origin https://github.com/vip-jiekaixu/ai-staged-shopee-listing.git
git push -u origin main
```

Publishing is an external action. Review `git status` and repository visibility before pushing.

## 4. Create the disclosure record

Prefer a signed tag only if signing is already configured:

```powershell
git tag -s v0.1.0 -m "First public release of the AI-staging/deterministic-execution method"
git push origin v0.1.0
```

Otherwise use an annotated tag and do not claim it is cryptographically signed:

```powershell
git tag -a v0.1.0 -m "First public release of the AI-staging/deterministic-execution method"
git push origin v0.1.0
```

Create a GitHub Release from `v0.1.0`. Use `docs/RELEASE_NOTES_v0.1.0.md` as the release description and attach:

- `ai-staged-shopee-listing-v0.1.0.zip`
- `ai-staged-shopee-listing-v0.1.0.zip.sha256`

The GitHub commit and release timestamps are the authoritative public disclosure dates.

## 5. Verify after publication

- The repository is public when signed out of GitHub.
- README, license, provenance, prior-art report, security policy, and CI are visible.
- The default-branch test workflow passes.
- The release page shows the intended tag and attachments.
- The downloaded release archive matches the published SHA-256 digest.
- No secret scanning or push-protection alert remains unresolved.

## 6. Add independent timestamp evidence

Connect the GitHub repository to Zenodo, archive `v0.1.0`, and retain the DOI. An independent archive strengthens publication-date evidence and makes the project citable; it still does not prove global novelty.

## 7. Build Codex for Open Source eligibility

- Keep Issues and Discussions active.
- Publish reproducible fixes and release notes.
- Collect only real usage metrics.
- Invite independent installation reports and contributors.
- Apply using `docs/CODEX_FOR_OSS_APPLICATION.md` only after adding verified public maintenance and adoption evidence.
