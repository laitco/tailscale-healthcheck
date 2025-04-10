import os
import logging
from healthcheck import initialize_oauth  # Import the OAuth initialization function

# Configure logging
logging.basicConfig(level=logging.INFO)

def on_starting(server):
    """
    Hook that runs only in the Gunicorn master process.
    """
    if os.getenv("OAUTH_CLIENT_ID") and os.getenv("OAUTH_CLIENT_SECRET"):
        logging.info("Gunicorn master process starting. Initializing OAuth...")
        initialize_oauth()
    else:
        logging.info("Gunicorn master process starting. Using AUTH_TOKEN for authentication. Skipping OAuth initialization.")
