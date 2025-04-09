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
   http://localhost:5000/health
   ```

## Running with Docker

1. **Build the Docker Image**:
   ```bash
   docker build -t tailscale-healthcheck .
   ```

2. **Run the Docker Container**:
   ```bash
   docker run -d -p 5000:5000 \
       --env-file .env \
       -e TAILNET_DOMAIN="example.com" \
       -e THRESHOLD_MINUTES=5 \
       -e TIMEZONE="UTC" \
       --name tailscale-healthcheck tailscale-healthcheck
   ```

3. **Access the Application**:
   Open your browser and navigate to:
   ```
   http://localhost:5000/health
   ```

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