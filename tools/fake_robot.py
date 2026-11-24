#!/usr/bin/env python3
"""Publish synthetic Unitree DDS state to exercise unitreetop's DDS path without a robot.

    python3 tools/fake_robot.py --family hg -d 1 -i lo      # G1-style (unitree_hg) lowstate + BMS
    python3 tools/fake_robot.py --family go -d 1 -i lo      # Go2-style lowstate + sportmodestate
    unitreetop -d 1 -i lo

Both families also serve a fake high-level RPC service named "sport" (Go2 SportClient
1xxx APIs and G1 LocoClient 7xxx APIs): every request is printed, Move/SetVelocity
drive the published sportmodestate velocity, so the control page can be tested end to
end without a robot.
"""
import argparse
import json
import math
import time

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelPublisher
from unitree_sdk2py.rpc.server import Server

GO2_API = {1001: "Damp", 1002: "BalanceStand", 1003: "StopMove", 1004: "StandUp", 1005: "StandDown",
           1006: "RecoveryStand", 1008: "Move", 1009: "Sit", 1010: "RiseSit"}
LOCO_API = {7101: "SetFsmId", 7105: "SetVelocity"}


class FakeSport(Server):
    """Answers SportClient / LocoClient requests and remembers the last velocity command."""

    def __init__(self):
        Server.__init__(self, "sport")
        self.vel = (0.0, 0.0, 0.0)
        self.vel_until = 0.0
        self.posture = "standing"

    def Init(self):
        for api, name in list(GO2_API.items()) + list(LOCO_API.items()):
            self._RegistHandler(api, self._make(api, name), False)

    def _make(self, api, name):
        def handler(parameter):
            print("[fake sport] {:<14} {}".format(name, parameter), flush=True)
            p = json.loads(parameter or "{}")
            if name == "Move":
                self.vel, self.vel_until = (p.get("x", 0), p.get("y", 0), p.get("z", 0)), time.time() + 0.5
            elif name == "SetVelocity":
                v = p.get("velocity", [0, 0, 0])
                self.vel, self.vel_until = tuple(v), time.time() + float(p.get("duration", 1.0))
            elif name in ("StopMove", "Damp"):
                self.vel = (0.0, 0.0, 0.0)
            if name in ("Damp", "StandDown", "RecoveryStand", "StandUp", "Sit"):
                self.posture = name
            elif name == "SetFsmId":
                self.posture = "fsm {}".format(p.get("data"))
            return 0, ""
        return handler

    def velocity(self):
        return self.vel if time.time() < self.vel_until else (0.0, 0.0, 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", choices=["go", "hg"], default="hg")
    ap.add_argument("-d", "--domain", type=int, default=1)
    ap.add_argument("-i", "--interface", default="lo")
    ap.add_argument("--hz", type=float, default=500.0)
    ap.add_argument("--motors", type=int, default=None, help="active motors (default 29 hg / 12 go)")
    a = ap.parse_args()
    ChannelFactoryInitialize(a.domain, a.interface)
    sport_srv = FakeSport()
    sport_srv.Init()
    sport_srv.Start()

    if a.family == "hg":
        from unitree_sdk2py.idl.default import (unitree_hg_msg_dds__BmsState_ as BmsDefault,
                                                unitree_hg_msg_dds__LowState_ as LowDefault)
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import BmsState_, LowState_
        n = a.motors or 29
        bms_pub = ChannelPublisher("rt/lf/bmsstate", BmsState_)
        bms_pub.Init()
        bms = BmsDefault()
    else:
        from unitree_sdk2py.idl.default import (unitree_go_msg_dds__LowState_ as LowDefault,
                                                unitree_go_msg_dds__SportModeState_ as SportDefault)
        from unitree_sdk2py.idl.unitree_go.msg.dds_ import LowState_, SportModeState_
        n = a.motors or 12
        sport_pub = ChannelPublisher("rt/sportmodestate", SportModeState_)
        sport_pub.Init()
        sport = SportDefault()
    low_pub = ChannelPublisher("rt/lowstate", LowState_)
    low_pub.Init()
    low = LowDefault()
    print("publishing {} lowstate with {} motors on domain {} / {}".format(a.family, n, a.domain, a.interface))
    k = 0
    t0 = time.time()
    while True:
        t = time.time() - t0
        low.tick = k
        for i in range(n):
            m = low.motor_state[i]
            m.mode = 1
            m.q = 0.5 * math.sin(t + i * 0.3)
            m.dq = 0.5 * math.cos(t + i * 0.3)
            m.tau_est = 5 * math.sin(2 * t + i)
            if a.family == "hg":
                m.temperature = [40 + i % 7, 35 + i % 5]
                m.vol = 52.0
            else:
                m.temperature = 40 + i % 7
        low.imu_state.rpy = [0.05 * math.sin(t), 0.03 * math.cos(t), t % 6.28 - 3.14]
        low.imu_state.accelerometer = [0.1, 0.0, 9.81]
        if a.family == "go":
            low.bms_state.soc = 77
            low.bms_state.current = -4200
            low.bms_state.cell_vol = [3950] * 8 + [0] * 7
            low.power_v = 31.6
        low_pub.Write(low)
        if k % 10 == 0:
            if a.family == "hg":
                bms.soc = 81
                bms.current = -6300
                bms.bmsvoltage = [54200, 0, 0]
                bms.cell_vol = [3870 + j for j in range(14)] + [0] * 26
                bms.temperature = [31, 32, 30] + [0] * 9
                bms.soh = 97
                bms.cycle = 12
                bms_pub.Write(bms)
            else:
                vx, vy, wz = sport_srv.velocity()
                sport.mode = 1
                sport.body_height = 0.31
                sport.velocity = [float(vx), float(vy), 0.0]
                sport.yaw_speed = float(wz)
                sport_pub.Write(sport)
        k += 1
        time.sleep(1.0 / a.hz)


if __name__ == "__main__":
    main()
