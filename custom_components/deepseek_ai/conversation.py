"""Streaming conversation using HA's authenticated ChatLog and tool executor."""

from __future__ import annotations

from typing import Literal

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import intent, llm
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DeepSeekEntry
from .api import ApiError
from .const import DOMAIN
from .engine import run
from .entity import AgentEntity
from .privacy import private_request
from .web import WebAPI


async def async_setup_entry(
    hass: HomeAssistant, entry: DeepSeekEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    for subentry in entry.subentries.values():
        if subentry.subentry_type == "conversation":
            async_add_entities(
                [DeepSeekConversation(entry, subentry)], config_subentry_id=subentry.subentry_id
            )


class DeepSeekConversation(conversation.ConversationEntity, AgentEntity):
    _attr_supports_streaming = True
    _attr_supported_languages = "*"

    def __init__(self, entry: DeepSeekEntry, subentry: ConfigSubentry) -> None:
        AgentEntity.__init__(self, entry, subentry)
        if self.options["llm_hass_api"]:
            self._attr_supported_features = conversation.ConversationEntityFeature.CONTROL

    @property
    def supported_languages(self) -> Literal["*"]:
        return "*"

    @private_request
    async def _async_handle_message(
        self, user_input: conversation.ConversationInput, chat_log: conversation.ChatLog
    ) -> conversation.ConversationResult:
        runtime = self.entry.runtime_data
        selection = (
            WebAPI(self.hass, runtime.api, runtime.metrics)
            if self.options["web"]
            else self.options["llm_hass_api"]
        )
        try:
            if chat_log.llm_api and chat_log.llm_api.api.requires_admin:
                await llm.async_get_authorized_api_instance(
                    chat_log.llm_api.api, user_input.as_llm_context(DOMAIN)
                )
            await chat_log.async_provide_llm_data(
                user_input.as_llm_context(DOMAIN),
                selection,
                self.options["prompt"],
                user_input.extra_system_prompt,
            )
            await run(runtime, chat_log, self.entity_id, self.options)
        except conversation.ConverseError as err:
            return err.as_conversation_result()
        except (ApiError, TimeoutError, HomeAssistantError) as err:
            if isinstance(err, ApiError):
                runtime.handle_error(err)
            response = intent.IntentResponse(language=user_input.language)
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                str(err) if isinstance(err, ApiError) else "DeepSeek request failed or timed out",
            )
            return conversation.ConversationResult(
                response=response, conversation_id=chat_log.conversation_id
            )
        return conversation.async_get_result_from_chat_log(user_input, chat_log)
