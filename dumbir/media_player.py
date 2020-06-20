import asyncio
import logging
import os.path
import yaml

import voluptuous as vol

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    PLATFORM_SCHEMA
)

from homeassistant.components.media_player.const import (
    SUPPORT_TURN_OFF,
    SUPPORT_TURN_ON,
    SUPPORT_PREVIOUS_TRACK,
    SUPPORT_NEXT_TRACK,
    SUPPORT_PLAY,
    SUPPORT_PAUSE,
    SUPPORT_STOP,
    SUPPORT_VOLUME_STEP,
    SUPPORT_VOLUME_SET, SUPPORT_VOLUME_MUTE,
    # SUPPORT_SELECT_CHANNEL,
    SUPPORT_SELECT_SOURCE,
    MEDIA_TYPE_CHANNEL
)

from homeassistant.const import (
    CONF_COMMAND_OFF,
    CONF_COMMAND_ON,
    CONF_NAME,
    CONF_HOST,
    STATE_OFF,
    STATE_ON,
    STATE_UNKNOWN,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_PLAYING
)

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.restore_state import RestoreEntity

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "DumbIR Media Player"

CONF_CHANNELS = 'channels'
CONF_DOWN = 'down'
CONF_IRCODES = 'ir_codes'
CONF_MEDIA = 'media'
CONF_MUTE = 'mute'
CONF_NEXT = 'next'
CONF_PAUSE = 'pause'
CONF_PLAY = 'play'
CONF_POWER = 'power'
CONF_POWER_SENSOR = 'power_sensor'
CONF_PREVIOUS = 'previous'
CONF_SOURCES = 'sources'
CONF_STOP = 'stop'
CONF_TOGGLE = 'toggle'
CONF_UP = 'up'
CONF_VOLUME = 'volume'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_IRCODES): cv.string,
    vol.Optional(CONF_POWER_SENSOR): cv.entity_id
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

    async_add_entities([DumbIRMediaPlayer( hass, config, ir_codes)])


class DumbIRMediaPlayer(MediaPlayerEntity, RestoreEntity):
    def __init__(self, hass, config, ir_codes):

        """Initialize the Broadlink IR Media device."""
        self.hass = hass

        self._name = config.get(CONF_NAME)
        self._host = config.get(CONF_HOST)
        self._power_sensor = config.get(CONF_POWER_SENSOR)
        self._ir_codes = ir_codes

        self._state = STATE_IDLE
        self._source_list = []
        self._channel_list = []
        self._source = None
        self._support_flags = 0
        self._is_volume_muted = False
        self._is_power_toggle = False

        #Supported features
        if CONF_POWER in self._ir_codes:
            power = self._ir_codes[CONF_POWER]
            if CONF_TOGGLE in power and power[CONF_TOGGLE] is not None:
                self._is_power_toggle = True
                self._support_flags = self._support_flags | SUPPORT_TURN_OFF 
                self._support_flags = self._support_flags | SUPPORT_TURN_ON
                power = {CONF_COMMAND_ON : power[CONF_TOGGLE],
                         CONF_COMMAND_OFF : power[CONF_TOGGLE]}
                self._ir_codes.update({CONF_POWER: power})
            else:
                if CONF_COMMAND_OFF in power and power[CONF_COMMAND_OFF] is not None:
                    self._support_flags = self._support_flags | SUPPORT_TURN_OFF

                if CONF_COMMAND_ON in power and power[CONF_COMMAND_ON] is not None:
                    self._support_flags = self._support_flags | SUPPORT_TURN_ON

        if CONF_VOLUME in self._ir_codes:
            volume = self._ir_codes[CONF_VOLUME]
            if (CONF_DOWN in volume and volume[CONF_DOWN] is not None) \
                or (CONF_UP in volume and volume[CONF_UP] is not None):
                self._support_flags = self._support_flags | SUPPORT_VOLUME_STEP

            if CONF_MUTE in volume and volume[CONF_MUTE] is not None:
                self._support_flags = self._support_flags | SUPPORT_VOLUME_MUTE

        if CONF_MEDIA in self._ir_codes:
            media = self._ir_codes[CONF_MEDIA]
            if CONF_PREVIOUS in media and media[CONF_PREVIOUS] is not None:
                self._support_flags = self._support_flags | SUPPORT_PREVIOUS_TRACK

            if CONF_NEXT in media and media[CONF_NEXT] is not None:
                self._support_flags = self._support_flags | SUPPORT_NEXT_TRACK

            if CONF_PLAY in media and media[CONF_PLAY] is not None:
                self._support_flags = self._support_flags | SUPPORT_PLAY

            if CONF_PAUSE in media and media[CONF_PAUSE] is not None:
                self._support_flags = self._support_flags | SUPPORT_PAUSE

            if CONF_STOP in media and media[CONF_STOP] is not None:
                self._support_flags = self._support_flags | SUPPORT_STOP

        if CONF_SOURCES in self._ir_codes and self._ir_codes[CONF_SOURCES] is not None:
            self._support_flags = self._support_flags | SUPPORT_SELECT_SOURCE

            # Source list
            for key in self._ir_codes[CONF_SOURCES]:
                self._source_list.append(key)
        '''
        if CONF_CHANNELS in self._ir_codes and self._ir_codes[CONF_CHANNELS] is not None:
            self._support_flags = self._support_flags | SUPPORT_SELECT_CHANNEL

            # Channel list
            for key in self._ir_codes[CONF_CHANNELS]:
                self._channel_list.append(key)
        '''

    async def _send_command(self, payload):
        if type(payload) is not str:
            # get an element from the array
            for ite in payload:
                # send a command
                self._send_command(ite)

        service_data_json = {'host':  self._host, 'packet': payload}
        _LOGGER.debug("json: %s", service_data_json)

        await self.hass.services.async_call('broadlink', 'send',
                                            service_data_json )
            
    '''
    @property
    def should_poll(self):
        """Push an update after each command."""
        return True

    @property
    def unique_id(self):
        """Return a unique ID."""
        return self._unique_id
    '''

    @property
    def name(self):
        """Return the name of the media player."""
        return self._name

    @property
    def state(self):
        """Return the state of the player."""
        return self._state


    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        return .5

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        return self._is_volume_muted

    @property
    def media_content_id(self):
        """Return the title of current playing media."""
        # mandatory property
        return None

    @property
    def media_content_type(self):
        """Content type of current playing media."""
        # mandatory property
        return MEDIA_TYPE_CHANNEL

    @property
    def channel_list(self):
        return self._channel_list
        
    @property
    def channel(self):
        return self._channel

    @property
    def source_list(self):
        return self._source_list
        
    @property
    def source(self):
        return self._source

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        return self._support_flags

    async def async_turn_off(self):
        """Turn the media player off."""
        await self._send_command(self._ir_codes[CONF_POWER][CONF_COMMAND_OFF])
        
        self._state = STATE_OFF
        await self.async_update_ha_state()

    async def async_turn_on(self):
        """Turn the media player off."""
        await self._send_command(self._ir_codes[CONF_POWER][CONF_COMMAND_ON])

        self._state = STATE_ON
        await self.async_update_ha_state()

    async def async_media_play(self):
        """Send play command.
        This method must be run in the event loop and returns a coroutine.
        """
        await self._send_command(self._ir_codes[CONF_MEDIA][CONF_PLAY])
        self._state = STATE_PLAYING
        await self.async_update_ha_state()

    async def async_media_pause(self):
        """Send pause command.
        This method must be run in the event loop and returns a coroutine.
        """
        await self._send_command(self._ir_codes[CONF_MEDIA][CONF_PAUSE])
        self._state = STATE_PAUSED
        await self.async_update_ha_state()

    async def async_media_stop(self):
        """Send stop command.
        This method must be run in the event loop and returns a coroutine.
        """
        await self._send_command(self._ir_codes[CONF_MEDIA][CONF_STOP])
        self._state = STATE_IDLE
        await self.async_update_ha_state()

    async def async_media_previous_track(self):
        """Send previous track command."""
        await self._send_command(self._ir_codes[CONF_MEDIA][CONF_PREVIOUS])
        await self.async_update_ha_state()

    async def async_media_next_track(self):
        """Send next track command."""
        await self._send_command(self._ir_codes[CONF_MEDIA][CONF_NEXT])
        await self.async_update_ha_state()

    async def async_volume_down(self):
        """Turn volume down for media player."""
        await self._send_command(self._ir_codes[CONF_VOLUME][CONF_DOWN])
        await self.async_update_ha_state()

    async def async_volume_up(self):
        """Turn volume up for media player."""
        await self._send_command(self._ir_codes[CONF_VOLUME][CONF_UP])
        await self.async_update_ha_state()
    
    async def async_mute_volume(self, mute):
        """Mute the volume."""
        self._is_volume_muted = not self._is_volume_muted

        await self._send_command(self._ir_codes[CONF_VOLUME][CONF_MUTE])
        await self.async_update_ha_state()

    async def async_select_source(self, source):
        """Select channel from source."""
        self._source = source
        await self._send_command(self._ir_codes[CONF_SOURCES][source])
        await self.async_update_ha_state()

    async def async_power_sensor_changed(self, entity_id, old_state, new_state):
        """update power state"""
        if new_state is None:
            return

        if new_state.state == STATE_ON and self._state == STATE_OFF:
            self._state = STATE_ON
            await self.async_update_ha_state()

        if new_state.state == STATE_OFF:
            self._state = STATE_OFF
            await self.async_update_ha_state()

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        if self._power_sensor:
            async_track_state_change(self.hass, self._power_sensor,
                                     self.async_power_sensor_changed)

        last_state = await self.async_get_last_state()
        _LOGGER.debug(last_state)

        if last_state is not None:
            self._state = last_state.state
