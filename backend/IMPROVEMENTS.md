# 改进完成指南

## ✅ 已完成的三项改进

### 1. 移除了 `breaker_on` 字段
**文件**：`main.py`  
**改动**：
- 删除了 API 返回中的 `"breaker_on"` 字段
- 原因：该字段是错误推断，在负载通电时仍显示 false，与现实不符
- 状态：现在 `/api/realtime` 不再返回该字段

### 2. 实现了批量扫描接口 GET /api/scan_holding
**文件**：`main.py`（第 620 行）  
**功能**：
```
GET /api/scan_holding?start=0&end=63&block=8
```

**参数**：
- `start`：起始寄存器地址（默认 0）
- `end`：结束寄存器地址（默认 63）
- `block`：每次读取的块大小（默认 8，范围 1~125）

**用途**：
- 快速批量扫描寄存器
- 在分闸/合闸两种状态下对比差异
- 反向工程找到真实状态位

**返回示例**：
```json
{
  "success": true,
  "blocks": [
    {
      "start": 0,
      "start_hex": "0x0000",
      "count": 8,
      "registers": [226, 227, 0, 227, 0, 0, 0, 0],
      "response": "01 03 00 00 10 ...",
      "crc_ok": true,
      "frame_type": "echo_addr"
    }
  ],
  "register_map": {
    "0x0000": 226,
    "0x0001": 227,
    ...
  },
  "timestamp": 1776151248
}
```

### 3. 创建了对比测试脚本
**文件**：`compare_states.py`  
**功能**：
- 记录分闸状态下的所有寄存器
- 执行合闸命令
- 记录合闸状态下的所有寄存器
- 自动对比两个状态的差异
- 找出变化的地址（很可能是状态位）

---

## 🚀 快速使用

### 方式 1：交互式模式（推荐新手）
```bash
cd backend
python compare_states.py
```

进入菜单，按提示选择操作：
```
请选择操作：
  1. 记录分闸状态
  2. 记录合闸状态
  3. 对比差异并查找状态位
  4. 执行合闸
  5. 执行分闸
  6. 查看对比结果
  0. 退出
```

### 方式 2：命令行模式（自动化）
```bash
# 完整自动流程
python compare_states.py --auto

# 或手动四步
python compare_states.py --record-open      # 记录分闸
python compare_states.py --record-close     # 记录合闸
python compare_states.py --compare          # 对比差异
```

### 方式 3：API 调用
```bash
# 在浏览器打开
http://127.0.0.1:8000/docs

# 找到 GET /api/scan_holding
# 输入参数，点击"Try it out"

# 或直接 curl
curl "http://127.0.0.1:8000/api/scan_holding?start=0&end=63&block=8"
```

---

## 📊 数据文件说明

运行对比脚本后，会自动创建 `compare_data/` 目录：

| 文件 | 说明 |
|------|------|
| `state_open.json` | 分闸状态的完整扫描结果 |
| `state_close.json` | 合闸状态的完整扫描结果 |
| `compare_result.json` | 对比分析结果（包含差异地址） |

---

## 🔍 典型工作流

### 步骤 1：启动后端
```bash
cd backend
python main.py
```

### 步骤 2：打开另一个终端，运行对比脚本
```bash
cd backend
python compare_states.py
```

### 步骤 3：执行对比

**选项 A：交互式（适合调试）**
```
选择 1 → 记录分闸状态
选择 4 → 执行合闸
等待 3 秒
选择 2 → 记录合闸状态
选择 3 → 对比差异
```

**选项 B：自动流程（适合快速验证）**
```bash
python compare_states.py --auto
```

### 步骤 4：查看结果
```bash
# 打开 compare_data/compare_result.json
# 或在对比脚本中选择 6
```

---

## 📈 预期结果

### 如果找到状态位
```
🔍 发现 1 个差异地址：
  0x0008: '0' → '1' (变化: 1)

⭐ 关键发现：
  这些地址很可能包含真实状态位！
  建议下一步：
    - 检查 0x0008 的具体含义
```

### 如果未找到
```
⚠️ 未发现任何差异，可能原因：
  1. 状态位可能不在 0x0000~0x003F 范围内
  2. 状态位可能在其他 Modbus 区域（Coils/Input Registers）
  3. 设备延迟较大，需要重新扫描
```

**下一步建议**：
- 扩大扫描范围：`--record-open` 再加上 `end=127`
- 或尝试 Coils 区（功能码 01）
- 或尝试 Input Registers（功能码 04）

---

## 🔧 故障排除

### 连接失败
```
❌ 连接失败，请确保后端服务运行在 http://127.0.0.1:8000
```

**解决**：确保 `main.py` 已启动
```bash
python main.py
# 看到类似提示表示成功
# INFO:     Uvicorn running on http://127.0.0.1:8000
```

### 扫描超时
```
❌ 扫描异常：Request timed out
```

**解决**：
1. 减小扫描范围（`end=31` 而不是 `63`）
2. 增加块大小（`block=16` 而不是 `8`）
3. 检查串口连接是否稳定

### 响应为空或不完整
检查 `main.py` 的串口配置是否正确：
```python
DEFAULT_PORT = "COM7"
DEFAULT_BAUDRATE = 9600
DEFAULT_SLAVE_ID = 1
```

---

## 💡 高级技巧

### 扩大扫描范围寻找更多信息
```bash
# 默认只扫描 0x00~0x3F
python compare_states.py --auto

# 扫描更大范围
curl "http://127.0.0.1:8000/api/scan_holding?start=0&end=127&block=8"
```

### 分别测试不同负载
1. 空载分闸
   ```
   python compare_states.py --record-open
   [不连接任何负载]
   python compare_states.py --record-close
   ```

2. 重负载分闸
   ```
   [连接 2000W 负载]
   python compare_states.py --record-open
   [合闸]
   python compare_states.py --record-close
   ```

3. 对比两次结果，看功率/电流是否变化

---

## 📋 API 端点速查

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/realtime` | 实时数据（电压、温度等）|
| GET | `/api/scan_holding` | 批量扫描寄存器 |
| GET | `/api/groups` | 按组读取寄存器 |
| POST | `/api/control/close` | 合闸 |
| POST | `/api/control/open` | 分闸 |
| GET | `/docs` | Swagger 界面 |

---

## ✨ 下一步建议

### 优先级 1：定位真实状态位
1. 运行 `python compare_states.py --auto`
2. 查找差异地址
3. 文档中确认该地址的含义

### 优先级 2：确认功率/电流
1. 连接明显负载（≥ 1000W）
2. 合闸后等待 10 秒
3. 查看 `/api/realtime` 的 `power_w` 和 `current_a`
4. 如果仍为 0，则这些地址可能错误

### 优先级 3：扫描其他 Modbus 区域
如果 Holding Registers 找不到状态位，考虑：
- 功能码 01（Read Coils）
- 功能码 02（Read Discrete Inputs）
- 功能码 04（Read Input Registers）

---

## 📞 快速链接

- 项目交接文档：`/memories/repo/project_handoff.md`
- 后端代码：`backend/main.py`
- 对比脚本：`backend/compare_states.py`
- API 文档：http://127.0.0.1:8000/docs

---

**最后更新**：2026年4月15日  
**工程状态**：✅ 基础功能完成 | ⏳ 等待状态位反向工程
