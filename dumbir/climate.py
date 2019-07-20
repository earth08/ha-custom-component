import asyncio
from configparser import ConfigParser
import logging
import os.path

import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant.components.climate import ClimateDevice, PLATFORM_SCHEMA
from homeassistant.components.climate.const import (
    HVAC_MODE_AUTO, HVAC_MODE_COOL, HVAC_MODE_DRY,
    HVAC_MODE_HEAT, HVAC_MODE_OFF,
    ATTR_HVAC_MODE, ATTR_FAN_MODE,
    ATTR_SWING_MODE,
    SUPPORT_TARGET_TEMPERATURE,
    SUPPORT_FAN_MODE,
    SUPPORT_SWING_MODE)
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT, ATTR_TEMPERATURE,
    CONF_NAME, CONF_HOST, CONF_MAC, CONF_TIMEOUT,
    CONF_CUSTOMIZE, PRECISION_HALVES,
    PRECISION_TENTHS, PRECISION_WHOLE,
    STATE_OFF, STATE_ON)

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change
from homeassistant.helpers.restore_state import RestoreEntity

_LOGGER = logging.getLogger(__name__)

DEFAULT_SUPPORT_FLAGS = (
    SUPPORT_FAN_MODE |
    SUPPORT_TARGET_TEMPERATURE)

CONF_IRCODES_INI = 'ircodes_ini'
CONF_MIN_TEMP = 'min_temp'
CONF_MAX_TEMP = 'max_temp'
CONF_TARGET_TEMP = 'target_temp'
CONF_PRECISION = 'precision'
CONF_TEMP_SENSOR = 'temp_sensor'
CONF_OPERATIONS = 'operations'
CONF_FAN_MODES = 'fan_modes'
CONF_SWING_MODES = 'swing_modes'
CONF_CURRENT_FAN_MODE = 'current_fan_mode'
CONF_CURRENT_SWING_MODE = 'current_swing_mode'

DEFAULT_NAME = 'Broadlink IR Climate'
DEFAULT_RETRY = 3
DEFAULT_MIN_TEMP = 16
DEFAULT_MAX_TEMP = 30
DEFAULT_PRECISION = PRECISION_WHOLE
DEFAULT_OPERATION_LIST = [HVAC_MODE_AUTO]
DEFAULT_FAN_MODE_LIST = [HVAC_MODE_AUTO]
DEFAULT_SWING_MODE_LIST = []

CUSTOMIZE_SCHEMA = vol.Schema({
    vol.Optional(CONF_OPERATIONS): vol.All(cv.ensure_list, [dict]),
    vol.Optional(CONF_FAN_MODES): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_SWING_MODES): vol.All(cv.ensure_list, [cv.string])
})


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_IRCODES_INI): cv.string,
    vol.Optional(CONF_MIN_TEMP, default=DEFAULT_MIN_TEMP): vol.Coerce(float),
    vol.Optional(CONF_MAX_TEMP, default=DEFAULT_MAX_TEMP): vol.Coerce(float),
    vol.Optional(CONF_PRECISION, default=DEFAULT_PRECISION): vol.In(
        [PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE]),
    vol.Optional(CONF_TEMP_SENSOR): cv.entity_id,
    vol.Optional(CONF_CUSTOMIZE, default={}): CUSTOMIZE_SCHEMA
})


async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    """Set up the Broadlink IR Climate platform."""
    ircodes_ini_file = config.get(CONF_IRCODES_INI)

    if ircodes_ini_file.startswith("/"):
        ircodes_ini_file = ircodes_ini_file[1:]

    ircodes_ini_path = hass.config.path(ircodes_ini_file)

    if not os.path.exists(ircodes_ini_path):
        _LOGGER.error("The ini file was not found. (%s)", ircodes_ini_path)
        return

    ircodes_ini = ConfigParser()
    ircodes_ini.read(ircodes_ini_path)

    async_add_entities([BroadlinkIRClimate(hass, config, ircodes_ini)])


class BroadlinkIRClimate(ClimateDevice, RestoreEntity):
    # Implement one of these methods.
    def __init__(self, hass, config, ircodes_ini):

        """Initialize the Broadlink IR Climate device."""
        self.hass = hass

        self._name = config.get(CONF_NAME)
        self._host = config.get(CONF_HOST)

        self._min_temp = config.get(CONF_MIN_TEMP)
        self._max_temp = config.get(CONF_MAX_TEMP)
        self._unit_of_measurement = hass.config.units.temperature_unit
        self._precision = config.get(CONF_PRECISION)
        self._target_temperature = self._min_temp

        self._commands_ini = ircodes_ini
        self._current_operation = STATE_OFF
        self._last_on_operation = None
        self._current_temperature = self._target_temperature

        self._fan_list = config.get(CONF_CUSTOMIZE).get(
            CONF_FAN_MODES, DEFAULT_FAN_MODE_LIST)
        self._current_fan_mode = self._fan_list[0]

        self._support_flags = DEFAULT_SUPPORT_FLAGS

        self._current_swing_mode = None
        self._swing_list = config.get(CONF_CUSTOMIZE).get(CONF_SWING_MODES, [])
        if self._swing_list:
            self._current_swing_mode = self._swing_list[0]
            self._support_flags = self._support_flags | SUPPORT_SWING_MODE

        self._operation_list = [STATE_OFF]
        self._custom_operations = {}
        for an_op in config.get(CONF_CUSTOMIZE).get(CONF_OPERATIONS,
                                                    DEFAULT_OPERATION_LIST):
            for op, op_conf in an_op.items():
                op = op.lower()
                self._operation_list.append(op)
                if not bool(op_conf):
                    continue
                if CONF_MIN_TEMP in op_conf:
                    op_conf[CONF_TARGET_TEMP] = op_conf[CONF_MIN_TEMP]
                if CONF_FAN_MODES in op_conf:
                    op_conf[CONF_CURRENT_FAN_MODE] = op_conf[CONF_FAN_MODES][0]
                if CONF_SWING_MODES in op_conf:
                    op_conf[CONF_CURRENT_SWING_MODE] = op_conf[CONF_SWING_MODES][0]
           
                self._custom_operations[op] = op_conf

        self._common_temp_conf = (self._min_temp, self._max_temp,
                                  self._precision, self._target_temperature)
        self._common_fan_conf = (self._fan_list, self._current_fan_mode)
        self._common_swing_conf = (self._swing_list, self._current_swing_mode)

        self._temp_lock = asyncio.Lock()

        self._temp_sensor_entity_id = config.get(CONF_TEMP_SENSOR)

        if self._temp_sensor_entity_id:
            async_track_state_change(
                hass, temp_sensor_entity_id,
                self._async_temp_sensor_changed)

            sensor_state = hass.states.get(temp_sensor_entity_id)

            if sensor_state:
                self._async_update_current_temp(sensor_state)

    def _get_command_value(self, section):
        swing_mode = ''
        if self._swing_list:
            swing_mode = '_' + self._current_swing_mode.lower()
            swing_mode = swing_mode.replace(' ', '')
        temp = '_' + str(int(self._target_temperature)
                         if self.target_temperature ==
                         int(self.target_temperature)
                         else self._target_temperature).replace('.', '_')
        value = self._current_fan_mode.lower()
        value = value.replace(' ', '') + swing_mode + temp

        if value in self._commands_ini[section]:
            return value

        if self._swing_list:
            # definitely incorrect configuration
            _LOGGER.warning("Please check your ini file for command "
                            "'%s' in section '%s'", value, section)
            return value

        value = self._current_fan_mode.lower()
        return value.replace(' ', '') + temp

    def _set_custom_operation(self, operation_mode):
        if self._current_operation in self._custom_operations:
            custom_operation = self._custom_operations[self._current_operation]
            if CONF_TARGET_TEMP in custom_operation:
                custom_operation[CONF_TARGET_TEMP] = self._target_temperature

            if CONF_FAN_MODES in custom_operation:
                custom_operation[CONF_CURRENT_FAN_MODE] = self._current_fan_mode

            if CONF_SWING_MODES in custom_operation:
                custom_operation[CONF_CURRENT_SWING_MODE] = self._current_swing_mode
        elif self._current_operation != 'off':
            self._common_temp_conf = self._common_temp_conf[:3] + (self._target_temperature,)
            self._common_fan_conf = self._common_fan_conf[:1] + (self._current_fan_mode,)
            self._common_swing_conf = self._common_swing_conf[:1] + (self._current_swing_mode,)
            
        if operation_mode in self._custom_operations:
            custom_operation = self._custom_operations[operation_mode]
            if CONF_MIN_TEMP in custom_operation:
                self._min_temp = custom_operation[CONF_MIN_TEMP]

            if CONF_MAX_TEMP in custom_operation:
                self._max_temp = custom_operation[CONF_MAX_TEMP]

            if CONF_TARGET_TEMP in custom_operation:
                self._target_temperature = custom_operation[CONF_TARGET_TEMP]

            if CONF_PRECISION in custom_operation:
                self._precision = custom_operation[CONF_PRECISION]

            if CONF_FAN_MODES in custom_operation:
                self._fan_list = custom_operation[CONF_FAN_MODES]
                self._current_fan_mode = custom_operation[CONF_CURRENT_FAN_MODE]

            if CONF_SWING_MODES in custom_operation:
                self._swing_list = custom_operation[CONF_SWING_MODES]
                self._current_swing_mode = custom_operation[CONF_CURRENT_SWING_MODE]
        elif operation_mode != 'off':
            (self._min_temp, self._max_temp, self._precision,
             self._target_temperature) = self._common_temp_conf
            (self._fan_list, self._current_fan_mode) = self._common_fan_conf
            (self._swing_list, self._current_swing_mode) = self._common_swing_conf

    async def send_ir(self):
        async with self._temp_lock:
            section = self._current_operation.lower()

            value = 'off_command' if section == 'off' else self._get_command_value(section)
            payload = self._commands_ini.get(section, value)

            _LOGGER.debug("Sending command [%s %s] to %s", section, value,
                          self._name)
            service_data_json = {'host':  self._host, 'packet': payload}
            # _LOGGER.debug("json: %s", service_data_json)

            await self.hass.services.async_call('broadlink', 'send',
                                                service_data_json )

    async def _async_temp_sensor_changed(self, entity_id, old_state, new_state):
        """Handle temperature changes."""
        if new_state is None:
            return

        self._async_update_current_temp(new_state)
        await self.async_update_ha_state()

    @callback
    def _async_update_current_temp(self, state):
        """Update thermostat with latest state from sensor."""
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)

        try:
            _state = state.state
            if self.represents_float(_state):
                self._current_temperature = self.hass.config.units.temperature(
                    float(_state), unit)
        except ValueError as ex:
            _LOGGER.error('Unable to update from sensor: %s', ex)

    def represents_float(self, s):
        try:
            float(s)
            return True
        except ValueError:
            return False

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def name(self):
        """Return the name of the climate device."""
        return self._name

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._current_temperature

    @property
    def min_temp(self):
        """Return the polling state."""
        return self._min_temp

    @property
    def max_temp(self):
        """Return the polling state."""
        return self._max_temp

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temperature

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return self._precision

    @property
    def precision(self):
        return self._precision

    @property
    def hvac_mode(self):
        """Return current operation ie. heat, cool."""
        return self._current_operation

    @property
    def last_on_operation(self):
        """Return the last non-idle operation ie. heat, cool."""
        return self._last_on_operation

    @property
    def hvac_modes(self):
        """Return the list of available operation modes."""
        return self._operation_list

    @property
    def fan_mode(self):
        """Return the fan setting."""
        return self._current_fan_mode

    @property
    def fan_modes(self):
        """Return the list of available fan modes."""
        return self._fan_list

    @property
    def swing_mode(self):
        """Return the swing setting."""
        return self._current_swing_mode

    @property
    def swing_modes(self):
        """List of available swing modes."""
        return self._swing_list

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags

    @property
    def device_state_attributes(self) -> dict:
        """Platform specific attributes"""
        data = super().state_attributes
        data['last_on_operation'] = self._last_on_operation
        return data

    async def async_set_temperature(self, **kwargs):
        """Set new target temperatures."""
        temperature = kwargs.get(ATTR_TEMPERATURE)

        if temperature is None:
            return

        if temperature < self._min_temp or temperature > self._max_temp:
            _LOGGER.warning('The temperature value is out of min/max range')
            return

        self._target_temperature = round(temperature) if self._precision == PRECISION_WHOLE else round(temperature, 1)

        if not (self._current_operation.lower() == 'off'):
            await self.send_ir()

        await self.async_update_ha_state()

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target temperature."""
        self._set_custom_operation(hvac_mode)
        if not hvac_mode == HVAC_MODE_OFF:
            self._last_on_operation = hvac_mode

        self._current_operation = hvac_mode

        await self.send_ir()
        await self.async_update_ha_state()

    async def async_set_fan_mode(self, fan_mode):
        """Set new target fan mode."""
        self._current_fan_mode = fan_mode

        if not (self._current_operation.lower() == 'off'):
            await self.send_ir()

        await self.async_update_ha_state()

    async def async_set_swing_mode(self, swing_mode):
        """Set new target swing mode."""
        self._current_swing_mode = swing_mode

        if not (self._current_operation.lower() == 'off'):
            await self.send_ir()

        await self.async_update_ha_state()

    async def async_turn_off(self):
        """Turn thermostat off."""
        await self.async_set_operation_mode(STATE_OFF)

    async def async_turn_on(self):
        """Turn thermostat off."""
        if self._last_on_operation is not None:
            await self.async_set_operation_mode(self._last_on_operation)
        else:
            await self.async_set_operation_mode(self._operation_list[1])

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()

        if last_state is not None:
            _LOGGER.debug(last_state)
            self._target_temperature = last_state.attributes['temperature']
            #self._current_operation = last_state.attributes['operation_mode']
            self._current_fan_mode = last_state.attributes[ATTR_FAN_MODE]
            self._current_swing_mode = last_state.attributes[ATTR_SWING_MODE]

            if 'last_on_operation' in last_state.attributes:
                self._last_on_operation = last_state.attributes['last_on_operation']
