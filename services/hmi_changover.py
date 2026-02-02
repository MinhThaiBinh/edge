import paho.mqtt.client as mqtt
import json

class HMIChangeoverService:
    def __init__(self, broker_host, broker_port, username=None, password=None):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.topic = "topic/changover/hmi"
        
        # Khởi tạo client với API Version 1 để tương thích với code cũ
        try:
            # Paho MQTT v2.0+
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
        except AttributeError:
            # Paho MQTT v1.x
            self.client = mqtt.Client()
        
        if username and password:
            self.client.username_pw_set(username, password)
            
        # Gán các callback nội bộ
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        
        # Biến để lưu hàm xử lý logic từ bên ngoài
        self.external_callback = None

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f">>> [MQTT CHANGEOVER] Đã kết nối tới {self.broker_host}", flush=True)
            self.client.subscribe(self.topic, qos=1)
            print(f">>> [MQTT CHANGEOVER] Đã subscribe: {self.topic}", flush=True)
        else:
            print(f">>> [MQTT CHANGEOVER] Kết nối thất bại, mã lỗi: {rc}", flush=True)

    def _on_message(self, client, userdata, msg):
        try:
            payload_str = msg.payload.decode("utf-8")
            data = json.loads(payload_str)
            print(f">>> [MQTT CHANGEOVER] Nhận dữ liệu: {data}")
            
            if self.external_callback:
                self.external_callback(data)
                
        except Exception as e:
            print(f"[MQTT CHANGEOVER] Lỗi parse dữ liệu: {e}")

    def set_callback(self, callback_func):
        self.external_callback = callback_func

    def start(self):
        self.client.connect(self.broker_host, self.broker_port, 60)
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
