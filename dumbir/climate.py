import asyncio
from configparser import ConfigParser
import logging
import os.path
from typing import Any, Dict, List, Optional

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
    STATE_OFF, STATE_ON, TEMP_CELSIUS)

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import (
    ConfigType, HomeAssistantType, ServiceDataType)
from homeassistant.util.temperature import convert as convert_temperature

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

DEFAULT_NAME = 'DumbIR Climate'
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
    vol.Optional(CONF_CUSTOMIZE, default={}): CUSTOMIZE_SCHEMA,
    vol.Optional(CONF_TEMPERATURE_SENSOR): cv.entity_id,
    vol.Optional(CONF_HUMIDITY_SENSOR): cv.entity_id,
    vol.Optional(CONF_POWER_SENSOR): cv.entity_id
})


async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    """Set up the Dumb IR Climate platform."""
    ircodes_ini_file = config.get(CONF_IRCODES_INI)

    if ircodes_ini_file.startswith("/"):
        ircodes_ini_file = ircodes_ini_file[1:]

    ircodes_ini_path = hass.config.path(ircodes_ini_file)

    if not os.path.exists(ircodes_ini_path):
        _LOGGER.error("The ini file was not found. (%s)", ircodes_ini_path)
        return

    ircodes_ini = ConfigParser()
    ircodes_ini.read(ircodes_ini_path)

    async_add_entities([DumbIRClimate(hass, config, ircodes_ini)])


class DumbIRClimate(ClimateDevice, RestoreEntity):
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
        self._current_mode = HVAC_MODE_OFF
        self._last_on_mode = None
        self._last_temp_per_mode = {}

        self._fan_modes = config.get(CONF_CUSTOMIZE).get(
            CONF_FAN_MODES, DEFAULT_FAN_MODE_LIST)
        self._current_fan_mode = self._fan_modes[0]

        self._support_flags = DEFAULT_SUPPORT_FLAGS

        self._current_swing_mode = None
        self._swing_modes = config.get(CONF_CUSTOMIZE).get(CONF_SWING_MODES, [])
        if self._swing_modes:
            self._current_swing_mode = self._swing_modes[0]
            self._support_flags = self._support_flags | SUPPORT_SWING_MODE

        self._hvac_modes = [HVAC_MODE_OFF]
        self._custom_modes = {}
        for an_op in config.get(CONF_CUSTOMIZE).get(CONF_OPERATIONS,
                                                    DEFAULT_OPERATION_LIST):
            for op, op_conf in an_op.items():
                op = op.lower()
                self._hvac_modes.append(op)
                if not bool(op_conf):
                    continue
                if CONF_MIN_TEMP in op_conf:
                    op_conf[CONF_TARGET_TEMP] = op_conf[CONF_MIN_TEMP]
                if CONF_FAN_MODES in op_conf:
                    op_conf[CONF_CURRENT_FAN_MODE] = op_conf[CONF_FAN_MODES][0]
                if CONF_SWING_MODES in op_conf:
                    op_conf[CONF_CURRENT_SWING_MODE] = op_conf[CONF_SWING_MODES][0]

                self._custom_modes[op] = op_conf

        self._common_temp_conf = (self._min_temp, self._max_temp,
                                  self._precision, self._target_temperature)
        self._common_fan_conf = (self._fan_modes, self._current_fan_mode)
        self._common_swing_conf = (self._swing_modes, self._current_swing_mode)

        self._temp_lock = asyncio.Lock()
        # to suppress false error from Alexa component
        self._current_temperature = 21.0
        '''
        self._temp_sensor_entity_id = config.get(CONF_TEMP_SENSOR)
        
        self._temperature_sensor = config.get(CONF_TEMPERATURE_SENSOR)
        self._humidity_sensor = config.get(CONF_HUMIDITY_SENSOR)
        self._power_sensor = config.get(CONF_POWER_SENSOR)

        self._current_temperature = None
        self._current_humidity = None

        if self._temp_sensor_entity_id:
            async_track_state_change(
                hass, temp_sensor_entity_id,
                self._async_temp_sensor_changed)

            sensor_state = hass.states.get(temp_sensor_entity_id)

            if sensor_state:
                self._async_update_current_temp(sensor_state)
        '''

    def _get_command_value(self, section):
        swing_mode = ''
        if self._swing_modes:
            swing_mode = '_' + self._current_swing_mode
            swing_mode = swing_mode.replace(' ', '')
        temp = '_' + str(int(self._target_temperature)
                         if self.target_temperature ==
                         int(self.target_temperature)
                         else self._target_temperature).replace('.', '_')
        value = self._current_fan_mode
        value = value.replace(' ', '') + swing_mode + temp

        if value in self._commands_ini[section]:
            return value

        if self._swing_modes:
            # definitely incorrect configuration
            _LOGGER.warning("Please check your ini file for command "
                            "'%s' in section '%s'", value, section)
            return value

        value = self._current_fan_mode
        return value.replace(' ', '') + temp

    def _set_custom_mode(self, hvac_mode):
        if self._current_mode in self._custom_modes:
            # store status for custom mode
            custom_mode = self._custom_modes[self._current_mode]
            if CONF_TARGET_TEMP in custom_mode:
                custom_mode[CONF_TARGET_TEMP] = self._target_temperature

            if CONF_FAN_MODES in custom_mode:
                custom_mode[CONF_CURRENT_FAN_MODE] = self._current_fan_mode

            if CONF_SWING_MODES in custom_mode:
                custom_mode[CONF_CURRENT_SWING_MODE] = self._current_swing_mode
        elif self._current_mode != HVAC_MODE_OFF:
            self._common_temp_conf = self._common_temp_conf[:3] + (self._target_temperature,)
            self._common_fan_conf = self._common_fan_conf[:1] + (self._current_fan_mode,)
            self._common_swing_conf = self._common_swing_conf[:1] + (self._current_swing_mode,)

        if hvac_mode in self._custom_modes:
            custom_mode = self._custom_modes[hvac_mode]
            if CONF_MIN_TEMP in custom_mode:
                self._min_temp = custom_mode[CONF_MIN_TEMP]

            if CONF_MAX_TEMP in custom_mode:
                self._max_temp = custom_mode[CONF_MAX_TEMP]

            if CONF_TARGET_TEMP in custom_mode:
                self._target_temperature = custom_mode[CONF_TARGET_TEMP]

            if CONF_PRECISION in custom_mode:
                self._precision = custom_mode[CONF_PRECISION]

            if CONF_FAN_MODES in custom_mode:
                self._fan_modes = custom_mode[CONF_FAN_MODES]
                self._current_fan_mode = custom_mode[CONF_CURRENT_FAN_MODE]

            if CONF_SWING_MODES in custom_mode:
                self._swing_modes = custom_mode[CONF_SWING_MODES]
                self._current_swing_mode = custom_mode[CONF_CURRENT_SWING_MODE]
        elif hvac_mode != HVAC_MODE_OFF:
            (self._min_temp, self._max_temp, self._precision,
             self._target_temperature) = self._common_temp_conf
            (self._fan_modes, self._current_fan_mode) = self._common_fan_conf
            (self._swing_modes, self._current_swing_mode) = self._common_swing_conf

    async def send_ir(self):
        async with self._temp_lock:
            section = self._current_mode

            value = 'off_command' if section == HVAC_MODE_OFF else self._get_command_value(section)
            payload = self._commands_ini.get(section, value)

            service_data_json = {'host':  self._host, 'packet': payload}
            # _LOGGER.debug("json: %s", service_data_json)

            await self.hass.services.async_call('broadlink', 'send',
                                                service_data_json )

    '''
    async def _async_temp_sensor_changed(self, entity_id, old_state, new_state):
        """Handle temperature changes."""
        if new_state is None:
            return

        self._async_update_current_temp(new_state)
        await self.async_update_ha_state()
    '''

    @property
    def precision(self) -> float:
        return self._precision

    '''
    async def _async_humidity_sensor_changed(self, entity_id, old_state, new_state):
        """Handle humidity sensor changes."""
        if new_state is None:
            return

        self._async_update_humidity(new_state)
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

    @callback
    def _async_update_temp(self, state):
        """Update thermostat with latest state from temperature sensor."""
        try:
            if state.state != STATE_UNKNOWN:
                self._current_temperature = float(state.state)
        except ValueError as ex:
            _LOGGER.error("Unable to update from temperature sensor: %s", ex)

    @callback
    def _async_update_humidity(self, state):
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
    def should_poll(self):
        """Return the polling state."""
        return False
    '''

    @property
    def name(self):
        """Return the name of the climate device."""
        return self._name

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
        return self._current_mode

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
        return self._current_mode

    @property
    def current_temperature(self) -> Optional[float]:
        """Return the current temperature."""
        return self._current_temperature
    '''

    @property
    def target_temperature(self) -> Optional[float]:
        """Return the temperature we try to reach."""
        return self._target_temperature

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
        return self._current_fan_mode

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
        return self._current_swing_mode

    @property
    def swing_modes(self) -> Optional[List[str]]:
        """Return the list of available swing modes.

        Requires SUPPORT_SWING_MODE.
        """
        return self._swing_modes

    def set_temperature(self, **kwargs) -> None:
        """Set new target temperature."""
        # TODO
        pass

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)

        if temperature is None:
            return

        if temperature < self._min_temp or temperature > self._max_temp:
            _LOGGER.warning('The temperature value is out of min/max range')
            return

        self._target_temperature = round(temperature) if self._precision == PRECISION_WHOLE else round(temperature, 1)

        if not (self._current_mode == HVAC_MODE_OFF):
            self._last_temp_per_mode[self._current_mode] = self._target_temperature
            await self.send_ir()

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

    def set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        pass

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        self._current_fan_mode = fan_mode

        if not (self._current_mode == HVAC_MODE_OFF):
            await self.send_ir()
        await self.async_update_ha_state()
        # await self.hass.async_add_executor_job(self.set_fan_mode, fan_mode)

    '''
    def set_hvac_mode(self, hvac_mode: str) -> None:
        """Set new target hvac mode."""
        pass
    '''

    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        """Set new target hvac mode."""
        self._set_custom_mode(hvac_mode)
        if hvac_mode == HVAC_MODE_OFF:
            if self._current_mode != HVAC_MODE_OFF:
                self._last_on_mode = self._current_mode
        elif hvac_mode != self._current_mode:
            self._last_on_mode = hvac_mode
            self._target_temperature = self._last_temp_per_mode.get(hvac_mode, self._target_temperature)

        self._current_mode = hvac_mode

        await self.send_ir()
        await self.async_update_ha_state()
        # await self.hass.async_add_executor_job(self.set_hvac_mode, hvac_mode)

    '''
    def set_swing_mode(self, swing_mode: str) -> None:
        """Set new target swing mode."""
        pass
    '''

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set new target swing operation."""
        self._current_swing_mode = swing_mode

        if not (self._current_mode == HVAC_MODE_OFF):
            await self.send_ir()

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
        if self._last_on_mode is not None:
            await self.async_set_hvac_mode(self._last_on_mode)
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

    @property
    def device_state_attributes(self) -> dict:
        """Platform specific attributes."""
        return {
            'last_on_mode' : self._last_on_mode,
            'last_temp_per_mode' : self._last_temp_per_mode,
        }

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()

        if last_state is not None:
            self._current_mode = last_state.state
            self._current_fan_mode = last_state.attributes[ATTR_FAN_MODE]
            self._current_swing_mode = last_state.attributes[ATTR_SWING_MODE]

            if 'last_on_mode' in last_state.attributes:
                self._last_on_mode = last_state.attributes['last_on_mode']

            if 'last_temp_per_mode' in last_state.attributes:
                self._last_temp_per_mode = last_state.attributes['last_temp_per_mode']

            if self._last_on_mode in self._last_temp_per_mode:
                self._target_temperature = self._last_temp_per_mode[self._last_on_mode]

        '''
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
        '''
