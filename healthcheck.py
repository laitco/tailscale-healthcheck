import os
import requests
from datetime import datetime, timedelta
from flask import Flask, jsonify, redirect
import pytz
import logging  # Add logging for debugging
from threading import Timer  # For token renewal

# Configure logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.url_map.strict_slashes = False  # Allow trailing slashes to be ignored

# Load configuration from environment variables
TAILNET_DOMAIN = os.getenv("TAILNET_DOMAIN", "example.com")  # Default to "laitco.de"
TAILSCALE_API_URL = f"https://api.tailscale.com/api/v2/tailnet/{TAILNET_DOMAIN}/devices"
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "your-default-token")
THRESHOLD_MINUTES = int(os.getenv("THRESHOLD_MINUTES", 5))  # Default to 5 minutes
PORT = int(os.getenv("PORT", 5000))  # Default to port 5000
TIMEZONE = os.getenv("TIMEZONE", "UTC")  # Default to UTC

# Load OAuth configuration from environment variables
OAUTH_CLIENT_ID = os.getenv("OAUTH_CLIENT_ID")
OAUTH_CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET")

# Global variable to store the OAuth access token and timer
ACCESS_TOKEN = None
TOKEN_RENEWAL_TIMER = None

def fetch_oauth_token():
    """
    Fetches a new OAuth access token using the client ID and client secret.
    """
    global ACCESS_TOKEN, TOKEN_RENEWAL_TIMER
    try:
        response = requests.post(
            "https://api.tailscale.com/api/v2/oauth/token",
            data={
                "client_id": OAUTH_CLIENT_ID,
                "client_secret": OAUTH_CLIENT_SECRET
            }
        )
        response.raise_for_status()
        token_data = response.json()
        ACCESS_TOKEN = token_data["access_token"]
        logging.info("Successfully fetched OAuth access token.")

        # Cancel any existing timer before scheduling a new one
        if TOKEN_RENEWAL_TIMER:
            TOKEN_RENEWAL_TIMER.cancel()

        # Schedule the next token renewal after 50 minutes
        TOKEN_RENEWAL_TIMER = Timer(50 * 60, fetch_oauth_token)
        TOKEN_RENEWAL_TIMER.start()

        # Log the token renewal time in the configured timezone
        try:
            tz = pytz.timezone(TIMEZONE)
            renewal_time = datetime.now(tz).isoformat()
            logging.info(f"OAuth access token renewed at {renewal_time} ({TIMEZONE}).")
        except pytz.UnknownTimeZoneError:
            logging.error(f"Unknown timezone: {TIMEZONE}. Logging renewal time in UTC.")
            logging.info(f"OAuth access token renewed at {datetime.utcnow().isoformat()} UTC.")
    except requests.exceptions.HTTPError as http_err:
        logging.error(f"HTTP error during token fetch: {http_err}")
        if response.status_code == 401:
            logging.error("Unauthorized error (401). Retrying token fetch...")
            ACCESS_TOKEN = None
        else:
            logging.error(f"Unexpected HTTP error: {response.status_code}")
    except Exception as e:
        logging.error(f"Failed to fetch OAuth access token: {e}")
        ACCESS_TOKEN = None

def initialize_oauth():
    """
    Initializes OAuth token fetching if OAuth is configured.
    This function should only be called once during the master process initialization.
    """
    if OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET:
        logging.info("OAuth configuration detected. Fetching initial access token...")
        fetch_oauth_token()

# Only initialize OAuth in the Gunicorn master process
if os.getenv("GUNICORN_MASTER_PROCESS", "false").lower() == "true":
    initialize_oauth()

# Log the configured timezone
logging.debug(f"Configured TIMEZONE: {TIMEZONE}")

@app.route('/health', methods=['GET'])
def health_check():
    try:
        # Determine the authorization method
        if OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET and ACCESS_TOKEN:
            auth_header = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        else:
            auth_header = {"Authorization": f"Bearer {AUTH_TOKEN}"}

        # Fetch data from Tailscale API
        response = requests.get(
            TAILSCALE_API_URL,
            headers=auth_header
        )
        response.raise_for_status()
        devices = response.json().get("devices", [])

        # Get the timezone object
        try:
            tz = pytz.timezone(TIMEZONE)
        except pytz.UnknownTimeZoneError:
            logging.error(f"Unknown timezone: {TIMEZONE}")
            return jsonify({"error": f"Unknown timezone: {TIMEZONE}"}), 400

        # Calculate the threshold time (now - THRESHOLD_MINUTES) in the specified timezone
        threshold_time = datetime.now(tz) - timedelta(minutes=THRESHOLD_MINUTES)
        logging.debug(f"Threshold time: {threshold_time.isoformat()}")

        # Check health status for each device
        health_status = []
        for device in devices:
            last_seen = datetime.strptime(device["lastSeen"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
            last_seen_local = last_seen.astimezone(tz)  # Convert lastSeen to the specified timezone
            logging.debug(f"Device {device['name']} last seen (local): {last_seen_local.isoformat()}")
            is_healthy = last_seen_local >= threshold_time
            machine_name = device["name"].split('.')[0]  # Extract machine name before the first dot
            health_status.append({
                "id": device["id"],
                "device": device["name"],
                "machineName": machine_name,
                "hostname": device["hostname"],
                "lastSeen": last_seen_local.isoformat(),  # Include timezone offset in ISO format
                "healthy": is_healthy
            })

        return jsonify(health_status)

    except Exception as e:
        logging.error(f"Error in health_check: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health/', methods=['GET'])
def health_check_redirect():
    # Redirect to /health without trailing slash
    return redirect('/health', code=301)

@app.route('/health/<identifier>', methods=['GET'])
def health_check_by_identifier(identifier):
    try:
        # Determine the authorization method
        if OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET and ACCESS_TOKEN:
            auth_header = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        else:
            auth_header = {"Authorization": f"Bearer {AUTH_TOKEN}"}

        # Fetch data from Tailscale API
        response = requests.get(
            TAILSCALE_API_URL,
            headers=auth_header
        )
        response.raise_for_status()
        devices = response.json().get("devices", [])

        # Get the timezone object
        try:
            tz = pytz.timezone(TIMEZONE)
        except pytz.UnknownTimeZoneError:
            logging.error(f"Unknown timezone: {TIMEZONE}")
            return jsonify({"error": f"Unknown timezone: {TIMEZONE}"}), 400

        # Calculate the threshold time (now - THRESHOLD_MINUTES) in the specified timezone
        threshold_time = datetime.now(tz) - timedelta(minutes=THRESHOLD_MINUTES)
        logging.debug(f"Threshold time: {threshold_time.isoformat()}")

        # Convert identifier to lowercase for case-insensitive comparison
        identifier_lower = identifier.lower()

        # Find the device with the matching hostname, ID, name, or machineName
        for device in devices:
            machine_name = device["name"].split('.')[0]  # Extract machine name before the first dot
            if (device["hostname"].lower() == identifier_lower or
                device["id"].lower() == identifier_lower or
                device["name"].lower() == identifier_lower or
                machine_name.lower() == identifier_lower):
                last_seen = datetime.strptime(device["lastSeen"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
                last_seen_local = last_seen.astimezone(tz)  # Convert lastSeen to the specified timezone
                logging.debug(f"Device {device['name']} last seen (local): {last_seen_local.isoformat()}")
                is_healthy = last_seen_local >= threshold_time
                return jsonify({
                    "id": device["id"],
                    "device": device["name"],
                    "machineName": machine_name,
                    "hostname": device["hostname"],
                    "lastSeen": last_seen_local.isoformat(),  # Include timezone offset in ISO format
                    "healthy": is_healthy
                })

        # If no matching hostname, ID, name, or machineName is found
        return jsonify({"error": "Device not found"}), 404

    except Exception as e:
        logging.error(f"Error in health_check_by_identifier: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health/unhealthy', methods=['GET'])
def health_check_unhealthy():
    try:
        # Determine the authorization method
        if OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET and ACCESS_TOKEN:
            auth_header = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        else:
            auth_header = {"Authorization": f"Bearer {AUTH_TOKEN}"}

        # Fetch data from Tailscale API
        response = requests.get(
            TAILSCALE_API_URL,
            headers=auth_header
        )
        response.raise_for_status()
        devices = response.json().get("devices", [])

        # Get the timezone object
        try:
            tz = pytz.timezone(TIMEZONE)
        except pytz.UnknownTimeZoneError:
            logging.error(f"Unknown timezone: {TIMEZONE}")
            return jsonify({"error": f"Unknown timezone: {TIMEZONE}"}), 400

        # Calculate the threshold time (now - THRESHOLD_MINUTES) in the specified timezone
        threshold_time = datetime.now(tz) - timedelta(minutes=THRESHOLD_MINUTES)
        logging.debug(f"Threshold time: {threshold_time.isoformat()}")

        # Check health status for each device and filter unhealthy devices
        unhealthy_devices = []
        for device in devices:
            last_seen = datetime.strptime(device["lastSeen"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
            last_seen_local = last_seen.astimezone(tz)  # Convert lastSeen to the specified timezone
            logging.debug(f"Device {device['name']} last seen (local): {last_seen_local.isoformat()}")
            is_healthy = last_seen_local >= threshold_time
            if not is_healthy:
                machine_name = device["name"].split('.')[0]  # Extract machine name before the first dot
                unhealthy_devices.append({
                    "id": device["id"],
                    "device": device["name"],
                    "machineName": machine_name,
                    "hostname": device["hostname"],
                    "lastSeen": last_seen_local.isoformat(),  # Include timezone offset in ISO format
                    "healthy": is_healthy
                })

        return jsonify(unhealthy_devices)

    except Exception as e:
        logging.error(f"Error in health_check_unhealthy: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health/healthy', methods=['GET'])
def health_check_healthy():
    try:
        # Determine the authorization method
        if OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET and ACCESS_TOKEN:
            auth_header = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        else:
            auth_header = {"Authorization": f"Bearer {AUTH_TOKEN}"}

        # Fetch data from Tailscale API
        response = requests.get(
            TAILSCALE_API_URL,
            headers=auth_header
        )
        response.raise_for_status()
        devices = response.json().get("devices", [])

        # Get the timezone object
        try:
            tz = pytz.timezone(TIMEZONE)
        except pytz.UnknownTimeZoneError:
            logging.error(f"Unknown timezone: {TIMEZONE}")
            return jsonify({"error": f"Unknown timezone: {TIMEZONE}"}), 400

        # Calculate the threshold time (now - THRESHOLD_MINUTES) in the specified timezone
        threshold_time = datetime.now(tz) - timedelta(minutes=THRESHOLD_MINUTES)
        logging.debug(f"Threshold time: {threshold_time.isoformat()}")

        # Check health status for each device and filter healthy devices
        healthy_devices = []
        for device in devices:
            last_seen = datetime.strptime(device["lastSeen"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
            last_seen_local = last_seen.astimezone(tz)  # Convert lastSeen to the specified timezone
            logging.debug(f"Device {device['name']} last seen (local): {last_seen_local.isoformat()}")
            is_healthy = last_seen_local >= threshold_time
            if is_healthy:
                machine_name = device["name"].split('.')[0]  # Extract machine name before the first dot
                healthy_devices.append({
                    "id": device["id"],
                    "device": device["name"],
                    "machineName": machine_name,
                    "hostname": device["hostname"],
                    "lastSeen": last_seen_local.isoformat(),  # Include timezone offset in ISO format
                    "healthy": is_healthy
                })

        return jsonify(healthy_devices)

    except Exception as e:
        logging.error(f"Error in health_check_healthy: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)