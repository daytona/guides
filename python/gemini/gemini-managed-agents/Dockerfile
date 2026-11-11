# Worker image for Gemini Managed Agents self-hosted environments.
# build_snapshot.py builds it into a Daytona snapshot named
# gemini-managed-agents-<sha8>, where <sha8> comes from this file's SHA-256.
FROM python:3.12-slim-bookworm

ARG GEMINI_API_CLI_VERSION=0.4.6

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash ca-certificates curl git jq procps ripgrep \
    && rm -rf /var/lib/apt/lists/*

# The gemini-api CLI is the worker: `environments connect` and `environments serve`.
# Install a pinned release and verify it against the published checksums.
RUN set -eux; \
    case "$(uname -m)" in \
        x86_64) arch=x86_64 ;; \
        aarch64) arch=arm64 ;; \
        *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;; \
    esac; \
    url="https://github.com/google-gemini/gemini-api-cli/releases/download/v${GEMINI_API_CLI_VERSION}"; \
    cd /tmp; \
    curl -fsSLO "${url}/gemini-api_Linux_${arch}.tar.gz"; \
    curl -fsSLO "${url}/checksums.txt"; \
    grep " gemini-api_Linux_${arch}.tar.gz\$" checksums.txt | sha256sum -c -; \
    tar -xzf "gemini-api_Linux_${arch}.tar.gz" -C /usr/local/bin gemini-api; \
    rm -f "gemini-api_Linux_${arch}.tar.gz" checksums.txt; \
    gemini-api version

# Root for the agent's file tools and the working directory for its shell commands.
RUN mkdir -p /workspace && chmod 777 /workspace

WORKDIR /workspace
