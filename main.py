import os
import paho.mqtt.client as mqtt
from fastapi import FastAPI
from services.camera_service import CameraSystem

# Tắt cảnh báo hệ thống
os.environ["TORCH_NNPACK"] = "0"

app = FastAPI()

# --- CẤU HÌNH ĐƯỜNG DẪN ---
MODEL_PATH = "/home/cminh/aiot/pill_detection/weights/best.pt"
RTSP_URL = "rtsp://admin:IJMCYI@192.168.186.19:554/ch1/main"
SAVE_DIR = "/home/cminh/aiot/pill_detection/received_images"

# Khởi tạo hệ thống AI
camera_sys = CameraSystem(RTSP_URL, MODEL_PATH, SAVE_DIR)

# --- LOGIC MQTT ---
def on_message(client, userdata, msg):
    payload = msg.payload.decode()
    print(f"\n[MQTT TRIGGER] Nhận tín hiệu: {payload}")
    
    # Gọi AI xử lý
    res = camera_sys.capture_and_detect()
    
    # In kết quả ra Terminal để bạn theo dõi (Thay vì lưu DB)
    if "error" in res:
        print(">>> LỖI: Camera chưa sẵn sàng.")
    else:
        print(f">>> KẾT QUẢ AI: Tìm thấy {res['count']} viên thuốc. Ảnh lưu: {res['file']}")

mqtt_client = mqtt.Client()
mqtt_client.username_pw_set("congminh_broker", "congminh_broker")
mqtt_client.on_message = on_message

@app.on_event("startup")
async def startup():
    print("--- Khởi động hệ thống Edge AIoT ---")
    mqtt_client.connect("192.168.1.108", 1883, 60)
    mqtt_client.subscribe("topic/sensor/counter")
    mqtt_client.loop_start()

@app.on_event("shutdown")
def shutdown():
    camera_sys.stop()
    mqtt_client.loop_stop()