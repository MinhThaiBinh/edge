import os
import sys
import asyncio
from typing import Optional
from fastapi import FastAPI, Request
from datetime import datetime

# Add parent directory to sys.path to allow imports if running main.py directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# NNPACK FIX
os.environ["TORCH_NNPACK"] = "0"
os.environ["TORCH_CPP_LOG_LEVEL"] = "ERROR"

from app.config import MODEL_PATH, RTSP_URL, MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS
from app.drivers.camera import CameraSystem
from app.drivers.mqtt import (
    CounterService, 
    HMIDefectService, 
    HMIChangeoverService,
    HMIDowntimeService
)
from app.storage.db import ensure_timeseries
from app.engine.logic import (
    get_current_shift_code, 
    get_current_shift,
    check_and_create_downtime, 
    update_current_production_stats,
    finalize_production_record_on_shift_change,
    initialize_production_record
)
from app.utils.messaging import set_mqtt_publish_func
from app.engine.processor import (
    process_and_save_defect, 
    process_and_save_counter, 
    process_and_save_hmi_defect,
    process_hmi_changeover,
    process_hmi_downtime_reason
)

app = FastAPI(title="Edge IoT AI Backend")



# State
state = {
    "camera_sys": None,
    "counter_service": None,
    "hmi_service": None,
    "changeover_service": None,
    "downtime_service": None,
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
    if data: 
        print(f">>> [MQTT] Nhận dữ liệu Defect từ HMI: {data}")
        asyncio.run_coroutine_threadsafe(process_and_save_hmi_defect(data), state["loop"])

def changeover_callback(data):
    if data: asyncio.run_coroutine_threadsafe(process_hmi_changeover(data), state["loop"])

def downtime_callback(data):
    if data: asyncio.run_coroutine_threadsafe(process_hmi_downtime_reason(data), state["loop"])

# --- TASKS ---

async def main_monitor_task():
    """Task chạy ngầm: Giám sát đổi ca, Phát hiện downtime và Cập nhật KPI định kỳ."""
    # Khởi tạo ca hiện tại
    last_shift = await get_current_shift_code()
    now_utc = datetime.utcnow()
    print(f">>> [MONITOR] Bắt đầu monitor task. Ca hiện tại: {last_shift}")
    
    # --- NEW: Kiểm tra và chốt bản ghi tồn đọng khi khởi động ---
    try:
        from app.storage.db import get_production_db
        db = get_production_db()
        
        # 1. Dọn dẹp whitespace dư thừa trong DB (Sanitization)
        print(">>> [STARTUP] Đang chuẩn hóa dữ liệu machinecode...")
        # (Sẽ thực thực hiện quét và update nếu cần, nhưng để an toàn và nhanh, 
        # ta tập trung vào việc đóng các downtime active 'ma')
        
        # 2. Xử lý bản ghi sản xuất tồn đọng
        stale_prods = await db.production_records.find({"status": "running"}).to_list(None)
        for p in stale_prods:
            m_code = p["machinecode"].strip()
            p_code = p["productcode"].strip()
            
            # Nếu bản ghi thuộc ca khác với ca hiện tại, chốt nó lại
            if p.get("shiftcode") != last_shift:
                print(f">>> [STARTUP] Phát hiện bản ghi tồn đọng từ ca cũ ({p.get('shiftcode')}) cho máy {m_code}. Đang chốt...")
                await finalize_production_record_on_shift_change(m_code, {}, now_utc)
                # Mở bản ghi mới cho ca hiện tại
                await initialize_production_record(m_code, p_code)
            else:
                # Nếu vẫn cùng ca, đảm bảo machinecode đã được strip trong DB
                if p["machinecode"] != m_code:
                    await db.production_records.update_one({"_id": p["_id"]}, {"$set": {"machinecode": m_code}})

        # 3. Đóng tất cả các Downtime 'ma' (Active nhưng máy đang Running)
        print(">>> [STARTUP] Đang kiểm tra và đóng các Downtime active không hợp lệ...")
        active_dts = await db.downtime_records.find({"status": "active"}).to_list(None)
        for dt in active_dts:
            m_code = dt["machinecode"].strip()
            # Kiểm tra xem máy này có đang có record 'running' không
            is_running = await db.production_records.find_one({"machinecode": m_code, "status": "running"})
            # Nếu máy đang running (từ ca hiện tại), thì không thể có downtime active (trừ khi vừa mới phát sinh)
            # Tuy nhiên để dọn dẹp 'ma', ta sẽ đóng các downtime cũ hơn 5 phút
            dt_duration = (datetime.utcnow() - dt["start_time"]).total_seconds()
            if is_running and dt_duration > 300: 
                print(f">>> [STARTUP] Đóng downtime 'ma' cho máy {m_code} ({int(dt_duration)}s)")
                await close_active_downtime(m_code)

    except Exception as e:
        print(f">>> [STARTUP ERROR] Lỗi dọn dẹp bản ghi: {e}")

    while True:
        try:
            # 1. Kiểm tra đổi ca (logic chuyển giao bình thường)
            current_shift = await get_current_shift_code()
            if current_shift != last_shift:
                print(f">>> [SHIFT] Phát hiện đổi ca: {last_shift} -> {current_shift}")
                now_utc = datetime.utcnow()
                
                db = get_production_db()
                active_prods = await db.production_records.find({"status": "running"}).to_list(None)
                
                for p in active_prods:
                    m_code = p["machinecode"]
                    p_code = p["productcode"]
                    await finalize_production_record_on_shift_change(m_code, {}, now_utc)
                    await initialize_production_record(m_code, p_code)
                
                last_shift = current_shift
            
            # 2. Kiểm tra downtime tự động (quá ngưỡng cấu hình)
            await check_and_create_downtime()
            
            # 3. Cập nhật OEE/KPI real-time
            db = get_production_db()
            active_prods = await db.production_records.find({"status": "running"}).to_list(None)
            for p in active_prods:
                await update_current_production_stats(p["machinecode"])
                
        except Exception as e:
            print(f">>> [MONITOR ERROR] Lỗi trong loop monitor: {e}")
            
        await asyncio.sleep(30)

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
        state["downtime_service"] = HMIDowntimeService(MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS)

        # Callbacks
        state["counter_service"].set_callback(counter_callback)
        state["hmi_service"].set_callback(hmi_callback)
        state["changeover_service"].set_callback(changeover_callback)
        state["downtime_service"].set_callback(downtime_callback)

        # Start Services
        state["counter_service"].start()
        state["hmi_service"].start()
        state["changeover_service"].start()
        state["downtime_service"].start()
        
        # Thiết lập callback cho messaging util
        set_mqtt_publish_func(state["downtime_service"].publish)
        
        asyncio.create_task(main_monitor_task())
        print("--- Hệ thống đã sẵn sàng ---")
    except Exception as e:
        print(f">>> [ERROR] Khởi động thất bại: {e}")

@app.on_event("shutdown")
async def shutdown():
    print("--- Đang dừng hệ thống ---")
    if state["counter_service"]: state["counter_service"].stop()
    if state["hmi_service"]: state["hmi_service"].stop()
    if state["changeover_service"]: state["changeover_service"].stop()
    if state["downtime_service"]: state["downtime_service"].stop()
    if state["camera_sys"]: state["camera_sys"].stop()
