# ================== NNPACK FIX ==================
import os
import sys
os.environ["TORCH_NNPACK"] = "0"
os.dup2(os.open(os.devnull, os.O_WRONLY), 2)
# ===============================================

import json
import asyncio
import paho.mqtt.client as mqtt
from fastapi import FastAPI
from services.camera_service import CameraSystem
from services.processor import process_and_save_defect # Import logic xử lý mới

from database import ensure_timeseries
app = FastAPI()

# --- CẤU HÌNH ---
MODEL_PATH = "/home/cminh/aiot/pill_detection/weights/best.pt"
RTSP_URL = "rtsp://admin:IJMCYI@192.168.1.80:554/ch1/main"

# Khởi tạo hệ thống AI (Lưu ý: CameraSystem mới không cần SAVE_DIR nữa)
camera_sys = CameraSystem(RTSP_URL, MODEL_PATH)

# --- LOGIC MQTT ---
def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode()
        print(f"\n[MQTT TRIGGER] Nhận tín hiệu: {payload}")
        
        # 1. Gọi AI xử lý lấy data (bao gồm bytes ảnh)
        ai_res = camera_sys.capture_and_detect()
        
        if ai_res is None:
            print(">>> LỖI: Không lấy được frame từ Camera.")
            return

        # 2. Đẩy vào background task để xử lý logic ngưỡng & lưu DB
        # Vì on_message là hàm sync, ta dùng loop để chạy hàm async
        asyncio.run_coroutine_threadsafe(
            process_and_save_defect(ai_res), 
            loop
        )

    except Exception as e:
        print(f">>> Lỗi xử lý message: {e}")

mqtt_client = mqtt.Client()
mqtt_client.username_pw_set("congminh_broker", "congminh_broker")
mqtt_client.on_message = on_message

@app.on_event("startup")
async def startup():
    await ensure_timeseries()
    global loop
    loop = asyncio.get_running_loop() # Lấy loop hiện tại của FastAPI
    
    print("--- Khởi động hệ thống Edge AIoT ---")
    try:
        mqtt_client.connect("192.168.1.79", 1883, 60)
        mqtt_client.subscribe("topic/sensor/counter")
        mqtt_client.loop_start()
    except Exception as e:
        print(f"Không thể kết nối Broker: {e}")

@app.on_event("shutdown")
def shutdown():
    camera_sys.stop()
