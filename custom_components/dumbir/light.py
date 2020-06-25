"""Provides functionality to interact with lights."""
import asyncio
import logging
import os.path

import voluptuous as vol

from homeassistant.components.light import (
    ATTR_EFFECT,
    SUPPORT_EFFECT,
    LightEntity,
    PLATFORM_SCHEMA
)

from homeassistant.const import (
    CONF_COMMAND_OFF,
    CONF_COMMAND_ON,
    CONF_HOST,
    CONF_NAME,
    STATE_ON
)

import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.restore_state import RestoreEntity

from . import (
    load_ircodes,
    send_command
)

from .const import (
    CONF_COMMANDS,
    CONF_IRCODES,
    CONF_POWER,
    CONF_POWER_SENSOR,
    CONF_TOGGLE
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "DumbIR Light"

CONF_CHANNEL = 'channel'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_IRCODES): cv.string,
    vol.Optional(CONF_CHANNEL, default=0): cv.positive_int
})


async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    """Set up the Dumb IR Media Player platform."""
    ir_codes = load_ircodes(hass, config.get(CONF_IRCODES))

    if not ir_codes:
        return

    async_add_entities([DumbIRLight( hass, config, ir_codes)])


class DumbIRLight(LightEntity, RestoreEntity):
    def __init__(self, hass, config, ir_codes):
        """Initialize the Broadlink IR Media device."""
        self.hass = hass

        self._name = config.get(CONF_NAME)
        self._host = config.get(CONF_HOST)
        self._ir_codes = ir_codes

        self._is_on = False
        self._support_flags = 0

        channel = config.get(CONF_CHANNEL)
        if isinstance(self._ir_codes, list):
            if channel < len(ir_codes):
                self._ir_codes = ir_codes[channel]
            else:
                self._ir_codes = ir_codes[0]
            
        #Supported features
        if CONF_POWER in self._ir_codes:
            power = self._ir_codes[CONF_POWER]
            if CONF_TOGGLE in power and power[CONF_TOGGLE] is not None:
                power = {CONF_COMMAND_ON : power[CONF_TOGGLE],
                         CONF_COMMAND_OFF : power[CONF_TOGGLE]}
                self._ir_codes.update({CONF_POWER: power})

        self._effect_list = None
        self._effect = None
        if ATTR_EFFECT in self._ir_codes:
            self._support_flags = self._support_flags | SUPPORT_EFFECT
            self._effect_list = list(self._ir_codes[ATTR_EFFECT].keys())
            self._effect = self._effect_list[0]

    @property
    def name(self) -> str:
        """Return the name of the media player."""
        return self._name

    @property
    def effect_list(self) -> list:
        """Return the list of supported effects."""
        return self._effect_list

    @property
    def effect(self) -> str:
        """Return the current effect."""
        return self._effect

    @property
    def is_on(self) -> bool:
        """Return the current effect."""
        return self._is_on

    @property
    def supported_features(self) -> int:
        """Flag supported features."""
        return self._support_flags

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the light on"""
        self._is_on = True

        if ATTR_EFFECT in kwargs:
            self._effect = kwargs[ATTR_EFFECT]

        if CONF_COMMAND_ON in self._ir_codes[CONF_POWER]:
            await send_command(self.hass, self._host,
                               self._ir_codes[CONF_POWER][CONF_COMMAND_ON])

        if self._effect is not None:
            await send_command(self.hass, self._host,
                               self._ir_codes[ATTR_EFFECT][self._effect])

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the light off"""
        self._is_on = False
        await send_command(self.hass, self._host,
                           self._ir_codes[CONF_POWER][CONF_COMMAND_OFF])

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()

        if last_state is not None:
            self._is_on = last_state.state == STATE_ON
            if ATTR_EFFECT in last_state.attributes:
                self._effect = last_state.attributes[ATTR_EFFECT]
