# Use official Python slim image for a lightweight production build
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PORT 8000
ENV PYTHONPATH=/app

# Install system dependencies (libpq-dev for PostgreSQL/PostGIS support)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port FastAPI will run on
EXPOSE 8000

# Command to run the application using uvicorn
# alembic upgrade is best-effort; if the DB is unavailable the server still boots.
CMD ["sh", "-c", "alembic upgrade head || echo '[WARN] alembic migration skipped — DB may be unavailable'; uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
