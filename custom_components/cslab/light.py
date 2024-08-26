"""Support for csLights lights."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .cshome_helpers import AccType, DeviceInfoFromHomeItem, DeviceModelFromType
from .cshome_master import CSHomeMaster, CSLightDev

_log = logging.getLogger(__name__)


def hass_to_cs_brightness(hass_brightness: int) -> float:
    """Convert Home Assistant brightness to csLights brightness."""
    return hass_brightness / 255.0


def cs_to_hass_brightness(cs_brightness: float) -> int:
    """Convert csLights brightness to Home Assistant brightness."""
    return int(cs_brightness * 255.0)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up light entities."""
    csmaster: CSHomeMaster = hass.data[DOMAIN][config_entry.entry_id]
    light_entities = []

    lights = csmaster.get_lights()
    for light in lights:
        item = light.get_home_item()
        if item.accessory.type != AccType.LIGHT:
            continue
        if len(item.all_modules()) == 0:
            continue
        light_entities.append(CSLight(csmaster, light))
    # add light entities to Home Assistant
    async_add_entities(light_entities, True)


class CSLight(LightEntity):
    """Representation of a csLights light."""

    should_poll = False

    def __init__(self, csmaster: CSHomeMaster, dev: CSLightDev) -> None:
        """Initialize the light."""
        item = dev.get_home_item()
        if len(item.accessory.name) == 0:
            self._name = f"csLIGHT_{item.accessory.id:03}"
        else:
            self._name = item.accessory.name
        self._dev = dev
        self._csmaster = csmaster
        self._home_item = item
        if item.has_brightness():
            self._name = f"{item.accessory.location.room}-{item.accessory.location.zone} LED({item.accessory.location.pos_x},{item.accessory.location.pos_y})"
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF

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
        """Return the name of the light."""
        return self._name

    @property
    def brightness(self) -> int:
        """Return the brightness of the light."""
        return cs_to_hass_brightness(self._dev.get_current_brightness())

    @property
    def is_on(self) -> bool | None:
        """Return the state of the light."""
        return self._dev.get_current_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""
        await self._dev.set_target_state(True)
        if ATTR_BRIGHTNESS in kwargs:
            await self._dev.set_target_brightness(
                hass_to_cs_brightness(kwargs[ATTR_BRIGHTNESS])
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the light to turn off."""
        await self._dev.set_target_state(False)

    async def async_update(self) -> None:
        """Fetch new state data for the light."""
        _log.debug(
            "Update request for light %s id:%d",
            self._name,
            self._dev.get_home_item().accessory.id,
        )
        await self._csmaster.updateAccessoryReq(self._home_item.accessory.id)
