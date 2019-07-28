"""Provides functionality to interact with lights."""
import asyncio
import logging
import os.path
import yaml

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

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "DumbIR Media Player"

CONF_IRCODES = 'ir_codes'
CONF_POWER = 'power'
CONF_TOGGLE = 'toggle'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_IRCODES): cv.string
})


async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    """Set up the Dumb IR Media Player platform."""
    ir_codes_file = config.get(CONF_IRCODES)

    if ir_codes_file.startswith("/"):
        ir_codes_file = ir_codes_file[1:]

    ir_codes_path = hass.config.path(ir_codes_file)

    if not os.path.exists(ir_codes_path):
        _LOGGER.error("The ir code file was not found. (%s)", ir_codes_path)
        return

    with open(ir_codes_path, 'r') as f:
        ir_codes = yaml.load(f, Loader=yaml.SafeLoader)

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

    async def _send_command(self, payload):
        if type(payload) is not str:
            # get an element from the array
            for ite in pyaload:
                # send a command
                self._send_command(ite)

        service_data_json = {'host':  self._host, 'packet': payload}

        await self.hass.services.async_call('broadlink', 'send',
                                            service_data_json )

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
            await self._send_command(self._ir_codes[CONF_POWER][CONF_COMMAND_ON])

        if self._effect is not None:
            await self._send_command(self._ir_codes[ATTR_EFFECT][self._effect])

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the light off"""
        self._is_on = False
        await self._send_command(self._ir_codes[CONF_POWER][CONF_COMMAND_OFF])

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()

        if last_state is not None:
            self._is_on = last_state.state == STATE_ON
            if ATTR_EFFECT in last_state.attributes:
                self._effect = last_state.attributes[ATTR_EFFECT]
