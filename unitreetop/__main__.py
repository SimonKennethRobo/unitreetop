"""unitreetop command line entry point."""
import argparse
import json
import os
import sys
import time

from . import __version__
from .core import UnitreeTop
from .core.models import MODELS

PAGE_NAMES = ["all", "cpu", "gpu", "mem", "joints", "imu", "power", "info"]


def build_parser():
    p = argparse.ArgumentParser(
        prog="unitreetop",
        description="top-like monitor for Unitree robots: CPU/GPU/memory plus live robot state "
                    "(joints, battery, IMU) over unitree_sdk2 DDS.")
    p.add_argument("-i", "--interface", default=os.environ.get("UNITREETOP_IFACE"),
                   help="network interface connected to the robot (e.g. eth0 / eth1 / enp3s0). "
                        "Default: the NIC with a 192.168.123.x address, else CycloneDDS auto-select")
    p.add_argument("-d", "--domain", type=int, default=int(os.environ.get("UNITREETOP_DOMAIN", 0)),
                   help="DDS domain id (robot: 0, unitree_mujoco: 1)")
    p.add_argument("-r", "--robot", default="auto", choices=["auto"] + sorted(MODELS),
                   help="robot model (joint names / layout). auto = detect from DDS")
    p.add_argument("--lowstate-topic", default=None,
                   help="lowstate topic (default rt/lowstate; rt/lf/lowstate is lower rate and cheaper)")
    p.add_argument("--gpu", default="auto", choices=["auto", "jtop", "tegra", "nvidia", "none"],
                   help="GPU/board backend")
    p.add_argument("--interval", type=float, default=0.5, help="system stats interval [s]")
    p.add_argument("--robot-hz", type=float, default=20.0,
                   help="minimum robot snapshot / history rate [Hz]; fast pages (JOINTS/IMU) raise it")
    p.add_argument("-p", "--page", default="all", choices=PAGE_NAMES, help="start page")
    p.add_argument("--demo", action="store_true", help="synthetic robot data, no DDS needed")
    p.add_argument("--no-robot", action="store_true", help="host stats only")
    p.add_argument("--json", action="store_true", help="print one JSON snapshot and exit")
    p.add_argument("--wait", type=float, default=2.0, help="seconds to collect before --json output")
    p.add_argument("-v", "--version", action="version", version="unitreetop " + __version__)
    return p


UNITREE_NET = "192.168.123."  # robot-internal network on every Unitree model


def guess_interface():
    """NIC with a 192.168.123.x address (the robot's internal network), else None."""
    try:
        import socket
        import psutil
        for name, addrs in psutil.net_if_addrs().items():
            if any(a.family == socket.AF_INET and a.address.startswith(UNITREE_NET) for a in addrs):
                return name
    except Exception:
        pass
    return None


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.interface is None and not (args.demo or args.no_robot):
        args.interface = guess_interface()
    ut = UnitreeTop(interface=args.interface, domain=args.domain, robot=args.robot, interval=args.interval,
                    robot_hz=args.robot_hz, gpu=args.gpu, demo=args.demo, no_robot=args.no_robot,
                    lowstate_topic=args.lowstate_topic)
    try:
        ut.start()
        if args.json:
            time.sleep(args.wait)
            json.dump(ut.as_dict(), sys.stdout, indent=2, default=str)
            sys.stdout.write("\n")
        else:
            from .gui import run_gui
            # curses owns the tty; stray prints from the SDK / cyclonedds would corrupt it
            # (CycloneDDS writes warnings from C straight to fd 2, so redirect the fd too)
            real_out, real_err = sys.stdout, sys.stderr
            saved_fd2 = os.dup(2)
            devnull = open(os.devnull, "w")
            os.dup2(devnull.fileno(), 2)
            sys.stdout = sys.stderr = devnull
            try:
                run_gui(ut, PAGE_NAMES.index(args.page))
            finally:
                os.dup2(saved_fd2, 2)
                sys.stdout, sys.stderr = real_out, real_err
    except KeyboardInterrupt:
        pass
    finally:
        ut.close()
    # cyclonedds listener threads can keep the interpreter alive; leave promptly
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
