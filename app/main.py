import os
import sys
import asyncio
from fastapi import FastAPI

# Add parent directory to sys.path to allow imports if running main.py directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# NNPACK FIX
os.environ["TORCH_NNPACK"] = "0"

from app.config import MODEL_PATH, RTSP_URL, MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS
from app.drivers.camera import CameraSystem
from app.drivers.mqtt import CounterService, HMIDefectService, HMIChangeoverService
from app.storage.db import ensure_timeseries
from app.engine.logic import get_current_shift_code
from app.engine.processor import (
    process_and_save_defect, 
    process_and_save_counter, 
    process_and_save_hmi_defect,
    process_hmi_changeover
)

app = FastAPI(title="Edge IoT AI Backend")

# State
state = {
    "camera_sys": None,
    "counter_service": None,
    "hmi_service": None,
    "changeover_service": None,
    "loop": None
}

# --- CALLBACKS ---

def counter_callback(data):
    try:
        if not data or not isinstance(data, dict): return
        device_id = data.get("device")
        if device_id:
            print(f">>> [MQTT] Nhận dữ liệu counter từ {device_id}")
            asyncio.run_coroutine_threadsafe(process_and_save_counter(data), state["loop"])
            if state["camera_sys"]:
                print(f">>> [AI] Kích hoạt camera cho {device_id}...")
                ai_res = state["camera_sys"].capture_and_detect()
                if ai_res:
                    asyncio.run_coroutine_threadsafe(process_and_save_defect(ai_res, machinecode=device_id), state["loop"])
    except Exception as e:
        print(f">>> [ERROR] Lỗi counter_callback: {e}")

def hmi_callback(data):
    if data: asyncio.run_coroutine_threadsafe(process_and_save_hmi_defect(data), state["loop"])

def changeover_callback(data):
    if data: asyncio.run_coroutine_threadsafe(process_hmi_changeover(data), state["loop"])

# --- TASKS ---

async def shift_monitor_task():
    last_shift = await get_current_shift_code()
    print(f">>> [SHIFT] Ca hiện tại: {last_shift}")
    while True:
        await asyncio.sleep(60)
        current_shift = await get_current_shift_code()
        if current_shift != last_shift:
            print(f">>> [SHIFT] Phát hiện đổi ca: {last_shift} -> {current_shift}")
            last_shift = current_shift

# --- LIFECYCLE ---

@app.on_event("startup")
async def startup():
    print("--- Đang khởi tạo hệ thống Edge AIoT ---", flush=True)
    await ensure_timeseries()
    state["loop"] = asyncio.get_running_loop()
    
    try:
        # Drivers
        state["camera_sys"] = CameraSystem(RTSP_URL, MODEL_PATH)
        state["counter_service"] = CounterService(MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS)
        state["hmi_service"] = HMIDefectService(MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS)
        state["changeover_service"] = HMIChangeoverService(MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS)

        # Callbacks
        state["counter_service"].set_callback(counter_callback)
        state["hmi_service"].set_callback(hmi_callback)
        state["changeover_service"].set_callback(changeover_callback)

        # Start Services
        state["counter_service"].start()
        state["hmi_service"].start()
        state["changeover_service"].start()
        
        asyncio.create_task(shift_monitor_task())
        print("--- Hệ thống đã sẵn sàng ---")
    except Exception as e:
        print(f">>> [ERROR] Khởi động thất bại: {e}")

@app.on_event("shutdown")
async def shutdown():
    print("--- Đang dừng hệ thống ---")
    if state["counter_service"]: state["counter_service"].stop()
    if state["hmi_service"]: state["hmi_service"].stop()
    if state["changeover_service"]: state["changeover_service"].stop()
    if state["camera_sys"]: state["camera_sys"].stop()
