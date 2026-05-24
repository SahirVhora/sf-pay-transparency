# Security And Publishing Notes

This project is a local SuccessFactors readiness prototype. Treat it as a demo and analysis aid, not as production security architecture.

## Before Sharing

- Remove local credentials: `rm -f .pay_transparency_credentials.*`
- Confirm `.gitignore` still excludes `.pay_transparency_credentials.*`, `.env`, and generated Python cache files.
- Do not publish screenshots containing tenant URLs, company IDs, usernames, employee identifiers, pay values, sample rows, or country-specific client data.
- Use demo data or redacted screenshots for LinkedIn, talks, and public repos.
- Keep the backend bound to `127.0.0.1` for local use.
- Replace password storage with OS keyring, a vault, OAuth, or another approved enterprise credential pattern before shared hosting.
- Validate legal interpretation and country-specific implementation details with qualified HR/legal stakeholders.

## Data Handling

The evidence pack masks sample values and does not return raw employee/pay rows used for calculations. This does not make the tool automatically safe for real tenant demonstrations. Metadata, resolved entity names, field names, row counts, and aggregate calculations can still reveal sensitive implementation details.
