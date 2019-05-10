# ha-custome-component
HomeAssistant Custom Component 

## dumbir : custome component broadlink IR 
[`climate.py`](https://github.com/vpnmaster/homeassistant-custom-components/tree/master/custom_components/climate) is originally written by @vpnmaster, @Thunderbird2086 added **swing mode** and keeps maintaining.

* Supported Home Assistant version : 0.92 or above as of April 24th 2019

### How to install
1. copy the directory `dumbir` to `.homeassistant/custom_compoents/dumbir`.
1. copy IR data to `.homeassistatn/broadlink_ir_codes/broadlink_climate_codes`
1. Add configuration to `.homessistant/configuration.yaml`. See below.

#### Configuration variables:
**name** (Optional): Name of climate component<br />
**host** (Required): The hostname/IP address of the broadlink rm device<br />
**mac** (Required): The MAC address of the broadlink rm device <br />
**timeout** (Optional): Timeout in seconds for the connection to the device<br />
**ircodes_ini** (Required): The path of ir codes ini file<br />
**min_temp** (Optional): Set minimum set point available (default: 16)<br />
**max_temp** (Optional): Set maximum set point available (default: 30)<br />
**precision** (Optional): Set your climate device temperature precision. Supported values are 0.1, 0.5 and 1.0. Τhis value also defines the temperature_step (default: 1.0)<br />
**temp_sensor** (Optional): **entity_id** for a temperature sensor, **temp_sensor.state must be temperature.**<br />
**customize** (Optional): List of options to customize.<br />
  **- operations** (Optional*): List of operation modes (default: auto)<br />
  **- fan_modes** (Optional*): List of fan modes (default: auto)<br />
  **- swing_modes** (Optional*): List of swing modes. It doesn't have default values. Please omit if your device doesn't support<br />
  
#### Sample configuation
```yaml
climate:
  - platform: dumbir
    name: Daikin
    host: 192.168.1.85
    mac: 'BB:BB:BB:BB:BB:BB'
    # note that path is 'broadlink_climate_codes'
    ircodes_ini: 'broadlink_climate_codes/daikin_arc_478a19.ini'
    min_temp: 18
    max_temp: 30
    precision: .5
    temp_sensor: sensor.living_room_temperature
    customize:
      fan_modes:
        # common fan modes
        - low
        - mid
        - high
        - auto
      swing_modes:
        # common swing modes
        - auto
        - swing
        - high
        - mid
        - low
      operations:
        - auto:
            # auto mode specific settings
            min_temp: -5
            max_temp: 5
            precision: 0.5
            fan_modes:
              # In this example, auto mode has only one fan mode of nice
              # we should have __common fan mode__ to support operation specific fan mode
              - nice
            swing_modes:
              # auto mode has only a few swing modes
              # we should have __common swing mode__ to support operation specific swing mode
              - auto
              - swing
            # we should set default swing mode as it has only one swing mode
            default_swing_mode: auto
            default_fan_mode: nice
        - cool:
        - heat:
        - dry:
            # This is an example
            # dry mode specific settings
            min_temp: -2
            max_temp: 2
            precision: 0.5
            swing_modes:
              # dry mode has only one swing mode of auto
              - auto
            # we should set default swing mode as it has only one swing mode
            default_swing_mode: auto
            default_fan_mode: auto
```

#### How to make new IR command file(INI):
```ini
[off]   ; operation mode
off_command = ...

[idle]   ; operation mode
idle_command = ...

[dry]   ; operation mode
; a command consist of fan mode, swing mode (if exist), and temperature
low_swing_1 = ...
...

[heat]   ; heat
; In this example, heat mode does not have swing mode.
low_25 = ...
...

[cool]   ; cool
; In this example, cool mode has swing mode.
high_swing_18 = ...
...

```
