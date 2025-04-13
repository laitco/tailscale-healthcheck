import os
import requests
from datetime import datetime, timedelta
from flask import Flask, jsonify, redirect
import pytz
import logging  # Add logging for debugging
from threading import Timer  # For token renewal
from urllib3.exceptions import ProtocolError  # Add import for better error handling
from http.client import RemoteDisconnected  # Add import for better error handling

# Configure logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.url_map.strict_slashes = False  # Allow trailing slashes to be ignored

# Load configuration from environment variables
TAILNET_DOMAIN = os.getenv("TAILNET_DOMAIN", "example.com")  # Default to "example.com"
TAILSCALE_API_URL = f"https://api.tailscale.com/api/v2/tailnet/{TAILNET_DOMAIN}/devices"
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "your-default-token")
ONLINE_THRESHOLD_MINUTES = int(os.getenv("ONLINE_THRESHOLD_MINUTES", 5))  # Default to 5 minutes
KEY_THRESHOLD_MINUTES = int(os.getenv("KEY_THRESHOLD_MINUTES", 1440))  # Default to 1440 minutes
PORT = int(os.getenv("PORT", 5000))  # Default to port 5000
TIMEZONE = os.getenv("TIMEZONE", "UTC")  # Default to UTC

# Load OAuth configuration from environment variables
OAUTH_CLIENT_ID = os.getenv("OAUTH_CLIENT_ID")
OAUTH_CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET")

# Global variable to store the OAuth access token and timer
ACCESS_TOKEN = None
TOKEN_RENEWAL_TIMER = None

# Global variable to track if it's the initial token fetch
IS_INITIAL_FETCH = True

def fetch_oauth_token():
    """
    Fetches a new OAuth access token using the client ID and client secret.
    """
    global ACCESS_TOKEN, TOKEN_RENEWAL_TIMER, IS_INITIAL_FETCH
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

        # Log the token renewal time only if it's not the initial fetch
        if not IS_INITIAL_FETCH:
            try:
                tz = pytz.timezone(TIMEZONE)
                renewal_time = datetime.now(tz).isoformat()
                logging.info(f"OAuth access token renewed at {renewal_time} ({TIMEZONE}).")
            except pytz.UnknownTimeZoneError:
                logging.error(f"Unknown timezone: {TIMEZONE}. Logging renewal time in UTC.")
                logging.info(f"OAuth access token renewed at {datetime.utcnow().isoformat()} UTC.")
        else:
            IS_INITIAL_FETCH = False  # Mark the initial fetch as complete
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

def make_authenticated_request(url, headers):
    """
    Makes an authenticated request to the given URL and handles 401 errors by refreshing the token.
    """
    global ACCESS_TOKEN
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 401:
            logging.error("Unauthorized error (401). Attempting to refresh OAuth token...")
            fetch_oauth_token()  # Immediately refresh the token
            if ACCESS_TOKEN:  # Retry the request with the new token
                headers["Authorization"] = f"Bearer {ACCESS_TOKEN}"
                response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response
    except (RemoteDisconnected, ProtocolError) as e:
        logging.error(f"Connection error during authenticated request: {e}. Retrying...")
        return make_authenticated_request(url, headers)  # Retry the request
    except Exception as e:
        logging.error(f"Error during authenticated request: {e}")
        raise

@app.route('/health', methods=['GET'])
def health_check():
    try:
        # Determine the authorization method
        if OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET and ACCESS_TOKEN:
            auth_header = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        else:
            auth_header = {"Authorization": f"Bearer {AUTH_TOKEN}"}

        # Fetch data from Tailscale API using the helper function
        response = make_authenticated_request(TAILSCALE_API_URL, auth_header)
        devices = response.json().get("devices", [])

        # Get the timezone object
        try:
            tz = pytz.timezone(TIMEZONE)
        except pytz.UnknownTimeZoneError:
            logging.error(f"Unknown timezone: {TIMEZONE}")
            return jsonify({"error": f"Unknown timezone: {TIMEZONE}"}), 400

        # Calculate the threshold time (now - ONLINE_THRESHOLD_MINUTES) in the specified timezone
        threshold_time = datetime.now(tz) - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)
        logging.debug(f"Threshold time: {threshold_time.isoformat()}")

        # Check health status for each device
        health_status = []
        for device in devices:
            last_seen = datetime.strptime(device["lastSeen"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
            last_seen_local = last_seen.astimezone(tz)
            expires = None
            key_healthy = True if device.get("keyExpiryDisabled", False) else True
            if not device.get("keyExpiryDisabled", False) and device.get("expires"):
                expires = datetime.strptime(device["expires"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
                expires = expires.astimezone(tz)
                time_until_expiry = expires - datetime.now(tz)
                key_healthy = time_until_expiry.total_seconds() / 60 > KEY_THRESHOLD_MINUTES

            online_is_healthy = last_seen_local >= threshold_time
            machine_name = device["name"].split('.')[0]
            health_info = {
                "id": device["id"],
                "device": device["name"],
                "machineName": machine_name,
                "hostname": device["hostname"],
                "lastSeen": last_seen_local.isoformat(),
                "online_healthy": online_is_healthy,
                "keyExpiryDisabled": device.get("keyExpiryDisabled", False),
                "key_healthy": key_healthy,
                "healthy": online_is_healthy and key_healthy
            }
            
            if not device.get("keyExpiryDisabled", False):
                health_info["keyExpiryTimestamp"] = expires.isoformat() if expires else None
            
            health_status.append(health_info)

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

        # Fetch data from Tailscale API using the helper function
        response = make_authenticated_request(TAILSCALE_API_URL, auth_header)
        devices = response.json().get("devices", [])

        # Get the timezone object
        try:
            tz = pytz.timezone(TIMEZONE)
        except pytz.UnknownTimeZoneError:
            logging.error(f"Unknown timezone: {TIMEZONE}")
            return jsonify({"error": f"Unknown timezone: {TIMEZONE}"}), 400

        # Calculate the threshold time (now - ONLINE_THRESHOLD_MINUTES) in the specified timezone
        threshold_time = datetime.now(tz) - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)
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
                expires = None
                key_healthy = True if device.get("keyExpiryDisabled", False) else True
                if not device.get("keyExpiryDisabled", False) and device.get("expires"):
                    expires = datetime.strptime(device["expires"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
                    expires = expires.astimezone(tz)
                    time_until_expiry = expires - datetime.now(tz)
                    key_healthy = time_until_expiry.total_seconds() / 60 > KEY_THRESHOLD_MINUTES

                logging.debug(f"Device {device['name']} last seen (local): {last_seen_local.isoformat()}")
                online_is_healthy = last_seen_local >= threshold_time
                health_info = {
                    "id": device["id"],
                    "device": device["name"],
                    "machineName": machine_name,
                    "hostname": device["hostname"],
                    "lastSeen": last_seen_local.isoformat(),  # Include timezone offset in ISO format
                    "online_healthy": online_is_healthy,
                    "keyExpiryDisabled": device.get("keyExpiryDisabled", False),
                    "key_healthy": key_healthy,
                    "healthy": online_is_healthy and key_healthy
                }
                
                if not device.get("keyExpiryDisabled", False):
                    health_info["keyExpiryTimestamp"] = expires.isoformat() if expires else None
                
                return jsonify(health_info)

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

        # Fetch data from Tailscale API using the helper function
        response = make_authenticated_request(TAILSCALE_API_URL, auth_header)
        devices = response.json().get("devices", [])

        # Get the timezone object
        try:
            tz = pytz.timezone(TIMEZONE)
        except pytz.UnknownTimeZoneError:
            logging.error(f"Unknown timezone: {TIMEZONE}")
            return jsonify({"error": f"Unknown timezone: {TIMEZONE}"}), 400

        # Calculate the threshold time (now - ONLINE_THRESHOLD_MINUTES) in the specified timezone
        threshold_time = datetime.now(tz) - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)
        logging.debug(f"Threshold time: {threshold_time.isoformat()}")

        # Check health status for each device and filter unhealthy devices
        unhealthy_devices = []
        for device in devices:
            last_seen = datetime.strptime(device["lastSeen"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
            last_seen_local = last_seen.astimezone(tz)  # Convert lastSeen to the specified timezone
            expires = None
            key_healthy = True if device.get("keyExpiryDisabled", False) else True
            if not device.get("keyExpiryDisabled", False) and device.get("expires"):
                expires = datetime.strptime(device["expires"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
                expires = expires.astimezone(tz)
                time_until_expiry = expires - datetime.now(tz)
                key_healthy = time_until_expiry.total_seconds() / 60 > KEY_THRESHOLD_MINUTES

            logging.debug(f"Device {device['name']} last seen (local): {last_seen_local.isoformat()}")
            online_is_healthy = last_seen_local >= threshold_time
            if not online_is_healthy:
                machine_name = device["name"].split('.')[0]  # Extract machine name before the first dot
                health_info = {
                    "id": device["id"],
                    "device": device["name"],
                    "machineName": machine_name,
                    "hostname": device["hostname"],
                    "lastSeen": last_seen_local.isoformat(),  # Include timezone offset in ISO format
                    "online_healthy": online_is_healthy,
                    "keyExpiryDisabled": device.get("keyExpiryDisabled", False),
                    "key_healthy": key_healthy,
                    "healthy": online_is_healthy and key_healthy
                }
                
                if not device.get("keyExpiryDisabled", False):
                    health_info["keyExpiryTimestamp"] = expires.isoformat() if expires else None
                
                unhealthy_devices.append(health_info)

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

        # Fetch data from Tailscale API using the helper function
        response = make_authenticated_request(TAILSCALE_API_URL, auth_header)
        devices = response.json().get("devices", [])

        # Get the timezone object
        try:
            tz = pytz.timezone(TIMEZONE)
        except pytz.UnknownTimeZoneError:
            logging.error(f"Unknown timezone: {TIMEZONE}")
            return jsonify({"error": f"Unknown timezone: {TIMEZONE}"}), 400

        # Calculate the threshold time (now - ONLINE_THRESHOLD_MINUTES) in the specified timezone
        threshold_time = datetime.now(tz) - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)
        logging.debug(f"Threshold time: {threshold_time.isoformat()}")

        # Check health status for each device and filter healthy devices
        healthy_devices = []
        for device in devices:
            last_seen = datetime.strptime(device["lastSeen"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
            last_seen_local = last_seen.astimezone(tz)  # Convert lastSeen to the specified timezone
            expires = None
            key_healthy = True if device.get("keyExpiryDisabled", False) else True
            if not device.get("keyExpiryDisabled", False) and device.get("expires"):
                expires = datetime.strptime(device["expires"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
                expires = expires.astimezone(tz)
                time_until_expiry = expires - datetime.now(tz)
                key_healthy = time_until_expiry.total_seconds() / 60 > KEY_THRESHOLD_MINUTES

            logging.debug(f"Device {device['name']} last seen (local): {last_seen_local.isoformat()}")
            online_is_healthy = last_seen_local >= threshold_time
            if online_is_healthy:
                machine_name = device["name"].split('.')[0]  # Extract machine name before the first dot
                health_info = {
                    "id": device["id"],
                    "device": device["name"],
                    "machineName": machine_name,
                    "hostname": device["hostname"],
                    "lastSeen": last_seen_local.isoformat(),  # Include timezone offset in ISO format
                    "online_healthy": online_is_healthy,
                    "keyExpiryDisabled": device.get("keyExpiryDisabled", False),
                    "key_healthy": key_healthy,
                    "healthy": online_is_healthy and key_healthy
                }
                
                if not device.get("keyExpiryDisabled", False):
                    health_info["keyExpiryTimestamp"] = expires.isoformat() if expires else None
                
                healthy_devices.append(health_info)

        return jsonify(healthy_devices)

    except Exception as e:
        logging.error(f"Error in health_check_healthy: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)