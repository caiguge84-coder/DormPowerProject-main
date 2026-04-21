# -----------------------------
# 1. 导入需要的库
# -----------------------------
from flask import Flask, jsonify, request
from flask_cors import CORS
import pymysql

# 导入温湿度传感器读取函数
from read_sensor import read_temperature_humidity
from modbus_client import read_all_blocks, control_breaker


# -----------------------------
# 2. 创建 Flask 应用
# -----------------------------
app = Flask(__name__)
CORS(app)


# -----------------------------
# 3. 数据库连接配置
# -----------------------------
db_config = {
    "host": "localhost",
    "user": "root",
    "password": "123456789",
    "database": "dorm_power_db",
    "charset": "utf8mb4"
}

MODBUS_TABLE = "modbus_realtime_records"


# -----------------------------
# 4. 获取数据库连接
# -----------------------------
def get_connection():
    return pymysql.connect(**db_config)


def ensure_modbus_table():
    conn = get_connection()
    cursor = conn.cursor()
    create_sql = f"""
    CREATE TABLE IF NOT EXISTS {MODBUS_TABLE} (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        ch1_voltage INT NOT NULL,
        ch2_voltage INT NOT NULL,
        ch3_voltage INT NOT NULL,
        ch4_voltage INT NOT NULL,
        ch5_voltage INT NOT NULL,
        ch6_voltage INT NOT NULL,
        ch1_power INT NOT NULL,
        ch2_power INT NOT NULL,
        ch3_power INT NOT NULL,
        ch4_power INT NOT NULL,
        ch5_power INT NOT NULL,
        ch6_power INT NOT NULL,
        ch1_temperature INT NOT NULL,
        ch2_temperature INT NOT NULL,
        ch3_temperature INT NOT NULL,
        ch4_temperature INT NOT NULL,
        ch5_temperature INT NOT NULL,
        ch6_temperature INT NOT NULL,
        ch1_current INT NOT NULL,
        ch2_current INT NOT NULL,
        ch3_current INT NOT NULL,
        ch4_current INT NOT NULL,
        ch5_current INT NOT NULL,
        ch6_current INT NOT NULL,
        ch1_status_raw VARCHAR(8) NOT NULL,
        ch2_status_raw VARCHAR(8) NOT NULL,
        ch3_status_raw VARCHAR(8) NOT NULL,
        ch4_status_raw VARCHAR(8) NOT NULL,
        ch5_status_raw VARCHAR(8) NOT NULL,
        ch6_status_raw VARCHAR(8) NOT NULL,
        record_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    cursor.execute(create_sql)
    conn.commit()
    cursor.close()
    conn.close()


def _status_to_breaker_on(status_hex):
    status_text = str(status_hex or "").upper()
    if status_text in {"5A00", "A500"}:
        return True
    if status_text == "0000":
        return False
    return False


def map_row_to_channels(row):
    if not row:
        return []

    channels = []
    for idx in range(1, 7):
        voltage = row[f"ch{idx}_voltage"]
        power = row[f"ch{idx}_power"]
        temperature_raw = row[f"ch{idx}_temperature"]
        current = row[f"ch{idx}_current"]
        status_raw = (row.get(f"ch{idx}_status_raw") or "0000").upper()
        channels.append({
            "ch": idx,
            "voltage_raw": voltage,
            "voltage": float(voltage),
            "power_raw": power,
            "power": float(power),
            "temperature_raw": temperature_raw,
            "temperature": round(float(temperature_raw) / 10.0, 1),
            "current_raw": current,
            "current": round(float(current) * 0.1, 3),
            # 按当前设备映射，漏电与电流同源寄存器，先返回 raw 值
            "leakage_current_raw": current,
            "leakage_current": float(current),
            "status_raw": status_raw,
            "breaker_on": _status_to_breaker_on(status_raw),
        })
    return channels


def insert_modbus_record(channels):
    ensure_modbus_table()
    conn = get_connection()
    cursor = conn.cursor()

    fields = []
    placeholders = []
    values = []
    metrics = ["voltage_raw", "power_raw", "temperature_raw", "current_raw", "status_raw"]

    for metric in metrics:
        for idx in range(1, 7):
            key = f"ch{idx}_{metric.replace('_raw', '')}" if metric != "status_raw" else f"ch{idx}_status_raw"
            fields.append(key)
            placeholders.append("%s")
            channel_data = channels[idx - 1]
            values.append(channel_data[metric])

    sql = f"""
    INSERT INTO {MODBUS_TABLE} ({", ".join(fields)}, record_time)
    VALUES ({", ".join(placeholders)}, NOW())
    """
    cursor.execute(sql, values)
    conn.commit()
    inserted_id = cursor.lastrowid

    cursor.close()
    conn.close()
    return inserted_id


def get_latest_modbus_row():
    ensure_modbus_table()
    conn = get_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    sql = f"SELECT * FROM {MODBUS_TABLE} ORDER BY record_time DESC, id DESC LIMIT 1"
    cursor.execute(sql)
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def get_modbus_rows(limit=30):
    ensure_modbus_table()
    conn = get_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    sql = f"SELECT * FROM {MODBUS_TABLE} ORDER BY record_time DESC, id DESC LIMIT %s"
    cursor.execute(sql, (int(limit),))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


# -----------------------------
# 5. 插入一条采集记录
# -----------------------------
def insert_power_record(device_name, power, temperature, humidity, status):
    conn = get_connection()
    cursor = conn.cursor()

    sql = """
    INSERT INTO power_records (device_name, power, temperature, humidity, status, record_time)
    VALUES (%s, %s, %s, %s, %s, NOW())
    """
    cursor.execute(sql, (device_name, power, temperature, humidity, status))
    conn.commit()

    cursor.close()
    conn.close()


# -----------------------------
# 6. 首页测试路由
# -----------------------------
@app.route('/')
def home():
    return 'Flask backend is running.'


# -----------------------------
# 7. 测试数据库连接
# -----------------------------
@app.route('/api/test_db')
def test_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        return jsonify({
            "code": 200,
            "message": "数据库连接成功",
            "data": result
        })

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"数据库连接失败：{str(e)}"
        })


# -----------------------------
# 8. 获取最新一条实时数据
# -----------------------------
@app.route('/api/realtime')
def get_realtime_data():
    try:
        conn = get_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        sql = """
        SELECT * FROM power_records
        ORDER BY record_time DESC
        LIMIT 1
        """
        cursor.execute(sql)
        data = cursor.fetchone()

        cursor.close()
        conn.close()

        return jsonify({
            "code": 200,
            "message": "success",
            "data": data
        })

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": str(e)
        })


# -----------------------------
# 9. 获取最近 20 条历史数据
# -----------------------------
@app.route('/api/history')
def get_history_data():
    try:
        conn = get_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        sql = """
        SELECT * FROM power_records
        ORDER BY record_time DESC
        LIMIT 20
        """
        cursor.execute(sql)
        data = cursor.fetchall()

        cursor.close()
        conn.close()

        return jsonify({
            "code": 200,
            "message": "success",
            "data": data
        })

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": str(e)
        })


# -----------------------------
# 10. 手动采集传感器数据并写入数据库
# 浏览器访问：http://127.0.0.1:5000/api/collect
# -----------------------------
@app.route('/api/collect')
def collect_sensor_data():
    try:
        sensor_data = read_temperature_humidity()

        if not sensor_data["success"]:
            return jsonify({
                "code": 500,
                "message": sensor_data.get("message", "传感器读取失败")
            })

        temperature = sensor_data["temperature"]
        humidity = sensor_data["humidity"]

        # 暂时固定值，后面接功率传感器时再改
        device_name = "Dorm Sensor"
        power = 0.0
        status = "运行中"

        insert_power_record(
            device_name=device_name,
            power=power,
            temperature=temperature,
            humidity=humidity,
            status=status
        )

        return jsonify({
            "code": 200,
            "message": "采集并存入数据库成功",
            "data": {
                "device_name": device_name,
                "power": power,
                "temperature": temperature,
                "humidity": humidity,
                "status": status
            }
        })

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"采集入库失败：{str(e)}"
        })


@app.route('/api/modbus/test/read-all')
def modbus_test_read_all():
    result = read_all_blocks()
    if not result.get("success"):
        return jsonify({
            "code": 500,
            "message": result.get("message", "Modbus读取失败"),
            "data": result
        })

    return jsonify({
        "code": 200,
        "message": "success",
        "data": result
    })


@app.route('/api/modbus/test/control', methods=['POST'])
def modbus_test_control():
    payload = request.get_json(silent=True) or {}
    channel = payload.get("channel")
    action = payload.get("action")
    result = control_breaker(channel=channel, action=action)
    if not result.get("success"):
        return jsonify({
            "code": 500,
            "message": result.get("message", "控制失败"),
            "data": result
        })

    return jsonify({
        "code": 200,
        "message": "success",
        "data": result
    })


@app.route('/api/collect/modbus', methods=['POST'])
def collect_modbus_data():
    try:
        result = read_all_blocks()
        if not result.get("success"):
            return jsonify({
                "code": 500,
                "message": result.get("message", "Modbus读取失败"),
                "data": result
            })

        inserted_id = insert_modbus_record(result["channels"])
        return jsonify({
            "code": 200,
            "message": "采集并入库成功",
            "data": {
                "id": inserted_id,
                "channels": result["channels"]
            }
        })
    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"采集入库失败：{str(e)}"
        })


@app.route('/api/realtime/modbus')
def get_modbus_realtime():
    try:
        row = get_latest_modbus_row()
        if not row:
            return jsonify({
                "code": 200,
                "message": "暂无数据",
                "data": None
            })

        channels = map_row_to_channels(row)
        return jsonify({
            "code": 200,
            "message": "success",
            "data": {
                "id": row["id"],
                "record_time": row["record_time"].strftime("%Y-%m-%d %H:%M:%S"),
                "channels": channels
            }
        })
    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"读取实时数据失败：{str(e)}"
        })


@app.route('/api/history/modbus')
def get_modbus_history():
    try:
        try:
            limit = int(request.args.get("limit", 30))
        except Exception:
            limit = 30

        rows = get_modbus_rows(limit=max(1, min(limit, 200)))
        items = []
        for row in rows:
            channels = map_row_to_channels(row)
            ch1 = channels[0] if channels else None
            items.append({
                "id": row["id"],
                "record_time": row["record_time"].strftime("%Y-%m-%d %H:%M:%S"),
                "channels": channels,
                "ch1": ch1
            })

        return jsonify({
            "code": 200,
            "message": "success",
            "data": items
        })
    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"读取历史数据失败：{str(e)}"
        })


@app.route('/api/control/breaker', methods=['POST'])
def api_control_breaker():
    payload = request.get_json(silent=True) or {}
    channel = payload.get("channel", 1)
    action = payload.get("action")
    result = control_breaker(channel=channel, action=action)
    if not result.get("success"):
        return jsonify({
            "code": 500,
            "message": result.get("message", "控制失败"),
            "data": result
        })

    return jsonify({
        "code": 200,
        "message": "控制成功",
        "data": result
    })


# -----------------------------
# 11. 启动 Flask 服务
# -----------------------------
if __name__ == '__main__':
    print("Flask 准备启动...")
    app.run(debug=True, port=5000)