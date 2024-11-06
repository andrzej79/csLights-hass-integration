# Use the official Home Assistant image as the base
FROM homeassistant/home-assistant:latest

# Install development tools and utilities
RUN apk update && apk add --no-cache \
    build-base \
    python3-dev \
    libffi-dev \
    openssl-dev \
    cargo \
    git \
    bash \
    curl \
    neofetch \
    sudo \
    shadow \
    && pip install --upgrade pip setuptools wheel

# Install VS Code Server for remote development
# ENV DEBIAN_FRONTEND=noninteractive
# RUN curl -fsSL https://code-server.dev/install.sh | sh

# Create a non-root user (optional but recommended)
RUN adduser -D -h /home/vscode -s /bin/bash vscode
RUN adduser vscode wheel

# Configure sudoers to allow passwordless sudo for wheel group
RUN echo "%wheel ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# Set the working directory
WORKDIR /workspaces/cslights-integration

# Expose the Home Assistant port
EXPOSE 8123

# Switch to the non-root user
USER vscode

# Copy requirements and install Python dependencies
COPY requirements_dev.txt /tmp/pip-tmp/
RUN pip install --no-cache-dir -r /tmp/pip-tmp/requirements_dev.txt

# Set the entry point (if necessary)
CMD ["python"]
