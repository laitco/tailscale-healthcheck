# Repository Guidelines

## Project Structure & Module Organization
- `healthcheck.py`: Flask app with `/health*` endpoints and Tailscale API integration.
- `gunicorn_config.py`: Startup hooks, timeouts, OAuth init in master process.
- `Dockerfile`: Production image (Python 3.9, Gunicorn) with healthcheck.
- `.github/workflows/`: CI to build and publish Docker images.
- `requirements.txt`: Runtime deps (`flask`, `requests`, `pytz`, `gunicorn`, `python-dateutil`).
- `README.md`: Usage, config, and Docker instructions.
- Tests: create under `tests/` (e.g., `tests/test_healthcheck.py`).

## Build, Test, and Development Commands
- Create env and install deps:
  - `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- Run locally (Gunicorn):
  - `gunicorn -w 4 -b 0.0.0.0:5000 -c gunicorn_config.py healthcheck:app`
- Run locally (Flask dev):
  - `FLASK_APP=healthcheck.py flask run --port 5000`
- Lint:
  - `pip install flake8 && flake8 healthcheck.py`
- Test (pytest):
  - `pip install pytest && pytest -q`
- Docker build/run:
  - `docker build -t tailscale-healthcheck .`
  - `docker run -p 5000:5000 --env-file .env tailscale-healthcheck`

## Coding Style & Naming Conventions
- Python 3.9, 4-space indentation, UTF-8.
- Names: `snake_case` functions/variables, `PascalCase` classes, modules in `lower_snake_case.py`.
- Keep routes idempotent and JSON-only; avoid trailing-slash redirects (already handled).
- Prefer small pure helpers (e.g., `should_include_device`) with clear docstrings.

## Testing Guidelines
- Framework: `pytest`. Place files under `tests/` named `test_*.py`.
- Focus: unit-test helpers (`should_include_device`, `should_force_update_healthy`) and response shaping for `/health*` with mocked HTTP.
- Mocking: patch `requests.get/post` and time using `unittest.mock`.
- Run locally with `pytest -q`; add fixtures for env vars.

## Commit & Pull Request Guidelines
- Commits: short imperative subject; link issues (e.g., “Resolves #19”).
- PRs: clear description, linked issues, sample requests/responses, and notes on config/env changes.
- Requirements: lint passes, tests added/updated, README or docs updated when behavior/config changes.

## Security & Configuration Tips
- Prefer OAuth (`OAUTH_CLIENT_ID/SECRET`) over `AUTH_TOKEN`. Never hardcode secrets.
- Use `.env` for local dev only; do not commit real credentials.
- Keep sensitive values masked in logs/output (already supported by the app).
