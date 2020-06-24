#!/usr/bin/env python3

import argparse
from configparser import ConfigParser
import logging
import pprint
import yaml

FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT, level=logging.DEBUG)

_LOGGER = logging.getLogger(__name__)

def main(yaml_file):
    with open(yaml_file, 'r') as stream:
        conf = yaml.safe_load(stream)

    pp = pprint.PrettyPrinter(indent=2)
    for k, v in conf.items():
        print(k)
        if type(v) is dict:
            for k1, v1 in v.items():
                print("  {}".format(k1))
                if type(v1) is dict:
                  for k2, v2 in v1.items():
                      print("    {}".format(k2))
                      if type(v2) is dict:
                          for k3, v3 in v2.items():
                              print("      {}".format(k3))



if __name__ == '__main__':
    parser = argparse.ArgumentParser(fromfile_prefix_chars='@');
    parser.add_argument('yaml', help="yaml file")
    args = parser.parse_args()

    main(args.yaml)
