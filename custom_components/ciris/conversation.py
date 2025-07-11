"""CIRIS conversation agent."""
import logging
from typing import Any, Literal

import httpx
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.util import ulid

from .const import (
    CONF_API_KEY,
    CONF_API_URL,
    CONF_CHANNEL,
    CONF_TIMEOUT,
    DEFAULT_TIMEOUT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: conversation.AddEntitiesCallback,
) -> None:
    """Set up CIRIS conversation platform."""
    agent = CIRISAgent(hass, config_entry)
    async_add_entities([agent])


class CIRISAgent(conversation.ConversationEntity):
    """CIRIS conversation agent."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the agent."""
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}-conversation"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "CIRIS AI Assistant",
            "manufacturer": "CIRIS AI",
            "model": "CIRIS Agent",
        }
        
        # API configuration
        self.api_url = entry.data[CONF_API_URL]
        self.api_key = entry.data.get(CONF_API_KEY)
        self.timeout = entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
        self.channel = entry.data.get(CONF_CHANNEL, "homeassistant")
        
        # HTTP client
        self._client = httpx.AsyncClient(
            base_url=self.api_url,
            timeout=httpx.Timeout(self.timeout),
            headers=self._get_headers(),
        )

    def _get_headers(self) -> dict[str, str]:
        """Get headers for API requests."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return supported languages."""
        return "*"  # Support all languages

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        """Process a sentence from the user."""
        intent_response = intent.IntentResponse(language=user_input.language)
        
        try:
            # Check if CIRIS is available
            status_response = await self._client.get("/v1/agent/status")
            if status_response.status_code != 200:
                intent_response.async_set_speech(
                    "I'm having trouble connecting to CIRIS. Please check the configuration."
                )
                return conversation.ConversationResult(
                    response=intent_response,
                    conversation_id=user_input.conversation_id or ulid.ulid(),
                )
            
            # Add context for CIRIS
            enhanced_message = (
                f"{user_input.text}\n\n"
                f"[This was received via Home Assistant conversation. "
                f"You can control devices if asked. Please SPEAK to respond, thank you!]"
            )
            
            # Send to CIRIS
            interact_response = await self._client.post(
                "/v1/agent/interact",
                json={
                    "message": enhanced_message,
                    "channel_id": f"{self.channel}_{user_input.conversation_id or 'default'}",
                },
            )
            
            if interact_response.status_code == 200:
                result = interact_response.json()
                response_text = result.get("content", "I didn't understand that.")
                
                # Check if CIRIS wants to control devices
                # This is a simple implementation - could be enhanced
                if "turn on" in response_text.lower() or "turn off" in response_text.lower():
                    # Parse intent from CIRIS response
                    # For now, just speak the response
                    pass
                
                intent_response.async_set_speech(response_text)
            else:
                intent_response.async_set_speech(
                    "I encountered an error processing your request."
                )
                
        except httpx.TimeoutException:
            intent_response.async_set_speech(
                "CIRIS is taking too long to respond. Please try again."
            )
        except Exception as e:
            _LOGGER.error("Error processing with CIRIS: %s", e)
            intent_response.async_set_speech(
                "I encountered an error. Please try again later."
            )
        
        return conversation.ConversationResult(
            response=intent_response,
            conversation_id=user_input.conversation_id or ulid.ulid(),
        )

    async def async_will_remove_from_hass(self) -> None:
        """Clean up on removal."""
        await self._client.aclose()