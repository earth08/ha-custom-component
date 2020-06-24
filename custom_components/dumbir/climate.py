"""Provides functionality to interact with climate devices."""
import asyncio
from configparser import ConfigParser
import logging
import os.path
from typing import Any, Dict, List, Optional

import voluptuous as vol

from homeassistant.components.climate import ClimateEntity, PLATFORM_SCHEMA
from homeassistant.components.climate.const import (
    HVAC_MODE_AUTO,
    HVAC_MODE_COOL,
    HVAC_MODE_DRY,
    HVAC_MODE_HEAT,
    HVAC_MODE_OFF,
    ATTR_HVAC_MODE,
    ATTR_FAN_MODE,
    ATTR_FAN_MODES,
    ATTR_SWING_MODE,
    ATTR_SWING_MODES,
    SUPPORT_FAN_MODE,
    SUPPORT_SWING_MODE,
    SUPPORT_TARGET_TEMPERATURE
)

from homeassistant.const import (
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_COMMAND_OFF,
    CONF_CUSTOMIZE,
    CONF_NAME,
    CONF_HOST,
    CONF_MAC,
    CONF_TIMEOUT,
    PRECISION_HALVES,
    PRECISION_TENTHS,
    PRECISION_WHOLE,
    STATE_OFF,
    STATE_ON,
    TEMP_CELSIUS
)

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util.temperature import convert as convert_temperature

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

DEFAULT_SUPPORT_FLAGS = (
    SUPPORT_FAN_MODE |
    SUPPORT_TARGET_TEMPERATURE
)

ATTR_LAST_ON_STATE = 'last_on_state'

CONF_COMMAND_IDLE = 'command_idle'
CONF_FAN_MODES = 'fan_modes'
CONF_HUMIDITY_SENSOR = 'humidity_sensor'
CONF_MAX_TEMP = 'max_temp'
CONF_MIN_TEMP = 'min_temp'
CONF_OPERATIONS = 'operations'
CONF_PRECISION = 'precision'
CONF_SWING_MODES = 'swing_modes'
CONF_TEMPERATURE = 'temperature'
CONF_TEMPERATURE_SENSOR = 'temperature_sensor'

DEFAULT_NAME = 'DumbIR Climate'
DEFAULT_FAN_MODE_LIST = [HVAC_MODE_AUTO]
DEFAULT_MIN_TEMP = 16
DEFAULT_MAX_TEMP = 30
DEFAULT_OPERATION_LIST = [HVAC_MODE_AUTO]
DEFAULT_RETRY = 3
DEFAULT_PRECISION = PRECISION_WHOLE
DEFAULT_SWING_MODE_LIST = []


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_IRCODES): cv.string,
    vol.Optional(CONF_TEMPERATURE_SENSOR): cv.entity_id,
    vol.Optional(CONF_HUMIDITY_SENSOR): cv.entity_id,
    vol.Optional(CONF_POWER_SENSOR): cv.entity_id
    # To override 
    #vol.Optional(CONF_MIN_TEMP, default=DEFAULT_MIN_TEMP): vol.Coerce(float),
    #vol.Optional(CONF_MAX_TEMP, default=DEFAULT_MAX_TEMP): vol.Coerce(float),
    #vol.Optional(CONF_PRECISION, default=DEFAULT_PRECISION): vol.In(
    #    [PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE]),
    #vol.Optional(CONF_CUSTOMIZE, default={}): CUSTOMIZE_SCHEMA,
})


async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    """Set up the Dumb IR Climate platform."""
    climate_conf = load_ircodes(hass, config.get(CONF_IRCODES))

    if not climate_conf:
        return

    async_add_entities([DumbIRClimate(hass, config, climate_conf)])


class DumbIRClimate(ClimateEntity, RestoreEntity):
    def __init__(self, hass, config, climate_conf):

        """Initialize the Broadlink IR Climate device."""
        self.hass = hass

        self._name = config.get(CONF_NAME)
        self._host = config.get(CONF_HOST)

        temperature = climate_conf.get(CONF_TEMPERATURE)
        self._min_temp = temperature.get(CONF_MIN_TEMP)
        self._max_temp = temperature.get(CONF_MAX_TEMP)
        self._precision = temperature.get(CONF_PRECISION)

        self._current_state = {}
        self._current_state[ATTR_TEMPERATURE]= self._min_temp

        self._unit_of_measurement = hass.config.units.temperature_unit

        self._commands = climate_conf.get(CONF_COMMANDS)

        self._current_hvac_mode = HVAC_MODE_OFF

        self._last_state = {}

        self._fan_modes = climate_conf.get(CONF_FAN_MODES,
                                           DEFAULT_FAN_MODE_LIST)
        self._current_state[ATTR_FAN_MODE] = self._fan_modes[0]
        self._last_state[ATTR_FAN_MODE] = self._fan_modes[0]

        self._support_flags = DEFAULT_SUPPORT_FLAGS

        self._current_state[ATTR_SWING_MODE] = None
        self._last_state[ATTR_SWING_MODE] = None
        self._swing_modes = climate_conf.get(CONF_SWING_MODES, [])
        if self._swing_modes:
            self._current_state[ATTR_SWING_MODE] = self._swing_modes[0]
            self._last_state[ATTR_SWING_MODE] = self._swing_modes[0]
            self._support_flags = self._support_flags | SUPPORT_SWING_MODE

        self._hvac_modes = [HVAC_MODE_OFF]

        self._custom_modes = {}
        for an_op in climate_conf.get(CONF_OPERATIONS,
                                      DEFAULT_OPERATION_LIST):
            for op, op_conf in an_op.items():
                op = op.lower()
                self._hvac_modes.append(op)
                last_state = {ATTR_TEMPERATURE: self._min_temp,
                              ATTR_FAN_MODE: self._current_state[ATTR_FAN_MODE],
                              ATTR_SWING_MODE: self._current_state[ATTR_SWING_MODE]}
                if bool(op_conf):
                    if CONF_MIN_TEMP in op_conf:
                        last_state[ATTR_TEMPERATURE] = op_conf[CONF_MIN_TEMP]
                    if CONF_FAN_MODES in op_conf:
                        last_state[ATTR_FAN_MODE] = op_conf[CONF_FAN_MODES][0]
                    if CONF_SWING_MODES in op_conf:
                        last_state[ATTR_SWING_MODE] = op_conf[CONF_SWING_MODES][0]
                    self._custom_modes[op] = op_conf

            self._last_state[op] = last_state

        self._last_state[ATTR_HVAC_MODE] = self._hvac_modes[1]

        self._common_temp_conf = (self._min_temp, self._max_temp, self._precision)
        self._common_fan_conf = self._fan_modes
        self._common_swing_conf = self._swing_modes

        self._temp_lock = asyncio.Lock()

        # to suppress false error from Alexa component
        self._current_temperature = 21.0
        
        self._temperature_sensor = config.get(CONF_TEMPERATURE_SENSOR)
        self._humidity_sensor = config.get(CONF_HUMIDITY_SENSOR)
        self._power_sensor = config.get(CONF_POWER_SENSOR)

        self._current_humidity = None

    def _set_custom_mode(self, hvac_mode):
        if hvac_mode == HVAC_MODE_OFF:
            return

        (self._min_temp, self._max_temp, self._precision) = self._common_temp_conf
        self._fan_modes = self._common_fan_conf
        self._swing_modes = self._common_swing_conf

        if hvac_mode in self._custom_modes:
            custom_mode = self._custom_modes[hvac_mode]
            if CONF_MIN_TEMP in custom_mode:
                self._min_temp = custom_mode[CONF_MIN_TEMP]

            if CONF_MAX_TEMP in custom_mode:
                self._max_temp = custom_mode[CONF_MAX_TEMP]

            if CONF_FAN_MODES in custom_mode:
                self._fan_modes = custom_mode[CONF_FAN_MODES]

            if CONF_SWING_MODES in custom_mode:
                self._swing_modes = custom_mode[CONF_SWING_MODES]


    def _update_last_state(self, hvac_mode):
        last_state = {}
        last_state[ATTR_TEMPERATURE] = self._current_state[ATTR_TEMPERATURE]
        if hvac_mode in self._custom_modes:
            custom_mode = self._custom_modes[hvac_mode]
            if CONF_FAN_MODES in custom_mode:
                last_state[ATTR_FAN_MODE] = self._current_state[ATTR_FAN_MODE]
            else:
                self._last_state[ATTR_FAN_MODE] = self._current_state[ATTR_FAN_MODE]

            if CONF_SWING_MODES in custom_mode:
                last_state[ATTR_SWING_MODE] = self._current_state[ATTR_SWING_MODE]
            else:
                self._last_state[ATTR_SWING_MODE] = self._current_state[ATTR_SWING_MODE]

        self._last_state.update({hvac_mode: last_state})

    def _restore_last_state(self, hvac_mode):
        last_state = self._last_state[hvac_mode]
        self._current_state[ATTR_TEMPERATURE] = last_state[ATTR_TEMPERATURE]

        if ATTR_FAN_MODE in last_state:
            self._current_state[ATTR_FAN_MODE] = last_state[ATTR_FAN_MODE]
        else:
            self._current_state[ATTR_FAN_MODE] = self._last_state.get(ATTR_FAN_MODE, None)

        if ATTR_SWING_MODE in last_state:
            self._current_state[ATTR_SWING_MODE] = last_state[ATTR_SWING_MODE] 
        else:
            self._current_state[ATTR_SWING_MODE] = self._last_state.get(ATTR_SWING_MODE, None)

    def _get_payload(self, hvac_mode, fan_mode, target_temperature, swing_mode):
        if self.hvac_mode == HVAC_MODE_OFF:
            return self._commands[CONF_POWER][CONF_COMMAND_OFF]

        payload = self._commands[hvac_mode][fan_mode]
        
        if swing_mode:
            payload = payload[swing_mode]

        return payload[target_temperature]

    async def _send_ir(self):
        async with self._temp_lock:
            payload = self._get_payload(self._current_hvac_mode,
                                        self._current_state[ATTR_FAN_MODE],
                                        self._current_state[ATTR_TEMPERATURE],
                                        self._current_state[ATTR_SWING_MODE])

            await send_command(self.hass, self._host, payload)

    async def _async_temp_sensor_changed(self, entity_id, old_state, new_state):
        """Handle temperature changes."""
        if new_state is None:
            return

        self._update_current_temp(new_state)
        await self.async_update_ha_state()

    async def _async_humidity_sensor_changed(self, entity_id, old_state, new_state):
        """Handle humidity sensor changes."""
        if new_state is None:
            return

        self._update_humidity(new_state)
        await self.async_update_ha_state()

    async def _async_power_sensor_changed(self, entity_id, old_state, new_state):
        """Handle power sensor changes."""
        if new_state is None:
            return

        if new_state.state == STATE_ON and self._hvac_mode == HVAC_MODE_OFF:
            self._on_by_remote = True
            await self.async_update_ha_state()

        if new_state.state == HVAC_MODE_OFF:
            self._on_by_remote = False
            if self._hvac_mode != HVAC_MODE_OFF:
                self._hvac_mode = HVAC_MODE_OFF
            await self.async_update_ha_state()

    @callback
    def _update_current_temp(self, state):
        """Update thermostat with latest state from sensor."""
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)

        try:
            _state = state.state
            if self.represents_float(_state):
                self._current_temperature = self.hass.config.units.temperature(
                    float(_state), unit)
        except ValueError as ex:
            _LOGGER.error('Unable to update from sensor: %s', ex)

    @callback
    def _update_temp(self, state):
        """Update thermostat with latest state from temperature sensor."""
        try:
            if state.state != STATE_UNKNOWN:
                self._current_temperature = float(state.state)
        except ValueError as ex:
            _LOGGER.error("Unable to update from temperature sensor: %s", ex)

    @callback
    def _update_humidity(self, state):
        """Update thermostat with latest state from humidity sensor."""
        try:
            if state.state != STATE_UNKNOWN:
                self._current_humidity = float(state.state)
        except ValueError as ex:
            _LOGGER.error("Unable to update from humidity sensor: %s", ex)

    def represents_float(self, s):
        try:
            float(s)
            return True
        except ValueError:
            return False

    @property
    def name(self):
        """Return the name of the climate device."""
        return self._name

    @property
    def precision(self) -> float:
        return self._precision

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def state_attributes(self) -> Dict[str, Any]:
        """Platform specific attributes."""
        data = super().state_attributes
        data[ATTR_LAST_ON_STATE] = self._last_state
        return data

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def current_humidity(self) -> Optional[int]:
        """Return the current humidity."""
        return None

    @property
    def target_humidity(self) -> Optional[int]:
        """Return the humidity we try to reach."""
        return None

    @property
    def hvac_mode(self) -> str:
        """Return current operation ie. heat, cool."""
        return self._current_hvac_mode

    @property
    def hvac_modes(self) -> List[str]:
        """Return the list of available operation modes."""
        return self._hvac_modes

    '''
    @property
    def hvac_action(self) -> Optional[str]:
        """Return the current running hvac operation if supported.

        Need to be one of CURRENT_HVAC_*.
        """
        return self._current_hvac_mode
    '''

    @property
    def current_temperature(self) -> Optional[float]:
        """Return the current temperature."""
        return self._current_temperature

    @property
    def target_temperature(self) -> Optional[float]:
        """Return the temperature we try to reach."""
        return self._current_state[ATTR_TEMPERATURE]

    @property
    def target_temperature_step(self) -> Optional[float]:
        """Return the supported step of target temperature."""
        return self._precision

    '''
    @property
    def target_temperature_high(self) -> Optional[float]:
        """Return the highbound target temperature we try to reach.

        Requires SUPPORT_TARGET_TEMPERATURE_RANGE.
        """
        # TODO
        pass

    @property
    def target_temperature_low(self) -> Optional[float]:
        """Return the lowbound target temperature we try to reach.

        Requires SUPPORT_TARGET_TEMPERATURE_RANGE.
        """
        # TODO
        pass

    @property
    def preset_mode(self) -> Optional[str]:
        """Return the current preset mode, e.g., home, away, temp.

        Requires SUPPORT_PRESET_MODE.
        """
        # TODO
        pass

    @property
    def preset_modes(self) -> Optional[List[str]]:
        """Return a list of available preset modes.

        Requires SUPPORT_PRESET_MODE.
        """
        # TODO
        pass

    @property
    def is_aux_heat(self) -> Optional[bool]:
        """Return true if aux heater.

        Requires SUPPORT_AUX_HEAT.
        """
        # TODO
        pass
    '''

    @property
    def fan_mode(self) -> Optional[str]:
        """Return the fan setting.

        Requires SUPPORT_FAN_MODE.
        """
        return self._current_state[ATTR_FAN_MODE]

    @property
    def fan_modes(self) -> Optional[List[str]]:
        """Return the list of available fan modes.

        Requires SUPPORT_FAN_MODE.
        """
        return self._fan_modes

    @property
    def swing_mode(self) -> Optional[str]:
        """Return the swing setting.

        Requires SUPPORT_SWING_MODE.
        """
        return self._current_state[ATTR_SWING_MODE]

    @property
    def swing_modes(self) -> Optional[List[str]]:
        """Return the list of available swing modes.

        Requires SUPPORT_SWING_MODE.
        """
        return self._swing_modes

    '''
    def set_temperature(self, **kwargs) -> None:
        """Set new target temperature."""
        # TODO
        pass
    '''

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)

        if temperature is None:
            return

        if temperature < self._min_temp or temperature > self._max_temp:
            _LOGGER.warning('The temperature value is out of min/max range')
            return

        self._target_temperature = round(temperature) if self._precision == PRECISION_WHOLE else round(temperature, 1)

        if self._current_hvac_mode != HVAC_MODE_OFF:
            self._current_state[ATTR_TEMPERATURE] = self._target_temperature
            await self._send_ir()

        await self.async_update_ha_state()
        # await self.hass.async_add_executor_job(
        #     ft.partial(self.set_temperature, **kwargs))

    '''
    def set_humidity(self, humidity: int) -> None:
        """Set new target humidity."""
        # TODO
        pass

    async def async_set_humidity(self, humidity: int) -> None:
        """Set new target humidity."""
        await self.hass.async_add_executor_job(self.set_humidity, humidity)
    '''

    '''
    def set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        pass
    '''

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        self._current_state[ATTR_FAN_MODE] = fan_mode

        if self._current_hvac_mode != HVAC_MODE_OFF:
            await self._send_ir()

        await self.async_update_ha_state()
        # await self.hass.async_add_executor_job(self.set_fan_mode, fan_mode)

    '''
    def set_hvac_mode(self, hvac_mode: str) -> None:
        """Set new target hvac mode."""
        pass
    '''

    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        """Set new target hvac mode."""
        if hvac_mode == self._current_hvac_mode:
            return

        self._update_last_state(self._current_hvac_mode)

        if hvac_mode == HVAC_MODE_OFF:
            self._last_state[ATTR_HVAC_MODE] = self._current_hvac_mode
        else:
            self._set_custom_mode(hvac_mode)
            self._restore_last_state(hvac_mode)

        #
        # safe guard during migration
        #
        if self._current_state[ATTR_TEMPERATURE] < self._min_temp or \
            self._current_state[ATTR_TEMPERATURE] > self._max_temp:
            self._current_state[ATTR_TEMPERATURE] = self._min_temp

        if self._current_state[ATTR_FAN_MODE] not in self._fan_modes:
            self._current_state[ATTR_FAN_MODE] = self._fan_modes[0]

        if self._swing_modes:
           if self._current_state[ATTR_SWING_MODE] not in self._swing_modes:
               self._current_state[ATTR_SWING_MODE] = self._swing_modes[0]
        ######

        self._current_hvac_mode = hvac_mode

        await self._send_ir()
        await self.async_update_ha_state()
        # await self.hass.async_add_executor_job(self.set_hvac_mode, hvac_mode)

    '''
    def set_swing_mode(self, swing_mode: str) -> None:
        """Set new target swing mode."""
        pass
    '''

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set new target swing operation."""
        self._current_state[ATTR_SWING_MODE] = swing_mode

        if self._current_hvac_mode != HVAC_MODE_OFF:
            await self._send_ir()

        await self.async_update_ha_state()
        # await self.hass.async_add_executor_job(self.set_swing_mode, swing_mode)

    '''
    def set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        # TODO
        pass

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        await self.hass.async_add_executor_job(
            self.set_preset_mode, preset_mode)

    def turn_aux_heat_on(self) -> None:
        """Turn auxiliary heater on."""
        # TODO
        pass

    async def async_turn_aux_heat_on(self) -> None:
        """Turn auxiliary heater on."""
        await self.hass.async_add_executor_job(self.turn_aux_heat_on)

    def turn_aux_heat_off(self) -> None:
        """Turn auxiliary heater off."""
        # TODO
        pass

    async def async_turn_aux_heat_off(self) -> None:
        """Turn auxiliary heater off."""
        await self.hass.async_add_executor_job(self.turn_aux_heat_off)
    '''

    async def async_turn_on(self) -> None:
        """Turn the entity on."""
        if ATTR_HVAC_MODE in self._last_state:
            await self.async_set_hvac_mode(self._last_state[ATTR_HVAC_MODE])
        else:
            await self.async_set_hvac_mode(self._hvac_modes[1])

    '''
    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        if hasattr(self, 'turn_off'):
            # pylint: disable=no-member
            await self.hass.async_add_executor_job(self.turn_off)
            return

        # Fake turn off
        if HVAC_MODE_OFF in self._hvac_modes:
            await self.async_set_hvac_mode(HVAC_MODE_OFF)
        # await self.async_set_hvac_mode(HVAC_MODE_OFF)
    '''

    @property
    def supported_features(self) -> int:
        """Return the list of supported features."""
        return self._support_flags

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        return convert_temperature(self._min_temp, TEMP_CELSIUS,
                                   self.temperature_unit)

    @property
    def max_temp(self) -> float:
        """Return the polling state."""
        return convert_temperature(self._max_temp, TEMP_CELSIUS,
                                   self.temperature_unit)

    '''
    @property
    def min_humidity(self) -> int:
        """Return the minimum humidity."""
        return DEFAULT_MIN_HUMIDITY

    @property
    def max_humidity(self) -> int:
        """Return the maximum humidity."""
        return DEFAULT_MAX_HUMIDITY
    '''

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()

        if last_state is not None:
            self._current_hvac_mode = last_state.state
            self._set_custom_mode(last_state.state)

            self._current_state[ATTR_TEMPERATURE] = last_state.attributes[ATTR_TEMPERATURE]
            self._current_state[ATTR_FAN_MODE] = last_state.attributes[ATTR_FAN_MODE]
            if ATTR_SWING_MODE in last_state.attributes:
                self._current_state[ATTR_SWING_MODE] = last_state.attributes[ATTR_SWING_MODE]

            if ATTR_LAST_ON_STATE in last_state.attributes:
                self._last_state = last_state.attributes[ATTR_LAST_ON_STATE]

        if self._temperature_sensor:
            async_track_state_change(self.hass, self._temperature_sensor, 
                                     self._async_temp_sensor_changed)

            temp_sensor_state = self.hass.states.get(self._temperature_sensor)
            if temp_sensor_state and temp_sensor_state.state != STATE_UNKNOWN:
                self._async_update_temp(temp_sensor_state)

        if self._humidity_sensor:
            async_track_state_change(self.hass, self._humidity_sensor, 
                                     self._async_humidity_sensor_changed)

            humidity_sensor_state = self.hass.states.get(self._humidity_sensor)
            if humidity_sensor_state and humidity_sensor_state.state != STATE_UNKNOWN:
                self._async_update_humidity(humidity_sensor_state)

        if self._power_sensor:
            async_track_state_change(self.hass, self._power_sensor, 
                                     self._async_power_sensor_changed)
