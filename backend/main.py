import time
import threading
import sqlite3
import asyncio
from datetime import datetime
from collections import deque
import uuid
import serial
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from serial.tools import list_ports

app = FastAPI(title="Dorm Power Backend - Engineering Edition")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# 默认配置
# =========================================================
DEFAULT_PORT = "COM7"
DEFAULT_BAUDRATE = 9600
DEFAULT_SLAVE_ID = 1
TIMEOUT = 1.0

current_port = DEFAULT_PORT
current_baudrate = DEFAULT_BAUDRATE
current_slave_id = DEFAULT_SLAVE_ID

# 已确认实时主块：从 0x0000 连续读取 8 个寄存器
REALTIME_START_ADDR = 0x0000
REALTIME_REG_COUNT = 0x0008

# 工程上先只按“分组读取”处理，不再长期使用滑动窗口全扫
REGISTER_GROUPS = [
    {"name": "realtime_main", "start": 0x0000, "count": 8, "desc": "实时主块：电压/漏电流/功率/温度/电流/告警/电量"},
    {"name": "group_0008", "start": 0x0008, "count": 6, "desc": "待验证数据块 0x0008"},
    {"name": "group_0010", "start": 0x0010, "count": 6, "desc": "待验证数据块 0x0010"},
    {"name": "group_0015", "start": 0x0015, "count": 4, "desc": "待验证状态/参数块 0x0015"},
]

# 写线圈：根据文档，00 00 ~ 00 05 对应第1~第6路开关
# 你当前设备使用 0x0003 已验证
DEFAULT_BREAKER_COIL_ADDR = 0x0003

# 串口锁，避免并发访问 COM 口
serial_lock = threading.Lock()
db_lock = threading.Lock()

DB_PATH = "energy_monitor.db"
latest_stream_payload = {
    "timestamp": int(time.time()),
    "realtime": None,
    "co2_kg_per_hour": 0.0,
}
sampler_thread = None
sampler_stop_event = threading.Event()
sampler_pause_until_ts = 0.0
control_busy_until_ts = 0.0
readable_summary_cache = {
    "success": True,
    "port": current_port,
    "baudrate": current_baudrate,
    "slave_id": current_slave_id,
    "timestamp": int(time.time()),
    "realtime": None,
    "input_registers_0x0000_0x0005": None,
    "guide03_blocks": {},
    "coils": None,
    "discrete_inputs": None,
    "errors": {},
    "cache_hit": False,
}
power_history_w = deque(maxlen=60)
last_strategy_state = {
    "idle_start_ts": 0,
    "last_auto_cut_ts": 0,
    "last_nilm_alarm_ts": 0,
}
sampler_failure_count = 0
sampler_consecutive_failures = 0
sampler_last_success_ts = 0.0
sampler_last_error = ""
sampler_backoff_s = 1.0
carbon_factor_kg_per_kwh = 0.5703
control_mode = "manual"
last_control_at_ts = 0.0
last_control_by_key = {}
recent_control_acks = deque(maxlen=50)
last_nilm_score = 0.0
last_nilm_label = "unknown"
device_id = "modbus:default:01"
# 电流校准参数（最小改动：默认保持现有行为）
current_func_addr = 0x04
current_switch_index = 0
current_scale = 0.01


# =========================================================
# CRC / 基础工具
# =========================================================
def crc16_modbus(data: bytes) -> bytes:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def check_crc(resp: bytes) -> bool:
    if len(resp) < 4:
        return False
    body = resp[:-2]
    recv_crc = resp[-2:]
    calc_crc = crc16_modbus(body)
    return recv_crc == calc_crc


def parse_words(data: bytes):
    if len(data) % 2 != 0:
        return []
    return [(data[i] << 8) | data[i + 1] for i in range(0, len(data), 2)]


def to_signed_16(value: int) -> int:
    return value - 0x10000 if value >= 0x8000 else value


def calc_co2_emission(power_w: float) -> float:
    return round((power_w / 3600 / 1000) * 570.3, 4)


def friendly_error(e: Exception) -> str:
    msg = str(e)
    if "PermissionError" in msg or "拒绝访问" in msg:
        return "串口被占用，请关闭串口工具/停止高频轮询/不要重复启动后端"
    if "could not open port" in msg:
        return f"串口打开失败：{msg}"
    return msg


def get_db_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def api_ok(data=None, message="ok", code=0):
    return {
        "success": True,
        "code": code,
        "message": message,
        "data": data,
        "ts": int(time.time() * 1000),
    }


def api_err(message, code=1, data=None):
    return {
        "success": False,
        "code": code,
        "message": message,
        "data": data,
        "ts": int(time.time() * 1000),
    }


def init_db():
    with db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS realtime_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                port TEXT,
                baudrate INTEGER,
                slave_id INTEGER,
                voltage_v REAL,
                leakage_current_ma REAL,
                power_w REAL,
                temperature_c REAL,
                current_a REAL,
                alarm_status INTEGER,
                energy_kwh REAL,
                co2_kg_per_hour REAL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS alarm_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                slave_id INTEGER,
                alarm_status INTEGER,
                alarm_bits TEXT,
                message TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                action_type TEXT,
                target TEXT,
                success INTEGER,
                detail TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS control_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                operator TEXT,
                source TEXT,
                action TEXT,
                mode TEXT,
                idempotency_key TEXT,
                coil_addr TEXT,
                request_frame TEXT,
                response_frame TEXT,
                success INTEGER,
                reason TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS nilm_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT,
                step_w REAL,
                risk_score REAL,
                label TEXT,
                detail TEXT
            )
            """
        )
        conn.commit()
        cur.close()
        conn.close()


def insert_realtime_record(data: dict):
    with db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO realtime_records (
                created_at, port, baudrate, slave_id,
                voltage_v, leakage_current_ma, power_w,
                temperature_c, current_a, alarm_status, energy_kwh, co2_kg_per_hour
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                current_port,
                current_baudrate,
                current_slave_id,
                float(data.get("voltage_v", 0)),
                float(data.get("leakage_current_ma", 0)),
                float(data.get("power_w", 0)),
                float(data.get("temperature_c", 0)),
                float(data.get("current_a", 0)),
                int(data.get("alarm_status", 0)),
                float(data.get("energy_kwh", 0)),
                float(data.get("co2_kg_per_hour", 0)),
            ),
        )
        conn.commit()
        cur.close()
        conn.close()


def insert_alarm_event(alarm_status: int, alarms):
    if alarm_status == 0:
        return
    with db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO alarm_events (created_at, slave_id, alarm_status, alarm_bits, message)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                current_slave_id,
                int(alarm_status),
                ",".join([str(a.get("bit")) for a in alarms]),
                "；".join([a.get("message", "") for a in alarms]),
            ),
        )
        conn.commit()
        cur.close()
        conn.close()


def insert_strategy_action(action_type: str, target: str, success: bool, detail: str):
    with db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO strategy_actions (created_at, action_type, target, success, detail)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                action_type,
                target,
                1 if success else 0,
                detail,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()


def insert_control_log(operator: str, source: str, action: str, mode: str, idempotency_key: str, coil_addr: str,
                      request_frame: str, response_frame: str, success: bool, reason: str):
    with db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO control_logs (
                created_at, operator, source, action, mode, idempotency_key, coil_addr,
                request_frame, response_frame, success, reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                operator,
                source,
                action,
                mode,
                idempotency_key,
                coil_addr,
                request_frame,
                response_frame,
                1 if success else 0,
                reason,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()


def insert_nilm_event(event_type: str, step_w: float, risk_score: float, label: str, detail: str):
    with db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO nilm_events (created_at, event_type, step_w, risk_score, label, detail)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                event_type,
                float(step_w),
                float(risk_score),
                label,
                detail,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()


# =========================================================
# 告警解析
# =========================================================
def parse_alarm_status(alarm_status: int):
    """
    当前文档里未完全坐实 bit 定义，这里先做通用 bit 拆解。
    后续拿到明确 bit 含义再替换文案。
    """
    alarms = []
    if alarm_status == 0:
        return alarms

    for bit in range(16):
        if alarm_status & (1 << bit):
            alarms.append({
                "bit": bit,
                "message": f"告警位 bit{bit} 触发",
                "time": time.strftime("%Y-%m-%d %H:%M:%S")
            })
    return alarms


# =========================================================
# 报文构造
# =========================================================
def build_read_frame(slave_id: int, start_addr: int, count: int, function_code: int = 0x03) -> bytes:
    frame = bytes([
        slave_id,
        function_code,
        (start_addr >> 8) & 0xFF,
        start_addr & 0xFF,
        (count >> 8) & 0xFF,
        count & 0xFF,
    ])
    return frame + crc16_modbus(frame)


def build_bit_read_frame(slave_id: int, function_code: int, start_addr: int, count: int) -> bytes:
    frame = bytes([
        slave_id,
        function_code,
        (start_addr >> 8) & 0xFF,
        start_addr & 0xFF,
        (count >> 8) & 0xFF,
        count & 0xFF,
    ])
    return frame + crc16_modbus(frame)


def build_write_coil_frame(slave_id: int, coil_addr: int, on: bool) -> bytes:
    value_hi = 0xFF if on else 0x00
    value_lo = 0x00
    frame = bytes([
        slave_id,
        0x05,
        (coil_addr >> 8) & 0xFF,
        coil_addr & 0xFF,
        value_hi,
        value_lo,
    ])
    return frame + crc16_modbus(frame)


def build_write_single_register_frame(slave_id: int, reg_addr: int, value: int) -> bytes:
    frame = bytes([
        slave_id,
        0x06,
        (reg_addr >> 8) & 0xFF,
        reg_addr & 0xFF,
        (value >> 8) & 0xFF,
        value & 0xFF,
    ])
    return frame + crc16_modbus(frame)


# =========================================================
# 响应解析
# =========================================================
def parse_read_response(resp: bytes, slave_id: int, expected_fc: int = 0x03, expected_start_addr: int = None):
    """
    工程版解析器，兼容：
    1) 标准 Modbus:
       01 03/04 [byte_count] [data...] CRC

    2) 厂家 echo_addr 格式:
       01 03/04 [addr_hi] [addr_lo] [byte_count] [data...] CRC

    你的现场实测：
       01 03 00 00 10 ...
       01 03 00 08 0C ...
       01 03 00 10 0C ...
    都按 echo_addr 处理。
    """
    if not resp or len(resp) < 7:
        raise Exception("响应为空或长度过短")

    if resp[0] != slave_id:
        raise Exception(f"从站地址不匹配，收到: {resp[0]}")

    if resp[1] & 0x80:
        code = resp[2] if len(resp) > 2 else None
        raise Exception(f"设备返回异常响应，功能码: 0x{resp[1]:02X}, 异常码: {code}")

    if resp[1] != expected_fc:
        raise Exception(f"功能码异常，收到: {resp[1]}")

    if not check_crc(resp):
        raise Exception("CRC 校验失败")

    frame_type = "unknown"
    echoed_addr = None
    byte_count = 0
    data_start = 0

    # 设备现场存在两种格式，优先按“长度+地址”可靠判别，避免把 0x0400 误判为标准帧。
    if len(resp) >= 8:
        candidate_echo_addr = (resp[2] << 8) | resp[3]
        candidate_echo_bc = resp[4]
        echo_len_ok = (5 + candidate_echo_bc + 2) <= len(resp) and candidate_echo_bc > 0 and candidate_echo_bc % 2 == 0
        echo_addr_match = expected_start_addr is not None and candidate_echo_addr == expected_start_addr
        if echo_addr_match or echo_len_ok:
            frame_type = "echo_addr"
            echoed_addr = candidate_echo_addr
            byte_count = candidate_echo_bc
            data_start = 5

    # 标准格式：01 03 0C [data] CRC
    if frame_type == "unknown":
        candidate_std_bc = resp[2]
        std_len_ok = candidate_std_bc > 0 and (3 + candidate_std_bc + 2) <= len(resp)
        if not std_len_ok:
            raise Exception("无法识别读响应帧格式")
        frame_type = "standard"
        byte_count = candidate_std_bc
        data_start = 3

    if byte_count <= 0:
        raise Exception("响应数据字节数无效")

    data_end = data_start + byte_count
    if len(resp) < data_end + 2:
        raise Exception(f"响应数据长度不完整，期望 {byte_count}，实际 {len(resp) - data_start - 2}")

    data = resp[data_start:data_end]
    regs = parse_words(data)

    return {
        "frame_type": frame_type,
        "crc_ok": True,
        "echoed_addr": echoed_addr,
        "byte_count": byte_count,
        "registers": regs,
        "raw_response": resp.hex(" ").upper()
    }


def parse_bit_read_response(resp: bytes, slave_id: int, expected_fc: int):
    if not resp or len(resp) < 5:
        raise Exception("响应为空或长度过短")

    if resp[0] != slave_id:
        raise Exception(f"从站地址不匹配，收到: {resp[0]}")

    if resp[1] & 0x80:
        code = resp[2] if len(resp) > 2 else None
        raise Exception(f"设备返回异常响应，功能码: 0x{resp[1]:02X}, 异常码: {code}")

    if resp[1] != expected_fc:
        raise Exception(f"功能码异常，收到: {resp[1]}")

    if not check_crc(resp):
        raise Exception("CRC 校验失败")

    byte_count = resp[2]
    data_start = 3
    data_end = data_start + byte_count
    if len(resp) < data_end + 2:
        raise Exception("响应数据长度不完整")

    data = resp[data_start:data_end]
    bits = []
    for b in data:
        for i in range(8):
            bits.append((b >> i) & 0x01)

    return {
        "byte_count": byte_count,
        "bits": bits,
        "raw_response": resp.hex(" ").upper(),
    }


# =========================================================
# 文档导向的寄存器映射（先只放“已确认”和“待验证”）
# =========================================================
REGISTER_MAP_CONFIRMED = {
    0x0000: {"name": "total_voltage_v", "signed": False, "scale": 1},
    0x0001: {"name": "leakage_current_ma", "signed": False, "scale": 0.1},
    0x0002: {"name": "total_power_w", "signed": False, "scale": 1},
    0x0003: {"name": "module_temperature_c", "signed": True, "scale": 0.1},
    0x0004: {"name": "line_current_a", "signed": False, "scale": 0.01},
    0x0005: {"name": "alarm_status", "signed": False, "scale": 1},
    0x0006: {"name": "energy_low", "signed": False, "scale": 1},
    0x0007: {"name": "energy_high", "signed": False, "scale": 1},
}

# 扩展读取分组（按文档常用区段拆分，单次读取不超过 125）
FULL_READ_GROUPS = [
    {"name": "base_0000_0023", "start": 0x0000, "count": 0x24, "desc": "基础实时+状态区"},
    {"name": "leakage_0030_0031", "start": 0x0030, "count": 0x02, "desc": "漏电阈值与总告警位"},
]

FULL_REGISTER_FIELD_MAP = {
    0x0000: {"name": "total_voltage_v", "signed": False, "scale": 1},
    0x0001: {"name": "leakage_current_ma", "signed": False, "scale": 0.1},
    0x0002: {"name": "total_power_w", "signed": False, "scale": 1},
    0x0003: {"name": "module_temperature_c", "signed": True, "scale": 0.1},
    0x0004: {"name": "line_current_a", "signed": False, "scale": 0.01},
    0x0005: {"name": "alarm_status", "signed": False, "scale": 1},
    0x0008: {"name": "phase_a_voltage_v", "signed": False, "scale": 1},
    0x0009: {"name": "phase_b_voltage_v", "signed": False, "scale": 1},
    0x000A: {"name": "phase_c_voltage_v", "signed": False, "scale": 1},
    0x000B: {"name": "phase_a_current_a", "signed": False, "scale": 0.01},
    0x000C: {"name": "phase_b_current_a", "signed": False, "scale": 0.01},
    0x000D: {"name": "phase_c_current_a", "signed": False, "scale": 0.01},
    0x000E: {"name": "phase_n_current_a", "signed": False, "scale": 0.01},
    0x000F: {"name": "phase_a_power_w", "signed": False, "scale": 1},
    0x0010: {"name": "phase_b_power_w", "signed": False, "scale": 1},
    0x0011: {"name": "phase_c_power_w", "signed": False, "scale": 1},
    0x0015: {"name": "wiring_mode_bits", "signed": False, "scale": 1},
    0x0016: {"name": "breaker_state_raw", "signed": False, "scale": 1},
    0x0019: {"name": "temp_a_c", "signed": True, "scale": 0.1},
    0x001A: {"name": "temp_b_c", "signed": True, "scale": 0.1},
    0x001B: {"name": "temp_c_c", "signed": True, "scale": 0.1},
    0x001C: {"name": "temp_n_c", "signed": True, "scale": 0.1},
    0x001D: {"name": "phase_short_circuit_status", "signed": False, "scale": 1},
    0x001E: {"name": "phase_alarm_bits", "signed": False, "scale": 1},
    0x001F: {"name": "trip_counter", "signed": False, "scale": 1},
    0x0020: {"name": "device_status_bits", "signed": False, "scale": 1},
    0x0021: {"name": "breaker_open_close_status", "signed": False, "scale": 1},
    0x0022: {"name": "remote_close_forbidden", "signed": False, "scale": 1},
    0x0023: {"name": "rated_current_raw", "signed": False, "scale": 1},
    0x0030: {"name": "leakage_threshold_ma", "signed": False, "scale": 0.1},
    0x0031: {"name": "total_alarm_bits", "signed": False, "scale": 1},
}

DOCUMENT_WRITE_REG_HINTS = {
    0x0000: "电压上限（文档提示，06写寄存器）",
    0x0001: "电压下限（文档提示，06写寄存器）",
    0x0002: "漏电流上限（文档提示，06写寄存器）",
    0x0005: "电流门限（文档提示，06写寄存器）",
    0x000A: "漏电预警值（文档提示，06写寄存器）",
    0x0014: "电压预警上/下限相关（文档提示，06写寄存器）",
    0x0015: "电压预警上/下限相关（文档提示，06写寄存器）",
    0x002B: "A相电流门限（文档提示，06写寄存器）",
    0x002C: "B相电流门限（文档提示，06写寄存器）",
    0x002D: "C相电流门限（文档提示，06写寄存器）",
}


# =========================================================
# 串口收发
# =========================================================
def send_frame(port_name: str, baudrate: int, frame: bytes, read_size: int = 128):
    print("=" * 80)
    print("串口通信开始")
    print("端口:", port_name)
    print("波特率:", baudrate)
    print("发送报文:", frame.hex(" ").upper())

    with serial_lock:
        with serial.Serial(
            port=port_name,
            baudrate=baudrate,
            bytesize=8,
            parity='N',
            stopbits=1,
            timeout=TIMEOUT
        ) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            time.sleep(0.05)

            ser.write(frame)
            ser.flush()

            time.sleep(0.20)
            resp = ser.read(read_size)

    print("接收报文:", resp.hex(" ").upper() if resp else "<空>")
    return resp


# =========================================================
# 读取逻辑
# =========================================================
def read_register_block(
    port_name: str,
    baudrate: int,
    slave_id: int,
    start_addr: int,
    reg_count: int,
    function_code: int = 0x03
):
    request = build_read_frame(slave_id, start_addr, reg_count, function_code=function_code)
    resp = send_frame(port_name, baudrate, request, read_size=128)
    parsed = parse_read_response(resp, slave_id, expected_fc=function_code, expected_start_addr=start_addr)

    return {
        "function_code": function_code,
        "start_addr": start_addr,
        "start_addr_hex": f"0x{start_addr:04X}",
        "reg_count": reg_count,
        "request": request.hex(" ").upper(),
        "response": parsed["raw_response"],
        "frame_type": parsed["frame_type"],
        "crc_ok": parsed["crc_ok"],
        "echoed_addr": parsed["echoed_addr"],
        "echoed_addr_hex": f"0x{parsed['echoed_addr']:04X}" if parsed["echoed_addr"] is not None else None,
        "byte_count": parsed["byte_count"],
        "registers": parsed["registers"]
    }


def read_bit_block(port_name: str, baudrate: int, slave_id: int, function_code: int, start_addr: int, bit_count: int):
    request = build_bit_read_frame(slave_id, function_code, start_addr, bit_count)
    resp = send_frame(port_name, baudrate, request, read_size=128)
    parsed = parse_bit_read_response(resp, slave_id, function_code)

    trimmed_bits = parsed["bits"][:bit_count]
    active_indices = [i for i, v in enumerate(trimmed_bits) if v == 1]
    return {
        "function_code": function_code,
        "start_addr": start_addr,
        "start_addr_hex": f"0x{start_addr:04X}",
        "bit_count": bit_count,
        "request": request.hex(" ").upper(),
        "response": parsed["raw_response"],
        "byte_count": parsed["byte_count"],
        "bits": trimmed_bits,
        "active_indices": active_indices,
        "active_addrs": [start_addr + i for i in active_indices],
        "active_addrs_hex": [f"0x{start_addr + i:04X}" for i in active_indices],
    }


def read_group(group_name: str, port_name: str, baudrate: int, slave_id: int):
    group = next((g for g in REGISTER_GROUPS if g["name"] == group_name), None)
    if not group:
        raise Exception(f"未知分组: {group_name}")

    block = read_register_block(
        port_name,
        baudrate,
        slave_id,
        group["start"],
        group["count"]
    )

    return {
        "name": group["name"],
        "desc": group["desc"],
        "start": group["start"],
        "count": group["count"],
        "block": block
    }


def parse_realtime_from_registers(regs):
    if len(regs) < 8:
        raise Exception(f"实时寄存器不足，至少需要 8 个，实际 {len(regs)}")

    voltage_v = float(regs[0])
    leakage_current_ma = round(regs[1] * 0.1, 2)
    power_w = float(regs[2])
    temperature_c = round(to_signed_16(regs[3]) * 0.1, 1)
    current_a = round(regs[4] * 0.01, 2)
    alarm_status = int(regs[5])
    energy_raw = (regs[7] << 16) | regs[6]
    energy_kwh = round(energy_raw / 1000, 3)

    return {
        "voltage_v": voltage_v,
        "leakage_current_ma": leakage_current_ma,
        "power_w": power_w,
        "temperature_c": temperature_c,
        "current_a": current_a,
        "alarm_status": alarm_status,
        "energy_kwh": energy_kwh,
        "timestamp": int(time.time())
    }


def read_realtime_legacy(port_name: str, baudrate: int, slave_id: int):
    block = read_register_block(port_name, baudrate, slave_id, REALTIME_START_ADDR, REALTIME_REG_COUNT)
    parsed = parse_realtime_from_registers(block["registers"])

    return {
        "frame_type": block["frame_type"],
        "crc_ok": block["crc_ok"],
        "echoed_addr": block["echoed_addr"],
        "raw_response": block["response"],
        "raw_registers": block["registers"],
        **parsed
    }


def read_guide_value_block(port_name: str, baudrate: int, slave_id: int, func_addr: int, switch_start: int = 0, switch_count: int = 4):
    start_addr = (func_addr << 8) | (switch_start & 0xFF)
    return read_register_block(
        port_name,
        baudrate,
        slave_id,
        start_addr,
        switch_count,
        function_code=0x03
    )


def pick_switch_value(block: dict, switch_index: int = 0):
    regs = block.get("registers", [])
    if not regs:
        return 0
    if switch_index < 0 or switch_index >= len(regs):
        switch_index = 0
    return regs[switch_index]


def parse_manual_switch_states(words):
    """
    手册 0x15 分合闸状态:
    每路通常用高字节表示，5A=合闸，A5=分闸。
    """
    states = []
    for idx, w in enumerate(words):
        high = (int(w) >> 8) & 0xFF
        state = "unknown"
        on = None
        if high == 0x5A:
            state = "close_on"
            on = True
        elif high == 0xA5:
            state = "open_off"
            on = False
        states.append({
            "switch_no": idx + 1,
            "raw_word_hex": f"0x{int(w):04X}",
            "state_code_hex": f"0x{high:02X}",
            "state": state,
            "on": on
        })
    return states


def parse_manual_alarm_bits(words):
    """
    手册 0x31 总告警位:
    现场常见有效值在高字节，做高字节优先并保留16位兜底。
    """
    parsed = []
    for idx, w in enumerate(words):
        raw16 = int(w) & 0xFFFF
        hi = (raw16 >> 8) & 0xFF
        parsed.append({
            "switch_no": idx + 1,
            "raw_word_hex": f"0x{raw16:04X}",
            "active_bits_hi": parse_bit_flags(hi, width=8),
            "active_bits_16": parse_bit_flags(raw16, width=16),
        })
    return parsed


def read_realtime(port_name: str, baudrate: int, slave_id: int):
    """
    统一走手册标准格式:
      start_addr = (func_addr << 8) | switch_start
    """
    blocks = {}
    errors = {}
    func_map = {
        "total_voltage": 0x00,      # 手册明确
        "current": current_func_addr,  # 可配置，默认 0x04
        "phase_a_voltage": 0x08,    # 手册明确
        "phase_b_voltage": 0x09,    # 手册明确
        "phase_c_voltage": 0x0A,    # 手册明确
        "phase_a_current": 0x0B,    # 手册明确
        "phase_b_current": 0x0C,    # 手册明确
        "phase_c_current": 0x0D,    # 手册明确
        "phase_n_current": 0x0E,    # 手册明确
        "switch_state": 0x15,       # 手册明确
        "total_alarm_bits": 0x31,   # 手册明确
    }
    for name, func_addr in func_map.items():
        try:
            blocks[name] = read_guide_value_block(
                port_name,
                baudrate,
                slave_id,
                func_addr=func_addr,
                switch_start=0,
                switch_count=4
            )
        except Exception as e:
            errors[name] = friendly_error(e)
            blocks[name] = {"registers": []}

    voltage_raw = pick_switch_value(blocks["total_voltage"], 0)
    current_raw = pick_switch_value(blocks["current"], current_switch_index)
    switch_words = blocks["switch_state"].get("registers", [])
    alarm_words = blocks["total_alarm_bits"].get("registers", [])
    alarm_status = pick_switch_value(blocks["total_alarm_bits"], 0)

    # 手册示例 379/221 等直接为伏特，不做缩放
    voltage_v = float(voltage_raw)
    current_a = round(current_raw * current_scale, 3)
    power_w = 0.0
    temperature_c = 0.0
    energy_kwh = 0.0
    switch_states = parse_manual_switch_states(switch_words)
    breaker_on = any(s.get("on") is True for s in switch_states)
    alarm_details = parse_manual_alarm_bits(alarm_words)
    humidity_rh = 50.0
    feels_like_c = round(temperature_c + 0.02 * max(0.0, humidity_rh - 50.0), 2)
    env_status = "舒适" if 18 <= temperature_c <= 29 else "偏冷/偏热"

    return {
        "frame_type": "guide03_standard",
        "raw_response": blocks["total_voltage"].get("response", ""),
        "raw_registers": blocks["total_voltage"].get("registers", []),
        "voltage_v": voltage_v,
        "leakage_current_ma": 0.0,
        "power_w": power_w,
        "temperature_c": temperature_c,
        "current_a": current_a,
        "alarm_status": int(alarm_status),
        "energy_kwh": energy_kwh,
        "breaker_on": breaker_on,
        "switch_states": switch_states,
        "alarm_details": alarm_details,
        "humidity_rh": humidity_rh,
        "feels_like_c": feels_like_c,
        "environment_status": env_status,
        "strict_manual_mode": True,
        "manual_unconfirmed_fields": ["power_w", "temperature_c", "energy_kwh"],
        "guide_blocks": {k: v.get("registers", []) for k, v in blocks.items()},
        "current_calibration": {
            "func_addr": current_func_addr,
            "switch_index": current_switch_index,
            "scale": current_scale,
            "raw": current_raw,
        },
        "read_errors": errors,
        "timestamp": int(time.time()),
        "timestamp_ms": int(time.time() * 1000),
        "device_id": f"{port_name}:{slave_id}",
        "quality_flag": "good" if not errors else "degraded",
    }


def build_stream_payload(realtime_data: dict):
    power_w = float(realtime_data.get("power_w", 0))
    co2_kg_per_hour = round((power_w / 1000.0) * carbon_factor_kg_per_kwh, 4)
    co2_g_per_second = round((co2_kg_per_hour * 1000.0) / 3600.0, 4)
    return {
        "timestamp": int(time.time()),
        "realtime": realtime_data,
        "co2_kg_per_hour": co2_kg_per_hour,
        "co2_g_per_second": co2_g_per_second,
    }


def evaluate_strategy_rules(realtime_data: dict):
    """
    规则 + AI(简化NILM)：
    - 功率阶跃检测
    - 工作时段无人空转治理
    - 超大功率自动断电
    """
    now_ts = time.time()
    power_w = float(realtime_data.get("power_w", 0.0))
    breaker_on = bool(realtime_data.get("breaker_on", False))

    global last_nilm_score, last_nilm_label
    if power_history_w:
        step_w = abs(power_w - power_history_w[-1])
    else:
        step_w = 0.0
    power_history_w.append(power_w)

    nilm_threshold = 300.0
    nilm_cooldown_s = 30.0
    risk_score = min(100.0, round((step_w / nilm_threshold) * 45 + max(power_w - 1200, 0) / 30, 2))
    label = "normal"
    if risk_score >= 70:
        label = "high_risk_appliance"
    elif risk_score >= 45:
        label = "suspicious_appliance"
    last_nilm_score = risk_score
    last_nilm_label = label

    if step_w >= nilm_threshold and now_ts - last_strategy_state["last_nilm_alarm_ts"] > nilm_cooldown_s:
        detail = f"NILM阶跃识别: step={round(step_w,1)}W, power={round(power_w,1)}W"
        insert_strategy_action("nilm_step_alarm", "load_profile", True, detail)
        insert_nilm_event("step_detected", step_w, risk_score, label, detail)
        last_strategy_state["last_nilm_alarm_ts"] = now_ts

    dt = datetime.now()
    in_class_time = dt.weekday() < 5 and (8 <= dt.hour <= 17)
    if in_class_time and breaker_on and power_w > 80:
        if last_strategy_state["idle_start_ts"] <= 0:
            last_strategy_state["idle_start_ts"] = now_ts
        idle_duration = now_ts - last_strategy_state["idle_start_ts"]
    else:
        idle_duration = 0
        last_strategy_state["idle_start_ts"] = 0

    auto_cut_done = False
    if power_w >= 2500 and now_ts - last_strategy_state["last_auto_cut_ts"] > 20:
        try:
            control_breaker(current_port, current_baudrate, current_slave_id, close_on=False, coil_addr=DEFAULT_BREAKER_COIL_ADDR)
            insert_strategy_action("auto_cutoff_overpower", f"coil:0x{DEFAULT_BREAKER_COIL_ADDR:04X}", True, f"power={power_w}W")
            last_strategy_state["last_auto_cut_ts"] = now_ts
            auto_cut_done = True
        except Exception as e:
            insert_strategy_action("auto_cutoff_overpower", f"coil:0x{DEFAULT_BREAKER_COIL_ADDR:04X}", False, friendly_error(e))

    if idle_duration >= 300 and now_ts - last_strategy_state["last_auto_cut_ts"] > 20:
        try:
            control_breaker(current_port, current_baudrate, current_slave_id, close_on=False, coil_addr=DEFAULT_BREAKER_COIL_ADDR)
            insert_strategy_action("auto_cutoff_idle", f"coil:0x{DEFAULT_BREAKER_COIL_ADDR:04X}", True, f"idle_for={int(idle_duration)}s")
            last_strategy_state["last_auto_cut_ts"] = now_ts
            auto_cut_done = True
            last_strategy_state["idle_start_ts"] = 0
        except Exception as e:
            insert_strategy_action("auto_cutoff_idle", f"coil:0x{DEFAULT_BREAKER_COIL_ADDR:04X}", False, friendly_error(e))

    return {
        "power_step_w": round(step_w, 2),
        "nilm_risk_score": risk_score,
        "nilm_label": label,
        "nilm_threshold_w": nilm_threshold,
        "nilm_cooldown_s": nilm_cooldown_s,
        "in_class_time": in_class_time,
        "idle_duration_s": int(idle_duration),
        "auto_cutoff_triggered": auto_cut_done,
        "strategy_mode": "rule+ai-strict-manual"
    }


def sampler_loop():
    global latest_stream_payload, readable_summary_cache
    global sampler_failure_count, sampler_consecutive_failures, sampler_last_success_ts, sampler_last_error, sampler_backoff_s, device_id
    while not sampler_stop_event.is_set():
        if time.time() < sampler_pause_until_ts:
            sampler_stop_event.wait(0.1)
            continue
        try:
            data = read_realtime(current_port, current_baudrate, current_slave_id)
            device_id = data.get("device_id", device_id)
            strategy = evaluate_strategy_rules(data)
            payload = build_stream_payload(data)
            payload["strategy"] = strategy
            payload["alarm"] = {"active": parse_alarm_status(int(data.get("alarm_status", 0)))}
            payload["control_ack"] = recent_control_acks[-1] if recent_control_acks else None
            latest_stream_payload = payload
            db_record = dict(data)
            db_record["co2_kg_per_hour"] = payload["co2_kg_per_hour"]
            insert_realtime_record(db_record)
            insert_alarm_event(int(data.get("alarm_status", 0)), parse_alarm_status(int(data.get("alarm_status", 0))))
            readable_summary_cache["realtime"] = data
            readable_summary_cache["timestamp"] = int(time.time())
            sampler_last_success_ts = time.time()
            sampler_last_error = ""
            sampler_consecutive_failures = 0
            sampler_backoff_s = 1.0
        except Exception as e:
            sampler_failure_count += 1
            sampler_consecutive_failures += 1
            sampler_last_error = friendly_error(e)
            latest_stream_payload = {
                "timestamp": int(time.time()),
                "realtime": None,
                "co2_kg_per_hour": 0.0,
                "error": friendly_error(e),
            }
            sampler_backoff_s = min(8.0, sampler_backoff_s * 2.0)
        sampler_stop_event.wait(max(1.0, sampler_backoff_s))


def ensure_sampler_started():
    global sampler_thread
    if sampler_thread is None or not sampler_thread.is_alive():
        sampler_stop_event.clear()
        sampler_thread = threading.Thread(target=sampler_loop, daemon=True)
        sampler_thread.start()


def pause_sampler_for(seconds: float = 1.2):
    global sampler_pause_until_ts
    hold = max(0.0, seconds)
    sampler_pause_until_ts = max(sampler_pause_until_ts, time.time() + hold)


def mark_control_busy(seconds: float = 2.0):
    global control_busy_until_ts
    hold = max(0.0, seconds)
    control_busy_until_ts = max(control_busy_until_ts, time.time() + hold)


def in_control_busy_window() -> bool:
    return time.time() < control_busy_until_ts


def parse_confirmed_register_map(reg_map: dict):
    fields = {}

    for addr, meta in REGISTER_MAP_CONFIRMED.items():
        if addr not in reg_map:
            continue

        raw = reg_map[addr]
        value = to_signed_16(raw) if meta["signed"] else raw
        value = value * meta["scale"]
        fields[meta["name"]] = round(value, 3) if isinstance(value, float) else value

    if 0x0006 in reg_map and 0x0007 in reg_map:
        energy_raw = (reg_map[0x0007] << 16) | reg_map[0x0006]
        fields["energy_kwh"] = round(energy_raw / 1000, 3)

    return fields


def parse_bit_flags(value: int, width: int = 16):
    active_bits = []
    for bit in range(width):
        if value & (1 << bit):
            active_bits.append(bit)
    return active_bits


def parse_full_register_map(reg_map: dict):
    fields = {}
    missing_addrs = []

    for addr, meta in FULL_REGISTER_FIELD_MAP.items():
        if addr not in reg_map:
            missing_addrs.append(addr)
            continue

        raw = reg_map[addr]
        value = to_signed_16(raw) if meta["signed"] else raw
        value = value * meta["scale"]
        fields[meta["name"]] = round(value, 3) if isinstance(value, float) else value

    if 0x0006 in reg_map and 0x0007 in reg_map:
        energy_raw = (reg_map[0x0007] << 16) | reg_map[0x0006]
        fields["energy_kwh"] = round(energy_raw / 1000, 3)

    for key in ["alarm_status", "phase_alarm_bits", "device_status_bits", "total_alarm_bits"]:
        raw_val = fields.get(key)
        if isinstance(raw_val, int):
            fields[f"{key}_active_bits"] = parse_bit_flags(raw_val)

    return {
        "fields": fields,
        "missing_addrs": missing_addrs,
        "missing_addrs_hex": [f"0x{x:04X}" for x in missing_addrs],
    }


def read_full_realtime(port_name: str, baudrate: int, slave_id: int):
    blocks = []
    errors = []

    for group in FULL_READ_GROUPS:
        try:
            block = read_register_block(port_name, baudrate, slave_id, group["start"], group["count"])
            blocks.append({
                "name": group["name"],
                "desc": group["desc"],
                "start": group["start"],
                "count": group["count"],
                "block": block
            })
            time.sleep(0.03)
        except Exception as e:
            errors.append({
                "name": group["name"],
                "start": group["start"],
                "count": group["count"],
                "message": friendly_error(e)
            })

    if not blocks:
        # 所有扩展块都失败时，回退到已验证的实时主块，保证接口可用
        fallback_block = read_register_block(
            port_name,
            baudrate,
            slave_id,
            REALTIME_START_ADDR,
            REALTIME_REG_COUNT
        )
        blocks.append({
            "name": "fallback_realtime_main",
            "desc": "扩展区失败后的回退主块",
            "start": REALTIME_START_ADDR,
            "count": REALTIME_REG_COUNT,
            "block": fallback_block
        })

    reg_map = rebuild_register_map_from_groups(blocks)
    parsed = parse_full_register_map(reg_map)
    confirmed_fields = parse_confirmed_register_map(reg_map)

    return {
        "groups": blocks,
        "group_errors": errors,
        "register_map": {f"0x{k:04X}": v for k, v in sorted(reg_map.items())},
        "fields": parsed["fields"],
        "missing_addrs_hex": parsed["missing_addrs_hex"],
        "confirmed_fields": confirmed_fields,
        "alarms": parse_alarm_status(int(parsed["fields"].get("alarm_status", 0))),
        "timestamp": int(time.time()),
    }


def rebuild_register_map_from_groups(group_blocks):
    reg_map = {}
    for gb in group_blocks:
        start_addr = gb["block"]["start_addr"]
        regs = gb["block"]["registers"]
        for i, val in enumerate(regs):
            reg_map[start_addr + i] = val
    return reg_map


# =========================================================
# 控制逻辑
# =========================================================
def control_breaker(port_name: str, baudrate: int, slave_id: int, close_on: bool, coil_addr: int = DEFAULT_BREAKER_COIL_ADDR):
    request = build_write_coil_frame(slave_id, coil_addr, close_on)
    attempts = []
    max_attempts = 3

    for i in range(max_attempts):
        resp = send_frame(port_name, baudrate, request, read_size=32)
        attempt = {
            "attempt": i + 1,
            "request": request.hex(" ").upper(),
            "response": resp.hex(" ").upper() if resp else "",
            "response_len": len(resp) if resp else 0
        }

        if not resp:
            attempt["error"] = "控制无响应"
            attempts.append(attempt)
            time.sleep(0.08)
            continue

        if len(resp) < 8:
            attempt["error"] = "控制响应长度不足"
            attempts.append(attempt)
            time.sleep(0.08)
            continue

        if resp[0] != slave_id:
            attempt["error"] = f"控制响应从站地址不匹配，收到: {resp[0]}"
            attempts.append(attempt)
            time.sleep(0.08)
            continue

        if resp[1] & 0x80:
            code = resp[2] if len(resp) > 2 else None
            attempt["error"] = f"设备返回控制异常，功能码: 0x{resp[1]:02X}, 异常码: {code}"
            attempts.append(attempt)
            time.sleep(0.08)
            continue

        if resp[1] != 0x05:
            attempt["error"] = f"控制响应功能码错误，收到: {resp[1]}"
            attempts.append(attempt)
            time.sleep(0.08)
            continue

        if not check_crc(resp):
            attempt["error"] = "控制响应 CRC 校验失败"
            attempts.append(attempt)
            time.sleep(0.08)
            continue

        attempts.append(attempt)
        return {
            "action": "close" if close_on else "open",
            "coil_addr": coil_addr,
            "coil_addr_hex": f"0x{coil_addr:04X}",
            "request": request.hex(" ").upper(),
            "response": resp.hex(" ").upper(),
            "message": "合闸成功" if close_on else "分闸成功",
            "attempts": attempts
        }

    last_error = attempts[-1].get("error", "控制失败") if attempts else "控制失败"
    raise Exception(f"{last_error} | 尝试详情: {attempts}")


def write_single_register(port_name: str, baudrate: int, slave_id: int, reg_addr: int, value: int):
    request = build_write_single_register_frame(slave_id, reg_addr, value)
    resp = send_frame(port_name, baudrate, request, read_size=32)

    if not resp:
        raise Exception("写寄存器无响应")

    if len(resp) < 8:
        raise Exception("写寄存器响应长度不足")

    if resp[0] != slave_id:
        raise Exception(f"写寄存器响应从站地址不匹配，收到: {resp[0]}")

    if resp[1] & 0x80:
        code = resp[2] if len(resp) > 2 else None
        raise Exception(f"设备返回写寄存器异常，功能码: 0x{resp[1]:02X}, 异常码: {code}")

    if resp[1] != 0x06:
        raise Exception(f"写寄存器响应功能码错误，收到: {resp[1]}")

    if not check_crc(resp):
        raise Exception("写寄存器响应 CRC 校验失败")

    return {
        "reg_addr": reg_addr,
        "reg_addr_hex": f"0x{reg_addr:04X}",
        "value": value,
        "request": request.hex(" ").upper(),
        "response": resp.hex(" ").upper(),
        "hint": DOCUMENT_WRITE_REG_HINTS.get(reg_addr)
    }


# =========================================================
# 子模块映射（逐路激励 + 差分）
# =========================================================
def parse_coil_addr_list(text: str):
    addrs = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        addrs.append(int(token))
    if not addrs:
        raise Exception("线圈地址列表为空")
    return addrs


def snapshot_mapping_data(port_name: str, baudrate: int, slave_id: int, reg_start: int, reg_count: int, bit_count: int):
    holding = read_register_block(port_name, baudrate, slave_id, reg_start, reg_count)
    coils = read_bit_block(port_name, baudrate, slave_id, 0x01, 0, bit_count)
    discrete = read_bit_block(port_name, baudrate, slave_id, 0x02, 0, bit_count)
    return {
        "holding": holding["registers"],
        "coils": coils["bits"],
        "discrete": discrete["bits"],
        "timestamp": int(time.time())
    }


def compute_diff_indices(before_vals, after_vals):
    n = min(len(before_vals), len(after_vals))
    diff = []
    for i in range(n):
        if before_vals[i] != after_vals[i]:
            diff.append(i)
    return diff


def run_submodule_mapping(port_name: str, baudrate: int, slave_id: int, coil_addrs, reg_start: int, reg_count: int, settle_ms: int):
    results = []
    settle_s = max(0.2, settle_ms / 1000.0)

    for coil_addr in coil_addrs:
        # 每一路统一执行：分闸采样 -> 合闸采样 -> 分闸恢复
        control_breaker(port_name, baudrate, slave_id, close_on=False, coil_addr=coil_addr)
        time.sleep(settle_s)
        open_snap = snapshot_mapping_data(port_name, baudrate, slave_id, reg_start, reg_count, bit_count=32)

        control_breaker(port_name, baudrate, slave_id, close_on=True, coil_addr=coil_addr)
        time.sleep(settle_s)
        close_snap = snapshot_mapping_data(port_name, baudrate, slave_id, reg_start, reg_count, bit_count=32)

        control_breaker(port_name, baudrate, slave_id, close_on=False, coil_addr=coil_addr)
        time.sleep(0.2)

        holding_diff = compute_diff_indices(open_snap["holding"], close_snap["holding"])
        coils_diff = compute_diff_indices(open_snap["coils"], close_snap["coils"])
        discrete_diff = compute_diff_indices(open_snap["discrete"], close_snap["discrete"])

        results.append({
            "coil_addr": coil_addr,
            "coil_addr_hex": f"0x{coil_addr:04X}",
            "holding_changed_offsets": holding_diff,
            "holding_changed_addrs_hex": [f"0x{reg_start + i:04X}" for i in holding_diff],
            "coils_changed_offsets": coils_diff,
            "discrete_changed_offsets": discrete_diff,
            "open_snapshot": open_snap,
            "close_snapshot": close_snap,
        })

    candidates = []
    for item in results:
        if item["holding_changed_addrs_hex"]:
            candidates.append({
                "coil_addr": item["coil_addr"],
                "candidate_registers": item["holding_changed_addrs_hex"]
            })

    return {
        "mapping_strategy": "per-coil open/close differential",
        "reg_window": {
            "start": reg_start,
            "start_hex": f"0x{reg_start:04X}",
            "count": reg_count
        },
        "results": results,
        "candidate_mapping": candidates,
        "timestamp": int(time.time())
    }


# =========================================================
# 自动扫描
# =========================================================
def auto_scan_once():
    ports = [p.device for p in list_ports.comports()]
    baudrates = [9600, 19200, 4800, 38400]
    slave_ids = [1, 2, 3, 4, 5]

    priority = [(DEFAULT_PORT, DEFAULT_BAUDRATE, DEFAULT_SLAVE_ID)]
    tried = set(priority)

    for port, baud, slave in priority:
        try:
            data = read_realtime(port, baud, slave)
            return {"port": port, "baudrate": baud, "slave_id": slave, "data": data}
        except Exception as e:
            print(f"优先参数失败: {port}, {baud}, {slave}, {friendly_error(e)}")

    for port in ports:
        for baud in baudrates:
            for slave in slave_ids:
                key = (port, baud, slave)
                if key in tried:
                    continue
                try:
                    data = read_realtime(port, baud, slave)
                    return {"port": port, "baudrate": baud, "slave_id": slave, "data": data}
                except Exception as e:
                    print(f"扫描失败: {port}, {baud}, {slave}, {friendly_error(e)}")

    return None


# =========================================================
# API
# =========================================================
@app.get("/")
def root():
    return {
        "success": True,
        "message": "Dorm Power Backend Engineering Edition is running"
    }


@app.get("/api/status")
def api_status():
    return api_ok({
        "config": {
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "realtime_start_addr": f"0x{REALTIME_START_ADDR:04X}",
            "realtime_reg_count": REALTIME_REG_COUNT,
            "breaker_coil_addr": f"0x{DEFAULT_BREAKER_COIL_ADDR:04X}",
            "groups": REGISTER_GROUPS
        },
        "document_write_reg_hints": {
            f"0x{k:04X}": v for k, v in DOCUMENT_WRITE_REG_HINTS.items()
        },
        "control_mode": control_mode
    })


@app.get("/api/sampler/health")
def api_sampler_health():
    return api_ok({
        "thread_alive": bool(sampler_thread and sampler_thread.is_alive()),
        "last_success_ts": sampler_last_success_ts,
        "last_success_ms": int(sampler_last_success_ts * 1000) if sampler_last_success_ts else 0,
        "consecutive_failures": sampler_consecutive_failures,
        "total_failures": sampler_failure_count,
        "last_error": sampler_last_error,
        "backoff_seconds": sampler_backoff_s,
        "device_id": device_id,
    })


@app.get("/api/debug/current_calibration")
def api_debug_current_calibration(
    func_addr: int = Query(current_func_addr, description="电流功能地址，如 4/11/12/13/14"),
    switch_index: int = Query(current_switch_index, description="路号索引 0~3"),
    scale: float = Query(current_scale, description="比例因子，如 0.01"),
    reference_current_a: float = Query(None, description="可选参考电流(A)，用于误差评估"),
):
    """
    只读调试接口：返回电流计算全链路证据，便于现场校准。
    """
    global current_func_addr, current_switch_index, current_scale
    try:
        if func_addr < 0 or func_addr > 0xFF:
            return api_err("func_addr 必须在 0~255")
        if switch_index < 0 or switch_index > 15:
            return api_err("switch_index 必须在 0~15")
        if scale <= 0 or scale > 100:
            return api_err("scale 必须在 (0,100]")

        # 可配置参数即时生效（保持最小改动，不重构主链路）
        current_func_addr = int(func_addr)
        current_switch_index = int(switch_index)
        current_scale = float(scale)

        blk = read_guide_value_block(
            current_port,
            current_baudrate,
            current_slave_id,
            func_addr=current_func_addr,
            switch_start=0,
            switch_count=4
        )
        regs = blk.get("registers", [])
        raw = pick_switch_value(blk, current_switch_index)
        est = round(float(raw) * current_scale, 6)

        error_percent = None
        if reference_current_a is not None and abs(reference_current_a) > 1e-9:
            error_percent = round(abs(est - float(reference_current_a)) / abs(float(reference_current_a)) * 100.0, 4)

        return api_ok({
            "config": {
                "current_func_addr": current_func_addr,
                "current_switch_index": current_switch_index,
                "current_scale": current_scale,
            },
            "raw_block": {
                "start_addr_hex": blk.get("start_addr_hex"),
                "frame_type": blk.get("frame_type"),
                "registers": regs,
                "response": blk.get("response"),
            },
            "calculation": {
                "raw_value": raw,
                "formula": "current_a = raw_value * current_scale",
                "current_a_est": est,
                "reference_current_a": reference_current_a,
                "error_percent": error_percent,
                "pass_target_le_5_percent": (error_percent is not None and error_percent <= 5.0),
            },
        })
    except Exception as e:
        return api_err(friendly_error(e))


@app.get("/api/ports")
def api_ports():
    ports_info = []
    for p in list_ports.comports():
        ports_info.append({
            "device": p.device,
            "description": p.description,
            "hwid": p.hwid
        })
    return {"success": True, "ports": ports_info}


@app.get("/api/scan")
def api_scan():
    global current_port, current_baudrate, current_slave_id

    result = auto_scan_once()
    if not result:
        return {"success": False, "message": "未扫描到设备"}

    current_port = result["port"]
    current_baudrate = result["baudrate"]
    current_slave_id = result["slave_id"]

    return {
        "success": True,
        "message": "扫描成功",
        "port": current_port,
        "baudrate": current_baudrate,
        "slave_id": current_slave_id,
        "data": result["data"],
        "alarms": parse_alarm_status(result["data"]["alarm_status"])
    }


@app.get("/api/realtime")
def api_realtime():
    global current_port, current_baudrate, current_slave_id
    try:
        cached = latest_stream_payload.get("realtime")
        # 优先返回采样线程缓存，避免前端轮询被串口阻塞拖慢
        if cached:
            return {
                "success": True,
                "port": current_port,
                "baudrate": current_baudrate,
                "slave_id": current_slave_id,
                "data": cached,
                "alarms": parse_alarm_status(int(cached.get("alarm_status", 0))),
                "note": "using sampler cache"
            }
        if in_control_busy_window():
            return {
                "success": False,
                "message": "control busy and no cache available"
            }
        data = read_realtime(current_port, current_baudrate, current_slave_id)
        return {
            "success": True,
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "data": data,
            "alarms": parse_alarm_status(data["alarm_status"])
        }
    except Exception as e:
        return {"success": False, "message": friendly_error(e)}


@app.get("/api/registers/range")
def api_registers_range(
    start: int = Query(..., description="起始地址，如 0"),
    count: int = Query(..., description="寄存器数量，如 8")
):
    global current_port, current_baudrate, current_slave_id
    try:
        if count <= 0 or count > 125:
            return {"success": False, "message": "count 必须在 1~125 之间"}

        block = read_register_block(current_port, current_baudrate, current_slave_id, start, count)

        reg_map = {start + i: v for i, v in enumerate(block["registers"])}
        confirmed_fields = parse_confirmed_register_map(reg_map)

        return {
            "success": True,
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "data": block,
            "confirmed_fields": confirmed_fields,
            "alarms": parse_alarm_status(int(confirmed_fields.get("alarm_status", 0)))
        }
    except Exception as e:
        return {"success": False, "message": friendly_error(e)}


@app.get("/api/registers/input_range")
def api_input_registers_range(
    start: int = Query(..., description="起始地址，如 0"),
    count: int = Query(..., description="寄存器数量，如 6")
):
    global current_port, current_baudrate, current_slave_id
    try:
        if count <= 0 or count > 125:
            return {"success": False, "message": "count 必须在 1~125 之间"}

        block = read_register_block(
            current_port,
            current_baudrate,
            current_slave_id,
            start,
            count,
            function_code=0x04
        )
        reg_map = {start + i: v for i, v in enumerate(block["registers"])}
        return {
            "success": True,
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "data": block,
            "register_map": {f"0x{k:04X}": v for k, v in sorted(reg_map.items())}
        }
    except Exception as e:
        return {"success": False, "message": friendly_error(e)}


@app.get("/api/registers/guide03")
def api_guide03_read(
    func_addr: int = Query(..., description="手册功能地址，例如 0x08 传 8"),
    switch_start: int = Query(0, description="开关起始编号，例如 0"),
    switch_count: int = Query(4, description="开关数量，例如 4")
):
    """
    按《简易485通讯应用指南》2.2/2.3 的地址格式读取：
      帧 = [slave][03][func_addr][switch_start][count_hi][count_lo][crc]
    对应本后端 start_addr = (func_addr << 8) | switch_start
    """
    global current_port, current_baudrate, current_slave_id
    try:
        if func_addr < 0 or func_addr > 0xFF:
            return {"success": False, "message": "func_addr 必须在 0~255 之间"}
        if switch_start < 0 or switch_start > 0xFF:
            return {"success": False, "message": "switch_start 必须在 0~255 之间"}
        if switch_count <= 0 or switch_count > 125:
            return {"success": False, "message": "switch_count 必须在 1~125 之间"}

        start_addr = (func_addr << 8) | switch_start
        block = read_register_block(
            current_port,
            current_baudrate,
            current_slave_id,
            start_addr,
            switch_count,
            function_code=0x03
        )
        return {
            "success": True,
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "guide_format": {
                "func_addr_hex": f"0x{func_addr:02X}",
                "switch_start_hex": f"0x{switch_start:02X}",
                "switch_count": switch_count,
                "computed_start_addr_hex": f"0x{start_addr:04X}",
                "example_tx_no_crc": f"{current_slave_id:02X} 03 {func_addr:02X} {switch_start:02X} {switch_count >> 8:02X} {switch_count & 0xFF:02X}"
            },
            "data": block
        }
    except Exception as e:
        return {"success": False, "message": friendly_error(e)}


@app.get("/api/bits/coils")
def api_read_coils(
    start: int = Query(0, description="起始地址"),
    count: int = Query(6, description="读取位数量")
):
    global current_port, current_baudrate, current_slave_id
    try:
        if count <= 0 or count > 2000:
            return {"success": False, "message": "count 必须在 1~2000 之间"}
        data = read_bit_block(current_port, current_baudrate, current_slave_id, 0x01, start, count)
        return {
            "success": True,
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "data": data
        }
    except Exception as e:
        return {"success": False, "message": friendly_error(e)}


@app.get("/api/bits/discrete")
def api_read_discrete_inputs(
    start: int = Query(0, description="起始地址"),
    count: int = Query(6, description="读取位数量")
):
    global current_port, current_baudrate, current_slave_id
    try:
        if count <= 0 or count > 2000:
            return {"success": False, "message": "count 必须在 1~2000 之间"}
        data = read_bit_block(current_port, current_baudrate, current_slave_id, 0x02, start, count)
        return {
            "success": True,
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "data": data
        }
    except Exception as e:
        return {"success": False, "message": friendly_error(e)}


@app.post("/api/mapping/run")
def api_run_submodule_mapping(
    coils: str = Query("0,1,2,3,4,5", description="待激励线圈地址列表，逗号分隔"),
    reg_start: int = Query(8, description="寄存器窗口起始地址"),
    reg_count: int = Query(24, description="寄存器窗口长度"),
    settle_ms: int = Query(1200, description="动作后稳定等待毫秒")
):
    global current_port, current_baudrate, current_slave_id
    try:
        if reg_count <= 0 or reg_count > 125:
            return {"success": False, "message": "reg_count 必须在 1~125 之间"}
        if settle_ms < 100:
            return {"success": False, "message": "settle_ms 不能小于 100"}

        coil_addrs = parse_coil_addr_list(coils)
        data = run_submodule_mapping(
            current_port,
            current_baudrate,
            current_slave_id,
            coil_addrs=coil_addrs,
            reg_start=reg_start,
            reg_count=reg_count,
            settle_ms=settle_ms
        )
        return {
            "success": True,
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "data": data
        }
    except Exception as e:
        return {"success": False, "message": friendly_error(e)}


@app.get("/api/scan_holding")
def api_scan_holding(
    start: int = Query(0, description="起始地址，如 0"),
    end: int = Query(63, description="结束地址（包含），如 63"),
    block: int = Query(8, description="每次读取的块大小，如 8")
):
    """
    批量扫描保持寄存器，用于反向工程和状态位定位。
    可多次调用，在不同状态下（分闸/合闸）进行对比。
    """
    global current_port, current_baudrate, current_slave_id
    try:
        if start < 0 or end > 0xFFFF or start > end:
            return {"success": False, "message": "地址范围无效"}
        if block <= 0 or block > 125:
            return {"success": False, "message": "块大小必须在 1~125 之间"}

        blocks = []
        current_addr = start

        while current_addr <= end:
            read_count = min(block, end - current_addr + 1)
            
            try:
                print(f"扫描块：0x{current_addr:04X} ~ 0x{current_addr + read_count - 1:04X}")
                block_data = read_register_block(current_port, current_baudrate, current_slave_id, current_addr, read_count)
                
                blocks.append({
                    "start": current_addr,
                    "start_hex": f"0x{current_addr:04X}",
                    "count": read_count,
                    "registers": block_data["registers"],
                    "response": block_data["response"],
                    "crc_ok": block_data["crc_ok"],
                    "frame_type": block_data["frame_type"]
                })
                
                time.sleep(0.05)  # 避免串口过载
            except Exception as block_error:
                print(f"块读取失败 0x{current_addr:04X}: {friendly_error(block_error)}")
                blocks.append({
                    "start": current_addr,
                    "start_hex": f"0x{current_addr:04X}",
                    "count": read_count,
                    "error": friendly_error(block_error)
                })
            
            current_addr += read_count

        # 构建完整的寄存器映射
        full_reg_map = {}
        for b in blocks:
            if "registers" in b:
                for i, val in enumerate(b["registers"]):
                    full_reg_map[b["start"] + i] = val

        confirmed_fields = parse_confirmed_register_map(full_reg_map)

        return {
            "success": True,
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "scan_params": {
                "start": start,
                "start_hex": f"0x{start:04X}",
                "end": end,
                "end_hex": f"0x{end:04X}",
                "block_size": block,
                "total_regs_attempted": end - start + 1
            },
            "blocks": blocks,
            "register_map": {f"0x{k:04X}": v for k, v in sorted(full_reg_map.items())},
            "confirmed_fields": confirmed_fields,
            "alarms": parse_alarm_status(int(confirmed_fields.get("alarm_status", 0))),
            "timestamp": int(time.time())
        }
    except Exception as e:
        return {"success": False, "message": friendly_error(e)}


@app.get("/api/groups")
def api_groups():
    global current_port, current_baudrate, current_slave_id
    try:
        group_blocks = []
        for group in REGISTER_GROUPS:
            g = read_group(group["name"], current_port, current_baudrate, current_slave_id)
            group_blocks.append(g)
            time.sleep(0.03)

        reg_map = rebuild_register_map_from_groups(group_blocks)
        confirmed_fields = parse_confirmed_register_map(reg_map)

        return {
            "success": True,
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "groups": group_blocks,
            "register_map": {f"0x{k:04X}": v for k, v in sorted(reg_map.items())},
            "confirmed_fields": confirmed_fields,
            "alarms": parse_alarm_status(int(confirmed_fields.get("alarm_status", 0)))
        }
    except Exception as e:
        return {"success": False, "message": friendly_error(e)}


@app.get("/api/groups/{group_name}")
def api_group_detail(group_name: str):
    global current_port, current_baudrate, current_slave_id
    try:
        g = read_group(group_name, current_port, current_baudrate, current_slave_id)
        start = g["block"]["start_addr"]
        reg_map = {start + i: v for i, v in enumerate(g["block"]["registers"])}
        confirmed_fields = parse_confirmed_register_map(reg_map)

        return {
            "success": True,
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "group": g,
            "confirmed_fields": confirmed_fields,
            "alarms": parse_alarm_status(int(confirmed_fields.get("alarm_status", 0)))
        }
    except Exception as e:
        return {"success": False, "message": friendly_error(e)}


@app.get("/api/realtime/full")
def api_realtime_full():
    global current_port, current_baudrate, current_slave_id
    try:
        data = read_full_realtime(current_port, current_baudrate, current_slave_id)
        return {
            "success": True,
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "data": data,
        }
    except Exception as e:
        return {"success": False, "message": friendly_error(e)}


@app.post("/api/control/open")
def api_control_open(
    coil_addr: int = Query(DEFAULT_BREAKER_COIL_ADDR, description="线圈地址，如 0x0000 传 0"),
    operator: str = Query("unknown", description="操作者"),
    source: str = Query("web", description="来源"),
    idempotency_key: str = Query("", description="幂等键"),
    min_interval_ms: int = Query(1200, description="最小操作间隔")
):
    global current_port, current_baudrate, current_slave_id, last_control_at_ts
    try:
        if coil_addr < 0 or coil_addr > 0xFFFF:
            return api_err("coil_addr 必须在 0~65535 之间")
        allowed, reason = check_control_allowed(control_mode, "open")
        if not allowed:
            return api_err(reason, code=403)
        if (time.time() - last_control_at_ts) * 1000 < min_interval_ms:
            return api_err("操作过于频繁，请稍后重试", code=429)
        if idempotency_key and idempotency_key in last_control_by_key:
            return api_ok(last_control_by_key[idempotency_key], "idempotent replay")
        mark_control_busy(2.2)
        pause_sampler_for(1.5)
        result = control_breaker(
            current_port,
            current_baudrate,
            current_slave_id,
            close_on=False,
            coil_addr=coil_addr
        )
        last_control_at_ts = time.time()
        ack = {
            "ack_id": str(uuid.uuid4()),
            "action": "open",
            "coil_addr_hex": result["coil_addr_hex"],
            "response": result["response"],
            "success": True,
            "mode": control_mode,
        }
        recent_control_acks.append(ack)
        if idempotency_key:
            last_control_by_key[idempotency_key] = ack
        insert_strategy_action("control_open", f"coil:{result['coil_addr_hex']}", True, result["response"])
        insert_control_log(operator, source, "open", control_mode, idempotency_key, result["coil_addr_hex"], result["request"], result["response"], True, "")
        return api_ok({
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "ack": ack,
            "result": result
        })
    except Exception as e:
        insert_strategy_action("control_open", "coil:unknown", False, friendly_error(e))
        insert_control_log(operator, source, "open", control_mode, idempotency_key, f"0x{coil_addr:04X}", "", "", False, friendly_error(e))
        return api_err(friendly_error(e))


@app.post("/api/control/close")
def api_control_close(
    coil_addr: int = Query(DEFAULT_BREAKER_COIL_ADDR, description="线圈地址，如 0x0001 传 1"),
    operator: str = Query("unknown", description="操作者"),
    source: str = Query("web", description="来源"),
    idempotency_key: str = Query("", description="幂等键"),
    min_interval_ms: int = Query(1200, description="最小操作间隔")
):
    global current_port, current_baudrate, current_slave_id, last_control_at_ts
    try:
        if coil_addr < 0 or coil_addr > 0xFFFF:
            return api_err("coil_addr 必须在 0~65535 之间")
        allowed, reason = check_control_allowed(control_mode, "close")
        if not allowed:
            return api_err(reason, code=403)
        if (time.time() - last_control_at_ts) * 1000 < min_interval_ms:
            return api_err("操作过于频繁，请稍后重试", code=429)
        if idempotency_key and idempotency_key in last_control_by_key:
            return api_ok(last_control_by_key[idempotency_key], "idempotent replay")
        mark_control_busy(2.2)
        pause_sampler_for(1.5)
        result = control_breaker(
            current_port,
            current_baudrate,
            current_slave_id,
            close_on=True,
            coil_addr=coil_addr
        )
        last_control_at_ts = time.time()
        ack = {
            "ack_id": str(uuid.uuid4()),
            "action": "close",
            "coil_addr_hex": result["coil_addr_hex"],
            "response": result["response"],
            "success": True,
            "mode": control_mode,
        }
        recent_control_acks.append(ack)
        if idempotency_key:
            last_control_by_key[idempotency_key] = ack
        insert_strategy_action("control_close", f"coil:{result['coil_addr_hex']}", True, result["response"])
        insert_control_log(operator, source, "close", control_mode, idempotency_key, result["coil_addr_hex"], result["request"], result["response"], True, "")
        return api_ok({
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "ack": ack,
            "result": result
        })
    except Exception as e:
        insert_strategy_action("control_close", "coil:unknown", False, friendly_error(e))
        insert_control_log(operator, source, "close", control_mode, idempotency_key, f"0x{coil_addr:04X}", "", "", False, friendly_error(e))
        return api_err(friendly_error(e))


@app.post("/api/write/register")
def api_write_register(
    addr: int = Query(..., description="寄存器地址"),
    value: int = Query(..., description="写入值")
):
    global current_port, current_baudrate, current_slave_id
    try:
        result = write_single_register(current_port, current_baudrate, current_slave_id, addr, value)
        insert_strategy_action("write_register", f"reg:0x{addr:04X}", True, f"value={value}")
        return {
            "success": True,
            "warning": "写参数前请确认文档和现场设备允许该地址写入",
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "data": result
        }
    except Exception as e:
        insert_strategy_action("write_register", f"reg:0x{addr:04X}", False, friendly_error(e))
        return {"success": False, "message": friendly_error(e)}


@app.get("/api/metrics/summary")
def api_metrics_summary(hours: int = Query(24, description="统计最近小时数")):
    try:
        if hours <= 0 or hours > 24 * 30:
            return {"success": False, "message": "hours 必须在 1~720 之间"}
        with db_lock:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(AVG(power_w), 0),
                    COALESCE(SUM(co2_kg_per_hour) / 3600.0, 0),
                    COALESCE(MAX(power_w), 0),
                    COALESCE(MIN(power_w), 0)
                FROM realtime_records
                WHERE created_at >= datetime('now', ?)
                """,
                (f"-{hours} hours",),
            )
            row = cur.fetchone()
            cur.execute(
                "SELECT COUNT(*) FROM alarm_events WHERE created_at >= datetime('now', ?)",
                (f"-{hours} hours",),
            )
            alarm_count = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM strategy_actions WHERE created_at >= datetime('now', ?)",
                (f"-{hours} hours",),
            )
            strategy_count = cur.fetchone()[0]
            cur.close()
            conn.close()

        sample_count, avg_power, co2_kg_total, max_power, min_power = row
        baseline_power = max(avg_power * 1.2, avg_power + 50)
        energy_saving_rate = 0.0
        if baseline_power > 0:
            energy_saving_rate = round(max(0.0, (baseline_power - avg_power) / baseline_power * 100), 2)

        return api_ok({
            "window_hours": hours,
            "sample_count": sample_count,
            "avg_power_w": round(avg_power, 3),
            "max_power_w": round(max_power, 3),
            "min_power_w": round(min_power, 3),
            "co2_kg_total": round(co2_kg_total, 4),
            "alarm_count": alarm_count,
            "strategy_action_count": strategy_count,
            "estimated_energy_saving_rate_percent": energy_saving_rate,
        })
    except Exception as e:
        return api_err(friendly_error(e))


@app.get("/api/metrics/aggregate")
def api_metrics_aggregate(
    granularity: str = Query("minute", description="minute/hour"),
    hours: int = Query(24, description="lookback hours"),
):
    try:
        if granularity not in ("minute", "hour"):
            return api_err("granularity 必须为 minute 或 hour")
        bucket_fmt = "%Y-%m-%d %H:%M" if granularity == "minute" else "%Y-%m-%d %H"
        with db_lock:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT strftime('{bucket_fmt}', created_at) AS bucket,
                       COUNT(*) AS sample_count,
                       COALESCE(AVG(power_w), 0),
                       COALESCE(AVG(voltage_v), 0),
                       COALESCE(AVG(current_a), 0),
                       COALESCE(SUM(co2_kg_per_hour)/3600.0, 0)
                FROM realtime_records
                WHERE created_at >= datetime('now', ?)
                GROUP BY bucket
                ORDER BY bucket ASC
                """,
                (f"-{hours} hours",),
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()
        data = [
            {
                "bucket": r[0],
                "sample_count": r[1],
                "avg_power_w": round(r[2], 3),
                "avg_voltage_v": round(r[3], 3),
                "avg_current_a": round(r[4], 3),
                "co2_kg": round(r[5], 6),
            }
            for r in rows
        ]
        return api_ok({"granularity": granularity, "hours": hours, "items": data})
    except Exception as e:
        return api_err(friendly_error(e))


@app.get("/api/config/carbon_factor")
def api_get_carbon_factor():
    return api_ok({"carbon_factor_kg_per_kwh": carbon_factor_kg_per_kwh})


@app.post("/api/config/carbon_factor")
def api_set_carbon_factor(value: float = Query(..., description="kg/kWh")):
    global carbon_factor_kg_per_kwh
    if value <= 0 or value > 5:
        return api_err("碳排因子范围无效")
    carbon_factor_kg_per_kwh = float(value)
    return api_ok({"carbon_factor_kg_per_kwh": carbon_factor_kg_per_kwh}, "updated")


def check_control_allowed(mode: str, action: str):
    if mode == "protect" and action == "close":
        return False, "保护模式下禁止合闸"
    return True, ""


@app.get("/api/control/mode")
def api_get_control_mode():
    return api_ok({"mode": control_mode})


@app.post("/api/control/mode")
def api_set_control_mode(mode: str = Query(..., description="manual/auto/protect")):
    global control_mode
    if mode not in ("manual", "auto", "protect"):
        return api_err("mode 必须是 manual/auto/protect")
    control_mode = mode
    insert_strategy_action("set_control_mode", "system", True, mode)
    return api_ok({"mode": control_mode}, "mode updated")


@app.get("/api/readable/summary")
def api_readable_summary():
    """
    整合当前“可读到”的核心数据，供前端一次拉取展示。
    """
    global current_port, current_baudrate, current_slave_id
    now_ts = int(time.time())
    if readable_summary_cache.get("timestamp", 0) and now_ts - int(readable_summary_cache.get("timestamp", 0)) <= 3:
        cached = dict(readable_summary_cache)
        cached["cache_hit"] = True
        return cached
    # 控制窗口内避免新增串口读请求，降低分/合闸写线圈与轮询抢占导致的失败概率。
    if in_control_busy_window():
        cached = dict(readable_summary_cache)
        if cached:
            cached["cache_hit"] = True
            cached["note"] = "control busy, using cache"
            return cached
        return {
            "success": False,
            "message": "control busy and no readable cache available",
            "cache_hit": False,
            "timestamp": now_ts
        }

    result = {
        "success": True,
        "port": current_port,
        "baudrate": current_baudrate,
        "slave_id": current_slave_id,
        "timestamp": now_ts,
        "realtime": latest_stream_payload.get("realtime"),
        "input_registers_0x0000_0x0005": None,
        "guide03_blocks": {},
        "coils": None,
        "discrete_inputs": None,
        "errors": {},
        "cache_hit": False,
    }
    try:
        block = read_register_block(
            current_port, current_baudrate, current_slave_id, 0, 6, function_code=0x04
        )
        result["input_registers_0x0000_0x0005"] = block["registers"]
    except Exception as e:
        result["errors"]["input_registers_0x0000_0x0005"] = friendly_error(e)

    guide_funcs = {
        "total_voltage": 0x00,
        "current": 0x04,
        "switch_state": 0x15,
        "total_alarm_bits": 0x31,
    }
    for name, func_addr in guide_funcs.items():
        try:
            blk = read_guide_value_block(
                current_port, current_baudrate, current_slave_id, func_addr=func_addr, switch_count=4
            )
            result["guide03_blocks"][name] = {
                "func_addr_hex": f"0x{func_addr:02X}",
                "registers": blk["registers"],
                "response": blk["response"],
            }
        except Exception as e:
            result["errors"][f"guide03_{name}"] = friendly_error(e)

    try:
        result["coils"] = read_bit_block(current_port, current_baudrate, current_slave_id, 0x01, 0, 16)
    except Exception as e:
        result["errors"]["coils"] = friendly_error(e)

    try:
        result["discrete_inputs"] = read_bit_block(current_port, current_baudrate, current_slave_id, 0x02, 0, 16)
    except Exception as e:
        result["errors"]["discrete_inputs"] = friendly_error(e)

    readable_summary_cache.clear()
    readable_summary_cache.update(result)
    return result


@app.get("/api/control/logs")
def api_control_logs(limit: int = Query(50, description="最近记录条数")):
    try:
        with db_lock:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, created_at, operator, source, action, mode, idempotency_key, coil_addr, success, reason
                FROM control_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, min(200, limit)),),
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()
        items = [
            {
                "id": r[0],
                "created_at": r[1],
                "operator": r[2],
                "source": r[3],
                "action": r[4],
                "mode": r[5],
                "idempotency_key": r[6],
                "coil_addr": r[7],
                "success": bool(r[8]),
                "reason": r[9],
            }
            for r in rows
        ]
        return api_ok({"items": items})
    except Exception as e:
        return api_err(friendly_error(e))


@app.get("/api/nilm/events")
def api_nilm_events(limit: int = Query(50, description="最近识别事件条数")):
    try:
        with db_lock:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, created_at, event_type, step_w, risk_score, label, detail
                FROM nilm_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, min(200, limit)),),
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()
        items = [
            {
                "id": r[0],
                "created_at": r[1],
                "event_type": r[2],
                "step_w": r[3],
                "risk_score": r[4],
                "label": r[5],
                "detail": r[6],
            }
            for r in rows
        ]
        return api_ok({"items": items})
    except Exception as e:
        return api_err(friendly_error(e))


@app.get("/api/dashboard/overview")
def api_dashboard_overview():
    rt = latest_stream_payload.get("realtime") or {}
    return api_ok({
        "device_id": rt.get("device_id", device_id),
        "quality_flag": rt.get("quality_flag", "unknown"),
        "timestamp_ms": rt.get("timestamp_ms", int(time.time() * 1000)),
        "voltage_v": rt.get("voltage_v", 0),
        "current_a": rt.get("current_a", 0),
        "power_w": rt.get("power_w", 0),
        "co2_kg_per_hour": latest_stream_payload.get("co2_kg_per_hour", 0),
        "sampler_health": {
            "alive": bool(sampler_thread and sampler_thread.is_alive()),
            "consecutive_failures": sampler_consecutive_failures,
        }
    })


@app.get("/api/dashboard/realtime_trend")
def api_dashboard_realtime_trend(hours: int = Query(1, description="窗口小时数")):
    try:
        with db_lock:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT created_at, power_w, voltage_v, current_a
                FROM realtime_records
                WHERE created_at >= datetime('now', ?)
                ORDER BY id ASC
                """,
                (f"-{hours} hours",),
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()
        return api_ok({
            "hours": hours,
            "items": [
                {
                    "ts": r[0],
                    "power_w": r[1],
                    "voltage_v": r[2],
                    "current_a": r[3],
                }
                for r in rows
            ]
        })
    except Exception as e:
        return api_err(friendly_error(e))


@app.get("/api/dashboard/carbon_wall")
def api_dashboard_carbon_wall():
    try:
        with db_lock:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COALESCE(SUM(co2_kg_per_hour)/3600.0,0)
                FROM realtime_records
                WHERE created_at >= datetime('now', 'start of day')
                """
            )
            today = float(cur.fetchone()[0] or 0.0)
            cur.execute(
                """
                SELECT COALESCE(SUM(co2_kg_per_hour)/3600.0,0)
                FROM realtime_records
                """
            )
            total = float(cur.fetchone()[0] or 0.0)
            cur.close()
            conn.close()
        baseline = total * 1.15
        reduced = max(0.0, baseline - total)
        equivalent_trees = round(total / 18.3, 3) if total > 0 else 0.0
        return api_ok({
            "today_co2_kg": round(today, 4),
            "total_co2_kg": round(total, 4),
            "estimated_reduction_kg": round(reduced, 4),
            "equivalent_trees": equivalent_trees,
            "carbon_factor_kg_per_kwh": carbon_factor_kg_per_kwh,
        })
    except Exception as e:
        return api_err(friendly_error(e))


@app.get("/api/dashboard/alarm_timeline")
def api_dashboard_alarm_timeline(limit: int = Query(100, description="最近告警数量")):
    try:
        with db_lock:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, created_at, alarm_status, message
                FROM alarm_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, min(500, limit)),),
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()
        return api_ok({
            "items": [
                {
                    "id": r[0],
                    "created_at": r[1],
                    "alarm_status": r[2],
                    "message": r[3],
                    "level": "high" if int(r[2]) > 0 else "info",
                }
                for r in rows
            ]
        })
    except Exception as e:
        return api_err(friendly_error(e))


@app.get("/api/dashboard/strategy_panel")
def api_dashboard_strategy_panel():
    return api_ok({
        "mode": control_mode,
        "nilm": {
            "risk_score": last_nilm_score,
            "label": last_nilm_label,
        },
        "idle_governance": {
            "idle_start_ts": last_strategy_state.get("idle_start_ts", 0),
            "last_auto_cut_ts": last_strategy_state.get("last_auto_cut_ts", 0),
        },
        "last_control_ack": recent_control_acks[-1] if recent_control_acks else None,
    })


@app.websocket("/ws/realtime")
async def websocket_realtime(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            payload = {
                "timestamp": int(time.time()),
                "realtime": latest_stream_payload.get("realtime"),
                "alarm": latest_stream_payload.get("alarm", {"active": []}),
                "strategy": latest_stream_payload.get("strategy", {}),
                "control_ack": recent_control_acks[-1] if recent_control_acks else None,
                "topics": ["realtime", "alarm", "strategy", "control_ack"],
            }
            await ws.send_json(payload)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
    except Exception:
        return


@app.get("/api/document/hints")
def api_document_hints():
    return {
        "success": True,
        "summary": {
            "protocol": "RS485 / Modbus RTU",
            "default_baudrate": 9600,
            "supported_baudrate_hint": [9600, 19200],
            "parity": "N",
            "stopbits": 1,
            "default_slave_id": 1,
            "function_codes": {
                "01": "读线圈",
                "02": "读离散量输入",
                "03": "读保持寄存器/实时数据/告警数据",
                "04": "读输入寄存器/参数区",
                "05": "写单个线圈（分合闸）",
                "06": "写单个寄存器（参数设置）"
            }
        },
        "write_register_hints": {
            f"0x{k:04X}": v for k, v in DOCUMENT_WRITE_REG_HINTS.items()
        },
        "engineering_notes": [
            "现场实测读响应存在 echo_addr 格式：01 03 [addr_hi] [addr_lo] [byte_count] [data] CRC",
            "实时主块建议固定读取 0x0000 开始的 8 个寄存器",
            "不要长期使用滑动窗口全地址扫描，建议按组读取",
            "前端优先展示已确认字段：电压、漏电流、功率、温度、电流、告警、电量"
        ]
    }


@app.on_event("startup")
def on_startup():
    init_db()
    ensure_sampler_started()


@app.on_event("shutdown")
def on_shutdown():
    sampler_stop_event.set()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)