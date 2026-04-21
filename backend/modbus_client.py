import time
import threading

from pymodbus.client import ModbusSerialClient

PORT = "COM7"
BAUDRATE = 9600
PARITY = "N"
STOPBITS = 1
BYTESIZE = 8
TIMEOUT = 1.5
SLAVE_ID = 0x01

READ_BLOCKS = {
    "voltage": {"start": 0x0000, "count": 6},
    "power": {"start": 0x0200, "count": 6},
    "temperature": {"start": 0x0300, "count": 6},
    "current": {"start": 0x0400, "count": 6},
    "status": {"start": 0x1500, "count": 6},
}

COIL_BY_CHANNEL = {
    1: 0x0000,
    2: 0x0001,
    3: 0x0002,
    4: 0x0003,
    5: 0x0004,
    6: 0x0005,
}

# 串口是单资源，Flask并发请求下需要全局互斥，避免端口抢占导致 PermissionError(13)
SERIAL_LOCK = threading.Lock()


def _modbus_crc(data):
    crc = 0xFFFF
    for value in data:
        crc ^= value
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def _with_crc(payload):
    crc = _modbus_crc(payload)
    return payload + [crc & 0xFF, (crc >> 8) & 0xFF]


def _to_hex(payload):
    return " ".join(f"{byte:02X}" for byte in payload)


def _build_read_request(start_addr, count):
    payload = [SLAVE_ID, 0x03, (start_addr >> 8) & 0xFF, start_addr & 0xFF, (count >> 8) & 0xFF, count & 0xFF]
    return _with_crc(payload)


def _build_read_response(registers):
    payload = [SLAVE_ID, 0x03, len(registers) * 2]
    for reg in registers:
        payload.extend([(reg >> 8) & 0xFF, reg & 0xFF])
    return _with_crc(payload)


def _build_write_request(coil_addr, turn_on):
    value_hi = 0xFF if turn_on else 0x00
    payload = [SLAVE_ID, 0x05, (coil_addr >> 8) & 0xFF, coil_addr & 0xFF, value_hi, 0x00]
    return _with_crc(payload)


def _build_write_response(coil_addr, turn_on):
    return _build_write_request(coil_addr, turn_on)


def _normalize_action(action):
    action_text = str(action or "").strip().lower()
    if action_text in {"close", "on", "合闸"}:
        return True
    if action_text in {"open", "off", "分闸"}:
        return False
    raise ValueError("action must be open/close")


class DormModbusClient:
    def __init__(self):
        self.client = ModbusSerialClient(
            port=PORT,
            baudrate=BAUDRATE,
            parity=PARITY,
            stopbits=STOPBITS,
            bytesize=BYTESIZE,
            timeout=TIMEOUT,
        )

    def connect(self):
        return self.client.connect()

    def close(self):
        try:
            self.client.close()
        except Exception:
            pass

    def read_registers(self, start_addr, count):
        with SERIAL_LOCK:
            for attempt in range(2):
                if not self.connect():
                    if attempt == 1:
                        return {"success": False, "message": "串口连接失败"}
                    time.sleep(0.2)
                    continue
                try:
                    response = self.client.read_holding_registers(address=start_addr, count=count, device_id=SLAVE_ID)
                    if response.isError():
                        if attempt == 1:
                            return {"success": False, "message": f"Modbus读取失败: {response}"}
                        time.sleep(0.2)
                        continue

                    registers = response.registers or []
                    request_hex = _to_hex(_build_read_request(start_addr, count))
                    response_hex = _to_hex(_build_read_response(registers))
                    return {
                        "success": True,
                        "start_addr": start_addr,
                        "count": count,
                        "registers": registers,
                        "request_hex": request_hex,
                        "response_hex": response_hex,
                    }
                except Exception as exc:
                    if attempt == 1:
                        return {"success": False, "message": f"读取异常: {repr(exc)}"}
                    time.sleep(0.2)
                finally:
                    self.close()

    def write_single_coil(self, coil_addr, action):
        try:
            turn_on = _normalize_action(action)
        except ValueError as exc:
            return {"success": False, "message": str(exc)}

        with SERIAL_LOCK:
            if not self.connect():
                return {"success": False, "message": "串口连接失败"}

            try:
                response = self.client.write_coil(address=coil_addr, value=turn_on, device_id=SLAVE_ID)
                if response.isError():
                    return {"success": False, "message": f"Modbus写线圈失败: {response}"}

                request_hex = _to_hex(_build_write_request(coil_addr, turn_on))
                response_hex = _to_hex(_build_write_response(coil_addr, turn_on))
                return {
                    "success": True,
                    "coil_addr": coil_addr,
                    "action": "close" if turn_on else "open",
                    "request_hex": request_hex,
                    "response_hex": response_hex,
                }
            except Exception as exc:
                return {"success": False, "message": f"写线圈异常: {repr(exc)}"}
            finally:
                self.close()


def _status_to_breaker_on(status_raw):
    if status_raw in {0x5A00, 0xA500}:
        return True
    if status_raw == 0x0000:
        return False
    return False


def _build_channels(raw_map):
    channels = []
    for index in range(6):
        voltage_raw = raw_map["voltage"][index]
        power_raw = raw_map["power"][index]
        temp_raw = raw_map["temperature"][index]
        current_raw = raw_map["current"][index]
        status_raw = raw_map["status"][index]
        channels.append(
            {
                "ch": index + 1,
                "voltage_raw": voltage_raw,
                "voltage": float(voltage_raw),
                "power_raw": power_raw,
                "power": float(power_raw),
                "temperature_raw": temp_raw,
                "temperature": round(temp_raw / 10.0, 1),
                "current_raw": current_raw,
                "current": round(float(current_raw) * 0.1, 3),
                # 按现场口径，漏电与电流当前同源寄存器，先输出 raw 字段待后续倍率标定
                "leakage_current_raw": current_raw,
                "leakage_current": float(current_raw),
                "status_raw": f"{status_raw:04X}",
                "breaker_on": _status_to_breaker_on(status_raw),
            }
        )
    return channels


def read_all_blocks():
    block_results = {}
    raw_map = {}

    for metric_name, block in READ_BLOCKS.items():
        result = DormModbusClient().read_registers(start_addr=block["start"], count=block["count"])
        block_results[metric_name] = result
        if not result.get("success"):
            return {
                "success": False,
                "message": f"{metric_name} 读取失败: {result.get('message', 'unknown error')}",
                "blocks": block_results,
            }
        raw_map[metric_name] = result["registers"]

    channels = _build_channels(raw_map)
    return {
        "success": True,
        "channels": channels,
        "blocks": block_results,
    }


def control_breaker(channel, action):
    try:
        channel_no = int(channel)
    except Exception:
        return {"success": False, "message": "channel must be integer"}

    if channel_no not in COIL_BY_CHANNEL:
        return {"success": False, "message": "channel must be in 1~6"}

    write_result = DormModbusClient().write_single_coil(COIL_BY_CHANNEL[channel_no], action)
    if not write_result.get("success"):
        return write_result

    # 继电器状态回写寄存器存在硬件延时，避免回读过快导致展示旧状态
    time.sleep(0.2)
    status_result = DormModbusClient().read_registers(
        start_addr=READ_BLOCKS["status"]["start"],
        count=READ_BLOCKS["status"]["count"],
    )
    if not status_result.get("success"):
        return {
            "success": False,
            "message": "控制下发成功，但状态回读失败",
            "write": write_result,
            "status_read": status_result,
        }

    raw_status = status_result["registers"][channel_no - 1]
    return {
        "success": True,
        "write": write_result,
        "status_read": status_result,
        "channel": channel_no,
        "status_raw": f"{raw_status:04X}",
        "breaker_on": _status_to_breaker_on(raw_status),
    }
