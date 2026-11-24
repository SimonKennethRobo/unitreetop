"""Keyboard teleoperation: high-level velocity + posture commands over unitree_sdk2 RPC.

Safety model
------------
* Nothing is sent until the operator *arms* the controller (and arming requires an
  online robot). Leaving the control page, quitting, or Esc disarms and stops.
* Velocity is hold-to-drive: each key press refreshes a per-axis deadman timer; an axis
  whose key has not been seen for ``hold_timeout`` s returns to zero (terminals have no
  key-release events, so the timer must outlast the keyboard auto-repeat delay).
* Commanded velocity is slew-rate limited, then sent at ``rate`` Hz while non-zero;
  one StopMove is sent when it reaches zero. Space zeroes everything immediately.
* Damp is executed ahead of anything else queued and zeroes the velocity.

All RPC calls run on the teleop thread, never on the UI thread.
"""
import collections
import threading
import time

from .models import MODELS

# unitree_sdk2py/rpc/internal.py
RPC_ERRORS = {
    3001: "unknown error", 3102: "send failed", 3103: "api not registered", 3104: "timeout (service not running?)",
    3105: "api mismatch", 3106: "bad reply data", 3107: "lease invalid", 3201: "server send failed",
    3202: "server internal error", 3203: "api not implemented", 3204: "bad parameter", 3205: "lease denied",
    3206: "lease missing", 3207: "lease exists",
}

AXES = ("vx", "vy", "wz")
# key -> (axis, sign)
DRIVE_KEYS = {"w": ("vx", 1), "s": ("vx", -1), "a": ("vy", 1), "d": ("vy", -1), "q": ("wz", 1), "e": ("wz", -1)}


def describe(code):
    if code is None:
        return "sent"
    if code == 0:
        return "ok"
    return "{} {}".format(code, RPC_ERRORS.get(code, "robot error"))


# ----------------------------------------------------------------------------
# Backends: one per SDK client family
# ----------------------------------------------------------------------------

class Backend:
    name = "none"
    # default limits: m/s, m/s, rad/s  and slew limits per second
    limits = {"vx": 0.5, "vy": 0.3, "wz": 0.8}
    accel = {"vx": 1.0, "vy": 1.0, "wz": 2.0}
    # action key -> label shown in the panel
    labels = {"sit": "n/a", "stand": "n/a", "damp": "Damp"}

    def move(self, vx, vy, wz):
        raise NotImplementedError

    def stop_move(self):
        return self.move(0.0, 0.0, 0.0)

    def action(self, name):
        raise NotImplementedError


class SportBackend(Backend):
    """Go2 / Go2-W / B2 / B2-W: SportClient (service "sport")."""

    labels = {"sit": "StandDown", "stand": "RecoveryStand", "damp": "Damp"}

    def __init__(self, model_key):
        if model_key.startswith("b2"):
            from unitree_sdk2py.b2.sport.sport_client import SportClient
            self.name = "b2 SportClient"
        else:
            from unitree_sdk2py.go2.sport.sport_client import SportClient
            self.name = "go2 SportClient"
        self.cli = SportClient()
        self.cli.SetTimeout(3.0)
        self.cli.Init()

    def move(self, vx, vy, wz):
        return self.cli.Move(vx, vy, wz)  # fire-and-forget (no reply)

    def stop_move(self):
        return self.cli.StopMove()

    def action(self, name):
        if name == "sit":
            return self.cli.StandDown()
        if name == "stand":
            return self.cli.RecoveryStand()  # works from lying and from damping, ends in balance stand
        if name == "damp":
            return self.cli.Damp()
        return None


class LocoBackend(Backend):
    """G1 (service "sport", 7xxx APIs) and H1 (service "loco"): LocoClient.

    The SDK's posture helpers discard the RPC code, so SetFsmId is called directly.
    """
    limits = {"vx": 0.3, "vy": 0.2, "wz": 0.5}
    accel = {"vx": 0.6, "vy": 0.6, "wz": 1.0}

    def __init__(self, model_key):
        if model_key == "h1":
            from unitree_sdk2py.h1.loco.h1_loco_client import LocoClient
            self.name = "h1 LocoClient"
            self.fsm = {"stand": 2, "damp": 1}                 # StandUp, Damp
            self.labels = {"sit": "n/a", "stand": "StandUp (fsm 2)", "damp": "Damp (fsm 1)"}
        else:
            from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
            self.name = "g1 LocoClient"
            self.fsm = {"sit": 3, "stand": 706, "damp": 1}     # Sit, Squat2StandUp, Damp
            self.labels = {"sit": "Sit (fsm 3)", "stand": "Squat2StandUp (fsm 706)", "damp": "Damp (fsm 1)"}
        self.cli = LocoClient()
        self.cli.SetTimeout(3.0)
        self.cli.Init()

    def move(self, vx, vy, wz):
        # duration=1 s: the robot itself stops if commands stop arriving
        return self.cli.SetVelocity(vx, vy, wz, 1.0)

    def action(self, name):
        fid = self.fsm.get(name)
        return None if fid is None else self.cli.SetFsmId(fid)


class DemoBackend(Backend):
    name = "demo"
    labels = {"sit": "StandDown", "stand": "RecoveryStand", "damp": "Damp"}

    def __init__(self, link=None):
        self.link = link

    def move(self, vx, vy, wz):
        if self.link is not None:
            self.link.cmd_vel = (vx, vy, wz)
        return None

    def stop_move(self):
        self.move(0.0, 0.0, 0.0)
        return 0

    def action(self, name):
        if self.link is not None:
            self.link.posture = {"sit": "lying", "stand": "standing", "damp": "damped"}.get(name, "?")
        return 0


def make_backend(model_key, demo_link=None):
    """Return (backend, error). Imports the SDK client only when control is first used."""
    if demo_link is not None:
        return DemoBackend(demo_link), ""
    if model_key not in MODELS:
        return None, "robot model unknown yet"
    try:
        if model_key in ("go2", "go2w", "b2", "b2w"):
            return SportBackend(model_key), ""
        if model_key in ("g1", "h1"):
            return LocoBackend(model_key), ""
    except Exception as e:  # SDK missing / DDS not initialised
        return None, "control client init failed: {}".format(e)
    return None, "no high-level control API for {} in unitree_sdk2py".format(MODELS[model_key].name)


# ----------------------------------------------------------------------------
# Teleop state machine + sender thread
# ----------------------------------------------------------------------------

class Teleop:
    SCALES = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5)

    def __init__(self, backend, hold_timeout=0.7, rate=20.0, limits=None):
        self.backend = backend
        self.limits = dict(backend.limits)
        self.limits.update({k: v for k, v in (limits or {}).items() if v})
        self.accel = dict(backend.accel)
        self.hold_timeout = hold_timeout
        self.rate = rate
        self.scale_i = self.SCALES.index(1.0)
        self.armed = False
        self.cmd = {a: 0.0 for a in AXES}          # slew-limited velocity actually sent
        self._target = {a: 0.0 for a in AXES}
        self._pressed = {a: 0.0 for a in AXES}     # monotonic time of last key press
        self._moving = False
        self._queue = collections.deque()
        self.log = collections.deque(maxlen=8)     # (wall time, text, ok)
        self.last_move = ""
        self.sent = 0
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="utop-teleop", daemon=True)
        self._thread.start()

    # -- operator API (UI thread) ----------------------------------------
    @property
    def scale(self):
        return self.SCALES[self.scale_i]

    def arm(self):
        with self._lock:
            self.armed = True
        self._note("armed", True)

    def disarm(self, reason="disarmed"):
        """Stop (StopMove is sent only if we were armed) and refuse further commands."""
        if not self.armed:
            return
        self.stop(note=False)
        with self._lock:
            self.armed = False
        self._note(reason, True)

    def drive(self, key):
        """Register a press of w/a/s/d/q/e."""
        axis, sign = DRIVE_KEYS[key]
        with self._lock:
            if not self.armed:
                return
            self._target[axis] = sign * self.limits[axis] * self.scale
            self._pressed[axis] = time.monotonic()
            # opposite key on the same axis overrides immediately
        self._wake.set()

    def stop(self, note=True):
        with self._lock:
            if not self.armed:  # a monitoring-only session never sends anything
                return
            for a in AXES:
                self._target[a] = 0.0
                self._pressed[a] = 0.0
                self.cmd[a] = 0.0
            self._queue.append("stop")
        if note:
            self._note("stop", True)
        self._wake.set()

    def action(self, name):
        with self._lock:
            if not self.armed:
                return
            if name == "damp":  # emergency-ish: drop pending work, zero velocity, go first
                self._queue.clear()
                for a in AXES:
                    self._target[a] = self.cmd[a] = 0.0
                    self._pressed[a] = 0.0
                self._queue.appendleft("damp")
            else:
                self._queue.append(name)
        self._wake.set()

    def change_scale(self, step):
        self.scale_i = max(0, min(len(self.SCALES) - 1, self.scale_i + step))

    def active_keys(self):
        now = time.monotonic()
        keys = set()
        for k, (axis, sign) in DRIVE_KEYS.items():
            if now - self._pressed[axis] < self.hold_timeout and self._target[axis] * sign > 0:
                keys.add(k)
        return keys

    def close(self):
        self.disarm("closed")
        self._wake.set()
        time.sleep(1.5 / self.rate)  # let the loop flush the final StopMove
        self._running = False
        self._wake.set()

    # -- sender thread -----------------------------------------------------
    def _note(self, text, ok):
        self.log.appendleft((time.strftime("%H:%M:%S"), text, ok))

    def _call(self, label, fn, *args):
        try:
            code = fn(*args)
        except Exception as e:
            self._note("{}: {}".format(label, e), False)
            return
        self._note("{}: {}".format(label, describe(code)), code in (None, 0))

    def _loop(self):
        period = 1.0 / self.rate
        last = time.monotonic()
        while self._running:
            self._wake.wait(period)
            self._wake.clear()
            now = time.monotonic()
            dt = min(now - last, 0.2)
            last = now
            with self._lock:
                jobs = list(self._queue)
                self._queue.clear()
                armed = self.armed
                # deadman: axes whose key is no longer repeating fall back to zero
                for a in AXES:
                    if now - self._pressed[a] >= self.hold_timeout:
                        self._target[a] = 0.0
                    step = self.accel[a] * self.scale * dt
                    d = self._target[a] - self.cmd[a]
                    self.cmd[a] += max(-step, min(step, d))
                    if abs(self.cmd[a]) < 1e-3 and self._target[a] == 0.0:
                        self.cmd[a] = 0.0
                cmd = (self.cmd["vx"], self.cmd["vy"], self.cmd["wz"])
            for job in jobs:
                if job == "stop":  # only ever queued while armed
                    self._call("StopMove", self.backend.stop_move)
                    self._moving = False
                else:
                    self._call(self.backend.labels.get(job, job), self.backend.action, job)
                    if job == "damp":
                        self._moving = False  # no StopMove to a robot that just went limp
            if not armed:
                continue
            if any(cmd):
                try:
                    code = self.backend.move(*cmd)
                    self.sent += 1
                    self.last_move = "Move({:+.2f}, {:+.2f}, {:+.2f}) {}".format(cmd[0], cmd[1], cmd[2], describe(code))
                    if code not in (None, 0):
                        self._note(self.last_move, False)
                except Exception as e:
                    self._note("Move: {}".format(e), False)
                self._moving = True
            elif self._moving:
                self._call("StopMove", self.backend.stop_move)
                self._moving = False
