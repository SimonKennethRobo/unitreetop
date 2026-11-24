"""Synthetic robot so the UI can be tried without hardware (``--demo``)."""
import math
import time

from .models import MODELS
from .robot import Battery, Imu, Motor, Remote, RobotState, Sport


class DemoLink:
    def __init__(self, robot="go2"):
        self.model = MODELS.get(robot if robot != "auto" else "go2", MODELS["go2"])
        self._t0 = time.monotonic()
        self._tick = 0

    def start(self):
        pass

    def stop(self):
        pass

    def snapshot(self) -> RobotState:
        t = time.monotonic() - self._t0
        self._tick += 1
        m = self.model
        st = RobotState(status="demo", model=m, family=m.family, lowstate_topic="rt/lowstate",
                        tick=self._tick, age=0.0)
        st.rates = {"rt/lowstate": 500.0, "rt/sportmodestate": 50.0}
        for i, name in enumerate(m.joints):
            if name is None:
                continue
            ph = t * 2.0 + i * 0.7
            st.motors.append(Motor(i, name, True, 1, 0.6 * math.sin(ph), 1.2 * math.cos(ph),
                                   8.0 * math.sin(ph + 0.4) + (3 if "calf" in name or "knee" in name else 0),
                                   35 + 10 * (0.5 + 0.5 * math.sin(t / 20 + i)), lost=i))
        roll, pitch, yaw = 0.05 * math.sin(t), 0.08 * math.sin(t * 1.3), (t * 0.2) % (2 * math.pi) - math.pi
        cy, sy, cp, sp, cr, sr = (math.cos(yaw / 2), math.sin(yaw / 2), math.cos(pitch / 2),
                                  math.sin(pitch / 2), math.cos(roll / 2), math.sin(roll / 2))
        quat = [cr * cp * cy + sr * sp * sy, sr * cp * cy - cr * sp * sy,
                cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy]
        st.imu = Imu(quat, [0.3 * math.cos(t), 0.2 * math.sin(t), 0.2],
                     [0.4 * math.sin(t * 3), 0.3 * math.cos(t * 2), 9.81 + 0.3 * math.sin(t * 5)],
                     [roll, pitch, yaw], 42)
        soc = max(5.0, 87 - t / 30)
        st.battery = Battery(True, soc, 25.2 + 4.2 * soc / 100, -3.5 - 2 * math.sin(t), 37, 98, 8,
                             [33, 32, 36, 35], [3.15 + 0.52 * soc / 100 + 0.004 * k for k in range(8)],
                             "1.18", "(demo)")
        st.sport = Sport(True, 1, 1, 0, 0.32, [math.cos(t / 5), math.sin(t / 5), 0.32],
                         [0.4 * math.cos(t / 3), 0.0, 0.0], 0.2, "(demo)")
        st.foot_force = [int(80 + 60 * math.sin(t * 4 + k * math.pi / 2)) for k in range(4)]
        st.remote = Remote(True, math.sin(t), math.cos(t), 0.0, 0.3, ["A"] if int(t) % 3 == 0 else [])
        st.board = {"bus voltage": "{:.2f} V".format(st.battery.voltage), "fan": "0, 0, 0, 0"}
        st.version = "demo"
        return st
