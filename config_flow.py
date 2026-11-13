"""配置流程：添加集成 + 选项（数据源、自定义日期、提醒）。"""
from __future__ import annotations

from datetime import time as dtime
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TimeSelector,
)

from . import core
from .const import (
    CONF_CUSTOM_REST,
    CONF_CUSTOM_WORK,
    CONF_HOLIDAY_LEAD,
    CONF_MONTH_END_AT,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_TIME,
    CONF_URL,
    DEFAULT_HOLIDAY_LEAD,
    DEFAULT_MONTH_END_AT,
    DEFAULT_NOTIFY_TIME,
    DEFAULT_URL,
    DOMAIN,
    NAME,
)


class CnWorkdayConfigFlow(ConfigFlow, domain=DOMAIN):
    """只允许一个实例。"""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title=NAME, data={})

        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return CnWorkdayOptionsFlow()


class CnWorkdayOptionsFlow(OptionsFlow):
    """数据源 + 自定义日期 + 提醒设置。"""

    def _coordinator(self):
        bucket = self.hass.data.get(DOMAIN) or {}
        return bucket.get(self.config_entry.entry_id)

    def _schema(self) -> vol.Schema:
        opts = self.config_entry.options
        coord = self._coordinator()
        work = ",".join(sorted(coord.custom_work)) if coord else ""
        rest = ",".join(sorted(coord.custom_rest)) if coord else ""

        raw_time = opts.get(CONF_NOTIFY_TIME) or DEFAULT_NOTIFY_TIME
        try:
            hour, minute = [int(x) for x in str(raw_time).split(":")[:2]]
            default_time = dtime(hour, minute)
        except (ValueError, IndexError):
            default_time = dtime(8, 0)

        return vol.Schema(
            {
                vol.Optional(CONF_URL, default=opts.get(CONF_URL) or DEFAULT_URL): str,
                vol.Optional(CONF_CUSTOM_WORK, default=work): TextSelector(
                    TextSelectorConfig(multiline=True)
                ),
                vol.Optional(CONF_CUSTOM_REST, default=rest): TextSelector(
                    TextSelectorConfig(multiline=True)
                ),
                vol.Optional(
                    CONF_NOTIFY_SERVICE, default=opts.get(CONF_NOTIFY_SERVICE) or ""
                ): str,
                vol.Optional(CONF_NOTIFY_TIME, default=default_time): TimeSelector(),
                vol.Optional(
                    CONF_HOLIDAY_LEAD,
                    default=opts.get(CONF_HOLIDAY_LEAD) or DEFAULT_HOLIDAY_LEAD,
                ): str,
                vol.Optional(
                    CONF_MONTH_END_AT,
                    default=opts.get(CONF_MONTH_END_AT) or DEFAULT_MONTH_END_AT,
                ): str,
            }
        )

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        coord = self._coordinator()

        if user_input is not None:
            try:
                work = core.normalize_dates(user_input.get(CONF_CUSTOM_WORK))
                rest = core.normalize_dates(user_input.get(CONF_CUSTOM_REST))
            except ValueError:
                return self.async_show_form(
                    step_id="init", data_schema=self._schema(), errors={"base": "invalid_dates"}
                )
            both = work & rest
            if both:
                return self.async_show_form(
                    step_id="init", data_schema=self._schema(), errors={"base": "date_conflict"}
                )

            if coord is not None:
                await coord.async_set_custom(work, rest)

            notify_time = user_input.get(CONF_NOTIFY_TIME)
            if isinstance(notify_time, dtime):
                user_input[CONF_NOTIFY_TIME] = notify_time.strftime("%H:%M:%S")

            cleaned = {
                k: v
                for k, v in user_input.items()
                if k not in (CONF_CUSTOM_WORK, CONF_CUSTOM_REST)
            }
            return self.async_create_entry(title="", data=cleaned)

        return self.async_show_form(step_id="init", data_schema=self._schema())
