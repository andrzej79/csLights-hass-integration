#!/bin/sh
# Creates the development Home Assistant instance in config/ (git-ignored).
# Runs once after the devcontainer is created; existing files are kept.

cd "$(dirname "$0")" || exit 1
mkdir -p config

if [ ! -f config/configuration.yaml ]; then
    cp configuration-defaults.yaml config/configuration.yaml
fi

if [ ! -f config/automations.yaml ]; then
    echo "[]" > config/automations.yaml
fi

for f in scripts.yaml scenes.yaml secrets.yaml; do
    [ -f "config/$f" ] || touch "config/$f"
done

sed -i "s|#alias ll='ls -l'|alias ll='ls -l --group-directories-first'|" "$HOME/.bashrc"
