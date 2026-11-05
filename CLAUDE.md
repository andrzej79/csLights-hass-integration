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

Development happens in the VS Code devcontainer (`.devcontainer/`, Python 3.14, venv at `/home/vscode/.local/ha-venv`). Its Home Assistant version comes from `requirements_dev.txt` → `requirements_test.txt`, so the devcontainer, the tests and CI all use the version pinned by `pytest-homeassistant-custom-component`.

```sh
# Run Home Assistant with the integration loaded (UI on port 8123).
# Also available as the "Python Debugger: Module" launch config.
python -m homeassistant -c config

# Static checks (no project config, so tool defaults apply). mypy reports the voluptuous
# data_schema arguments, see "Home Assistant compatibility" below.
ruff check custom_components/cslab
mypy custom_components/cslab

# Simulate losing the master connection, to test reconnect behaviour (uses iptables, devcontainer only)
./cshomemaster_block.sh
./cshomemaster_unblock.sh
```

- Tests (`tests/`) run the integration inside real Home Assistant (via `pytest-homeassistant-custom-component`) against `FakeDaemon` in `tests/conftest.py`, which mimics the master's protocol. They run in the devcontainer (`pytest`); outside it, recent Home Assistant versions need a Python 3.14 venv. Keep `FakeDaemon` in line with the real daemon when the protocol changes, and still check bigger changes against a real master.

```sh
pytest                                    # all tests (devcontainer)
pytest tests/test_cslab.py::test_config_flow   # one test

# outside the devcontainer
python3.14 -m venv .venv && .venv/bin/pip install -r requirements_test.txt && .venv/bin/pytest
```
- CI (`.github/workflows/`) runs the tests, hassfest and HACS validation on every push, so `manifest.json`, `hacs.json` and the translation files must pass those validators. GitHub disables scheduled workflows after 60 days without repository activity; re-enable them with `gh workflow enable`.
- The development Home Assistant instance lives in `config/` (git-ignored, also excluded from the Docker build by `.dockerignore`). `postcreate_init.sh` creates `config/configuration.yaml` from `configuration-defaults.yaml`, so make default config changes in the latter. Home Assistant loads the integration straight from `custom_components/cslab` in the repository root because `PYTHONPATH` points there (set in `devcontainer.json` and `launch.json`); don't copy or symlink it into `config/`.
- Debug logging is controlled by the `custom_components.cslab` logger in `config/configuration.yaml`.

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

- `async_setup` starts the receive task, then waits for the connection, home model and module list, with a 5 second timeout for each. If any step fails, `async_setup_entry` cleans up and raises `ConfigEntryNotReady`, so Home Assistant retries.
- The platforms create their entities once, from the device lists filled during setup. Any change to the home model therefore needs a reload of the config entry.
- The receive loop must never die: read errors and timeouts go to `handleConnectionError`, and exceptions from message handlers are logged and skipped.
- `handleConnectionError` retries every 5 seconds. After reconnecting it requests the home model before any accessory states. If the model differs from the one loaded at setup (compared with `_home_model_signature`), it schedules a reload instead of requesting states. Sending `GetAccState` for an accessory the master no longer has crashed older daemons.
- Home model and module list replies are only applied once, at setup. Later home models are only compared with the loaded one.
- Changing the host in the options flow tests the connection, updates `entry.data` and reloads the entry.
- Logging: a failed setup is not logged by the integration itself; `ConfigEntryNotReady` carries `setup_error` and Home Assistant logs it. After setup, an outage logs one warning when it starts and one when the connection is restored; the retries in between are debug only. Commands sent while the master is offline are dropped with a debug log.

### Home Assistant compatibility

- The minimum Home Assistant version is set in `hacs.json` (currently 2024.12.0, the first version where a plain `OptionsFlow` gets `self.config_entry` from Home Assistant). Raise it when using a newer API.
- Since 2026.9, Home Assistant validates with `probatio` and aliases `import voluptuous` to it for custom integrations, so `voluptuous` imports keep working. Importing `probatio` directly would break versions before 2026.9. mypy against current Home Assistant reports the `data_schema` arguments for this reason; that is expected.

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

### Brand images

Icons and logos are in `custom_components/cslab/brand/`, which Home Assistant 2026.3+ prefers over the `home-assistant/brands` repo. Make logo changes there, not in the brands repo. Its `custom_integrations/cslab` copy is legacy and only used by Home Assistant versions before 2026.3. If the integration ever moves into Home Assistant core, remove this folder and add the images to the brands repo instead.
