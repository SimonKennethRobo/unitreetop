# unitreetop

**English** | [中文](README.zh-CN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![Platform](<https://img.shields.io/badge/platform-Jetson%20%7C%20Linux-lightgrey>)

A terminal monitor for Unitree robots, combining [jtop](https://github.com/rbonghi/jetson_stats)-style host/Jetson metrics with live robot telemetry over [`unitree_sdk2py`](https://github.com/unitreerobotics/unitree_sdk2_python) (CycloneDDS), styled after [btop](https://github.com/aristocratos/btop).

![all](docs/screenshot-all.png)
![joints](docs/screenshot-joints.png)

<sub>Captured on a real Go2.</sub>

---

## Features

- **Host & GPU**: Per-core CPU, memory/swap/disk, network, processes, and temperatures. Supports Jetson (`jtop` / sysfs) and desktop NVIDIA GPUs (NVML / `nvidia-smi`).
- **Robot Telemetry (Read-Only)**:
  - **Joints**: Position (`q`), velocity (`dq`), torque (`tau`), temperature, mode, packet loss/error bits, and real-time history graphs.
  - **Battery & Power**: SOC, voltage, current, power, cycles, SOH, cell voltages/spread, and board bus/NTC/fan stats.
  - **Motion & Control**: IMU (RPY, quaternion, gyro, accel), foot force, wireless remote sticks/buttons, and `SportModeState`.
  - **DDS Inspector**: Live discovery and frequency (Hz) measurement of all DDS topics on the network.
- **Zero-Config Discovery**: Auto-detects the robot network NIC (`192.168.123.x`), DDS message family, and robot model.
- **Low Overhead**: ~8% of a single core at 1 Hz on a Go2 Orin NX.
- **Self-Contained & Scriptable**: Bundles `unitree_sdk2_python` as a submodule; includes a Python API, one-shot JSON export, and a demo mode.

## Supported Robots

| Model                    | DDS Family     | Joints  | Status                                             |
| :----------------------- | :------------- | :------ | :------------------------------------------------- |
| **Go2**            | `unitree_go` | 12      | Verified on hardware                               |
| **Go2-W**          | `unitree_go` | 16      | Implemented from SDK                               |
| **B2 / B2-W**      | `unitree_go` | 12 / 16 | Implemented from SDK (pass `-r b2` / `-r b2w`) |
| **H1**             | `unitree_go` | 19      | Implemented from SDK                               |
| **G1 (23/29 DoF)** | `unitree_hg` | 23 / 29 | Verified in simulation                             |
| **H1-2**           | `unitree_hg` | 27      | Verified in simulation                             |

## Installation

### Prerequisites

- **Required**: Python >= 3.8, `psutil`, `cyclonedds==0.10.x` (usually pre-installed on Unitree Jetson boards; otherwise `pip3 install cyclonedds==0.10.2`).
- **Optional**: `jetson-stats` (with `jtop.service` active) for full Jetson metrics; `nvidia-ml-py` for desktop GPUs.

### Install from Source (Recommended)

```bash
git clone --recurse-submodules https://github.com/SimonKennethRobo/unitreetop.git ~/Apps/unitreetop
ln -s ~/Apps/unitreetop/bin/unitreetop ~/.local/bin/unitreetop
ln -s ~/Apps/unitreetop/bin/unitreetop ~/.local/bin/untop   # optional alias
```

*(If you already cloned without `--recurse-submodules`, run `git submodule update --init`.)*

Alternatively, install via pip:

```bash
pip3 install -e .            # or pip3 install -e ".[jetson]"
```

## Usage

```bash
unitreetop                       # Auto-detect NIC (192.168.123.x) & robot model
unitreetop -i eth1               # Specify network interface (Go2 dock is usually eth1)
unitreetop -i enp3s0 -r g1       # External PC connected to G1
unitreetop -p joints             # Launch directly into the JOINTS page
unitreetop --demo -r g1          # Run with synthetic data (no robot needed)
unitreetop -d 1 -i lo            # Connect to unitree_mujoco simulator (domain 1)
unitreetop --json --wait 3       # Print a single JSON snapshot and exit
```

### CLI Options & Env Vars

| Option                    | Env Var               | Default         | Description                                                                              |
| :------------------------ | :-------------------- | :-------------- | :--------------------------------------------------------------------------------------- |
| `-i`, `--interface`   | `UNITREETOP_IFACE`  | `auto`        | Network interface on the robot subnet                                                    |
| `-d`, `--domain`      | `UNITREETOP_DOMAIN` | `0`           | DDS domain ID (`0` for real robot, `1` for MuJoCo)                                   |
| `-r`, `--robot`       | -                     | `auto`        | Force model: `go2`, `go2w`, `b2`, `b2w`, `h1`, `g1`, `h1_2`                |
| `-p`, `--page`        | -                     | `all`         | Start page: `all`, `cpu`, `gpu`, `mem`, `joints`, `imu`, `power`, `info` |
| `--gpu`                 | -                     | `auto`        | GPU backend: `auto`, `jtop`, `tegra`, `nvidia`, `none`                         |
| `--lowstate-topic`      | -                     | `rt/lowstate` | Lowstate topic (e.g., `rt/lf/lowstate` for low-rate mirror)                            |
| `--no-robot`            | -                     | -               | Monitor host metrics only                                                                |
| `--demo`                | -                     | -               | Generate synthetic robot telemetry                                                       |
| `--json` / `--wait N` | -                     | `2s`          | Collect for `N` seconds, output JSON, and exit                                         |

> **Tip**: Set `UNITREETOP_SDK=system` to use your system-installed `unitree_sdk2py` instead of the bundled submodule.

### Controls & Pages

- **Navigation**: `1`-`8`, `Left`/`Right`, `Tab`, or mouse click on the top bar. (`q` / `Esc` to quit, `p` to pause).
- **Refresh Rate**: `+` / `-` adjusts the current page's rate (`JOINTS` & `IMU` default to **50 Hz**; other pages default to **1 Hz**).
- **Page Shortcuts**:
  - `1` **all**: Overview of CPU, memory, GPU, power, robot status, battery, IMU, and joints.
  - `2` **cpu**: Per-core load/clocks and process list (`s` to cycle sort: CPU / Mem / PID).
  - `3` **gpu**: GPU clocks, power rails, thermals, fan, `nvpmodel`, and hardware engines.
  - `4` **mem**: Memory/swap history and robot NIC bandwidth graphs.
  - `5` **joints**: Full joint telemetry (`Up`/`Down` to select joint for history graph; `a` to toggle inactive slots).
  - `6` **imu**: Orientation, rates, acceleration, `SportModeState`, foot forces, and remote inputs.
  - `7` **power**: Detailed BMS metrics, individual cell voltages, and power graphs.
  - `8` **info**: Software versions, active SDK path, and all discovered DDS topics (`Up`/`Down` to scroll).

## Python API

`unitreetop` exposes a `jtop`-like context manager for scripting and logging:

```python
from unitreetop import UnitreeTop

with UnitreeTop(interface="eth1") as ut:
    while ut.ok():
        r = ut.robot
        print(f"CPU: {ut.cpu['total']}% | SOC: {r.battery.soc}% | RPY: {r.imu.rpy}")
        for m in r.active_motors:
            if m.temp > 70:
                print(f"Warning: {m.name} at {m.temp} C")
```

Access ring-buffer history via `ut.history.get(key)` (e.g., `cpu`, `ram`, `gpu0`, `board_power`, `roll`, `bat_power`, `q0`, `tau0`).

## Troubleshooting

| Issue                                       | Solution                                                                                                                                                     |
| :------------------------------------------ | :----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Stuck at `waiting for rt/lowstate`        | Pass `-i <iface>` explicitly; verify the NIC has a `192.168.123.x` IP, `-d` matches the robot's domain, and UDP multicast isn't blocked by a firewall. |
| `CycloneDDS library could not be located` | Build CycloneDDS 0.10.x and export `CYCLONEDDS_HOME=<install_prefix>`.                                                                                     |
| `No module named unitree_sdk2py`          | Run `git submodule update --init` to pull the bundled SDK.                                                                                                 |
| B2 detected as Go2                          | Both share identical DDS message layouts; pass `-r b2` (or `-r b2w`).                                                                                    |
| Bad colors or broken box characters         | Ensure `TERM=xterm-256color` and use a Nerd Font / Unicode-complete monospace font.                                                                        |
| High CPU usage                              | Lower the refresh rate with `-` or switch to the `all` page (1 Hz) for background monitoring.                                                            |

## Known Limitations

- **Read-only**: Never publishes commands to the robot.
- **Single robot**: Monitors one DDS domain/interface per instance.
- **G1 / H1-2 BMS**: Battery scaling (mV / mA) is inferred from SDK IDL definitions and falls back to motor bus voltage if no `BmsState_` topic is present.

## Development & Architecture

See [docs/architecture.md](docs/architecture.md) for internals and instructions on adding new robot models or UI pages.

To test the full DDS pipeline locally without hardware:

```bash
python3 tools/fake_robot.py --family hg -d 1 -i lo &
unitreetop -d 1 -i lo
```
