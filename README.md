# Industrial Barcode Scanner PLC Terminal

Industrial Barcode Scanner PLC Terminal is a Windows desktop application for reading barcode scanner data over a serial port and writing scan results to a Siemens S7 PLC. The project includes a PyQt desktop UI, a Tkinter desktop UI, configurable PLC addresses, heartbeat output, local runtime settings, reconnect logic, and startup diagnostics.

工业扫码枪 PLC 终端是一款 Windows 桌面软件，用于通过串口读取扫码枪数据，并将扫码结果写入西门子 S7 PLC。项目包含 PyQt 界面版和 Tkinter 界面版，支持 PLC 地址配置、心跳写入、本地运行配置、自动重连和启动环境检查。

## Features

- Serial barcode scanner connection with configurable COM port.
- Siemens S7 PLC communication through `python-snap7`.
- Configurable scan-result write target and heartbeat target.
- Chinese desktop UI for on-site operation.
- Local settings saved to `scanner_settings.json`.
- Startup checks and runtime logs for troubleshooting.

## Download

Packaged Windows executables are available in GitHub Releases:

[Download v1.0.0](https://github.com/JC-qq897888271/industrial-barcode-scanner-plc-terminal/releases/tag/v1.0.0)

Release assets:

- `IndustrialBarcodeScannerPLC-Tk.exe` - Tkinter version with startup auto-run support.
- `IndustrialBarcodeScannerPLC-Qt.exe` - PyQt version.

## Files

- `扫码枪.py` - PyQt desktop application.
- `扫码枪_tk.py` - Tkinter desktop application with startup auto-run support.
- `plc_comm.py` - Siemens S7 PLC communication helper.
- `plc_comm使用说明.py` - Chinese usage examples for the PLC helper.
- `scanner_settings.example.json` - sanitized example runtime configuration.

## Requirements

- Python 3.9+
- pyserial
- python-snap7
- PyQt5 for the PyQt UI
- Tkinter, included with most Windows Python installations

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

## Run

PyQt version:

```powershell
python .\扫码枪.py
```

Tkinter version:

```powershell
python .\扫码枪_tk.py
```

## Configuration

Copy the example configuration if you want to start from a template:

```powershell
Copy-Item .\scanner_settings.example.json .\scanner_settings.json
```

`scanner_settings.json` is ignored by Git because it may contain local COM ports, PLC addresses, DB addresses, and runtime choices.

## Notes

- Build outputs, packaged executables, cache files, logs, local scanner profiles, and crash reports are ignored by default.
- The included PLC examples use placeholder addresses. Adjust COM port, PLC IP, Rack, Slot, DB number, and data types before connecting to real equipment.
- Use the software only after verifying PLC addresses and signal behavior in a safe test environment.

## License

This project is licensed under the MIT License. See `LICENSE` for details.
