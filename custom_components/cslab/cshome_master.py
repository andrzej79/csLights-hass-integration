"""Code to handle a csLights master."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
import logging

from homeassistant import core
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_VERSION, CONF_HOST

from .const import CSMASTER_TCP_PORT, DOMAIN
from .cshome_helpers import (
    AccType,
    CSHomeItem,
    CSHomeItemFromJson,
    CSModule,
    CSModuleFromJson,
)

_log = logging.getLogger(__name__)


class CSHomeMaster:
    """CS-Lab's home master class."""

    def __init__(self, hass: core.HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the system."""
        self.hass = hass
        self.config_entry = config_entry
        self.port = CSMASTER_TCP_PORT
        self._task: asyncio.Task | None = None
        self._home_items: list[CSHomeItem] = []
        self._lights: list[CSLightDev] = []
        self._blinds: list[CSBlindDev] = []
        self._relays: list[CSRelayDev] = []
        self._switches: list[CSWallSwitchDev] = []
        self._hwModules: list[CSModule] = []
        self._ctrlModDevs: list[CSLightsCtrlModDev] = []
        self._tcpConnectionReady = asyncio.Event()
        self._homeModelReady = asyncio.Event()
        self._moduleListReady = asyncio.Event()
        self._master_online = False
        self._tcpReader: asyncio.StreamReader | None = None
        self._tcpWriter: asyncio.StreamWriter | None = None
        _log.debug("CSHomeMaster initialized host: %s port: %d", self.host, self.port)
        hass.data.setdefault(DOMAIN, {})[self.config_entry.entry_id] = self

    def __del__(self) -> None:
        """Destructor."""
        _log.debug("CSHomeMaster deleted")

    async def async_cleanup(self) -> None:
        """Cleanup."""
        if self._task is not None:
            self._task.cancel()
        if self._tcpWriter is not None:
            self._tcpWriter.close()
        if self._tcpReader is not None:
            self._tcpReader.feed_eof()
        self._home_items.clear()
        self._lights.clear()
        self._blinds.clear()
        self._relays.clear()
        self._switches.clear()
        self._hwModules.clear()
        self._ctrlModDevs.clear()
        _log.debug("CSHomeMaster cleanup completed")

    async def async_setup(self) -> bool:
        """Async setup of cshome master."""
        _log.debug("CSHomeMaster async setup")
        self._task = self.hass.async_create_background_task(
            self.async_task(), name="CSHomeMaster rx handler"
        )
        _log.debug("CSHomeMaster async task created")

        # wait for connection to be ready
        try:
            await asyncio.wait_for(self._tcpConnectionReady.wait(), timeout=5)
        except TimeoutError:
            _log.error("TCP connection with host: %s failed!", self.host)
            return False
        # wait for home model to be received
        try:
            await asyncio.wait_for(self.readHomeModel(), timeout=5)
        except TimeoutError:
            _log.error("Home model receive timeout!")
            return False
        try:
            await asyncio.wait_for(self.getModuleList(), timeout=5)
        except TimeoutError:
            _log.error("Module list receive timeout!")
            return False
        # connection ready, home model received
        _log.debug("CSHomeMaster setup completed")
        return True

    @property
    def master_online(self) -> bool:
        """Return master online status."""
        return self._master_online

    async def async_task(self) -> None:
        """Async task."""
        _log.debug("receiver async_task started")
        try:
            await self.initConnection()
            while True:
                await asyncio.sleep(0)
                if self._master_online is False:
                    await self.handleConnectionError()
                    continue
                if self._tcpReader is None:
                    raise RuntimeError("TCP reader is None")
                try:
                    rplData = await asyncio.wait_for(
                        self._tcpReader.readline(), timeout=60
                    )
                except TimeoutError:
                    _log.error("TCP read timeout")
                    await self.handleConnectionError()
                    continue
                _log.debug("csLights Received data size: %d", len(rplData))
                if len(rplData) == 0:
                    await self.handleConnectionError()
                    continue
                await self.parseIncomingData(rplData)

        except asyncio.CancelledError:
            _log.debug("receiver async_task cancelled")
            return

    async def handleConnectionError(self) -> None:
        """Handle connection error."""
        self._master_online = False
        if self._tcpWriter is not None:
            self._tcpWriter.close()
        if self._tcpReader is not None:
            self._tcpReader.feed_eof()
        await self.devs_publish_update()
        _log.error("Connection error, reconnecting...")
        await asyncio.sleep(5)
        if await self.initConnection() is True:
            await self.update_all_accessories()
            _log.info("Connection restored")

    async def initConnection(self) -> bool:
        """Initialize connection."""
        try:
            connection = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port, limit=16 * 1024 * 1024),
                timeout=5,
            )
            self._tcpReader, self._tcpWriter = connection
        except ConnectionRefusedError:
            _log.error("Connection refused")
            return False
        except OSError as e:
            _log.error("Failed to connect to %s: %s", self.host, e)
            return False
        self._master_online = True
        self._tcpConnectionReady.set()
        return True

    async def parseIncomingData(self, data: bytes) -> None:
        """Parse data."""
        try:
            jrpl = json.loads(data)
        except json.JSONDecodeError as e:
            _log.error(
                "Failed to parse json (exc: %s line: %d pos: %d)",
                e.msg,
                e.lineno,
                e.pos,
            )
            return
        if jrpl.get("rpl-type") == "acc-state":
            await self.handleIncomingAccState(jrpl)
        elif jrpl.get("rpl-type") == "home-model":
            await self.handleIncomingHomeModel(jrpl)
        elif jrpl.get("rpl-type") == "wled-diag":
            await self.handleIncomingWLedDiag(jrpl)
        elif jrpl.get("rpl-type") == "module-list":
            await self.handleIncomingModuleList(jrpl)
        elif jrpl.get("rpl-type") == "lbus-status":
            await self.handleIncomingLBusStatus(jrpl)
        else:
            _log.error("Unknown json data: %s", jrpl)

    async def handleIncomingAccState(self, jrpl: dict) -> None:
        """Handle incoming accessory state."""
        acc_id = jrpl.get("acc-id")
        isValid = jrpl.get("valid")
        if isValid is None or acc_id is None:
            _log.error("Invalid json accessorry state data: %s", jrpl)
            return
        brightness = jrpl.get("brightness")
        isOn = jrpl.get("on")
        currPos = jrpl.get("currPos")
        state = jrpl.get("state")
        value = jrpl.get("value")
        for light in self._lights:
            if light.get_home_item().accessory.id == acc_id:
                await light.set_online(True)
                if brightness is not None and isOn is not None:
                    await light.set_current_brightness_and_state(brightness, isOn)
                    return
                if brightness is not None:
                    await light.set_current_brightness(brightness)
                if isOn is not None:
                    await light.set_current_state(isOn)
                # accessory found, no need to continue
                return
        for blind in self._blinds:
            if blind.get_home_item().accessory.id == acc_id:
                await blind.set_online(True)
                if currPos is not None:
                    _log.debug("acc[%d] currPos: %.2f", acc_id, currPos)
                    await blind.set_current_position(currPos)
                if state is not None:
                    _log.debug("acc[%d] state: %s", acc_id, state)
                    await blind.set_current_state(state)
                # accessory found, no need to continue
                return
        for relay in self._relays:
            if relay.get_home_item().accessory.id == acc_id:
                await relay.set_online(True)
                if state is not None:
                    await relay.set_current_state(state)
                # accessory found, no need to continue
                return
        for switch in self._switches:
            if switch.get_home_item().accessory.id == acc_id:
                await switch.set_online(True)
                if value is not None:
                    _log.debug("update of wall switch %d to %s", acc_id, value)
                    await switch.set_current_state(value)
                # accessory found, no need to continue
                return
        _log.debug("Received state update of unknown device, acc_id: %d", acc_id)

    async def handleIncomingHomeModel(self, jrpl: dict) -> None:
        """Handle incoming home model."""
        # data received, json loaded
        self._home_items.clear()
        accessories = jrpl.get("accessories")
        if accessories is None:
            _log.error("Invalid json (no accessories) home model data: %s", jrpl)
            return
        for acc in accessories:
            await asyncio.sleep(0)
            home_item = CSHomeItemFromJson(acc)
            self._home_items.append(home_item)
            if home_item.accessory.type == AccType.LIGHT:
                lightDev = CSLightDev(self, home_item)
                self._lights.append(lightDev)
            elif home_item.accessory.type == AccType.WINDOWBLIND:
                blindDev = CSBlindDev(self, home_item)
                self._blinds.append(blindDev)
            elif home_item.accessory.type == AccType.RELAY:
                relayDev = CSRelayDev(self, home_item)
                self._relays.append(relayDev)
            elif home_item.accessory.type in (AccType.SWITCH, AccType.XORSWITCH):
                switchDev = CSWallSwitchDev(self, home_item)
                self._switches.append(switchDev)
            else:
                _log.warning("Unknown accessory type: %s", home_item.accessory.type)
            self._homeModelReady.set()

    async def handleIncomingWLedDiag(self, jrpl: dict) -> None:
        """Handle incoming WLED diagnostics."""
        sn = jrpl.get("sn")
        vled = jrpl.get("vLed")
        tntc = jrpl.get("tNtc")
        if sn is None or vled is None or tntc is None:
            _log.error("Invalid json WLED diagnostics data: %s", jrpl)
            return
        for light in self._lights:
            module = light.get_home_item().get_module_by_sn(sn)
            if module is None:
                continue
            await light.updateDiag(vled, tntc)
            _log.debug("updated: WLED diag: sn:%s vled:%.3f tntc:%.3f", sn, vled, tntc)
            # accessory found, no need to continue
            break

    async def handleIncomingModuleList(self, jrpl: dict) -> None:
        """Handle incoming module list."""
        _log.debug("Received module list")
        modules = jrpl.get("modules")
        if modules is None:
            _log.error("Invalid json (no modules) in module list reply: %s", jrpl)
            return
        for mod in modules:
            module = CSModuleFromJson(mod)
            self._hwModules.append(module)
            if "lbusCount" not in mod:
                continue
            lbusCount = mod["lbusCount"]
            if lbusCount > 0:
                self._ctrlModDevs.append(CSLightsCtrlModDev(self, module, lbusCount))
        self._moduleListReady.set()

    async def handleIncomingLBusStatus(self, jrpl: dict) -> None:
        """Handle incoming light bus status."""
        mod_json = jrpl.get("module")

        # Validate essential fields
        if (
            not mod_json
            or "sn" not in mod_json
            or "lbusIndex" not in jrpl
            or "current" not in jrpl
        ):
            _log.error("Invalid json light bus status data: %s", jrpl)
            return

        # Extract necessary values
        sn = mod_json["sn"]
        lbusIdx = jrpl["lbusIndex"]
        current = jrpl["current"]

        # Iterate through control modules and find matching serial number
        for ctrlModDev in self._ctrlModDevs:
            module = ctrlModDev.get_module()
            if module.sn == sn:
                await ctrlModDev.set_lb_current(lbusIdx, current)
                # Trigger update if this is the last light bus index
                if lbusIdx == (ctrlModDev.get_lb_count() - 1):
                    await ctrlModDev.trigger_publish_updates()
                return

    async def setAccBrightnessValue(self, accId: int, value: float) -> bool:
        """Set Accessory Brightness value."""
        data = {
            "command": "AccSetValue",
            "acc-id": str(accId),
            "evt-type": "set-brightness",
            "evt-value": value,
        }
        data_str = json.dumps(data)
        if self._tcpWriter is None:
            _log.error("TCP writer is None")
            return False
        self._tcpWriter.write(data_str.encode())
        return True

    async def setAccBoolValue(self, accId: int, value: bool) -> bool:
        """Set Accessory Boolean value."""
        data = {
            "command": "AccSetValue",
            "acc-id": str(accId),
            "evt-type": "set-bool",
            "evt-value": value,
        }
        data_str = json.dumps(data)
        if self._tcpWriter is None:
            _log.error("TCP writer is None")
            return False
        self._tcpWriter.write(data_str.encode())
        return True

    async def setAccPositionValue(self, accId: int, value: float) -> bool:
        """Set Accessory Position value."""
        data = {
            "command": "AccSetValue",
            "acc-id": str(accId),
            "evt-type": "set-position",
            "evt-value": value,
        }
        data_str = json.dumps(data)
        if self._tcpWriter is None:
            _log.error("TCP writer is None")
            return False
        self._tcpWriter.write(data_str.encode())
        return True

    async def updateAccessoryReq(self, accId: int) -> bool:
        """Request accessory update."""
        data = {
            "command": "GetAccState",
            "acc-id": str(accId),
        }
        data_str = json.dumps(data)
        if self._tcpWriter is None:
            _log.error("TCP writer is None")
            return False
        self._tcpWriter.write(data_str.encode())
        return True

    async def readHomeModel(self) -> bool:
        """Read data from the tcp connection (test)."""
        data = {"command": "GetHomeModel"}
        data_str = json.dumps(data)
        if self._tcpWriter is None:
            _log.error("TCP writer is None")
            return False
        self._tcpWriter.write(data_str.encode())
        await self._tcpWriter.drain()
        # wait for home model to be ready
        try:
            await asyncio.wait_for(self._homeModelReady.wait(), timeout=5)
        except TimeoutError:
            _log.error("Home model not receive timeout")
            return False
        return True

    async def getModuleList(self) -> bool:
        """Get module list."""
        data = {"command": "GetModules"}
        data_str = json.dumps(data)
        if self._tcpWriter is None:
            _log.error("TCP writer is None")
            return False
        self._tcpWriter.write(data_str.encode())
        await self._tcpWriter.drain()
        # wait for module list to be ready
        try:
            await asyncio.wait_for(self._moduleListReady.wait(), timeout=5)
        except TimeoutError:
            _log.error("Module list not receive timeout")
            return False
        return True

    async def update_all_accessories(self) -> None:
        """Update all accessories."""
        for home_item in self._home_items:
            await self.updateAccessoryReq(home_item.accessory.id)

    async def devs_publish_update(self) -> None:
        """Set publish update for all devices."""
        for light in self._lights:
            await light.publish_updates()
        await asyncio.sleep(0.2)
        for blind in self._blinds:
            await blind.publish_updates()
        await asyncio.sleep(0.2)
        for relay in self._relays:
            await relay.publish_updates()
        await asyncio.sleep(0.2)
        for switch in self._switches:
            await switch.publish_updates()

    def get_home_items(self):
        """Return home items."""
        return self._home_items

    def get_lights(self):
        """Return lights."""
        return self._lights

    def get_blinds(self):
        """Return blinds."""
        return self._blinds

    def get_relays(self):
        """Return relays."""
        return self._relays

    def get_wall_switches(self):
        """Return wall switches."""
        return self._switches

    def get_ctrl_mod_devs(self):
        """Return control module devices."""
        return self._ctrlModDevs

    @property
    def host(self) -> str:
        """Return the host of this bridge."""
        return self.config_entry.data[CONF_HOST]

    @property
    def api_version(self) -> int:
        """Return api version we're set-up for."""
        return self.config_entry.data[CONF_API_VERSION]


###################################################
# CSLights system Base device
###################################################
class CSBaseDev:
    """Base class for csLights devices."""

    def __init__(self, csmaster: CSHomeMaster, item: CSHomeItem) -> None:
        """Initialize the device."""
        self._csmaster = csmaster
        self._home_item = item
        self._name = item.accessory.name
        self._online = False
        self._callbacks: set[Callable[[], None]] = set()

    def get_home_item(self) -> CSHomeItem:
        """Return home item."""
        return self._home_item

    def register_callback(self, callback: Callable[[], None]) -> None:
        """Register callback, called when Roller changes state."""
        if callback in self._callbacks:
            _log.warning("Callback already registered!")
        else:
            self._callbacks.add(callback)

    def remove_callback(self, callback: Callable[[], None]) -> None:
        """Remove previously registered callback."""
        self._callbacks.discard(callback)

    @property
    def online(self) -> bool:
        """Return online state."""
        return self._online

    async def set_online(self, online: bool) -> None:
        """Set online state."""
        if self._online == online:
            return
        self._online = online
        await self.publish_updates()

    async def publish_updates(self) -> None:
        """Publish updates to all registered callbacks."""
        for callback in self._callbacks:
            callback()


###################################################
# CSLights system Light device
###################################################
class CSLightDev(CSBaseDev):
    """Representation of a csLights light device."""

    def __init__(self, csmaster: CSHomeMaster, item: CSHomeItem) -> None:
        """Initialize the light."""
        super().__init__(csmaster, item)
        self._diag_vled: float | None = None
        self._diag_tntc: float | None = None
        self._target_state: bool | None = None
        self._current_state: bool | None = None
        self._target_brightness = 0.0
        self._current_brightness = 0.0

    def get_current_state(self) -> bool | None:
        """Return state of the light."""
        return self._current_state

    async def set_current_state(self, state: bool) -> None:
        """Set current state of the light."""
        self._current_state = state
        await self.publish_updates()

    def get_current_brightness(self) -> float:
        """Return brightness of the light."""
        return self._current_brightness

    async def set_current_brightness(self, brightness: float) -> None:
        """Set current brightness of the light."""
        self._current_brightness = brightness
        await self.publish_updates()

    async def set_current_brightness_and_state(
        self, brightness: float, state: bool
    ) -> None:
        """Set current brightness and state of the light."""
        self._current_brightness = brightness
        self._current_state = state
        await self.publish_updates()

    async def set_target_state(self, state: bool) -> None:
        """Set state of the light."""
        await self._csmaster.setAccBoolValue(self._home_item.accessory.id, state)
        self._target_state = state

    async def set_target_brightness(self, brightness: float) -> None:
        """Set brightness of the light."""
        await self._csmaster.setAccBrightnessValue(
            self._home_item.accessory.id, brightness
        )
        self._target_brightness = brightness

    def get_vled(self) -> float | None:
        """Return VLED value."""
        return self._diag_vled

    def get_tntc(self) -> float | None:
        """Return TNTC value."""
        return self._diag_tntc

    async def updateDiag(self, vled: float, tntc: float) -> None:
        """Update diagnostics."""
        self._diag_vled = vled
        self._diag_tntc = tntc
        await self.publish_updates()


###################################################
# CSLights system Window Blind device
###################################################
class CSBlindDev(CSBaseDev):
    """Representation of a csLights window blind device."""

    def __init__(self, csmaster: CSHomeMaster, item: CSHomeItem) -> None:
        """Initialize the window blind."""
        super().__init__(csmaster, item)
        self._current_state: str | None = None
        self._target_position = 0.0
        self._current_position = 0.0

    def get_current_state(self) -> str | None:
        """Return state of the blind."""
        return self._current_state

    async def set_current_state(self, state: str) -> None:
        """Set current state of the blind."""
        self._current_state = state
        await self.publish_updates()

    def get_current_position(self) -> float:
        """Return current position of the blind."""
        return self._current_position

    async def set_current_position(self, pos: float) -> None:
        """Set current position of the blind."""
        self._current_position = pos
        await self.publish_updates()

    async def set_target_position(self, pos: float | None) -> None:
        """Set target position of the blind."""
        if pos is None:
            return
        await self._csmaster.setAccPositionValue(self._home_item.accessory.id, pos)
        self._target_position = pos


###################################################
# CSLights system Relay (switch) device
###################################################
class CSRelayDev(CSBaseDev):
    """Representation of a csLights relay device."""

    def __init__(self, csmaster: CSHomeMaster, item: CSHomeItem) -> None:
        """Initialize the relay."""
        super().__init__(csmaster, item)
        self._current_state: bool | None = None
        self._target_state: bool = False

    def get_current_state(self) -> bool | None:
        """Return state of the relay."""
        return self._current_state

    async def set_current_state(self, state: bool) -> None:
        """Set current state of the relay."""
        self._current_state = state
        await self.publish_updates()

    async def set_target_state(self, state: bool) -> None:
        """Set state of the relay."""
        await self._csmaster.setAccBoolValue(self._home_item.accessory.id, state)
        self._target_state = state


###################################################
# CSLights system wall switch device
###################################################
class CSWallSwitchDev(CSBaseDev):
    """Representation of a csLights wall-switch device."""

    def __init__(self, csmaster: CSHomeMaster, item: CSHomeItem) -> None:
        """Initialize the switch."""
        super().__init__(csmaster, item)
        self._current_state: bool | None = None

    def get_current_state(self) -> bool | None:
        """Return state of the switch."""
        return self._current_state

    async def set_current_state(self, state: bool) -> None:
        """Set current state of the switch."""
        self._current_state = state
        await self.publish_updates()


###################################################
# CSLightsCtrl module device
###################################################
class CSLightsCtrlModDev:
    """Base class for csLights devices."""

    def __init__(self, csmaster: CSHomeMaster, module: CSModule, lb_count: int) -> None:
        """Initialize the device."""
        self._csmaster = csmaster
        self._module = module
        self._callbacks: set[Callable[[], None]] = set()
        self._lbCurrents: list[float] = [0.0] * lb_count

    def get_module(self) -> CSModule:
        """Return module."""
        return self._module

    def get_lb_count(self) -> int:
        """Return light bus count."""
        return len(self._lbCurrents)

    def get_lb_current(self, lb_idx: int) -> float | None:
        """Return light bus current."""
        if lb_idx < len(self._lbCurrents):
            return self._lbCurrents[lb_idx]
        return None

    async def set_lb_current(self, lb_idx: int, current: float) -> None:
        """Set light bus current."""
        if lb_idx < len(self._lbCurrents):
            self._lbCurrents[lb_idx] = current

    async def trigger_publish_updates(self) -> None:
        """Trigger publish updates."""
        await self.publish_updates()

    def register_callback(self, callback: Callable[[], None]) -> None:
        """Register callback, called when Roller changes state."""
        if callback in self._callbacks:
            _log.warning("Callback already registered!")
        else:
            self._callbacks.add(callback)

    def remove_callback(self, callback: Callable[[], None]) -> None:
        """Remove previously registered callback."""
        self._callbacks.discard(callback)

    async def publish_updates(self) -> None:
        """Publish updates to all registered callbacks."""
        for callback in self._callbacks:
            callback()
