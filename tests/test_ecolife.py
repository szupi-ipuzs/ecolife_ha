"""Tests for the EcoLife integration (config flow, setup, polling)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import device_registry as dr

from custom_components.ecolife.api import API_URL, PATH_LOGIN, PATH_USER_SEARCH
from custom_components.ecolife.const import CONF_SCAN_INTERVAL, DOMAIN

LOGIN_URL = API_URL + PATH_LOGIN
SEARCH_URL = API_URL + PATH_USER_SEARCH
TOKEN = "a" * 32

LOGIN_OK = {"status": 0, "data": TOKEN, "settings": {"logLevel": "INFO"}}
LOGIN_BAD = {"status": 1, "data": "emailPasswordError", "settings": None}
SEARCH_REJECTED = {"status": 1, "measurePoints": None, "observedMPs": None, "aggMeasures": None}


def _m(t: str, unit: str, value: str) -> dict[str, Any]:
    return {"unit": unit, "value": value, "measureType": t, "min": "0", "max": "100", "norm": "25", "valuePercentage": "50"}


def _mp(mp_id: str, name: str, pm25: str = "27.00") -> dict[str, Any]:
    return {
        "id": mp_id,
        "userId": "u1",
        "name": name,
        "uuids": ["8a23f35945084ebab2e0b39e50ad0b61"],
        "location": {"latitude": 49.0, "longtitude": 20.4},
        "latest": {
            "PRESSURE": _m("PRESSURE", "Pa", "967.35"),
            "TEMP": _m("TEMP", "C", "20.46"),
            "HUMIDITY": _m("HUMIDITY", "pc", "44.41"),
            "VOC": _m("VOC", "chwc", "106"),
            "PM25": _m("PM25", "ugm3", pm25),
            "PM10": _m("PM10", "ugm3", "29.00"),
            "CONTAMINATION": _m("CONTAMINATION", "pc", "108"),
        },
        "site": "in",
        "origin": "ecolife",
        "lastUpdate": {"year": 2026, "monthValue": 11, "dayOfMonth": 22, "hour": 18, "minute": 33, "second": 58, "nano": 0},
        "range": "low",
    }


def _search(pm25: str = "27.00") -> dict[str, Any]:
    return {
        "status": 0,
        "measurePoints": [_mp("mp1", "Living room", pm25)],
        "observedMPs": [_mp("mp2", "Neighbour")],
        "aggMeasures": [],
    }


class Responder:
    """Return queued JSON responses for one URL (last one repeats)."""

    def __init__(self, *responses: dict[str, Any]) -> None:
        self.responses = list(responses)
        self.bodies: list[dict[str, Any]] = []

    async def __call__(self, method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

        self.bodies.append(json.loads(data) if isinstance(data, (str, bytes)) else data)
        body = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return AiohttpClientMockResponse(method, url, json=body)


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        title="user@example.com",
        data={CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"},
        options={CONF_SCAN_INTERVAL: 30},
    )


async def test_user_flow(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """Credentials are validated and the interval stored."""
    login = Responder(LOGIN_BAD, LOGIN_OK)
    aioclient_mock.post(LOGIN_URL, side_effect=login)
    aioclient_mock.post(SEARCH_URL, json=_search())

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    # Below the 10 s minimum is rejected by the form itself.
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_EMAIL: "u@example.com", CONF_PASSWORD: "x", CONF_SCAN_INTERVAL: 5}
        )

    user_input = {CONF_EMAIL: "User@Example.com", CONF_PASSWORD: "bad", CONF_SCAN_INTERVAL: 10}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    user_input[CONF_PASSWORD] = "secret"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_EMAIL: "User@Example.com", CONF_PASSWORD: "secret"}
    assert result["options"] == {CONF_SCAN_INTERVAL: 10}
    assert result["result"].unique_id == "user@example.com"
    # Mimics the app's login body
    assert login.bodies[-1] == {
        "email": "User@Example.com", "password": "secret", "fcmToken": None, "locale": "en", "token": None,
    }


async def test_setup_creates_devices_and_sensors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Login, then userSearch builds devices and sensors."""
    search = Responder(_search())
    aioclient_mock.post(LOGIN_URL, json=LOGIN_OK)
    aioclient_mock.post(SEARCH_URL, side_effect=search)
    entry = _entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert search.bodies[0] == {"token": TOKEN}

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert {d.name for d in devices} == {"Living room", "Neighbour"}

    assert hass.states.get("sensor.living_room_pm2_5").state == "27.0"
    assert hass.states.get("sensor.living_room_temperature").state == "20.46"
    assert hass.states.get("sensor.living_room_atmospheric_pressure").state == "967.35"
    assert hass.states.get("sensor.living_room_voc").state == "106.0"
    assert hass.states.get("sensor.living_room_pollution_level").state == "108.0"
    assert hass.states.get("sensor.living_room_air_quality").state == "low"
    assert hass.states.get("sensor.living_room_last_update").state == "2026-11-22T18:33:58+00:00"
    assert hass.states.get("sensor.neighbour_pm10").state == "29.0"

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_poll_relogins_when_token_rejected(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A rejected token triggers one re-login and the poll still succeeds."""
    login = Responder(LOGIN_OK)
    aioclient_mock.post(LOGIN_URL, side_effect=login)
    aioclient_mock.post(SEARCH_URL, side_effect=Responder(_search(), SEARCH_REJECTED, _search("5")))
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert len(login.bodies) == 2
    assert hass.states.get("sensor.living_room_pm2_5").state == "5.0"


async def test_bad_credentials_start_reauth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Rejected credentials at startup put the entry in reauth."""
    aioclient_mock.post(LOGIN_URL, json=LOGIN_BAD)
    entry = _entry()
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_server_down_retries(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """HTTP errors make setup retry later."""
    aioclient_mock.post(LOGIN_URL, status=502)
    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.parametrize("interval", [10, 3600])
async def test_options_flow(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, interval: int) -> None:
    """The polling interval can be changed afterwards."""
    aioclient_mock.post(LOGIN_URL, json=LOGIN_OK)
    aioclient_mock.post(SEARCH_URL, json=_search())
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "settings"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_SCAN_INTERVAL: interval})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_SCAN_INTERVAL: interval}
    assert entry.runtime_data.update_interval.total_seconds() == interval


async def test_remove_device_hides_it_until_refresh(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, hass_ws_client
) -> None:
    """Deleting a device only hides it locally; 'Refresh device list' restores it."""
    from homeassistant.helpers import entity_registry as er
    from homeassistant.setup import async_setup_component

    from custom_components.ecolife.const import CONF_HIDDEN_DEVICES

    aioclient_mock.post(LOGIN_URL, json=LOGIN_OK)
    aioclient_mock.post(SEARCH_URL, json=_search())
    assert await async_setup_component(hass, "config", {})
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device_by_identifier((DOMAIN, "mp1"), entry.entry_id)
    assert device is not None

    # Same websocket command the "Delete" button on the device page sends.
    client = await hass_ws_client(hass)
    response = await client.remove_device(device.id)
    assert response["success"]
    await hass.async_block_till_done()
    assert entry.data[CONF_HIDDEN_DEVICES] == ["mp1"]
    assert dev_reg.async_get_device_by_identifier((DOMAIN, "mp1"), entry.entry_id) is None

    # Polling does not bring it back.
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert dev_reg.async_get_device_by_identifier((DOMAIN, "mp1"), entry.entry_id) is None
    assert hass.states.get("sensor.living_room_pm2_5") is None
    # A reload (e.g. HA restart) does not bring it back either.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert dev_reg.async_get_device_by_identifier((DOMAIN, "mp1"), entry.entry_id) is None
    assert dev_reg.async_get_device_by_identifier((DOMAIN, "mp2"), entry.entry_id) is not None

    # Nothing but login/userSearch was ever sent to the server.
    assert {str(url) for _, url, _, _ in aioclient_mock.mock_calls} == {LOGIN_URL, SEARCH_URL}

    # Hub options -> "Refresh device list".
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "refresh_devices"})
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {"count": "1"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "devices_refreshed"
    await hass.async_block_till_done()

    assert CONF_HIDDEN_DEVICES not in entry.data
    assert entry.state is ConfigEntryState.LOADED
    assert dev_reg.async_get_device_by_identifier((DOMAIN, "mp1"), entry.entry_id) is not None
    assert hass.states.get("sensor.living_room_pm2_5").state == "27.0"
    assert er.async_get(hass).async_get("sensor.living_room_pm2_5") is not None


async def test_images(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, hass_client
) -> None:
    """Device picture is served and used; brand icon is served for the integration."""
    from homeassistant.setup import async_setup_component

    aioclient_mock.post(LOGIN_URL, json=LOGIN_OK)
    aioclient_mock.post(SEARCH_URL, json=_search())
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "brands", {})
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.living_room_air_quality")
    assert state.attributes["entity_picture"] == "/ecolife_static/device.png"
    assert "entity_picture" not in hass.states.get("sensor.living_room_pm2_5").attributes

    client = await hass_client()
    resp = await client.get("/ecolife_static/device.png")
    assert resp.status == 200
    assert (await resp.read())[:8] == b"\x89PNG\r\n\x1a\n"

    resp = await client.get("/api/brands/integration/ecolife/icon.png")
    assert resp.status == 200
    assert (await resp.read())[:8] == b"\x89PNG\r\n\x1a\n"
    resp = await client.get("/api/brands/integration/ecolife/dark_logo@2x.png")  # falls back to icon
    assert resp.status == 200
