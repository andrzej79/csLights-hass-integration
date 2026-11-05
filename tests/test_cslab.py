"""csLights integration in real Home Assistant against the fake daemon."""

import asyncio
import json

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cslab.const import DOMAIN

from .conftest import accessory, module


def no_usage_reports(caplog):
    bad = [r.getMessage() for r in caplog.records
           if "Detected that" in r.getMessage() or "deprecated" in r.getMessage().lower()]
    assert not bad, bad


async def setup_entry(hass, host="127.0.0.1"):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: host}, title="csLights Master Controller")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def wait_until(hass, pred, timeout=15):
    for _ in range(int(timeout * 10)):
        if pred():
            return True
        await asyncio.sleep(0.1)
        await hass.async_block_till_done()
    return False


async def test_config_flow(hass, daemon, caplog):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result2 = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "   "})
    assert result2["errors"] == {"base": "invalid_host"}

    daemon.stop()  # nothing listening -> cannot_connect
    result3 = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "127.0.0.1"})
    assert result3["errors"] == {"base": "cannot_connect"}

    await daemon.start(daemon.port)
    result4 = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: " 127.0.0.1 "})
    assert result4["type"] is FlowResultType.CREATE_ENTRY
    assert result4["data"] == {CONF_HOST: "127.0.0.1"}
    await hass.async_block_till_done()

    # single_config_entry: a second flow is aborted
    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "single_instance_allowed"

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_unload(entry.entry_id)
    no_usage_reports(caplog)


async def test_setup_entities_and_unload(hass, daemon, caplog):
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED

    ent_reg = er.async_get(hass)
    ids = {e.unique_id: e.entity_id for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)}
    for uid in ("Light.001", "WindowBlind.002", "Relay.003", "Switch.004.switch",
                "Light.001.temp", "Light.001.vled", "lb.00:00:00:00:00:14.0.current"):
        assert uid in ids, (uid, sorted(ids))

    assert await wait_until(hass, lambda: hass.states.get(ids["Light.001"]).state == "on")
    light = hass.states.get(ids["Light.001"])
    assert light.attributes["brightness"] == 127
    assert await wait_until(
        hass, lambda: hass.states.get(ids["WindowBlind.002"]).attributes.get("current_position") == 29
    )  # round(), not int()
    assert await wait_until(hass, lambda: hass.states.get(ids["Relay.003"]).state == "on")
    assert await wait_until(hass, lambda: hass.states.get(ids["Switch.004.switch"]).state == "1")

    # wall switch with two modules is attached to its first module's device
    dev_reg = dr.async_get(hass)
    wall_dev = dev_reg.async_get(ent_reg.async_get(ids["Switch.004.switch"]).device_id)
    assert wall_dev.serial_number == "13"

    # commands reach the master
    await hass.services.async_call("light", "turn_on", {"entity_id": ids["Light.001"], "brightness": 255}, blocking=True)
    await hass.services.async_call("cover", "set_cover_position", {"entity_id": ids["WindowBlind.002"], "position": 57}, blocking=True)
    await asyncio.sleep(0.2)
    sent = [c for c in daemon.commands if c["command"] == "AccSetValue"]
    assert {"command": "AccSetValue", "acc-id": "1", "evt-type": "set-bool", "evt-value": True} in sent
    assert {"command": "AccSetValue", "acc-id": "1", "evt-type": "set-brightness", "evt-value": 1.0} in sent
    assert {"command": "AccSetValue", "acc-id": "2", "evt-type": "set-position", "evt-value": 0.57} in sent

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    no_usage_reports(caplog)


async def test_setup_retry_when_master_down(hass, daemon, caplog):
    daemon.stop()
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert any("cannot connect to 127.0.0.1" in r.getMessage() for r in caplog.records), \
        [r.getMessage() for r in caplog.records]
    # our own code logs nothing above debug for a failed setup
    own = [r.getMessage() for r in caplog.records
           if r.name.startswith("custom_components.cslab") and r.levelno >= 30]
    assert not own, own
    await hass.config_entries.async_unload(entry.entry_id)


async def test_options_flow_changes_host(hass, daemon, caplog):
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    daemon.stop()  # nothing listening -> cannot_connect
    bad = await hass.config_entries.options.async_configure(result["flow_id"], {"master_host": "localhost"})
    assert bad["errors"] == {"base": "cannot_connect"}
    await daemon.start(daemon.port)

    ok = await hass.config_entries.options.async_configure(result["flow_id"], {"master_host": "localhost"})
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert await wait_until(hass, lambda: entry.state is ConfigEntryState.LOADED and entry.data[CONF_HOST] == "localhost")

    assert await hass.config_entries.async_unload(entry.entry_id)
    no_usage_reports(caplog)


async def test_reconnect_and_model_change(hass, daemon, caplog):
    entry = await setup_entry(hass)
    ent_reg = er.async_get(hass)
    relay_id = ent_reg.async_get_entity_id("switch", DOMAIN, "Relay.003")
    assert relay_id

    assert await wait_until(hass, lambda: hass.states.get(relay_id).state == "on", 5)
    # daemon restart with unchanged model: unavailable, then back
    daemon.stop()
    assert await wait_until(hass, lambda: hass.states.get(relay_id).state == "unavailable", 5)
    await asyncio.sleep(7)          # at least one refused retry while the daemon is down
    await daemon.start(daemon.port)
    assert await wait_until(hass, lambda: any("restored" in r.getMessage() for r in caplog.records), 15)
    assert await wait_until(hass, lambda: hass.states.get(relay_id).state == "on", 15)
    msgs = [r.getMessage() for r in caplog.records if r.name.startswith("custom_components.cslab")]
    assert sum("lost" in m for m in msgs) == 1 and sum("restored" in m for m in msgs) == 1, msgs

    # model changed (relay removed) -> integration reloads, relay entity becomes unavailable/removed
    daemon.accessories = [a for a in daemon.accessories if a["accessory"]["id"] != 3]
    daemon.stop()
    await asyncio.sleep(0.5)
    await daemon.start(daemon.port)
    assert await wait_until(
        hass, lambda: any("Home model changed" in r.getMessage() for r in caplog.records), 15)
    assert await wait_until(hass, lambda: entry.state is ConfigEntryState.LOADED, 15)
    await hass.async_block_till_done()
    state = hass.states.get(relay_id)
    assert state is None or state.state == "unavailable", state

    assert await hass.config_entries.async_unload(entry.entry_id)
    no_usage_reports(caplog)


async def test_bad_messages_do_not_stop_receiver(hass, daemon, caplog):
    entry = await setup_entry(hass)
    ent_reg = er.async_get(hass)
    light_id = ent_reg.async_get_entity_id("light", DOMAIN, "Light.001")
    assert await wait_until(hass, lambda: hass.states.get(light_id).state == "on")

    writer = daemon.writers[-1]
    for raw in (
        b"\xff\xfe\n",                                            # invalid UTF-8
        b"[1, 2]\n",                                               # not an object
        b'{"rpl-type": "ctrl-devs-discover", "devs": []}\n',       # ignored broadcast
        b'{"rpl-type": "something-new"}\n',                        # unknown reply type
        b'{"rpl-type": "lbus-status", "module": 5, "lbusIndex": 0, "current": 1}\n',
        b'{"rpl-type": "acc-state", "acc-id": 1, "valid": true, "on": false, "brightness": 0.25}\n',
    ):
        writer.write(raw)
    # the last, valid message is still processed
    assert await wait_until(hass, lambda: hass.states.get(light_id).state == "off")
    assert not any("ctrl-devs-discover" in r.getMessage() and r.levelno >= 30 for r in caplog.records)

    assert await hass.config_entries.async_unload(entry.entry_id)


def entity_ids(hass, entry):
    ent_reg = er.async_get(hass)
    return {e.unique_id: e.entity_id for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)}


async def test_diagnostic_sensors(hass, daemon):
    entry = await setup_entry(hass)
    ids = entity_ids(hass, entry)
    temp, vled = ids["Light.001.temp"], ids["Light.001.vled"]
    lb0, lb1 = ids["lb.00:00:00:00:00:14.0.current"], ids["lb.00:00:00:00:00:14.1.current"]
    assert await wait_until(hass, lambda: hass.states.get(ids["Light.001"]).state == "on")

    daemon.send({"rpl-type": "wled-diag", "sn": "11", "vLed": 24.1, "tNtc": 41.5})
    # the master sends one message per light bus it has, here only bus 0
    daemon.send({"rpl-type": "lbus-status", "module": module(20, 1), "lbusIndex": 0, "current": 0.75})
    assert await wait_until(hass, lambda: hass.states.get(lb0).state == "750.0")
    assert float(hass.states.get(temp).state) == 41.5
    assert float(hass.states.get(vled).state) == 24.1
    assert hass.states.get(lb1).state == "0.0"

    # diagnostics go unavailable with the connection
    daemon.stop()
    assert await wait_until(hass, lambda: hass.states.get(lb0).state == "unavailable", 5)
    assert hass.states.get(temp).state == "unavailable"

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_entity_services_and_states(hass, daemon):
    entry = await setup_entry(hass)
    ids = entity_ids(hass, entry)
    blind, relay, spot, lamp = ids["WindowBlind.002"], ids["Relay.003"], ids["Light.005"], ids["Light.001"]
    # Home Assistant skips service calls to unavailable entities, so wait until
    # the master has sent a state for every entity used below
    for entity_id in (blind, relay, spot, lamp):
        assert await wait_until(hass, lambda e=entity_id: hass.states.get(e).state != "unavailable")

    # on/off light has no brightness
    assert hass.states.get(spot).attributes["supported_color_modes"] == ["onoff"]
    assert hass.states.get(lamp).attributes["supported_color_modes"] == ["brightness"]

    calls = [
        ("cover", "open_cover", blind), ("cover", "close_cover", blind),
        ("switch", "turn_off", relay), ("switch", "turn_on", relay),
        ("light", "turn_on", spot), ("light", "turn_off", lamp),
    ]
    for domain, service, entity_id in calls:
        await hass.services.async_call(domain, service, {"entity_id": entity_id}, blocking=True)
    await asyncio.sleep(0.2)
    sent = [(c["acc-id"], c["evt-type"], c["evt-value"]) for c in daemon.commands if c["command"] == "AccSetValue"]
    assert sent == [
        ("2", "set-position", 1.0), ("2", "set-position", 0.0),
        ("3", "set-bool", False), ("3", "set-bool", True),
        ("5", "set-bool", True), ("1", "set-bool", False),
    ]

    # blind movement and position states pushed by the master
    daemon.send({"rpl-type": "acc-state", "acc-id": 2, "valid": True, "type": "blind",
                 "currPos": 0.5, "cmdPos": 1.0, "state": "BlindUp"})
    assert await wait_until(hass, lambda: hass.states.get(blind).state == "opening")
    daemon.send({"rpl-type": "acc-state", "acc-id": 2, "valid": True, "type": "blind",
                 "currPos": 0.4, "cmdPos": 0.0, "state": "BlindDn"})
    assert await wait_until(hass, lambda: hass.states.get(blind).state == "closing")
    daemon.send({"rpl-type": "acc-state", "acc-id": 2, "valid": True, "type": "blind",
                 "currPos": 0.0, "cmdPos": 0.0, "state": "BlindIdle"})
    assert await wait_until(hass, lambda: hass.states.get(blind).state == "closed")

    # partial light update (brightness only) keeps the on state
    daemon.send({"rpl-type": "acc-state", "acc-id": 1, "valid": True, "brightness": 0.2})
    assert await wait_until(hass, lambda: hass.states.get(lamp).attributes.get("brightness") == 51)
    assert hass.states.get(lamp).state == "on"

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_commands_dropped_while_offline(hass, daemon):
    entry = await setup_entry(hass)
    master = hass.data[DOMAIN][entry.entry_id]
    daemon.stop()
    assert await wait_until(hass, lambda: not master.master_online, 5)
    n = len(daemon.commands)
    assert await master.setAccBoolValue(3, True) is False
    assert await master.updateAccessoryReq(3) is False
    assert len(daemon.commands) == n
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_unsupported_accessory_is_skipped(hass, daemon, caplog):
    daemon.accessories.append(accessory(9, 99, 1, [module(12, 3, 1)], "Future"))
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    ids = entity_ids(hass, entry)
    assert "Light.001" in ids and not any(".009" in uid for uid in ids)
    assert any("Skipping unsupported accessory" in r.getMessage() for r in caplog.records)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_setup_retry_when_home_model_missing(hass, daemon, caplog):
    daemon.silent = {"GetHomeModel"}
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert any("no home model received" in r.getMessage() for r in caplog.records)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_setup_retry_when_module_list_missing(hass, daemon, caplog):
    daemon.silent = {"GetModules"}
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert any("no module list received" in r.getMessage() for r in caplog.records)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_empty_master_sets_up(hass, daemon):
    daemon.accessories, daemon.modules = [], []
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert entity_ids(hass, entry) == {}
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_flow_unexpected_errors(hass, daemon):
    with patch("custom_components.cslab.config_flow.validate_connection", side_effect=ValueError("boom")):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "127.0.0.1"})
        assert result["errors"] == {"base": "unknown"}

    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    bad = await hass.config_entries.options.async_configure(result["flow_id"], {"master_host": "  "})
    assert bad["errors"] == {"base": "invalid_host"}
    with patch("custom_components.cslab.config_flow.validate_connection", side_effect=ValueError("boom")):
        err = await hass.config_entries.options.async_configure(result["flow_id"], {"master_host": "localhost"})
    assert err["errors"] == {"base": "unknown"}
    # unchanged host: no reload, entry stays loaded
    same = await hass.config_entries.options.async_configure(result["flow_id"], {"master_host": "127.0.0.1"})
    assert same["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED and entry.data[CONF_HOST] == "127.0.0.1"
    assert await hass.config_entries.async_unload(entry.entry_id)
