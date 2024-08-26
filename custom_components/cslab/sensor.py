"""Support for csLights sensors."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .cshome_helpers import (
    AccType,
    CSModuleType,
    DeviceInfoFromCSModule,
    DeviceInfoFromHomeItem,
    DeviceModelFromType,
)
from .cshome_master import CSHomeMaster, CSLightDev, CSLightsCtrlModDev, CSWallSwitchDev

_log = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    csmaster: CSHomeMaster = hass.data[DOMAIN][config_entry.entry_id]
    sensor_entities: list[CSLightSensorBase] = []

    # prepare LED drivers temperature and voltage sensors
    lights = csmaster.get_lights()
    for light in lights:
        item = light.get_home_item()
        if item.accessory.type != AccType.LIGHT:
            continue
        mods = item.all_modules()
        if len(mods) == 0:
            continue
        if mods[0].type != CSModuleType.LBUS_WLED:
            # Light temp and voltage sensors are only for LBUS-WLED modules
            continue
        sensor_entities.append(CSLightTempSensor(csmaster, light))
        sensor_entities.append(CSLightVoltageSensor(csmaster, light))

    # prepare wall-switch 'sensors'
    wall_switches = csmaster.get_wall_switches()
    for wall_switch in wall_switches:
        item = wall_switch.get_home_item()
        if item.accessory.type not in (AccType.SWITCH, AccType.XORSWITCH):
            continue
        mods = item.all_modules()
        if len(mods) == 0:
            continue
        sensor_entities.append(CSWallSwitchSensor(csmaster, wall_switch))

    # add light-sensor entities to Home Assistant
    async_add_entities(sensor_entities, True)

    # prepare light-bus current diagnostic sensors entities
    lb_sensor_entities: list[CSLightBusSensor] = [
        CSLightBusSensor(csmaster, ctrl_mod_dev, lb_idx)
        for ctrl_mod_dev in csmaster.get_ctrl_mod_devs()
        for lb_idx in range(ctrl_mod_dev.get_lb_count())
    ]
    # add light-bus current sensor entities to Home Assistant
    async_add_entities(lb_sensor_entities, True)


####################################################################################################
# csLights system sensor base class
####################################################################################################
class CSLightSensorBase(SensorEntity):
    """Base class for csLights sensors."""

    should_poll = False

    def __init__(
        self, csmaster: CSHomeMaster, dev: CSLightDev | CSWallSwitchDev
    ) -> None:
        """Initialize the sensor."""
        item = dev.get_home_item()
        self._name: str | None = None
        self._home_item = item
        self._state = None
        self._dev = dev
        self._csmaster = csmaster
        self._attr_state_class = SensorStateClass.MEASUREMENT

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
        return DeviceInfoFromHomeItem(self._dev.get_home_item())

    @property
    def name(self) -> str | None:
        """Return the name of the sensor."""
        return self._name

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        await self._csmaster.updateAccessoryReq(self._home_item.accessory.id)


####################################################################################################
# csLights system led driver temperature sensor class
####################################################################################################
class CSLightTempSensor(CSLightSensorBase):
    """Representation of a csLights temperature sensor."""

    def __init__(self, csmaster: CSHomeMaster, dev: CSLightDev) -> None:
        """Initialize the sensor."""
        super().__init__(csmaster, dev)
        self._name = f"{self._home_item.accessory.name} temp"
        self._attr_icon = "mdi:thermometer"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_suggested_display_precision = 1

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        acc = self._dev.get_home_item().accessory
        return f"{DeviceModelFromType(acc.type)}.{acc.id:03}.temp"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if isinstance(self._dev, CSLightDev):
            return self._dev.get_tntc()
        return None


####################################################################################################
# csLights system led driver voltage sensor class
####################################################################################################
class CSLightVoltageSensor(CSLightSensorBase):
    """Representation of a csLights voltage sensor."""

    def __init__(self, csmaster: CSHomeMaster, dev: CSLightDev) -> None:
        """Initialize the sensor."""
        super().__init__(csmaster, dev)
        self._name = f"{self._home_item.accessory.name} vled"
        self._attr_icon = "mdi:current-dc"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
        self._attr_device_class = SensorDeviceClass.VOLTAGE
        self._attr_suggested_display_precision = 1

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        acc = self._dev.get_home_item().accessory
        return f"{DeviceModelFromType(acc.type)}.{acc.id:03}.vled"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if isinstance(self._dev, CSLightDev):
            return self._dev.get_vled()
        return None


####################################################################################################
# csLights system wall switch 'sensor' class
####################################################################################################
class CSWallSwitchSensor(CSLightSensorBase):
    """Representation of a csLights wall-switch 'sensor'."""

    def __init__(self, csmaster: CSHomeMaster, dev: CSWallSwitchDev) -> None:
        """Initialize the sensor."""
        super().__init__(csmaster, dev)
        if len(self._home_item.accessory.name) == 0:
            self._name = f"csSWITCH_{self._home_item.accessory.id:03}"
        else:
            self._name = self._home_item.accessory.name
        self._attr_device_class = None
        self._attr_translation_key = "cswallswitch"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        acc = self._dev.get_home_item().accessory
        return f"{DeviceModelFromType(acc.type)}.{acc.id:03}.switch"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        return self._dev.get_current_state()


####################################################################################################
# csLightsCtrl module light bus current sensor class
####################################################################################################
class CSLightBusSensor(SensorEntity):
    """CSLightCtrl module light bus current sensor."""

    should_poll = False

    def __init__(
        self, csmaster: CSHomeMaster, dev: CSLightsCtrlModDev, lb_idx: int
    ) -> None:
        """Initialize the sensor."""
        self._name: str = f"lb_{lb_idx} current"
        self._dev = dev
        self._lb_idx = lb_idx
        self._csmaster = csmaster
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:current-dc"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_native_unit_of_measurement = UnitOfElectricCurrent.MILLIAMPERE
        self._attr_device_class = SensorDeviceClass.CURRENT
        self._attr_suggested_display_precision = 0

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self._dev.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self._dev.remove_callback(self.async_write_ha_state)

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        mod = self._dev.get_module()
        return f"lb.{mod.mac}.{self._lb_idx}.current"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return the device info."""
        return DeviceInfoFromCSModule(self._dev.get_module())

    @property
    def name(self) -> str | None:
        """Return the name of the sensor."""
        return self._name

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        current = self._dev.get_lb_current(self._lb_idx)
        if current is None:
            return None
        return current * 1000.0  # native units are mA

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
