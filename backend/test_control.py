import serial
import time


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


def build_write_coil_frame(slave_id: int, coil_addr: int, on: bool) -> bytes:
    value_hi = 0xFF if on else 0x00
    value_lo = 0x00
    frame = bytes([
        slave_id,
        0x05,
        (coil_addr >> 8) & 0xFF,
        coil_addr & 0xFF,
        value_hi,
        value_lo
    ])
    return frame + crc16_modbus(frame)


def send_command(port: str, baudrate: int, frame: bytes, timeout=1.0):
    print("准备打开串口...")
    print("发送:", frame.hex(" ").upper())

    ser = serial.Serial(
        port=port,
        baudrate=baudrate,
        bytesize=8,
        parity='N',
        stopbits=1,
        timeout=timeout,
        write_timeout=1
    )

    try:
        print("串口已打开")
        ser.reset_input_buffer()
        print("已清空输入缓冲区")
        ser.reset_output_buffer()
        print("已清空输出缓冲区")

        print("开始 write...")
        n = ser.write(frame)
        print(f"write 完成，写入 {n} 字节")

        print("开始 flush...")
        ser.flush()
        print("flush 完成")

        print("等待响应...")
        time.sleep(0.2)

        print("开始 read...")
        resp = ser.read(64)
        print("read 完成")

        if resp:
            print("响应:", resp.hex(" ").upper())
        else:
            print("响应: 无响应")

        return resp
    finally:
        ser.close()
        print("串口已关闭")


if __name__ == "__main__":
    # ===== 根据你的现场修改 =====
    PORT = "COM3"        # 改成你的实际串口
    BAUDRATE = 9600      # 如果你当前读取程序正常，就先保持一致
    SLAVE_ID = 1         # 从站地址，按现场设备改
    COIL_ADDR = 3        # 手册示例是 0x0003（第4个开关）
    # ========================

    print("1 = 合闸")
    print("2 = 分闸")
    choice = input("请选择操作: ").strip()

    if choice == "1":
        frame = build_write_coil_frame(SLAVE_ID, COIL_ADDR, True)
        send_command(PORT, BAUDRATE, frame)
    elif choice == "2":
        frame = build_write_coil_frame(SLAVE_ID, COIL_ADDR, False)
        send_command(PORT, BAUDRATE, frame)
    else:
        print("无效输入")