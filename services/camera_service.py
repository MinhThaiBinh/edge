import cv2
import time
import os
import threading
import gc
from datetime import datetime
from ultralytics import YOLO

class CameraSystem:
    def __init__(self, url, model_path, save_dir):
        print(f"--- Đang nạp Model YOLO từ: {model_path} ---")
        self.model = YOLO(model_path)
        self.cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.save_dir = save_dir
        self.latest_frame = None
        self.lock = threading.Lock()
        self.running = True
        self.stt = 1

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
                return {"error": "No frame"}
            frame = self.latest_frame.copy()

        # Inference
        results = self.model.predict(source=frame, imgsz=640, conf=0.25, verbose=False)
        
        # Tạo tên file lưu ảnh
        now = datetime.now().strftime("%H_%M_%S")
        filename = f"{now}_{self.stt}.jpg"
        os.makedirs(self.save_dir, exist_ok=True)
        
        # Vẽ bounding box và lưu
        annotated = results[0].plot()
        cv2.imwrite(os.path.join(self.save_dir, filename), annotated)
        
        self.stt += 1
        return {
            "time": now,
            "count": len(results[0].boxes),
            "file": filename
        }

    def stop(self):
        self.running = False
        self.cap.release()