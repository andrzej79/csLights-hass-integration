"""Support for csLights switches."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .cshome_helpers import AccType, DeviceInfoFromHomeItem, DeviceModelFromType
from .cshome_master import CSHomeMaster, CSRelayDev

_log = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up relay (switch) entities."""
    csmaster: CSHomeMaster = hass.data[DOMAIN][config_entry.entry_id]
    switch_entities = []

    relays = csmaster.get_relays()
    for relay in relays:
        item = relay.get_home_item()
        if item.accessory.type != AccType.RELAY:
            continue
        if len(item.all_modules()) == 0:
            continue
        switch_entities.append(CSSwitch(csmaster, relay))
    # add cover entities to Home Assistant
    async_add_entities(switch_entities, True)


class CSSwitch(SwitchEntity):
    """Representation of a csLights switch."""

    should_poll = False

    def __init__(self, csmaster: CSHomeMaster, dev: CSRelayDev) -> None:
        """Initialize the switch."""
        item = dev.get_home_item()
        if len(item.accessory.name) == 0:
            self._name = f"csRELAY_{item.accessory.id:03}"
        else:
            self._name = item.accessory.name
        self._dev = dev
        self._csmaster = csmaster
        self._home_item = item
        self._attr_device_class = SwitchDeviceClass.SWITCH

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self._dev.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self._dev.remove_callback(self.async_write_ha_state)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._dev.online and self._csmaster.master_online

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return the device info."""
        return DeviceInfoFromHomeItem(self._home_item)

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        acc = self._home_item.accessory
        return f"{DeviceModelFromType(acc.type)}.{acc.id:03}"

    @property
    def name(self) -> str:
        """Return the name of the window blind."""
        return self._name

    @property
    def is_on(self) -> bool | None:
        """Return the state of the switch."""
        return self._dev.get_current_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._dev.set_target_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._dev.set_target_state(False)

    async def async_update(self) -> None:
        """Update window blind current state."""
        _log.debug("Update request for switch %s", self._name)
        await self._csmaster.updateAccessoryReq(self._home_item.accessory.id)
