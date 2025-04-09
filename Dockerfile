# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container
COPY . /app

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port the app runs on
EXPOSE 5000

# Define default environment variables
ENV TAILNET_DOMAIN=example.com
ENV THRESHOLD_MINUTES=5
ENV PORT=5000
ENV TIMEZONE=UTC

# Remove AUTH_TOKEN from here to avoid storing sensitive data in the image

# Define environment variable for Flask
ENV FLASK_APP=healthcheck.py

# Add a health check to verify the container is running
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:$PORT/health || exit 1

# Run the application with Gunicorn
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "healthcheck:app"]
