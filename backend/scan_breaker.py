import time
import serial
from serial.tools import list_ports

# 可扫描参数
BAUDRATES = [19200, 9600, 4800, 38400]
SLAVE_IDS = range(1, 6)   # 先扫 1~5，后面可改成 range(1, 248)
START_ADDR = 0x0000
REG_COUNT = 0x0008
TIMEOUT = 0.5

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

def parse_response(resp: bytes, slave_id: int):
    if not resp or len(resp) < 7:
        return None

    if resp[0] != slave_id or resp[1] != 0x03:
        return None

    # 兼容三种格式：
    # 1) 标准:   01 03 10 [16字节数据] CRC
    # 2) 变种A:  01 03 00 10 [16字节数据] CRC
    # 3) 变种B:  01 03 00 00 10 [16字节数据] CRC   <- 你目前遇到的
    if resp[2] != 0x00:
        byte_count = resp[2]
        data = resp[3:3 + byte_count]
        frame_type = "标准Modbus"
    elif len(resp) >= 5 and resp[3] != 0x00:
        byte_count = resp[3]
        data = resp[4:4 + byte_count]
        frame_type = "厂商变种A"
    else:
        if len(resp) < 6:
            return None
        byte_count = resp[4]
        data = resp[5:5 + byte_count]
        frame_type = "厂商变种B"

    if len(data) < 16:
        return None

    regs = parse_words(data[:16])
    if len(regs) < 8:
        return None

    voltage_v = regs[0]
    leakage_current_ma = regs[1] * 0.1
    power_w = regs[2]
    temperature_c = to_signed_16(regs[3]) / 10
    current_a = regs[4] / 100
    alarm_status = regs[5]
    energy_raw = (regs[7] << 16) | regs[6]
    energy_kwh = energy_raw / 1000

    return {
        "frame_type": frame_type,
        "raw_response": resp.hex(" ").upper(),
        "registers": regs,
        "voltage_v": voltage_v,
        "leakage_current_ma": leakage_current_ma,
        "power_w": power_w,
        "temperature_c": temperature_c,
        "current_a": current_a,
        "alarm_status": alarm_status,
        "energy_kwh": energy_kwh,
    }

def try_read(port_name: str, baudrate: int, slave_id: int):
    request = build_read_frame(slave_id, START_ADDR, REG_COUNT)

    try:
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
            ser.write(request)
            time.sleep(0.2)
            resp = ser.read(64)

        result = parse_response(resp, slave_id)
        if result:
            return result
        return None

    except Exception:
        return None

def scan_all():
    ports = [p.device for p in list_ports.comports()]
    if not ports:
        print("未发现任何串口设备")
        return

    print("发现串口:", ports)
    print("-" * 60)

    found = []

    for port in ports:
        for baud in BAUDRATES:
            for slave in SLAVE_IDS:
                print(f"尝试: 端口={port}, 波特率={baud}, 地址={slave}")
                result = try_read(port, baud, slave)
                if result:
                    print("\n✅ 找到设备！")
                    print(f"端口: {port}")
                    print(f"波特率: {baud}")
                    print(f"地址: {slave}")
                    print(f"响应格式: {result['frame_type']}")
                    print(f"原始响应: {result['raw_response']}")
                    print(f"原始寄存器: {result['registers']}")
                    print(f"电压: {result['voltage_v']} V")
                    print(f"漏电电流: {result['leakage_current_ma']} mA")
                    print(f"功率: {result['power_w']} W")
                    print(f"温度: {result['temperature_c']} ℃")
                    print(f"电流: {result['current_a']} A")
                    print(f"告警状态: {result['alarm_status']}")
                    print(f"累计电量: {result['energy_kwh']} kWh")
                    print("-" * 60)

                    found.append({
                        "port": port,
                        "baudrate": baud,
                        "slave_id": slave,
                        "data": result
                    })

    if not found:
        print("\n❌ 未扫描到可用设备")
        print("请检查：")
        print("1. 串口号是否正确")
        print("2. 485 A/B 是否接反")
        print("3. 设备是否上电")
        print("4. 波特率是否被改过")
        print("5. 从站地址是否不是 1~5")
    else:
        print(f"\n扫描完成，共发现 {len(found)} 个匹配结果")

if __name__ == "__main__":
    scan_all()