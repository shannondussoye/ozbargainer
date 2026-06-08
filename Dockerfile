# Use the official Playwright Python image (includes browsers)
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

# Set working directory
WORKDIR /app

# Install Python dependencies and tzdata
COPY requirements.lock .
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y tzdata sqlite3 && \
    pip install uv && \
    uv pip sync requirements.lock --system && \
    playwright install chromium && \
    rm -rf /var/lib/apt/lists/*

# Copy source code
COPY . .

# Create directory for database/artifacts if valuable
RUN mkdir -p /app/data

# Non-root user for security
RUN useradd -m -s /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

# Set environment variables for generic usage
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Default command: Run the live monitor as a module
CMD ["python3", "-m", "ozbargain.core.monitor"]
