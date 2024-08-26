"""The csLights integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .cshome_master import CSHomeMaster

# List the platforms that you want to support.
# For your initial PR, limit it to 1 platform.
PLATFORMS: list[Platform] = [
    Platform.COVER,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# Create ConfigEntry type alias with API object
# Rename type alias and update all entry annotations
type CSNameConfigEntry = ConfigEntry[CSHomeMaster]

_log = logging.getLogger(__name__)


async def async_update_listener(hass: HomeAssistant, entry: CSNameConfigEntry):
    """Handle options update."""
    _log.debug("CSHomeMaster options updated %s", entry.entry_id)
    new_host = entry.options.get("master_host")
    old_host = entry.data.get(CONF_HOST)
    _log.debug("Host set in options: %s", new_host)
    _log.debug("Old Host: %s", old_host)
    if new_host is not None and new_host != "":
        hass.config_entries.async_update_entry(entry, data={CONF_HOST: new_host})
        _log.debug("CSHomeMaster options update done")
    else:
        _log.error("CSHomeMaster options update failed, bad host name")


# Update entry annotation
async def async_setup_entry(hass: HomeAssistant, entry: CSNameConfigEntry) -> bool:
    """Set up csLights from a config entry."""

    # Create API instance
    csmaster = CSHomeMaster(hass, entry)

    # Store the csmaster object in hass.data using DOMAIN and entry_id as keys
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    hass.data[DOMAIN][entry.entry_id] = csmaster
    _log.debug("CSHomeMaster setup entry %s", entry.entry_id)

    if not await csmaster.async_setup():
        _log.error("CSHomeMaster setup failed")
        # return False

    # Forward the setup to the platform(s)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # add options update listener
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    return True


# unload_entry function
async def async_unload_entry(hass: HomeAssistant, entry: CSNameConfigEntry) -> bool:
    """Unload a config entry."""
    _log.debug("Unloading CSHomeMaster entry %s", entry.entry_id)
    csmaster: CSHomeMaster = hass.data[DOMAIN][entry.entry_id]
    if csmaster is not None:
        await csmaster.async_cleanup()
        hass.data[DOMAIN][entry.entry_id] = None
        _log.debug("CSHomeMaster cleanup done")

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
