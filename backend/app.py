# -----------------------------
# 1. 导入需要的库
# -----------------------------
from flask import Flask, jsonify
from flask_cors import CORS
import pymysql

# 导入温湿度传感器读取函数
from read_sensor import read_temperature_humidity


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
    "password": "Yi160403.",
    "database": "dorm_power_db",
    "charset": "utf8mb4"
}


# -----------------------------
# 4. 获取数据库连接
# -----------------------------
def get_connection():
    return pymysql.connect(**db_config)


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


# -----------------------------
# 11. 启动 Flask 服务
# -----------------------------
if __name__ == '__main__':
    print("Flask 准备启动...")
    app.run(debug=True, port=5000)