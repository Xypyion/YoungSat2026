# Team Jenny web ground station

Our own browser-based ground station (served at `http://localhost:8765/`):
- **Bluetooth link** to the satellite (Web Bluetooth)
- **Sends the full setup in one go:** reference, strategy, Kp/Kd, target, estimator and Momentum profile
- **Read-back table:** checks every setting the satellite reports against the form
- **Live ADCS samples:** angle, error, rate and wheel command
- **One-click debug report.** One of these found the control-sign bug: see `../docs/evidence/gs_debug_report_2026-10-08-14-09-59.txt`.

> The source files will be added here (it runs on our second laptop).
