# Dockerfile for API service
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONPATH=/app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    postgresql-client \
    git \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r gardener && useradd -r -g gardener -m gardener

# Set working directory
WORKDIR /app

# Install uv and configure the project virtualenv on PATH
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/app/.venv/bin:/root/.local/bin:${PATH}"

# Copy packaging metadata, lockfile, and source, then sync the locked service environment
COPY pyproject.toml uv.lock README.md /app/
COPY gardener /app/gardener
COPY services /app/services
RUN uv sync --locked --no-dev --extra service --no-editable

# Create necessary directories and set ownership
RUN mkdir -p /app/logs && chown -R gardener:gardener /app

# Switch to non-root user
USER gardener

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()"

# Run the application
CMD ["uvicorn", "services.api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
