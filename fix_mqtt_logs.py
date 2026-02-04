import os

# 1. Update app/drivers/mqtt.py
mqtt_path = 'app/drivers/mqtt.py'
with open(mqtt_path, 'r', encoding='utf-8') as f:
    mqtt_content = f.read()

new_service = """
class ProductionRecordService(BaseMQTTService):
    def __init__(self, host, port, user, pw):
        super().__init__(host, port, "topic/get/productionrecord", user, pw, "MQTT PRODUCTION")
"""
if "class ProductionRecordService" not in mqtt_content:
    mqtt_content += new_service
    with open(mqtt_path, 'w', encoding='utf-8') as f:
        f.write(mqtt_content)
    print("Added ProductionRecordService to mqtt.py")

# 2. Update app/main.py
main_path = 'app/main.py'
with open(main_path, 'r', encoding='utf-8') as f:
    main_content = f.read()

# Add to state
if '"production_service": None' not in main_content:
    main_content = main_content.replace('"loop": None', '"production_service": None,\n    "loop": None')

# Add to imports
if 'ProductionRecordService' not in main_content:
    main_content = main_content.replace('HMIDowntimeService', 'HMIDowntimeService, ProductionRecordService')

# Initialize and start
init_line = 'state["production_service"] = ProductionRecordService(MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS)'
if init_line not in main_content:
    main_content = main_content.replace('state["defect_master_service"] = DefectMasterService(MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS)', 
                                        'state["defect_master_service"] = DefectMasterService(MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS)\n        ' + init_line)
    main_content = main_content.replace('state["defect_master_service"].start()', 
                                        'state["defect_master_service"].start()\n        state["production_service"].start()')

# Change publish func
main_content = main_content.replace('set_mqtt_publish_func(state["downtime_service"].publish)', 
                                    'set_mqtt_publish_func(state["production_service"].publish)')

with open(main_path, 'w', encoding='utf-8') as f:
    f.write(main_content)
print("Updated main.py to use ProductionRecordService for publishing")
