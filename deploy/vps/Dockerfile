# Dex Charm server. Build context: the repo root (server/, notes/, contract/).
FROM python:3.12-slim

# The Docker CLI is only used by CHARM_AGENT=hermes (docker exec into a Hermes container).
ARG DOCKER_CLI_VERSION=27.3.1
ARG DOCKER_ARCH=x86_64
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
 && curl -fsSL "https://download.docker.com/linux/static/stable/${DOCKER_ARCH}/docker-${DOCKER_CLI_VERSION}.tgz" \
    | tar -xz --strip-components=1 -C /usr/local/bin docker/docker \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv==0.12.1

WORKDIR /app
COPY contract/ contract/
COPY notes/ notes/
COPY server/ server/
WORKDIR /app/server
RUN uv sync --frozen --no-dev
# Preload Whisper base into the image so the first question isn't a 150 MB download.
ENV HF_HOME=/app/hf
RUN uv run --no-dev python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')"

EXPOSE 8765
CMD ["uv", "run", "--no-dev", "charm-server"]
