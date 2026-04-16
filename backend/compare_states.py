#!/usr/bin/env python3
"""
对比测试脚本：分闸 vs 合闸状态下的寄存器差异分析

用途：
  1. 记录分闸状态下的寄存器
  2. 执行合闸
  3. 记录合闸状态下的寄存器
  4. 对比两个状态的差异
  5. 找出真实状态位

使用方法：
  python compare_states.py
  或手动四步操作：
  python compare_states.py --record-open
  [执行合闸]
  python compare_states.py --record-close
  python compare_states.py --compare
"""

import requests
import json
import sys
import time
from pathlib import Path

# 配置
API_BASE_URL = "http://127.0.0.1:8000"
SCAN_START = 0
SCAN_END = 63
SCAN_BLOCK = 8

# 数据保存路径
DATA_DIR = Path(__file__).parent / "compare_data"
OPEN_STATE_FILE = DATA_DIR / "state_open.json"
CLOSE_STATE_FILE = DATA_DIR / "state_close.json"
COMPARE_RESULT_FILE = DATA_DIR / "compare_result.json"


def ensure_data_dir():
    """确保数据目录存在"""
    DATA_DIR.mkdir(exist_ok=True)
    print(f"✅ 数据目录：{DATA_DIR}")


def scan_registers(name: str, file_path: Path) -> dict:
    """扫描寄存器并保存结果"""
    print(f"\n📡 开始扫描 {name} 状态下的寄存器...")
    print(f"   范围：0x{SCAN_START:04X} ~ 0x{SCAN_END:04X}")
    print(f"   块大小：{SCAN_BLOCK}")

    try:
        url = f"{API_BASE_URL}/api/scan_holding"
        params = {
            "start": SCAN_START,
            "end": SCAN_END,
            "block": SCAN_BLOCK
        }

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if not data.get("success"):
            print(f"❌ 扫描失败：{data.get('message')}")
            return None

        # 提取寄存器映射
        register_map = data.get("register_map", {})
        print(f"✅ 成功读取 {len(register_map)} 个寄存器")

        # 保存完整结果
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"💾 数据已保存到：{file_path}")

        # 显示前几个值
        print(f"\n📊 寄存器示例：")
        for i, (addr, val) in enumerate(sorted(register_map.items())[:10]):
            print(f"   {addr}: {val}")
        if len(register_map) > 10:
            print(f"   ... 共 {len(register_map)} 个寄存器")

        return register_map

    except requests.exceptions.ConnectionError:
        print("❌ 连接失败，请确保后端服务运行在 http://127.0.0.1:8000")
        return None
    except Exception as e:
        print(f"❌ 扫描异常：{e}")
        return None


def control_breaker(action: str) -> bool:
    """执行合闸或分闸命令"""
    url = f"{API_BASE_URL}/api/control/{action}"

    print(f"\n🔌 执行 {'合闸' if action == 'close' else '分闸'} 命令...")

    try:
        response = requests.post(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("success"):
            print(f"✅ {'合闸' if action == 'close' else '分闸'} 成功！")
            if "data" in data and "message" in data["data"]:
                print(f"   {data['data']['message']}")
            return True
        else:
            print(f"❌ 控制失败：{data.get('message')}")
            return False

    except requests.exceptions.ConnectionError:
        print("❌ 连接失败，请确保后端服务运行在 http://127.0.0.1:8000")
        return False
    except Exception as e:
        print(f"❌ 控制异常：{e}")
        return False


def compare_states() -> dict:
    """对比两个状态的差异"""
    print("\n📊 开始对比分闸 vs 合闸状态的差异...")

    # 加载两个状态
    if not OPEN_STATE_FILE.exists():
        print(f"❌ 分闸状态文件不存在：{OPEN_STATE_FILE}")
        return None

    if not CLOSE_STATE_FILE.exists():
        print(f"❌ 合闸状态文件不存在：{CLOSE_STATE_FILE}")
        return None

    with open(OPEN_STATE_FILE, "r", encoding="utf-8") as f:
        open_data = json.load(f)

    with open(CLOSE_STATE_FILE, "r", encoding="utf-8") as f:
        close_data = json.load(f)

    open_map = open_data.get("register_map", {})
    close_map = close_data.get("register_map", {})

    print(f"\n分闸状态：{len(open_map)} 个寄存器")
    print(f"合闸状态：{len(close_map)} 个寄存器")

    # 找出差异
    differences = []
    all_addrs = set(open_map.keys()) | set(close_map.keys())

    for addr in sorted(all_addrs):
        open_val = open_map.get(addr, "未读取")
        close_val = close_map.get(addr, "未读取")

        if open_val != close_val:
            differences.append({
                "address": addr,
                "open_state": open_val,
                "close_state": close_val,
                "change": int(close_val) - int(open_val) if isinstance(open_val, (int, str)) and isinstance(close_val, (int, str)) else None
            })

    print(f"\n🔍 发现 {len(differences)} 个差异地址：")
    print("-" * 60)

    if differences:
        for diff in differences:
            addr = diff["address"]
            open_val = diff["open_state"]
            close_val = diff["close_state"]
            change = diff["change"]

            print(f"  {addr}: {open_val:>6} → {close_val:>6} (变化: {change if change is not None else 'N/A'})")

        # 如果只有 1-2 个地址变化，这很可能是状态位
        if len(differences) <= 3:
            print("\n⭐ 关键发现：")
            print("  这些地址很可能包含真实状态位！")
            print("  建议下一步：")
            for diff in differences:
                addr = diff["address"]
                print(f"    - 检查 {addr} 的具体含义")
    else:
        print("  ⚠️ 未发现任何差异，可能原因：")
        print("  1. 状态位可能不在 0x0000~0x003F 范围内")
        print("  2. 状态位可能在其他 Modbus 区域（Coils/Input Registers）")
        print("  3. 设备延迟较大，需要重新扫描")

    # 保存对比结果
    result = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "open_state_file": str(OPEN_STATE_FILE),
        "close_state_file": str(CLOSE_STATE_FILE),
        "scan_range": f"0x{SCAN_START:04X}~0x{SCAN_END:04X}",
        "total_addresses_scanned": len(all_addrs),
        "differences_found": len(differences),
        "differences": differences
    }

    with open(COMPARE_RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\n💾 对比结果已保存到：{COMPARE_RESULT_FILE}")

    return result


def interactive_mode():
    """交互式模式"""
    print("\n" + "=" * 60)
    print("  宿舍用电监测系统 - 分闸/合闸状态对比工具")
    print("=" * 60)

    ensure_data_dir()

    while True:
        print("\n请选择操作：")
        print("  1. 记录分闸状态（先确保当前是分闸）")
        print("  2. 记录合闸状态（先确保当前是合闸）")
        print("  3. 对比差异并查找状态位")
        print("  4. 执行合闸")
        print("  5. 执行分闸")
        print("  6. 查看对比结果")
        print("  0. 退出")

        choice = input("\n输入选择 (0-6): ").strip()

        if choice == "1":
            print("⚠️  请确保设备当前处于【分闸】状态")
            confirm = input("是否继续？(y/n): ").strip().lower()
            if confirm == "y":
                register_map = scan_registers("分闸", OPEN_STATE_FILE)
                if register_map:
                    print("\n✅ 分闸状态已记录")
                time.sleep(1)

        elif choice == "2":
            print("⚠️  请确保设备当前处于【合闸】状态")
            confirm = input("是否继续？(y/n): ").strip().lower()
            if confirm == "y":
                register_map = scan_registers("合闸", CLOSE_STATE_FILE)
                if register_map:
                    print("\n✅ 合闸状态已记录")
                time.sleep(1)

        elif choice == "3":
            result = compare_states()
            if result:
                print("\n✅ 对比完成")
            time.sleep(2)

        elif choice == "4":
            confirm = input("确认执行合闸？(y/n): ").strip().lower()
            if confirm == "y":
                control_breaker("close")
                print("⏳ 等待 3 秒后可进行下一步扫描...")
                time.sleep(3)

        elif choice == "5":
            confirm = input("确认执行分闸？(y/n): ").strip().lower()
            if confirm == "y":
                control_breaker("open")
                print("⏳ 等待 3 秒后可进行下一步扫描...")
                time.sleep(3)

        elif choice == "6":
            if COMPARE_RESULT_FILE.exists():
                with open(COMPARE_RESULT_FILE, "r", encoding="utf-8") as f:
                    result = json.load(f)
                print("\n" + "=" * 60)
                print("对比结果：")
                print("=" * 60)
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print("❌ 还未进行对比，请先执行操作 3")
            time.sleep(2)

        elif choice == "0":
            print("👋 再见！")
            break

        else:
            print("❌ 无效选择，请重试")


def cli_mode():
    """命令行模式"""
    if len(sys.argv) < 2:
        interactive_mode()
        return

    command = sys.argv[1]
    ensure_data_dir()

    if command == "--record-open":
        print("📡 记录分闸状态...")
        scan_registers("分闸", OPEN_STATE_FILE)

    elif command == "--record-close":
        print("📡 记录合闸状态...")
        scan_registers("合闸", CLOSE_STATE_FILE)

    elif command == "--compare":
        print("📊 对比状态差异...")
        compare_states()

    elif command == "--auto":
        print("🤖 自动对比流程")
        print("1. 记录分闸状态")
        scan_registers("分闸", OPEN_STATE_FILE)
        print("\n2. 等待 5 秒...")
        time.sleep(5)
        print("\n3. 执行合闸")
        control_breaker("close")
        print("\n4. 等待 5 秒...")
        time.sleep(5)
        print("\n5. 记录合闸状态")
        scan_registers("合闸", CLOSE_STATE_FILE)
        print("\n6. 对比差异")
        compare_states()
        print("\n✅ 自动对比完成")

    elif command == "--help":
        print(__doc__)

    else:
        print(f"❌ 未知命令：{command}")
        print("\n可用命令：")
        print("  --record-open    记录分闸状态")
        print("  --record-close   记录合闸状态")
        print("  --compare        对比两个状态")
        print("  --auto           完整自动流程")
        print("  --help           显示帮助")
        print("\n或直接运行：python compare_states.py（进入交互模式）")


if __name__ == "__main__":
    try:
        cli_mode()
    except KeyboardInterrupt:
        print("\n\n⏸️  已中断")
        sys.exit(0)
