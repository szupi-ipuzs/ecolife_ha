"""Config flow for EcoLife."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import EcolifeApi, EcolifeAuthError, EcolifeConnectionError
from .const import (
    CONF_HIDDEN_DEVICES,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

EMAIL_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
)
PASSWORD_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
)
INTERVAL_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=MIN_SCAN_INTERVAL,
        max=MAX_SCAN_INTERVAL,
        step=1,
        mode=NumberSelectorMode.BOX,
        unit_of_measurement="s",
    )
)


def _interval_schema(default: int) -> vol.Schema:
    return vol.Schema({vol.Required(CONF_SCAN_INTERVAL, default=default): INTERVAL_SELECTOR})


async def _validate_login(hass: HomeAssistant, email: str, password: str) -> dict[str, str]:
    """Try to log in; return a form ``errors`` dict (empty on success)."""
    api = EcolifeApi(async_get_clientsession(hass), email, password)
    try:
        await api.async_login()
    except EcolifeAuthError:
        return {"base": "invalid_auth"}
    except EcolifeConnectionError:
        return {"base": "cannot_connect"}
    except Exception:  # noqa: BLE001
        LOGGER.exception("Unexpected error while logging in to EcoLife")
        return {"base": "unknown"}
    return {}


def _clamp_interval(value: Any) -> int:
    return max(MIN_SCAN_INTERVAL, min(MAX_SCAN_INTERVAL, int(value)))


class EcolifeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EcoLife."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for EcoLife credentials and the polling interval."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()
            errors = await _validate_login(self.hass, email, user_input[CONF_PASSWORD])
            if not errors:
                return self.async_create_entry(
                    title=email,
                    data={CONF_EMAIL: email, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                    options={
                        CONF_SCAN_INTERVAL: _clamp_interval(user_input[CONF_SCAN_INTERVAL])
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL): EMAIL_SELECTOR,
                vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
                vol.Required(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): INTERVAL_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication when the stored password stops working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _validate_login(
                self.hass, entry.data[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR}),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the password of an existing hub."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _validate_login(
                self.hass, entry.data[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR}),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> EcolifeOptionsFlow:
        """Return the options flow."""
        return EcolifeOptionsFlow()


class EcolifeOptionsFlow(OptionsFlowWithReload):
    """Hub options: polling interval and refreshing the device list."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init", menu_options=["settings", "refresh_devices"]
        )

    async def async_step_refresh_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Un-hide devices removed from HA and re-read the list from the cloud."""
        entry = self.config_entry
        hidden = entry.data.get(CONF_HIDDEN_DEVICES, [])
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                entry,
                data={k: v for k, v in entry.data.items() if k != CONF_HIDDEN_DEVICES},
            )
            self.hass.config_entries.async_schedule_reload(entry.entry_id)
            return self.async_abort(
                reason="devices_refreshed",
                description_placeholders={"count": str(len(hidden))},
            )
        return self.async_show_form(
            step_id="refresh_devices",
            data_schema=vol.Schema({}),
            description_placeholders={"count": str(len(hidden))},
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the polling interval (the hub reloads automatically)."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: _clamp_interval(user_input[CONF_SCAN_INTERVAL])}
            )
        current = int(
            self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        return self.async_show_form(
            step_id="settings", data_schema=_interval_schema(current)
        )
