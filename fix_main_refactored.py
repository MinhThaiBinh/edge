import os

path = 'app/main.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the broken downtime_service line
content = content.replace('state["downtime_service"] = HMIDowntimeService, ProductionRecordService(MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS)', 
                          'state["downtime_service"] = HMIDowntimeService(MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS)')

# Ensure imports are clean
content = content.replace('HMIDowntimeService, ProductionRecordService, ProductionRecordService', 'HMIDowntimeService, ProductionRecordService')

# Fix consecutive duplicate lines of production_service if any
content = content.replace('state["production_service"] = ProductionRecordService(MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS)\n        state["production_service"] = ProductionRecordService(MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS)', 
                          'state["production_service"] = ProductionRecordService(MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS)')

# Also fix the start service section if it duplicated
content = content.replace('state["production_service"].start()\n        state["production_service"].start()', 
                          'state["production_service"].start()')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Manually cleaned up main.py and fixed the tuple error.")
