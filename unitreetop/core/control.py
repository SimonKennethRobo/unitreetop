"""Keyboard teleoperation: high-level velocity + posture commands over unitree_sdk2 RPC.

Behaviour follows the go2_keyboard_ctrl script (velocity lock, keys adjust steps):

* W/S, A/D, Q/E adjust vx, vy, wz. From zero the first press jumps to a start speed
  (3 steps for x/y, 5 for yaw, 0.1 per step); every further press adds or removes one
  step. The velocity stays *locked* until changed, and is sent as Move at 10 Hz while
  non-zero; a single StopMove follows when it returns to zero.
* Space clears the velocity. Z / X / P first clear the velocity (StopMove if moving),
  then call the posture API. The same posture key repeated within 0.65 s is ignored
  (keyboard auto-repeat). After P (damp) velocity keys are ignored until X succeeds.

Safety additions of unitreetop
------------------------------
* Nothing is sent until the operator *arms* the panel, and arming needs an online
  robot. Esc, leaving the page, quitting, SIGHUP/SIGTERM and the robot going offline
  all disarm, which stops the robot. A session that never arms sends nothing.
* Velocities are clamped to per-model limits (the original script has none).
* All RPC calls run on the teleop thread, never on the UI thread.
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
VELOCITY_STEP = 0.10                       # m/s for x/y, rad/s for yaw
START_STEPS = {"vx": 3, "vy": 3, "wz": 5}  # first press from zero
POSTURE_REPEAT_GAP = 0.65                  # s; same posture key again within this is ignored


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
    # velocity caps: m/s, m/s, rad/s
    limits = {"vx": 1.0, "vy": 0.6, "wz": 1.5}
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
    limits = {"vx": 0.6, "vy": 0.4, "wz": 1.0}

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
    """Velocity-lock teleop state machine plus the sender thread."""

    def __init__(self, backend, rate=10.0, limits=None, step=VELOCITY_STEP):
        self.backend = backend
        self.limits = dict(backend.limits)
        self.limits.update({k: v for k, v in (limits or {}).items() if v})
        self.step = step
        self.rate = rate
        self.armed = False
        self.damped = False                        # set by P, cleared by a successful X
        self.steps = {a: 0 for a in AXES}
        self.cmd = {a: 0.0 for a in AXES}          # locked velocity being sent
        self._moving = False
        self._queue = collections.deque()
        self._last_posture = (None, 0.0)
        self.log = collections.deque(maxlen=8)     # (wall time, text, ok)
        self.last_move = ""
        self.sent = 0
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="utop-teleop", daemon=True)
        self._thread.start()

    # -- operator API (UI thread) ----------------------------------------
    def max_steps(self, axis):
        return max(1, int(round(self.limits[axis] / self.step)))

    def arm(self):
        with self._lock:
            self.armed = True
        self._note("armed", True)

    def disarm(self, reason="disarmed"):
        """Clear the velocity (StopMove if moving) and refuse further commands."""
        if not self.armed:
            return
        self.stop(note=False)
        with self._lock:
            self.armed = False
        self._note(reason, True)

    def drive(self, key):
        """w/s a/d q/e: start at START_STEPS from zero, then +/- one step per press."""
        axis, sign = DRIVE_KEYS[key]
        with self._lock:
            if not self.armed or self.damped:
                return
            self._last_posture = (None, 0.0)
            n = self.steps[axis]
            n = sign * START_STEPS[axis] if n == 0 else n + sign
            cap = self.max_steps(axis)
            self.steps[axis] = max(-cap, min(cap, n))
            self._update_cmd()
        self._wake.set()

    def _update_cmd(self):
        for a in AXES:
            self.cmd[a] = round(self.steps[a] * self.step, 3)

    def _clear(self):
        for a in AXES:
            self.steps[a] = 0
            self.cmd[a] = 0.0
        self._queue.append("stop")

    def stop(self, note=True):
        with self._lock:
            if not self.armed:  # a monitoring-only session never sends anything
                return
            self._clear()
            self._last_posture = (None, 0.0)
        if note:
            self._note("velocity cleared", True)
        self._wake.set()

    def action(self, name):
        """z / x / p: clear velocity first, then the posture call (auto-repeat guarded)."""
        with self._lock:
            if not self.armed:
                return
            now = time.monotonic()
            last, at = self._last_posture
            self._last_posture = (name, now)
            if name == last and now - at < POSTURE_REPEAT_GAP:
                return
            self._clear()
            if name == "damp":
                self.damped = True
                self._queue.clear()              # damp goes first; nothing else pending matters
                self._queue.append("stop")
            self._queue.append(name)
        self._wake.set()

    def active_keys(self):
        keys = set()
        for k, (axis, sign) in DRIVE_KEYS.items():
            if self.steps[axis] * sign > 0:
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
            return None
        self._note("{}: {}".format(label, describe(code)), code in (None, 0))
        return code

    def _loop(self):
        period = 1.0 / self.rate
        next_move = 0.0
        while self._running:
            self._wake.wait(max(0.0, next_move - time.monotonic()) if self._moving else period)
            self._wake.clear()
            with self._lock:
                jobs = list(self._queue)
                self._queue.clear()
                armed = self.armed
                cmd = (self.cmd["vx"], self.cmd["vy"], self.cmd["wz"])
            for job in jobs:
                if job == "stop":                 # only queued while armed
                    if self._moving:
                        self._call("StopMove", self.backend.stop_move)
                        self._moving = False
                    continue
                code = self._call(self.backend.labels.get(job, job), self.backend.action, job)
                if job == "stand" and code in (None, 0):
                    self.damped = False
                elif job == "damp" and code not in (None, 0):
                    pass  # keep velocity keys locked anyway: the robot state is unknown
            if not armed:
                if self._moving:  # disarmed while moving (stop job already handled above)
                    self._call("StopMove", self.backend.stop_move)
                    self._moving = False
                continue
            now = time.monotonic()
            if any(cmd):
                if not self._moving or now >= next_move:
                    next_move = now + period
                    try:
                        code = self.backend.move(*cmd)
                        self.sent += 1
                        self.last_move = "Move({:+.2f}, {:+.2f}, {:+.2f}) {}".format(
                            cmd[0], cmd[1], cmd[2], describe(code))
                        if code not in (None, 0):  # like the script: never keep driving blind
                            self._note(self.last_move + " - velocity cleared", False)
                            with self._lock:
                                self._clear()
                    except Exception as e:
                        self._note("Move: {} - velocity cleared".format(e), False)
                        with self._lock:
                            self._clear()
                    self._moving = True
            elif self._moving:
                self._call("StopMove", self.backend.stop_move)
                self._moving = False
