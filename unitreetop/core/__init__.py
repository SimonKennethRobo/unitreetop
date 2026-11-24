"""Collector core: ``UnitreeTop`` gathers host + robot stats in a background thread.

Usage (mirrors ``jtop``)::

    from unitreetop import UnitreeTop

    with UnitreeTop(interface="eth1") as ut:
        while ut.ok():
            print(ut.cpu["total"], ut.robot.battery.soc, ut.robot.imu.rpy)
"""
import threading
import time

from .gpu import make_backend
from .robot import History, RobotLink, RobotState
from .system import SystemStats


class UnitreeTop:
    def __init__(self, interface=None, domain=0, robot="auto", interval=0.5, robot_hz=20.0,
                 gpu="auto", demo=False, no_robot=False, lowstate_topic=None):
        self.interval = interval
        self.robot_hz = robot_hz        # current snapshot rate (the GUI raises it for fast pages)
        self.robot_hz_base = robot_hz   # floor, keeps history sampling sane on slow pages
        self.interface = interface
        self.domain = domain
        self._sys = SystemStats()
        self._gpu_pref = gpu
        self.gpu_backend = None
        self.gpu_errors = []
        if no_robot:
            self._link = None
        elif demo:
            from .demo import DemoLink
            self._link = DemoLink(robot)
        else:
            self._link = RobotLink(interface, domain, robot, lowstate_topic)
        self.stats = {}
        self.gpu_stats = {}
        self.robot = RobotState()
        self.history = History(240)
        self._event = threading.Event()
        self._running = False
        self._threads = []
        self._lock = threading.Lock()
        # the per-process scan is by far the most expensive collector (~0.1 cpu-s on an
        # Orin NX with ~400 processes); the GUI enables it only while the CPU page is shown
        self.want_procs = False
        self.procs_interval = 2.0
        self._procs_t = 0.0

    # -- context manager -------------------------------------------------
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()

    def start(self):
        self.gpu_backend, self.gpu_errors = make_backend(self._gpu_pref)
        if self._link is not None:
            self._link.start()
        self._running = True
        self.stats = self._sys.read(with_procs=False)
        self._threads = [threading.Thread(target=self._sys_loop, name="utop-sys", daemon=True),
                         threading.Thread(target=self._robot_loop, name="utop-robot", daemon=True)]
        for t in self._threads:
            t.start()

    def close(self):
        self._running = False
        if self._link is not None:
            self._link.stop()
        if self.gpu_backend is not None:
            self.gpu_backend.close()

    def ok(self, timeout=None):
        """Block until fresh data is available (like jtop.ok())."""
        if not self._running:
            return False
        self._event.wait(timeout if timeout is not None else self.interval * 4)
        self._event.clear()
        return self._running

    # -- properties ------------------------------------------------------
    @property
    def cpu(self):
        return self.stats.get("cpu", {})

    @property
    def memory(self):
        return {"RAM": self.stats.get("mem", {}), "SWAP": self.stats.get("swap", {})}

    @property
    def gpu(self):
        return self.gpu_stats.get("gpus", [])

    # -- loops -----------------------------------------------------------
    def _sys_loop(self):
        while self._running:
            t0 = time.monotonic()
            try:
                procs = self.want_procs and t0 - self._procs_t >= self.procs_interval
                st = self._sys.read(with_procs=procs)
                if procs:
                    self._procs_t = t0
                elif "procs" in self.stats:
                    st["procs"] = self.stats["procs"]
                self.stats = st
            except Exception as e:
                self.stats.setdefault("errors", []).append(str(e))
            try:
                self.gpu_stats = self.gpu_backend.read()
            except Exception as e:
                self.gpu_errors.append("{}: {}".format(self.gpu_backend.name, e))
                from .gpu import NullBackend
                self.gpu_backend = NullBackend()
            h = self.history
            h.push("cpu", self.cpu.get("total", 0.0))
            for i, c in enumerate(self.cpu.get("cores", [])):
                h.push("cpu{}".format(i), c["load"])
            h.push("ram", self.stats.get("mem", {}).get("percent", 0.0))
            for i, g in enumerate(self.gpu):
                h.push("gpu{}".format(i), g["load"])
            for name, n in self.stats.get("net", {}).items():
                h.push("rx:" + name, n["rx"])
                h.push("tx:" + name, n["tx"])
            pw = self.gpu_stats.get("power", {})
            if pw:
                h.push("board_power", pw.get("total", 0.0))
            self._event.set()
            time.sleep(max(0.05, self.interval - (time.monotonic() - t0)))

    def _robot_loop(self):
        while self._running:
            t0 = time.monotonic()
            period = 1.0 / max(self.robot_hz, 1.0)
            if self._link is not None:
                st = self._link.snapshot()
                self.robot = st
                if st.online:
                    h = self.history
                    for k, v in zip(("roll", "pitch", "yaw"), st.imu.rpy):
                        h.push(k, v)
                    for k, v in zip(("gx", "gy", "gz"), st.imu.gyro):
                        h.push(k, v)
                    for k, v in zip(("ax", "ay", "az"), st.imu.acc):
                        h.push(k, v)
                    if st.battery.voltage:
                        h.push("bat_power", -st.battery.power)
                        h.push("bat_current", -st.battery.current)
                        h.push("bat_voltage", st.battery.voltage)
                    for m in st.motors:
                        h.push("q{}".format(m.index), m.q)
                        h.push("dq{}".format(m.index), m.dq)
                        h.push("tau{}".format(m.index), m.tau)
                        h.push("temp{}".format(m.index), m.temp)
            time.sleep(max(0.005, period - (time.monotonic() - t0)))

    # -- export ----------------------------------------------------------
    def as_dict(self):
        """Plain dict snapshot (used by ``--json``)."""
        from dataclasses import asdict
        r = self.robot
        robot = asdict(r)
        robot["model"] = r.model.key if r.model else None
        robot["topics"] = len(r.topics)
        robot["battery"]["power"] = r.battery.power
        st = dict(self.stats)
        st.pop("procs", None)
        return {"system": st, "gpu": self.gpu_stats, "gpu_backend": self.gpu_backend.name if self.gpu_backend else None,
                "robot": robot}


__all__ = ["UnitreeTop"]
