# Repository Guidelines

## Project Structure & Module Organization
The Flask app lives in `healthcheck.py`, exposing `/health` endpoints and talking to the Tailscale API. Gunicorn startup hooks and OAuth wiring reside in `gunicorn_config.py`. Container packaging is defined in `Dockerfile`, while runtime dependencies are pinned in `requirements.txt`. Continuous builds run via `.github/workflows/`. Add unit tests under `tests/` (for example `tests/test_healthcheck.py`) and keep new helpers in dedicated modules named with `lower_snake_case.py`.

## Build, Test, and Development Commands
Create a virtual environment and install runtime deps with `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`. Run the production stack locally via `gunicorn -w 4 -b 0.0.0.0:5000 -c gunicorn_config.py healthcheck:app`. For quick iteration use `FLASK_APP=healthcheck.py flask run --port 5000`. Lint the main module with `pip install flake8 && flake8 healthcheck.py`. Execute the test suite using `pip install pytest && pytest -q`. Build and run the Docker image with `docker build -t tailscale-healthcheck .` followed by `docker run -p 5000:5000 --env-file .env tailscale-healthcheck`.

## Coding Style & Naming Conventions
Target Python 3.12 with four-space indentation and UTF-8 files. Keep functions and variables in `snake_case`, classes in `PascalCase`, and modules in lowercase snake case. Routes should remain idempotent and return JSON only; avoid adding manual trailing-slash redirects. Add docstrings to pure helpers such as `should_include_device` when introducing new behavior, and prefer small, testable functions.

## Testing Guidelines
Use `pytest` with files named `tests/test_*.py`. Mock network calls with `unittest.mock.patch`, especially `requests.get` and `requests.post`, and control time-dependent logic by patching timezone utilities. Ensure new helpers and any `/health*` response transformations have dedicated unit coverage. Run `pytest -q` before submitting changes and document meaningful gaps.

## Commit & Pull Request Guidelines
Write commits with short imperative subjects (e.g., “Add device filter helper”) and link issues using “Resolves #<id>” when applicable. Pull requests should summarize behavior changes, include sample `/health` responses when relevant, and mention config or env var updates. Confirm lint and tests pass locally and update documentation when APIs or configuration knobs change.

## Security & Configuration Tips
Prefer OAuth credentials (`OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`) instead of static `AUTH_TOKEN`. Store secrets in `.env` for local development only, never commit real credentials, and rely on existing logging to keep sensitive values masked.
