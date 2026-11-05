# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Home Assistant custom integration (domain `cslab`, distributed via HACS) for the CS-Lab csLights home automation system. It connects to a single master controller over TCP. The only configuration is the master's host name or IP address.

## Related repository

The master controller software (csHomeMaster, a Qt daemon running on a Raspberry Pi Zero) is in the sibling repo at `../csLights/CSHomeMasterDaemonApp`. `../csLights` is a monorepo with its own `CLAUDE.md`. It is the authority on protocol behaviour, so check it rather than guessing what the master sends, and keep this integration in sync when its commands or reply JSON change.

- `src/mastercomconnection.cpp`: command handling and reply JSON
- `src/mastercomconnector.h`: TCP port
- `src/accessories/Acc*State.h`: `acc-state` payload fields
- `../csLights/common/MasterCom/`: protocol types shared by the C++ clients (this integration is a separate Python implementation)

## Development

Development happens in the VS Code devcontainer (`.devcontainer/`, Python 3.12, venv at `/home/vscode/.local/ha-venv`). Scripts and launch configs hard-code the path `/workspaces/csLights-hass-integration`.

```sh
# Run Home Assistant with the integration loaded (UI on port 8123).
# Also available as the "Python Debugger: Module" launch config.
python -m homeassistant -c /workspaces/csLights-hass-integration

# Static checks (no project config, so tool defaults apply; ruff is also available through the VS Code extension)
flake8 custom_components/cslab
mypy custom_components/cslab

# Simulate losing the master connection, to test reconnect behaviour (uses iptables, devcontainer only)
./cshomemaster_block.sh
./cshomemaster_unblock.sh
```

- There are no automated tests. Changes are verified by running Home Assistant against a real master controller.
- CI only runs hassfest and HACS validation (`.github/workflows/`), so `manifest.json`, `hacs.json` and the translation files must pass those validators.
- The repo root doubles as the Home Assistant config directory. `configuration.yaml`, `.storage/`, `home-assistant_v2.db`, logs and similar are git-ignored runtime state. `postcreate_init.sh` creates `configuration.yaml` from `configuration-defaults.yaml`, so make default config changes in the latter.
- Debug logging is controlled by the `custom_components.cslab` logger in `configuration.yaml`.

## Architecture

All code is in `custom_components/cslab/`. Almost all logic is in `cshome_master.py`; the platform files are thin adapters.

```
HA entities (light/cover/switch/sensor.py)
    │  call set_target_*; read get_current_*; register async_write_ha_state as callback
    ▼
Device objects (CSLightDev, CSBlindDev, CSRelayDev, CSWallSwitchDev, CSLightsCtrlModDev)
    │
    ▼
CSHomeMaster: owns the TCP connection and the receive task, stored in hass.data[DOMAIN][entry_id]
```

### Protocol (TCP port 19468, JSON)

- **Outgoing:** `{"command": ...}` objects with no line terminator, because the master finds message boundaries by counting braces: `GetHomeModel`, `GetModules`, `GetAccState`, `AccSetValue`. `acc-id` is sent as a string.
- **Incoming:** newline-delimited JSON, dispatched on `rpl-type` in `parseIncomingData`: `home-model`, `module-list`, `acc-state`, `wled-diag`, `lbus-status`.
- **Value ranges:** brightness and position are `0.0–1.0` on the wire. Conversion to HA's 0–255 and 0–100 happens in `light.py` and `cover.py`.
- **Timeouts:** 60 seconds without received data counts as a connection failure.

### State flow

Entities use `should_poll = False` and are push-driven. A command only writes to the socket, and entity state changes when the master replies with `acc-state`, which updates the device object and fires its callbacks. Entity `async_update` likewise just sends `GetAccState` and does not wait for the answer.

### Startup and reconnect

- `async_setup` starts the receive task, then waits for the connection, home model and module list, with a 5 second timeout for each.
- The platforms create their entities once, from the device lists filled during that step. If setup fails, `async_setup_entry` still returns `True` and the entities are created from empty lists, so they stay missing until the entry is reloaded.
- `handleConnectionError` retries every 5 seconds and then re-requests accessory states, but not the home model.
- `handleIncomingHomeModel` and `handleIncomingModuleList` append to the device lists without clearing them, so requesting either one again would create duplicates.
- Changing the host in the options flow copies it to `entry.data` without reloading. `CSHomeMaster.host` reads it live, so it only takes effect at the next reconnect.

### Data model and entity mapping (`cshome_helpers.py`)

The home model is a list of accessories, each with services, each bound to hardware modules. Accessories are skipped if they have no modules.

| Accessory type | HA platform |
|---|---|
| `LIGHT` | `light` (brightness mode if it has a `BRIGHTNESS` service, otherwise on/off) |
| `WINDOWBLIND` | `cover` |
| `RELAY` | `switch` |
| `SWITCH`, `XORSWITCH` (wall switches) | `sensor` |

`sensor.py` also adds diagnostics: temperature and VLED voltage for `LBUS_WLED` lights, and per-light-bus current for controller modules.

- HA devices represent hardware modules, not accessories (`DeviceInfoFromHomeItem` uses the accessory's first module), so several entities can share one device.
- Entity unique IDs are `{Model}.{id:03}` (for example `Light.007`), with a `.temp`, `.vled` or `.switch` suffix for sensors. Light-bus current sensors use `lb.{mac}.{index}.current`. Changing these formats orphans existing entities in users' registries.

### Translations

UI strings exist in both `strings.json` (which references HA `common::` keys) and `translations/en.json` (which has the resolved English text); update both.
