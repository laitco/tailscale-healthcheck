import os
import logging
from healthcheck import initialize_oauth  # Import the OAuth initialization function
import dbstore
import poller

# Configure logging with safe default (INFO) and env override
def _get_log_level_from_env(default=logging.INFO):
    level_name = os.getenv("LOG_LEVEL", "INFO")
    return getattr(logging, str(level_name).upper(), default)

logging.basicConfig(level=_get_log_level_from_env())

# Increase timeout settings
timeout = int(os.getenv("GUNICORN_TIMEOUT", 120))  # Default timeout to 120 seconds
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", 120))  # Default graceful timeout to 120 seconds

def on_starting(server):
    """
    Hook that runs only in the Gunicorn master process.

    Credentials are resolved through dbstore (env-first, DB-fallback), not
    os.getenv: anything entered through the setup wizard or /admin/settings
    lives only in SQLite, so an env-only check reported "using AUTH_TOKEN" and
    skipped the OAuth pre-warm on every OAuth install that wasn't configured
    by environment variable - i.e. most of them. Harmless in effect (the
    poller fetches a token on its first cycle either way), but the startup log
    actively misled anyone debugging authentication.
    """
    if dbstore.get_setting("oauth_client_id") and dbstore.get_setting("oauth_client_secret"):
        logging.info("Gunicorn master process starting. Initializing OAuth...")
        initialize_oauth()
    elif dbstore.get_setting("auth_token"):
        logging.info("Gunicorn master process starting. Using a static API token for authentication.")
    else:
        logging.info(
            "Gunicorn master process starting. No Tailscale credentials configured yet - "
            "complete the setup wizard at /admin/setup."
        )

def post_fork(server, worker):
    """
    Hook that runs in each worker process after fork. Only one worker (the
    one that wins the fcntl lock election in poller.start()) actually runs
    the background poll loop; the rest no-op.
    """
    poller.start()

def worker_exit(server, worker):
    """
    Hook to log when a worker exits.
    """
    logging.warning(f"Worker {worker.pid} exited. Gunicorn will attempt to restart it.")

def worker_abort(worker):
    """
    Hook to handle worker aborts gracefully.
    """
    logging.error(f"Worker {worker.pid} aborted unexpectedly. Gunicorn will restart it if possible.")

def post_request(worker, req, environ, resp):
    """
    Hook to handle post-request logging.
    """
    if req is None:
        logging.warning(f"Worker {worker.pid} received an invalid or incomplete request.")

def worker_timeout(worker):
    """
    Hook to log worker timeout events.
    """
    logging.error(f"Worker {worker.pid} timed out.")
