# Security Policy

Do not include real credentials, API keys, account emails or personal data in
issues or pull requests.

## Reporting a vulnerability

Use GitHub's "Report a vulnerability" feature on the repository's Security tab.
Include the affected file, impact and a minimal reproduction.

## Credential handling

- Secrets are read from the local `.env`, which is git-ignored.
- `.env.example` contains names and placeholders only.
- `GEMINI_API_KEY`, SMTP credentials and database URLs must stay private.
- Rotate any credential that may have been exposed.
