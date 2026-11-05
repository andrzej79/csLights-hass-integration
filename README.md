<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="custom_components/cslab/brand/dark_logo.png">
    <img alt="csLights" src="custom_components/cslab/brand/logo.png" width="320">
  </picture>
</p>

<h1 align="center">csLights for Home Assistant</h1>

<p align="center">
  Home Assistant integration for the <b>csLights</b> home automation system by CS-Lab.
</p>

<p align="center">
  <a href="https://github.com/andrzej79/csLights-hass-integration/releases"><img alt="Release" src="https://img.shields.io/github/v/release/andrzej79/csLights-hass-integration"></a>
  <a href="https://hacs.xyz"><img alt="HACS custom repository" src="https://img.shields.io/badge/HACS-custom-41BDF5.svg"></a>
  <a href="https://github.com/andrzej79/csLights-hass-integration/actions/workflows/tests.yaml"><img alt="Tests" src="https://github.com/andrzej79/csLights-hass-integration/actions/workflows/tests.yaml/badge.svg"></a>
  <a href="https://github.com/andrzej79/csLights-hass-integration/actions/workflows/hassfest.yaml"><img alt="hassfest" src="https://github.com/andrzej79/csLights-hass-integration/actions/workflows/hassfest.yaml/badge.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/github/license/andrzej79/csLights-hass-integration"></a>
</p>

---

The integration connects to the **csHomeMaster** controller of a csLights installation and adds every configured accessory to Home Assistant. Changes are pushed by the controller, so states update instantly, without polling.

## Features

| csLights accessory | In Home Assistant |
|---|---|
| LED PWM drivers and dimmable lights | `light` with brightness |
| On/off lights | `light` |
| Window blinds | `cover` with position, opening and closing state |
| Light and AUX relays | `switch` |
| Wall switches | `sensor` showing the switch value, usable as an automation trigger |

**Diagnostics** (shown under each device's diagnostic entities):
- LED driver temperature
- LED driver VLED input voltage
- Light bus current of each csLights controller

**Devices and areas:**
- Entities are grouped under the hardware module they belong to (LED driver, CSMIO-IO module or csLights controller).
- Each device suggests an area from the room and zone set in the csLights configuration.

**Reliable connection:**
- If the controller restarts or the network drops, entities become unavailable and the integration reconnects by itself.
- If the home configuration was changed on the controller in the meantime, the integration reloads, so new or removed accessories show up without restarting Home Assistant.

## Requirements

- Home Assistant **2024.12** or newer
- A csLights installation with a csHomeMaster controller reachable from Home Assistant on **TCP port 19468**
- Recommended: an up-to-date `CSHomeMasterDaemonApp` on the controller. Older versions can crash when a client requests an accessory that was removed from the configuration.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=andrzej79&repository=csLights-hass-integration&category=integration)

Or add it manually:

1. In Home Assistant, open **HACS**, open the **⋮** menu and choose **Custom repositories**.
2. Add `https://github.com/andrzej79/csLights-hass-integration` with the type **Integration**.
3. Search HACS for **csLights**, download it and restart Home Assistant.

### Manual

1. Download the [latest release](https://github.com/andrzej79/csLights-hass-integration/releases/latest).
2. Copy `custom_components/cslab` into the `custom_components` folder of your Home Assistant configuration.
3. Restart Home Assistant.

## Configuration

[![Open your Home Assistant instance and start setting up csLights.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=cslab)

1. Go to **Settings → Devices & services → Add integration** and choose **csLights**.
2. Enter the host name or IP address of the csHomeMaster controller.

Home Assistant checks the connection before saving. Only one controller can be configured.

To change the controller address later, open the integration and choose **Configure**. The integration connects to the new address straight away.

## Troubleshooting

When the connection to the controller is lost, the log shows one warning when it happens and one when it is restored. For more detail, enable debug logging:

```yaml
logger:
  logs:
    custom_components.cslab: debug
```

If setup fails because the controller is unreachable, Home Assistant keeps retrying in the background and shows the reason on the integration card.

Please report problems in the [issue tracker](https://github.com/andrzej79/csLights-hass-integration/issues).

## Development

The tests run the integration inside Home Assistant against a simulated controller. They need Python 3.14:

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```

For a full development environment with Home Assistant, open the repository in the included VS Code devcontainer.

## License

[MIT](LICENSE)
