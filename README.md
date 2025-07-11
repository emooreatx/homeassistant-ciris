# CIRIS Home Assistant Integration

This integration allows CIRIS to act as a conversation agent in Home Assistant, handling voice commands and conversations.

## Installation

1. Copy the `custom_components/ciris` folder to your Home Assistant `custom_components` directory
2. Restart Home Assistant
3. Go to Settings → Devices & Services → Add Integration
4. Search for "CIRIS"
5. Enter your CIRIS API URL (e.g., `http://192.168.50.8:8080`)
6. Optionally add an API key if your CIRIS instance requires authentication

## Configuration

After installation:

1. Go to Settings → Voice assistants
2. Create a new assistant or edit an existing one
3. Set the "Conversation agent" to "CIRIS"
4. Configure your STT and TTS as desired

## Features

- Full conversation support through CIRIS
- Maintains conversation context
- Can be extended to control Home Assistant devices
- Works with any STT/TTS combination

## Wyoming Bridge

For the best experience, use this integration with the CIRIS Wyoming Bridge addon for STT.