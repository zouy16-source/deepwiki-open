# syntax=docker/dockerfile:1-labs

# Backend-only image: runs the Python API (api/). The frontend is the separate
# Nuxt app in web/ (run on the host with `npm run dev`, or built/served on its own).

# Build argument for custom certificates directory
ARG CUSTOM_CERT_DIR="certs"

FROM python:3.11-slim AS py_deps
WORKDIR /api
COPY api/pyproject.toml .
COPY api/poetry.lock .
RUN python -m pip install poetry==2.0.1 --no-cache-dir && \
    poetry config virtualenvs.create true --local && \
    poetry config virtualenvs.in-project true --local && \
    poetry config virtualenvs.options.always-copy --local true && \
    POETRY_MAX_WORKERS=10 poetry install --no-interaction --no-ansi --only main && \
    poetry cache clear --all .

# Use Python 3.11 as final image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# git/curl/ca-certificates are needed for repository cloning and TLS.
RUN apt-get update && apt-get install -y \
    curl \
    git \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Update certificates if custom ones were provided and copied successfully
RUN if [ -n "${CUSTOM_CERT_DIR}" ]; then \
        mkdir -p /usr/local/share/ca-certificates && \
        if [ -d "${CUSTOM_CERT_DIR}" ]; then \
            cp -r ${CUSTOM_CERT_DIR}/* /usr/local/share/ca-certificates/ 2>/dev/null || true; \
            update-ca-certificates; \
            echo "Custom certificates installed successfully."; \
        else \
            echo "Warning: ${CUSTOM_CERT_DIR} not found. Skipping certificate installation."; \
        fi \
    fi

ENV PATH="/opt/venv/bin:$PATH"
ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken_cache/

# Copy Python dependencies
COPY --from=py_deps /api/.venv /opt/venv
RUN mkdir -p "$TIKTOKEN_CACHE_DIR"
# China-region: openaipublic.blob.core.windows.net is blocked, so use a
# pre-fetched cl100k_base cache file (sha256-verified) instead of downloading.
COPY tiktoken_cache/9b5ad71b2ce5302211f9c61530b329a4922fc6a4 /opt/tiktoken_cache/9b5ad71b2ce5302211f9c61530b329a4922fc6a4
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
COPY api/ ./api/

# Expose the API port
EXPOSE ${PORT:-8001}

# Startup script: load .env (if mounted) and run the API.
COPY <<'EOF' /app/start.sh
#!/bin/bash
if [ -f .env ]; then
  export $(grep -v "^#" .env | xargs -r)
fi
if [ -z "$OPENAI_API_KEY" ] && [ -z "$GOOGLE_API_KEY" ]; then
  echo "Warning: neither OPENAI_API_KEY nor GOOGLE_API_KEY is set. These are required for DeepWiki to function."
fi
exec python -m api.main --port ${PORT:-8001}
EOF
RUN chmod +x /app/start.sh

# Set environment variables
ENV PORT=8001
ENV SERVER_BASE_URL=http://localhost:${PORT:-8001}

# Create empty .env file (will be overridden if one exists at runtime)
RUN touch .env

# Command to run the application
CMD ["/app/start.sh"]
