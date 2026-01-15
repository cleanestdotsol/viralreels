# Use Python 3.12 slim image as base
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies including FFmpeg, fonts, and PostgreSQL client
RUN apt-get update && apt-get install -y \
    ffmpeg \
    gcc \
    g++ \
    postgresql-client \
    fonts-freefont-ttf \
    fonts-liberation \
    fontconfig \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p videos temp_slides flask_session

# Set permissions for videos directory
RUN chmod 755 videos temp_slides flask_session

# Expose port
EXPOSE 8080

# Use gunicorn to run the application
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "120"]
