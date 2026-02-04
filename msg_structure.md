# MQTT Message Structure Documentation

This document describes the JSON structure of messages for each MQTT topic used in the system.

## 1. Machine Counter (Incoming)
- **Topic**: `topic/sensor/counter`
- **Purpose**: Receives production counts from machine sensors.
- **Payload**:
| Field | Type | Description |
| :--- | :--- | :--- |
| `device` | string | Unique machine identifier (machinecode) |
| `shootcountnumber` | number | Current pulse/counter value from sensor |

Example:
```json
{
  "device": "PACKING_01",
  "shootcountnumber": 1250
}
```

## 2. HMI Defect Reporting (Incoming)
- **Topic**: `topic/defect/hmi`
- **Purpose**: Manual defect entry from the HMI.
- **Payload**:
| Field | Type | Description |
| :--- | :--- | :--- |
| `device` | string | Unique machine identifier |
| `defectcode` | string | Code representing the defect type (e.g., "d1", "d2") |

Example:
```json
{
  "device": "PACKING_01",
  "defectcode": "d1"
}
```

## 3. HMI Product Changeover (Incoming)
- **Topic**: `topic/changover/hmi`
- **Purpose**: Signals a change from one product to another.
- **Payload**:
| Field | Type | Description |
| :--- | :--- | :--- |
| `device` | string | Unique machine identifier |
| `productcode` | string | Code for the new product being started |
| `oldproduct` | string | Code for the product that just finished |

Example:
```json
{
  "device": "PACKING_01",
  "productcode": "PROD_BRU_002",
  "oldproduct": "PROD_BRU_001"
}
```

## 4. HMI Downtime Reason (Incoming / Outgoing)
- **Topic**: `topic/downtimeinput`
- **Purpose**: Bidirectional communication for downtime events and reasons.

### A. Incoming (HMI -> Edge): Update Downtime Reason
| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | string | Record ID of the downtime entry in Database |
| `machine` | string | Unique machine identifier |
| `downtimecode`| string | Reason code selected by operator |

### B. Outgoing (Edge -> HMI): Downtime Status Notification
| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | string | Record ID in Database |
| `machine` | string | Unique machine identifier |
| `status` | string | `active` (started) or `closed` (ended) |
| `downtimecode`| string | Current reason code |
| `createtime` | string | Start timestamp (ISO format) |
| `endtime` | string | End timestamp or "None" |

Example (Outgoing Status):
```json
{
  "id": "65b2f...123",
  "machine": "PACKING_01",
  "status": "active",
  "downtimecode": "M01",
  "createtime": "2024-02-04T10:00:00.000Z",
  "endtime": "None"
}
```

## 5. Camera AI Analysis (Internal Data)
While not an external MQTT topic, the internal structure used for AI processing is:
```json
{
  "count": 10,
  "ng_pill": 1,
  "image_bytes": "<binary_data_or_base64>"
}
```

## 6. Request Defect Master (Incoming / Outgoing)
- **Request Topic**: 
- **Response Topic**: 
- **Purpose**: Client requests a full list of available defect types from the master dictionary.

### A. Incoming Request (Client -> Edge)
```json
{
    "machine": "MACHINE_CODE"
}
```

### B. Outgoing Response (Edge -> Client)
```json
{
    "machine": "MACHINE_CODE",
    "defects": [
        {
            "defectcode": "d0",
            "defectname": "Thiếu viên",
            "defectgroup": "LVT"
        },
        ...
    ],
    "timestamp": "2026-02-04T10:00:00.000Z"
}
```

## 6. Request Defect Master (Incoming / Outgoing)
- **Request Topic**: topic/get/defectmaster
- **Response Topic**: topic/get/defectmaster/res
- **Purpose**: Client requests a full list of available defect types from the master dictionary.

### A. Incoming Request (Client -> Edge)
```json
{
    "machine": "MACHINE_CODE"
}
```

### B. Outgoing Response (Edge -> Client)
```json
{
    "machine": "MACHINE_CODE",
    "defects": [
        {
            "defectcode": "d0",
            "defectname": "Thiếu viên",
            "defectgroup": "LVT"
        },
        ...
    ],
    "timestamp": "2026-02-04T10:00:00.000Z"
}
```
