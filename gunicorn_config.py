import os
import logging
from healthcheck import initialize_oauth  # Import the OAuth initialization function

# Configure logging
logging.basicConfig(level=logging.INFO)

# Increase timeout settings
timeout = int(os.getenv("GUNICORN_TIMEOUT", 120))  # Default timeout to 120 seconds
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", 120))  # Default graceful timeout to 120 seconds

def on_starting(server):
    """
    Hook that runs only in the Gunicorn master process.
    """
    if os.getenv("OAUTH_CLIENT_ID") and os.getenv("OAUTH_CLIENT_SECRET"):
        logging.info("Gunicorn master process starting. Initializing OAuth...")
        initialize_oauth()
    else:
        logging.info("Gunicorn master process starting. Using AUTH_TOKEN for authentication. Skipping OAuth initialization.")

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
