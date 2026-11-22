# Contributing

Contributions are welcome.

## Getting started

1. Fork the repository and branch from `main`.
2. Copy `.env.example` to `.env` and fill in your own values; never commit it.
3. Start the stack with `docker compose up --build`, or work inside `backend/`.

## Before opening a pull request

- Run `cd backend && pytest -q`.
- Cover new behavior with tests under `backend/tests/`.
- Do not include real API keys, emails or personal data.
- Update the README and CHANGELOG when behavior changes.
