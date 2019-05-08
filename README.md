# ha-custome-component
HomeAssistant Custom Component 

Configure

climate:                                                                           
  - platform: broadlink                                                            
    name: Toyotomi Akira                                                           
    host: 192.168.1.85                                                             
    mac: 'BB:BB:BB:BB:BB:BB'                                                       
    ircodes_ini: 'broadlink_climate_codes/toyotomi_akira.ini'                      
    min_temp: 16                                                                   
    max_temp: 30                                                                   
    precision: 1                                                            
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
              # we should have __common swing mode__ to support operation specific swing mode
              # auto mode has only a few swing modes 
              - auto                                                               
              - swing                                                              
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
