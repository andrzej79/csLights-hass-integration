"""Helper functions for CSHome."""

from dataclasses import dataclass
from enum import Enum
import logging

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN

_log = logging.getLogger(__name__)


class AccType(Enum):
    """Enum for accessory type."""

    ANY = 0
    LIGHT = 1
    RELAY = 2
    WINDOWBLIND = 3
    SWITCH = 4
    XORSWITCH = 5


class SvcType(Enum):
    """Enum for service type."""

    ANY = 0
    BOOLEAN = 1
    BRIGHTNESS = 2
    COLOR = 3
    POSITION = 4


class SvcRole(Enum):
    """Enum for service role."""

    ANY = 0
    ACTUATOR = 1
    INITIATOR = 2


class CSModuleType(Enum):
    """Enum for module type."""

    ANY = 0
    CSLIGHT_CTRL = 1
    LBUS_WLED = 2
    CSMIO_IO = 3


@dataclass
class AccessoryLocation:
    """Class for accessory location."""

    room: str
    zone: str
    pos_x: int
    pos_y: int
    pos_z: int


@dataclass
class Accessory:
    """Class for accessory."""

    id: int
    name: str
    type: AccType
    location: AccessoryLocation


@dataclass
class CSModule:
    """Class for module."""

    mac: str
    sn: str
    name: str
    type: CSModuleType
    index: int

    def __eq__(self, other):
        """Return True if equal."""
        if isinstance(other, CSModule):
            return (
                self.mac == other.mac
                and self.sn == other.sn
                and self.name == other.name
                and self.type == other.type
                and self.index == other.index
            )
        return False

    def __hash__(self):
        """Return hash."""
        return hash((self.mac, self.sn, self.name, self.type, self.index))

    def __repr__(self):
        """Return string representation."""
        return f"CSModule(mac={self.mac}, sn={self.sn}, name={self.name}, type={self.type}, index={self.index})"


@dataclass
class CSLightBus:
    """Class for LightBus."""

    module: CSModule
    index: int


@dataclass
class Service:
    """Class for service."""

    id: int
    role: SvcRole
    type: SvcType


@dataclass
class CSHomeSvcItem:
    """Class for home service item."""

    service: Service
    modules: list[CSModule]


@dataclass
class CSHomeItem:
    """Class for home item."""

    accessory: Accessory
    services: list[CSHomeSvcItem]

    def has_brightness(self) -> bool:
        """Return True if accessory has brightness service."""
        return any(svc.service.type == SvcType.BRIGHTNESS for svc in self.services)

    def get_module_by_sn(self, sn: str) -> CSModule | None:
        """Return module by serial number."""
        for svc in self.services:
            for module in svc.modules:
                if module.sn == sn:
                    return module
        return None

    def all_modules(self) -> list[CSModule]:
        """Return all modules without duplicates."""
        unique_modules = set()  # Use a set to track unique modules
        for svc in self.services:
            for module in svc.modules:
                unique_modules.add(module)  # Add each module to the set
        return list(unique_modules)  # Convert the set back to a list

    def get_brightness_svc(self) -> CSHomeSvcItem | None:
        """Return brightness service."""
        for svc in self.services:
            if svc.service.type == SvcType.BRIGHTNESS:
                return svc
        return None


def CSModuleFromJson(data) -> CSModule:
    """Create CSModule from dict."""
    return CSModule(
        mac=data.get("mac"),
        sn=data.get("sn"),
        name=data.get("name"),
        type=CSModuleType(data.get("type")),
        index=data.get("index"),
    )


def CSHomeItemFromJson(data) -> CSHomeItem:
    """Create CSHomeItem from dict."""
    acc_dict = data.get("accessory")
    loc_dict = acc_dict.get("location")

    accessory = Accessory(
        id=acc_dict.get("id"),
        name=acc_dict.get("name"),
        type=AccType(acc_dict.get("type")),
        location=AccessoryLocation(
            room=loc_dict.get("room"),
            zone=loc_dict.get("zone"),
            pos_x=loc_dict.get("pos_x"),
            pos_y=loc_dict.get("pos_y"),
            pos_z=loc_dict.get("pos_z"),
        ),
    )
    services = []
    for svc_item in data.get("services"):
        svc = svc_item.get("service")
        service = Service(
            id=svc.get("id"),
            role=SvcRole(svc.get("role")),
            type=SvcType(svc.get("type")),
        )
        modules = []
        for mod in svc_item.get("modules"):
            module = CSModuleFromJson(mod)
            if module not in modules:
                modules.append(module)
            else:
                _log.warning("Duplicate module %s", module)
        services.append(CSHomeSvcItem(service=service, modules=modules))
    return CSHomeItem(accessory=accessory, services=services)


def DeviceModelFromType(acc_type: AccType) -> str:
    """Return device model from accessory type."""
    if acc_type == AccType.LIGHT:
        return "Light"
    if acc_type == AccType.RELAY:
        return "Relay"
    if acc_type == AccType.WINDOWBLIND:
        return "WindowBlind"
    if acc_type == AccType.SWITCH:
        return "Switch"
    if acc_type == AccType.XORSWITCH:
        return "XorSwitch"
    return "unknown"


def DeviceInfoFromCSModule(module: CSModule) -> DeviceInfo:
    """Create DeviceInfo from CSModule."""
    if module.type == CSModuleType.CSMIO_IO:
        dev_name = f"CSMIO-IO addr.{module.index}"
        dev_model = "CSMIO-IO CAN"
    elif module.type == CSModuleType.LBUS_WLED:
        dev_name = "LBUS-WLED Driver"
        dev_model = "csLEDPWM Driver"
    elif module.type == CSModuleType.CSLIGHT_CTRL:
        dev_name = "csLIGHT Controller"
        dev_model = "csLightsCtrl F7x"
    else:
        dev_name = "Unknown"
        dev_model = "Unknown"

    return DeviceInfo(
        identifiers={(DOMAIN, f"{module.type}_{module.index}_{module.sn}")},
        name=dev_name,
        model=dev_model,
        manufacturer="CS-Lab s.c.",
        serial_number=module.sn,
    )


def DeviceInfoFromHomeItem(item: CSHomeItem) -> DeviceInfo | None:
    """Create DeviceInfo from CSHomeItem."""
    mods = item.all_modules()
    if len(mods) == 0:
        _log.warning("No modules for accessory %s", item.accessory.name)
        return None
    if len(mods) > 1:
        _log.warning("More than one module for accessory %s", item.accessory.name)
    if item.accessory.location.room != item.accessory.location.zone:
        suggested_area = (
            f"{item.accessory.location.room}-{item.accessory.location.zone}"
        )
    else:
        suggested_area = item.accessory.location.room

    devInfo = DeviceInfoFromCSModule(mods[0])
    devInfo["suggested_area"] = suggested_area
    return devInfo
