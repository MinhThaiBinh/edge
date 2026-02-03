from typing import Callable, Any, Optional

# Global callback variable to be set by main.py
_mqtt_publish_func: Optional[Callable[[str, Any], None]] = None

def set_mqtt_publish_func(func: Callable[[str, Any], None]):
    global _mqtt_publish_func
    _mqtt_publish_func = func

def mqtt_publish(topic: str, data: Any):
    if _mqtt_publish_func:
        _mqtt_publish_func(topic, data)
    else:
        print(f">>> [MESSAGING] Warning: MQTT publish function not set. Cannot send to {topic}")
