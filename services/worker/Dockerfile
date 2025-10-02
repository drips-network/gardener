# Dockerfile for Worker service
FROM python:3.9.21-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONPATH=/app

# Install system dependencies including git and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    git \
    curl ca-certificates \
    nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user with home directory
RUN groupadd -r gardener && useradd -r -g gardener -m gardener

# Set working directory
WORKDIR /app

# Install uv and project dependencies via packaging extras
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
# uv installs to ~/.local/bin by default on Debian slim
ENV PATH="/root/.local/bin:${PATH}"

# Copy packaging metadata and source, then install service extras
COPY pyproject.toml README.md /app/
COPY gardener /app/gardener

# Install Node helper dependencies for Hardhat TS config parsing (isolated to helper subdir)
RUN cd /app/gardener/external_helpers/hardhat_config_parser \
    && npm ci --omit=dev

# Copy application code (services) early to allow optional pinned install
COPY services /app/services

# Optionally use pinned requirements for reproducible builds if present
RUN if [ -f /app/services/requirements.txt ]; then \
        uv pip install --system -r /app/services/requirements.txt ; \
    else \
        uv pip install --system -e '.[service]' ; \
    fi

# (services already copied above)

# Create necessary directories and set ownership
RUN mkdir -p /app/logs /app/workdir && chown -R gardener:gardener /app

# Switch to non-root user
USER gardener

# Configure git to allow operations in /app/workdir
RUN git config --global --add safe.directory '*'

# Health check (checking if Celery worker is responsive)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD celery -A services.worker.app.main inspect ping

# Run the Celery worker
CMD ["celery", "-A", "services.worker.app.main", "worker", "--loglevel=info", "--concurrency=1", "-n", "gardener-worker@%h"]
