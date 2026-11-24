"""Robot state over DDS (unitree_sdk2py).

Topics are found through DDS discovery (builtin publication topic), so the
lowstate message family (unitree_go vs unitree_hg) and the battery / sport
topics are chosen by the type actually published on the network instead of
being hard coded per robot.
"""
import math
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .models import GO, HG, MODELS, REMOTE_BUTTONS, RobotModel, guess_model

T_GO_LOW = "unitree_go::msg::dds_::LowState_"
T_HG_LOW = "unitree_hg::msg::dds_::LowState_"
T_GO_SPORT = "unitree_go::msg::dds_::SportModeState_"
T_HG_BMS = "unitree_hg::msg::dds_::BmsState_"
T_HG_MAINBOARD = "unitree_hg::msg::dds_::MainBoardState_"

# ----------------------------------------------------------------------------
# Normalized state
# ----------------------------------------------------------------------------


@dataclass
class Motor:
    index: int
    name: str
    active: bool = False
    mode: int = 0
    q: float = 0.0
    dq: float = 0.0
    tau: float = 0.0
    temp: float = 0.0          # winding / main temperature (C)
    temp2: Optional[float] = None  # hg: second sensor
    vol: Optional[float] = None    # hg: motor bus voltage
    lost: int = 0              # go: lost packet counter
    error: int = 0             # hg: motorstate error bits


@dataclass
class Imu:
    quat: List[float] = field(default_factory=lambda: [1.0, 0.0, 0.0, 0.0])
    gyro: List[float] = field(default_factory=lambda: [0.0] * 3)
    acc: List[float] = field(default_factory=lambda: [0.0] * 3)
    rpy: List[float] = field(default_factory=lambda: [0.0] * 3)
    temp: float = 0.0


@dataclass
class Battery:
    valid: bool = False
    soc: float = 0.0           # %
    voltage: float = 0.0       # V
    current: float = 0.0       # A, negative = discharging
    cycle: int = 0
    soh: Optional[int] = None
    status: int = 0
    temps: List[float] = field(default_factory=list)
    cells: List[float] = field(default_factory=list)  # V
    version: str = ""
    source: str = ""

    @property
    def power(self) -> float:
        return self.voltage * self.current


@dataclass
class Sport:
    valid: bool = False
    mode: int = 0
    gait: int = 0
    error_code: int = 0
    body_height: float = 0.0
    position: List[float] = field(default_factory=lambda: [0.0] * 3)
    velocity: List[float] = field(default_factory=lambda: [0.0] * 3)
    yaw_speed: float = 0.0
    source: str = ""


@dataclass
class Remote:
    valid: bool = False
    lx: float = 0.0
    ly: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    buttons: List[str] = field(default_factory=list)


@dataclass
class RobotState:
    status: str = "disabled"     # disabled | discovering | waiting | online | stale | demo
    model: Optional[RobotModel] = None
    family: str = ""
    lowstate_topic: str = ""
    tick: int = 0
    age: float = float("inf")    # seconds since last lowstate
    rates: Dict[str, float] = field(default_factory=dict)
    motors: List[Motor] = field(default_factory=list)
    imu: Imu = field(default_factory=Imu)
    battery: Battery = field(default_factory=Battery)
    sport: Sport = field(default_factory=Sport)
    remote: Remote = field(default_factory=Remote)
    foot_force: List[float] = field(default_factory=list)
    board: Dict[str, object] = field(default_factory=dict)  # misc board level values
    topics: Dict[str, str] = field(default_factory=dict)    # discovered topic -> type
    version: str = ""
    error: str = ""

    @property
    def online(self) -> bool:
        return self.status in ("online", "demo")

    @property
    def active_motors(self) -> List[Motor]:
        return [m for m in self.motors if m.active]


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _u8list(x) -> List[int]:
    return list(bytes(x)) if isinstance(x, (bytes, bytearray)) else [int(v) for v in x]


def parse_remote(raw) -> Remote:
    try:
        data = bytes(_u8list(raw))
        keys, lx, rx, ry, _l2, ly = struct.unpack_from("<2xH5f", data)
    except Exception:
        return Remote()
    vals = [lx, rx, ry, ly]
    if not all(math.isfinite(v) and abs(v) <= 1.5 for v in vals):
        return Remote()
    pressed = [n for i, n in enumerate(REMOTE_BUTTONS) if keys & (1 << i)]
    return Remote(True, lx, ly, rx, ry, pressed)


class _Counter:
    __slots__ = ("count", "last", "rate", "reader", "_t0", "_c0")

    def __init__(self):
        self.count = 0
        self.last = None
        self.rate = 0.0
        self.reader = None
        self._t0 = time.monotonic()
        self._c0 = 0

    def update_rate(self, now):
        dt = now - self._t0
        if dt >= 1.0:
            self.rate = (self.count - self._c0) / dt
            self._t0, self._c0 = now, self.count


# ----------------------------------------------------------------------------
# DDS link
# ----------------------------------------------------------------------------

class RobotLink:
    """Subscribes to the robot topics and produces RobotState snapshots."""

    def __init__(self, interface=None, domain=0, robot="auto", lowstate_topic=None,
                 discovery_timeout=3.0):
        self.interface = interface
        self.domain = domain
        self.robot = robot
        self.lowstate_topic = lowstate_topic
        self.discovery_timeout = discovery_timeout
        self._topics = {}          # name -> type name
        self._latest = {}          # role -> _Counter (latest sample in .last)
        self._subs = []
        self._lock = threading.Lock()
        self._active = []          # sticky "this slot carries data"
        self._model = MODELS.get(robot) if robot != "auto" else None
        self._family = self._model.family if self._model else ""
        self._status = "discovering"
        self._error = ""
        self._last_rx = None
        self._thread = None
        self._running = False
        self._dp = None

    # -- lifecycle -------------------------------------------------------
    def start(self):
        try:
            from unitree_sdk2py.core.channel import ChannelFactoryInitialize
            ChannelFactoryInitialize(self.domain, self.interface)  # configures the NIC
            from cyclonedds.domain import DomainParticipant
            self._dp = DomainParticipant(self.domain)
        except Exception as e:  # SDK / cyclonedds missing or bad interface
            self._status = "error"
            self._error = "DDS init failed: {}".format(e)
            return
        self._running = True
        self._thread = threading.Thread(target=self._discovery_loop, name="utop-discovery",
                                        daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    # -- discovery -------------------------------------------------------
    def _discovery_loop(self):
        reader = None
        try:
            from cyclonedds.builtin import BuiltinDataReader, BuiltinTopicDcpsPublication
            reader = BuiltinDataReader(self._dp, BuiltinTopicDcpsPublication)
        except Exception as e:
            self._error = "discovery unavailable ({}), using default topics".format(e)
        t0 = time.monotonic()
        subscribed = False
        while self._running:
            if reader is not None:
                try:
                    new = {}
                    for s in reader.take(N=256):
                        name = getattr(s, "topic_name", None)
                        if name:
                            new[name] = getattr(s, "type_name", "?")
                    if new:
                        with self._lock:
                            self._topics.update(new)
                except Exception:
                    pass
            if not subscribed:
                ready = self._family or self._lowstate_family_from_topics()
                timeout = time.monotonic() - t0 > self.discovery_timeout
                if ready or timeout or reader is None:
                    self._subscribe()
                    subscribed = True
            elif reader is not None:
                self._subscribe_extra()  # late joiners (e.g. sport mode switched on)
            time.sleep(0.5)

    def _lowstate_family_from_topics(self):
        topic = self.lowstate_topic or "rt/lowstate"
        t = self._topics.get(topic, "")
        if t == T_GO_LOW:
            return GO
        if t == T_HG_LOW:
            return HG
        return ""

    def _subscribe(self):
        fam = self._family or self._lowstate_family_from_topics() or GO
        self._family = fam
        if fam == GO:
            from unitree_sdk2py.idl.unitree_go.msg.dds_ import LowState_
        else:
            from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
        topic = self.lowstate_topic or "rt/lowstate"
        self._sub(topic, LowState_, "low")
        self._status = "waiting"
        if not self._topics:  # no discovery: subscribe to well known names
            if fam == GO:
                from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_
                self._sub("rt/sportmodestate", SportModeState_, "sport")
            else:
                from unitree_sdk2py.idl.unitree_hg.msg.dds_ import BmsState_
                self._sub("rt/lf/bmsstate", BmsState_, "bms")
        self._subscribe_extra()

    def _subscribe_extra(self):
        roles = {T_GO_SPORT: "sport", T_HG_BMS: "bms", T_HG_MAINBOARD: "mainboard"}
        for role_type, role in roles.items():
            if role in self._latest:
                continue
            cands = sorted(n for n, t in self._topics.items() if t == role_type)
            if not cands:
                continue
            # prefer the full-rate topic (rt/x) over the low-frequency mirror (rt/lf/x)
            cands.sort(key=lambda n: "/lf/" in n)
            try:
                if role == "sport":
                    from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_ as T
                elif role == "bms":
                    from unitree_sdk2py.idl.unitree_hg.msg.dds_ import BmsState_ as T
                else:
                    from unitree_sdk2py.idl.unitree_hg.msg.dds_ import MainBoardState_ as T
            except ImportError:
                continue
            self._sub(cands[0], T, role)

    def _sub(self, topic, typ, role):
        """KeepLast(1) reader: the listener only counts arrivals (for the Hz display);
        the newest sample is deserialized when a snapshot is taken. Taking every
        500 Hz lowstate in Python would cost most of a CPU core."""
        from cyclonedds.core import Listener, Policy, Qos
        from cyclonedds.sub import DataReader
        from cyclonedds.topic import Topic
        counter = _Counter()

        def on_data(_reader, c=counter):
            c.count += 1

        try:
            reader = DataReader(self._dp, Topic(self._dp, topic, typ), qos=Qos(Policy.History.KeepLast(1)),
                                listener=Listener(on_data_available=on_data))
        except Exception as e:
            self._error = "subscribe {} failed: {}".format(topic, e)
            return
        counter.reader = reader
        self._subs.append(reader)
        with self._lock:
            self._latest[role] = counter
            self._latest[role + ":topic"] = topic

    # -- snapshot --------------------------------------------------------
    def snapshot(self) -> RobotState:
        with self._lock:
            topics = dict(self._topics)
            latest = list(self._latest.items())
        st = RobotState(status=self._status, family=self._family, error=self._error,
                        topics=topics)
        if self._status == "error":
            return st
        now = time.monotonic()
        for role, c in latest:
            if isinstance(c, _Counter):
                c.update_rate(now)
                try:
                    got = c.reader.take(N=1)
                    if got:
                        c.last = got[-1]
                except Exception:
                    pass
                if c.count:
                    st.rates[self._latest.get(role + ":topic", role)] = c.rate
        low_c = self._latest.get("low")
        if low_c is None or low_c.last is None:
            st.model = self._model
            return st
        st.lowstate_topic = self._latest.get("low:topic", "")
        if low_c.count != getattr(self, "_last_count", -1):
            self._last_count = low_c.count
            self._last_rx = now
        st.age = now - self._last_rx if self._last_rx else float("inf")
        st.status = "online" if st.age < 1.0 else "stale"
        self._status = st.status
        try:
            if self._family == GO:
                self._fill_go(st, low_c.last)
            else:
                self._fill_hg(st, low_c.last)
            sp = self._latest.get("sport")
            if sp is not None and sp.last is not None:
                self._fill_sport(st, sp.last, self._latest.get("sport:topic", ""))
        except Exception as e:  # never let a malformed sample kill the UI
            st.error = "parse error: {}".format(e)
        return st

    def _model_for(self, motor_states):
        n = len(motor_states)
        if len(self._active) != n:
            self._active = [False] * n
        for i, m in enumerate(motor_states):
            if not self._active[i]:
                t = m.temperature
                t = t[0] if not isinstance(t, (int, float)) else t
                if m.mode or t or m.q or m.dq or m.tau_est:
                    self._active[i] = True
        if self._model is None or self.robot == "auto":
            self._model = guess_model(self._family, self._active)
        return self._model

    def _motors(self, st, motor_states, conv):
        model = self._model_for(motor_states)
        st.model = model
        for i, ms in enumerate(motor_states):
            name = model.joints[i] if i < len(model.joints) else None
            if name is None and not self._active[i]:
                continue
            m = Motor(i, name or "motor{}".format(i), self._active[i], ms.mode,
                      ms.q, ms.dq, ms.tau_est)
            conv(m, ms)
            st.motors.append(m)

    @staticmethod
    def _imu(msg) -> Imu:
        i = msg.imu_state
        return Imu(list(i.quaternion), list(i.gyroscope), list(i.accelerometer), list(i.rpy),
                   float(i.temperature))

    def _fill_go(self, st, msg):
        st.tick = msg.tick
        st.version = ".".join(str(v) for v in msg.version)

        def conv(m, ms):
            m.temp = float(ms.temperature)
            m.lost = ms.lost

        self._motors(st, msg.motor_state, conv)
        st.imu = self._imu(msg)
        b = msg.bms_state
        cells = [c / 1000.0 for c in b.cell_vol if c]
        volt = float(msg.power_v) if msg.power_v > 1 else sum(cells)
        st.battery = Battery(
            valid=bool(b.soc or cells), soc=float(b.soc), voltage=volt,
            current=b.current / 1000.0, cycle=b.cycle, status=b.status,
            temps=[float(t) for t in _u8list(b.bq_ntc) + _u8list(b.mcu_ntc)],
            cells=cells, version="{}.{}".format(b.version_high, b.version_low),
            source=self._latest.get("low:topic", "") + " bms_state")
        st.foot_force = list(msg.foot_force)
        st.remote = parse_remote(msg.wireless_remote)
        st.board = {
            "bus voltage": "{:.2f} V".format(msg.power_v),
            "bus current": "{:.2f} A".format(msg.power_a),
            "ntc1": "{} C".format(msg.temperature_ntc1),
            "ntc2": "{} C".format(msg.temperature_ntc2),
            "fan": ", ".join(str(f) for f in msg.fan_frequency),
            "bit_flag": "0x{:02x}".format(msg.bit_flag),
            "bandwidth": msg.bandwidth,
        }

    def _fill_hg(self, st, msg):
        st.tick = msg.tick
        st.version = ".".join(str(v) for v in msg.version)

        def conv(m, ms):
            m.temp = float(ms.temperature[0])
            m.temp2 = float(ms.temperature[1])
            m.vol = float(ms.vol)
            m.error = ms.motorstate

        self._motors(st, msg.motor_state, conv)
        st.imu = self._imu(msg)
        st.remote = parse_remote(msg.wireless_remote)
        st.board = {"mode_pr": msg.mode_pr, "mode_machine": msg.mode_machine}
        bc = self._latest.get("bms")
        if bc is not None and bc.last is not None:
            b = bc.last
            cells = [c / 1000.0 for c in b.cell_vol if 0 < c < 10000]
            v = b.bmsvoltage[0] if b.bmsvoltage else 0
            volt = v / 1000.0 if v > 1000 else float(v)
            if volt <= 0:
                volt = sum(cells)
            st.battery = Battery(
                valid=True, soc=float(b.soc), voltage=volt, current=b.current / 1000.0,
                cycle=b.cycle, soh=b.soh, status=b.bmsstate[0] if b.bmsstate else 0,
                temps=[float(t) for t in b.temperature if t],
                cells=cells, version="{}.{}".format(b.version_high, b.version_low),
                source=self._latest.get("bms:topic", ""))
        else:
            # no BMS topic: estimate pack voltage from the motor bus voltage
            vols = [m.vol for m in st.motors if m.active and m.vol]
            if vols:
                st.battery = Battery(valid=False, voltage=sum(vols) / len(vols),
                                     source="motor bus (no BMS topic)")
        mb = self._latest.get("mainboard")
        if mb is not None and mb.last is not None:
            st.board["mainboard temp"] = ", ".join(str(t) for t in mb.last.temperature)
            st.board["mainboard fan"] = ", ".join(str(f) for f in mb.last.fan_state)

    @staticmethod
    def _fill_sport(st, s, topic):
        st.sport = Sport(True, s.mode, s.gait_type, s.error_code, s.body_height,
                         list(s.position), list(s.velocity), s.yaw_speed, topic)
        if not st.foot_force:
            st.foot_force = list(s.foot_force)


# ----------------------------------------------------------------------------
# History helper shared by the GUI
# ----------------------------------------------------------------------------

class History:
    def __init__(self, maxlen=240):
        self.maxlen = maxlen
        self._d = {}

    def push(self, key, value):
        d = self._d.get(key)
        if d is None:
            d = self._d[key] = deque(maxlen=self.maxlen)
        d.append(value)

    def get(self, key):
        return self._d.get(key, ())
