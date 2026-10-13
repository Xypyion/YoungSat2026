# SunSeek Ground Station Lite (Team SuperTem)

A simpler desktop ground station we wrote for SunSeek, with a guided PD tuner and a built-in simulator.

## Run
```
pip install -r requirements.txt
python sunseek_gs.py
```
On Windows you can double-click `run.bat` instead.

Needs Python 3.10+ with PySide6, bleak, pyqtgraph and pyserial.

## What it does
- **Links:** Bluetooth (BLE, Nordic-UART style) or USB serial (115200) to the satellite, or a **built-in simulator** for practice without hardware.
- **Commands:** the same one-line ASCII protocol as the firmware (see [../docs/COMMANDS.md](../docs/COMMANDS.md)).
- **Live plots:** angle vs target, pointing error, wheel command.
- **Guided PD tuner:** step tests and an auto-tune helper.
- **Save gains:** writes Kp/Kd as power-on defaults into `../firmware/SunSeek_Platform_Firmware_v3_2_TeamSuperTem_OURS/Config_ADCS.h`. If the file isn't found, it asks you to pick it.
- **Saved settings:** in `~/.sunseek_gs_lite.json`.

## Status
- **Written for firmware v2.1** and tested only against its built-in simulator.
- **Uses only standard commands** (`ADCS_*`, `SET_TARGET`, `RW`, `STATUS`, …). For our v3.2-only commands (`ADCS_CONTROL_SIGN`, `ADCS_CTRL_MODE`, …), type them in its terminal box.
- **Plot limit is 80 %.** Its built-in limit mirrors the original firmware (`MAX_RW = 80`); our v3.2 limits the wheel to 45 % itself.

The hardware testing and the debug report in `../docs/evidence/` were done with a separate browser-based ground station we wrote, which lives on another laptop.
