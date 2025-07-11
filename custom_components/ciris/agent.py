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
            
            # Get available devices for context
            device_info = await self._get_device_info()
            
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
                "available_devices": device_info,
                "instructions": (
                    "You are integrated with Home Assistant. "
                    "You can control devices by mentioning their names in your response. "
                    "For example: 'I'll turn on the kitchen light for you' or "
                    "'Let me switch off the bedroom fan'. "
                    "The system will automatically execute these commands. "
                    "Please SPEAK naturally and include the action in your response."
                ),
            }
            
            # Send to CIRIS using the SDK
            try:
                # Add context to the message like Wyoming bridge does
                enhanced_message = (
                    f"{user_input.text}\n\n"
                    f"[This was received via API from Home Assistant, "
                    f"please SPEAK to service this authorized request, thank you!]"
                )
                
                _LOGGER.info(f"CIRIS: Sending message to API with context: {context}")
                response = await client.agent.interact(
                    message=enhanced_message,
                    context=context
                )
                
                response_text = response.response
                _LOGGER.info(f"CIRIS responded in {response.processing_time_ms}ms with: '{response_text}'")
                
                # Check if CIRIS wants to control devices
                device_controlled = await self._process_device_control(response_text, user_input)
                
                # Set the speech response
                intent_response.async_set_speech(response_text)
                
                # If we controlled a device, add a card to show what happened
                if device_controlled:
                    intent_response.async_set_card(
                        "CIRIS Device Control",
                        response_text
                    )
                
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

    async def _get_device_info(self) -> dict:
        """Get information about available devices."""
        device_info = {
            "lights": [],
            "switches": [],
            "fans": [],
            "covers": [],
            "climate": []
        }
        
        try:
            # Get all states at once
            states = self.hass.states.async_all()
            
            for state in states:
                entity_id = state.entity_id
                domain = entity_id.split(".")[0]
                
                if domain == "light":
                    device_info["lights"].append({
                        "entity_id": entity_id,
                        "name": state.attributes.get("friendly_name", entity_id),
                        "state": state.state
                    })
                elif domain == "switch":
                    device_info["switches"].append({
                        "entity_id": entity_id,
                        "name": state.attributes.get("friendly_name", entity_id),
                        "state": state.state
                    })
                elif domain == "fan":
                    device_info["fans"].append({
                        "entity_id": entity_id,
                        "name": state.attributes.get("friendly_name", entity_id),
                        "state": state.state
                    })
                elif domain == "cover":
                    device_info["covers"].append({
                        "entity_id": entity_id,
                        "name": state.attributes.get("friendly_name", entity_id),
                        "state": state.state
                    })
                    
            _LOGGER.debug(f"Found devices: {len(device_info['lights'])} lights, "
                         f"{len(device_info['switches'])} switches, "
                         f"{len(device_info['fans'])} fans, "
                         f"{len(device_info['covers'])} covers")
                         
        except Exception as e:
            _LOGGER.error(f"Error getting device info: {e}")
            
        return device_info

    async def _process_device_control(
        self, 
        response_text: str, 
        user_input: conversation.ConversationInput
    ) -> bool:
        """Process device control commands from CIRIS response."""
        import re
        
        controlled_any = False
        
        # Simple pattern matching for common commands
        # Turn on/off pattern: "turn on the kitchen light" or "turning off bedroom fan"
        turn_pattern = r'(turn(?:ing)?|switch(?:ing)?)\s+(on|off)\s+(?:the\s+)?(.+?)(?:\.|,|$)'
        matches = re.finditer(turn_pattern, response_text.lower(), re.IGNORECASE)
        
        for match in matches:
            action = match.group(2)  # "on" or "off"
            target = match.group(3).strip()  # "kitchen light"
            
            _LOGGER.info(f"Detected device control: {action} {target}")
            
            # Find matching entities
            entity_id = await self._find_entity(target)
            if entity_id:
                try:
                    if action == "on":
                        await self.hass.services.async_call(
                            entity_id.split(".")[0],  # domain (light, switch, etc)
                            "turn_on",
                            {"entity_id": entity_id},
                            context=user_input.context
                        )
                        controlled_any = True
                    elif action == "off":
                        await self.hass.services.async_call(
                            entity_id.split(".")[0],
                            "turn_off",
                            {"entity_id": entity_id},
                            context=user_input.context
                        )
                        controlled_any = True
                except Exception as e:
                    _LOGGER.error(f"Error controlling device {entity_id}: {e}")
        
        # Toggle pattern: "toggle the garage door"
        toggle_pattern = r'toggle\s+(?:the\s+)?(.+?)(?:\.|,|$)'
        toggle_matches = re.finditer(toggle_pattern, response_text.lower(), re.IGNORECASE)
        
        for match in toggle_matches:
            target = match.group(1).strip()
            _LOGGER.info(f"Detected toggle: {target}")
            
            entity_id = await self._find_entity(target)
            if entity_id:
                try:
                    await self.hass.services.async_call(
                        entity_id.split(".")[0],
                        "toggle",
                        {"entity_id": entity_id},
                        context=user_input.context
                    )
                    controlled_any = True
                except Exception as e:
                    _LOGGER.error(f"Error toggling device {entity_id}: {e}")
                    
        return controlled_any

    async def _find_entity(self, name: str) -> str | None:
        """Find entity ID by friendly name."""
        name_lower = name.lower()
        
        # Get all states
        states = self.hass.states.async_all()
        
        # Check all entities
        for state in states:
            entity_id = state.entity_id
            domain = entity_id.split(".")[0]
            
            # Only check controllable domains
            if domain in ["light", "switch", "fan", "cover", "climate"]:
                friendly_name = state.attributes.get("friendly_name", "").lower()
                
                # Check if the name matches or is contained in the friendly name
                if name_lower == friendly_name or name_lower in friendly_name:
                    _LOGGER.info(f"Found entity {entity_id} for '{name}'")
                    return entity_id
                
                # Also check entity_id itself (without domain)
                entity_name = entity_id.split(".")[1].replace("_", " ")
                if name_lower == entity_name or name_lower in entity_name:
                    _LOGGER.info(f"Found entity {entity_id} for '{name}'")
                    return entity_id
        
        _LOGGER.warning(f"Could not find entity for '{name}'")
        return None

    async def async_close(self) -> None:
        """Close the agent."""
        if self._client and self._client_initialized:
            try:
                await self._client.__aexit__(None, None, None)
                self._client = None
                self._client_initialized = False
            except Exception as e:
                _LOGGER.error(f"Error closing CIRIS client: {e}")