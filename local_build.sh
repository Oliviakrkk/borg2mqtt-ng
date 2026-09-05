#!/usr/bin/env bash
# Build the python wheel and the docker image locally.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Running tests with uv"
uv sync --dev
uv run pytest

echo "==> Building python wheel with uv"
rm -rf dist
uv build --wheel

echo "==> Building docker image (linux/amd64)"
docker build --platform=linux/amd64 -t borg2mqtt-ng:local .

echo "==> Done. Run it with:"
echo "    docker run --rm borg2mqtt-ng:local --help"
