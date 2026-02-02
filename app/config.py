import os

# --- PATHS ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = "/home/cminh/aiot/pill_detection/weights/best.pt"

# --- NETWORK ---
RTSP_URL = "rtsp://admin:IJMCYI@192.168.1.80:554/ch1/main"
MQTT_HOST = "192.168.1.77" 
MQTT_PORT = 1883
MQTT_USER = "congminh_broker"
MQTT_PASS = "congminh_broker"

# --- DATABASE ---
# MONGODB_URL = "mongodb://congminh_mongo:congminh_mongo@192.168.1.77:27017/?authSource=admin"
# (Using current URL from database.py for consistency)
MONGODB_URL = "mongodb://congminh_mongo:congminh_mongo@192.168.1.77:27017/?authSource=admin"

# --- LOGIC SETTINGS ---
THRESHOLD = 12
NODE_ID = "AIOT_001"
