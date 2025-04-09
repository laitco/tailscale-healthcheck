import os
import requests
from datetime import datetime, timedelta
from flask import Flask, jsonify, redirect
import pytz
import logging  # Add logging for debugging

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

# Log the configured timezone
logging.debug(f"Configured TIMEZONE: {TIMEZONE}")

@app.route('/health', methods=['GET'])
def health_check():
    try:
        # Fetch data from Tailscale API
        response = requests.get(
            TAILSCALE_API_URL,
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"}
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
        # Fetch data from Tailscale API
        response = requests.get(
            TAILSCALE_API_URL,
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"}
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
        # Fetch data from Tailscale API
        response = requests.get(
            TAILSCALE_API_URL,
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"}
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
        # Fetch data from Tailscale API
        response = requests.get(
            TAILSCALE_API_URL,
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"}
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