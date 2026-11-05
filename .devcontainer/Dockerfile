# Development container for the csLights Home Assistant integration.
# Recent Home Assistant releases need Python 3.14.
FROM mcr.microsoft.com/devcontainers/python:3.14

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# System packages:
# - iptables: cshomemaster_block.sh / cshomemaster_unblock.sh (needs --cap-add=NET_ADMIN)
# - ffmpeg, libturbojpeg0, libpcap0.8: used by integrations in Home Assistant's default_config
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ffmpeg \
        iptables \
        libpcap0.8 \
        libturbojpeg0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# go2rtc is needed by default_config (camera streaming); use the version
# recommended by Home Assistant (homeassistant/components/go2rtc/const.py)
COPY --from=ghcr.io/alexxit/go2rtc:1.9.14 /usr/local/bin/go2rtc /usr/local/bin/go2rtc

RUN pip3 install --no-cache-dir uv

USER vscode
ENV VIRTUAL_ENV="/home/vscode/.local/ha-venv"
RUN uv venv "$VIRTUAL_ENV" \
    && echo 'source "$HOME/.local/ha-venv/bin/activate"' >> "$HOME/.bashrc"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Home Assistant (version pinned by the test harness), test and lint tools
WORKDIR /tmp/requirements
COPY requirements_dev.txt requirements_test.txt ./
RUN uv pip install -r requirements_dev.txt

WORKDIR /workspaces
ENV SHELL=/bin/bash
