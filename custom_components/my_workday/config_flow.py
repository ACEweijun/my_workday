"""配置流程：单实例，选项里控制联动与提醒。"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_HOLIDAY_URL, CONF_NOTIFY_SERVICE, CONF_SOON_DAYS,
    CONF_SYNC_DUE_TO_TODOS, DEFAULT_HOLIDAY_URL, DEFAULT_SOON_DAYS, DOMAIN, NAME,
)


class MyWorkdayConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title=NAME, data={})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return MyWorkdayOptionsFlow()


class MyWorkdayOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = self.hass.config_entries.async_get_entry(self.handler)
        options = current.options if current else {}
        schema = vol.Schema({
            vol.Optional(CONF_SYNC_DUE_TO_TODOS,
                         default=options.get(CONF_SYNC_DUE_TO_TODOS, False)): cv.boolean,
            vol.Optional(CONF_SOON_DAYS,
                         default=options.get(CONF_SOON_DAYS, DEFAULT_SOON_DAYS)): vol.Coerce(int),
            vol.Optional(CONF_HOLIDAY_URL,
                         default=options.get(CONF_HOLIDAY_URL, DEFAULT_HOLIDAY_URL)): cv.string,
            vol.Optional(CONF_NOTIFY_SERVICE,
                         default=options.get(CONF_NOTIFY_SERVICE, "")): cv.string,
        })
        return self.async_show_form(step_id="init", data_schema=schema)
