# ================== NNPACK FIX ==================
import os
import sys
os.environ["TORCH_NNPACK"] = "0"
# ===============================================

import asyncio
from fastapi import FastAPI
from services.camera_service import CameraSystem
from services.processor import (
    process_and_save_defect, 
    process_and_save_counter, 
    process_and_save_hmi_defect,
    process_hmi_changeover
)
from services.counter_service import CounterService
from services.hmidefect_service import HMIDefectService
from services.hmi_changover import HMIChangeoverService
from database import ensure_timeseries
from logic import get_current_shift_code

app = FastAPI()

# --- CẤU HÌNH ---
MODEL_PATH = "/home/cminh/aiot/pill_detection/weights/best.pt"
RTSP_URL = "rtsp://admin:IJMCYI@192.168.1.80:554/ch1/main"
MQTT_HOST = "192.168.1.77" 
MQTT_PORT = 1883
MQTT_USER = "congminh_broker"
MQTT_PASS = "congminh_broker"

# Các instance service sẽ được khởi tạo trong sự kiện startup
camera_sys = None
counter_service = None
hmi_service = None
changeover_service = None

# --- CALLBACK XỬ LÝ DỮ LIỆU ---

def counter_callback(data):
    """Xử lý dữ liệu từ Counter sensor"""
    try:
        if not data or not isinstance(data, dict):
            return

        device_id = data.get("device")

        # Lưu Counter
        if device_id:
            print(f">>> [MQTT] Nhận dữ liệu counter từ {device_id}")
            asyncio.run_coroutine_threadsafe(process_and_save_counter(data), loop)
        
            # Kích hoạt AI check gắn với thiết bị vừa gửi counter
            if camera_sys:
                print(f">>> [AI] Kích hoạt kiểm tra camera cho {device_id}...", flush=True)
                ai_res = camera_sys.capture_and_detect()
                if ai_res:
                    # Đổi thành machinecode theo yêu cầu cấu trúc bảng
                    asyncio.run_coroutine_threadsafe(process_and_save_defect(ai_res, machinecode=device_id), loop)

    except Exception as e:
        print(f">>> [ERROR] Lỗi trong counter_callback: {e}")

def hmi_callback(data):
    """Xử lý dữ liệu báo lỗi từ HMI"""
    try:
        if data:
            asyncio.run_coroutine_threadsafe(process_and_save_hmi_defect(data), loop)
    except Exception as e:
        print(f">>> [ERROR] Lỗi trong hmi_callback: {e}")

def changeover_callback(data):
    """Xử lý dữ liệu thay đổi sản phẩm từ HMI"""
    try:
        if data:
            asyncio.run_coroutine_threadsafe(process_hmi_changeover(data), loop)
    except Exception as e:
        print(f">>> [ERROR] Lỗi trong changeover_callback: {e}")

@app.on_event("startup")
async def startup():
    global loop, camera_sys, counter_service, hmi_service, changeover_service
    
    # Khởi tạo DB
    await ensure_timeseries()
    
    loop = asyncio.get_running_loop()
    
    print("--- Đang khởi tạo hệ thống Edge AIoT ---", flush=True)
    
    try:
        # 1. Khởi tạo CameraSystem (AI)
        print(f">>> [SYSTEM] Đang nạp AI model và kết nối Camera...", flush=True)
        camera_sys = CameraSystem(RTSP_URL, MODEL_PATH)

        # 2. Khởi tạo MQTT Services
        print(f">>> [MQTT] Đang kết nối tới Broker {MQTT_HOST}...", flush=True)
        counter_service = CounterService(MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS)
        hmi_service = HMIDefectService(MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS)
        changeover_service = HMIChangeoverService(MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS)

        # Đăng ký callbacks
        counter_service.set_callback(counter_callback)
        hmi_service.set_callback(hmi_callback)
        changeover_service.set_callback(changeover_callback)

        # Khởi chạy các service MQTT
        counter_service.start()
        hmi_service.start()
        changeover_service.start()
        print(f">>> [MQTT] Đã khởi chạy các service kết nối tới {MQTT_HOST}", flush=True)
        
        # Khởi chạy Shift Monitor Task
        asyncio.create_task(shift_monitor_task())
        print(">>> [SYSTEM] Đã khởi chạy Shift Monitor Task", flush=True)
        
        print("--- Hệ thống đã sẵn sàng ---", flush=True)
    except Exception as e:
        print(f">>> [ERROR] Không thể khởi động hệ thống: {e}", flush=True)

async def shift_monitor_task():
    """Task chạy ngầm để kiểm tra thay đổi ca và khởi tạo record mới"""
    last_shift = await get_current_shift_code()
    print(f">>> [SHIFT] Ca hiện tại: {last_shift}")
    
    while True:
        await asyncio.sleep(60) # Kiểm tra mỗi phút
        current_shift = await get_current_shift_code()
        
        if current_shift != last_shift:
            print(f">>> [SHIFT] Phát hiện đổi ca từ {last_shift} sang {current_shift}")
            # Ở đây có thể cần thêm logic lấy machinecode và productcode hiện tại
            # Giả sử tạm thời lấy từ một biến global hoặc từ DB
            # for machine in tracked_machines:
            #     await initialize_production_record(machine, current_product)
            last_shift = current_shift

@app.on_event("shutdown")
def shutdown():
    print("--- Đang dừng hệ thống ---")
    counter_service.stop()
    hmi_service.stop()
    changeover_service.stop()
    camera_sys.stop()
