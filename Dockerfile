FROM python:3.10-slim

# =========================
# SYSTEM DEPENDENCIES
# =========================
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# =========================
# WORK DIRECTORY
# =========================
WORKDIR /app

# =========================
# PIP UPGRADE
# =========================
RUN pip install --upgrade pip setuptools wheel

# =========================
# INSTALL PYTHON PACKAGES
# =========================
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# =========================
# COPY PROJECT FILES
# =========================
COPY . .

# =========================
# ENV SETTINGS (OPTIONAL SAFE DEFAULTS)
# =========================
ENV PYTHONUNBUFFERED=1
ENV TF_CPP_MIN_LOG_LEVEL=2

# =========================
# PORT
# =========================
EXPOSE 10000

# =========================
# RUN SERVER
# =========================
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--workers", "1", "--timeout", "300", "app:app"]