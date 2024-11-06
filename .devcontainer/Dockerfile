# Use the official Home Assistant image as the base
FROM homeassistant/home-assistant:latest

# Install development tools and utilities
RUN apk update && apk add --no-cache \
    build-base \
    python3 \
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
    iptables \
    nano \
    && pip install --upgrade pip setuptools wheel debugpy

# Create a non-root user (optional but recommended)
RUN adduser -D -h /home/vscode -s /bin/bash vscode
RUN adduser vscode wheel

# Configure sudoers to allow passwordless sudo for wheel group
RUN echo "%wheel ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# Customize bash for the vscode user: PS1 and alias
RUN echo 'export PS1="\[\e[32m\]\u@\h\[\e[m\]:\[\e[34m\]\w\[\e[m\]\$ "' >> /home/vscode/.bashrc && \
    echo 'alias ll="ls -l --group-directories-first"' >> /home/vscode/.bashrc 

# Set the working directory
WORKDIR /workspaces/cslights-integration

# Copy requirements and install Python dependencies
COPY requirements_dev.txt /tmp/pip-tmp/

# install requirements
RUN pip install -r /tmp/pip-tmp/requirements_dev.txt

# Ensure /usr/local/bin and /home/vscode/.local/bin are in PATH
ENV PATH="/usr/local/bin:/home/vscode/.local/bin:${PATH}"

# Expose ports
EXPOSE 8123 5678

# Switch to the non-root user
USER vscode
