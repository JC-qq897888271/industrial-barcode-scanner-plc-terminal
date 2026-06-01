from __future__ import annotations

import ctypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform
import queue
import sys
import tempfile
import threading
import time
import traceback
from datetime import datetime
from typing import Optional

import serial
from serial.tools import list_ports
from plc_comm import PLCVariable, SiemensPLCClient, SUPPORTED_DATA_TYPES

if sys.platform.startswith("win"):
    os.environ.setdefault("QT_OPENGL", "software")
    os.environ.setdefault("QT_ANGLE_PLATFORM", "software")

try:
    from PyQt5.QtCore import QLockFile, QEasingCurve, QPoint, QPropertyAnimation, QTimer, Qt
    from PyQt5.QtGui import QColor, QFont, QPainter, QPolygon, QTextCursor
    from PyQt5.QtWidgets import (
        QApplication,
        QAbstractSpinBox,
        QCheckBox,
        QComboBox,
        QDoubleSpinBox,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QSpinBox,
        QSizePolicy,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    from PySide6.QtCore import QLockFile, QEasingCurve, QPoint, QPropertyAnimation, QTimer, Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPolygon, QTextCursor
    from PySide6.QtWidgets import (
        QApplication,
        QAbstractSpinBox,
        QCheckBox,
        QComboBox,
        QDoubleSpinBox,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QSpinBox,
        QSizePolicy,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )


OUT_CUBIC = QEasingCurve.OutCubic if hasattr(QEasingCurve, "OutCubic") else QEasingCurve.Type.OutCubic
UP_DOWN_ARROWS = (
    QAbstractSpinBox.UpDownArrows
    if hasattr(QAbstractSpinBox, "UpDownArrows")
    else QAbstractSpinBox.ButtonSymbols.UpDownArrows
)
NO_BUTTONS = (
    QAbstractSpinBox.NoButtons
    if hasattr(QAbstractSpinBox, "NoButtons")
    else QAbstractSpinBox.ButtonSymbols.NoButtons
)
SINGLE_INSTANCE_LOCK_PATH = Path(tempfile.gettempdir()) / "barcode_scanner_qt_single_instance.lock"
STARTUP_LOG_FILE_NAME = "startup.log"

APP_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #0B111B;
    color: #F2F5FA;
    font-family: "Microsoft YaHei UI";
    font-size: 15px;
}

QFrame#toolbarCard,
QFrame#resultsCard,
QFrame#drawerPanel {
    background-color: #182231;
    border: 1px solid #31445D;
    border-radius: 18px;
}

QFrame#drawerCard {
    background-color: #0F1722;
    border: 1px solid #425974;
    border-radius: 16px;
}

QLabel#eyebrowLabel {
    color: #8EA2BD;
    font-size: 13px;
    letter-spacing: 1px;
}

QLabel#titleLabel {
    color: #F6F8FC;
    font-size: 30px;
    font-weight: 700;
}

QLabel#sectionTitle {
    color: #F3B53A;
    font-size: 20px;
    font-weight: 700;
}

QLabel#valueLabel {
    color: #F3B53A;
    font-size: 28px;
    font-weight: 700;
}

QLabel#subtleLabel {
    color: #93A6C1;
}

QPushButton {
    min-height: 20px;
    padding: 10px 18px;
    background-color: #1A2736;
    color: #F2F5FA;
    border: 1px solid #425974;
    border-radius: 12px;
    font-weight: 600;
}

QPushButton:hover {
    border-color: #F3B53A;
}

QPushButton:pressed {
    background-color: #223246;
}

QPushButton#accentButton {
    background-color: #F3B53A;
    color: #101722;
    border: 1px solid #F3B53A;
}

QPushButton#accentButton:hover {
    background-color: #FFC85A;
    border-color: #FFC85A;
}

QPushButton#secondaryButton {
    background-color: #0F1722;
}

QComboBox,
QLineEdit,
QSpinBox,
QDoubleSpinBox,
QPlainTextEdit {
    background-color: #0F1722;
    border: 1px solid #425974;
    border-radius: 12px;
    padding: 10px 14px;
    selection-background-color: #F3B53A;
    selection-color: #101722;
}

QComboBox::drop-down {
    width: 28px;
    border: none;
    background: transparent;
}

QSpinBox::up-button,
QSpinBox::down-button,
QDoubleSpinBox::up-button,
QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    width: 28px;
    border-left: 1px solid #425974;
    background-color: #182231;
}

QSpinBox::up-button,
QDoubleSpinBox::up-button {
    subcontrol-position: top right;
    border-top-right-radius: 11px;
    border-bottom: 1px solid #425974;
}

QSpinBox::down-button,
QDoubleSpinBox::down-button {
    subcontrol-position: bottom right;
    border-bottom-right-radius: 11px;
}

QSpinBox::up-button:hover,
QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover,
QDoubleSpinBox::down-button:hover {
    background-color: #223246;
}

QSpinBox::up-arrow,
QSpinBox::down-arrow,
QDoubleSpinBox::up-arrow,
QDoubleSpinBox::down-arrow {
    width: 10px;
    height: 10px;
}

QComboBox QAbstractItemView {
    background-color: #101722;
    color: #F2F5FA;
    border: 1px solid #425974;
    selection-background-color: #F3B53A;
    selection-color: #101722;
}

QCheckBox {
    color: #DEE6F0;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid #425974;
    background: #0F1722;
}

QCheckBox::indicator:checked {
    background: #F3B53A;
    border-color: #F3B53A;
}

QScrollBar:vertical {
    background: #101722;
    width: 12px;
    margin: 4px;
    border-radius: 6px;
}

QScrollBar::handle:vertical {
    background: #415774;
    min-height: 36px;
    border-radius: 6px;
}

QScrollBar::handle:vertical:hover {
    background: #F3B53A;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: none;
    border: none;
}

QToolButton#spinUpButton,
QToolButton#spinDownButton {
    background-color: #182231;
    color: #F2F5FA;
    border-left: 1px solid #425974;
    padding: 0px;
    font-size: 11px;
    font-weight: 700;
}

QToolButton#spinUpButton {
    border-top-right-radius: 11px;
    border-bottom: 1px solid #425974;
}

QToolButton#spinDownButton {
    border-bottom-right-radius: 11px;
}

QToolButton#spinUpButton:hover,
QToolButton#spinDownButton:hover {
    background-color: #223246;
    color: #F3B53A;
}
"""

PLC_RECONNECT_INTERVAL_SECONDS = 3.0
PLC_POLL_INTERVAL_SECONDS = 0.25
PLC_PULSE_SECONDS = 0.20
COM_RECONNECT_INTERVAL_SECONDS = 3.0


@dataclass(frozen=True)
class PLCSignalConfig:
    name: str
    db_number: int
    byte_offset: int
    bit_index: int
    auto_reset: bool = True

    def to_variable(self) -> PLCVariable:
        return PLCVariable(
            name=self.name,
            db_number=self.db_number,
            start=self.byte_offset,
            data_type="BOOL",
            bit_index=self.bit_index,
        )


@dataclass(frozen=True)
class PLCConnectionConfig:
    ip_address: str
    rack: int
    slot: int
    start_signal: PLCSignalConfig
    complete_signal: PLCSignalConfig


@dataclass(frozen=True)
class PLCDataTargetConfig:
    display_text: str
    variable: PLCVariable
    enabled: bool = True


@dataclass(frozen=True)
class PLCHeartbeatConfig:
    display_text: str
    variable: PLCVariable
    value_on: str
    value_off: str
    interval_on_seconds: float
    interval_off_seconds: float
    enabled: bool = False


class PLCAddressError(RuntimeError):
    pass


class PLCWorkerThread(threading.Thread):
    def __init__(self, config: PLCConnectionConfig, output_queue: queue.Queue, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.config = config
        self.output_queue = output_queue
        self.stop_event = stop_event
        self.command_queue: queue.Queue = queue.Queue()
        self.client: Optional[SiemensPLCClient] = None
        self.last_start_value: Optional[bool] = None
        self.last_complete_value: Optional[bool] = None
        self.heartbeat_config: Optional[PLCHeartbeatConfig] = None
        self.heartbeat_is_high = False
        self.heartbeat_next_toggle_at = 0.0

    def request_complete_pulse(self) -> None:
        self.command_queue.put(("pulse_complete", None))

    def request_write_scan_data(self, target_config: PLCDataTargetConfig, scan_text: str) -> None:
        self.command_queue.put(("write_scan_data", (target_config, scan_text)))

    def request_update_heartbeat(self, heartbeat_config: PLCHeartbeatConfig) -> None:
        self.command_queue.put(("update_heartbeat", heartbeat_config))

    def run(self) -> None:
        while not self.stop_event.is_set():
            self._drain_commands()

            if not self._ensure_connected():
                continue

            try:
                self._poll_start_signal()
                self._poll_complete_signal()
                self._drain_commands()
                self._process_heartbeat()
            except PLCAddressError as exc:
                self.output_queue.put(("plc_error", str(exc)))
                self.stop_event.set()
                break
            except Exception as exc:
                self.output_queue.put(
                    (
                        "plc_disconnected",
                        f"检测到 PLC 断线: {exc}，{int(PLC_RECONNECT_INTERVAL_SECONDS)} 秒后自动重连。",
                    )
                )
                self._reset_client()
                self._sleep_with_stop(PLC_RECONNECT_INTERVAL_SECONDS)
                continue

            self._sleep_with_stop(PLC_POLL_INTERVAL_SECONDS)

        self._reset_client()

    def _ensure_connected(self) -> bool:
        if self.client is not None and self.client.is_connected:
            return True

        try:
            self.client = SiemensPLCClient(self.config.ip_address, self.config.rack, self.config.slot)
            self.client.connect()
            self.last_start_value = None
            self.last_complete_value = None
            self._reset_heartbeat_runtime()
            self.output_queue.put(
                (
                    "plc_connected",
                    f"已连接 PLC {self.config.ip_address} (Rack {self.config.rack}, Slot {self.config.slot})",
                )
            )
            return True
        except ValueError as exc:
            self.output_queue.put(("plc_error", f"PLC 配置无效: {exc}"))
            self.stop_event.set()
            return False
        except RuntimeError as exc:
            if "python-snap7" in str(exc):
                self.output_queue.put(("plc_error", f"PLC 环境无效: {exc}"))
                self.stop_event.set()
                return False
            self.output_queue.put(
                (
                    "plc_status",
                    f"PLC 连接失败: {exc}，{int(PLC_RECONNECT_INTERVAL_SECONDS)} 秒后自动重连。",
                )
            )
            self._reset_client()
            self._sleep_with_stop(PLC_RECONNECT_INTERVAL_SECONDS)
            return False
        except Exception as exc:
            self.output_queue.put(
                (
                    "plc_status",
                    f"PLC 连接失败: {exc}，{int(PLC_RECONNECT_INTERVAL_SECONDS)} 秒后自动重连。",
                )
            )
            self._reset_client()
            self._sleep_with_stop(PLC_RECONNECT_INTERVAL_SECONDS)
            return False

    def _poll_start_signal(self) -> None:
        start_variable = self.config.start_signal.to_variable()
        try:
            start_value = bool(round(self.client.read_value(start_variable)))
        except Exception as exc:
            self._raise_if_address_unavailable(exc, start_variable, "开始信号")
            raise

        if self.last_start_value is None:
            self.last_start_value = start_value
            return

        if start_value and not self.last_start_value:
            if self.config.start_signal.auto_reset:
                try:
                    self.client.write_bool(start_variable, False)
                except Exception as exc:
                    self._raise_if_address_unavailable(exc, start_variable, "开始信号")
                    raise
                start_value = False
            self.output_queue.put(("plc_start_signal", "已收到 PLC 开始信号"))

        self.last_start_value = start_value

    def _poll_complete_signal(self) -> None:
        complete_variable = self.config.complete_signal.to_variable()
        try:
            complete_value = bool(round(self.client.read_value(complete_variable)))
        except Exception as exc:
            self._raise_if_address_unavailable(exc, complete_variable, "完成信号")
            raise

        if self.last_complete_value is None:
            self.last_complete_value = complete_value
            return

        if complete_value and not self.last_complete_value:
            if self.config.complete_signal.auto_reset:
                try:
                    self.client.write_bool(complete_variable, False)
                except Exception as exc:
                    self._raise_if_address_unavailable(exc, complete_variable, "完成信号")
                    raise
                complete_value = False
            self.output_queue.put(("plc_complete_signal", "已收到 PLC 完成信号"))

        self.last_complete_value = complete_value

    def _drain_commands(self) -> None:
        while True:
            try:
                command, payload = self.command_queue.get_nowait()
            except queue.Empty:
                return

            if command == "pulse_complete":
                self._pulse_complete_signal()
            elif command == "write_scan_data":
                self._write_scan_data(*payload)
            elif command == "update_heartbeat":
                self._update_heartbeat_config(payload)

    def _pulse_complete_signal(self) -> None:
        if self.client is None or not self.client.is_connected:
            self.output_queue.put(("plc_error", "PLC 未连接，无法处理完成信号命令。"))
            return

    def _update_heartbeat_config(self, heartbeat_config: PLCHeartbeatConfig) -> None:
        self.heartbeat_config = heartbeat_config if heartbeat_config.enabled else None
        self._reset_heartbeat_runtime()

    def _reset_heartbeat_runtime(self) -> None:
        self.heartbeat_is_high = False
        self.heartbeat_next_toggle_at = 0.0

    def _process_heartbeat(self) -> None:
        config = self.heartbeat_config
        if config is None or self.client is None or not self.client.is_connected:
            return

        now = time.monotonic()
        if self.heartbeat_next_toggle_at and now < self.heartbeat_next_toggle_at:
            return

        variable = config.variable
        raw_value = config.value_on if not self.heartbeat_is_high else config.value_off
        wait_seconds = config.interval_on_seconds if not self.heartbeat_is_high else config.interval_off_seconds

        try:
            value = self._coerce_scan_value(raw_value, variable)
            self.client.write_value(variable, value)
        except Exception as exc:
            try:
                self._raise_if_address_unavailable(exc, variable, "心跳信号")
            except PLCAddressError as address_exc:
                self.heartbeat_config = None
                self.output_queue.put(("heartbeat_error", str(address_exc)))
                return

            if isinstance(exc, ValueError):
                self.heartbeat_config = None
                self.output_queue.put(("heartbeat_error", f"心跳设置无效: {exc}"))
                return
            raise

        self.heartbeat_is_high = not self.heartbeat_is_high
        self.heartbeat_next_toggle_at = now + max(0.1, float(wait_seconds))

    def _write_scan_data(self, target_config: PLCDataTargetConfig, scan_text: str) -> None:
        if not target_config.enabled:
            return
        if self.client is None or not self.client.is_connected:
            self.output_queue.put(("plc_data_error", "PLC 未连接，本次扫码数据未写入。"))
            return

        try:
            variable = target_config.variable
            value = self._coerce_scan_value(scan_text, variable)
            self.client.write_value(variable, value)
            start_signal_text = self._write_start_signal_after_scan()
            target_text = self._format_target(variable)
            self.output_queue.put(
                (
                    "plc_data_written",
                    f"已写入 {target_config.display_text} -> {target_text}，{start_signal_text}",
                )
            )
        except Exception as exc:
            self.output_queue.put(("plc_data_error", f"扫码数据写入 PLC 失败: {exc}"))

    def _write_start_signal_after_scan(self) -> str:
        start_variable = self.config.start_signal.to_variable()
        try:
            self.client.write_bool(start_variable, True)
        except Exception as exc:
            self._raise_if_address_unavailable(exc, start_variable, "开始信号")
            raise

        final_value = True
        if self.config.start_signal.auto_reset:
            self._sleep_with_stop(PLC_PULSE_SECONDS)
            try:
                self.client.write_bool(start_variable, False)
            except Exception as exc:
                self._raise_if_address_unavailable(exc, start_variable, "开始信号")
                raise
            final_value = False

        # 同步内部状态，避免软件自己写出的开始信号再次被轮询逻辑误判成外部触发。
        self.last_start_value = final_value

        start_target_text = self._format_target(start_variable)
        if self.config.start_signal.auto_reset:
            return f"并将开始信号 {start_target_text} 置 1 后自动置 0"
        return f"并将开始信号 {start_target_text} 置 1"

    @staticmethod
    def _coerce_scan_value(scan_text: str, variable: PLCVariable):
        text = scan_text.strip()
        data_type = variable.normalized_type()

        if data_type == "S7STRING":
            return text
        if data_type == "BOOL":
            lowered = text.lower()
            if lowered in {"1", "true", "on", "yes"}:
                return True
            if lowered in {"0", "false", "off", "no"}:
                return False
            raise ValueError(f"无法将 '{scan_text}' 写入 BOOL，可用 1/0 或 true/false。")
        if data_type == "REAL":
            return float(text)
        if data_type in {"INT", "DINT", "WORD", "DWORD", "BYTE"}:
            return int(float(text))
        raise ValueError(f"暂不支持的写入类型: {data_type}")

    @staticmethod
    def _format_target(variable: PLCVariable) -> str:
        data_type = variable.normalized_type()
        if data_type == "BOOL":
            return f"DB{variable.db_number}.DBX{variable.start}.{variable.bit_index} ({data_type})"
        if data_type in {"INT", "WORD"}:
            area = "DBW"
        elif data_type in {"REAL", "DINT", "DWORD"}:
            area = "DBD"
        else:
            area = "DBB"
        return f"DB{variable.db_number}.{area}{variable.start} ({data_type})"

    @staticmethod
    def _is_address_unavailable_error(exc: Exception) -> bool:
        message = str(exc).lower()
        keywords = (
            "item not available",
            "address out of range",
            "object does not exist",
            "db not found",
            "cpu : item not available",
        )
        return any(keyword in message for keyword in keywords)

    @classmethod
    def _raise_if_address_unavailable(cls, exc: Exception, variable: PLCVariable, label: str) -> None:
        if not cls._is_address_unavailable_error(exc):
            return
        target_text = cls._format_target(variable)
        raise PLCAddressError(
            f"{label}地址不可用: {target_text}，请检查 Rack/Slot、DB/字节/位，"
            "并确认 PLC 已开启 PUT/GET 且目标 DB 允许非优化访问。"
        ) from exc

    def _sleep_with_stop(self, duration: float) -> None:
        end_time = time.time() + duration
        while time.time() < end_time and not self.stop_event.is_set():
            time.sleep(0.05)

    def _reset_client(self) -> None:
        if self.client is None:
            return

        try:
            self.client.disconnect()
        except Exception:
            pass
        finally:
            self.client = None


class StepSpinBox(QSpinBox):
    def __init__(self) -> None:
        super().__init__()
        # Compatibility mode: use Qt's native spin buttons instead of custom-painted controls.
        self.setButtonSymbols(UP_DOWN_ARROWS)


class StepDoubleSpinBox(QDoubleSpinBox):
    def __init__(self) -> None:
        super().__init__()
        # Compatibility mode: use Qt's native spin buttons instead of custom-painted controls.
        self.setButtonSymbols(UP_DOWN_ARROWS)


class SerialReaderThread(threading.Thread):
    def __init__(self, port: str, baudrate: int, output_queue: queue.Queue, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.port = port
        self.baudrate = baudrate
        self.output_queue = output_queue
        self.stop_event = stop_event
        self.serial_port: Optional[serial.Serial] = None

    def run(self) -> None:
        try:
            self.serial_port = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.2,
            )
            self.output_queue.put(("status", f"已连接 {self.port} @ {self.baudrate}"))
        except Exception as exc:
            self.output_queue.put(("error", f"打开串口失败: {exc}"))
            return

        buffer = bytearray()
        last_byte_time = 0.0

        try:
            while not self.stop_event.is_set():
                chunk = self.serial_port.read(self.serial_port.in_waiting or 1)
                if chunk:
                    buffer.extend(chunk)
                    last_byte_time = time.time()
                    self._emit_complete_frames(buffer)
                    continue

                if buffer and last_byte_time and time.time() - last_byte_time > 0.25:
                    self._emit_scan(bytes(buffer), source="idle-flush")
                    buffer.clear()
        except Exception as exc:
            self.output_queue.put(("error", f"读取串口失败: {exc}"))
        finally:
            if self.serial_port and self.serial_port.is_open:
                try:
                    self.serial_port.close()
                except Exception:
                    pass
            self.output_queue.put(("status", "串口已断开"))

    def _emit_complete_frames(self, buffer: bytearray) -> None:
        while True:
            end_index = self._find_terminator(buffer)
            if end_index < 0:
                return

            payload = bytes(buffer[:end_index])
            skip = 1
            if end_index + 1 < len(buffer):
                current = buffer[end_index]
                nxt = buffer[end_index + 1]
                if (current, nxt) in ((13, 10), (10, 13)):
                    skip = 2

            del buffer[: end_index + skip]
            if payload:
                self._emit_scan(payload, source="line")

    @staticmethod
    def _find_terminator(buffer: bytearray) -> int:
        for index, value in enumerate(buffer):
            if value in (10, 13):
                return index
        return -1

    def _emit_scan(self, payload: bytes, source: str) -> None:
        try:
            text = payload.decode("utf-8").strip()
        except UnicodeDecodeError:
            text = payload.decode("gbk", errors="replace").strip()

        self.output_queue.put(
            (
                "scan",
                {
                    "text": text,
                    "hex": payload.hex(" ").upper(),
                    "length": len(payload),
                    "source": source,
                },
            )
        )


class ScannerWindow(QMainWindow):
    DRAWER_WIDTH = 520
    SERIAL_SECTION_HEIGHT = 156
    DATA_SECTION_HEIGHT = 280
    HEARTBEAT_SECTION_HEIGHT = 420
    DEFAULT_BAUDRATE = 9600
    SETTINGS_FILE_NAME = "scanner_settings.json"

    def __init__(self) -> None:
        super().__init__()
        self.output_queue: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.reader_thread: Optional[SerialReaderThread] = None
        self.plc_stop_event: Optional[threading.Event] = None
        self.plc_thread: Optional[PLCWorkerThread] = None
        self.port_options: dict[str, str] = {}
        self.settings_path = Path(__file__).resolve().with_name(self.SETTINGS_FILE_NAME)
        self.preferred_port_device = ""
        self._suspend_auto_save = True
        self.com_manual_disconnect = False
        self.drawer_open = False
        self.serial_section_open = False
        self.data_section_open = False
        self.heartbeat_section_open = False
        self.plc_connected = False
        self.awaiting_plc_completion = False

        self.setWindowTitle("工业扫码枪 PLC 终端")
        self.resize(1180, 720)

        self._build_ui()
        self._bind_plc_auto_save_signals()
        self._load_settings_from_json()
        self._apply_data_target_settings(save_to_disk=False)
        self._apply_heartbeat_settings(save_to_disk=False, push_to_runtime=False)
        self.serial_section_height = max(
            self.SERIAL_SECTION_HEIGHT, self.serial_section_body.layout().sizeHint().height() + 4
        )
        self.serial_section_body.setMaximumHeight(self.serial_section_height if self.serial_section_open else 0)
        self.data_section_height = max(self.DATA_SECTION_HEIGHT, self.data_section_body.layout().sizeHint().height() + 4)
        self.data_section_body.setMaximumHeight(self.data_section_height if self.data_section_open else 0)
        self.heartbeat_section_height = max(
            self.HEARTBEAT_SECTION_HEIGHT, self.heartbeat_section_body.layout().sizeHint().height() + 4
        )
        self.heartbeat_section_body.setMaximumHeight(
            self.heartbeat_section_height if self.heartbeat_section_open else 0
        )
        self.drawer_open_width = max(self.DRAWER_WIDTH, self.drawer_content.layout().sizeHint().width() + 36)
        self.refresh_ports()
        self._suspend_auto_save = False

        self.queue_timer = QTimer(self)
        self.queue_timer.timeout.connect(self.process_queue)
        self.queue_timer.start(100)

        self.com_reconnect_timer = QTimer(self)
        self.com_reconnect_timer.setSingleShot(True)
        self.com_reconnect_timer.timeout.connect(self._attempt_com_reconnect)

        self.drawer_animation = QPropertyAnimation(self.drawer_panel, b"maximumWidth", self)
        self.drawer_animation.setDuration(220)
        self.drawer_animation.setEasingCurve(OUT_CUBIC)

        self.serial_section_animation = QPropertyAnimation(self.serial_section_body, b"maximumHeight", self)
        self.serial_section_animation.setDuration(180)
        self.serial_section_animation.setEasingCurve(OUT_CUBIC)

        self.data_section_animation = QPropertyAnimation(self.data_section_body, b"maximumHeight", self)
        self.data_section_animation.setDuration(180)
        self.data_section_animation.setEasingCurve(OUT_CUBIC)

        self.heartbeat_section_animation = QPropertyAnimation(self.heartbeat_section_body, b"maximumHeight", self)
        self.heartbeat_section_animation.setDuration(180)
        self.heartbeat_section_animation.setEasingCurve(OUT_CUBIC)

        QTimer.singleShot(250, self._auto_connect_devices)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        page = QHBoxLayout(root)
        page.setContentsMargins(16, 16, 16, 16)
        page.setSpacing(16)

        self.drawer_panel = QFrame()
        self.drawer_panel.setObjectName("drawerPanel")
        self.drawer_panel.setMinimumWidth(0)
        self.drawer_panel.setMaximumWidth(0)
        self.drawer_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        page.addWidget(self.drawer_panel)

        drawer_panel_layout = QVBoxLayout(self.drawer_panel)
        drawer_panel_layout.setContentsMargins(0, 0, 0, 0)
        drawer_panel_layout.setSpacing(0)

        self.drawer_scroll_area = QScrollArea()
        self.drawer_scroll_area.setWidgetResizable(True)
        self.drawer_scroll_area.setFrameShape(QFrame.NoFrame)
        self.drawer_scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        drawer_panel_layout.addWidget(self.drawer_scroll_area)

        self.drawer_content = QWidget()
        self.drawer_scroll_area.setWidget(self.drawer_content)

        drawer_layout = QVBoxLayout(self.drawer_content)
        drawer_layout.setContentsMargins(18, 18, 18, 18)
        drawer_layout.setSpacing(14)

        drawer_title = QLabel("设置")
        drawer_title.setObjectName("sectionTitle")
        drawer_layout.addWidget(drawer_title)

        drawer_hint = QLabel("保持原来的左侧设置栏逻辑，串口设置这一项现在支持收起和展开。")
        drawer_hint.setWordWrap(True)
        drawer_hint.setObjectName("subtleLabel")
        drawer_layout.addWidget(drawer_hint)

        self._build_plc_panel(drawer_layout)

        drawer_card = QFrame()
        drawer_card.setObjectName("drawerCard")
        drawer_layout.addWidget(drawer_card)

        drawer_card_layout = QVBoxLayout(drawer_card)
        drawer_card_layout.setContentsMargins(16, 16, 16, 16)
        drawer_card_layout.setSpacing(12)

        self.serial_section_button = QPushButton("串口设置 ▼")
        self.serial_section_button.setObjectName("secondaryButton")
        self.serial_section_button.clicked.connect(self.toggle_serial_settings)
        drawer_card_layout.addWidget(self.serial_section_button)

        self.serial_section_body = QFrame()
        self.serial_section_body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.serial_section_body.setMinimumHeight(0)
        drawer_card_layout.addWidget(self.serial_section_body)

        serial_body_layout = QVBoxLayout(self.serial_section_body)
        serial_body_layout.setContentsMargins(0, 0, 0, 0)
        serial_body_layout.setSpacing(12)

        port_label = QLabel("COM 端口")
        port_label.setObjectName("sectionTitle")
        serial_body_layout.addWidget(port_label)

        drawer_hint = QLabel("在这里选择扫码枪 COM 口，并完成连接或断开。")
        drawer_hint.setWordWrap(True)
        drawer_hint.setObjectName("subtleLabel")
        serial_body_layout.addWidget(drawer_hint)

        self.port_combo = QComboBox()
        self.port_combo.setPlaceholderText("未发现可用串口")
        serial_body_layout.addWidget(self.port_combo)

        row_actions = QHBoxLayout()
        row_actions.setSpacing(10)
        serial_body_layout.addLayout(row_actions)

        self.refresh_button = QPushButton("刷新串口")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.clicked.connect(self.refresh_ports)
        row_actions.addWidget(self.refresh_button)

        self.connect_button = QPushButton("连接设备")
        self.connect_button.setObjectName("accentButton")
        self.connect_button.clicked.connect(self.toggle_connection)
        row_actions.addWidget(self.connect_button)

        baud_hint = QLabel(f"波特率固定为 {self.DEFAULT_BAUDRATE}")
        baud_hint.setObjectName("subtleLabel")
        serial_body_layout.addWidget(baud_hint)

        self.apply_serial_settings_button = QPushButton("应用参数")
        self.apply_serial_settings_button.setObjectName("accentButton")
        self.apply_serial_settings_button.clicked.connect(self.apply_serial_settings)
        serial_body_layout.addWidget(self.apply_serial_settings_button)

        self._build_data_panel(drawer_layout)
        self._build_heartbeat_panel(drawer_layout)

        drawer_layout.addStretch(1)

        self.content_panel = QFrame()
        self.content_panel.setObjectName("contentPanel")
        page.addWidget(self.content_panel, 1)

        content_layout = QVBoxLayout(self.content_panel)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)

        toolbar = QFrame()
        toolbar.setObjectName("toolbarCard")
        content_layout.addWidget(toolbar)

        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(18, 14, 18, 14)
        toolbar_layout.setSpacing(14)

        self.settings_button = QPushButton("设置")
        self.settings_button.clicked.connect(self.toggle_drawer)
        toolbar_layout.addWidget(self.settings_button)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        eyebrow = QLabel("工业扫码枪 PLC 终端")
        eyebrow.setObjectName("eyebrowLabel")
        title_box.addWidget(eyebrow)

        title = QLabel("工业扫码监控终端")
        title.setObjectName("titleLabel")
        title_box.addWidget(title)
        toolbar_layout.addLayout(title_box, 1)

        status_box = QHBoxLayout()
        status_box.setSpacing(8)
        toolbar_layout.addLayout(status_box)

        self.com_connection_chip = QLabel()
        self._set_com_connection_chip("未连接", "idle")
        status_box.addWidget(self.com_connection_chip)

        self.plc_connection_chip = QLabel()
        self._set_plc_connection_chip("未连接", "idle")
        status_box.addWidget(self.plc_connection_chip)

        results_card = QFrame()
        results_card.setObjectName("resultsCard")
        content_layout.addWidget(results_card, 1)

        results_layout = QVBoxLayout(results_card)
        results_layout.setContentsMargins(18, 18, 18, 18)
        results_layout.setSpacing(14)

        results_header = QHBoxLayout()
        results_header.setSpacing(12)
        results_layout.addLayout(results_header)

        results_title_box = QVBoxLayout()
        results_title_box.setSpacing(4)
        results_header.addLayout(results_title_box, 1)

        results_title = QLabel("扫码结果")
        results_title.setObjectName("sectionTitle")
        results_title_box.addWidget(results_title)

        self.last_scan_label = QLabel("等待扫码")
        self.last_scan_label.setObjectName("valueLabel")
        results_title_box.addWidget(self.last_scan_label)

        controls_box = QHBoxLayout()
        controls_box.setSpacing(10)
        results_header.addLayout(controls_box)

        self.debug_checkbox = QCheckBox("显示调试信息")
        controls_box.addWidget(self.debug_checkbox)

        self.clear_button = QPushButton("清空输出")
        self.clear_button.setObjectName("secondaryButton")
        self.clear_button.clicked.connect(self.clear_output)
        controls_box.addWidget(self.clear_button)

        self.output_text = QPlainTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setPlaceholderText("当前状态：等待连接设备")
        self.output_text.setFont(QFont("Consolas", 11))
        results_layout.addWidget(self.output_text, 1)

        self.status_label = QLabel("未连接")
        self.status_label.setObjectName("subtleLabel")
        results_layout.addWidget(self.status_label)

    def _build_plc_panel(self, drawer_layout: QVBoxLayout) -> None:
        plc_card = QFrame()
        plc_card.setObjectName("drawerCard")
        drawer_layout.addWidget(plc_card)

        plc_layout = QVBoxLayout(plc_card)
        plc_layout.setContentsMargins(16, 16, 16, 16)
        plc_layout.setSpacing(12)

        plc_title = QLabel("PLC 通讯")
        plc_title.setObjectName("sectionTitle")
        plc_layout.addWidget(plc_title)

        plc_hint = QLabel("断线后会自动重连，保留一组开始信号和完成信号。")
        plc_hint.setWordWrap(True)
        plc_hint.setObjectName("subtleLabel")
        plc_layout.addWidget(plc_hint)

        self.plc_ip_input = QLineEdit("127.0.0.1")
        plc_layout.addLayout(self._create_plc_value_row("PLC IP", self.plc_ip_input))

        self.plc_rack_spin = self._create_spin_box(0, 7, 0)
        plc_layout.addLayout(self._create_plc_value_row("机架", self.plc_rack_spin))

        self.plc_slot_spin = self._create_spin_box(0, 31, 1)
        plc_layout.addLayout(self._create_plc_value_row("插槽", self.plc_slot_spin))

        (
            self.start_signal_db_spin,
            self.start_signal_byte_spin,
            self.start_signal_bit_spin,
            self.start_signal_reset_check,
        ) = self._build_plc_signal_row(plc_layout, "开始信号", 6100, 2, 0, True)

        (
            self.complete_signal_db_spin,
            self.complete_signal_byte_spin,
            self.complete_signal_bit_spin,
            self.complete_signal_reset_check,
        ) = self._build_plc_signal_row(plc_layout, "完成信号", 6100, 2, 1, True)

        plc_button_row = QHBoxLayout()
        plc_button_row.setSpacing(10)
        plc_layout.addLayout(plc_button_row)

        self.plc_connect_button = QPushButton("连接 PLC")
        self.plc_connect_button.setObjectName("accentButton")
        self.plc_connect_button.clicked.connect(self.connect_plc)
        plc_button_row.addWidget(self.plc_connect_button)

        self.plc_disconnect_button = QPushButton("断开 PLC")
        self.plc_disconnect_button.setObjectName("secondaryButton")
        self.plc_disconnect_button.clicked.connect(self.disconnect_plc)
        self.plc_disconnect_button.setEnabled(False)
        plc_button_row.addWidget(self.plc_disconnect_button)

        self.plc_status_label = QLabel("未连接 PLC")
        self.plc_status_label.setWordWrap(True)
        self.plc_status_label.setObjectName("subtleLabel")
        plc_layout.addWidget(self.plc_status_label)

    def _build_data_panel(self, drawer_layout: QVBoxLayout) -> None:
        data_card = QFrame()
        data_card.setObjectName("drawerCard")
        drawer_layout.addWidget(data_card)

        data_layout = QVBoxLayout(data_card)
        data_layout.setContentsMargins(16, 16, 16, 16)
        data_layout.setSpacing(12)

        self.data_section_button = QPushButton("数据设置 ▼")
        self.data_section_button.setObjectName("secondaryButton")
        self.data_section_button.clicked.connect(self.toggle_data_settings)
        data_layout.addWidget(self.data_section_button)

        self.data_section_body = QFrame()
        self.data_section_body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.data_section_body.setMinimumHeight(0)
        data_layout.addWidget(self.data_section_body)

        data_body_layout = QVBoxLayout(self.data_section_body)
        data_body_layout.setContentsMargins(0, 0, 0, 0)
        data_body_layout.setSpacing(12)

        data_title = QLabel("扫码结果写入 PLC")
        data_title.setObjectName("sectionTitle")
        data_body_layout.addWidget(data_title)

        data_hint = QLabel("扫码完成后，可将结果写入指定 PLC DB 块地址。")
        data_hint.setWordWrap(True)
        data_hint.setObjectName("subtleLabel")
        data_body_layout.addWidget(data_hint)

        self.data_display_text_input = QLineEdit("扫码结果")
        data_body_layout.addLayout(self._create_plc_value_row("显示文字", self.data_display_text_input))

        self.data_db_spin = self._create_spin_box(1, 65535, 6100)
        data_body_layout.addLayout(self._create_plc_value_row("DB 块号", self.data_db_spin))

        self.data_start_spin = self._create_spin_box(0, 65535, 36)
        data_body_layout.addLayout(self._create_plc_value_row("起始字节", self.data_start_spin))

        self.data_type_combo = QComboBox()
        self.data_type_combo.addItems(list(SUPPORTED_DATA_TYPES))
        self.data_type_combo.setCurrentText("S7STRING")
        self.data_type_combo.currentTextChanged.connect(self._sync_data_target_controls)
        data_body_layout.addLayout(self._create_plc_value_row("数据类型", self.data_type_combo))

        self.data_bool_bit_spin = self._create_spin_box(0, 7, 0)
        data_body_layout.addLayout(self._create_plc_value_row("BOOL 位", self.data_bool_bit_spin))

        self.data_write_enabled_check = QCheckBox("启用扫码结果写入 PLC")
        self.data_write_enabled_check.setChecked(True)
        data_body_layout.addWidget(self.data_write_enabled_check)

        self.apply_data_settings_button = QPushButton("应用参数")
        self.apply_data_settings_button.setObjectName("accentButton")
        self.apply_data_settings_button.clicked.connect(self.apply_data_settings)
        data_body_layout.addWidget(self.apply_data_settings_button)

        self.data_target_status_label = QLabel("当前写入目标：未应用")
        self.data_target_status_label.setWordWrap(True)
        self.data_target_status_label.setObjectName("subtleLabel")
        data_body_layout.addWidget(self.data_target_status_label)

        self._sync_data_target_controls()

    def _build_heartbeat_panel(self, drawer_layout: QVBoxLayout) -> None:
        heartbeat_card = QFrame()
        heartbeat_card.setObjectName("drawerCard")
        drawer_layout.addWidget(heartbeat_card)

        heartbeat_layout = QVBoxLayout(heartbeat_card)
        heartbeat_layout.setContentsMargins(16, 16, 16, 16)
        heartbeat_layout.setSpacing(12)

        self.heartbeat_section_button = QPushButton("心跳设置 ▼")
        self.heartbeat_section_button.setObjectName("secondaryButton")
        self.heartbeat_section_button.clicked.connect(self.toggle_heartbeat_settings)
        heartbeat_layout.addWidget(self.heartbeat_section_button)

        self.heartbeat_section_body = QFrame()
        self.heartbeat_section_body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.heartbeat_section_body.setMinimumHeight(0)
        heartbeat_layout.addWidget(self.heartbeat_section_body)

        heartbeat_body_layout = QVBoxLayout(self.heartbeat_section_body)
        heartbeat_body_layout.setContentsMargins(0, 0, 0, 0)
        heartbeat_body_layout.setSpacing(12)

        heartbeat_title = QLabel("PLC 心跳发送")
        heartbeat_title.setObjectName("sectionTitle")
        heartbeat_body_layout.addWidget(heartbeat_title)

        heartbeat_hint = QLabel("按配置循环向指定 PLC 地址发送值 1 / 值 0，可用于在线心跳检测。")
        heartbeat_hint.setWordWrap(True)
        heartbeat_hint.setObjectName("subtleLabel")
        heartbeat_body_layout.addWidget(heartbeat_hint)

        self.heartbeat_name_input = QLineEdit("心跳")
        heartbeat_body_layout.addLayout(self._create_plc_value_row("变量名称", self.heartbeat_name_input))

        self.heartbeat_db_spin = self._create_spin_box(1, 65535, 6100)
        heartbeat_body_layout.addLayout(self._create_plc_value_row("DB 块号", self.heartbeat_db_spin))

        self.heartbeat_start_spin = self._create_spin_box(0, 65535, 0)
        heartbeat_body_layout.addLayout(self._create_plc_value_row("起始字节", self.heartbeat_start_spin))

        self.heartbeat_type_combo = QComboBox()
        self.heartbeat_type_combo.addItems(list(SUPPORTED_DATA_TYPES))
        self.heartbeat_type_combo.setCurrentText("INT")
        self.heartbeat_type_combo.currentTextChanged.connect(self._sync_heartbeat_controls)
        heartbeat_body_layout.addLayout(self._create_plc_value_row("数据类型", self.heartbeat_type_combo))

        self.heartbeat_bool_bit_spin = self._create_spin_box(0, 7, 0)
        heartbeat_body_layout.addLayout(self._create_plc_value_row("BOOL 位", self.heartbeat_bool_bit_spin))

        self.heartbeat_value_on_input = QLineEdit("1")
        heartbeat_body_layout.addLayout(self._create_plc_value_row("发送值1", self.heartbeat_value_on_input))

        self.heartbeat_value_off_input = QLineEdit("0")
        heartbeat_body_layout.addLayout(self._create_plc_value_row("发送值0", self.heartbeat_value_off_input))

        self.heartbeat_interval_on_spin = self._create_double_spin_box(0.1, 3600.0, 1.0)
        heartbeat_body_layout.addLayout(self._create_plc_value_row("发1间隔(秒)", self.heartbeat_interval_on_spin))

        self.heartbeat_interval_off_spin = self._create_double_spin_box(0.1, 3600.0, 1.0)
        heartbeat_body_layout.addLayout(self._create_plc_value_row("发0间隔(秒)", self.heartbeat_interval_off_spin))

        self.heartbeat_enabled_check = QCheckBox("启用心跳")
        self.heartbeat_enabled_check.setChecked(False)
        heartbeat_body_layout.addWidget(self.heartbeat_enabled_check)

        self.apply_heartbeat_settings_button = QPushButton("应用心跳设置")
        self.apply_heartbeat_settings_button.setObjectName("accentButton")
        self.apply_heartbeat_settings_button.clicked.connect(self.apply_heartbeat_settings)
        heartbeat_body_layout.addWidget(self.apply_heartbeat_settings_button)

        self.heartbeat_status_label = QLabel("当前心跳：未应用")
        self.heartbeat_status_label.setWordWrap(True)
        self.heartbeat_status_label.setObjectName("subtleLabel")
        heartbeat_body_layout.addWidget(self.heartbeat_status_label)

        self._sync_heartbeat_controls()

    def _create_data_target_variable(self) -> PLCVariable:
        return PLCVariable(
            name=self.data_display_text_input.text().strip() or "扫码结果",
            db_number=int(self.data_db_spin.value()),
            start=int(self.data_start_spin.value()),
            data_type=self.data_type_combo.currentText().strip(),
            bit_index=int(self.data_bool_bit_spin.value()),
        )

    def _current_data_target_config(self) -> PLCDataTargetConfig:
        variable = self._create_data_target_variable()
        variable.validate()
        return PLCDataTargetConfig(
            display_text=self.data_display_text_input.text().strip() or "扫码结果",
            variable=variable,
            enabled=self.data_write_enabled_check.isChecked(),
        )

    def _sync_data_target_controls(self) -> None:
        is_bool = self.data_type_combo.currentText().strip().upper() == "BOOL"
        self.data_bool_bit_spin.setEnabled(is_bool)

    def _create_heartbeat_variable(self) -> PLCVariable:
        return PLCVariable(
            name=self.heartbeat_name_input.text().strip() or "心跳",
            db_number=int(self.heartbeat_db_spin.value()),
            start=int(self.heartbeat_start_spin.value()),
            data_type=self.heartbeat_type_combo.currentText().strip(),
            bit_index=int(self.heartbeat_bool_bit_spin.value()),
        )

    def _current_heartbeat_config(self) -> PLCHeartbeatConfig:
        variable = self._create_heartbeat_variable()
        variable.validate()
        value_on = self.heartbeat_value_on_input.text().strip() or "1"
        value_off = self.heartbeat_value_off_input.text().strip() or "0"
        PLCWorkerThread._coerce_scan_value(value_on, variable)
        PLCWorkerThread._coerce_scan_value(value_off, variable)
        return PLCHeartbeatConfig(
            display_text=self.heartbeat_name_input.text().strip() or "心跳",
            variable=variable,
            value_on=value_on,
            value_off=value_off,
            interval_on_seconds=float(self.heartbeat_interval_on_spin.value()),
            interval_off_seconds=float(self.heartbeat_interval_off_spin.value()),
            enabled=self.heartbeat_enabled_check.isChecked(),
        )

    def _sync_heartbeat_controls(self) -> None:
        is_bool = self.heartbeat_type_combo.currentText().strip().upper() == "BOOL"
        self.heartbeat_bool_bit_spin.setEnabled(is_bool)

    def apply_heartbeat_settings(self) -> None:
        self._apply_heartbeat_settings(save_to_disk=True, push_to_runtime=True)

    def _apply_heartbeat_settings(self, save_to_disk: bool = False, push_to_runtime: bool = True) -> None:
        try:
            config = self._current_heartbeat_config()
        except Exception as exc:
            self.heartbeat_status_label.setText(f"心跳设置无效：{exc}")
            return

        target_text = PLCWorkerThread._format_target(config.variable)
        interval_text = f"{config.interval_on_seconds:.2f}s / {config.interval_off_seconds:.2f}s"
        if config.enabled:
            self.heartbeat_status_label.setText(
                f"当前心跳：{config.display_text} -> {target_text}，值 {config.value_on}/{config.value_off}，间隔 {interval_text}"
            )
        else:
            self.heartbeat_status_label.setText(
                f"当前心跳（已禁用）：{config.display_text} -> {target_text}，值 {config.value_on}/{config.value_off}"
            )

        if push_to_runtime:
            self._push_heartbeat_config_to_plc(config)

        if not save_to_disk:
            return

        try:
            self._save_settings_to_json()
            self._set_status(f"参数已保存到 {self.settings_path.name}")
        except Exception as exc:
            self._set_status(f"参数保存失败：{exc}")

    def _push_heartbeat_config_to_plc(self, config: Optional[PLCHeartbeatConfig] = None) -> None:
        if config is None:
            try:
                config = self._current_heartbeat_config()
            except Exception:
                return

        if self.plc_thread is not None:
            self.plc_thread.request_update_heartbeat(config)

    def apply_serial_settings(self) -> None:
        self.preferred_port_device = self._selected_port_device()
        try:
            self._save_settings_to_json()
            self._set_status(f"参数已保存到 {self.settings_path.name}")
        except Exception as exc:
            self._set_status(f"参数保存失败：{exc}")

    def apply_data_settings(self) -> None:
        self._apply_data_target_settings(save_to_disk=True)

    def _apply_data_target_settings(self, save_to_disk: bool = False) -> None:
        try:
            config = self._current_data_target_config()
        except Exception as exc:
            self.data_target_status_label.setText(f"数据设置无效：{exc}")
            return

        target_text = PLCWorkerThread._format_target(config.variable)
        prefix = "当前写入目标" if config.enabled else "当前写入目标（已禁用）"
        self.data_target_status_label.setText(f"{prefix}：{config.display_text} -> {target_text}")
        if not save_to_disk:
            return

        try:
            self._save_settings_to_json()
            self._set_status(f"参数已保存到 {self.settings_path.name}")
        except Exception as exc:
            self._set_status(f"参数保存失败：{exc}")

    def _save_settings_to_json(self) -> None:
        payload = {
            "serial": {
                "selected_port": self._selected_port_device(),
                "baudrate": self.DEFAULT_BAUDRATE,
            },
            "plc": {
                "ip_address": self.plc_ip_input.text().strip(),
                "rack": int(self.plc_rack_spin.value()),
                "slot": int(self.plc_slot_spin.value()),
                "start_signal": {
                    "db_number": int(self.start_signal_db_spin.value()),
                    "byte_offset": int(self.start_signal_byte_spin.value()),
                    "bit_index": int(self.start_signal_bit_spin.value()),
                    "auto_reset": self.start_signal_reset_check.isChecked(),
                },
                "complete_signal": {
                    "db_number": int(self.complete_signal_db_spin.value()),
                    "byte_offset": int(self.complete_signal_byte_spin.value()),
                    "bit_index": int(self.complete_signal_bit_spin.value()),
                    "auto_reset": self.complete_signal_reset_check.isChecked(),
                },
            },
            "data_target": {
                "display_text": self.data_display_text_input.text().strip() or "扫码结果",
                "db_number": int(self.data_db_spin.value()),
                "start": int(self.data_start_spin.value()),
                "data_type": self.data_type_combo.currentText().strip(),
                "bit_index": int(self.data_bool_bit_spin.value()),
                "enabled": self.data_write_enabled_check.isChecked(),
            },
            "heartbeat": {
                "display_text": self.heartbeat_name_input.text().strip() or "心跳",
                "db_number": int(self.heartbeat_db_spin.value()),
                "start": int(self.heartbeat_start_spin.value()),
                "data_type": self.heartbeat_type_combo.currentText().strip(),
                "bit_index": int(self.heartbeat_bool_bit_spin.value()),
                "value_on": self.heartbeat_value_on_input.text().strip() or "1",
                "value_off": self.heartbeat_value_off_input.text().strip() or "0",
                "interval_on_seconds": float(self.heartbeat_interval_on_spin.value()),
                "interval_off_seconds": float(self.heartbeat_interval_off_spin.value()),
                "enabled": self.heartbeat_enabled_check.isChecked(),
            },
        }
        self.settings_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_settings_from_json(self) -> None:
        if not self.settings_path.exists():
            return

        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except Exception:
            return

        serial_settings = payload.get("serial") if isinstance(payload, dict) else None
        if isinstance(serial_settings, dict):
            selected_port = str(serial_settings.get("selected_port") or "").strip()
            if selected_port:
                self.preferred_port_device = selected_port

        plc_settings = payload.get("plc") if isinstance(payload, dict) else None
        if isinstance(plc_settings, dict):
            self.plc_ip_input.setText(str(plc_settings.get("ip_address") or self.plc_ip_input.text()).strip())
            self._set_spin_value(self.plc_rack_spin, plc_settings.get("rack"))
            self._set_spin_value(self.plc_slot_spin, plc_settings.get("slot"))

            start_signal = plc_settings.get("start_signal")
            if isinstance(start_signal, dict):
                self._set_spin_value(self.start_signal_db_spin, start_signal.get("db_number"))
                self._set_spin_value(self.start_signal_byte_spin, start_signal.get("byte_offset"))
                self._set_spin_value(self.start_signal_bit_spin, start_signal.get("bit_index"))
                if "auto_reset" in start_signal:
                    self.start_signal_reset_check.setChecked(bool(start_signal.get("auto_reset")))

            complete_signal = plc_settings.get("complete_signal")
            if isinstance(complete_signal, dict):
                self._set_spin_value(self.complete_signal_db_spin, complete_signal.get("db_number"))
                self._set_spin_value(self.complete_signal_byte_spin, complete_signal.get("byte_offset"))
                self._set_spin_value(self.complete_signal_bit_spin, complete_signal.get("bit_index"))
                if "auto_reset" in complete_signal:
                    self.complete_signal_reset_check.setChecked(bool(complete_signal.get("auto_reset")))

        data_target = payload.get("data_target") if isinstance(payload, dict) else None
        if isinstance(data_target, dict):
            display_text = str(data_target.get("display_text") or "").strip()
            if display_text:
                self.data_display_text_input.setText(display_text)
            self._set_spin_value(self.data_db_spin, data_target.get("db_number"))
            self._set_spin_value(self.data_start_spin, data_target.get("start"))
            self._set_spin_value(self.data_bool_bit_spin, data_target.get("bit_index"))

            data_type = str(data_target.get("data_type") or "").strip().upper()
            if data_type in SUPPORTED_DATA_TYPES:
                self.data_type_combo.setCurrentText(data_type)

            if "enabled" in data_target:
                self.data_write_enabled_check.setChecked(bool(data_target.get("enabled")))

        heartbeat = payload.get("heartbeat") if isinstance(payload, dict) else None
        if isinstance(heartbeat, dict):
            heartbeat_name = str(heartbeat.get("display_text") or "").strip()
            if heartbeat_name:
                self.heartbeat_name_input.setText(heartbeat_name)

            self._set_spin_value(self.heartbeat_db_spin, heartbeat.get("db_number"))
            self._set_spin_value(self.heartbeat_start_spin, heartbeat.get("start"))
            self._set_spin_value(self.heartbeat_bool_bit_spin, heartbeat.get("bit_index"))
            self._set_double_spin_value(self.heartbeat_interval_on_spin, heartbeat.get("interval_on_seconds"))
            self._set_double_spin_value(self.heartbeat_interval_off_spin, heartbeat.get("interval_off_seconds"))

            heartbeat_type = str(heartbeat.get("data_type") or "").strip().upper()
            if heartbeat_type in SUPPORTED_DATA_TYPES:
                self.heartbeat_type_combo.setCurrentText(heartbeat_type)

            heartbeat_value_on = str(heartbeat.get("value_on") or "").strip()
            if heartbeat_value_on:
                self.heartbeat_value_on_input.setText(heartbeat_value_on)

            heartbeat_value_off = str(heartbeat.get("value_off") or "").strip()
            if heartbeat_value_off:
                self.heartbeat_value_off_input.setText(heartbeat_value_off)

            if "enabled" in heartbeat:
                self.heartbeat_enabled_check.setChecked(bool(heartbeat.get("enabled")))

        self._sync_data_target_controls()
        self._sync_heartbeat_controls()

    @staticmethod
    def _set_spin_value(spin_box: QSpinBox, value) -> None:
        try:
            spin_box.setValue(int(value))
        except (TypeError, ValueError):
            return

    @staticmethod
    def _set_double_spin_value(spin_box: QDoubleSpinBox, value) -> None:
        try:
            spin_box.setValue(float(value))
        except (TypeError, ValueError):
            return

    def _bind_plc_auto_save_signals(self) -> None:
        self.plc_ip_input.editingFinished.connect(self._auto_save_plc_settings)

        for spin_box in (
            self.plc_rack_spin,
            self.plc_slot_spin,
            self.start_signal_db_spin,
            self.start_signal_byte_spin,
            self.start_signal_bit_spin,
            self.complete_signal_db_spin,
            self.complete_signal_byte_spin,
            self.complete_signal_bit_spin,
        ):
            spin_box.valueChanged.connect(self._auto_save_plc_settings)

        self.start_signal_reset_check.toggled.connect(self._auto_save_plc_settings)
        self.complete_signal_reset_check.toggled.connect(self._auto_save_plc_settings)

    def _auto_save_plc_settings(self, *_args) -> None:
        if self._suspend_auto_save:
            return

        try:
            self._save_settings_to_json()
        except Exception as exc:
            self._set_status(f"PLC 参数自动保存失败：{exc}")

    def _create_plc_value_row(self, title: str, editor: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        label = QLabel(title)
        label.setObjectName("subtleLabel")
        label.setMinimumWidth(84)
        row.addWidget(label)
        row.addWidget(editor, 1)
        return row

    def _build_plc_signal_row(
        self,
        parent_layout: QVBoxLayout,
        title: str,
        db_default: int,
        byte_default: int,
        bit_default: int,
        reset_default: bool,
    ) -> tuple[QSpinBox, QSpinBox, QSpinBox, QCheckBox]:
        title_label = QLabel(title)
        title_label.setObjectName("subtleLabel")
        parent_layout.addWidget(title_label)

        row = QHBoxLayout()
        row.setSpacing(8)
        parent_layout.addLayout(row)

        row.addWidget(QLabel("DB"))
        db_spin = self._create_spin_box(1, 65535, db_default)
        row.addWidget(db_spin)

        row.addWidget(QLabel("字节"))
        byte_spin = self._create_spin_box(0, 65535, byte_default)
        row.addWidget(byte_spin)

        row.addWidget(QLabel("位"))
        bit_spin = self._create_spin_box(0, 7, bit_default)
        row.addWidget(bit_spin)

        reset_check = QCheckBox("置零")
        reset_check.setChecked(reset_default)
        row.addWidget(reset_check)
        row.addStretch(1)
        return db_spin, byte_spin, bit_spin, reset_check

    def _create_spin_box(self, minimum: int, maximum: int, value: int) -> QSpinBox:
        spin_box = StepSpinBox()
        spin_box.setRange(minimum, maximum)
        spin_box.setValue(value)
        spin_box.setMinimumWidth(92)
        return spin_box

    def _create_double_spin_box(self, minimum: float, maximum: float, value: float) -> QDoubleSpinBox:
        spin_box = StepDoubleSpinBox()
        spin_box.setRange(minimum, maximum)
        spin_box.setDecimals(2)
        spin_box.setSingleStep(0.1)
        spin_box.setValue(value)
        spin_box.setMinimumWidth(92)
        return spin_box

    def toggle_drawer(self) -> None:
        self.drawer_open = not self.drawer_open
        self.drawer_animation.stop()
        self.drawer_animation.setStartValue(self.drawer_panel.maximumWidth())
        self.drawer_animation.setEndValue(self.drawer_open_width if self.drawer_open else 0)
        self.drawer_animation.start()
        self.settings_button.setText("收起设置" if self.drawer_open else "设置")

    def toggle_serial_settings(self) -> None:
        self.serial_section_open = not self.serial_section_open
        self.serial_section_animation.stop()
        self.serial_section_animation.setStartValue(self.serial_section_body.maximumHeight())
        self.serial_section_animation.setEndValue(self.serial_section_height if self.serial_section_open else 0)
        self.serial_section_animation.start()
        self.serial_section_button.setText("串口设置 ▲" if self.serial_section_open else "串口设置 ▼")

    def toggle_data_settings(self) -> None:
        self.data_section_open = not self.data_section_open
        self.data_section_animation.stop()
        self.data_section_animation.setStartValue(self.data_section_body.maximumHeight())
        self.data_section_animation.setEndValue(self.data_section_height if self.data_section_open else 0)
        self.data_section_animation.start()
        self.data_section_button.setText("数据设置 ▲" if self.data_section_open else "数据设置 ▼")

    def toggle_heartbeat_settings(self) -> None:
        self.heartbeat_section_open = not self.heartbeat_section_open
        self.heartbeat_section_animation.stop()
        self.heartbeat_section_animation.setStartValue(self.heartbeat_section_body.maximumHeight())
        self.heartbeat_section_animation.setEndValue(self.heartbeat_section_height if self.heartbeat_section_open else 0)
        self.heartbeat_section_animation.start()
        self.heartbeat_section_button.setText("心跳设置 ▲" if self.heartbeat_section_open else "心跳设置 ▼")

    def _current_plc_config(self) -> PLCConnectionConfig:
        config = PLCConnectionConfig(
            ip_address=self.plc_ip_input.text().strip(),
            rack=int(self.plc_rack_spin.value()),
            slot=int(self.plc_slot_spin.value()),
            start_signal=PLCSignalConfig(
                name="start_signal",
                db_number=int(self.start_signal_db_spin.value()),
                byte_offset=int(self.start_signal_byte_spin.value()),
                bit_index=int(self.start_signal_bit_spin.value()),
                auto_reset=self.start_signal_reset_check.isChecked(),
            ),
            complete_signal=PLCSignalConfig(
                name="complete_signal",
                db_number=int(self.complete_signal_db_spin.value()),
                byte_offset=int(self.complete_signal_byte_spin.value()),
                bit_index=int(self.complete_signal_bit_spin.value()),
                auto_reset=self.complete_signal_reset_check.isChecked(),
            ),
        )
        config.start_signal.to_variable().validate()
        config.complete_signal.to_variable().validate()
        return config

    def connect_plc(self) -> None:
        try:
            config = self._current_plc_config()
        except Exception as exc:
            QMessageBox.warning(self, "提示", f"PLC 参数无效: {exc}")
            return

        self._stop_plc_thread()
        self.plc_stop_event = threading.Event()
        self.plc_thread = PLCWorkerThread(config, self.output_queue, self.plc_stop_event)
        self.plc_thread.start()
        self._push_heartbeat_config_to_plc()
        self.plc_connected = False
        self.awaiting_plc_completion = False
        self._set_plc_controls_enabled(False)
        self._set_plc_status("正在连接 PLC ...")
        self._set_plc_connection_chip("连接中", "pending")
        self._append_log("plc", f"开始连接 PLC {config.ip_address}")

    def disconnect_plc(self) -> None:
        self._stop_plc_thread()
        self.plc_connected = False
        self.awaiting_plc_completion = False
        self._set_plc_controls_enabled(True)
        self._set_plc_status("已手动断开 PLC")
        self._set_plc_connection_chip("未连接", "idle")
        self._append_log("plc", "已手动断开 PLC")

    def _stop_plc_thread(self) -> None:
        if self.plc_stop_event is not None:
            self.plc_stop_event.set()
        if self.plc_thread and self.plc_thread.is_alive():
            self.plc_thread.join(timeout=1.0)
        self.plc_thread = None
        self.plc_stop_event = None

    def _set_plc_controls_enabled(self, enabled: bool) -> None:
        widgets = [
            self.plc_ip_input,
            self.plc_rack_spin,
            self.plc_slot_spin,
            self.start_signal_db_spin,
            self.start_signal_byte_spin,
            self.start_signal_bit_spin,
            self.start_signal_reset_check,
            self.complete_signal_db_spin,
            self.complete_signal_byte_spin,
            self.complete_signal_bit_spin,
            self.complete_signal_reset_check,
        ]
        for widget in widgets:
            widget.setEnabled(enabled)

        self.plc_connect_button.setEnabled(enabled)
        self.plc_disconnect_button.setEnabled(not enabled)

    def _set_plc_status(self, message: str) -> None:
        self.plc_status_label.setText(message)

    def refresh_ports(self) -> None:
        current_port = self.preferred_port_device or self._selected_port_device()
        ports = sorted(list_ports.comports(), key=lambda item: item.device)
        labels = []
        port_lookup: dict[str, str] = {}

        for port in ports:
            description = port.description or "USB Serial Device"
            label = f"{port.device}  |  {description}"
            labels.append(label)
            port_lookup[label] = port.device
            port_lookup[port.device] = port.device

        self.port_options = port_lookup
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        self.port_combo.addItems(labels)
        self.port_combo.blockSignals(False)

        target_label = next((label for label in labels if port_lookup.get(label) == current_port), None)
        if target_label is None and current_port:
            target_label = f"{current_port}  |  已保存端口"
            self.port_combo.addItem(target_label)
            self.port_options[target_label] = current_port
            self.port_options[current_port] = current_port

        if target_label is not None:
            self.port_combo.setCurrentText(target_label)
            self.preferred_port_device = self.port_options.get(target_label, "")
        elif labels:
            self.port_combo.setCurrentText(labels[0])
            self.preferred_port_device = port_lookup.get(labels[0], "")
        else:
            self.port_combo.setCurrentIndex(-1)
            self.preferred_port_device = current_port

        self._set_status(f"已发现 {len(labels)} 个串口")
        if not self._is_connected():
            self._set_output_status_hint("等待连接设备")

    def toggle_connection(self) -> None:
        if self._is_connected():
            self.disconnect()
        else:
            self.connect()

    def connect(self) -> None:
        port_text = self.port_combo.currentText().strip()
        if not port_text:
            QMessageBox.warning(self, "提示", "请先在设置中选择串口。")
            return

        self.com_manual_disconnect = False
        self.com_reconnect_timer.stop()
        port = self.port_options.get(port_text, port_text.split("|", 1)[0].strip())
        self.stop_event = threading.Event()
        self.reader_thread = SerialReaderThread(port, self.DEFAULT_BAUDRATE, self.output_queue, self.stop_event)
        self.reader_thread.start()

        self.refresh_button.setEnabled(False)
        self.port_combo.setEnabled(False)
        self.connect_button.setText("断开连接")
        self._set_com_connection_chip("连接中", "pending")
        self._set_status(f"正在连接 {port} ...")
        self._set_output_status_hint("正在连接扫码枪...")

    def _auto_connect_devices(self) -> None:
        if self.plc_thread is None:
            self.connect_plc()

        if self._is_connected():
            return

        if self.port_combo.currentText().strip():
            self.connect()
        else:
            self._schedule_com_reconnect("未发现可用 COM 口")

    def disconnect(self) -> None:
        self.com_manual_disconnect = True
        self.com_reconnect_timer.stop()
        self.stop_event.set()
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=1.0)
        self.reader_thread = None
        self.refresh_button.setEnabled(True)
        self.port_combo.setEnabled(True)
        self.connect_button.setText("连接设备")
        self._set_com_connection_chip("未连接", "idle")
        self._set_status("未连接")
        self._set_output_status_hint("连接已断开")

    def _schedule_com_reconnect(self, reason: str) -> None:
        if self.com_manual_disconnect:
            return

        self.refresh_ports()
        self._set_status(f"{reason}，{int(COM_RECONNECT_INTERVAL_SECONDS)} 秒后自动重连。")
        self._set_output_status_hint("COM 重连中")
        self._set_com_connection_chip("重连中", "pending")
        self.com_reconnect_timer.start(int(COM_RECONNECT_INTERVAL_SECONDS * 1000))

    def _attempt_com_reconnect(self) -> None:
        if self.com_manual_disconnect or self._is_connected():
            return

        self.refresh_ports()
        if not self.port_combo.currentText().strip():
            self._schedule_com_reconnect("未发现可用 COM 口")
            return

        self.connect()

    def process_queue(self) -> None:
        while True:
            try:
                event_type, payload = self.output_queue.get_nowait()
            except queue.Empty:
                break

            if event_type == "scan":
                self._show_scan(payload)
            elif event_type == "status":
                if self.debug_checkbox.isChecked():
                    self._append_log("status", payload)
                self._set_status(payload)
                if isinstance(payload, str) and payload.startswith("已连接"):
                    self.com_reconnect_timer.stop()
                    self.com_manual_disconnect = False
                    self._set_com_connection_chip("已连接", "connected")
                    self._set_output_status_hint("等待扫码")
                if payload == "串口已断开":
                    self.reader_thread = None
                    self.refresh_button.setEnabled(True)
                    self.port_combo.setEnabled(True)
                    self.connect_button.setText("连接设备")
                    self._set_com_connection_chip("未连接", "idle")
                    self._set_output_status_hint("连接已断开")
                    if not self.com_manual_disconnect:
                        self._schedule_com_reconnect("串口已断开")
            elif event_type == "error":
                self._append_log("error", payload)
                self._set_status(payload)
                self.reader_thread = None
                self.refresh_button.setEnabled(True)
                self.port_combo.setEnabled(True)
                self.connect_button.setText("连接设备")
                self._set_com_connection_chip("连接失败", "error")
                self._set_output_status_hint("连接失败")
                self._schedule_com_reconnect(str(payload))

            elif event_type == "plc_status":
                if self.debug_checkbox.isChecked():
                    self._append_log("plc", payload)
                self._set_plc_status(payload)
                self._set_plc_connection_chip("重连中", "pending")
            elif event_type == "plc_connected":
                self.plc_connected = True
                self.awaiting_plc_completion = False
                self._set_plc_status(payload)
                self._set_plc_connection_chip("已连接", "connected")
                self._append_log("plc", payload)
            elif event_type == "plc_disconnected":
                self.plc_connected = False
                self.awaiting_plc_completion = False
                self._set_plc_status(payload)
                self._set_plc_connection_chip("重连中", "pending")
                self._append_log("plc", payload)
                self._set_output_status_hint("PLC 重连中")
            elif event_type == "plc_error":
                self.plc_connected = False
                self.awaiting_plc_completion = False
                self._set_plc_status(payload)
                self._set_plc_connection_chip("异常", "error")
                self._append_log("error", payload)
                self._set_output_status_hint("PLC 连接异常")
                if self.plc_stop_event is not None and self.plc_stop_event.is_set():
                    self._set_plc_controls_enabled(True)
                    self.plc_thread = None
                    self.plc_stop_event = None
            elif event_type == "plc_start_signal":
                self._set_plc_status(payload)
                self._append_log("plc", payload)
                self._set_output_status_hint("已收到 PLC 开始信号")
            elif event_type == "plc_complete_signal":
                self.awaiting_plc_completion = False
                self._set_plc_status(payload)
                self._append_log("plc", payload)
                self._set_status("已收到 PLC 完成信号，等待扫码")
                self._set_output_status_hint("等待扫码")
            elif event_type == "plc_data_written":
                self.awaiting_plc_completion = True
                self._set_plc_status(payload)
                self._append_log("plc", payload)
                self._set_status("等待 PLC 发送完成信号")
                self._set_output_status_hint("等待 PLC 发送完成信号")
            elif event_type == "plc_data_error":
                self._set_plc_status(payload)
                self._append_log("error", payload)
                self._set_output_status_hint("扫码数据写入 PLC 失败")
            elif event_type == "heartbeat_error":
                self.heartbeat_status_label.setText(f"心跳运行失败：{payload}")
                self._append_log("error", payload)

    def _show_scan(self, payload: dict[str, object]) -> None:
        text = str(payload.get("text") or "<空数据>")

        if self.plc_connected and self.awaiting_plc_completion:
            self._append_scan_text("未收到PLC完成信号")
            self._set_status("未收到PLC完成信号")
            self._set_plc_status("未收到PLC完成信号，等待 PLC 完成信号。")
            self._set_output_status_hint("等待 PLC 发送完成信号")
            return

        self.last_scan_label.setText(text)

        if self.debug_checkbox.isChecked():
            detail = f"[{payload['source']}] len={payload['length']} text={text} | hex={payload['hex']}"
            self._append_log("scan", detail)
        else:
            self._append_scan_text(text)

        self._write_scan_result_to_plc(text)
        self._set_status(f"最近一次扫码: {text}")

    def _write_scan_result_to_plc(self, scan_text: str) -> None:
        try:
            config = self._current_data_target_config()
        except Exception as exc:
            self._set_plc_status(f"数据设置无效：{exc}")
            return

        if not config.enabled:
            return
        if self.plc_thread is None or not self.plc_connected:
            self._set_plc_status("PLC 未连接，当前扫码结果未写入。")
            self._append_scan_text("PLC未连接")
            self._set_output_status_hint("PLC未连接")
            return

        self.plc_thread.request_write_scan_data(config, scan_text)

    def _append_log(self, level: str, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        label = "收到扫码内容" if level.lower() == "scan" else f"{level.upper():<6}"
        self.output_text.appendPlainText(f"[{timestamp}] {label} {message}")
        self.output_text.moveCursor(QTextCursor.End)

    def _append_scan_text(self, text: str) -> None:
        self._append_log("scan", text)

    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def _set_output_status_hint(self, message: str) -> None:
        text = str(message).strip() or "等待扫码"
        self.output_text.setPlaceholderText(f"当前状态：{text}")

    def _set_chip_state(self, chip: QLabel, prefix: str, text: str, mode: str) -> None:
        chip.setText(f"{prefix} {text}")
        styles = {
            "connected": "color: #8BE28B; background-color: #112418; border: 1px solid #2E6F44;",
            "pending": "color: #F3B53A; background-color: #1D2330; border: 1px solid #5F6470;",
            "error": "color: #FF9F8F; background-color: #2A1618; border: 1px solid #7A373C;",
            "idle": "color: #D7E0EC; background-color: #101722; border: 1px solid #425974;",
        }
        chip.setStyleSheet(f"padding: 8px 12px; border-radius: 12px; {styles.get(mode, styles['idle'])}")

    def _set_com_connection_chip(self, text: str, mode: str) -> None:
        self._set_chip_state(self.com_connection_chip, "COM", text, mode)

    def _set_plc_connection_chip(self, text: str, mode: str) -> None:
        self._set_chip_state(self.plc_connection_chip, "PLC", text, mode)

    def _selected_port_device(self) -> str:
        current_text = self.port_combo.currentText().strip()
        return self.port_options.get(current_text, current_text.split("|", 1)[0].strip())

    def _is_connected(self) -> bool:
        return self.reader_thread is not None and self.reader_thread.is_alive()

    def clear_output(self) -> None:
        self.output_text.clear()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming convention
        self.disconnect_plc()
        self.disconnect()
        super().closeEvent(event)


@dataclass
class RuntimeCheckResult:
    name: str
    passed: bool
    detail: str
    blocking: bool = True


def _app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _startup_log_path() -> Path:
    return _app_base_dir() / STARTUP_LOG_FILE_NAME


def _write_startup_log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with _startup_log_path().open("a", encoding="utf-8") as handle:
            lines = str(message).splitlines() or [""]
            for line in lines:
                handle.write(f"[{timestamp}] {line}\n")
    except Exception:
        pass


def _show_native_message_box(title: str, message: str, style: int = 0x10) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, message, title, style | 0x00001000)
    except Exception:
        pass


def _test_directory_writable(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"目录不存在：{path}"
    probe_path = path / f".startup_probe_{int(time.time() * 1000)}.tmp"
    try:
        probe_path.write_text("ok", encoding="utf-8")
        probe_path.unlink(missing_ok=True)
        return True, f"目录可写：{path}"
    except Exception as exc:
        return False, f"目录不可写：{path}，原因：{exc}"


def _collect_runtime_checks() -> list[RuntimeCheckResult]:
    checks: list[RuntimeCheckResult] = []

    system_name = platform.system() or "Unknown"
    system_release = platform.release() or "Unknown"
    checks.append(
        RuntimeCheckResult(
            name="操作系统",
            passed=system_name == "Windows",
            detail=f"{system_name} {system_release}",
            blocking=True,
        )
    )

    machine = platform.machine() or "Unknown"
    is_64_bit = sys.maxsize > 2**32
    checks.append(
        RuntimeCheckResult(
            name="处理器与系统位数",
            passed=is_64_bit,
            detail=f"machine={machine}, {'64位' if is_64_bit else '32位'}",
            blocking=True,
        )
    )

    app_dir = _app_base_dir()
    checks.append(
        RuntimeCheckResult(
            name="应用目录存在",
            passed=app_dir.exists(),
            detail=str(app_dir),
            blocking=True,
        )
    )
    app_dir_writable, app_dir_detail = _test_directory_writable(app_dir)
    checks.append(
        RuntimeCheckResult(
            name="应用目录写入权限",
            passed=app_dir_writable,
            detail=app_dir_detail,
            blocking=True,
        )
    )

    temp_dir = Path(tempfile.gettempdir())
    temp_dir_writable, temp_dir_detail = _test_directory_writable(temp_dir)
    checks.append(
        RuntimeCheckResult(
            name="临时目录写入权限",
            passed=temp_dir_writable,
            detail=temp_dir_detail,
            blocking=True,
        )
    )

    settings_path = app_dir / ScannerWindow.SETTINGS_FILE_NAME
    if settings_path.exists():
        try:
            settings_path.read_text(encoding="utf-8")
            checks.append(
                RuntimeCheckResult(
                    name="配置文件读取",
                    passed=True,
                    detail=f"配置文件可读取：{settings_path}",
                    blocking=False,
                )
            )
        except Exception as exc:
            checks.append(
                RuntimeCheckResult(
                    name="配置文件读取",
                    passed=False,
                    detail=f"配置文件读取失败：{settings_path}，原因：{exc}",
                    blocking=False,
                )
            )
    else:
        checks.append(
            RuntimeCheckResult(
                name="配置文件读取",
                passed=True,
                detail=f"配置文件不存在，将在首次保存时创建：{settings_path}",
                blocking=False,
            )
        )

    try:
        serial_version = getattr(serial, "__version__", "已加载")
        checks.append(
            RuntimeCheckResult(
                name="pyserial 模块",
                passed=True,
                detail=f"模块已加载：{serial_version}",
                blocking=True,
            )
        )
    except Exception as exc:
        checks.append(
            RuntimeCheckResult(
                name="pyserial 模块",
                passed=False,
                detail=f"模块异常：{exc}",
                blocking=True,
            )
        )

    try:
        ports = list(list_ports.comports())
        checks.append(
            RuntimeCheckResult(
                name="串口枚举",
                passed=True,
                detail=f"枚举成功，检测到 {len(ports)} 个串口",
                blocking=False,
            )
        )
    except Exception as exc:
        checks.append(
            RuntimeCheckResult(
                name="串口枚举",
                passed=False,
                detail=f"串口枚举失败：{exc}",
                blocking=False,
            )
        )

    try:
        import plc_comm as plc_comm_module

        checks.append(
            RuntimeCheckResult(
                name="PLC 通讯模块",
                passed=True,
                detail="plc_comm 模块已加载",
                blocking=True,
            )
        )

        snap7_loaded = getattr(plc_comm_module, "snap7", None) is not None
        snap7_error = getattr(plc_comm_module, "SNAP7_IMPORT_ERROR", None)
        checks.append(
            RuntimeCheckResult(
                name="snap7 运行库",
                passed=snap7_loaded,
                detail="snap7 已加载" if snap7_loaded else f"snap7 未加载：{snap7_error}",
                blocking=False,
            )
        )
    except Exception as exc:
        checks.append(
            RuntimeCheckResult(
                name="PLC 通讯模块",
                passed=False,
                detail=f"plc_comm 模块异常：{exc}",
                blocking=True,
            )
        )

    return checks


def _log_runtime_checks(checks: list[RuntimeCheckResult]) -> None:
    for check in checks:
        if check.passed:
            status = "通过"
        elif check.blocking:
            status = "失败"
        else:
            status = "警告"
        _write_startup_log(f"环境检查[{status}] {check.name}：{check.detail}")


def _format_runtime_issues(title: str, checks: list[RuntimeCheckResult]) -> str:
    lines = [title]
    for index, check in enumerate(checks, start=1):
        status = "失败" if check.blocking else "警告"
        lines.append(f"{index}. [{status}] {check.name}：{check.detail}")
    lines.append(f"日志文件：{_startup_log_path()}")
    return "\n".join(lines)


def _show_startup_error_dialog(summary: str, detail: str = "") -> None:
    app = QApplication.instance()
    created_app = False
    if app is None:
        app = QApplication(sys.argv)
        created_app = True

    message = f"{summary}\n\n日志文件：{_startup_log_path()}"
    if detail:
        message = f"{message}\n\n错误信息：{detail}"
    QMessageBox.critical(None, "启动异常", message)

    if created_app:
        app.quit()


def _window_state_snapshot(window: QMainWindow) -> str:
    try:
        return (
            f"visible={window.isVisible()}, "
            f"hidden={window.isHidden()}, "
            f"minimized={window.isMinimized()}, "
            f"maximized={window.isMaximized()}, "
            f"active={window.isActiveWindow()}"
        )
    except Exception as exc:
        return f"窗口状态读取失败: {exc}"


def _apply_full_window_style(window: QMainWindow) -> None:
    _write_startup_log("准备应用完整界面样式表。")
    window.setStyleSheet(APP_STYLESHEET)
    _write_startup_log(f"完整界面样式表应用完成，窗口状态：{_window_state_snapshot(window)}")


def _show_main_window_after_event_loop(window: QMainWindow, app: QApplication) -> None:
    try:
        _write_startup_log("事件循环回调已进入，准备显示主窗口。")
        _write_startup_log(f"显示前状态：{_window_state_snapshot(window)}")

        _write_startup_log("准备调用 show()。")
        window.show()
        _write_startup_log("show() 调用已返回。")
        _write_startup_log(f"show() 后状态：{_window_state_snapshot(window)}")

        if hasattr(window, "raise_"):
            _write_startup_log("准备调用 raise_()。")
            window.raise_()
            _write_startup_log(f"raise_() 调用已返回，窗口状态：{_window_state_snapshot(window)}")

        _write_startup_log("准备调用 activateWindow()。")
        window.activateWindow()
        _write_startup_log(f"activateWindow() 调用已返回，窗口状态：{_window_state_snapshot(window)}")

        _write_startup_log("准备处理首次显示事件。")
        app.processEvents()
        _write_startup_log(f"首次 processEvents() 返回后状态：{_window_state_snapshot(window)}")

        QTimer.singleShot(100, lambda: _apply_full_window_style(window))
        QTimer.singleShot(
            250,
            lambda: _write_startup_log(f"显示后 250ms 检查，窗口状态：{_window_state_snapshot(window)}"),
        )
        QTimer.singleShot(
            1000,
            lambda: _write_startup_log(f"显示后 1 秒检查，窗口状态：{_window_state_snapshot(window)}"),
        )
    except Exception as exc:
        _write_startup_log("显示主窗口阶段发生异常。")
        _write_startup_log(traceback.format_exc().rstrip())
        _show_startup_error_dialog("主窗口显示失败，详情已写入日志文件。", str(exc))
        app.quit()


def main() -> int:
    _write_startup_log("-" * 72)
    _write_startup_log("软件启动开始。")
    _write_startup_log(f"应用目录：{_app_base_dir()}")
    _write_startup_log(f"启动程序：{sys.executable}")
    _write_startup_log("开始执行启动环境检查。")

    runtime_checks = _collect_runtime_checks()
    _log_runtime_checks(runtime_checks)
    blocking_checks = [check for check in runtime_checks if not check.passed and check.blocking]
    warning_checks = [check for check in runtime_checks if not check.passed and not check.blocking]
    if blocking_checks:
        _write_startup_log(f"启动环境检查失败，共 {len(blocking_checks)} 项阻塞问题。")
        message = _format_runtime_issues("启动环境检查未通过，程序无法继续运行。", blocking_checks)
        _write_startup_log(message)
        _show_native_message_box("运行环境不满足", message)
        return 1
    if warning_checks:
        _write_startup_log(f"启动环境检查完成，发现 {len(warning_checks)} 项警告，可继续运行。")
    else:
        _write_startup_log("启动环境检查完成，所有核心项均通过。")

    app = None
    single_instance_lock = None
    lock_acquired = False
    try:
        _write_startup_log(
            f"Qt 软件渲染环境：QT_OPENGL={os.environ.get('QT_OPENGL')}, "
            f"QT_ANGLE_PLATFORM={os.environ.get('QT_ANGLE_PLATFORM')}"
        )
        try:
            software_gl_attribute = (
                Qt.AA_UseSoftwareOpenGL
                if hasattr(Qt, "AA_UseSoftwareOpenGL")
                else Qt.ApplicationAttribute.AA_UseSoftwareOpenGL
            )
            QApplication.setAttribute(software_gl_attribute, True)
            _write_startup_log("已请求 Qt 使用软件 OpenGL 渲染。")
        except Exception as exc:
            _write_startup_log(f"请求 Qt 使用软件 OpenGL 失败：{exc}")

        _write_startup_log("准备创建 QApplication。")
        app = QApplication(sys.argv)
        _write_startup_log("QApplication 创建成功。")
        app.aboutToQuit.connect(lambda: _write_startup_log("收到 aboutToQuit 信号。"))

        single_instance_lock = QLockFile(str(SINGLE_INSTANCE_LOCK_PATH))
        if hasattr(single_instance_lock, "setStaleLockTime"):
            single_instance_lock.setStaleLockTime(0)
        _write_startup_log(f"准备获取单实例锁：{SINGLE_INSTANCE_LOCK_PATH}")
        if not single_instance_lock.tryLock(100):
            _write_startup_log("检测到软件已在运行，弹窗提示后退出。")
            QMessageBox.warning(None, "重复打开提示", "软件已经在运行，请不要重复打开。")
            return 0
        lock_acquired = True
        _write_startup_log("单实例锁获取成功。")

        _write_startup_log("准备创建主窗口。")
        window = ScannerWindow()
        _write_startup_log("主窗口创建成功。")
        _write_startup_log(f"主窗口创建后状态：{_window_state_snapshot(window)}")

        QTimer.singleShot(
            0,
            lambda: _write_startup_log(f"事件循环已启动，显示前窗口状态：{_window_state_snapshot(window)}"),
        )
        QTimer.singleShot(0, lambda: _show_main_window_after_event_loop(window, app))
        _write_startup_log("主窗口显示已改为事件循环启动后执行。")
        _write_startup_log("准备进入事件循环。")

        exit_code = app.exec() if hasattr(app, "exec") else app.exec_()
        _write_startup_log(f"事件循环已退出，返回码：{exit_code}")
        return exit_code
    except Exception as exc:
        _write_startup_log("启动过程中发生异常。")
        _write_startup_log(traceback.format_exc().rstrip())
        _show_startup_error_dialog("软件启动失败，详情已写入日志文件。", str(exc))
        return 1
    finally:
        if single_instance_lock is not None and lock_acquired:
            try:
                single_instance_lock.unlock()
                _write_startup_log("单实例锁已释放。")
            except Exception:
                _write_startup_log("单实例锁释放失败。")


if __name__ == "__main__":
    raise SystemExit(main())
