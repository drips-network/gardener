FROM python:3.9.21-slim

# System deps for common packages and tooling
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git build-essential curl ca-certificates \
    # convenience CLIs
    postgresql-client redis-tools \
    # Node for hardhat helper
    nodejs npm \
    # optional: docker CLI if your cloud allows host socket mounting
    docker.io docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# Speed up pip a bit; keep wheels around
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Non-root user
RUN useradd -ms /bin/bash vscode
USER vscode
WORKDIR /workspaces/gardener

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
ENV PATH="/home/vscode/.local/bin:${PATH}"
