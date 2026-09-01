FROM python:3.14-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Extra web dependencies
RUN pip install --no-cache-dir fastapi uvicorn jinja2 python-multipart httpx

# Application code
COPY app.py .
COPY templates/ ./templates/

# Create a non-root user and set ownership
RUN mkdir -p /data /app/logs && \
    useradd -m -u 1000 webapp && \
    chown -R webapp:webapp /app /data

USER webapp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Start the application
CMD ["python", "app.py"]
