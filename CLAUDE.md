# CLAUDE.md: sf-pay-transparency

Python (standard library http.server) backend and proxy for SAP SuccessFactors Pay Transparency. Handles OData metadata fetching, API key management, and CORS proxy for a React frontend.

## DO NOT
- Delete or modify .github/workflows/ files
- Delete favicon.svg, CONTRIBUTING.md, SECURITY.md
- Run `ruff format` across the whole codebase without asking
- Change proxy_server.py auth logic without understanding OAuth2 flow
- Remove the `defusedxml` import or related security patches

## Commands
- Syntax check: `python3 -m py_compile backend_server.py proxy_server.py`
- Unit tests: `python3 -m unittest discover -s tests`
- Smoke test (starts the backend in demo mode): `python3 scripts/smoke_test.py`
- Run all three before pushing; CI runs the same steps
- Git: default branch is `main`. Always `git pull --rebase origin main` before pushing.

## Structure
- `backend_server.py`: main backend server (OData metadata, API endpoints)
- `proxy_server.py`: CORS proxy for frontend API calls
- `scripts/smoke_test.py`: demo-mode smoke test against the backend endpoints
- `tests/`: unit tests for backend HTTP handling and proxy security
