# ================== NNPACK FIX ==================
import os
import sys
os.environ["TORCH_NNPACK"] = "0"
# os.dup2(os.open(os.devnull, os.O_WRONLY), 2)
# ===============================================

import cv2
import time
import threading
from datetime import datetime
from ultralytics import YOLO

class CameraSystem:
    def __init__(self, url, model_path):
        print(f"--- Đang nạp Model YOLO từ: {model_path} ---", flush=True)
        self.model = YOLO(model_path)
        self.cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.latest_frame = None
        self.lock = threading.Lock()
        self.running = True

        self.reader_thread = threading.Thread(target=self._camera_reader, daemon=True)
        self.reader_thread.start()

    def _camera_reader(self):
        while self.running:
            ret, frame = self.cap.read()
            if ret and frame is not None:
                with self.lock:
                    self.latest_frame = frame
            time.sleep(0.01)

    def capture_and_detect(self):
        with self.lock:
            if self.latest_frame is None:
                return None
            frame = self.latest_frame.copy()

        # 1. AI Inference
        results = self.model.predict(source=frame, imgsz=640, conf=0.25, verbose=False)
        count = len(results[0].boxes)
        
        # 2. Vẽ kết quả lên ảnh
        annotated_frame = results[0].plot()

        # 3. Encode ảnh sang dạng Binary (JPEG) thay vì lưu ổ cứng
        # success: True/False, buffer: mảng byte ảnh
        success, buffer = cv2.imencode(".jpg", annotated_frame)
        
        if success:
            return {
                "count": count,
                "image_bytes": buffer.tobytes() # Chuyển sang bytes cho MongoDB
            }
        return None

    def stop(self):
        self.running = False
        self.cap.release()
