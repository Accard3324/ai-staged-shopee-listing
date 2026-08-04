# Contributing

Thank you for improving the project. Small, evidence-backed changes are easier to review and safer for real seller workflows.

## Before opening a change

- Search existing issues first.
- Reproduce the behavior with synthetic data; never attach real credentials, store exports, product workbooks, customer data, or authenticated browser files.
- Keep the AI-staging and deterministic-execution boundary intact.
- Preserve the `save_delist` safety boundary unless a maintainer explicitly approves a separate, fully tested design.

## Development

The runtime uses the Python standard library. On Windows, run:

```powershell
py -3 -X utf8 -m unittest discover -s tests -p "test_*.py"
```

Add or update the narrowest regression test that demonstrates the change. Network-backed provider checks must remain opt-in and must not run in the default suite.

## Pull requests

Describe:

1. The user-visible problem.
2. The exact behavior changed.
3. The tests or evidence used to verify it.
4. Any effect on credentials, external services, browser state, saving, or workbook write-back.

By submitting a contribution, you agree that it may be distributed under the repository's Apache-2.0 license.

