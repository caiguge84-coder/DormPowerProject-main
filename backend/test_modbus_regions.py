#!/usr/bin/env python3
"""
Modbus 区域测试脚本：探索 Coils、Discrete Inputs、Input Registers

功能码说明：
  01: Read Coils（读线圈）- 单比特读写
  02: Read Discrete Inputs（读离散输入）- 单比特只读
  03: Read Holding Registers（读保持寄存器）- 16 位读写 ✅ 已测试
  04: Read Input Registers（读输入寄存器）- 16 位只读

用途：
  - 在其他 Modbus 区域中寻找真实开关状态位
  - 寻找功率、电流等计量数据
  - 反向工程找出完整的设备映射
"""

import serial
import time
import threading
from typing import List, Dict, Optional

# 配置
PORT = "COM7"
BAUDRATE = 9600
SLAVE_ID = 1
TIMEOUT = 1.0

# 串口锁
serial_lock = threading.Lock()

# =========================================================
# CRC 计算
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


# =========================================================
# 报文构造
# =========================================================
def build_read_coils_frame(slave_id: int, start_addr: int, count: int) -> bytes:
    """功能码 01: 读线圈"""
    frame = bytes([
        slave_id,
        0x01,
        (start_addr >> 8) & 0xFF,
        start_addr & 0xFF,
        (count >> 8) & 0xFF,
        count & 0xFF,
    ])
    return frame + crc16_modbus(frame)


def build_read_discrete_inputs_frame(slave_id: int, start_addr: int, count: int) -> bytes:
    """功能码 02: 读离散输入"""
    frame = bytes([
        slave_id,
        0x02,
        (start_addr >> 8) & 0xFF,
        start_addr & 0xFF,
        (count >> 8) & 0xFF,
        count & 0xFF,
    ])
    return frame + crc16_modbus(frame)


def build_read_input_registers_frame(slave_id: int, start_addr: int, count: int) -> bytes:
    """功能码 04: 读输入寄存器"""
    frame = bytes([
        slave_id,
        0x04,
        (start_addr >> 8) & 0xFF,
        start_addr & 0xFF,
        (count >> 8) & 0xFF,
        count & 0xFF,
    ])
    return frame + crc16_modbus(frame)


# =========================================================
# 串口通信
# =========================================================
def send_frame(frame: bytes, read_size: int = 128) -> Optional[bytes]:
    """发送报文并接收响应"""
    try:
        with serial_lock:
            with serial.Serial(
                port=PORT,
                baudrate=BAUDRATE,
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
        
        return resp if resp else None
    except Exception as e:
        print(f"❌ 串口错误：{e}")
        return None


# =========================================================
# 响应解析
# =========================================================
def parse_coils_response(resp: bytes, slave_id: int) -> Optional[List[int]]:
    """解析功能码 01 响应"""
    if not resp or len(resp) < 5:
        return None
    
    if resp[0] != slave_id or resp[1] != 0x01:
        return None
    
    if not check_crc(resp):
        return None
    
    byte_count = resp[2]
    if len(resp) < 3 + byte_count + 2:
        return None
    
    coils = []
    for byte_idx in range(byte_count):
        byte_val = resp[3 + byte_idx]
        for bit_idx in range(8):
            coils.append(1 if (byte_val & (1 << bit_idx)) else 0)
    
    return coils


def parse_discrete_inputs_response(resp: bytes, slave_id: int) -> Optional[List[int]]:
    """解析功能码 02 响应"""
    if not resp or len(resp) < 5:
        return None
    
    if resp[0] != slave_id or resp[1] != 0x02:
        return None
    
    if not check_crc(resp):
        return None
    
    byte_count = resp[2]
    if len(resp) < 3 + byte_count + 2:
        return None
    
    inputs = []
    for byte_idx in range(byte_count):
        byte_val = resp[3 + byte_idx]
        for bit_idx in range(8):
            inputs.append(1 if (byte_val & (1 << bit_idx)) else 0)
    
    return inputs


def parse_words(data: bytes) -> List[int]:
    """从字节数组解析 16 位字"""
    if len(data) % 2 != 0:
        return []
    return [(data[i] << 8) | data[i + 1] for i in range(0, len(data), 2)]


def parse_input_registers_response(resp: bytes, slave_id: int) -> Optional[List[int]]:
    """解析功能码 04 响应"""
    if not resp or len(resp) < 7:
        return None
    
    if resp[0] != slave_id or resp[1] != 0x04:
        return None
    
    if not check_crc(resp):
        return None
    
    byte_count = resp[2]
    if len(resp) < 3 + byte_count + 2:
        return None
    
    data = resp[3:3 + byte_count]
    return parse_words(data)


# =========================================================
# 高级读取函数
# =========================================================
def read_coils(start_addr: int, count: int) -> Optional[Dict]:
    """读线圈"""
    frame = build_read_coils_frame(SLAVE_ID, start_addr, count)
    resp = send_frame(frame, read_size=128)
    
    if not resp:
        return None
    
    coils = parse_coils_response(resp, SLAVE_ID)
    if coils is None:
        return None
    
    return {
        "function_code": 1,
        "function_name": "Read Coils",
        "start_addr": start_addr,
        "start_addr_hex": f"0x{start_addr:04X}",
        "count": count,
        "response": resp.hex(" ").upper(),
        "crc_ok": check_crc(resp),
        "coils": coils,
        "non_zero_count": sum(1 for c in coils if c)
    }


def read_discrete_inputs(start_addr: int, count: int) -> Optional[Dict]:
    """读离散输入"""
    frame = build_read_discrete_inputs_frame(SLAVE_ID, start_addr, count)
    resp = send_frame(frame, read_size=128)
    
    if not resp:
        return None
    
    inputs = parse_discrete_inputs_response(resp, SLAVE_ID)
    if inputs is None:
        return None
    
    return {
        "function_code": 2,
        "function_name": "Read Discrete Inputs",
        "start_addr": start_addr,
        "start_addr_hex": f"0x{start_addr:04X}",
        "count": count,
        "response": resp.hex(" ").upper(),
        "crc_ok": check_crc(resp),
        "inputs": inputs,
        "non_zero_count": sum(1 for i in inputs if i)
    }


def read_input_registers(start_addr: int, count: int) -> Optional[Dict]:
    """读输入寄存器"""
    frame = build_read_input_registers_frame(SLAVE_ID, start_addr, count)
    resp = send_frame(frame, read_size=128)
    
    if not resp:
        return None
    
    registers = parse_input_registers_response(resp, SLAVE_ID)
    if registers is None:
        return None
    
    return {
        "function_code": 4,
        "function_name": "Read Input Registers",
        "start_addr": start_addr,
        "start_addr_hex": f"0x{start_addr:04X}",
        "count": count,
        "response": resp.hex(" ").upper(),
        "crc_ok": check_crc(resp),
        "registers": registers
    }


# =========================================================
# 区域扫描
# =========================================================
def scan_region(func_code: int, start: int, end: int, block: int) -> Dict:
    """扫描指定的 Modbus 区域"""
    
    func_names = {1: "Coils", 2: "Discrete Inputs", 4: "Input Registers"}
    func_name = func_names.get(func_code, "Unknown")
    
    print(f"\n{'='*60}")
    print(f"📡 扫描功能码 {func_code:02X}（{func_name}）")
    print(f"   范围：0x{start:04X} ~ 0x{end:04X}")
    print(f"   块大小：{block}")
    print(f"{'='*60}")
    
    results = []
    current_addr = start
    success_count = 0
    error_count = 0
    
    while current_addr <= end:
        read_count = min(block, end - current_addr + 1)
        
        try:
            print(f"\n读取块：0x{current_addr:04X} ~ 0x{current_addr + read_count - 1:04X}")
            
            if func_code == 1:
                result = read_coils(current_addr, read_count)
            elif func_code == 2:
                result = read_discrete_inputs(current_addr, read_count)
            elif func_code == 4:
                result = read_input_registers(current_addr, read_count)
            else:
                print("❌ 未知功能码")
                current_addr += read_count
                continue
            
            if result:
                results.append(result)
                success_count += 1
                
                if func_code in [1, 2]:
                    values = result.get("coils") or result.get("inputs", [])
                    print(f"✅ 成功读取 {len(values)} 个比特位，非零值：{result['non_zero_count']}")
                    if any(values):
                        print(f"   值：{values[:16]}{'...' if len(values) > 16 else ''}")
                else:
                    values = result.get("registers", [])
                    print(f"✅ 成功读取 {len(values)} 个寄存器")
                    print(f"   值：{values}")
            else:
                error_count += 1
                print(f"❌ 读取失败（可能设备不支持该功能码或地址）")
            
            time.sleep(0.1)
            
        except Exception as e:
            error_count += 1
            print(f"❌ 异常：{e}")
        
        current_addr += read_count
    
    print(f"\n{'='*60}")
    print(f"📊 扫描统计：成功 {success_count}，失败 {error_count}")
    print(f"{'='*60}")
    
    return {
        "function_code": func_code,
        "function_name": func_name,
        "scan_range": f"0x{start:04X}~0x{end:04X}",
        "blocks_read": len(results),
        "success_count": success_count,
        "error_count": error_count,
        "blocks": results
    }


# =========================================================
# 交互菜单
# =========================================================
def interactive_menu():
    """交互式菜单"""
    print("\n" + "="*60)
    print("  宿舍用电监测系统 - Modbus 区域测试工具")
    print("="*60)
    print(f"\n当前配置：")
    print(f"  端口：{PORT}")
    print(f"  波特率：{BAUDRATE}")
    print(f"  从站地址：{SLAVE_ID}")
    
    while True:
        print("\n请选择要测试的功能码：")
        print("  1. 功能码 01 - Read Coils（线圈）")
        print("  2. 功能码 02 - Read Discrete Inputs（离散输入）")
        print("  3. 功能码 04 - Read Input Registers（输入寄存器）")
        print("  4. 全部扫描（1+2+4）")
        print("  5. 自定义参数扫描")
        print("  0. 退出")
        
        choice = input("\n输入选择 (0-5): ").strip()
        
        if choice == "1":
            print("\n🔍 扫描功能码 01（线圈）")
            print("默认：0x0000~0x003F，块大小 8")
            result = scan_region(1, 0x0000, 0x003F, 8)
            
        elif choice == "2":
            print("\n🔍 扫描功能码 02（离散输入）")
            print("默认：0x0000~0x003F，块大小 8")
            result = scan_region(2, 0x0000, 0x003F, 8)
            
        elif choice == "3":
            print("\n🔍 扫描功能码 04（输入寄存器）")
            print("默认：0x0000~0x003F，块大小 8")
            result = scan_region(4, 0x0000, 0x003F, 8)
            
        elif choice == "4":
            print("\n🔍 全部扫描")
            for func_code in [1, 2, 4]:
                result = scan_region(func_code, 0x0000, 0x003F, 8)
                time.sleep(1)
            
        elif choice == "5":
            try:
                func_code = int(input("输入功能码（1/2/4）: ").strip())
                start = int(input("输入起始地址（十进制或 0x...）: ").strip(), 0)
                end = int(input("输入结束地址（十进制或 0x...）: ").strip(), 0)
                block = int(input("输入块大小（默认 8）: ").strip() or "8")
                
                result = scan_region(func_code, start, end, block)
            except ValueError:
                print("❌ 输入无效")
            
        elif choice == "0":
            print("👋 再见！")
            break
        
        else:
            print("❌ 无效选择")


if __name__ == "__main__":
    try:
        interactive_menu()
    except KeyboardInterrupt:
        print("\n\n⏸️  已中断")
