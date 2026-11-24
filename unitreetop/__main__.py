"""unitreetop command line entry point."""
import argparse
import json
import os
import signal
import sys
import time

from . import __version__
from .core import UnitreeTop
from .core.models import MODELS

PAGE_NAMES = ["all", "cpu", "gpu", "mem", "joints", "imu", "power", "info", "ctrl"]


def build_parser():
    p = argparse.ArgumentParser(
        prog="unitreetop",
        description="terminal console for Unitree robots: CPU/GPU/memory, live robot state "
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
    p.add_argument("--no-control", action="store_true",
                   help="monitor only: disable the keyboard control page (no command is ever sent)")
    p.add_argument("--vel-step", type=float, default=0.1,
                   help="teleop velocity change per key press [m/s or rad/s] (first press from zero: 3 steps, yaw 5)")
    p.add_argument("--max-vx", type=float, default=None, help="teleop forward speed cap [m/s] (model default)")
    p.add_argument("--max-vy", type=float, default=None, help="teleop lateral speed cap [m/s] (model default)")
    p.add_argument("--max-wz", type=float, default=None, help="teleop yaw rate cap [rad/s] (model default)")
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
                    lowstate_topic=args.lowstate_topic, control=not args.no_control,
                    vel_step=args.vel_step,
                    max_vel={"vx": args.max_vx, "vy": args.max_vy, "wz": args.max_wz})
    signalled = []

    def end_session(signum, _frame):  # ssh drop / kill: still run the cleanup (StopMove if armed)
        signalled.append(signum)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGHUP, end_session)
    signal.signal(signal.SIGTERM, end_session)
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
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception:
        # after SIGHUP the tty may be gone, so curses' own cleanup can fail: not an error then
        if not signalled:
            raise
    finally:
        ut.close()
    # cyclonedds listener threads can keep the interpreter alive; leave promptly
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
