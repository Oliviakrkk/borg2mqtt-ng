FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    BORG2MQTT_CONFIG=/root/.config/borg2mqtt/config.yml

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 \
      python3-venv \
      borgbackup \
      openssh-client \
      ca-certificates \
      cron \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv

# Wheel is built ahead of time with `uv build --wheel` (see local_build.sh /
# .github/workflows/reusable_checks.yml) and expected in ./dist
COPY dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -rf /tmp/*.whl

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
