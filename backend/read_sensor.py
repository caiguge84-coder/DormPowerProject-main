from pymodbus.client import ModbusSerialClient

PORT = "COM7"
BAUDRATE = 9600
SLAVE_ID = 1
REGISTER_ADDRESS = 0x0020
REGISTER_COUNT = 2


def read_temperature_humidity():
    client = ModbusSerialClient(
        port=PORT,
        baudrate=BAUDRATE,
        parity='N',
        stopbits=1,
        bytesize=8,
        timeout=2
    )

    try:
        if client.connect():
            result = client.read_holding_registers(
                address=REGISTER_ADDRESS,
                count=REGISTER_COUNT,
                device_id=SLAVE_ID
            )

            if result.isError():
                client.close()
                return {
                    "success": False,
                    "message": f"Modbus读取失败: {result}"
                }

            temp_raw = result.registers[0]
            hum_raw = result.registers[1]

            temperature = temp_raw / 10.0
            humidity = hum_raw / 10.0

            client.close()

            return {
                "success": True,
                "temperature": temperature,
                "humidity": humidity
            }

        else:
            return {
                "success": False,
                "message": "串口连接失败"
            }

    except Exception as e:
        try:
            client.close()
        except:
            pass

        return {
            "success": False,
            "message": f"程序异常: {repr(e)}"
        }


if __name__ == "__main__":
    data = read_temperature_humidity()
    print(data)