import time
import threading
import serial
from fastapi import FastAPI, Query
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
def build_read_frame(slave_id: int, start_addr: int, count: int) -> bytes:
    frame = bytes([
        slave_id,
        0x03,
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
def parse_read_response(resp: bytes, slave_id: int):
    """
    工程版解析器，兼容：
    1) 标准 Modbus:
       01 03 [byte_count] [data...] CRC

    2) 厂家 echo_addr 格式:
       01 03 [addr_hi] [addr_lo] [byte_count] [data...] CRC

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

    if resp[1] != 0x03:
        raise Exception(f"功能码异常，收到: {resp[1]}")

    if not check_crc(resp):
        raise Exception("CRC 校验失败")

    frame_type = "unknown"
    echoed_addr = None
    byte_count = 0
    data_start = 0

    # 标准格式：01 03 0C [data] CRC
    if resp[2] != 0x00:
        frame_type = "standard"
        byte_count = resp[2]
        data_start = 3

    # 厂家格式：01 03 00 08 0C [data] CRC
    else:
        if len(resp) < 8:
            raise Exception("地址回显格式长度不足")
        frame_type = "echo_addr"
        echoed_addr = (resp[2] << 8) | resp[3]
        byte_count = resp[4]
        data_start = 5

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
def read_register_block(port_name: str, baudrate: int, slave_id: int, start_addr: int, reg_count: int):
    request = build_read_frame(slave_id, start_addr, reg_count)
    resp = send_frame(port_name, baudrate, request, read_size=128)
    parsed = parse_read_response(resp, slave_id)

    return {
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


def read_realtime(port_name: str, baudrate: int, slave_id: int):
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
    resp = send_frame(port_name, baudrate, request, read_size=32)

    if not resp:
        raise Exception("控制无响应")

    if len(resp) < 8:
        raise Exception("控制响应长度不足")

    if resp[0] != slave_id:
        raise Exception(f"控制响应从站地址不匹配，收到: {resp[0]}")

    if resp[1] & 0x80:
        code = resp[2] if len(resp) > 2 else None
        raise Exception(f"设备返回控制异常，功能码: 0x{resp[1]:02X}, 异常码: {code}")

    if resp[1] != 0x05:
        raise Exception(f"控制响应功能码错误，收到: {resp[1]}")

    if not check_crc(resp):
        raise Exception("控制响应 CRC 校验失败")

    return {
        "action": "close" if close_on else "open",
        "coil_addr": coil_addr,
        "coil_addr_hex": f"0x{coil_addr:04X}",
        "request": request.hex(" ").upper(),
        "response": resp.hex(" ").upper(),
        "message": "合闸成功" if close_on else "分闸成功"
    }


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
    return {
        "success": True,
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
        }
    }


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


@app.post("/api/control/open")
def api_control_open():
    global current_port, current_baudrate, current_slave_id
    try:
        result = control_breaker(current_port, current_baudrate, current_slave_id, close_on=False)
        return {
            "success": True,
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "data": result
        }
    except Exception as e:
        return {"success": False, "message": friendly_error(e)}


@app.post("/api/control/close")
def api_control_close():
    global current_port, current_baudrate, current_slave_id
    try:
        result = control_breaker(current_port, current_baudrate, current_slave_id, close_on=True)
        return {
            "success": True,
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "data": result
        }
    except Exception as e:
        return {"success": False, "message": friendly_error(e)}


@app.post("/api/write/register")
def api_write_register(
    addr: int = Query(..., description="寄存器地址"),
    value: int = Query(..., description="写入值")
):
    global current_port, current_baudrate, current_slave_id
    try:
        result = write_single_register(current_port, current_baudrate, current_slave_id, addr, value)
        return {
            "success": True,
            "warning": "写参数前请确认文档和现场设备允许该地址写入",
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "data": result
        }
    except Exception as e:
        return {"success": False, "message": friendly_error(e)}


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)