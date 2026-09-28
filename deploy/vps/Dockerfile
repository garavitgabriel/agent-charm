# Dex Charm server for the Hermes VPS. Build context: the repo root (server/, notes/, contract/).
FROM python:3.12-slim

ARG DOCKER_CLI_VERSION=27.3.1
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
 && curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz" \
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
