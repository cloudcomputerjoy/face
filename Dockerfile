# Use bookworm instead of bullseye/slim for better mirror support
FROM python:3.9-slim-bookworm

# Fix for Exit Code 100: Add retries and clean the cache
RUN apt-get update --fix-missing && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Use a single worker to stay under 512MB RAM
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--workers", "1", "--timeout", "120", "app:app"]