from __future__ import annotations

"""
plc_comm.py 调用说明书
======================

这个文件不是 PLC 通讯库本体，而是给 `plc_comm.py` 配套的中文调用示例。
你可以直接修改这里的 PLC 参数和 DB 地址，然后把下面的示例函数拿去用。

一、先安装依赖
---------------
pip install python-snap7

二、核心对象
-------------
1. `SiemensPLCClient`
   用来连接、断开、读写西门子 PLC。

2. `PLCVariable`
   用来描述一个 PLC 变量地址。
   主要参数：
   - `name`: 变量名，只是给程序自己看的
   - `db_number`: DB 块号
   - `start`: 起始字节
   - `data_type`: 数据类型
   - `bit_index`: 只有 BOOL 时才需要，范围 0-7

三、支持的数据类型
------------------
`REAL`, `INT`, `DINT`, `WORD`, `DWORD`, `BYTE`, `BOOL`, `S7STRING`

四、几个要点
------------
1. `read_value()` 最终统一返回 `float`
   就算你读的是 `INT` 或 `BOOL`，也会先转成浮点数。

2. 如果你想拿字符串形式，优先用 `read_text()`
   它会按类型帮你转成更适合显示的文本。

3. 写 `BOOL` 时要么用 `write_bool()`，要么用 `write_value()`
   但 BOOL 变量一定要带 `bit_index`。

4. 写 `S7STRING` 前，PLC 里的目标地址最好已经是标准 S7 字符串
   因为库会先读取前 2 个字节当字符串头部。

5. 用完后记得 `disconnect()`

6. 这个说明文件默认不会自动连接 PLC，也不会自动写数据
   你手动调用哪个示例函数，它才会执行。
"""

import time

from plc_comm import PLCVariable, SiemensPLCClient


# 按你自己的 PLC 去改
PLC_IP = "127.0.0.1"
RACK = 0
SLOT = 1


# 按你自己的 DB 地址去改
BARCODE_DB = 6100
BARCODE_START = 10
START_SIGNAL_DB = 6100
START_SIGNAL_START = 0
START_SIGNAL_BIT = 0
COMPLETE_SIGNAL_DB = 6100
COMPLETE_SIGNAL_START = 0
COMPLETE_SIGNAL_BIT = 1


def create_client() -> SiemensPLCClient:
    """创建 PLC 客户端。"""
    return SiemensPLCClient(PLC_IP, RACK, SLOT)


def barcode_variable() -> PLCVariable:
    """扫码结果写入地址，默认按 S7STRING 处理。"""
    return PLCVariable(
        name="barcode_out",
        db_number=BARCODE_DB,
        start=BARCODE_START,
        data_type="S7STRING",
    )


def start_signal_variable() -> PLCVariable:
    """开始信号地址。"""
    return PLCVariable(
        name="start_signal",
        db_number=START_SIGNAL_DB,
        start=START_SIGNAL_START,
        data_type="BOOL",
        bit_index=START_SIGNAL_BIT,
    )


def complete_signal_variable() -> PLCVariable:
    """完成信号地址。"""
    return PLCVariable(
        name="complete_signal",
        db_number=COMPLETE_SIGNAL_DB,
        start=COMPLETE_SIGNAL_START,
        data_type="BOOL",
        bit_index=COMPLETE_SIGNAL_BIT,
    )


def example_connect_only() -> None:
    """只测试 PLC 是否能连接成功。"""
    client = create_client()
    try:
        client.connect()
        print(f"连接成功: PLC {PLC_IP} (Rack {RACK}, Slot {SLOT})")
    finally:
        client.disconnect()


def example_minimal_read() -> None:
    """最小示例：连接 PLC，读取一个 REAL。"""
    client = create_client()
    temperature = PLCVariable(
        name="temperature",
        db_number=1,
        start=0,
        data_type="REAL",
    )

    try:
        client.connect()
        value = client.read_value(temperature)
        print(f"读取成功: {temperature.name} = {value}")
    finally:
        client.disconnect()


def example_read_bool() -> None:
    """示例：读取一个 BOOL 位。"""
    client = create_client()
    run_flag = PLCVariable(
        name="run_flag",
        db_number=6100,
        start=2,
        data_type="BOOL",
        bit_index=0,
    )

    try:
        client.connect()
        value = client.read_value(run_flag)
        print(f"BOOL 读取结果: {run_flag.name} = {bool(round(value))}")
    finally:
        client.disconnect()


def example_read_text() -> None:
    """示例：读取一个 S7STRING 文本。"""
    client = create_client()
    barcode = barcode_variable()

    try:
        client.connect()
        text = client.read_text(barcode)
        print(f"字符串读取结果: {barcode.name} = {text}")
    finally:
        client.disconnect()


def example_batch_read() -> None:
    """示例：批量读取多个变量。"""
    client = create_client()
    variables = [
        PLCVariable(name="pressure", db_number=1, start=0, data_type="REAL"),
        PLCVariable(name="count", db_number=1, start=4, data_type="INT"),
        PLCVariable(name="ready", db_number=1, start=6, data_type="BOOL", bit_index=0),
    ]

    try:
        client.connect()
        results = client.read_values(variables)
        for name, value in results.items():
            print(f"{name} = {value}")
    finally:
        client.disconnect()


def example_write_values() -> None:
    """示例：写 REAL / BOOL / S7STRING。"""
    client = create_client()

    real_var = PLCVariable(name="set_speed", db_number=1, start=20, data_type="REAL")
    bool_var = PLCVariable(name="start_cmd", db_number=1, start=24, data_type="BOOL", bit_index=0)
    text_var = barcode_variable()

    try:
        client.connect()
        client.write_value(real_var, 12.5)
        client.write_bool(bool_var, True)
        client.write_value(text_var, "ABC123")
        print("写入完成。")
    finally:
        client.disconnect()


def example_read_series() -> None:
    """示例：连续读取多个数值。"""
    client = create_client()
    series_var = PLCVariable(
        name="history_values",
        db_number=1,
        start=100,
        data_type="REAL",
    )

    try:
        client.connect()
        values = client.read_series(series_var, count=5)
        print(f"连续读取结果: {values}")
    finally:
        client.disconnect()


def example_scanner_handshake_flow(barcode_text: str = "SAMPLE_BARCODE_001") -> None:
    """
    更贴近你现在项目的示例流程：
    1. 把扫码结果写到 PLC
    2. 把开始信号写 1
    3. 等待 PLC 把完成信号写 1
    """
    client = create_client()
    barcode = barcode_variable()
    start_signal = start_signal_variable()
    complete_signal = complete_signal_variable()

    try:
        client.connect()

        client.write_value(barcode, barcode_text)
        print(
            "已写入扫码结果: "
            f"{barcode_text} -> DB{barcode.db_number}.DBB{barcode.start} ({barcode.data_type})"
        )

        client.write_bool(start_signal, True)
        print(
            "已将开始信号置 1: "
            f"DB{start_signal.db_number}.DBX{start_signal.start}.{start_signal.bit_index}"
        )

        print("开始等待 PLC 完成信号...")
        for _ in range(50):
            completed = bool(round(client.read_value(complete_signal)))
            if completed:
                print(
                    "已收到 PLC 完成信号: "
                    f"DB{complete_signal.db_number}.DBX{complete_signal.start}.{complete_signal.bit_index}"
                )
                return
            time.sleep(0.1)

        print("等待超时: 5 秒内未收到 PLC 完成信号。")
    finally:
        client.disconnect()


def print_quick_start() -> None:
    """打印快速说明。"""
    print(__doc__.strip())
    print()
    print("推荐你先改这几个参数：")
    print(f"PLC_IP = {PLC_IP}")
    print(f"RACK = {RACK}")
    print(f"SLOT = {SLOT}")
    print(f"BARCODE_DB = {BARCODE_DB}")
    print(f"BARCODE_START = {BARCODE_START}")
    print(f"START_SIGNAL_DB = {START_SIGNAL_DB}")
    print(f"START_SIGNAL_START = {START_SIGNAL_START}")
    print(f"START_SIGNAL_BIT = {START_SIGNAL_BIT}")
    print(f"COMPLETE_SIGNAL_DB = {COMPLETE_SIGNAL_DB}")
    print(f"COMPLETE_SIGNAL_START = {COMPLETE_SIGNAL_START}")
    print(f"COMPLETE_SIGNAL_BIT = {COMPLETE_SIGNAL_BIT}")
    print()
    print("常用调用入口：")
    print("1. 只测连接: example_connect_only()")
    print("2. 读一个值: example_minimal_read()")
    print("3. 读字符串: example_read_text()")
    print("4. 写扫码结果并等待完成信号: example_scanner_handshake_flow()")
    print()
    print("这个文件默认不会自动执行读写动作。")
    print("你可以在 Python 里 import 它，也可以直接打开后手动调用示例函数。")


if __name__ == "__main__":
    print_quick_start()
