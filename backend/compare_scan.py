"""
对比扫描脚本 - 用于对比分闸/合闸状态下的寄存器差异
"""
import requests
import json
import time
from datetime import datetime

# 配置
BACKEND_URL = "http://127.0.0.1:8000"
SCAN_START = 0
SCAN_END = 63
SCAN_BLOCK = 8

def print_section(title):
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80)

def save_scan_result(data, filename):
    """保存扫描结果到文件"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ 结果已保存到: {filename}")

def load_scan_result(filename):
    """从文件加载扫描结果"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ 文件不存在: {filename}")
        return None

def scan_registers(state_name):
    """扫描寄存器"""
    print_section(f"扫描 [{state_name}] 状态的寄存器")
    print(f"范围: 0x{SCAN_START:04X} ~ 0x{SCAN_END:04X}, 块大小: {SCAN_BLOCK}")
    
    try:
        response = requests.get(
            f"{BACKEND_URL}/api/scan_holding",
            params={
                "start": SCAN_START,
                "end": SCAN_END,
                "block": SCAN_BLOCK
            },
            timeout=60
        )
        
        if response.status_code != 200:
            print(f"❌ HTTP 错误: {response.status_code}")
            print(f"   {response.text}")
            return None
        
        data = response.json()
        
        if not data.get("success"):
            print(f"❌ 扫描失败: {data.get('message', 'unknown error')}")
            return None
        
        print(f"✅ 扫描成功")
        print(f"   后端地址: {data.get('port', '?')}")
        print(f"   波特率: {data.get('baudrate', '?')}")
        print(f"   从站ID: {data.get('slave_id', '?')}")
        print(f"   块数: {len(data.get('blocks', []))}")
        print(f"   寄存器总数: {len(data.get('register_map', {}))}")
        
        return data
    
    except requests.exceptions.ConnectionError:
        print(f"❌ 无法连接到后端: {BACKEND_URL}")
        return None
    except Exception as e:
        print(f"❌ 扫描异常: {str(e)}")
        return None

def control_breaker(action):
    """控制分合闸"""
    print_section(f"执行 [{action}] 操作")
    
    endpoint = f"{BACKEND_URL}/api/control/{action}"
    
    try:
        response = requests.post(endpoint, timeout=10)
        
        if response.status_code != 200:
            print(f"❌ HTTP 错误: {response.status_code}")
            return False
        
        data = response.json()
        
        if not data.get("success"):
            print(f"❌ 操作失败: {data.get('message', 'unknown error')}")
            return False
        
        print(f"✅ 操作成功")
        print(f"   动作: {data['data'].get('action', '?')}")
        print(f"   响应: {data['data'].get('response', '?')}")
        return True
    
    except requests.exceptions.ConnectionError:
        print(f"❌ 无法连接到后端: {BACKEND_URL}")
        return False
    except Exception as e:
        print(f"❌ 操作异常: {str(e)}")
        return False

def compare_results(result_open, result_close, output_file):
    """对比两个扫描结果，找出差异"""
    print_section("对比扫描结果")
    
    if not result_open or not result_close:
        print("❌ 缺少必要的扫描数据")
        return
    
    reg_map_open = result_open.get("register_map", {})
    reg_map_close = result_close.get("register_map", {})
    
    if not reg_map_open or not reg_map_close:
        print("❌ 无法获取寄存器映射")
        return
    
    print(f"分闸状态寄存器数: {len(reg_map_open)}")
    print(f"合闸状态寄存器数: {len(reg_map_close)}")
    
    # 找出所有变化的寄存器
    all_regs = set(reg_map_open.keys()) | set(reg_map_close.keys())
    changes = []
    
    for reg_addr in sorted(all_regs):
        val_open = reg_map_open.get(reg_addr, None)
        val_close = reg_map_close.get(reg_addr, None)
        
        if val_open != val_close:
            changes.append({
                "address": reg_addr,
                "address_hex": f"0x{int(reg_addr, 16):04X}" if isinstance(reg_addr, str) else f"0x{reg_addr:04X}",
                "value_open": val_open,
                "value_close": val_close,
                "delta": (val_close - val_open) if isinstance(val_close, (int, float)) and isinstance(val_open, (int, float)) else None
            })
    
    if changes:
        print(f"\n🔍 发现 {len(changes)} 个差异点：\n")
        for change in changes:
            delta_str = f" (变化: {change['delta']:+d})" if change['delta'] is not None else ""
            print(f"  {change['address_hex']}: {change['value_open']} → {change['value_close']}{delta_str}")
    else:
        print("\n⚠️  未发现任何差异")
    
    # 保存对比结果
    comparison_data = {
        "timestamp": datetime.now().isoformat(),
        "backend_url": BACKEND_URL,
        "scan_params": {
            "start": SCAN_START,
            "end": SCAN_END,
            "block_size": SCAN_BLOCK
        },
        "open_state": {
            "timestamp": result_open.get("timestamp"),
            "register_count": len(reg_map_open)
        },
        "close_state": {
            "timestamp": result_close.get("timestamp"),
            "register_count": len(reg_map_close)
        },
        "differences": changes,
        "summary": {
            "total_changed": len(changes),
            "total_registers": len(all_regs)
        }
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(comparison_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 对比结果已保存到: {output_file}")
    
    return comparison_data

def main():
    print("\n")
    print("╔" + "="*78 + "╗")
    print("║" + " "*78 + "║")
    print("║" + "  宿舍电气监测系统 - 分闸/合闸状态对比扫描".center(78) + "║")
    print("║" + " "*78 + "║")
    print("╚" + "="*78 + "╝")
    
    # 生成时间戳文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_open = f"scan_open_{timestamp}.json"
    file_close = f"scan_close_{timestamp}.json"
    file_compare = f"compare_{timestamp}.json"
    
    # 步骤 1: 扫描分闸状态
    print("\n[第 1 步] 扫描分闸状态...")
    print("请确保设备当前处于分闸状态。按 Enter 继续...")
    input()
    
    result_open = scan_registers("分闸")
    if result_open:
        save_scan_result(result_open, file_open)
    else:
        print("❌ 分闸状态扫描失败，中止")
        return
    
    # 步骤 2: 控制合闸
    print("\n[第 2 步] 执行合闸操作...")
    success = control_breaker("close")
    if not success:
        print("❌ 合闸操作失败")
        print("❓ 是否继续扫描（可能已经合闸）？按 Enter 继续或 Ctrl+C 中止...")
        try:
            input()
        except KeyboardInterrupt:
            print("\n中止")
            return
    
    # 等待设备稳定
    print("\n[第 3 步] 等待设备稳定...")
    wait_time = 5
    for i in range(wait_time):
        print(f"   等待中... ({i+1}/{wait_time}s)")
        time.sleep(1)
    
    # 步骤 4: 扫描合闸状态
    print("\n[第 4 步] 扫描合闸状态...")
    result_close = scan_registers("合闸")
    if result_close:
        save_scan_result(result_close, file_close)
    else:
        print("❌ 合闸状态扫描失败")
        print("❓ 继续对比已有数据？按 Enter 继续或 Ctrl+C 中止...")
        try:
            input()
        except KeyboardInterrupt:
            print("\n中止")
            return
    
    # 步骤 5: 对比结果
    print("\n[第 5 步] 对比两个扫描结果...")
    if result_open and result_close:
        compare_results(result_open, result_close, file_compare)
    else:
        print("❌ 缺少必要数据，无法对比")
    
    # 步骤 6: 恢复到分闸状态（可选）
    print("\n[第 6 步] 是否恢复到分闸状态？(y/n)")
    choice = input().strip().lower()
    if choice == 'y':
        control_breaker("open")
    
    print_section("完成")
    print(f"✅ 所有扫描数据已保存:")
    print(f"   - 分闸状态: {file_open}")
    print(f"   - 合闸状态: {file_close}")
    print(f"   - 对比结果: {file_compare}")
    print()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n中止执行")
    except Exception as e:
        print(f"\n❌ 程序异常: {str(e)}")
        import traceback
        traceback.print_exc()
