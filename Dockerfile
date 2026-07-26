# Build the React (shadcn/ui) web dashboard
FROM node:22-slim AS frontend-build
WORKDIR /frontend
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate
COPY frontend/package.json frontend/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Create a dedicated non-root user and group for running the app
# Use a fixed UID/GID for easier permission management in runtimes
RUN groupadd -r app && useradd -r -g app -u 10001 appuser

# Copy the current directory contents into the container
COPY . /app

# Copy the built dashboard assets (built by the frontend-build stage above;
# frontend/vite.config.ts outputs to ../static/app relative to /frontend, i.e. /static/app)
COPY --from=frontend-build /static/app /app/static/app

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install curl for health checks and gosu for dropping privileges after fixing
# up bind-mount ownership in the entrypoint (see docker-entrypoint.sh)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gosu \
    && rm -rf /var/lib/apt/lists/*

# Ensure application files are owned by the non-root user
RUN chown -R appuser:app /app

# Persistent SQLite database (settings, users, device/key snapshots, audit log)
RUN mkdir -p /data && chown appuser:app /data
VOLUME ["/data"]

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

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
ENV PORT=5000
ENV TIMEZONE=UTC
ENV DATABASE_PATH=/data/healthcheck.db
ENV POLL_INTERVAL_SECONDS=60
ENV AUDIT_RETENTION_DAYS=14
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

# Container starts as root so the entrypoint can fix /data ownership for
# arbitrary bind mounts, then drops to appuser via gosu before exec'ing gunicorn.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "-c", "gunicorn_config.py", "healthcheck:app"]
