# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container
COPY . /app

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install curl for health checks
RUN apt-get update && apt-get install -y curl && apt-get clean

# Expose the port the app runs on
EXPOSE 5000

# Define default environment variables
ENV TAILNET_DOMAIN=example.com
ENV ONLINE_THRESHOLD_MINUTES=5
ENV KEY_THRESHOLD_MINUTES=1440
ENV GLOBAL_HEALTHY_THRESHOLD=100
ENV GLOBAL_ONLINE_HEALTHY_THRESHOLD=100
ENV GLOBAL_KEY_HEALTHY_THRESHOLD=100
ENV GLOBAL_UPDATE_HEALTHY_THRESHOLD=100
ENV UPDATE_HEALTHY_IS_INCLUDED_IN_HEALTH=NO
ENV DISPLAY_SETTINGS_IN_OUTPUT=NO
ENV PORT=5000
ENV TIMEZONE=UTC
ENV INCLUDE_OS=""
ENV EXCLUDE_OS=""
ENV INCLUDE_IDENTIFIER=""
ENV EXCLUDE_IDENTIFIER=""
ENV INCLUDE_TAGS=""
ENV EXCLUDE_TAGS=""
ENV INCLUDE_IDENTIFIER_UPDATE_HEALTHY=""
ENV EXCLUDE_IDENTIFIER_UPDATE_HEALTHY=""
ENV INCLUDE_TAG_UPDATE_HEALTHY=""
ENV EXCLUDE_TAG_UPDATE_HEALTHY=""
ENV GUNICORN_TIMEOUT=120
ENV GUNICORN_GRACEFUL_TIMEOUT=120

# Remove AUTH_TOKEN from here to avoid storing sensitive data in the image

# Define environment variable for Flask
ENV FLASK_APP=healthcheck.py

# Add a health check to verify the container is running
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:$PORT/health || exit 1

# Replace CMD with ENTRYPOINT to allow passing arguments like --help
ENTRYPOINT ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "-c", "gunicorn_config.py", "healthcheck:app"]
