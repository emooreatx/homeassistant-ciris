"""The CIRIS AI Assistant integration."""
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.components import conversation
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .agent import CIRISAgent

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CIRIS from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    # Create the conversation agent
    agent = CIRISAgent(hass, entry)
    
    # Store the agent and config data
    hass.data[DOMAIN][entry.entry_id] = {
        "agent": agent,
        "config": entry.data
    }
    
    # Register the conversation agent
    conversation.async_set_agent(hass, entry, agent)
    
    _LOGGER.info("CIRIS conversation agent registered successfully")
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unregister the conversation agent
    conversation.async_unset_agent(hass, entry)
    
    # Clean up the agent
    if entry.entry_id in hass.data[DOMAIN]:
        entry_data = hass.data[DOMAIN][entry.entry_id]
        if "agent" in entry_data:
            agent = entry_data["agent"]
            await agent.async_close()
    
    # Remove the data
    hass.data[DOMAIN].pop(entry.entry_id, None)
    
    _LOGGER.info("CIRIS conversation agent unloaded successfully")
    
    return True