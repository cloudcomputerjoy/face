# Use a stable Debian-based Python image
FROM python:3.9-slim-bullseye

# Fix for Exit Code 100: Clean lists and add retries for stability
# These libraries are required for dlib, face_recognition, and OpenCV
RUN apt-get clean && apt-get update -o Acquire::Retries=3 && apt-get install -y \
    cmake \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set the internal working directory
WORKDIR /app

# Copy requirements first (improves build speed via caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy your app.py and other files into the container
COPY . .

# Expose the port used by Render
EXPOSE 10000

# Run using Gunicorn (Production-grade server)
# Timeout is set to 120s to allow for heavy AI processing
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--workers", "1", "--timeout", "120", "app:app"]