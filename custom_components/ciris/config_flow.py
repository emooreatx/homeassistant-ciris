"""Config flow for CIRIS integration."""
import logging
from typing import Any

import httpx
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
            except httpx.ConnectError:
                errors["base"] = "cannot_connect"
            except httpx.TimeoutException:
                errors["base"] = "timeout"
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
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key

        async with httpx.AsyncClient(
            base_url=api_url,
            timeout=httpx.Timeout(timeout),
            headers=headers,
        ) as client:
            response = await client.get("/v1/agent/status")
            response.raise_for_status()