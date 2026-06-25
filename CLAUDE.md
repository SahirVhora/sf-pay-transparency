# CLAUDE.md — sf-pay-transparency

Flask proxy server for SAP SuccessFactors Pay Transparency. Handles OData metadata fetching, API key management, and CORS proxy for a React frontend.

## DO NOT
- Delete or modify .github/workflows/ files
- Delete favicon.svg, CONTRIBUTING.md, SECURITY.md
- Run `ruff format` across the whole codebase without asking
- Change proxy_server.py auth logic without understanding OAuth2 flow
- Remove the `defusedxml` import or related security patches

## Commands
- Syntax check: `python3 -m py_compile backend_server.py proxy_server.py`
- No test suite exists yet — verify by running syntax check + manual smoke test
- Git: default branch is `main`. Always `git pull --rebase origin main` before pushing.

## Structure
- `backend_server.py` — main Flask app (OData metadata, API endpoints)
- `proxy_server.py` — CORS proxy for frontend API calls
- `scripts/smoke_test.py` — basic smoke test / health check
