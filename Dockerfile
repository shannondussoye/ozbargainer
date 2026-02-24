# Use the official Playwright Python image (includes browsers)
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# Set working directory
WORKDIR /app

# Install Python dependencies and tzdata
COPY requirements.txt .
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y tzdata && \
    pip install --no-cache-dir -r requirements.txt && \
    playwright install chromium && \
    rm -rf /var/lib/apt/lists/*

# Copy source code
COPY . .

# Create directory for database/artifacts if valuable
RUN mkdir -p /app/data

# Set environment variables for generic usage
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Default command: Run the live monitor as a module
CMD ["python3", "-m", "ozbargain.core.monitor"]
