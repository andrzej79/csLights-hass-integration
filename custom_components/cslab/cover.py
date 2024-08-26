"""Support for csLights window blinds."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .cshome_helpers import AccType, DeviceInfoFromHomeItem, DeviceModelFromType
from .cshome_master import CSBlindDev, CSHomeMaster

_log = logging.getLogger(__name__)


def hass_to_cs_position(hass_pos: int) -> float | None:
    """Convert Home Assistant position to csLights position."""
    return hass_pos / 100.0


def cs_to_hass_position(cs_pos: float) -> int | None:
    """Convert csLights position to Home Assistant position."""
    return int(cs_pos * 100.0)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up cover entities."""
    csmaster: CSHomeMaster = hass.data[DOMAIN][config_entry.entry_id]
    cover_entities = []

    blinds = csmaster.get_blinds()
    for blind in blinds:
        item = blind.get_home_item()
        if item.accessory.type != AccType.WINDOWBLIND:
            continue
        if len(item.all_modules()) == 0:
            continue
        cover_entities.append(CSBlind(csmaster, blind))
    # add cover entities to Home Assistant
    async_add_entities(cover_entities, True)


class CSBlind(CoverEntity):
    """Representation of a csLights window blind."""

    should_poll = False

    def __init__(self, csmaster: CSHomeMaster, dev: CSBlindDev) -> None:
        """Initialize the window blind."""
        item = dev.get_home_item()
        if len(item.accessory.name) == 0:
            self._name = f"csBLIND_{item.accessory.id:03}"
        else:
            self._name = item.accessory.name
        self._dev = dev
        self._csmaster = csmaster
        self._home_item = item
        self._attr_device_class = CoverDeviceClass.BLIND
        self._attr_supported_features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.SET_POSITION
        )

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
    def current_cover_position(self) -> int | None:
        """Return the position of the blind."""
        return cs_to_hass_position(self._dev.get_current_position())

    @property
    def is_closed(self) -> bool:
        """Return if the blind is closed."""
        return self._dev.get_current_position() == 0.0

    @property
    def is_opening(self) -> bool:
        """Return if the blind is opening."""
        return self._dev.get_current_state() == "BlindUp"

    @property
    def is_closing(self) -> bool:
        """Return if the blind is closing."""
        return self._dev.get_current_state() == "BlindDn"

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Instruct the blind to open."""
        if ATTR_POSITION in kwargs:
            await self._dev.set_target_position(
                hass_to_cs_position(kwargs[ATTR_POSITION])
            )
        else:
            await self._dev.set_target_position(1.0)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Instruct the blind to close."""
        if ATTR_POSITION in kwargs:
            await self._dev.set_target_position(
                hass_to_cs_position(kwargs[ATTR_POSITION])
            )
        else:
            await self._dev.set_target_position(0.0)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set blind target position."""
        if ATTR_POSITION in kwargs:
            await self._dev.set_target_position(
                hass_to_cs_position(kwargs[ATTR_POSITION])
            )
        else:
            _log.error("Missing position in set_cover_position")

    async def async_update(self) -> None:
        """Update window blind current state."""
        _log.debug("Update request for window blind %s", self._name)
        await self._csmaster.updateAccessoryReq(self._home_item.accessory.id)
