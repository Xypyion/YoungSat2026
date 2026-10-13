"""SunSeek Ground Station Lite

A simpler ground station for SunSeek Platform Firmware v2.1, with a guided
PD tuner. Talks to the spacecraft over Bluetooth (BLE) or USB serial, or to a
built-in simulator for practice.

Run:  python sunseek_gs.py
Needs: PySide6, bleak, pyqtgraph, pyserial   (pip install -r requirements.txt)
"""
import asyncio
import json
import math
import random
import re
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QLocale, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QSlider, QSpinBox,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
    QHeaderView, QFileDialog,
)
import pyqtgraph as pg

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    BleakClient = BleakScanner = None
try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None

RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # GS -> spacecraft (write)
TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # spacecraft -> GS (notify)

# Mirrors of firmware limits (Config_ADCS.h)
KP_MAX = 20.0
KD_MAX = 20.0
MAX_RW = 80
DEADBAND = 2.0

SETTINGS_FILE = Path.home() / ".sunseek_gs_lite.json"
FIRMWARE_CONFIG_ADCS = (Path(__file__).resolve().parent.parent / "firmware"
                        / "SunSeek_Platform_Firmware_v3_2_TeamJenny_OURS" / "Config_ADCS.h")


def wrap360(x):
    return x % 360.0


def wrap180(x):
    x = (x + 180.0) % 360.0 - 180.0
    return 180.0 if x == -180.0 else x


def parse_kv(line):
    """'TM,A,1,B,2' -> {'A': '1', 'B': '2'}"""
    parts = line.split(",")[1:]
    return {parts[i].strip(): parts[i + 1].strip() for i in range(0, len(parts) - 1, 2)}


# ---------------------------------------------------------------------------
# Links: all three expose the same signals and open/close/send.
# ---------------------------------------------------------------------------
class BleLink(QObject):
    line = Signal(str)
    status = Signal(bool, str)
    error = Signal(str)
    found = Signal(list)

    def __init__(self):
        super().__init__()
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.client = None
        self._buf = ""
        self._lock = None

    def _run(self, coro):
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    def scan(self):
        self._run(self._scan())

    async def _scan(self):
        if BleakScanner is None:
            self.error.emit("Install bleak:  pip install bleak")
            self.found.emit([])
            return
        try:
            devs = await BleakScanner.discover(timeout=5)
            out = sorted((d.name, d.address) for d in devs
                         if (d.name or "").upper().startswith("SUNSEEK"))
            self.found.emit(out)
        except Exception as e:
            self.error.emit(f"Bluetooth scan failed: {e}")
            self.found.emit([])

    def open(self, address, name=""):
        self._run(self._connect(address, name))

    async def _connect(self, address, name):
        try:
            await self._disconnect(quiet=True)
            self.client = BleakClient(
                address, disconnected_callback=lambda _c: self.status.emit(False, ""))
            await self.client.connect()
            await self.client.start_notify(TX_UUID, self._notify)
            self.status.emit(True, name or address)
        except Exception as e:
            self.client = None
            self.error.emit(f"Bluetooth connect failed: {e}")
            self.status.emit(False, "")

    def close(self):
        self._run(self._disconnect())

    async def _disconnect(self, quiet=False):
        c, self.client = self.client, None
        if c is not None and c.is_connected:
            try:
                await c.disconnect()
            except Exception:
                pass
        if not quiet:
            self.status.emit(False, "")

    def send(self, text):
        self._run(self._send(text))

    async def _send(self, text):
        # One lock so commands always arrive in the order they were sent.
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if not (self.client and self.client.is_connected):
                self.error.emit("Not connected")
                return
            try:
                await self.client.write_gatt_char(RX_UUID, (text + "\n").encode(), response=True)
            except Exception as e:
                self.error.emit(f"Bluetooth send failed: {e}")

    def _notify(self, _sender, data):
        self._buf += bytes(data).decode("utf-8", "replace")
        while "\n" in self._buf:
            ln, self._buf = self._buf.split("\n", 1)
            ln = ln.strip()
            if ln:
                self.line.emit(ln)


class SerialLink(QObject):
    line = Signal(str)
    status = Signal(bool, str)
    error = Signal(str)
    found = Signal(list)

    def __init__(self):
        super().__init__()
        self.ser = None
        self._alive = False
        self._lock = threading.Lock()

    def scan(self):
        if serial is None:
            self.error.emit("Install pyserial:  pip install pyserial")
            self.found.emit([])
            return
        self.found.emit([(f"{p.device}  {p.description}", p.device)
                         for p in serial.tools.list_ports.comports()])

    def open(self, port, name=""):
        try:
            s = serial.Serial()
            s.port, s.baudrate, s.timeout = port, 115200, 0.2
            s.dtr = False  # do not hold the ESP32 in reset / boot mode
            s.rts = False
            s.open()
            self.ser = s
        except Exception as e:
            self.error.emit(f"Serial open failed: {e}")
            self.status.emit(False, "")
            return
        self._alive = True
        threading.Thread(target=self._reader, daemon=True).start()
        self.status.emit(True, port)

    def _reader(self):
        buf = b""
        while self._alive:
            try:
                buf += self.ser.read(256)
            except Exception as e:
                if self._alive:
                    self.error.emit(f"Serial read failed: {e}")
                break
            while b"\n" in buf:
                ln, buf = buf.split(b"\n", 1)
                ln = ln.decode("utf-8", "replace").strip()
                if ln:
                    self.line.emit(ln)
        self._alive = False
        self.status.emit(False, "")

    def close(self):
        self._alive = False
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    def send(self, text):
        if not (self.ser and self.ser.is_open):
            self.error.emit("Not connected")
            return
        with self._lock:
            try:
                self.ser.write((text + "\n").encode())
            except Exception as e:
                self.error.emit(f"Serial send failed: {e}")


class SimLink(QObject):
    """Rough single-axis spacecraft on a reaction wheel, running the same PD law,
    deadband, output limit and telemetry format as the firmware. For practice."""
    line = Signal(str)
    status = Signal(bool, str)
    error = Signal(str)
    found = Signal(list)

    DT = 0.02         # firmware ADCS_CONTROL_PERIOD_MS
    TM_PERIOD = 0.25  # firmware ADCS_TM_PERIOD_MS

    def __init__(self):
        super().__init__()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._step)
        self.reset()

    def reset(self):
        self.theta, self.omega, self.wheel = random.uniform(0, 360), 0.0, 0.0
        self.cmd = 0
        self.mode, self.ref, self.strategy = "MANUAL", "SUN", "REACTION"
        self.kp, self.kd, self.bias, self.target = 2.0, 0.5, 40, 0.0
        self.streams = {"SUN": False, "MAG": False, "GYRO": False, "ADCS": False}
        self.t_tm = self.t_sensor = 0.0

    def scan(self):
        self.found.emit([("SUNSEEK-SIMULATOR", "sim")])

    def open(self, address, name=""):
        self.reset()
        self.timer.start(int(self.DT * 1000))
        self.status.emit(True, "SUNSEEK-SIMULATOR")

    def close(self):
        self.timer.stop()
        self.status.emit(False, "")

    # sensors
    def _heading(self):
        return wrap360(self.theta + random.gauss(0, 0.4))

    def _sun(self):
        return max(-90.0, min(90.0, wrap180(self.theta) + random.gauss(0, 0.3)))

    def _rate(self):
        return self.omega + random.gauss(0, 0.2)

    def _measured(self):
        return self._heading() if self.ref == "MAG" else self._sun()

    def _error(self, angle):
        e = self.target - angle
        return wrap180(e) if self.ref == "MAG" else e

    def _step(self):
        # Control (same structure as adcsUpdate)
        if self.mode == "AUTO":
            e, r = self._error(self._measured()), self._rate()
            u = self.kp * e - self.kd * r if abs(e) >= DEADBAND else 0.0
            if self.strategy == "REACTION":
                self.cmd = int(round(max(-MAX_RW, min(MAX_RW, u))))
            else:
                self.cmd = int(round(max(0, min(MAX_RW, self.bias + u))))
        # Plant: wheel lags its command; body gets the opposite momentum change.
        old = self.wheel
        self.wheel += (self.cmd - self.wheel) * self.DT / 0.35
        self.omega += 1.6 * (self.wheel - old)  # sign chosen so ADCS_CONTROL_SIGN = +1 works
        self.omega -= 0.15 * self.omega * self.DT          # bearing / air drag
        if abs(self.omega) < 0.6 and abs(self.wheel - old) < 0.01:
            self.omega *= 0.9                               # static friction
        self.theta += self.omega * self.DT

        now = time.monotonic()
        if self.streams["ADCS"] and now - self.t_tm >= self.TM_PERIOD:
            self.t_tm = now
            ang = self._measured()
            e = self._error(ang)
            self.line.emit(
                f"TM,ADCS_MODE,{self.mode},ADCS_REFERENCE,{self.ref},TARGET,{self.target:.2f},"
                f"POINTING_ERROR,{e:.2f},SUN_ERROR,{self.target - self._sun():.2f},"
                f"MAG_ERROR,{wrap180(self.target - self._heading()):.2f},"
                f"GYRO_Z,{self._rate():.3f},RW_CMD,{self.cmd}")
            self.line.emit(f"TM,EST_RAW,{ang:.2f},EST_FILTERED,{ang:.2f},EST_ANGLE,{ang:.2f}")
        if any(self.streams[k] for k in ("SUN", "MAG", "GYRO")) and now - self.t_sensor >= 0.2:
            self.t_sensor = now
            self._sensor_lines(self.streams["SUN"], self.streams["MAG"], self.streams["GYRO"])

    def _sensor_lines(self, sun, mag, gyro):
        if sun:
            a = self._sun()
            ndv = a / 90.0
            l, r = int(2000 * (1 + ndv)), int(2000 * (1 - ndv))
            self.line.emit(f"TM,SUN_L,{l},SUN_R,{r},SUN_NDV,{ndv:.4f},SUN_ANGLE,{a:.2f}")
        if mag:
            h = math.radians(self._heading())
            self.line.emit(f"TM,MAG_X,{30*math.cos(h):.2f},MAG_Y,{30*math.sin(h):.2f},"
                           f"MAG_Z,-40.00,MAG_HEADING,{math.degrees(h) % 360:.2f}")
        if gyro:
            r = self._rate()
            self.line.emit(f"TM,GYRO_X,{random.gauss(0,.2):.3f},GYRO_Y,{random.gauss(0,.2):.3f},"
                           f"GYRO_Z,{r:.3f},BODY_RATE,{r:.3f}")

    def send(self, text):
        QTimer.singleShot(5, lambda: self._handle(text.strip()))

    def _handle(self, c):
        ack = lambda: self.line.emit("ACK," + c)
        err = lambda m: self.line.emit("ERR," + m)
        if c == "PING":
            self.line.emit("PONG")
        elif c in ("STOP", "RW_STOP"):
            self.mode, self.cmd = "MANUAL", 0
            if c == "STOP":
                for k in self.streams:
                    if k != "ADCS":
                        self.streams[k] = False
            ack()
        elif c == "ADCS_MODE,MANUAL":
            self.mode = "MANUAL"
            ack()
        elif c == "ADCS_MODE,AUTO":
            self.mode = "AUTO"
            self.cmd = self.bias if self.strategy == "MOMENTUM" else 0
            ack()
        elif c.startswith("ADCS_REFERENCE,"):
            if self.mode == "AUTO":
                return err("REFERENCE_CHANGE_REQUIRES_MANUAL")
            self.ref = c.split(",")[1]
            ack()
        elif c.startswith("ADCS_STRATEGY,"):
            if self.mode == "AUTO":
                return err("STRATEGY_CHANGE_REQUIRES_MANUAL")
            self.strategy, self.cmd = c.split(",")[1], 0
            ack()
        elif c.startswith("ADCS_TUNE,"):
            kp, kd, b = (float(x) for x in c.split(",")[1:4])
            self.kp, self.kd, self.bias = kp, kd, int(round(b))
            ack()
        elif c.startswith("SET_TARGET,"):
            if self.mode == "AUTO":
                return err("TARGET_OUT_OF_RANGE_OR_AUTO")
            self.target = float(c.split(",")[1])
            ack()
        elif c.startswith("RW,"):
            if self.mode == "AUTO":
                return err("MANUAL_RW_COMMAND_REQUIRES_MANUAL_MODE")
            self.cmd = int(round(float(c.split(",")[1])))
            ack()
        elif c.startswith("TM_STREAM,"):
            p = c.split(",")
            if p[1] == "QUIET":
                self.streams = dict.fromkeys(self.streams, False)
            elif p[1] == "ALL":
                for k in ("SUN", "MAG", "GYRO"):
                    self.streams[k] = p[2] == "ON"
            elif p[1] in self.streams:
                self.streams[p[1]] = p[2] == "ON"
            ack()
        elif c == "SUN_RAW":
            self._sensor_lines(True, False, False)
        elif c == "MAG_RAW":
            self._sensor_lines(False, True, False)
        elif c == "GYRO_RAW":
            self._sensor_lines(False, False, True)
        elif c in ("TM_SNAPSHOT,ALL", "SENSOR_STATUS"):
            self._sensor_lines(True, True, True)
        elif c == "STATUS":
            ack()
            self.line.emit(f"TM,ADCS_MODE,{self.mode},ADCS_REFERENCE,{self.ref},TARGET,{self.target:.2f},"
                           f"KP,{self.kp:.3f},KD,{self.kd:.3f},MOMENTUM_BIAS,{self.bias}")
            self.line.emit(f"TM,SAT_ID,SUNSEEK-SIMULATOR,ADCS_STRATEGY,{self.strategy}")
        else:
            err("UNKNOWN_COMMAND")


# ---------------------------------------------------------------------------
# PD step-response analysis + tuning advice (pure functions, no Qt)
# ---------------------------------------------------------------------------
def analyze_step(samples, deadband=DEADBAND, max_rw=MAX_RW):
    """samples: list of (t, pointing_error_deg, rw_cmd). Returns metrics dict."""
    m = {"ok": False, "overshoot": None, "rise": None, "settle": None, "sse": None,
         "crossings": 0, "sat": 0.0, "diverged": False, "small": False, "e0": 0.0}
    if len(samples) < 6:
        m["reason"] = "Not enough telemetry (is ADCS telemetry on?)"
        return m
    t0 = samples[0][0]
    ts = [s[0] - t0 for s in samples]
    e = [s[1] for s in samples]
    e0 = max(e[:3], key=abs)
    m["e0"] = e0
    if abs(e0) < 8:
        m["small"] = True
        m["reason"] = "Step too small — use at least 20–45°"
        return m
    sgn = 1.0 if e0 > 0 else -1.0
    n = [x * sgn for x in e]          # starts positive, goal is 0, negative = overshoot
    E0 = abs(e0)
    m["ok"] = True
    m["overshoot"] = max(0.0, -min(n)) / E0 * 100.0
    m["rise"] = next((ts[i] for i, x in enumerate(n) if x <= 0.1 * E0), None)
    tol = max(deadband + 2.0, 0.08 * E0)   # firmware stops pushing inside the ±2° deadband
    m["tol"] = tol
    outside = [i for i, x in enumerate(n) if abs(x) > tol]
    last_out = outside[-1] if outside else -1
    if last_out < len(n) - 1 and ts[-1] - ts[last_out + 1] >= 1.0:
        m["settle"] = ts[last_out + 1]
    sign_seq = [1 if x > 0 else -1 for x in n if abs(x) > deadband]
    m["crossings"] = sum(1 for a, b in zip(sign_seq, sign_seq[1:]) if a != b)
    tail = n[int(len(n) * 0.75):]
    m["sse"] = sum(tail) / len(tail) * sgn
    m["sat"] = sum(1 for s in samples if abs(s[2]) >= max_rw - 1) / len(samples)
    late = n[len(n) // 2:]
    if max(abs(x) for x in late) > 1.3 * E0 or (m["rise"] is None and min(late) > 0.95 * E0):
        m["diverged"] = True
    return m


def suggest_gains(m, kp, kd, duration):
    """Returns (new_kp, new_kd, message, good)."""
    clamp = lambda v, hi: round(max(0.0, min(hi, v)), 3)
    if not m["ok"]:
        return kp, kd, m.get("reason", "No result"), False
    if m["diverged"]:
        return kp, kd, ("Error got BIGGER — the wheel pushes the wrong way. Press STOP, flip "
                        "ADCS_CONTROL_SIGN in Config_ADCS.h (1.0f ↔ -1.0f) and upload again."), False
    ov, osc = m["overshoot"], m["crossings"]
    note = ""
    if m["sat"] > 0.6:
        note = "  (Wheel is at max 80 most of the time — more gain won't make it faster.)"
    if osc >= 3 or ov > 30:
        nkd = kd * 1.6 if kd > 0.01 else max(0.2, 0.3 * kp)
        nkp = kp * 0.8 if m["sat"] > 0.5 else kp
        return clamp(nkp, KP_MAX), clamp(nkd, KD_MAX), "Wobbles / big overshoot → more damping (Kd ↑)." + note, False
    if ov > 20:
        nkd = max(kd * 1.4, 0.15 * kp)
        return kp, clamp(nkd, KD_MAX), "Some overshoot → a bit more Kd." + note, False
    if m["rise"] is None or m["settle"] is None:
        # Clean but not there yet: push harder; trim Kd if it is braking too much.
        nkd = kd * 0.7 if kd > 0.6 * kp else kd
        grow = 1.3 if ov > 5 else 1.7
        return clamp(kp * grow, KP_MAX), clamp(nkd, KD_MAX), "Too slow / stops short → more Kp." + note, False
    if abs(m["sse"]) > DEADBAND + 2.0:
        return clamp(kp * 1.3, KP_MAX), kd, "Stops short of the target (friction) → more Kp." + note, False
    if m["settle"] > 0.6 * duration and m["sat"] < 0.5:
        return clamp(kp * 1.25, KP_MAX), kd, "Works but slow → try a little more Kp." + note, False
    return kp, kd, "Good response ✓  Save these gains." + note, True


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------
class Dial(QWidget):
    """Compass-style dial: needle = current angle, orange tick = target."""

    def __init__(self, size=200):
        super().__init__()
        self.setMinimumSize(size, size)
        self.angle = None
        self.target = None

    def set(self, angle, target=None):
        self.angle, self.target = angle, target
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = min(self.width(), self.height()) - 16
        cx, cy, r = self.width() / 2, self.height() / 2, s / 2
        p.setPen(QPen(QColor("#31445b"), 2))
        p.setBrush(QColor("#0e1a28"))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setPen(QColor("#8294a8"))
        f = QFont("Segoe UI", 9, QFont.Bold)
        p.setFont(f)
        for deg in range(0, 360, 30):
            a = math.radians(deg - 90)
            inner = r * (0.86 if deg % 90 else 0.80)
            p.drawLine(QPointF(cx + inner * math.cos(a), cy + inner * math.sin(a)),
                       QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
        for deg, txt in ((0, "0"), (90, "90"), (180, "180"), (270, "270")):
            a = math.radians(deg - 90)
            p.drawText(QPointF(cx + 0.66 * r * math.cos(a) - 10, cy + 0.66 * r * math.sin(a) + 5), txt)

        def needle(deg, color, width, length):
            a = math.radians(deg - 90)
            p.setPen(QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx, cy), QPointF(cx + length * r * math.cos(a), cy + length * r * math.sin(a)))

        if self.target is not None:
            needle(self.target, "#ffb454", 3, 0.95)
        if self.angle is not None:
            needle(self.angle, "#4fd1ff", 5, 0.8)
        p.setBrush(QColor("#dce7f3"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), 5, 5)


def big_label(text="---", size=26, color="#dce7f3"):
    lb = QLabel(text)
    lb.setStyleSheet(f"font-size:{size}px;font-weight:800;color:{color};")
    return lb


def small(text):
    lb = QLabel(text)
    lb.setStyleSheet("color:#8294a8;")
    lb.setWordWrap(True)
    return lb


def dspin(lo, hi, val, step, dec=2, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setValue(val)
    s.setSuffix(suffix)
    s.setLocale(QLocale.c())
    return s


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SunSeek Ground Station Lite")
        self.resize(1280, 820)

        self.links = {"Bluetooth": BleLink(), "USB Serial": SerialLink(), "Simulator": SimLink()}
        for ln in self.links.values():
            ln.line.connect(self._rx)
            ln.status.connect(self._link_status)
            ln.error.connect(lambda m: self._flash(m, error=True))
            ln.found.connect(self._devices_found)
        self.link = None
        self.connected = False

        self.mode = "MANUAL"
        self.current = None        # current pointing angle, in reference self.cur_ref
        self.cur_ref = None
        self.heading = None        # magnetometer heading
        self.sun_angle = None
        self.target = None
        self.sent_strategy = None
        self.sync_gains = False
        self.health = {}
        self.hist = {"t": [], "angle": [], "target": [], "err": [], "rw": []}
        self.t0 = time.monotonic()

        self.test = None           # running step test
        self.autotune = None       # running auto-tune session
        self.last_result = None
        self.step_dir = 1

        self.settings = self._load_settings()
        self._build()
        self._apply_settings()
        self.plot_timer = QTimer(self)
        self.plot_timer.timeout.connect(self._refresh_plots)
        self.plot_timer.start(200)

    # ---------------- UI ----------------
    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)

        # Connection bar + big STOP
        bar = QHBoxLayout()
        self.link_type = QComboBox()
        self.link_type.addItems(list(self.links))
        self.dev = QComboBox()
        self.dev.setMinimumWidth(280)
        self.btn_scan = QPushButton("SCAN")
        self.btn_conn = QPushButton("CONNECT")
        self.btn_conn.setObjectName("primary")
        self.conn_lbl = big_label("● DISCONNECTED", 15, "#ff6b6b")
        self.mode_lbl = big_label("MODE: ---", 15, "#8294a8")
        self.btn_stop = QPushButton("■  STOP")
        self.btn_stop.setObjectName("stop")
        self.btn_stop.setToolTip("Stops the wheel, returns to MANUAL, cancels tests")
        for w in (QLabel("Link"), self.link_type, self.dev, self.btn_scan, self.btn_conn, self.conn_lbl):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(self.mode_lbl)
        bar.addSpacing(16)
        bar.addWidget(self.btn_stop)
        v.addLayout(bar)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._sensors_tab(), "① Sensors")
        self.tabs.addTab(self._point_tab(), "② Point && Turn")
        self.tabs.addTab(self._tune_tab(), "③ Tune PD")
        self.tabs.addTab(self._terminal_tab(), "Terminal")
        v.addWidget(self.tabs)

        self.status_lbl = QLabel("Ready. Pick a link, SCAN, CONNECT.  (Use 'Simulator' to practise without hardware.)")
        self.statusBar().addWidget(self.status_lbl, 1)

        self.btn_scan.clicked.connect(self._scan)
        self.btn_conn.clicked.connect(self._connect_toggle)
        self.btn_stop.clicked.connect(self.stop_all)
        self.link_type.currentTextChanged.connect(lambda _: self.dev.clear())

    def _sensors_tab(self):
        w = QWidget()
        g = QGridLayout(w)

        def card(title, key):
            box = QGroupBox(title)
            lay = QVBoxLayout(box)
            row = QHBoxLayout()
            live = QPushButton("LIVE  OFF")
            live.setCheckable(True)
            once = QPushButton("READ ONCE")
            row.addWidget(live)
            row.addWidget(once)
            lay.addLayout(row)
            live.toggled.connect(lambda on, k=key, b=live: self._toggle_stream(k, on, b))
            once.clicked.connect(lambda _=False, k=key: self.send({"SUN": "SUN_RAW", "MAG": "MAG_RAW", "GYRO": "GYRO_RAW"}[k]))
            return box, lay, live

        # Sun
        box, lay, self.live_sun = card("SUN SENSOR (LDRs)", "SUN")
        self.sun_big = big_label("--- °", 34, "#ffd166")
        self.sun_l, self.sun_r, self.sun_ndv = QLabel("L ---"), QLabel("R ---"), QLabel("NDV ---")
        self.sun_bar = QSlider(Qt.Horizontal)
        self.sun_bar.setRange(-90, 90)
        self.sun_bar.setEnabled(False)
        lay.addWidget(small("Sun angle"))
        lay.addWidget(self.sun_big)
        lay.addWidget(self.sun_bar)
        for x in (self.sun_l, self.sun_r, self.sun_ndv):
            lay.addWidget(x)
        lay.addWidget(small("Shine a torch: left side → L up & angle +, right side → R up & angle −. "
                            "Stuck at 0 or 4095 = wiring (L=GPIO17, R=GPIO16)."))
        lay.addStretch()
        g.addWidget(box, 0, 0)

        # Mag
        box, lay, self.live_mag = card("MAGNETOMETER (compass)", "MAG")
        self.mag_dial = Dial(190)
        self.mag_big = big_label("--- °", 34, "#4fd1ff")
        self.mag_xyz = QLabel("X ---  Y ---  Z ---  µT")
        lay.addWidget(self.mag_dial, 1)
        lay.addWidget(self.mag_big, 0, Qt.AlignHCenter)
        lay.addWidget(self.mag_xyz)
        lay.addWidget(small("Turn slowly a full circle: heading should sweep 0→360 smoothly. "
                            "Keep away from steel and the motor magnet."))
        g.addWidget(box, 0, 1)

        # Gyro
        box, lay, self.live_gyro = card("GYROSCOPE", "GYRO")
        self.gyro_big = big_label("--- °/s", 34, "#55e38a")
        self.gyro_xyz = QLabel("X ---  Y ---  Z ---")
        lay.addWidget(small("Body rate"))
        lay.addWidget(self.gyro_big)
        lay.addWidget(self.gyro_xyz)
        lay.addWidget(small("Still → near 0.  Spin left → +, spin right → −.  "
                            "Not ~0 when still = put the still values in GYRO_BIAS_*_DPS (Config_Sensor.h)."))
        lay.addStretch()
        g.addWidget(box, 0, 2)

        row = QHBoxLayout()
        b_all = QPushButton("ALL LIVE ON")
        b_off = QPushButton("ALL LIVE OFF")
        b_chk = QPushButton("CHECK SENSORS DETECTED")
        self.rate = QComboBox()
        self.rate.addItems(["1 Hz", "2 Hz", "5 Hz", "10 Hz", "20 Hz"])
        self.rate.setCurrentText("5 Hz")
        self.sensor_health = QLabel("")
        for x in (b_all, b_off, b_chk, QLabel("Live rate"), self.rate, self.sensor_health):
            row.addWidget(x)
        row.addStretch()
        g.addLayout(row, 1, 0, 1, 3)
        g.setRowStretch(0, 1)
        b_all.clicked.connect(lambda: [b.setChecked(True) for b in (self.live_sun, self.live_mag, self.live_gyro)])
        b_off.clicked.connect(lambda: [b.setChecked(False) for b in (self.live_sun, self.live_mag, self.live_gyro)])
        b_chk.clicked.connect(lambda: self.send("SENSOR_STATUS"))
        self.rate.currentTextChanged.connect(lambda t: self.send("TM_RATE," + t.split()[0]))
        return w

    def _control_box(self):
        box = QGroupBox("SETUP")
        g = QGridLayout(box)
        self.ref_mag = QRadioButton("Magnetometer (heading 0–360°)")
        self.ref_sun = QRadioButton("Sun sensor (−90…+90°)")
        self.ref_mag.setChecked(True)
        grp = QButtonGroup(box)
        grp.addButton(self.ref_mag)
        grp.addButton(self.ref_sun)
        self.st_reaction = QRadioButton("Reaction")
        self.st_momentum = QRadioButton("Momentum")
        self.st_reaction.setChecked(True)
        grp2 = QButtonGroup(box)
        grp2.addButton(self.st_reaction)
        grp2.addButton(self.st_momentum)
        g.addWidget(QLabel("Point using"), 0, 0)
        g.addWidget(self.ref_mag, 0, 1)
        g.addWidget(self.ref_sun, 1, 1)
        g.addWidget(QLabel("Wheel"), 2, 0)
        g.addWidget(self.st_reaction, 2, 1)
        g.addWidget(self.st_momentum, 3, 1)
        return box

    def _point_tab(self):
        w = QWidget()
        h = QHBoxLayout(w)
        left = QVBoxLayout()
        left.addWidget(self._control_box())

        nowbox = QGroupBox("NOW")
        ng = QGridLayout(nowbox)
        self.pt_dial = Dial(220)
        self.pt_angle = big_label("--- °", 30, "#4fd1ff")
        self.pt_target = big_label("--- °", 30, "#ffb454")
        self.pt_err = big_label("--- °", 30)
        self.pt_rw = QLabel("Wheel ---")
        ng.addWidget(self.pt_dial, 0, 0, 4, 1)
        ng.addWidget(small("Angle"), 0, 1)
        ng.addWidget(self.pt_angle, 0, 2)
        ng.addWidget(small("Target"), 1, 1)
        ng.addWidget(self.pt_target, 1, 2)
        ng.addWidget(small("Error"), 2, 1)
        ng.addWidget(self.pt_err, 2, 2)
        ng.addWidget(self.pt_rw, 3, 1, 1, 2)
        left.addWidget(nowbox)

        turn = QGroupBox("TURN")
        tg = QGridLayout(turn)
        for i, d in enumerate((-90, -45, -10, 10, 45, 90)):
            b = QPushButton(f"{d:+d}°")
            b.setMinimumHeight(40)
            b.clicked.connect(lambda _=False, d=d: self.turn_by(d))
            tg.addWidget(b, 0, i)
        self.goto = dspin(-90, 359.9, 90, 5, 1, " °")
        bgo = QPushButton("GO TO")
        bgo.setObjectName("primary")
        bhold = QPushButton("HOLD HERE")
        brel = QPushButton("RELEASE (MANUAL)")
        tg.addWidget(QLabel("Heading"), 1, 0)
        tg.addWidget(self.goto, 1, 1, 1, 2)
        tg.addWidget(bgo, 1, 3)
        tg.addWidget(bhold, 1, 4)
        tg.addWidget(brel, 1, 5)
        tg.addWidget(small("Turn buttons are relative to where it points now. Uses the gains from the Tune tab. "
                           "If the error grows instead of shrinking: STOP and flip ADCS_CONTROL_SIGN."), 2, 0, 1, 6)
        bgo.clicked.connect(lambda: self.go_to(self.goto.value()))
        bhold.clicked.connect(lambda: self._ref_ready() and self.go_to(self.current))
        brel.clicked.connect(lambda: self.send("ADCS_MODE,MANUAL"))
        left.addWidget(turn)

        man = QGroupBox("MANUAL WHEEL (Reaction, MANUAL mode only)")
        mg = QHBoxLayout(man)
        self.wheel = QSlider(Qt.Horizontal)
        self.wheel.setRange(-100, 100)
        self.wheel_lbl = QLabel("0 %")
        bspin = QPushButton("SPIN")
        bzero = QPushButton("ZERO")
        mg.addWidget(self.wheel, 1)
        mg.addWidget(self.wheel_lbl)
        mg.addWidget(bspin)
        mg.addWidget(bzero)
        self.wheel.valueChanged.connect(lambda v: self.wheel_lbl.setText(f"{v} %"))
        bspin.clicked.connect(self.spin_wheel)
        bzero.clicked.connect(lambda: (self.wheel.setValue(0), self.send("RW_STOP")))
        left.addWidget(man)
        left.addStretch()
        h.addLayout(left, 0)

        plots = pg.GraphicsLayoutWidget()
        self.p_angle = plots.addPlot(row=0, col=0, title="Angle (blue) & target (orange)")
        self.p_angle.showGrid(x=True, y=True, alpha=0.25)
        self.c_angle = self.p_angle.plot(pen=pg.mkPen("#4fd1ff", width=2))
        self.c_target = self.p_angle.plot(pen=pg.mkPen("#ffb454", width=2, style=Qt.DashLine))
        self.p_err = plots.addPlot(row=1, col=0, title="Error ° (white)   Wheel % (green)")
        self.p_err.showGrid(x=True, y=True, alpha=0.25)
        self.p_err.setXLink(self.p_angle)
        self.c_err = self.p_err.plot(pen=pg.mkPen("#dce7f3", width=2))
        self.c_rw = self.p_err.plot(pen=pg.mkPen("#55e38a", width=1))
        h.addWidget(plots, 1)
        return w

    def _tune_tab(self):
        w = QWidget()
        h = QHBoxLayout(w)
        left = QVBoxLayout()

        gains = QGroupBox("GAINS  —  u = Kp·error − Kd·rate")
        gg = QGridLayout(gains)
        self.kp = dspin(0, KP_MAX, 2.0, 0.1, 3)
        self.kd = dspin(0, KD_MAX, 0.5, 0.05, 3)
        self.bias = QSpinBox()
        self.bias.setRange(0, 100)
        self.bias.setValue(40)
        self.bias.setSuffix(" %")
        bapply = QPushButton("APPLY NOW")
        bapply.setObjectName("primary")
        gg.addWidget(QLabel("Kp  (push toward target)"), 0, 0)
        gg.addWidget(self.kp, 0, 1)
        gg.addWidget(QLabel("Kd  (brake / damping)"), 1, 0)
        gg.addWidget(self.kd, 1, 1)
        gg.addWidget(QLabel("Momentum bias"), 2, 0)
        gg.addWidget(self.bias, 2, 1)
        gg.addWidget(bapply, 3, 0, 1, 2)
        pr = QHBoxLayout()
        for name, kp, kd in (("Gentle", 0.5, 0.0), ("Medium", 1.5, 0.5), ("Firmware default", 2.0, 0.5)):
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, a=kp, d=kd: (self.kp.setValue(a), self.kd.setValue(d)))
            pr.addWidget(b)
        gg.addLayout(pr, 4, 0, 1, 2)
        gg.addWidget(small("PD only (no I term). Gains apply live, even in AUTO. Kp, Kd: 0–20."), 5, 0, 1, 2)
        bapply.clicked.connect(self.apply_gains)
        left.addWidget(gains)

        test = QGroupBox("STEP TEST  —  turn by a fixed amount and measure the response")
        tg = QGridLayout(test)
        self.step = dspin(10, 120, 45, 5, 0, " °")
        self.dur = dspin(5, 60, 15, 1, 0, " s")
        self.rounds = QSpinBox()
        self.rounds.setRange(1, 15)
        self.rounds.setValue(6)
        self.btn_test = QPushButton("RUN ONE STEP TEST")
        self.btn_auto = QPushButton("AUTO-TUNE")
        self.btn_auto.setObjectName("primary")
        self.btn_suggest = QPushButton("APPLY SUGGESTION")
        self.btn_suggest.setEnabled(False)
        self.test_state = QLabel("")
        tg.addWidget(QLabel("Step size"), 0, 0)
        tg.addWidget(self.step, 0, 1)
        tg.addWidget(QLabel("Record for"), 1, 0)
        tg.addWidget(self.dur, 1, 1)
        tg.addWidget(QLabel("Auto-tune max rounds"), 2, 0)
        tg.addWidget(self.rounds, 2, 1)
        tg.addWidget(self.btn_test, 3, 0)
        tg.addWidget(self.btn_auto, 3, 1)
        tg.addWidget(self.test_state, 4, 0, 1, 2)
        tg.addWidget(small("Pick sensor & wheel on the Point tab. Start Gentle. Keep a hand near STOP."), 5, 0, 1, 2)
        self.btn_test.clicked.connect(lambda: self.start_step_test(auto=False))
        self.btn_auto.clicked.connect(self.start_autotune)
        self.btn_suggest.clicked.connect(self.apply_suggestion)
        left.addWidget(test)

        res = QGroupBox("RESULT")
        rg = QGridLayout(res)
        self.r_vals = {}
        for i, (k, name) in enumerate((("overshoot", "Overshoot"), ("rise", "Rise time (to 90 %)"),
                                       ("settle", "Settling time"), ("sse", "Final error"),
                                       ("crossings", "Wobbles"), ("sat", "Wheel at max"))):
            rg.addWidget(QLabel(name), i // 2, (i % 2) * 2)
            self.r_vals[k] = big_label("---", 16)
            rg.addWidget(self.r_vals[k], i // 2, (i % 2) * 2 + 1)
        self.verdict = QLabel("Run a step test to get advice.")
        self.verdict.setWordWrap(True)
        self.verdict.setStyleSheet("font-size:14px;font-weight:700;color:#ffd166;")
        rg.addWidget(self.verdict, 3, 0, 1, 4)
        rg.addWidget(self.btn_suggest, 4, 0, 1, 4)
        left.addWidget(res)

        save = QHBoxLayout()
        bsave = QPushButton("SAVE GAINS INTO FIRMWARE (Config_ADCS.h)")
        bsave.clicked.connect(self.save_to_firmware)
        save.addWidget(bsave)
        left.addLayout(save)
        left.addStretch()
        h.addLayout(left, 0)

        right = QVBoxLayout()
        self.p_step = pg.PlotWidget(title="Step response: error ° vs time (latest bright, previous grey)")
        self.p_step.showGrid(x=True, y=True, alpha=0.25)
        self.p_step.addLine(y=0, pen=pg.mkPen("#8294a8"))
        self.tol_hi = self.p_step.addLine(y=3, pen=pg.mkPen("#55e38a", style=Qt.DotLine))
        self.tol_lo = self.p_step.addLine(y=-3, pen=pg.mkPen("#55e38a", style=Qt.DotLine))
        self.c_step_prev = self.p_step.plot(pen=pg.mkPen("#4a5b6e", width=2))
        self.c_step = self.p_step.plot(pen=pg.mkPen("#4fd1ff", width=3))
        right.addWidget(self.p_step, 2)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["#", "Kp", "Kd", "Overshoot", "Settle", "Final err", "Advice"])
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        right.addWidget(self.table, 1)
        h.addLayout(right, 1)
        return w

    def _terminal_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.cmd = QLineEdit()
        self.cmd.setPlaceholderText("Type a command, e.g. STATUS or RW,30   (↑/↓ = history)")
        self.cmd_hist, self.cmd_idx = [], 0
        bsend = QPushButton("SEND")
        row.addWidget(self.cmd, 1)
        row.addWidget(bsend)
        for c in ("PING", "STATUS", "HELP", "SENSOR_STATUS", "MISSION_STATUS"):
            b = QPushButton(c)
            b.clicked.connect(lambda _=False, c=c: self.send(c))
            row.addWidget(b)
        v.addLayout(row)
        opt = QHBoxLayout()
        self.hide_tm = QCheckBox("Hide TM (telemetry) lines")
        self.hide_tm.setChecked(True)
        bclr = QPushButton("CLEAR")
        opt.addWidget(self.hide_tm)
        opt.addStretch()
        opt.addWidget(bclr)
        v.addLayout(opt)
        self.term = QPlainTextEdit()
        self.term.setReadOnly(True)
        self.term.setMaximumBlockCount(4000)
        self.term.setStyleSheet("font-family:Consolas;font-size:10pt;")
        v.addWidget(self.term)
        bsend.clicked.connect(self._send_typed)
        self.cmd.returnPressed.connect(self._send_typed)
        bclr.clicked.connect(self.term.clear)
        self.cmd.installEventFilter(self)
        return w

    def eventFilter(self, obj, ev):
        if obj is self.cmd and ev.type() == ev.Type.KeyPress and self.cmd_hist:
            if ev.key() == Qt.Key_Up:
                self.cmd_idx = max(0, self.cmd_idx - 1)
                self.cmd.setText(self.cmd_hist[self.cmd_idx])
                return True
            if ev.key() == Qt.Key_Down:
                self.cmd_idx = min(len(self.cmd_hist), self.cmd_idx + 1)
                self.cmd.setText(self.cmd_hist[self.cmd_idx] if self.cmd_idx < len(self.cmd_hist) else "")
                return True
        return super().eventFilter(obj, ev)

    def _send_typed(self):
        c = self.cmd.text().strip()
        if not c:
            return
        self.send(c)
        if not self.cmd_hist or self.cmd_hist[-1] != c:
            self.cmd_hist.append(c)
        self.cmd_idx = len(self.cmd_hist)
        self.cmd.clear()

    # ---------------- link ----------------
    def _scan(self):
        self.dev.clear()
        self.btn_scan.setEnabled(False)
        self._flash("Scanning…")
        self.links[self.link_type.currentText()].scan()

    def _devices_found(self, devs):
        self.btn_scan.setEnabled(True)
        self.dev.clear()
        for name, addr in devs:
            self.dev.addItem(f"{name}   [{addr}]" if addr != name else name, addr)
        last = self.settings.get("device")
        i = self.dev.findData(last)
        if i >= 0:
            self.dev.setCurrentIndex(i)
        self._flash(f"Found {len(devs)} device(s)" if devs else "Nothing found — is the spacecraft on?",
                    error=not devs)

    def _connect_toggle(self):
        if self.connected:
            self.stop_all()
            self.link.close()
            return
        if self.dev.currentIndex() < 0:
            self._flash("Press SCAN and pick a device first", error=True)
            return
        self.link = self.links[self.link_type.currentText()]
        self.conn_lbl.setText("◐ CONNECTING…")
        self.conn_lbl.setStyleSheet("font-size:15px;font-weight:800;color:#f2c94c;")
        self.link.open(self.dev.currentData(), self.dev.currentText())

    def _link_status(self, ok, name):
        if self.sender() is not self.link:
            return
        if ok == self.connected and not ok:
            self.conn_lbl.setText("● DISCONNECTED")
            self.conn_lbl.setStyleSheet("font-size:15px;font-weight:800;color:#ff6b6b;")
            return
        self.connected = ok
        if ok:
            self.conn_lbl.setText("● CONNECTED  " + name.split("[")[0].strip())
            self.conn_lbl.setStyleSheet("font-size:15px;font-weight:800;color:#55e38a;")
            self.btn_conn.setText("DISCONNECT")
            self.settings["device"] = self.dev.currentData()
            self.settings["link"] = self.link_type.currentText()
            self.sent_strategy = None
            self.sync_gains = True
            # Quiet the downlink, then stream only ADCS (so we always know where it points).
            for i, c in enumerate(("TM_STREAM,QUIET", "TM_STREAM,ADCS,ON", "STATUS")):
                QTimer.singleShot(200 + 150 * i, lambda c=c: self.send(c))
            self._flash("Connected")
        else:
            self.conn_lbl.setText("● DISCONNECTED")
            self.conn_lbl.setStyleSheet("font-size:15px;font-weight:800;color:#ff6b6b;")
            self.btn_conn.setText("CONNECT")
            self.cancel_tests("link lost")
            for b in (self.live_sun, self.live_mag, self.live_gyro):
                b.blockSignals(True)
                b.setChecked(False)
                b.setText("LIVE  OFF")
                b.blockSignals(False)
            self._flash("Disconnected", error=True)

    def send(self, cmd):
        cmd = cmd.strip()
        if not cmd:
            return
        self._term("TX > " + cmd, "#4fd1ff")
        if not self.connected or self.link is None:
            self._flash("Not connected", error=True)
            return
        self.link.send(cmd)

    def send_many(self, cmds, gap_ms=60):
        for i, c in enumerate(cmds):
            QTimer.singleShot(i * gap_ms, lambda c=c: self.send(c))

    # ---------------- receive ----------------
    def _rx(self, line):
        if self.sender() is not self.link:
            return
        if not (line.startswith("TM,") and self.hide_tm.isChecked()):
            color = "#ff6b6b" if line.startswith("ERR") else "#55e38a" if line.startswith(("ACK", "PONG")) else "#dce7f3"
            self._term("RX < " + line, color)
        if line.startswith("ERR,"):
            self._flash(self._explain_err(line), error=True)
        elif line.startswith("ACK,"):
            self._flash(line)
        if not line.startswith("TM,"):
            return
        d = parse_kv(line)
        f = lambda k: float(d[k])
        try:
            if "ADCS_MODE" in d:
                self.mode = d["ADCS_MODE"]
                c = "#55e38a" if self.mode == "AUTO" else "#8294a8"
                self.mode_lbl.setText("MODE: " + self.mode)
                self.mode_lbl.setStyleSheet(f"font-size:15px;font-weight:800;color:{c};")
            if "ADCS_STRATEGY" in d:
                self.sent_strategy = d["ADCS_STRATEGY"]
            if "KP" in d and "KD" in d and self.sync_gains:
                self.sync_gains = False
                self.kp.setValue(f("KP"))
                self.kd.setValue(f("KD"))
                if "MOMENTUM_BIAS" in d:
                    self.bias.setValue(int(f("MOMENTUM_BIAS")))
            if "POINTING_ERROR" in d:
                self._adcs_sample(d)
            if "SUN_ANGLE" in d:
                self.sun_angle = f("SUN_ANGLE")
                self.sun_big.setText(f"{self.sun_angle:+.1f} °")
                self.sun_bar.setValue(int(max(-90, min(90, self.sun_angle))))
                self.sun_l.setText(f"Left  {d.get('SUN_L', '---')}")
                self.sun_r.setText(f"Right  {d.get('SUN_R', '---')}")
                self.sun_ndv.setText(f"NDV  {d.get('SUN_NDV', '---')}")
            if "MAG_HEADING" in d:
                self.heading = f("MAG_HEADING")
                self.mag_big.setText(f"{self.heading:.1f} °")
                self.mag_dial.set(self.heading)
                self.mag_xyz.setText(f"X {d.get('MAG_X')}   Y {d.get('MAG_Y')}   Z {d.get('MAG_Z')}  µT")
            # In the ADCS packet GYRO_Z is the body rate; elsewhere it is the raw Z axis.
            if "POINTING_ERROR" not in d and ("BODY_RATE" in d or "GYRO_Z" in d):
                rate = f("BODY_RATE") if "BODY_RATE" in d else f("GYRO_Z")
                self.gyro_big.setText(f"{rate:+.2f} °/s")
                if "GYRO_X" in d:
                    self.gyro_xyz.setText(f"X {d['GYRO_X']}   Y {d.get('GYRO_Y')}   Z {d.get('GYRO_Z')}")
            for k, v in d.items():
                if k.startswith("SENSOR_"):   # TM,SENSOR_GYRO,READY
                    self.health[k[7:]] = v
                    ok = all(x in ("READY", "DETECTED") for x in self.health.values())
                    self.sensor_health.setText("  ".join(f"{a}: {b}" for a, b in self.health.items()))
                    self.sensor_health.setStyleSheet(f"color:{'#55e38a' if ok else '#ff6b6b'};font-weight:700;")
        except (ValueError, KeyError):
            pass

    def _adcs_sample(self, d):
        now = time.monotonic()
        err = float(d["POINTING_ERROR"])
        tgt = float(d["TARGET"])
        rw = int(float(d.get("RW_CMD", 0)))
        ref = d.get("ADCS_REFERENCE", "MAG")
        ang = wrap360(tgt - err) if ref == "MAG" else tgt - err
        self.current, self.target, self.cur_ref = ang, tgt, ref
        h = self.hist
        for k, val in (("t", now - self.t0), ("angle", ang), ("target", tgt), ("err", err), ("rw", rw)):
            h[k].append(val)
        if len(h["t"]) > 2400:
            for k in h:
                del h[k][:400]
        self.pt_angle.setText(f"{ang:.1f} °")
        self.pt_target.setText(f"{tgt:.1f} °")
        c = "#55e38a" if abs(err) <= DEADBAND + 1 else "#ffd166" if abs(err) < 15 else "#ff6b6b"
        self.pt_err.setText(f"{err:+.1f} °")
        self.pt_err.setStyleSheet(f"font-size:30px;font-weight:800;color:{c};")
        self.pt_rw.setText(f"Wheel {rw:+d} %    Rate {float(d.get('GYRO_Z', 0)):+.1f} °/s")
        self.pt_dial.set(ang, tgt)
        if self.test and self.test["recording"]:
            self.test["samples"].append((now, err, rw))

    def _explain_err(self, line):
        tips = {
            "ADCS_SENSOR_NOT_READY": "AUTO refused: sensors not read OK (IMU detected? Sun sensor dark?)",
            "TARGET_OUT_OF_RANGE_OR_AUTO": "Target refused: out of range (Sun −90…90, Mag 0…359.9)",
            "MANUAL_RW_COMMAND_REQUIRES_MANUAL_MODE": "Wheel command refused: switch to MANUAL first",
            "RW_REQUIRES_REACTION_STRATEGY": "Manual spin needs Reaction wheel strategy",
            "ADCS_TUNE_OUT_OF_RANGE": "Gains refused: Kp/Kd must be 0–20, bias 0–100",
        }
        key = line[4:]
        return line + ("   → " + tips[key] if key in tips else "")

    # ---------------- commands ----------------
    def _toggle_stream(self, key, on, btn):
        btn.setText("LIVE  ON" if on else "LIVE  OFF")
        btn.setStyleSheet("background:#1d4d33;" if on else "")
        self.send(f"TM_STREAM,{key},{'ON' if on else 'OFF'}")

    def ref(self):
        return "MAG" if self.ref_mag.isChecked() else "SUN"

    def strategy(self):
        return "MOMENTUM" if self.st_momentum.isChecked() else "REACTION"

    def clamp_target(self, t):
        if self.ref() == "MAG":
            t = wrap360(t)
            return 0.0 if t >= 359.95 else t
        return max(-90.0, min(90.0, t))

    def tune_cmd(self):
        return f"ADCS_TUNE,{self.kp.value():.3f},{self.kd.value():.3f},{self.bias.value()}"

    def go_to(self, t):
        if not self.connected:
            self._flash("Not connected", error=True)
            return
        t = self.clamp_target(t)
        cmds = ["ADCS_MODE,MANUAL", f"ADCS_REFERENCE,{self.ref()}"]
        if self.sent_strategy != self.strategy():   # changing strategy stops the wheel, so only when needed
            cmds.append(f"ADCS_STRATEGY,{self.strategy()}")
            self.sent_strategy = self.strategy()
        cmds += [self.tune_cmd(), f"SET_TARGET,{t:.1f}", "TM_STREAM,ADCS,ON", "ADCS_MODE,AUTO"]
        self.send_many(cmds)
        self.goto.setValue(t)
        self._flash(f"Going to {t:.1f}°")

    def _ref_ready(self):
        """True when telemetry is already in the selected reference; otherwise switch and wait."""
        if self.current is not None and self.cur_ref == self.ref():
            return True
        if self.connected:
            self.send_many(["ADCS_MODE,MANUAL", f"ADCS_REFERENCE,{self.ref()}", "TM_STREAM,ADCS,ON"])
        self._flash("Switching to " + ("magnetometer" if self.ref() == "MAG" else "sun sensor")
                    + " — press again in a second", error=True)
        return False

    def turn_by(self, d):
        if not self._ref_ready():
            return
        if self.current is None:
            self._flash("Don't know where it points yet — wait for telemetry", error=True)
            return
        self.go_to(self.current + d)

    def spin_wheel(self):
        cmds = []
        if self.mode == "AUTO":
            cmds.append("ADCS_MODE,MANUAL")
        if self.sent_strategy != "REACTION":
            cmds.append("ADCS_STRATEGY,REACTION")
            self.sent_strategy = "REACTION"
            self.st_reaction.setChecked(True)
        cmds.append(f"RW,{self.wheel.value()}")
        self.send_many(cmds)

    def apply_gains(self):
        self.send(self.tune_cmd())

    def stop_all(self):
        self.cancel_tests("STOP pressed")
        self.wheel.setValue(0)
        if self.connected:
            self.send("STOP")
            QTimer.singleShot(150, lambda: self.send("TM_STREAM,ADCS,ON"))
        for b in (self.live_sun, self.live_mag, self.live_gyro):
            b.blockSignals(True)
            b.setChecked(False)
            b.setText("LIVE  OFF")
            b.setStyleSheet("")
            b.blockSignals(False)

    # ---------------- tuning ----------------
    def start_step_test(self, auto=False):
        if not self.connected:
            self._flash("Not connected", error=True)
            return
        if self.test or not self._ref_ready():
            return
        if not auto:
            self.autotune = None
        start = self.current
        step = self.step.value() * self.step_dir
        if self.ref() == "SUN" and not -85 <= start + step <= 85:
            step = -step
            self.step_dir = -self.step_dir
        self.test = {"samples": [], "recording": False, "kp": self.kp.value(), "kd": self.kd.value(),
                     "duration": self.dur.value()}
        self.go_to(start + step)
        self.step_dir = -self.step_dir     # next test goes back
        # Start recording once the AUTO command has gone out.
        QTimer.singleShot(500, self._begin_recording)
        QTimer.singleShot(500 + int(self.dur.value() * 1000), self._finish_test)
        self.test_state.setText(f"● Recording {self.dur.value():.0f} s …")
        self.btn_test.setEnabled(False)
        self.btn_suggest.setEnabled(False)

    def _begin_recording(self):
        if self.test:
            self.test["recording"] = True

    def _finish_test(self):
        if not self.test:
            return
        t, self.test = self.test, None
        self.btn_test.setEnabled(True)
        m = analyze_step(t["samples"])
        nkp, nkd, msg, good = suggest_gains(m, t["kp"], t["kd"], t["duration"])
        self.last_result = (m, nkp, nkd, good)
        self._show_result(t, m, nkp, nkd, msg, good)
        if self.autotune is not None:
            a = self.autotune
            a["round"] += 1
            if good or m["diverged"] or not m["ok"] or a["round"] >= a["max"]:
                self.autotune = None
                self.btn_auto.setText("AUTO-TUNE")
                end = "done ✓" if good else "stopped"
                self.test_state.setText(f"Auto-tune {end} after {a['round']} round(s). Kp={self.kp.value():.3f} Kd={self.kd.value():.3f}")
                if m["diverged"]:
                    self.send("STOP")
            else:
                self.kp.setValue(nkp)
                self.kd.setValue(nkd)
                self.test_state.setText(f"Auto-tune round {a['round']+1}/{a['max']}: Kp={nkp:.3f} Kd={nkd:.3f}")
                QTimer.singleShot(1500, lambda: self.autotune is not None and self.start_step_test(auto=True))
        else:
            self.test_state.setText("Test finished.")
            if m["diverged"]:
                self.send("STOP")

    def _show_result(self, t, m, nkp, nkd, msg, good):
        fmt = lambda v, f: "---" if v is None else f.format(v)
        self.r_vals["overshoot"].setText(fmt(m["overshoot"], "{:.0f} %"))
        self.r_vals["rise"].setText(fmt(m["rise"], "{:.1f} s"))
        self.r_vals["settle"].setText(fmt(m["settle"], "{:.1f} s") if m["ok"] else "---")
        if m["ok"] and m["settle"] is None:
            self.r_vals["settle"].setText("not settled")
        self.r_vals["sse"].setText(fmt(m["sse"], "{:+.1f} °"))
        self.r_vals["crossings"].setText(str(m["crossings"]) if m["ok"] else "---")
        self.r_vals["sat"].setText(f"{m['sat']*100:.0f} %" if m["ok"] else "---")
        change = "" if good or (nkp == t["kp"] and nkd == t["kd"]) else f"   Suggest: Kp {t['kp']:.3f}→{nkp:.3f}, Kd {t['kd']:.3f}→{nkd:.3f}"
        self.verdict.setText(msg + change)
        self.verdict.setStyleSheet(f"font-size:14px;font-weight:700;color:{'#55e38a' if good else '#ff6b6b' if m['diverged'] else '#ffd166'};")
        self.btn_suggest.setEnabled(bool(change))
        # plot
        s = t["samples"]
        if s:
            self.c_step_prev.setData(*self.c_step.getData()) if self.c_step.getData()[0] is not None else None
            t0 = s[0][0]
            self.c_step.setData([x[0] - t0 for x in s], [x[1] for x in s])
            tol = m.get("tol", DEADBAND + 1)
            self.tol_hi.setValue(tol)
            self.tol_lo.setValue(-tol)
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, val in enumerate((r + 1, f"{t['kp']:.3f}", f"{t['kd']:.3f}", fmt(m["overshoot"], "{:.0f} %"),
                                 fmt(m["settle"], "{:.1f} s"), fmt(m["sse"], "{:+.1f}°"), msg)):
            self.table.setItem(r, c, QTableWidgetItem(str(val)))
        self.table.scrollToBottom()

    def apply_suggestion(self):
        if self.last_result:
            _, nkp, nkd, _ = self.last_result
            self.kp.setValue(nkp)
            self.kd.setValue(nkd)
            self.apply_gains()
            self.btn_suggest.setEnabled(False)

    def start_autotune(self):
        if self.autotune is not None:
            self.cancel_tests("auto-tune cancelled")
            return
        if not self.connected or self.current is None:
            self._flash("Connect first and wait for ADCS telemetry", error=True)
            return
        self.autotune = {"round": 0, "max": self.rounds.value()}
        self.btn_auto.setText("CANCEL AUTO-TUNE")
        self.test_state.setText(f"Auto-tune round 1/{self.rounds.value()}")
        self.start_step_test(auto=True)

    def cancel_tests(self, why):
        if self.test or self.autotune is not None:
            self.test_state.setText("Cancelled: " + why)
        self.test = None
        self.autotune = None
        self.btn_auto.setText("AUTO-TUNE")
        self.btn_test.setEnabled(True)

    def save_to_firmware(self):
        path = FIRMWARE_CONFIG_ADCS
        if not path.exists():
            p, _ = QFileDialog.getOpenFileName(self, "Find Config_ADCS.h", str(Path.home()), "Config_ADCS.h")
            if not p:
                return
            path = Path(p)
        kp, kd = self.kp.value(), self.kd.value()
        if QMessageBox.question(self, "Save gains",
                                f"Write Kp = {kp:.3f} and Kd = {kd:.3f} as the power-on defaults in\n{path}?\n\n"
                                "Then re-upload the firmware in Arduino IDE.") != QMessageBox.Yes:
            return
        txt = path.read_text(encoding="utf-8")
        txt = re.sub(r"(#define\s+ADCS_DEFAULT_KP\s+)[-\d.]+f?", lambda mm: f"{mm.group(1)}{kp:.3f}f", txt)
        txt = re.sub(r"(#define\s+ADCS_DEFAULT_KD\s+)[-\d.]+f?", lambda mm: f"{mm.group(1)}{kd:.3f}f", txt)
        path.write_text(txt, encoding="utf-8")
        self._flash(f"Saved to {path.name}. Re-upload the firmware to make them the default.")

    # ---------------- misc ----------------
    def _refresh_plots(self):
        h = self.hist
        if not h["t"]:
            return
        cut = h["t"][-1] - 60
        i = next((k for k, x in enumerate(h["t"]) if x >= cut), 0)
        t = h["t"][i:]
        self.c_angle.setData(t, h["angle"][i:])
        self.c_target.setData(t, h["target"][i:])
        self.c_err.setData(t, h["err"][i:])
        self.c_rw.setData(t, h["rw"][i:])

    def _term(self, text, color):
        self.term.appendHtml(f'<span style="color:#5d6f82">{time.strftime("%H:%M:%S")}</span> '
                             f'<span style="color:{color}">{text.replace("<", "&lt;")}</span>')

    def _flash(self, msg, error=False):
        self.status_lbl.setText(msg)
        self.status_lbl.setStyleSheet(f"color:{'#ff6b6b' if error else '#dce7f3'};font-weight:600;")

    def _load_settings(self):
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _apply_settings(self):
        s = self.settings
        if s.get("link") in self.links:
            self.link_type.setCurrentText(s["link"])
        self.kp.setValue(s.get("kp", 2.0))
        self.kd.setValue(s.get("kd", 0.5))
        self.bias.setValue(s.get("bias", 40))
        (self.ref_sun if s.get("ref") == "SUN" else self.ref_mag).setChecked(True)
        (self.st_momentum if s.get("strategy") == "MOMENTUM" else self.st_reaction).setChecked(True)
        self.step.setValue(s.get("step", 45))

    def closeEvent(self, ev):
        self.settings.update(kp=self.kp.value(), kd=self.kd.value(), bias=self.bias.value(),
                             ref=self.ref(), strategy=self.strategy(), step=self.step.value())
        try:
            SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except Exception:
            pass
        if self.connected and self.link:
            self.link.send("STOP")
            self.link.close()
        ev.accept()


STYLE = """
QWidget{background:#0b1420;color:#dce7f3;font-family:'Segoe UI';font-size:10pt}
QGroupBox{border:1px solid #27445c;border-radius:8px;margin-top:14px;padding:8px;font-weight:700;color:#73d9ff}
QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px}
QPushButton{background:#16324a;border:1px solid #2c5272;border-radius:6px;padding:7px 12px;font-weight:700}
QPushButton:hover{background:#1e4363}
QPushButton:disabled{color:#5d6f82;background:#101d2b}
QPushButton:checked{background:#1d4d33;border-color:#55e38a}
QPushButton#primary{background:#0f5c8c;border-color:#4fd1ff}
QPushButton#stop{background:#b3261e;border:2px solid #ff6b6b;font-size:16px;padding:10px 26px}
QPushButton#stop:hover{background:#d9342b}
QComboBox,QLineEdit,QSpinBox,QDoubleSpinBox,QPlainTextEdit,QTableWidget{background:#0e1a28;border:1px solid #31445b;border-radius:4px;padding:4px}
QTabBar::tab{background:#101d2b;padding:9px 22px;font-weight:700;border-top-left-radius:6px;border-top-right-radius:6px}
QTabBar::tab:selected{background:#16324a;color:#4fd1ff}
QHeaderView::section{background:#16324a;padding:4px;border:none}
QRadioButton::indicator,QCheckBox::indicator{width:14px;height:14px;border:2px solid #4a6a88;border-radius:8px;background:#0e1a28}
QCheckBox::indicator{border-radius:3px}
QRadioButton::indicator:checked,QCheckBox::indicator:checked{background:#4fd1ff;border-color:#4fd1ff}
"""


def main():
    QLocale.setDefault(QLocale.c())   # keep 1.5 as "1.5" on Thai/other locales
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    pg.setConfigOptions(antialias=True, background="#07131f", foreground="#8294a8")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
