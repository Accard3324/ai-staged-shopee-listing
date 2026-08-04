# Repository guidance for Codex

## Scope

This repository is a Windows-first, standard-library Python application. Keep changes focused on the AI-staging and deterministic-execution workflow.

## Invariants

- AI may analyze assets and prepare structured listing content, but browser form execution must remain deterministic code.
- Keep `objective_record` separate from `selection_assessment`; downstream copy generation may consume only approved objective facts.
- Never change the safe terminal action from `save_delist` to live publication without an explicit maintainer decision and new safety tests.
- Stop on failed validation. Do not skip a failed step and continue to save.
- Never commit `.env`, credentials, workbooks, downloaded product assets, screenshots, HTML snapshots, logs, or generated listing packets.
- Tests must use fake accounts, fake keys, and synthetic SKUs. Do not call live AI providers or Shopee in the default test suite.

## Verification

Run from the repository root on Windows:

```powershell
py -3 -X utf8 -m unittest discover -s tests -p "test_*.py"
```

For a launcher smoke check:

```powershell
start_app.bat --check
```

Update user-facing documentation when a workflow step, configuration field, model option, safety boundary, or expected test result changes.
