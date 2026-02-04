import os
import cv2
import time
import threading
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
        
        # 2. Phân loại và đếm
        classes = results[0].boxes.cls.tolist() if hasattr(results[0].boxes, 'cls') else []
        count = len(classes)
        
        # Đếm ng_pill dựa trên class name
        ng_pill = 0
        names = self.model.names
        for cls_idx in classes:
            name = names.get(cls_idx, "").lower()
            if "ng" in name or "defect" in name:
                ng_pill += 1
                
        print(f">>> [CAMERA] Detect thành công: {count} objects (NG Pill: {ng_pill})", flush=True)
        
        # 3. Vẽ kết quả lên ảnh
        annotated_frame = results[0].plot()

        # 4. Encode ảnh sang dạng Binary (JPEG)
        success, buffer = cv2.imencode(".jpg", annotated_frame)
        
        if success:
            return {
                "count": count,
                "ng_pill": ng_pill,
                "image_bytes": buffer.tobytes()
            }
        return None

    def stop(self):
        self.running = False
        self.cap.release()
