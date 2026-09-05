FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 \
      python3-venv \
      borgbackup \
      openssh-client \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv

# Wheel is built ahead of time with `uv build --wheel` (see local_build.sh /
# .github/workflows/reusable_checks.yml) and expected in ./dist
COPY dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -rf /tmp/*.whl

ENTRYPOINT ["borg2mqtt"]
CMD ["--help"]
