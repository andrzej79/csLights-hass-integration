#!/bin/sh

if [ ! -f /workspaces/csLights-hass-integration/configuration.yaml ]; then 
    cp /workspaces/csLights-hass-integration/configuration-defaults.yaml /workspaces/csLights-hass-integration/configuration.yaml; 
fi

if [ ! -f /workspaces/csLights-hass-integration/automations.yaml ]; then 
    echo "[]" >/workspaces/csLights-hass-integration/automations.yaml
fi

if [ ! -f /workspaces/csLights-hass-integration/scripts.yaml ]; then 
    touch /workspaces/csLights-hass-integration/scripts.yaml
fi

if [ ! -f /workspaces/csLights-hass-integration/scenes.yaml ]; then 
    touch /workspaces/csLights-hass-integration/scenes.yaml
fi

if [ ! -f /workspaces/csLights-hass-integration/secrets.yaml ]; then 
    touch /workspaces/csLights-hass-integration/secrets.yaml
fi

sed -i "s|#alias ll='ls -l'|alias ll='ls -l --group-directories-first'|" /home/vscode/.bashrc

