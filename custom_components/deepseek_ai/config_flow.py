"""Native credentials and independently configurable functionality subentries."""

from typing import Any

import probatio as vol
from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.helpers import llm, selector
from homeassistant.helpers.httpx_client import get_async_client

from .api import ApiError, DeepSeekClient
from .const import DEFAULTS, DOMAIN, MODELS, NAME, SUBTYPES
from .settings import agent_settings


def credentials_schema():
    return vol.Schema({vol.Required(CONF_API_KEY): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)), vol.Optional("max_concurrent", default=2): vol.All(vol.Coerce(int), vol.Range(min=1, max=8))})


class DeepSeekFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _credentials(self, step, user_input):
        errors = {}
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            try:
                if not key:
                    raise ApiError("invalid_auth")
                await DeepSeekClient(get_async_client(self.hass), key).validate_key()
            except ApiError as err:
                errors["base"] = "invalid_auth" if err.status in (401, 403) or err.code == "invalid_auth" else "cannot_connect"
            else:
                data = {CONF_API_KEY: key, "max_concurrent": user_input.get("max_concurrent", 2)}
                if step == "user":
                    return self.async_create_entry(title=NAME, data=data, subentries=[{"subentry_type": kind, "title": f"{NAME} {kind.replace('_', ' ').title()}", "unique_id": None, "data": {}} for kind in ("conversation", "ai_task", "stt", "tts")])
                entry = self._get_reauth_entry() if step == "reauth_confirm" else self._get_reconfigure_entry()
                return self.async_update_reload_and_abort(entry, data_updates=data)
        return self.async_show_form(step_id=step, data_schema=credentials_schema(), errors=errors)

    async def async_step_user(self, user_input=None):
        return await self._credentials("user", user_input)

    async def async_step_reconfigure(self, user_input=None):
        return await self._credentials("reconfigure", user_input)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        return await self._credentials("reauth_confirm", user_input)

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry):
        return dict.fromkeys(SUBTYPES, AgentFlow)


class AgentFlow(config_entries.ConfigSubentryFlow):
    """The HA-selected subtype controls which capabilities appear in the form."""

    async def async_step_user(self, user_input=None):
        self.options = {}
        return await self.async_step_init(user_input)

    async def async_step_reconfigure(self, user_input=None):
        self.options = dict(self._get_reconfigure_subentry().data)
        return await self.async_step_init(user_input)

    async def async_step_init(self, user_input=None):
        kind = self._subentry_type
        errors = {}
        if user_input is not None:
            data = {**self.options, **user_input}
            name = data.pop("name", f"{NAME} {kind}").strip()
            try:
                agent_settings(kind, data)
                if kind == "evaluation" and data.get("acknowledge_experimental") is not True:
                    raise ValueError("experimental_required")
            except ValueError as err:
                errors["base"] = str(err)
            else:
                if self.source == "user":
                    return self.async_create_entry(title=name or NAME, data=data)
                return self.async_update_and_abort(self._get_entry(), self._get_reconfigure_subentry(), title=name or NAME, data=data)
        fields: dict[Any, Any] = {vol.Required("name", default=self._get_reconfigure_subentry().title if self.source == "reconfigure" else f"{NAME} {kind}"): str}
        options = {**DEFAULTS, **self.options}
        if kind in ("conversation", "ai_task", "evaluation"):
            fields[vol.Required("model", default=options["model"])] = selector.SelectSelector(selector.SelectSelectorConfig(options=MODELS))
            fields[vol.Required("thinking", default=options["thinking"])] = selector.SelectSelector(selector.SelectSelectorConfig(options=["none", "low", "high", "max"]))
            fields[vol.Required("prompt", default=options["prompt"])] = selector.TemplateSelector()
            fields[vol.Required("max_tokens", default=options["max_tokens"])] = vol.All(vol.Coerce(int), vol.Range(min=64, max=384000))
        if kind == "conversation":
            fields[vol.Optional("llm_hass_api", default=self.options.get("llm_hass_api", [llm.LLM_API_ASSIST]))] = selector.SelectSelector(selector.SelectSelectorConfig(options=[selector.SelectOptionDict(value=api.id, label=api.name) for api in llm.async_get_apis(self.hass)], multiple=True))
            fields[vol.Required("history_turns", default=options["history_turns"])] = vol.All(vol.Coerce(int), vol.Range(min=1, max=50))
        if kind in ("conversation", "ai_task"):
            fields[vol.Required("web", default=options["web"])] = bool
            fields[vol.Required("max_tool_rounds", default=options["max_tool_rounds"])] = vol.All(vol.Coerce(int), vol.Range(min=1, max=20))
        if kind == "evaluation":
            fields[vol.Required("acknowledge_experimental", default=self.options.get("acknowledge_experimental", False))] = bool
        if kind == "tts":
            fields[vol.Required("voice", default=options["voice"])] = selector.SelectSelector(selector.SelectSelectorConfig(options=["stella", "tide"]))
        fields[vol.Required("timeout", default=options["timeout"])] = vol.All(vol.Coerce(int), vol.Range(min=5, max=600))
        fields[vol.Required("total_timeout", default=options["total_timeout"])] = vol.All(vol.Coerce(int), vol.Range(min=30, max=900))
        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields), errors=errors)

