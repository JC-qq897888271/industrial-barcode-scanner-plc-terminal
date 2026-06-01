from __future__ import annotations

import ctypes
from dataclasses import dataclass
import json
import msvcrt
from pathlib import Path
import platform
import queue
import sys
import tempfile
import threading
import time
import traceback
import tkinter as tk
import winreg
from tkinter import messagebox, scrolledtext, ttk
from datetime import datetime
from typing import Optional

import serial
from serial.tools import list_ports

from plc_comm import PLCVariable, SiemensPLCClient, SUPPORTED_DATA_TYPES


PLC_RECONNECT_INTERVAL_SECONDS = 3.0
PLC_POLL_INTERVAL_SECONDS = 0.25
PLC_PULSE_SECONDS = 0.20
COM_RECONNECT_INTERVAL_SECONDS = 3.0
DEFAULT_BAUDRATE = 9600
SETTINGS_FILE_NAME = "scanner_settings.json"
STARTUP_LOG_FILE_NAME = "startup_tk.log"
SINGLE_INSTANCE_LOCK_PATH = Path(tempfile.gettempdir()) / "barcode_scanner_tk_single_instance.lock"
STARTUP_REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_REGISTRY_VALUE_NAME = "BarcodeCdcScannerTk"


@dataclass(frozen=True)
class PLCConnectionConfig:
    ip_address: str
    rack: int
    slot: int


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


@dataclass
class RuntimeCheckResult:
    name: str
    passed: bool
    detail: str
    blocking: bool = True


class PLCAddressError(RuntimeError):
    pass


class FlatCheckbutton(tk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        text: str,
        variable: tk.BooleanVar,
        *,
        bg: str,
        fg: str,
        muted: str,
        accent: str,
        border: str,
        disabled: str,
    ) -> None:
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0)
        self.variable = variable
        self.enabled = True
        self.bg_color = bg
        self.fg_color = fg
        self.muted_color = muted
        self.accent_color = accent
        self.border_color = border
        self.disabled_color = disabled

        self.box_size = 18
        self.box = tk.Canvas(
            self,
            width=self.box_size,
            height=self.box_size,
            bg=bg,
            highlightthickness=0,
            bd=0,
        )
        self.box.pack(side="left", padx=(0, 7))
        self.label = tk.Label(self, text=text, bg=bg, fg=fg, anchor="w")
        self.label.pack(side="left", fill="x", expand=True)

        for widget in (self, self.box, self.label):
            widget.bind("<Button-1>", self._toggle)
            widget.configure(cursor="hand2")
        self.variable.trace_add("write", lambda *_args: self._sync())
        self._sync()

    def configure(self, cnf=None, **kw):  # type: ignore[override]
        if cnf is None:
            cnf = {}
        options = dict(cnf, **kw)
        state = options.pop("state", None)
        result = super().configure(options) if options else None
        if state is not None:
            self.enabled = str(state) != "disabled"
            cursor = "hand2" if self.enabled else "arrow"
            for widget in (self, self.box, self.label):
                widget.configure(cursor=cursor)
            self._sync()
        return result

    config = configure

    def _toggle(self, _event=None) -> None:
        if not self.enabled:
            return
        self.variable.set(not bool(self.variable.get()))

    def _sync(self) -> None:
        checked = bool(self.variable.get())
        text_fg = self.fg_color if self.enabled else self.disabled_color
        self.label.configure(fg=text_fg)
        self.box.delete("all")

        outline = self.accent_color if checked else self.border_color
        fill = self.accent_color if checked else self.bg_color
        if not self.enabled and not checked:
            outline = self.disabled_color

        self.box.create_rectangle(
            2,
            2,
            self.box_size - 2,
            self.box_size - 2,
            outline=outline,
            fill=fill,
            width=1,
        )
        if checked:
            self.box.create_line(
                5,
                9,
                8,
                12,
                14,
                6,
                fill=self.bg_color,
                width=2,
                capstyle="round",
                joinstyle="round",
            )


class FlatButton(tk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        text: str,
        command,
        *,
        bg: str,
        fg: str,
        hover_bg: str,
        disabled_bg: str,
        disabled_fg: str,
        border: str,
        disabled_border: str,
    ) -> None:
        super().__init__(parent, bg=bg, highlightthickness=1, highlightbackground=border, bd=0, cursor="hand2")
        self.command = command
        self.text = text
        self.enabled = True
        self.normal_bg = bg
        self.normal_fg = fg
        self.hover_bg = hover_bg
        self.disabled_bg = disabled_bg
        self.disabled_fg = disabled_fg
        self.border = border
        self.disabled_border = disabled_border

        self.label = tk.Label(
            self,
            text=text,
            bg=bg,
            fg=fg,
            padx=14,
            pady=8,
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.label.pack(fill="both", expand=True)

        for widget in (self, self.label):
            widget.bind("<Button-1>", self._invoke)
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)

    def configure(self, cnf=None, **kw):  # type: ignore[override]
        if cnf is None:
            cnf = {}
        options = dict(cnf, **kw)
        state = options.pop("state", None)
        text = options.pop("text", None)
        command = options.pop("command", None)
        result = super().configure(options) if options else None
        if text is not None:
            self.text = str(text)
            self.label.configure(text=self.text)
        if command is not None:
            self.command = command
        if state is not None:
            self.enabled = str(state) != "disabled"
            self._sync()
        return result

    config = configure

    def set_palette(self, *, bg: str, fg: str, hover_bg: str, border: str) -> None:
        self.normal_bg = bg
        self.normal_fg = fg
        self.hover_bg = hover_bg
        self.border = border
        self._sync()

    def cget(self, key: str):  # type: ignore[override]
        if key == "text":
            return self.text
        if key == "state":
            return "normal" if self.enabled else "disabled"
        return super().cget(key)

    def _invoke(self, _event=None) -> None:
        if self.enabled and self.command is not None:
            self.command()

    def _enter(self, _event=None) -> None:
        if self.enabled:
            self._paint(self.hover_bg, self.normal_fg, self.border, "hand2")

    def _leave(self, _event=None) -> None:
        self._sync()

    def _sync(self) -> None:
        if self.enabled:
            self._paint(self.normal_bg, self.normal_fg, self.border, "hand2")
        else:
            self._paint(self.disabled_bg, self.disabled_fg, self.disabled_border, "arrow")

    def _paint(self, bg: str, fg: str, border: str, cursor: str) -> None:
        self.configure(bg=bg, highlightbackground=border, cursor=cursor)
        self.label.configure(bg=bg, fg=fg, cursor=cursor)


class SingleInstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            self.handle.close()
            self.handle = None
            return False

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.handle.close()
            self.handle = None


class PLCWorkerThread(threading.Thread):
    def __init__(self, config: PLCConnectionConfig, output_queue: queue.Queue, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.config = config
        self.output_queue = output_queue
        self.stop_event = stop_event
        self.command_queue: queue.Queue = queue.Queue()
        self.client: Optional[SiemensPLCClient] = None
        self.heartbeat_config: Optional[PLCHeartbeatConfig] = None
        self.heartbeat_is_high = False
        self.heartbeat_next_toggle_at = 0.0

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
            self._reset_heartbeat_runtime()
            self.output_queue.put(
                (
                    "plc_connected",
                    f"已连接 PLC {self.config.ip_address} (Rack {self.config.rack}, Slot {self.config.slot})",
                )
            )
            return True
        except ValueError as exc:
            self.output_queue.put(("plc_error", f"PLC 参数无效: {exc}"))
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

    def _drain_commands(self) -> None:
        while True:
            try:
                command, payload = self.command_queue.get_nowait()
            except queue.Empty:
                return

            if command == "write_scan_data":
                self._write_scan_data(*payload)
            elif command == "update_heartbeat":
                self._update_heartbeat_config(payload)

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
            target_text = self._format_target(variable)
            self.output_queue.put(
                (
                    "plc_data_written",
                    f"已写入 {target_config.display_text} -> {target_text}",
                )
            )
        except Exception as exc:
            self.output_queue.put(("plc_data_error", f"扫码数据写入 PLC 失败: {exc}"))

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
            f"{label}地址不可用: {target_text}，请检查 Rack/Slot、DB/字节/位，并确认 PLC 已开启 PUT/GET。"
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
            self.output_queue.put(("error", f"串口打开失败: {exc}"))
            return

        buffer = bytearray()
        last_data_at = 0.0

        try:
            while not self.stop_event.is_set():
                chunk = self.serial_port.read(self.serial_port.in_waiting or 1)
                if chunk:
                    buffer.extend(chunk)
                    last_data_at = time.monotonic()
                    self._flush_by_terminator(buffer)
                    continue

                if buffer and last_data_at and time.monotonic() - last_data_at >= 0.25:
                    payload = bytes(buffer)
                    buffer.clear()
                    self._emit_scan(payload, source="idle")
        except Exception as exc:
            self.output_queue.put(("error", f"串口读取失败: {exc}"))
        finally:
            try:
                if self.serial_port and self.serial_port.is_open:
                    self.serial_port.close()
            except Exception:
                pass
            self.output_queue.put(("status", "串口已断开"))

    def _flush_by_terminator(self, buffer: bytearray) -> None:
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
    checks.append(RuntimeCheckResult("应用目录存在", app_dir.exists(), str(app_dir), True))
    app_dir_writable, app_dir_detail = _test_directory_writable(app_dir)
    checks.append(RuntimeCheckResult("应用目录写入权限", app_dir_writable, app_dir_detail, True))

    temp_dir = Path(tempfile.gettempdir())
    temp_dir_writable, temp_dir_detail = _test_directory_writable(temp_dir)
    checks.append(RuntimeCheckResult("临时目录写入权限", temp_dir_writable, temp_dir_detail, True))

    settings_path = app_dir / SETTINGS_FILE_NAME
    if settings_path.exists():
        try:
            settings_path.read_text(encoding="utf-8")
            checks.append(RuntimeCheckResult("配置文件读取", True, f"配置文件可读取：{settings_path}", False))
        except Exception as exc:
            checks.append(RuntimeCheckResult("配置文件读取", False, f"配置文件读取失败：{exc}", False))
    else:
        checks.append(RuntimeCheckResult("配置文件读取", True, f"配置文件不存在，将自动创建：{settings_path}", False))

    try:
        serial_version = getattr(serial, "__version__", "已加载")
        checks.append(RuntimeCheckResult("pyserial 模块", True, f"模块已加载：{serial_version}", True))
    except Exception as exc:
        checks.append(RuntimeCheckResult("pyserial 模块", False, f"模块异常：{exc}", True))

    try:
        ports = list(list_ports.comports())
        checks.append(RuntimeCheckResult("串口枚举", True, f"枚举成功，检测到 {len(ports)} 个串口", False))
    except Exception as exc:
        checks.append(RuntimeCheckResult("串口枚举", False, f"串口枚举失败：{exc}", False))

    try:
        import plc_comm as plc_comm_module

        checks.append(RuntimeCheckResult("PLC 通讯模块", True, "plc_comm 模块已加载", True))
        snap7_loaded = getattr(plc_comm_module, "snap7", None) is not None
        snap7_error = getattr(plc_comm_module, "SNAP7_IMPORT_ERROR", None)
        checks.append(
            RuntimeCheckResult(
                "snap7 运行库",
                snap7_loaded,
                "snap7 已加载" if snap7_loaded else f"snap7 未加载：{snap7_error}",
                False,
            )
        )
    except Exception as exc:
        checks.append(RuntimeCheckResult("PLC 通讯模块", False, f"plc_comm 模块异常：{exc}", True))

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


class ScannerTkApp:
    COLOR_BG = "#0B111B"
    COLOR_PANEL = "#182231"
    COLOR_CARD = "#0F1722"
    COLOR_BORDER = "#31445D"
    COLOR_BORDER_LIGHT = "#425974"
    COLOR_TEXT = "#F2F5FA"
    COLOR_MUTED = "#93A6C1"
    COLOR_ACCENT = "#F3B53A"
    COLOR_ACCENT_HOVER = "#FFC85A"
    COLOR_ERROR = "#D95656"
    COLOR_CONNECTED = "#2D8A63"
    COLOR_PENDING = "#8D6A21"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("工业扫码枪 PLC 终端 - Tk")
        self.root.geometry("1180x720")
        self.root.minsize(980, 620)
        self.root.configure(bg=self.COLOR_BG)

        self.settings_path = _app_base_dir() / SETTINGS_FILE_NAME
        self.output_queue: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.reader_thread: Optional[SerialReaderThread] = None
        self.plc_stop_event: Optional[threading.Event] = None
        self.plc_thread: Optional[PLCWorkerThread] = None
        self.port_options: dict[str, str] = {}
        self.preferred_port_device = ""
        self.com_manual_disconnect = False
        self.plc_connected = False
        self.drawer_open = True
        self.serial_section_open = False
        self.data_section_open = False
        self.heartbeat_section_open = False
        self.com_reconnect_job: Optional[str] = None
        self._startup_auto_run_applying = False
        self._suspend_auto_save = True
        self._pending_save_job: Optional[str] = None

        self.status_var = tk.StringVar(value="等待初始化...")
        self.last_scan_var = tk.StringVar(value="等待扫码")
        self.com_status_var = tk.StringVar(value="未连接")
        self.plc_status_var = tk.StringVar(value="未连接")
        self.output_hint_var = tk.StringVar(value="当前状态：等待连接设备")
        self.data_target_status_var = tk.StringVar(value="当前写入目标：未应用")
        self.heartbeat_status_var = tk.StringVar(value="当前心跳：未应用")

        self.serial_port_var = tk.StringVar()
        self.plc_ip_var = tk.StringVar(value="127.0.0.1")
        self.plc_rack_var = tk.IntVar(value=0)
        self.plc_slot_var = tk.IntVar(value=1)

        self.data_display_text_var = tk.StringVar(value="扫码结果")
        self.data_db_var = tk.IntVar(value=6100)
        self.data_start_var = tk.IntVar(value=36)
        self.data_type_var = tk.StringVar(value="S7STRING")
        self.data_bit_var = tk.IntVar(value=0)
        self.data_enabled_var = tk.BooleanVar(value=True)

        self.heartbeat_name_var = tk.StringVar(value="心跳")
        self.heartbeat_db_var = tk.IntVar(value=6100)
        self.heartbeat_start_var = tk.IntVar(value=0)
        self.heartbeat_type_var = tk.StringVar(value="INT")
        self.heartbeat_bit_var = tk.IntVar(value=0)
        self.heartbeat_value_on_var = tk.StringVar(value="1")
        self.heartbeat_value_off_var = tk.StringVar(value="0")
        self.heartbeat_interval_on_var = tk.DoubleVar(value=1.0)
        self.heartbeat_interval_off_var = tk.DoubleVar(value=1.0)
        self.heartbeat_enabled_var = tk.BooleanVar(value=False)

        self.startup_auto_run_var = tk.BooleanVar(value=False)
        self.startup_auto_run_status_var = tk.StringVar(value="当前状态：未启用")
        self.debug_var = tk.BooleanVar(value=False)

        self._build_ui()
        self._load_startup_auto_run_state()
        self._bind_auto_save()
        self.startup_auto_run_var.trace_add("write", self._on_startup_auto_run_changed)
        self._load_settings_from_json()
        self.apply_data_target_settings(save_to_disk=False)
        self.apply_heartbeat_settings(save_to_disk=False, push_to_runtime=False)
        self.refresh_ports()
        self._sync_heartbeat_controls()
        self._sync_data_controls()
        self._suspend_auto_save = False

        self.root.after(100, self._poll_queue)
        self.root.after(250, self._auto_connect_devices)
        self.root.after(500, self._minimize_on_startup)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self) -> None:
        self._configure_style()
        self.root.columnconfigure(0, weight=0, minsize=520)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.left_shell = tk.Frame(self.root, bg=self.COLOR_BG, width=520)
        self.left_shell.grid(row=0, column=0, sticky="nsew", padx=(16, 8), pady=16)
        self.left_shell.grid_propagate(False)
        self.left_shell.rowconfigure(0, weight=1)
        self.left_shell.columnconfigure(0, weight=1)

        left_canvas = tk.Canvas(self.left_shell, bg=self.COLOR_BG, highlightthickness=0, borderwidth=0)
        self.left_canvas = left_canvas
        left_scroll = ttk.Scrollbar(
            self.left_shell,
            orient="vertical",
            command=left_canvas.yview,
            style="Dark.Vertical.TScrollbar",
        )
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left_canvas.grid(row=0, column=0, sticky="nsew")
        left_scroll.grid(row=0, column=1, sticky="ns")

        left = tk.Frame(left_canvas, bg=self.COLOR_BG)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")

        def _sync_left_scroll(_event=None) -> None:
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))
            left_canvas.itemconfigure(left_window, width=left_canvas.winfo_width())

        left.bind("<Configure>", _sync_left_scroll)
        left_canvas.bind("<Configure>", _sync_left_scroll)

        def _wheel(event) -> None:
            self._scroll_left_settings(event)

        left_canvas.bind_all("<MouseWheel>", _wheel)

        tk.Label(
            left,
            text="设置",
            bg=self.COLOR_BG,
            fg=self.COLOR_ACCENT,
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(anchor="w", padx=(16, 0), pady=(16, 8))

        self._create_startup_panel(left)
        self._create_plc_panel(left)
        self._create_serial_panel(left)
        self._create_data_panel(left)
        self._create_heartbeat_panel(left)

        right = tk.Frame(self.root, bg=self.COLOR_BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=16)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        toolbar = self._make_card(right, bg=self.COLOR_PANEL, border=self.COLOR_BORDER)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        toolbar.columnconfigure(1, weight=1)

        self.settings_button = self._make_button(toolbar, "收起设置", self.toggle_drawer, secondary=True)
        self.settings_button.grid(row=0, column=0, padx=(14, 10), pady=12, sticky="w")

        title_box = tk.Frame(toolbar, bg=self.COLOR_PANEL)
        title_box.grid(row=0, column=1, sticky="ew", pady=10)
        tk.Label(
            title_box,
            text="工业扫码枪 PLC 终端",
            bg=self.COLOR_PANEL,
            fg=self.COLOR_MUTED,
            font=("Consolas", 9),
        ).pack(anchor="w")
        tk.Label(
            title_box,
            text="工业扫码监控终端",
            bg=self.COLOR_PANEL,
            fg=self.COLOR_TEXT,
            font=("Microsoft YaHei UI", 19, "bold"),
        ).pack(anchor="w")

        status_box = tk.Frame(toolbar, bg=self.COLOR_PANEL)
        status_box.grid(row=0, column=2, padx=(12, 14), pady=12, sticky="e")
        self.com_connection_chip = self._make_chip(status_box, "COM 未连接")
        self.com_connection_chip.pack(side="left", padx=(0, 8))
        self.plc_connection_chip = self._make_chip(status_box, "PLC 未连接")
        self.plc_connection_chip.pack(side="left")

        results_card = self._make_card(right, bg=self.COLOR_PANEL, border=self.COLOR_BORDER)
        results_card.grid(row=1, column=0, sticky="nsew")
        results_card.columnconfigure(0, weight=1)
        results_card.rowconfigure(1, weight=1)

        results_header = tk.Frame(results_card, bg=self.COLOR_PANEL)
        results_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 10))
        results_header.columnconfigure(0, weight=1)

        title_group = tk.Frame(results_header, bg=self.COLOR_PANEL)
        title_group.grid(row=0, column=0, sticky="w")
        tk.Label(
            title_group,
            text="扫码结果",
            bg=self.COLOR_PANEL,
            fg=self.COLOR_ACCENT,
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_group,
            textvariable=self.last_scan_var,
            bg=self.COLOR_PANEL,
            fg=self.COLOR_ACCENT,
            font=("Microsoft YaHei UI", 20, "bold"),
        ).pack(anchor="w", pady=(2, 0))

        controls_box = tk.Frame(results_header, bg=self.COLOR_PANEL)
        controls_box.grid(row=0, column=1, sticky="e")
        self.debug_checkbox = self._make_checkbutton(controls_box, "显示调试信息", self.debug_var, bg=self.COLOR_PANEL)
        self.debug_checkbox.pack(side="left", padx=(0, 10))
        self.clear_button = self._make_button(controls_box, "清空输出", self.clear_output, secondary=True)
        self.clear_button.pack(side="left")

        self.output_text = scrolledtext.ScrolledText(
            results_card,
            wrap="word",
            height=22,
            font=("Consolas", 11),
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT,
            insertbackground=self.COLOR_TEXT,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=self.COLOR_BORDER_LIGHT,
            highlightcolor=self.COLOR_ACCENT,
        )
        self.output_text.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 10))
        self.output_text.configure(state="disabled")

        self.status_label = tk.Label(
            results_card,
            textvariable=self.status_var,
            bg=self.COLOR_PANEL,
            fg=self.COLOR_MUTED,
            anchor="w",
        )
        self.status_label.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 14))

        self._set_plc_controls_enabled(True)

    def _configure_style(self) -> None:
        self.root.option_add("*Font", "{Microsoft YaHei UI} 11")
        self.root.option_add("*TCombobox*Listbox.background", self.COLOR_CARD)
        self.root.option_add("*TCombobox*Listbox.foreground", self.COLOR_TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#223246")
        self.root.option_add("*TCombobox*Listbox.selectForeground", self.COLOR_TEXT)
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Dark.TCombobox",
            fieldbackground=self.COLOR_CARD,
            background=self.COLOR_CARD,
            foreground=self.COLOR_TEXT,
            selectbackground="#223246",
            selectforeground=self.COLOR_TEXT,
            bordercolor=self.COLOR_BORDER_LIGHT,
            arrowcolor=self.COLOR_TEXT,
            lightcolor=self.COLOR_BORDER_LIGHT,
            darkcolor=self.COLOR_BORDER_LIGHT,
            padding=(8, 8),
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", self.COLOR_CARD), ("disabled", self.COLOR_PANEL)],
            foreground=[("readonly", self.COLOR_TEXT), ("disabled", self.COLOR_MUTED)],
        )
        style.configure(
            "Dark.Vertical.TScrollbar",
            background=self.COLOR_BORDER_LIGHT,
            troughcolor=self.COLOR_BG,
            bordercolor=self.COLOR_BG,
            arrowcolor=self.COLOR_TEXT,
        )

    def _make_card(self, parent: tk.Widget, *, bg: str | None = None, border: str | None = None) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=bg or self.COLOR_CARD,
            highlightbackground=border or self.COLOR_BORDER_LIGHT,
            highlightthickness=1,
            bd=0,
        )

    def _make_button(
        self,
        parent: tk.Widget,
        text: str,
        command,
        *,
        accent: bool = False,
        secondary: bool = False,
    ) -> FlatButton:
        bg = self.COLOR_ACCENT if accent else (self.COLOR_CARD if secondary else self.COLOR_PANEL)
        fg = self.COLOR_BG if accent else self.COLOR_TEXT
        active_bg = self.COLOR_ACCENT_HOVER if accent else "#223246"
        return FlatButton(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            hover_bg=active_bg,
            disabled_bg=self.COLOR_CARD,
            disabled_fg=self.COLOR_MUTED,
            border=self.COLOR_ACCENT if accent else self.COLOR_BORDER_LIGHT,
            disabled_border=self.COLOR_BORDER_LIGHT,
        )

    def _make_checkbutton(
        self,
        parent: tk.Widget,
        text: str,
        variable: tk.BooleanVar,
        *,
        bg: str | None = None,
    ) -> FlatCheckbutton:
        base_bg = bg or self.COLOR_CARD
        return FlatCheckbutton(
            parent,
            text=text,
            variable=variable,
            bg=base_bg,
            fg=self.COLOR_TEXT,
            muted=self.COLOR_MUTED,
            accent=self.COLOR_ACCENT,
            border=self.COLOR_BORDER_LIGHT,
            disabled=self.COLOR_MUTED,
        )

    def _make_chip(self, parent: tk.Widget, text: str) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            bg=self.COLOR_PANEL,
            fg=self.COLOR_ACCENT,
            padx=14,
            pady=9,
            highlightthickness=1,
            highlightbackground=self.COLOR_BORDER_LIGHT,
            font=("Microsoft YaHei UI", 10, "bold"),
        )

    def _create_startup_panel(self, parent: tk.Widget) -> None:
        startup_frame = self._make_card(parent)
        startup_frame.pack(fill="x", padx=16, pady=(0, 10))
        inner = tk.Frame(startup_frame, bg=self.COLOR_CARD)
        inner.pack(fill="x", padx=12, pady=12)

        self._title(inner, "系统启动")
        self._hint(inner, "勾选后写入当前用户启动项，Windows 登录后自动启动本软件。")
        self.startup_auto_run_check = self._make_checkbutton(inner, "开机自启", self.startup_auto_run_var)
        self.startup_auto_run_check.pack(fill="x", pady=(2, 0))
        tk.Label(
            inner,
            textvariable=self.startup_auto_run_status_var,
            bg=self.COLOR_CARD,
            fg=self.COLOR_MUTED,
            anchor="w",
            justify="left",
            wraplength=450,
        ).pack(fill="x", pady=(8, 0))

    def _create_plc_panel(self, parent: tk.Widget) -> None:
        plc_frame = self._make_card(parent)
        plc_frame.pack(fill="x", padx=16, pady=(0, 10))
        inner = tk.Frame(plc_frame, bg=self.COLOR_CARD)
        inner.pack(fill="x", padx=12, pady=12)

        self._title(inner, "PLC 通讯")
        self._hint(inner, "扫码后直接把结果写入 PLC，断线后会自动重连。")

        self.plc_ip_entry = self._add_labeled_entry(inner, "PLC IP", self.plc_ip_var)
        self.plc_rack_spin = self._add_labeled_spinbox(inner, "机架", self.plc_rack_var, 0, 7)
        self.plc_slot_spin = self._add_labeled_spinbox(inner, "插槽", self.plc_slot_var, 0, 31)

        actions = tk.Frame(inner, bg=self.COLOR_CARD)
        actions.pack(fill="x", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.plc_connect_button = self._make_button(actions, "连接 PLC", self.connect_plc, accent=True)
        self.plc_connect_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.plc_disconnect_button = self._make_button(actions, "断开 PLC", self.disconnect_plc, secondary=True)
        self.plc_disconnect_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.plc_status_label = tk.Label(
            inner,
            text="未连接 PLC",
            bg=self.COLOR_CARD,
            fg=self.COLOR_MUTED,
            anchor="w",
            justify="left",
            wraplength=450,
        )
        self.plc_status_label.pack(fill="x", pady=(10, 0))

    def _create_serial_panel(self, parent: tk.Widget) -> None:
        card, body = self._create_collapsible_card(parent, "串口设置", self.toggle_serial_settings)
        self.serial_section_card = card
        self.serial_section_body = body

        self._title(body, "COM 端口")
        self._hint(body, "在这里选择扫码枪 COM 口，并完成连接或断开。")
        self._add_labeled_combobox(body, "COM 端口", self.serial_port_var, "serial_port_combo")

        actions = tk.Frame(body, bg=self.COLOR_CARD)
        actions.pack(fill="x", pady=(8, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.refresh_button = self._make_button(actions, "刷新串口", self.refresh_ports, secondary=True)
        self.refresh_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.connect_button = self._make_button(actions, "连接设备", self.toggle_connection, accent=True)
        self.connect_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self._hint(body, f"波特率固定为 {DEFAULT_BAUDRATE}")
        self.apply_serial_button = self._make_button(body, "应用参数", self.apply_serial_settings, accent=True)
        self.apply_serial_button.pack(fill="x", pady=(8, 0))
        self._set_section_body_visible(body, self.serial_section_open)

    def _create_data_panel(self, parent: tk.Widget) -> None:
        card, body = self._create_collapsible_card(parent, "数据设置", self.toggle_data_settings)
        self.data_section_card = card
        self.data_section_body = body

        self._title(body, "扫码结果写入 PLC")
        self._hint(body, "扫码完成后，可将结果写入指定 PLC DB 块地址。")
        self._add_labeled_entry(body, "显示文字", self.data_display_text_var)
        self._add_labeled_spinbox(body, "DB 块号", self.data_db_var, 1, 65535)
        self._add_labeled_spinbox(body, "起始字节", self.data_start_var, 0, 65535)
        self._add_labeled_combobox(body, "数据类型", self.data_type_var, "data_type_combo", SUPPORTED_DATA_TYPES)
        self.data_type_combo.bind("<<ComboboxSelected>>", lambda _event: self._sync_data_controls())
        self.data_bit_spin = self._add_labeled_spinbox(body, "BOOL 位", self.data_bit_var, 0, 7)
        self.data_enabled_check = self._make_checkbutton(body, "启用扫码结果写入 PLC", self.data_enabled_var)
        self.data_enabled_check.pack(fill="x", pady=(8, 0))
        self._make_button(body, "应用参数", self.apply_data_target_settings, accent=True).pack(fill="x", pady=(8, 0))
        tk.Label(
            body,
            textvariable=self.data_target_status_var,
            bg=self.COLOR_CARD,
            fg=self.COLOR_MUTED,
            anchor="w",
            justify="left",
            wraplength=450,
        ).pack(fill="x", pady=(8, 0))
        self._set_section_body_visible(body, self.data_section_open)

    def _create_heartbeat_panel(self, parent: tk.Widget) -> None:
        card, body = self._create_collapsible_card(parent, "心跳设置", self.toggle_heartbeat_settings)
        self.heartbeat_section_card = card
        self.heartbeat_section_body = body

        self._title(body, "PLC 心跳发送")
        self._hint(body, "按配置循环向指定 PLC 地址发送值 1 / 值 0，可用于在线心跳检测。")
        self._add_labeled_entry(body, "变量名称", self.heartbeat_name_var)
        self._add_labeled_spinbox(body, "DB 块号", self.heartbeat_db_var, 1, 65535)
        self._add_labeled_spinbox(body, "起始字节", self.heartbeat_start_var, 0, 65535)
        self._add_labeled_combobox(body, "数据类型", self.heartbeat_type_var, "heartbeat_type_combo", SUPPORTED_DATA_TYPES)
        self.heartbeat_type_combo.bind("<<ComboboxSelected>>", lambda _event: self._sync_heartbeat_controls())
        self.heartbeat_bit_spin = self._add_labeled_spinbox(body, "BOOL 位", self.heartbeat_bit_var, 0, 7)
        self._add_labeled_entry(body, "发送值 1", self.heartbeat_value_on_var)
        self._add_labeled_entry(body, "发送值 0", self.heartbeat_value_off_var)
        self._add_labeled_spinbox(body, "发 1 间隔", self.heartbeat_interval_on_var, 0.1, 3600.0, is_float=True, increment=0.1)
        self._add_labeled_spinbox(body, "发 0 间隔", self.heartbeat_interval_off_var, 0.1, 3600.0, is_float=True, increment=0.1)
        self.heartbeat_enabled_check = self._make_checkbutton(body, "启用心跳", self.heartbeat_enabled_var)
        self.heartbeat_enabled_check.pack(fill="x", pady=(8, 0))
        self._make_button(body, "应用心跳设置", self.apply_heartbeat_settings, accent=True).pack(fill="x", pady=(8, 0))
        tk.Label(
            body,
            textvariable=self.heartbeat_status_var,
            bg=self.COLOR_CARD,
            fg=self.COLOR_MUTED,
            anchor="w",
            justify="left",
            wraplength=450,
        ).pack(fill="x", pady=(8, 0))
        self._set_section_body_visible(body, self.heartbeat_section_open)

    def _create_collapsible_card(self, parent: tk.Widget, title: str, command) -> tuple[tk.Frame, tk.Frame]:
        card = self._make_card(parent)
        card.pack(fill="x", padx=16, pady=(0, 10))
        inner = tk.Frame(card, bg=self.COLOR_CARD)
        inner.pack(fill="x", padx=12, pady=12)
        button = self._make_button(inner, f"{title} ▼", command, secondary=True)
        button.pack(fill="x")
        body = tk.Frame(inner, bg=self.COLOR_CARD)
        if title == "串口设置":
            self.serial_section_button = button
        elif title == "数据设置":
            self.data_section_button = button
        elif title == "心跳设置":
            self.heartbeat_section_button = button
        self._set_collapsible_button_state(button, title, False)
        return card, body

    def _set_collapsible_button_state(self, button: FlatButton, title: str, is_open: bool) -> None:
        button.configure(text=f"{title} {'▲' if is_open else '▼'}")
        button.set_palette(
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT,
            hover_bg="#223246",
            border=self.COLOR_BORDER_LIGHT,
        )

    def _set_section_body_visible(self, body: tk.Frame, is_open: bool) -> None:
        if is_open:
            body.pack(fill="x", pady=(12, 0))
        else:
            body.pack_forget()

    def toggle_drawer(self) -> None:
        self.drawer_open = not self.drawer_open
        if self.drawer_open:
            self.root.columnconfigure(0, minsize=520)
            self.left_shell.grid()
            self.settings_button.configure(text="收起设置")
        else:
            self.left_shell.grid_remove()
            self.root.columnconfigure(0, minsize=0)
            self.settings_button.configure(text="设置")

    def toggle_serial_settings(self) -> None:
        self.serial_section_open = not self.serial_section_open
        self._set_section_body_visible(self.serial_section_body, self.serial_section_open)
        self._set_collapsible_button_state(self.serial_section_button, "串口设置", self.serial_section_open)

    def toggle_data_settings(self) -> None:
        self.data_section_open = not self.data_section_open
        self._set_section_body_visible(self.data_section_body, self.data_section_open)
        self._set_collapsible_button_state(self.data_section_button, "数据设置", self.data_section_open)

    def toggle_heartbeat_settings(self) -> None:
        self.heartbeat_section_open = not self.heartbeat_section_open
        self._set_section_body_visible(self.heartbeat_section_body, self.heartbeat_section_open)
        self._set_collapsible_button_state(self.heartbeat_section_button, "心跳设置", self.heartbeat_section_open)

    def _title(self, parent: tk.Widget, text: str) -> None:
        tk.Label(
            parent,
            text=text,
            bg=self.COLOR_CARD,
            fg=self.COLOR_ACCENT,
            anchor="w",
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(fill="x", pady=(0, 8))

    def _hint(self, parent: tk.Widget, text: str) -> None:
        tk.Label(
            parent,
            text=text,
            bg=self.COLOR_CARD,
            fg=self.COLOR_MUTED,
            anchor="w",
            justify="left",
            wraplength=450,
        ).pack(fill="x", pady=(0, 8))

    def _divider(self, parent: tk.Widget) -> None:
        tk.Frame(parent, bg="#111A26", height=1).pack(fill="x", pady=8)

    def _create_signal_row(
        self,
        parent: tk.Widget,
        title: str,
        db_var: tk.IntVar,
        byte_var: tk.IntVar,
        bit_var: tk.IntVar,
    ) -> tuple[tk.Widget, tk.Widget, tk.Widget]:
        tk.Label(parent, text=title, bg=self.COLOR_CARD, fg=self.COLOR_MUTED, anchor="w").pack(fill="x", pady=(0, 6))
        row = tk.Frame(parent, bg=self.COLOR_CARD)
        row.pack(fill="x")
        for column in (1, 3, 5):
            row.columnconfigure(column, weight=1, uniform="signal")
        tk.Label(row, text="DB", bg=self.COLOR_CARD, fg=self.COLOR_TEXT, anchor="w").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        db_spin = self._make_spinbox(row, db_var, 1, 65535)
        db_spin.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        tk.Label(row, text="字节", bg=self.COLOR_CARD, fg=self.COLOR_TEXT, anchor="w").grid(
            row=0, column=2, sticky="w", padx=(0, 6)
        )
        byte_spin = self._make_spinbox(row, byte_var, 0, 65535)
        byte_spin.grid(row=0, column=3, sticky="ew", padx=(0, 10))
        tk.Label(row, text="位", bg=self.COLOR_CARD, fg=self.COLOR_TEXT, anchor="w").grid(
            row=0, column=4, sticky="w", padx=(0, 6)
        )
        bit_spin = self._make_spinbox(row, bit_var, 0, 7)
        bit_spin.grid(row=0, column=5, sticky="ew")
        return db_spin, byte_spin, bit_spin

    def _make_labeled_row(self, parent, label_text: str) -> tk.Frame:
        row = tk.Frame(parent, bg=self.COLOR_CARD)
        row.pack(fill="x", pady=4)
        row.columnconfigure(1, weight=1)
        tk.Label(
            row,
            text=label_text,
            bg=self.COLOR_CARD,
            fg=self.COLOR_MUTED,
            width=12,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))
        return row

    def _add_labeled_entry(self, parent, label_text: str, variable: tk.StringVar) -> tk.Entry:
        row = self._make_labeled_row(parent, label_text)
        entry = tk.Entry(
            row,
            textvariable=variable,
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT,
            insertbackground=self.COLOR_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.COLOR_BORDER_LIGHT,
            highlightcolor=self.COLOR_ACCENT,
            disabledbackground=self.COLOR_PANEL,
            disabledforeground=self.COLOR_MUTED,
        )
        entry.grid(row=0, column=1, sticky="ew")
        return entry

    def _add_labeled_combobox(
        self,
        parent,
        label_text: str,
        variable: tk.StringVar,
        attr_name: str,
        values: tuple[str, ...] | list[str] | None = None,
    ) -> ttk.Combobox:
        row = self._make_labeled_row(parent, label_text)
        combo = ttk.Combobox(row, textvariable=variable, state="readonly", style="Dark.TCombobox")
        if values is not None:
            combo["values"] = list(values)
        combo.bind("<MouseWheel>", self._on_combobox_mousewheel)
        combo.bind("<Button-4>", self._on_combobox_mousewheel)
        combo.bind("<Button-5>", self._on_combobox_mousewheel)
        setattr(self, attr_name, combo)
        combo.grid(row=0, column=1, sticky="ew")
        return combo

    def _scroll_left_settings(self, event) -> None:
        if not hasattr(self, "left_canvas"):
            return
        if getattr(event, "num", None) == 4:
            units = -1
        elif getattr(event, "num", None) == 5:
            units = 1
        else:
            units = int(-1 * (getattr(event, "delta", 0) / 120))
        if units:
            self.left_canvas.yview_scroll(units, "units")

    def _on_combobox_mousewheel(self, event):
        self._scroll_left_settings(event)
        return "break"

    def _make_spinbox(
        self,
        parent: tk.Widget,
        variable: tk.Variable,
        minimum,
        maximum,
        *,
        increment: float = 1.0,
    ) -> tk.Entry:
        return tk.Entry(
            parent,
            textvariable=variable,
            width=8,
            justify="center",
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.COLOR_BORDER_LIGHT,
            highlightcolor=self.COLOR_ACCENT,
            insertbackground=self.COLOR_TEXT,
            disabledbackground=self.COLOR_PANEL,
            disabledforeground=self.COLOR_MUTED,
        )

    def _add_labeled_spinbox(
        self,
        parent,
        label_text: str,
        variable: tk.Variable,
        minimum,
        maximum,
        *,
        is_float: bool = False,
        increment: float = 1.0,
    ):
        row = self._make_labeled_row(parent, label_text)
        spin = self._make_spinbox(row, variable, minimum, maximum, increment=increment)
        spin.grid(row=0, column=1, sticky="ew")
        return spin

    def _bind_auto_save(self) -> None:
        tracked_vars = [
            self.plc_ip_var,
            self.plc_rack_var,
            self.plc_slot_var,
            self.data_display_text_var,
            self.data_db_var,
            self.data_start_var,
            self.data_type_var,
            self.data_bit_var,
            self.data_enabled_var,
            self.heartbeat_name_var,
            self.heartbeat_db_var,
            self.heartbeat_start_var,
            self.heartbeat_type_var,
            self.heartbeat_bit_var,
            self.heartbeat_value_on_var,
            self.heartbeat_value_off_var,
            self.heartbeat_interval_on_var,
            self.heartbeat_interval_off_var,
            self.heartbeat_enabled_var,
        ]
        for variable in tracked_vars:
            variable.trace_add("write", self._schedule_settings_save)

        self.data_type_combo.bind("<<ComboboxSelected>>", lambda event: self._sync_data_controls())
        self.heartbeat_type_combo.bind("<<ComboboxSelected>>", lambda event: self._sync_heartbeat_controls())

    def _schedule_settings_save(self, *_args) -> None:
        if self._suspend_auto_save:
            return
        if self._pending_save_job is not None:
            self.root.after_cancel(self._pending_save_job)
        self._pending_save_job = self.root.after(250, self._save_settings_to_json)

    def _save_settings_to_json(self) -> None:
        self._pending_save_job = None
        selected_port = self._selected_port_device()
        payload = {
            "serial": {
                "selected_port": selected_port,
                "baudrate": DEFAULT_BAUDRATE,
            },
            "plc": {
                "ip_address": self.plc_ip_var.get().strip(),
                "rack": int(self.plc_rack_var.get()),
                "slot": int(self.plc_slot_var.get()),
            },
            "data_target": {
                "display_text": self.data_display_text_var.get().strip() or "扫码结果",
                "db_number": int(self.data_db_var.get()),
                "start": int(self.data_start_var.get()),
                "data_type": self.data_type_var.get().strip(),
                "bit_index": int(self.data_bit_var.get()),
                "enabled": bool(self.data_enabled_var.get()),
            },
            "heartbeat": {
                "display_text": self.heartbeat_name_var.get().strip() or "心跳",
                "db_number": int(self.heartbeat_db_var.get()),
                "start": int(self.heartbeat_start_var.get()),
                "data_type": self.heartbeat_type_var.get().strip(),
                "bit_index": int(self.heartbeat_bit_var.get()),
                "value_on": self.heartbeat_value_on_var.get().strip() or "1",
                "value_off": self.heartbeat_value_off_var.get().strip() or "0",
                "interval_on_seconds": float(self.heartbeat_interval_on_var.get()),
                "interval_off_seconds": float(self.heartbeat_interval_off_var.get()),
                "enabled": bool(self.heartbeat_enabled_var.get()),
            },
        }
        try:
            self.settings_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self._append_log("error", f"保存配置失败: {exc}")

    def _load_settings_from_json(self) -> None:
        if not self.settings_path.exists():
            return
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._append_log("error", f"读取配置失败: {exc}")
            return

        self._suspend_auto_save = True
        try:
            serial_settings = payload.get("serial") if isinstance(payload, dict) else None
            if isinstance(serial_settings, dict):
                selected_port = str(serial_settings.get("selected_port") or "").strip()
                if selected_port:
                    self.preferred_port_device = selected_port
                    self.serial_port_var.set(selected_port)

            plc_settings = payload.get("plc") if isinstance(payload, dict) else None
            if isinstance(plc_settings, dict):
                self.plc_ip_var.set(str(plc_settings.get("ip_address") or "127.0.0.1").strip() or "127.0.0.1")
                self.plc_rack_var.set(int(plc_settings.get("rack", 0)))
                self.plc_slot_var.set(int(plc_settings.get("slot", 1)))

            data_target = payload.get("data_target") if isinstance(payload, dict) else None
            if isinstance(data_target, dict):
                self.data_display_text_var.set(str(data_target.get("display_text") or "扫码结果"))
                self.data_db_var.set(int(data_target.get("db_number", 6100)))
                self.data_start_var.set(int(data_target.get("start", 36)))
                self.data_type_var.set(str(data_target.get("data_type") or "S7STRING").upper())
                self.data_bit_var.set(int(data_target.get("bit_index", 0)))
                self.data_enabled_var.set(bool(data_target.get("enabled", True)))

            heartbeat = payload.get("heartbeat") if isinstance(payload, dict) else None
            if isinstance(heartbeat, dict):
                self.heartbeat_name_var.set(str(heartbeat.get("display_text") or "心跳"))
                self.heartbeat_db_var.set(int(heartbeat.get("db_number", 6100)))
                self.heartbeat_start_var.set(int(heartbeat.get("start", 0)))
                self.heartbeat_type_var.set(str(heartbeat.get("data_type") or "INT").upper())
                self.heartbeat_bit_var.set(int(heartbeat.get("bit_index", 0)))
                self.heartbeat_value_on_var.set(str(heartbeat.get("value_on") or "1"))
                self.heartbeat_value_off_var.set(str(heartbeat.get("value_off") or "0"))
                self.heartbeat_interval_on_var.set(float(heartbeat.get("interval_on_seconds", 1.0)))
                self.heartbeat_interval_off_var.set(float(heartbeat.get("interval_off_seconds", 1.0)))
                self.heartbeat_enabled_var.set(bool(heartbeat.get("enabled", False)))
        finally:
            self._suspend_auto_save = False

    def _sync_data_controls(self) -> None:
        data_type = self.data_type_var.get().strip().upper()
        state = "normal" if data_type == "BOOL" else "disabled"
        self.data_bit_spin.configure(state=state)

    def _sync_heartbeat_controls(self) -> None:
        data_type = self.heartbeat_type_var.get().strip().upper()
        state = "normal" if data_type == "BOOL" else "disabled"
        self.heartbeat_bit_spin.configure(state=state)

    def _startup_run_command(self) -> str:
        if getattr(sys, "frozen", False):
            return f'"{Path(sys.executable).resolve()}"'

        launcher = Path(sys.executable).resolve()
        pythonw = launcher.with_name("pythonw.exe")
        if pythonw.exists():
            launcher = pythonw
        return f'"{launcher}" "{Path(__file__).resolve()}"'

    def _read_startup_run_value(self) -> str:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REGISTRY_KEY, 0, winreg.KEY_READ) as key:
                value, _value_type = winreg.QueryValueEx(key, STARTUP_REGISTRY_VALUE_NAME)
        except FileNotFoundError:
            return ""
        return str(value or "").strip()

    def _set_startup_auto_run(self, enabled: bool) -> None:
        if enabled:
            command = self._startup_run_command()
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                STARTUP_REGISTRY_KEY,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(key, STARTUP_REGISTRY_VALUE_NAME, 0, winreg.REG_SZ, command)
            return

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REGISTRY_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, STARTUP_REGISTRY_VALUE_NAME)
        except FileNotFoundError:
            return

    def _load_startup_auto_run_state(self) -> None:
        enabled = bool(self._read_startup_run_value())
        self._startup_auto_run_applying = True
        try:
            self.startup_auto_run_var.set(enabled)
        finally:
            self._startup_auto_run_applying = False
        self.startup_auto_run_status_var.set("当前状态：已启用" if enabled else "当前状态：未启用")

    def _on_startup_auto_run_changed(self, *_args) -> None:
        if self._startup_auto_run_applying:
            return

        enabled = bool(self.startup_auto_run_var.get())
        try:
            self._set_startup_auto_run(enabled)
        except Exception as exc:
            self._startup_auto_run_applying = True
            try:
                self.startup_auto_run_var.set(not enabled)
            finally:
                self._startup_auto_run_applying = False
            self.startup_auto_run_status_var.set(f"当前状态：设置失败：{exc}")
            self._append_log("error", f"开机自启设置失败: {exc}")
            messagebox.showwarning("提示", f"开机自启设置失败：{exc}")
            return

        self.startup_auto_run_status_var.set("当前状态：已启用" if enabled else "当前状态：未启用")
        self._append_log("status", "开机自启已启用。" if enabled else "开机自启已关闭。")

    def apply_serial_settings(self) -> None:
        self.preferred_port_device = self._selected_port_device()
        self._save_settings_to_json()
        self._append_log("status", f"串口参数已保存：{self.preferred_port_device or '未选择串口'}")

    def _create_data_target_variable(self) -> PLCVariable:
        return PLCVariable(
            name=self.data_display_text_var.get().strip() or "扫码结果",
            db_number=int(self.data_db_var.get()),
            start=int(self.data_start_var.get()),
            data_type=self.data_type_var.get().strip(),
            bit_index=int(self.data_bit_var.get()),
        )

    def _current_data_target_config(self) -> PLCDataTargetConfig:
        variable = self._create_data_target_variable()
        variable.validate()
        return PLCDataTargetConfig(
            display_text=self.data_display_text_var.get().strip() or "扫码结果",
            variable=variable,
            enabled=bool(self.data_enabled_var.get()),
        )

    def apply_data_target_settings(self, save_to_disk: bool = True) -> None:
        try:
            config = self._current_data_target_config()
        except Exception as exc:
            self.data_target_status_var.set(f"数据设置无效：{exc}")
            return

        if save_to_disk:
            self._save_settings_to_json()

        target_text = PLCWorkerThread._format_target(config.variable)
        if config.enabled:
            self.data_target_status_var.set(f"当前写入目标：{config.display_text} -> {target_text}")
        else:
            self.data_target_status_var.set(f"当前写入目标（已禁用）：{config.display_text} -> {target_text}")

    def _create_heartbeat_variable(self) -> PLCVariable:
        return PLCVariable(
            name=self.heartbeat_name_var.get().strip() or "心跳",
            db_number=int(self.heartbeat_db_var.get()),
            start=int(self.heartbeat_start_var.get()),
            data_type=self.heartbeat_type_var.get().strip(),
            bit_index=int(self.heartbeat_bit_var.get()),
        )

    def _current_heartbeat_config(self) -> PLCHeartbeatConfig:
        variable = self._create_heartbeat_variable()
        variable.validate()
        value_on = self.heartbeat_value_on_var.get().strip() or "1"
        value_off = self.heartbeat_value_off_var.get().strip() or "0"
        PLCWorkerThread._coerce_scan_value(value_on, variable)
        PLCWorkerThread._coerce_scan_value(value_off, variable)
        return PLCHeartbeatConfig(
            display_text=self.heartbeat_name_var.get().strip() or "心跳",
            variable=variable,
            value_on=value_on,
            value_off=value_off,
            interval_on_seconds=float(self.heartbeat_interval_on_var.get()),
            interval_off_seconds=float(self.heartbeat_interval_off_var.get()),
            enabled=bool(self.heartbeat_enabled_var.get()),
        )

    def apply_heartbeat_settings(self, save_to_disk: bool = True, push_to_runtime: bool = True) -> None:
        try:
            config = self._current_heartbeat_config()
        except Exception as exc:
            self.heartbeat_status_var.set(f"心跳设置无效：{exc}")
            return

        if save_to_disk:
            self._save_settings_to_json()

        target_text = PLCWorkerThread._format_target(config.variable)
        interval_text = f"{config.interval_on_seconds:.2f}s / {config.interval_off_seconds:.2f}s"
        if config.enabled:
            self.heartbeat_status_var.set(
                f"当前心跳：{config.display_text} -> {target_text}，值 {config.value_on}/{config.value_off}，间隔 {interval_text}"
            )
        else:
            self.heartbeat_status_var.set(
                f"当前心跳（已禁用）：{config.display_text} -> {target_text}，值 {config.value_on}/{config.value_off}"
            )

        if push_to_runtime:
            self._push_heartbeat_config_to_plc(config)

    def _push_heartbeat_config_to_plc(self, config: Optional[PLCHeartbeatConfig] = None) -> None:
        if self.plc_thread is None:
            return
        if config is None:
            try:
                config = self._current_heartbeat_config()
            except Exception:
                return
        self.plc_thread.request_update_heartbeat(config)

    def _current_plc_config(self) -> PLCConnectionConfig:
        config = PLCConnectionConfig(
            ip_address=self.plc_ip_var.get().strip(),
            rack=int(self.plc_rack_var.get()),
            slot=int(self.plc_slot_var.get()),
        )
        if not config.ip_address:
            raise ValueError("PLC IP 不能为空。")
        return config

    def connect_plc(self) -> None:
        try:
            config = self._current_plc_config()
        except Exception as exc:
            messagebox.showwarning("提示", f"PLC 参数无效: {exc}")
            return

        self._save_settings_to_json()
        self._stop_plc_thread()
        self.plc_stop_event = threading.Event()
        self.plc_thread = PLCWorkerThread(config, self.output_queue, self.plc_stop_event)
        self.plc_thread.start()
        self._push_heartbeat_config_to_plc()
        self.plc_connected = False
        self._set_plc_controls_enabled(False)
        self._set_plc_status("正在连接 PLC ...")
        self._set_plc_connection_text("连接中")
        self._append_log("plc", f"开始连接 PLC {config.ip_address}")

    def disconnect_plc(self) -> None:
        self._stop_plc_thread()
        self.plc_connected = False
        self._set_plc_controls_enabled(True)
        self._set_plc_status("已手动断开 PLC")
        self._set_plc_connection_text("未连接")
        self._append_log("plc", "已手动断开 PLC")

    def _stop_plc_thread(self) -> None:
        if self.plc_stop_event is not None:
            self.plc_stop_event.set()
        if self.plc_thread and self.plc_thread.is_alive():
            self.plc_thread.join(timeout=1.0)
        self.plc_thread = None
        self.plc_stop_event = None

    def _set_widget_enabled(self, widget: tk.Widget, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        try:
            widget.configure(state=state)
        except tk.TclError:
            if enabled:
                widget.state(["!disabled"])
            else:
                widget.state(["disabled"])

    def _set_plc_controls_enabled(self, enabled: bool) -> None:
        widgets = [
            self.plc_ip_entry,
            self.plc_rack_spin,
            self.plc_slot_spin,
        ]
        for widget in widgets:
            self._set_widget_enabled(widget, enabled)

        self.plc_connect_button.configure(state="normal" if enabled else "disabled")
        self.plc_disconnect_button.configure(state="disabled" if enabled else "normal")
        self._set_connection_button_palette(self.plc_connect_button, active=enabled)
        self._set_connection_button_palette(self.plc_disconnect_button, active=not enabled)

    def _set_connection_button_palette(self, button: FlatButton, *, active: bool) -> None:
        if active:
            button.set_palette(
                bg=self.COLOR_ACCENT,
                fg=self.COLOR_BG,
                hover_bg=self.COLOR_ACCENT_HOVER,
                border=self.COLOR_ACCENT,
            )
            return
        button.set_palette(
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT,
            hover_bg="#223246",
            border=self.COLOR_BORDER_LIGHT,
        )

    def _set_plc_status(self, message: str) -> None:
        self.plc_status_label.configure(text=message)

    def refresh_ports(self) -> None:
        current_selection = self.serial_port_var.get().strip()
        current_port = self._selected_port_device() if current_selection else self.preferred_port_device
        ports = sorted(list_ports.comports(), key=lambda item: item.device)
        labels = []
        port_lookup: dict[str, str] = {}

        for port in ports:
            description = port.description or "USB Serial Device"
            label = f"{port.device} | {description}"
            labels.append(label)
            port_lookup[label] = port.device
            port_lookup[port.device] = port.device

        self.port_options = port_lookup
        self.serial_port_combo["values"] = labels

        target_label = next((label for label in labels if port_lookup.get(label) == current_port), None)
        if target_label is None and current_port:
            target_label = f"{current_port} | 已保存端口"
            labels.append(target_label)
            self.serial_port_combo["values"] = labels
            self.port_options[target_label] = current_port
            self.port_options[current_port] = current_port

        if target_label is not None:
            self.serial_port_var.set(target_label)
            self.preferred_port_device = self.port_options.get(target_label, "")
        elif labels:
            self.serial_port_var.set(labels[0])
            self.preferred_port_device = port_lookup.get(labels[0], "")
        else:
            self.serial_port_var.set("")
            self.preferred_port_device = current_port

        self._set_status(f"已发现 {len(ports)} 个串口")
        if not self._is_connected():
            self._set_output_status_hint("等待连接设备")

    def toggle_connection(self) -> None:
        if self._is_connected():
            self.disconnect()
        else:
            self.connect()

    def connect(self) -> None:
        port_text = self.serial_port_var.get().strip()
        if not port_text:
            messagebox.showwarning("提示", "请先选择串口。")
            return

        self.preferred_port_device = self._selected_port_device()
        self._save_settings_to_json()
        self.com_manual_disconnect = False
        self._cancel_com_reconnect()
        port = self.port_options.get(port_text, port_text.split("|", 1)[0].strip())
        self.stop_event = threading.Event()
        self.reader_thread = SerialReaderThread(port, DEFAULT_BAUDRATE, self.output_queue, self.stop_event)
        self.reader_thread.start()

        self.refresh_button.configure(state="disabled")
        self.serial_port_combo.configure(state="disabled")
        self.connect_button.configure(text="断开连接")
        self._set_com_connection_text("连接中")
        self._set_status(f"正在连接 {port} ...")
        self._set_output_status_hint("正在连接扫码枪...")

    def _auto_connect_devices(self) -> None:
        if self.plc_thread is None:
            self.connect_plc()

        if self._is_connected():
            return

        if self.serial_port_var.get().strip():
            self.connect()
        else:
            self._schedule_com_reconnect("未发现可用 COM 口")

    def disconnect(self) -> None:
        self.com_manual_disconnect = True
        self._cancel_com_reconnect()
        self.stop_event.set()
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=1.0)
        self.reader_thread = None
        self.refresh_button.configure(state="normal")
        self.serial_port_combo.configure(state="readonly")
        self.connect_button.configure(text="连接设备")
        self._set_com_connection_text("未连接")
        self._set_status("未连接")
        self._set_output_status_hint("连接已断开")

    def _schedule_com_reconnect(self, reason: str) -> None:
        if self.com_manual_disconnect:
            return
        self._cancel_com_reconnect()
        self.refresh_ports()
        self._set_status(f"{reason}，{int(COM_RECONNECT_INTERVAL_SECONDS)} 秒后自动重连。")
        self._set_output_status_hint("COM 重连中")
        self._set_com_connection_text("重连中")
        self.com_reconnect_job = self.root.after(int(COM_RECONNECT_INTERVAL_SECONDS * 1000), self._attempt_com_reconnect)

    def _cancel_com_reconnect(self) -> None:
        if self.com_reconnect_job is None:
            return
        try:
            self.root.after_cancel(self.com_reconnect_job)
        except tk.TclError:
            pass
        self.com_reconnect_job = None

    def _attempt_com_reconnect(self) -> None:
        self.com_reconnect_job = None
        if self.com_manual_disconnect or self._is_connected():
            return
        self.refresh_ports()
        if not self.serial_port_var.get().strip():
            self._schedule_com_reconnect("未发现可用 COM 口")
            return
        self.connect()

    def _poll_queue(self) -> None:
        while True:
            try:
                event_type, payload = self.output_queue.get_nowait()
            except queue.Empty:
                break

            if event_type == "scan":
                self._show_scan(payload)
            elif event_type == "status":
                if self.debug_var.get():
                    self._append_log("status", payload)
                self._set_status(str(payload))
                if isinstance(payload, str) and payload.startswith("已连接"):
                    self._cancel_com_reconnect()
                    self.com_manual_disconnect = False
                    self._set_com_connection_text("已连接")
                    self._set_output_status_hint("等待扫码")
                if payload == "串口已断开":
                    self.reader_thread = None
                    self.refresh_button.configure(state="normal")
                    self.serial_port_combo.configure(state="readonly")
                    self.connect_button.configure(text="连接设备")
                    self._set_com_connection_text("未连接")
                    self._set_output_status_hint("连接已断开")
                    if not self.com_manual_disconnect:
                        self._schedule_com_reconnect("串口已断开")
            elif event_type == "error":
                self._append_log("error", payload)
                self._set_status(str(payload))
                self.reader_thread = None
                self.refresh_button.configure(state="normal")
                self.serial_port_combo.configure(state="readonly")
                self.connect_button.configure(text="连接设备")
                self._set_com_connection_text("连接失败")
                self._set_output_status_hint("连接失败")
                self._schedule_com_reconnect(str(payload))
            elif event_type == "plc_status":
                if self.debug_var.get():
                    self._append_log("plc", payload)
                self._set_plc_status(str(payload))
                self._set_plc_connection_text("重连中")
            elif event_type == "plc_connected":
                self.plc_connected = True
                self._set_plc_status(str(payload))
                self._set_plc_connection_text("已连接")
                self._append_log("plc", payload)
            elif event_type == "plc_disconnected":
                self.plc_connected = False
                self._set_plc_status(str(payload))
                self._set_plc_connection_text("重连中")
                self._append_log("plc", payload)
                self._set_output_status_hint("PLC 重连中")
            elif event_type == "plc_error":
                self.plc_connected = False
                self._set_plc_status(str(payload))
                self._set_plc_connection_text("异常")
                self._append_log("error", payload)
                self._set_output_status_hint("PLC 连接异常")
            elif event_type == "plc_data_written":
                self._set_plc_status(str(payload))
                self._append_log("plc", payload)
                self._set_status("扫码结果已写入 PLC，等待扫码")
                self._set_output_status_hint("等待扫码")
            elif event_type == "plc_data_error":
                self._set_plc_status(str(payload))
                self._append_log("error", payload)
                self._set_output_status_hint("扫码数据写入 PLC 失败")
            elif event_type == "heartbeat_error":
                self.heartbeat_status_var.set(f"心跳运行失败：{payload}")
                self._append_log("error", payload)

        self.root.after(100, self._poll_queue)

    def _show_scan(self, payload: dict[str, object]) -> None:
        text = str(payload.get("text") or "<空数据>")

        self.last_scan_var.set(text)

        if self.debug_var.get():
            detail = f"[{payload['source']}] len={payload['length']} text={text} | hex={payload['hex']}"
            self._append_log("scan", detail)
        else:
            self._append_scan_text(text)

        self._write_scan_result_to_plc(text)
        self._set_status(f"最近一次扫码：{text}")

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

    def _append_log(self, level: str, message: object) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        if level.lower() == "scan":
            label = "收到扫码内容"
        elif level.lower() == "plc":
            label = "PLC"
        elif level.lower() == "error":
            label = "ERROR"
        else:
            label = "STATUS"

        self.output_text.configure(state="normal")
        self.output_text.insert("end", f"[{timestamp}] {label} {message}\n")
        self.output_text.see("end")
        self.output_text.configure(state="disabled")

    def _append_scan_text(self, text: str) -> None:
        self._append_log("scan", text)

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _set_output_status_hint(self, message: str) -> None:
        self.output_hint_var.set(f"当前状态：{str(message).strip() or '等待扫码'}")

    def _set_com_connection_text(self, text: str) -> None:
        self.com_status_var.set(text)
        self._set_chip_state(self.com_connection_chip, "COM", text)

    def _set_plc_connection_text(self, text: str) -> None:
        self.plc_status_var.set(text)
        self._set_chip_state(self.plc_connection_chip, "PLC", text)

    def _set_chip_state(self, chip: tk.Label, prefix: str, text: str) -> None:
        mode_color = self.COLOR_ACCENT
        if "已连接" in text:
            mode_color = self.COLOR_CONNECTED
        elif any(key in text for key in ("异常", "失败")):
            mode_color = self.COLOR_ERROR
        elif any(key in text for key in ("连接中", "重连中")):
            mode_color = self.COLOR_ACCENT
        chip.configure(text=f"{prefix} {text}", fg=mode_color)

    def _selected_port_device(self) -> str:
        current_text = self.serial_port_var.get().strip()
        return self.port_options.get(current_text, current_text.split("|", 1)[0].strip())

    def _is_connected(self) -> bool:
        return self.reader_thread is not None and self.reader_thread.is_alive()

    def clear_output(self) -> None:
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.configure(state="disabled")

    def _minimize_on_startup(self) -> None:
        try:
            self.root.iconify()
            _write_startup_log("Tk 主窗口已按启动设置自动最小化。")
        except tk.TclError as exc:
            _write_startup_log(f"Tk 主窗口自动最小化失败：{exc}")

    def on_close(self) -> None:
        self.disconnect_plc()
        self.disconnect()
        self.root.destroy()


def main() -> int:
    _write_startup_log("-" * 72)
    _write_startup_log("Tk 版软件启动开始。")
    _write_startup_log(f"应用目录：{_app_base_dir()}")
    _write_startup_log(f"启动程序：{sys.executable}")

    runtime_checks = _collect_runtime_checks()
    _log_runtime_checks(runtime_checks)
    blocking_checks = [check for check in runtime_checks if not check.passed and check.blocking]
    if blocking_checks:
        message = _format_runtime_issues("启动环境检查未通过，程序无法继续运行。", blocking_checks)
        _write_startup_log(message)
        _show_native_message_box("运行环境不满足", message)
        return 1

    lock = SingleInstanceLock(SINGLE_INSTANCE_LOCK_PATH)
    if not lock.acquire():
        _write_startup_log("检测到 Tk 版软件已在运行。")
        _show_native_message_box("重复打开提示", "软件已经在运行，请不要重复打开。", style=0x30)
        return 0

    try:
        _write_startup_log("准备创建 Tk 根窗口。")
        root = tk.Tk()
        _write_startup_log("Tk 根窗口创建成功。")
        app = ScannerTkApp(root)
        _write_startup_log("Tk 主界面创建成功。")
        root.after(0, lambda: _write_startup_log("Tk 事件循环已启动。"))
        _write_startup_log("准备进入 Tk mainloop。")
        root.mainloop()
        _write_startup_log("Tk mainloop 已退出。")
        return 0
    except Exception as exc:
        _write_startup_log("Tk 启动过程中发生异常。")
        _write_startup_log(traceback.format_exc().rstrip())
        _show_native_message_box("启动异常", f"Tk 版启动失败：{exc}\n\n日志文件：{_startup_log_path()}")
        return 1
    finally:
        lock.release()
        _write_startup_log("单实例锁已释放。")


if __name__ == "__main__":
    raise SystemExit(main())
