# Tailscale Healthcheck

A Python-based Flask application to monitor the health of devices in a Tailscale network. The application provides endpoints to check the health status of all devices, specific devices, and lists of healthy or unhealthy devices.

## Features

- **Health Status**: Check the health of all devices in the Tailscale network.
- **Device Lookup**: Query the health of a specific device by hostname, ID, or name (case-insensitive).
- **Healthy Devices**: List all healthy devices.
- **Unhealthy Devices**: List all unhealthy devices.
- **Timezone Support**: Adjust `lastSeen` timestamps to a configurable timezone.

## Endpoints

### `/health`
Returns the health status of all devices.

**Example Response**:
```json
[
  {
    "id": "1234567890",
    "device": "examplehostname.example.com",
    "machineName": "examplehostname",
    "hostname": "examplehostname",
    "lastSeen": "2025-04-09T22:03:57+02:00",
    "healthy": true
  }
]
```

### `/health/<identifier>`
Returns the health status of a specific device by hostname, ID, or name.

**Example**:
```
GET /health/examplehostname
```

**Example Response**:
```json
{
  "id": "1234567890",
  "device": "examplehostname.example.com",
  "machineName": "examplehostname",
  "hostname": "examplehostname",
  "lastSeen": "2025-04-09T22:03:57+02:00",
  "healthy": true
}
```

### `/health/healthy`
Returns a list of all healthy devices.

### `/health/unhealthy`
Returns a list of all unhealthy devices.

## Configuration

The application is configured using environment variables:

| Variable           | Default Value | Description                                   |
|--------------------|---------------|-----------------------------------------------|
| `TAILNET_DOMAIN`   | `example.com` | The Tailscale tailnet domain.                |
| `AUTH_TOKEN`       | None          | The Tailscale API token (required).          |
| `THRESHOLD_MINUTES`| `5`           | The threshold in minutes to determine health.|
| `PORT`             | `5000`        | The port the application runs on.            |
| `TIMEZONE`         | `UTC`         | The timezone for `lastSeen` adjustments.     |

### Generating the Tailscale API Key

To use this application, you need to generate a Tailscale API key:

1. Visit the Tailscale Admin Console:  
   [https://login.tailscale.com/admin/settings/keys](https://login.tailscale.com/admin/settings/keys)

2. Click **Generate Key** and copy the generated API key.

3. Set the API key as the `AUTH_TOKEN` environment variable.

**Note**: Ensure the API key is stored securely and not shared publicly.

## Running Locally

1. **Clone the Repository**:
   ```bash
   git clone <repository-url>
   cd tailscale-healthcheck
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the Application**:
   ```bash
   export AUTH_TOKEN="your-secret-token"
   python healthcheck.py
   ```

4. **Access the Application**:
   Open your browser and navigate to:
   ```
   http://IP-ADDRESS_OR_HOSTNAME:5000/health
   ```

## Running with Docker

### Build and Run Locally

1. **Build the Docker Image**:
   ```bash
   docker build -t laitco/tailscale-healthcheck .
   ```

2. **Run the Docker Container**:
   ```bash
   docker run -d -p 5000:5000 \
       --env-file .env \
       -e TAILNET_DOMAIN="example.com" \
       -e THRESHOLD_MINUTES=5 \
       -e TIMEZONE="UTC" \
       --name tailscale-healthcheck laitco/tailscale-healthcheck
   ```

3. **Access the Application**:
   Open your browser and navigate to:
   ```
   http://IP-ADDRESS_OR_HOSTNAME:5000/health
   ```

### Run from Docker Hub

1. **Pull the Docker Image**:
   ```bash
   docker pull laitco/tailscale-healthcheck:latest
   ```

2. **Run the Docker Container**:
   ```bash
   docker run -d -p 5000:5000 \
       --env-file .env \
       -e TAILNET_DOMAIN="example.com" \
       -e THRESHOLD_MINUTES=5 \
       -e TIMEZONE="UTC" \
       --name tailscale-healthcheck laitco/tailscale-healthcheck:latest
   ```

3. **Access the Application**:
   Open your browser and navigate to:
   ```
   http://IP-ADDRESS_OR_HOSTNAME:5000/health
   ```

## Integration with Gatus Monitoring System

You can integrate this healthcheck application with the [Gatus](https://github.com/TwiN/gatus) monitoring system to monitor the health of specific devices.

### Example Configuration

```yaml
endpoints:
  - name: tailscale-examplehostname.example.com
    group: tailscale
    url: "http://IP-ADDRESS_OR_HOSTNAME:5000/health/examplehostname"
    interval: 5m
    conditions:
      - "[STATUS] == 200"
      - "[BODY].healthy == pat(*true*)"
    alerts:
      - type: email
        failure-threshold: 2
        success-threshold: 3
        description: "healthcheck failed"
        send-on-resolved: true
```

### Explanation

- **`name`**: A descriptive name for the endpoint being monitored.
- **`group`**: A logical grouping for endpoints (e.g., `tailscale`).
- **`url`**: The URL of the healthcheck endpoint for a specific device.
- **`interval`**: The frequency of the healthcheck (e.g., every 5 minutes).
- **`conditions`**:
  - `[STATUS] == 200`: Ensures the HTTP status code is `200`.
  - `[BODY].healthy == pat(*true*)`: Checks if the `healthy` field in the response body is `true`.
- **`alerts`**:
  - **`type`**: The type of alert (e.g., `email`).
  - **`failure-threshold`**: The number of consecutive failures before triggering an alert.
  - **`success-threshold`**: The number of consecutive successes before resolving an alert.
  - **`description`**: A description of the alert.
  - **`send-on-resolved`**: Whether to send a notification when the issue is resolved.

For more details on configuring Gatus, refer to the [Gatus documentation](https://github.com/TwiN/gatus).

## Development

### Linting
Run `flake8` to lint the code:
```bash
pip install flake8
flake8 healthcheck.py
```

### Testing
Use `pytest` for testing:
```bash
pip install pytest
pytest
```

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.