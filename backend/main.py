import time
import serial
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from serial.tools import list_ports

app = FastAPI(title="Dorm Power Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# 已确认参数
# =========================
DEFAULT_PORT = "COM7"
DEFAULT_BAUDRATE = 9600
DEFAULT_SLAVE_ID = 1
TIMEOUT = 1.0
START_ADDR = 0x0000
REG_COUNT = 0x0008

current_port = DEFAULT_PORT
current_baudrate = DEFAULT_BAUDRATE
current_slave_id = DEFAULT_SLAVE_ID


# =========================
# 基础工具
# =========================
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
    crc_recv = resp[-2:]
    crc_calc = crc16_modbus(body)
    return crc_recv == crc_calc


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


def to_signed_16(value: int) -> int:
    return value - 0x10000 if value >= 0x8000 else value


def parse_words(data: bytes):
    if len(data) % 2 != 0:
        return []
    return [(data[i] << 8) | data[i + 1] for i in range(0, len(data), 2)]


def parse_alarm_status(alarm_status: int):
    alarms = []
    if alarm_status == 0:
        return alarms

    for bit in range(16):
        if alarm_status & (1 << bit):
            alarms.append({
                "id": bit,
                "type": "设备告警",
                "message": f"告警位 bit{bit} 触发",
                "time": time.strftime("%Y-%m-%d %H:%M:%S")
            })
    return alarms


def calc_co2_emission(power_w: float) -> float:
    # 按你现有项目逻辑保留
    return round((power_w / 3600 / 1000) * 570.3, 4)


# =========================
# 响应解析
# =========================
def parse_response(resp: bytes, slave_id: int):
    if not resp or len(resp) < 7:
        raise Exception("响应为空或长度过短")

    if resp[0] != slave_id:
        raise Exception(f"从站地址不匹配，收到: {resp[0]}")

    if resp[1] == 0x83:
        if len(resp) >= 3:
            code = resp[2]
            raise Exception(f"设备返回异常码: 0x{code:02X}")
        raise Exception("设备返回异常响应")

    if resp[1] != 0x03:
        raise Exception(f"功能码异常，收到: {resp[1]}")

    crc_ok = check_crc(resp)

    # 兼容三种格式：
    # 1) 标准:   01 03 10 [16字节数据] CRC
    # 2) 变种A:  01 03 00 10 [16字节数据] CRC
    # 3) 变种B:  01 03 00 00 10 [16字节数据] CRC
    if resp[2] != 0x00:
        byte_count = resp[2]
        data = resp[3:3 + byte_count]
        frame_type = "standard"
    elif len(resp) >= 5 and resp[3] != 0x00:
        byte_count = resp[3]
        data = resp[4:4 + byte_count]
        frame_type = "variant_a"
    else:
        if len(resp) < 6:
            raise Exception("变种响应长度不足")
        byte_count = resp[4]
        data = resp[5:5 + byte_count]
        frame_type = "variant_b"

    if len(data) < 16:
        raise Exception(f"数据区长度不足: {len(data)}")

    regs = parse_words(data[:16])
    if len(regs) < 8:
        raise Exception("寄存器数量不足")

    # 映射关系按你当前设备验证结果
    voltage_v = float(regs[0])
    leakage_current_ma = round(regs[1] * 0.1, 2)
    power_w = float(regs[2])
    temperature_c = float(to_signed_16(regs[3]) / 10)
    current_a = float(regs[4] / 100)
    alarm_status = int(regs[5])
    energy_raw = (regs[7] << 16) | regs[6]
    energy_kwh = float(energy_raw / 1000)

    return {
        "frame_type": frame_type,
        "crc_ok": crc_ok,
        "raw_response": resp.hex(" ").upper(),
        "raw_registers": regs,
        "voltage_v": voltage_v,
        "leakage_current_ma": leakage_current_ma,
        "power_w": power_w,
        "temperature_c": temperature_c,
        "current_a": current_a,
        "alarm_status": alarm_status,
        "energy_kwh": energy_kwh,
        "breaker_on": power_w > 0,
        "co2_emission_g_s": calc_co2_emission(power_w),
        "timestamp": int(time.time())
    }


# =========================
# 串口通信
# =========================
def read_device(port_name: str, baudrate: int, slave_id: int):
    request = build_read_frame(slave_id, START_ADDR, REG_COUNT)

    print("=" * 80)
    print("串口读取开始")
    print("端口:", port_name)
    print("波特率:", baudrate)
    print("从站地址:", slave_id)
    print("发送报文:", request.hex(" ").upper())

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
        time.sleep(0.1)

        ser.write(request)
        ser.flush()

        time.sleep(0.3)
        resp = ser.read(128)

    print("接收报文:", resp.hex(" ").upper() if resp else "<空>")

    return parse_response(resp, slave_id)


def auto_scan_once():
    ports = [p.device for p in list_ports.comports()]
    baudrates = [9600, 19200, 4800, 38400]
    slave_ids = [1, 2, 3, 4, 5]

    priority = [(DEFAULT_PORT, DEFAULT_BAUDRATE, DEFAULT_SLAVE_ID)]
    tried = set(priority)

    for port, baud, slave in priority:
        try:
            data = read_device(port, baud, slave)
            return {
                "port": port,
                "baudrate": baud,
                "slave_id": slave,
                "data": data
            }
        except Exception as e:
            print(f"优先参数失败: {port}, {baud}, {slave}, {e}")

    for port in ports:
        for baud in baudrates:
            for slave in slave_ids:
                key = (port, baud, slave)
                if key in tried:
                    continue
                try:
                    data = read_device(port, baud, slave)
                    return {
                        "port": port,
                        "baudrate": baud,
                        "slave_id": slave,
                        "data": data
                    }
                except Exception as e:
                    print(f"扫描失败: {port}, {baud}, {slave}, {e}")
                    continue

    return None


# =========================
# API
# =========================
@app.get("/")
def root():
    return {
        "success": True,
        "message": "Dorm Power Backend is running"
    }


@app.get("/api/status")
def api_status():
    return {
        "success": True,
        "config": {
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "start_addr": START_ADDR,
            "reg_count": REG_COUNT
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

    return {
        "success": True,
        "ports": ports_info
    }


@app.get("/api/test")
def api_test():
    global current_port, current_baudrate, current_slave_id

    try:
        request = build_read_frame(current_slave_id, START_ADDR, REG_COUNT)
        data = read_device(current_port, current_baudrate, current_slave_id)
        return {
            "success": True,
            "message": "测试读取成功",
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "request": request.hex(" ").upper(),
            "data": data
        }
    except Exception as e:
        return {
            "success": False,
            "message": str(e),
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id
        }


@app.get("/api/realtime")
def api_realtime():
    global current_port, current_baudrate, current_slave_id

    try:
        data = read_device(current_port, current_baudrate, current_slave_id)
        return {
            "success": True,
            "port": current_port,
            "baudrate": current_baudrate,
            "slave_id": current_slave_id,
            "data": data,
            "alarms": parse_alarm_status(data["alarm_status"])
        }
    except Exception as e:
        return {
            "success": False,
            "message": str(e)
        }


@app.get("/api/scan")
def api_scan():
    global current_port, current_baudrate, current_slave_id

    result = auto_scan_once()
    if not result:
        return {
            "success": False,
            "message": "未扫描到设备"
        }

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


@app.post("/api/control/open")
def api_control_open():
    return {
        "success": False,
        "message": "暂未实现分闸控制，请确认协议中的写线圈/写寄存器地址"
    }


@app.post("/api/control/close")
def api_control_close():
    return {
        "success": False,
        "message": "暂未实现合闸控制，请确认协议中的写线圈/写寄存器地址"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)