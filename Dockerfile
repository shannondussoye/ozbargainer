# Use the official Playwright Python image (includes browsers)
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Ensure matching browser binaries are installed
# (In case pip installs a newer version than the base image provides)
RUN playwright install chromium

# Copy source code
COPY . .

# Create directory for database/artifacts if valuable
RUN mkdir -p /app/data

# Set environment variables for generic usage
ENV PYTHONUNBUFFERED=1

# Default command (can be overridden)
CMD ["python", "fetch_user_activity.py", "--help"]
