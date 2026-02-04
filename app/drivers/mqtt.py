import paho.mqtt.client as mqtt
import json

class BaseMQTTService:
    def __init__(self, broker_host, broker_port, topic, username=None, password=None, prefix="MQTT"):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.topic = topic
        self.prefix = prefix
        print(f">>> [{self.prefix}] Initializing on topic: {self.topic}")
        
        try:
            # Paho MQTT v2.0+ support
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
        except AttributeError:
            # Paho MQTT v1.x
            self.client = mqtt.Client()
            
        if username and password:
            self.client.username_pw_set(username, password)
            
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.external_callback = None

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f">>> [{self.prefix}] Đã kết nối tới {self.broker_host}", flush=True)
            self.client.subscribe(self.topic, qos=1)
            print(f">>> [{self.prefix}] Đã subscribe: {self.topic}", flush=True)
        else:
            print(f">>> [{self.prefix}] Kết nối thất bại, mã lỗi: {rc}", flush=True)

    def _on_message(self, client, userdata, msg):
        try:
            payload_str = msg.payload.decode("utf-8")
            data = json.loads(payload_str)
            print(f"[{self.prefix}] Received on {msg.topic}: {msg.payload}")
            if self.external_callback:
                self.external_callback(data)
        except Exception as e:
            print(f"[{self.prefix}] Lỗi parse dữ liệu: {e}")

    def set_callback(self, callback_func):
        self.external_callback = callback_func

    def start(self):
        self.client.connect(self.broker_host, self.broker_port, 60)
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def publish(self, topic, data):
        try:
            payload = json.dumps(data, default=str)
            self.client.publish(topic, payload, qos=1)
            print(f">>> [{self.prefix}] Published to {topic}")
        except Exception as e:
            print(f"[{self.prefix}] Lỗi publish: {e}")

class CounterService(BaseMQTTService):
    def __init__(self, host, port, user, pw):
        super().__init__(host, port, "topic/sensor/counter", user, pw, "MQTT COUNTER")

class HMIDefectService(BaseMQTTService):
    def __init__(self, host, port, user, pw):
        super().__init__(host, port, "topic/defect/hmi", user, pw, "MQTT HMI")

class HMIChangeoverService(BaseMQTTService):
    def __init__(self, host, port, user, pw):
        super().__init__(host, port, "topic/changover/hmi", user, pw, "MQTT CHANGEOVER")

class HMIDowntimeService(BaseMQTTService):
    def __init__(self, host, port, user, pw):
        super().__init__(host, port, "topic/downtimeinput", user, pw, "MQTT DOWNTIME")

class DefectMasterService(BaseMQTTService):
    def __init__(self, host, port, user, pw):
        super().__init__(host, port, "topic/get/defectmaster", user, pw, "MQTT DEFECT MASTER")

class ProductionRecordService(BaseMQTTService):
    def __init__(self, host, port, user, pw):
        super().__init__(host, port, "topic/get/productionrecord", user, pw, "MQTT PRODUCTION")
