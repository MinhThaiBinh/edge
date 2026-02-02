import paho.mqtt.client as mqtt
import json

class HMIDefectService:
    def __init__(self, broker_host, broker_port, username=None, password=None):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.topic = "topic/defect/hmi"
        
        # Khởi tạo client
        self.client = mqtt.Client()
        
        if username and password:
            self.client.username_pw_set(username, password)
            
        # Gán các callback nội bộ
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        
        # Biến để lưu callback xử lý logic bên ngoài
        self.external_callback = None

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f">>> [MQTT HMI] Đã kết nối tới {self.broker_host}", flush=True)
            self.client.subscribe(self.topic, qos=1)
            print(f">>> [MQTT HMI] Đã subscribe: {self.topic}", flush=True)
        else:
            print(f">>> [MQTT HMI] Kết nối thất bại, mã lỗi: {rc}", flush=True)

    def _on_message(self, client, userdata, msg):
        try:
            payload_str = msg.payload.decode("utf-8")
            data = json.loads(payload_str)
            print(f">>> [HMI MQTT] Nhận thông tin lỗi: {data}")
            
            # Gói tin kỳ vọng: {"device": "m011", "defectcode": "d0"}
            if self.external_callback:
                self.external_callback(data)
                
        except Exception as e:
            print(f">>> [HMI MQTT] Lỗi parse dữ liệu: {e}")

    def set_callback(self, callback_func):
        """Gán logic xử lý khi nhận tin nhắn từ HMI"""
        self.external_callback = callback_func

    def start(self):
        """Khởi động kết nối"""
        try:
            self.client.connect(self.broker_host, self.broker_port, 60)
            self.client.loop_start()
        except Exception as e:
            print(f">>> [HMI MQTT] Không thể kết nối: {e}")

    def stop(self):
        """Dừng kết nối"""
        self.client.loop_stop()
        self.client.disconnect()
