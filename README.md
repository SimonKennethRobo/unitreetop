# unitreetop

**English** | [中文](README.zh-CN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![Platform](https://img.shields.io/badge/platform-Jetson%20%7C%20Linux-lightgrey)

**unitreetop** is a terminal monitor for Unitree robots, inspired by
[jetson_stats / jtop](https://github.com/rbonghi/jetson_stats) and styled after [btop](https://github.com/aristocratos/btop).

Next to the usual host metrics (CPU, GPU, memory, temperatures, power), it shows the robot's own state live over
[`unitree_sdk2py`](https://github.com/unitreerobotics/unitree_sdk2_python) (CycloneDDS): **joints, battery/BMS, IMU,
foot force, wireless remote and sport state**. It is read-only and never sends a command.

![all](docs/screenshot-all.png)
![joints](docs/screenshot-joints.png)

<sub>Real Go2 (terminal capture rendered to PNG).</sub>

---

## Contents

- [Features](#features)
- [Supported robots](#supported-robots)
- [Quick start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
- [Pages](#pages)
- [JSON output and Python API](#json-output-and-python-api)
- [How it works](#how-it-works)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)
- [Development](#development)
- [License and credits](#license-and-credits)

## Features

- **Host**: per-core CPU load and frequency, load average, memory/swap/disk, network rates, process list, temperatures.
- **GPU / board**: on Jetson via jtop: GPU load and frequency, power rails (VDD_IN …), fan, nvpmodel, jetson_clocks,
  hardware engines, CUDA/TensorRT versions. Desktop GPUs via NVML or `nvidia-smi`.
- **Robot state** (DDS):
  - joints: q (rad/°), dq, tau, temperature, mode, lost-packet counter or error bits, with q/dq/tau history of the selected joint;
  - battery: SOC, voltage, current, power, cycles, SOH, BMS temperatures, every cell voltage and the cell spread;
  - IMU: RPY, quaternion, angular rate, acceleration and its norm, IMU temperature;
  - foot force, wireless remote sticks and buttons, sport mode state (sportmodestate);
  - every DDS topic on the network with its type, and the measured rate of each subscribed topic.
- **Auto-detection**: robot family and model are detected through DDS discovery; the NIC on the robot network
  (192.168.123.x) is picked automatically.
- **btop look**: rounded panels, superscript hotkeys, `■` gradient meters, braille graphs, 256-color theme.
- **Per-page refresh rate**: change it with `+`/`-`. JOINTS/IMU default to 50 Hz, all other pages to 1 Hz.
- **Low overhead**: about 8% of one core on a Go2's Orin NX at 1 Hz.
- **Self-contained**: the official Python SDK is bundled as a git submodule.
- **Extras**: one-shot JSON output, a Python API, a demo mode and a fake DDS publisher for testing.

## Supported robots

| Model | DDS family | Joints | Battery source | Status |
|---|---|---|---|---|
| Go2 | `unitree_go` | 12 | `LowState_.bms_state` | ✅ tested on a real robot |
| Go2-W | `unitree_go` | 16 (incl. wheels) | `LowState_.bms_state` | implemented from the SDK definitions |
| B2 / B2-W | `unitree_go` | 12 / 16 | `LowState_.bms_state` | implemented from the SDK definitions; pass `-r b2` / `-r b2w` |
| H1 | `unitree_go` | 19 | `LowState_.bms_state` | implemented from the SDK definitions |
| G1 (23/29 DoF) | `unitree_hg` | 23 / 29 | `BmsState_` topic | tested against simulated DDS data |
| H1-2 | `unitree_hg` | 27 | `BmsState_` topic | tested against simulated DDS data |

Joint names and order come from the `unitree_sdk2_python` low-level examples (`example/*/low_level`).

## Quick start

On the robot's Jetson (Go2 expansion dock, or PC2 on G1/H1):

```bash
git clone --recurse-submodules git@github.com:SimonKennethRobo/unitreetop.git ~/Apps/unitreetop
ln -s ~/Apps/unitreetop/bin/unitreetop ~/.local/bin/unitreetop
unitreetop
```

To try the interface without a robot:

```bash
python3 -m unitreetop --demo -r g1
```

## Installation

### Requirements

| Dependency | Notes |
|---|---|
| Python ≥ 3.8 | the Go2's Ubuntu 20.04 ships Python 3.8 |
| `psutil` | host statistics |
| `unitree_sdk2py` | **bundled as a git submodule** (`third_party/unitree_sdk2_python`), nothing to install |
| `cyclonedds==0.10.x` | DDS Python binding used by the SDK (normally already present on the robot's Jetson) |
| `jetson-stats` (optional) | richer GPU/power/fan data on Jetson; needs `jtop.service` running |
| `nvidia-ml-py` (optional) | desktop NVIDIA GPUs; falls back to `nvidia-smi` |

### unitree_sdk2py (bundled submodule)

[unitree_sdk2_python](https://github.com/unitreerobotics/unitree_sdk2_python) is pinned as a submodule at
`third_party/unitree_sdk2_python`. At startup unitreetop puts that copy first on `sys.path`, so a checkout runs as is:

```bash
git clone --recurse-submodules <repo>        # fresh clone
git submodule update --init                  # existing clone without the submodule
```

- **Use your installed SDK instead** (for example a patched copy on the robot): set `UNITREETOP_SDK=system`.
- **Check which SDK is in use**: the `sdk` line on the INFO page shows the actual path.
- **CycloneDDS binding**: the `cyclonedds` Python package is still required (`pip3 install cyclonedds==0.10.2`).
  If it cannot find the CycloneDDS C library, build cyclonedds 0.10.x and `export CYCLONEDDS_HOME=<install prefix>`.

### Option 1: run the script directly (recommended)

`bin/unitreetop` runs straight from the source tree: no pip install needed, and a `git pull` takes effect immediately.

```bash
ln -s "$PWD/bin/unitreetop" ~/.local/bin/unitreetop
ln -s "$PWD/bin/unitreetop" ~/.local/bin/untop      # optional short name
```

Make sure `~/.local/bin` is on your `PATH`; Ubuntu's default `~/.profile` adds it.

### Option 2: pip

```bash
pip3 install -e .              # provides the unitreetop / untop commands
pip3 install -e ".[jetson]"    # also installs jetson-stats
```

An editable install keeps using the bundled SDK. A non-editable install falls back to an installed `unitree_sdk2py`.

## Usage

```bash
unitreetop                       # auto-select the NIC with a 192.168.123.x address
unitreetop -i eth1               # explicit NIC (Go2 expansion dock: usually eth1)
unitreetop -i enp3s0 -r g1       # external PC cabled to a G1, model forced
unitreetop -p joints             # open the JOINTS page directly
unitreetop --json                # print one JSON snapshot and exit
unitreetop --demo -r h1_2        # synthetic data, no robot or DDS needed
unitreetop -d 1 -i lo            # unitree_mujoco simulator (domain 1)
```

### Command line

| Option | Default | Description |
|---|---|---|
| `-i`, `--interface` | auto | NIC connected to the robot. Defaults to the NIC with a 192.168.123.x address, else CycloneDDS auto-selection |
| `-d`, `--domain` | `0` | DDS domain id (robot: 0, unitree_mujoco: 1) |
| `-r`, `--robot` | `auto` | `auto` / `go2` / `go2w` / `b2` / `b2w` / `h1` / `g1` / `h1_2`; selects joint names and layout |
| `--lowstate-topic` | `rt/lowstate` | or `rt/lf/lowstate` (low-rate mirror) |
| `--gpu` | `auto` | GPU/board backend: `auto` / `jtop` / `tegra` / `nvidia` / `none` |
| `-p`, `--page` | `all` | start page: `all` `cpu` `gpu` `mem` `joints` `imu` `power` `info` |
| `--interval` | `0.5` | host statistics period [s] |
| `--robot-hz` | `20` | minimum robot snapshot rate (fast pages raise it) |
| `--no-robot` | | host only |
| `--demo` | | synthetic robot data |
| `--json` / `--wait N` | / `2` | collect for N seconds, print one JSON snapshot, exit |

| Environment variable | Effect |
|---|---|
| `UNITREETOP_IFACE` | default for `-i` |
| `UNITREETOP_DOMAIN` | default for `-d` |
| `UNITREETOP_SDK=system` | use the installed `unitree_sdk2py` instead of the bundled one |

### Keys

| Key | Action |
|---|---|
| `1`–`8`, `←` `→` `Tab`, mouse click on the menu | switch page |
| `+` / `-` | refresh rate of the current page |
| `p` | pause / resume |
| `q` / `Esc` | quit |
| `↑` `↓` / `PgUp` `PgDn` (JOINTS) | select a joint; the graphs below show its history |
| `a` (JOINTS) | show / hide motor slots without data |
| `s` (CPU) | process sort: CPU → memory → PID |
| `↑` `↓` (INFO) | scroll the DDS topic list |

### Refresh rate

Each page keeps its own refresh rate. The menu bar shows the current value (`+- 50Hz`) and adds the measured frame rate
when the terminal cannot keep up, e.g. `50Hz(~38)`.

| Page | Default | Step | Range |
|---|---|---|---|
| JOINTS, IMU | 50 Hz | 10 Hz | 10–200 Hz |
| ALL, CPU, GPU, MEM, POWER, INFO | 1 Hz | 1 Hz | 1–10 Hz |

Robot data is sampled at the rate of the current page (at least `--robot-hz`), so a 50 Hz page really shows 50 Hz
data. Graphs keep the last 240 samples, which is about 4.8 s at 50 Hz.

**CPU cost** (Go2 Orin NX, share of one core): about 8% at 1 Hz and about 48% at 50 Hz, roughly proportional to the rate.

The terminal needs 256 colors (`xterm-256color`, `tmux-256color`, …); otherwise unitreetop falls back to 8 colors.

## Pages

| Page | Content |
|---|---|
| ¹ **all** | CPU graph and per-core load; memory/swap/disk/GPU meters, board power and temperatures; robot status, battery, RPY, foot force, remote; all joints |
| ² **cpu** | CPU graph, per-core load and frequency, process list (refreshed every 2 s, scanned only while this page is open) |
| ³ **gpu** | per-GPU load graph and clocks; temperatures, power rails with a board power graph, board info (model, L4T, CUDA, TensorRT, nvpmodel, fan, engines) |
| ⁴ **mem** | memory graph, NIC addresses and rates; download/upload graph of the robot NIC |
| ⁵ **joints** | mode, q (rad/°), dq, tau, temperature for every joint, plus lost packets (go family) or second temperature, voltage and error bits (hg family); signed q and tau meters; q/dq/tau graphs of the selected joint |
| ⁶ **imu** | RPY and quaternion, angular rate, acceleration and its norm; sportmodestate (when published), foot force, remote sticks and buttons; roll/pitch/gyro-z graphs |
| ⁷ **power** | battery SOC, voltage, current, power, cycles, SOH, BMS temperatures, cell voltages and spread; robot board (bus voltage, NTCs, fans); battery power, battery voltage and compute board power graphs |
| ⁸ **info** | host and software versions; robot model, DDS family, firmware, tick, SDK in use, rate of each subscribed topic; all discovered DDS topics (● = subscribed) |

Joint temperatures turn yellow at 60 °C and red at 75 °C.

## JSON output and Python API

### JSON

```bash
unitreetop --json --wait 3 | jq '.robot.battery'
```

The snapshot has three sections:

- `system`: cpu, mem, swap, disk, net, temp, uptime
- `gpu`: gpus, power, temp, fan, info, engines
- `robot`: status, model, family, rates, motors[], imu, battery, sport, remote, foot_force, board

### Python API (same style as `jtop`)

```python
from unitreetop import UnitreeTop

with UnitreeTop(interface="eth1") as ut:       # same options as the CLI: domain, robot, demo, gpu, ...
    while ut.ok():                             # blocks until fresh data arrives
        r = ut.robot                           # RobotState
        print(ut.cpu["total"], ut.gpu, r.battery.soc, r.imu.rpy)
        for m in r.active_motors:              # Motor: index name q dq tau temp ...
            if m.temp > 70:
                print("hot joint", m.name, m.temp)
```

`ut.history.get(key)` returns the ring buffers behind the graphs:

| Group | Keys |
|---|---|
| host | `cpu`, `cpu<N>`, `ram`, `gpu<N>`, `board_power`, `rx:<iface>`, `tx:<iface>` |
| IMU | `roll`, `pitch`, `yaw`, `gx`, … |
| battery | `bat_power`, `bat_voltage` |
| joints | `q<N>`, `dq<N>`, `tau<N>`, `temp<N>` |

## How it works

See [docs/architecture.md](docs/architecture.md) for details.

- **Topic discovery.** unitreetop reads the DDS builtin `DCPSPublication` topic to get the type of every topic on the network.
  - The type of `rt/lowstate` selects the family: `unitree_go::…::LowState_` means Go2/B2/H1, `unitree_hg::…::LowState_` means G1/H1-2.
  - Battery (`unitree_hg BmsState_`), main board (`MainBoardState_`) and sport state (`SportModeState_`) topics are found by type, not by hard-coded names.
  - Topics that appear later, such as sport mode being switched on, are subscribed on the fly.
- **Model detection.** The model is guessed from which motor slots carry data.
  - go family: 12 slots → Go2, 16 → Go2-W, 17 or more → H1.
  - hg family: the slot pattern tells G1 from H1-2.
- **Cheap reception.** lowstate is published at 500 Hz. Each reader keeps only the newest sample (`KeepLast(1)`); its
  callback only counts arrivals for the Hz display, and the newest sample is decoded only when the UI needs it.
  Decoding every sample in Python costs about 70% of a core; this design costs about 5%.
- **GPU backends.** On Jetson unitreetop uses jtop, falling back to tegra sysfs; on desktops it uses NVML or `nvidia-smi`.
- **Terminal repair.** Kernel and syslog broadcasts on the robot's Jetson write straight to the tty and corrupt the
  screen, so the whole screen is repainted every 2 s.

## Troubleshooting

| Symptom | Fix |
|---|---|
| stuck at `waiting for rt/lowstate` | pass `-i` with the NIC that reaches the robot; check that it has an address in 192.168.123.0/24 and that `-d` matches the robot's domain. On an external PC, also check the firewall for blocked UDP multicast |
| `DDS init failed: … CycloneDDS library could not be located` | the `cyclonedds` Python package cannot find its C library: build CycloneDDS 0.10.x and set `CYCLONEDDS_HOME` |
| `No module named unitree_sdk2py` | the submodule is not checked out: run `git submodule update --init` |
| wrong model (e.g. a B2 shown as Go2) | force it with `-r` |
| `no GPU backend` on the GPU page | Jetson: install jetson-stats and start `jtop.service`; desktop: make sure `nvidia-smi` works |
| only 8 colors / squares render badly | set `TERM=xterm-256color` and use a monospace font with Unicode coverage |
| high CPU on a 50 Hz page | press `-` to lower that page's rate; leave long-running sessions on ALL (1 Hz) |
| G1 battery values look wrong | see [Known limitations](#known-limitations); issues with `unitreetop --json` output are welcome |

## Known limitations

- Go2 and B2 (and Go2-W and B2-W) publish identical lowstate layouts and cannot be told apart, so pass `-r b2` for a B2.
- G1/H1-2 BMS units (voltage in mV, current in mA) are inferred from the SDK IDL and not yet verified on a real
  robot. Without a BMS topic, the battery voltage is estimated from the motor bus voltage.
- Read-only by design: no commands are sent.
- One robot (one DDS domain and NIC) per instance.

## Development

```
unitreetop/
├── bin/unitreetop                    # launcher, no install needed
├── third_party/unitree_sdk2_python   # official Python SDK (git submodule, pinned)
├── tools/fake_robot.py               # fake DDS publisher (go / hg family)
├── unitreetop/
│   ├── __main__.py                   # CLI entry point
│   ├── _sdk.py                       # bundled SDK on sys.path
│   ├── core/                         # collectors: system / gpu / robot (DDS) / models / demo
│   └── gui/                          # curses UI: common (primitives, theme) / pages / main loop
└── docs/architecture.md              # architecture and extension guide
```

Test the DDS path without a robot:

```bash
python3 tools/fake_robot.py --family hg -d 1 -i lo &    # fake G1: 29 joints + rt/lf/bmsstate
unitreetop -d 1 -i lo
```

For adding robot models or pages, see [docs/architecture.md](docs/architecture.md#extending).

## License and credits

Released under the [MIT License](LICENSE). The bundled
[unitree_sdk2_python](https://github.com/unitreerobotics/unitree_sdk2_python) keeps its own BSD-3-Clause license.

- [jetson_stats](https://github.com/rbonghi/jetson_stats) by rbonghi: the jtop idea and the Jetson data source
- [btop](https://github.com/aristocratos/btop) by aristocratos: UI style and default color theme
- [unitree_sdk2_python](https://github.com/unitreerobotics/unitree_sdk2_python): DDS message definitions and joint layouts

Not affiliated with Unitree Robotics or NVIDIA.
