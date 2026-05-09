FROM python:3.9-slim-bullseye

# Install core system dependencies
RUN apt-get update && apt-get install -y \
    cmake \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip for better stability
RUN pip install --upgrade pip

COPY requirements.txt .

# CRITICAL: We set MAKEFLAGS="-j1" to force single-core compilation.
# This keeps RAM usage under 1GB and prevents the "8GiB Out of Memory" crash.
RUN MAKEFLAGS="-j1" pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--workers", "1", "--timeout", "200", "app:app"]