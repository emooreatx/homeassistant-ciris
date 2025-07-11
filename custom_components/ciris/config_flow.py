"""Config flow for CIRIS integration."""
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_API_KEY,
    CONF_API_URL,
    CONF_CHANNEL,
    CONF_TIMEOUT,
    DEFAULT_API_URL,
    DEFAULT_CHANNEL,
    DEFAULT_TIMEOUT,
    DOMAIN,
)

# Import the CIRIS SDK with HA wrapper
from .ciris_ha_client import CIRISClient
from .ciris_sdk.exceptions import CIRISError, CIRISTimeoutError

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for CIRIS."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Validate the API connection
            try:
                await self._test_connection(
                    user_input[CONF_API_URL],
                    user_input.get(CONF_API_KEY),
                    user_input.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
                )
            except CIRISTimeoutError:
                errors["base"] = "timeout"
            except CIRISError as e:
                if "401" in str(e) or "unauthorized" in str(e).lower():
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Create the entry
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, "CIRIS"),
                    data=user_input,
                )

        # Show the form
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_NAME, default="CIRIS"): str,
                    vol.Required(CONF_API_URL, default=DEFAULT_API_URL): str,
                    vol.Optional(CONF_API_KEY): str,
                    vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): vol.All(
                        vol.Coerce(int), vol.Range(min=5, max=300)
                    ),
                    vol.Optional(CONF_CHANNEL, default=DEFAULT_CHANNEL): str,
                }
            ),
            errors=errors,
        )

    async def _test_connection(
        self, api_url: str, api_key: str | None, timeout: int
    ) -> None:
        """Test the API connection."""
        # Use default credentials if no API key provided
        if not api_key:
            api_key = "admin:ciris_admin_password"
        
        client = CIRISClient(
            base_url=api_url,
            api_key=api_key,
            timeout=float(timeout),
            max_retries=0
        )
        
        try:
            async with client:
                # Handle username:password auth
                if client._transport.api_key and ':' in client._transport.api_key:
                    username, password = client._transport.api_key.split(':', 1)
                    _LOGGER.info(f"Testing connection with username: {username}")
                    
                    try:
                        token = await client.auth.login(username, password)
                        _LOGGER.info("Successfully authenticated with CIRIS")
                        # Don't persist the token in HA context
                        client._transport.set_api_key(token.access_token, persist=False)
                    except Exception as e:
                        _LOGGER.error(f"Failed to authenticate: {e}")
                        raise
                
                # Test connection
                status = await client.agent.get_status()
                _LOGGER.info(f"Connected to CIRIS: {status.name} (state: {status.cognitive_state})")
                
        except Exception as e:
            _LOGGER.error(f"Connection test failed: {e}")
            raise