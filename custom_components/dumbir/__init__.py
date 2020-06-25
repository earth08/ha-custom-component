"""DubmIR"""
import logging
import os.path
import yaml


_LOGGER = logging.getLogger(__name__)


def load_ircodes(hass, ircodes_path):
    """load ircodes"""
    if ircodes_path.startswith("/"):
        ircodes_path = ircodes_path[1:]

    ir_codes_path = hass.config.path(ircodes_path)

    if not os.path.exists(ir_codes_path):
        _LOGGER.error("The ir code file was not found. (%s)", ir_codes_path)
        return None

    with open(ir_codes_path, 'r') as f:
        ir_codes = yaml.load(f, Loader=yaml.SafeLoader)

    if not ir_codes:
        _LOGGER.error("The ir code file is empty. (%s)", ir_codes_path)

    return ir_codes


async def send_command(hass, host, payload):
    """send command to broadlink remote"""
    if type(payload) is not str:
        # get an element from the array
        for ite in payload:
            # send a command
            send_command(hass, host, ite)

    service_data_json = {'host':  host, 'packet': payload}
    _LOGGER.debug("json: %s", service_data_json)

    await hass.services.async_call('broadlink', 'send',
                                   service_data_json)
