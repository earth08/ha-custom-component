#!/usr/bin/env python3

import argparse
from configparser import ConfigParser
import logging
import yaml

FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT, level=logging.DEBUG)

_LOGGER = logging.getLogger(__name__)


def modify_command(cmd):
    if not cmd.endswith('_command'):
        return cmd

    new_cmd = 'command_'
    new_cmd = new_cmd + cmd.replace('_command', '')

    return new_cmd


def get_power_command(modes, ircodes_ini):
    power = {}
    if 'idle' in modes:
        # power.update(ircodes_ini['idle'])
        for opt in ircodes_ini['idle']:
            power.update({modify_command(opt): ircodes_ini['idle'][opt]})
        ircodes_ini.remove_section('idle')
        modes.remove('idle')

    if 'off' in modes:
        # power.update(ircodes_ini['off'])
        for opt in ircodes_ini['off']:
            power.update({modify_command(opt): ircodes_ini['off'][opt]})
        ircodes_ini.remove_section('off')
        modes.remove('off')

    return power


def get_modes(modes, ircodes_ini):
    commands = {}
    for mode in modes:
        if mode not in commands:
            commands[mode] = {}

        for cmd in ircodes_ini[mode]:
            pos = cmd.find('_')
            fan = cmd[:pos]
            if fan not in commands[mode]:
                commands[mode][fan] = {}

            pos = pos + 1
            swing = None
            if not cmd[pos].isdigit():
                pos2 = cmd.find('_', pos)
                swing = cmd[pos:pos2]
                if swing not in commands[mode][fan]:
                    commands[mode][fan][swing] = {}
                pos = pos2 + 1

            temp = cmd[pos:]
            temp = float(temp.replace('_', '.'))

            if swing:
                commands[mode][fan][swing][temp] = ircodes_ini[mode][cmd]
            else:
                commands[mode][fan][temp] = ircodes_ini[mode][cmd]

    return commands


def main(ini_file):
    ircodes_ini = ConfigParser()
    ircodes_ini.read(ini_file)

    modes = ircodes_ini.sections()
    commands = {}
    commands.update({'power': get_power_command(modes, ircodes_ini)})
    commands.update(get_modes(modes, ircodes_ini))

    commands = {'commands': commands}

    yaml_file = ini_file.replace('ini', 'yaml')
    with open(yaml_file, 'w') as outfile:
        yaml.dump(commands, outfile)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(fromfile_prefix_chars='@')
    parser.add_argument('ini', help="ini file")
    args = parser.parse_args()

    main(args.ini)
