# Security policy

## Supported version

Security fixes target the latest tagged release and the default branch.

## Reporting a vulnerability

Do not open a public issue for a vulnerability that could expose credentials, browser sessions, seller data, or unauthorized marketplace actions. Use GitHub private vulnerability reporting when it is enabled. If it is unavailable, contact the repository owner through the private address listed on the maintainer's public GitHub profile.

Include only sanitized reproduction details. Never send live API keys, cookies, OAuth tokens, `.env` files, workbooks, customer records, or complete authenticated page captures.

## Security model

- Secrets belong only in the local `.env` or a provider-owned credential store.
- The default test suite is offline and must use fake data.
- Browser automation reuses a session the operator has already authorized; it does not bypass account access controls.
- The automated terminal action is `save_delist`, not live publication.
- Operators remain responsible for marketplace rules, content accuracy, account permissions, and third-party service terms.

