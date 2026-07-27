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

# Define default environment variables. Only process-bootstrap concerns and
# the TAILNET_DOMAIN sentinel (a real, non-empty value would be treated as an
# operator-provided override and permanently lock that setting out of the
# admin UI) belong here - everything else in SETTINGS_REGISTRY already has a
# matching default there, so baking a duplicate non-empty ENV value in here
# would make it un-editable via /admin/settings for every stock deployment
# that never explicitly overrode it themselves.
ENV TAILNET_DOMAIN=example.com
ENV PORT=5000
ENV DATABASE_PATH=/data/healthcheck.db
ENV GUNICORN_TIMEOUT=120
ENV GUNICORN_GRACEFUL_TIMEOUT=120

# Remove AUTH_TOKEN from here to avoid storing sensitive data in the image

# Define environment variable for Flask
ENV FLASK_APP=healthcheck.py

# Add a health check to verify the container is running. Uses a small Python
# script (not plain curl) so it can read HEALTH_ENDPOINT_TOKEN from SQLite
# when that setting was only configured via /admin/settings, not an env var.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 /app/docker-healthcheck.py || exit 1

# Starts as root by default so the entrypoint can fix /data ownership for
# arbitrary bind mounts, then drops to appuser via gosu before exec'ing
# gunicorn - but the entrypoint also works correctly if a hardened runtime
# (e.g. Kubernetes runAsUser/runAsNonRoot) already starts it as non-root:
# it detects that and just execs directly, skipping the chown/gosu steps it
# wouldn't have permission for anyway (see docker-entrypoint.sh).
ENTRYPOINT ["docker-entrypoint.sh"]
# --preload imports the app once in the master and forks workers from it, so
# the interpreter, imports, and module-level setup are shared copy-on-write
# instead of duplicated per worker (measured ~74 -> ~63 MiB at 4 workers). It
# also means dbstore.init_db()/sync_env_settings() run once at boot rather than
# racing four times on the same SQLite writer.
#
# Safe with this app's startup work specifically: poller.start() runs in
# post_fork (see gunicorn_config.py), so the fcntl-based single-runner election
# still happens per worker after the fork rather than being inherited.
#
# --max-requests recycles each worker after ~1000 requests (jittered so they
# don't all recycle at once), bounding any slow leak in a long-lived deployment.
# Worker count stays at 4: /health/cache/invalidate and /admin/api/poll-now run
# a full poll cycle synchronously in the request thread, so each in-flight call
# occupies a sync worker for its duration - the spare capacity is deliberate.
CMD ["gunicorn", "-w", "4", "--preload", "--max-requests", "1000", "--max-requests-jitter", "100", \
     "-b", "0.0.0.0:5000", "-c", "gunicorn_config.py", "healthcheck:app"]
