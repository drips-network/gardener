# Dockerfile for API service
FROM python:3.9.21-slim

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
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r gardener && useradd -r -g gardener -m gardener

# Set working directory
WORKDIR /app

# Install uv and project dependencies via packaging extras
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
# uv installs to ~/.local/bin by default on Debian slim
ENV PATH="/root/.local/bin:${PATH}"

# Copy packaging metadata and source, then install service extras
# Copy application code (services) early to allow optional pinned install
COPY services /app/services

COPY pyproject.toml README.md /app/
COPY gardener /app/gardener
# Optionally use pinned requirements for reproducible builds if present
RUN if [ -f /app/services/requirements.txt ]; then \
        uv pip install -r /app/services/requirements.txt ; \
    else \
        uv pip install -e '.[service]' ; \
    fi

# (services already copied above)

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
