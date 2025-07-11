"""CIRIS conversation agent."""
import logging
from typing import Any, Literal

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

# Import the CIRIS SDK with HA wrapper
from .ciris_ha_client import CIRISClient
from .ciris_sdk.exceptions import CIRISError, CIRISTimeoutError

_LOGGER = logging.getLogger(__name__)


class CIRISAgent(conversation.AbstractConversationAgent):
    """CIRIS conversation agent."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the agent."""
        self.hass = hass
        self.entry = entry
        
        # API configuration
        self.api_url = entry.data[CONF_API_URL]
        self.api_key = entry.data.get(CONF_API_KEY)
        self.timeout = entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
        self.channel = entry.data.get(CONF_CHANNEL, "homeassistant")
        
        # Initialize CIRIS SDK client
        self._client = None
        self._client_initialized = False

    async def _ensure_client(self) -> CIRISClient:
        """Ensure the CIRIS client is initialized."""
        if self._client is None:
            # Use default credentials if no API key provided
            api_key = self.api_key
            if not api_key:
                api_key = "admin:ciris_admin_password"
            
            _LOGGER.info(f"Creating CIRIS client for URL: {self.api_url}")
            self._client = CIRISClient(
                base_url=self.api_url,
                api_key=api_key,
                timeout=float(self.timeout),
                max_retries=0  # No retries for conversation
            )
            
        if not self._client_initialized:
            await self._client.__aenter__()
            
            # Handle username:password auth
            if self._client._transport.api_key and ':' in self._client._transport.api_key:
                username, password = self._client._transport.api_key.split(':', 1)
                _LOGGER.info(f"Using username/password auth for user: {username}")
                
                try:
                    token = await self._client.auth.login(username, password)
                    _LOGGER.info("Successfully logged in to CIRIS")
                    # Don't persist the token in HA context
                    self._client._transport.set_api_key(token.access_token, persist=False)
                except Exception as e:
                    _LOGGER.error(f"Failed to login to CIRIS: {e}")
                    raise
            
            self._client_initialized = True
            
        return self._client

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return supported languages."""
        return "*"  # Support all languages

    @property
    def attribution(self) -> str | None:
        """Return attribution information."""
        return "Powered by CIRIS AI"

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        """Process a sentence from the user."""
        _LOGGER.info(f"CIRIS: Processing input: '{user_input.text}'")
        intent_response = intent.IntentResponse(language=user_input.language)
        
        try:
            client = await self._ensure_client()
            
            # Check if CIRIS is available
            try:
                status = await client.agent.get_status()
                _LOGGER.info(f"CIRIS status check successful: {status.name} (state: {status.cognitive_state})")
            except Exception as e:
                _LOGGER.error(f"Failed to get CIRIS status: {e}")
                intent_response.async_set_speech(
                    "I'm having trouble connecting to CIRIS. Please check the configuration."
                )
                return conversation.ConversationResult(
                    response=intent_response,
                    conversation_id=user_input.conversation_id or ulid.ulid(),
                )
            
            # Build context for CIRIS
            context = {
                "source": "homeassistant",
                "channel_id": f"{self.channel}_{user_input.conversation_id or 'default'}",
                "input_method": "voice" if user_input.conversation_id else "text",
                "language": user_input.language,
                "hass_context": {
                    "user_id": user_input.context.user_id if user_input.context else None,
                    "parent_id": user_input.context.parent_id if user_input.context else None,
                },
                "instructions": (
                    "You are integrated with Home Assistant. "
                    "You can control devices if asked. "
                    "Please SPEAK to respond, thank you!"
                ),
            }
            
            # Send to CIRIS using the SDK
            try:
                _LOGGER.info(f"CIRIS: Sending message to API with context: {context}")
                response = await client.agent.interact(
                    message=user_input.text,
                    context=context
                )
                
                response_text = response.response
                _LOGGER.info(f"CIRIS responded in {response.processing_time_ms}ms with: '{response_text}'")
                
                # Check if CIRIS wants to control devices
                # This is a simple implementation - could be enhanced
                if "turn on" in response_text.lower() or "turn off" in response_text.lower():
                    # Parse intent from CIRIS response
                    # For now, just speak the response
                    pass
                
                intent_response.async_set_speech(response_text)
                
            except CIRISTimeoutError:
                _LOGGER.warning("CIRIS timeout")
                intent_response.async_set_speech(
                    "CIRIS is taking too long to respond. Please try again."
                )
            except CIRISError as e:
                _LOGGER.error(f"CIRIS error: {e}")
                intent_response.async_set_speech(
                    "I encountered an error processing your request."
                )
                
        except Exception as e:
            _LOGGER.error(f"Error processing with CIRIS: {e}", exc_info=True)
            intent_response.async_set_speech(
                "I encountered an error. Please try again later."
            )
        
        return conversation.ConversationResult(
            response=intent_response,
            conversation_id=user_input.conversation_id or ulid.ulid(),
        )

    async def async_close(self) -> None:
        """Close the agent."""
        if self._client and self._client_initialized:
            try:
                await self._client.__aexit__(None, None, None)
                self._client = None
                self._client_initialized = False
            except Exception as e:
                _LOGGER.error(f"Error closing CIRIS client: {e}")