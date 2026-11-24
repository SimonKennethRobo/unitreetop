# Architecture

**English** | [中文](architecture.zh-CN.md)

This guide covers module layout, threading, DDS details and how to extend unitreetop. It is meant for anyone changing the code.

## Data flow

```
                 ┌──────────────────────── UnitreeTop (core/__init__.py) ────────────────────────┐
                 │                                                                               │
 psutil ────────▶│ SystemStats.read()  ─┐                                                        │
 jtop / sysfs ──▶│ GpuBackend.read()   ─┼─ utop-sys thread (--interval, 0.5 s) ─▶ stats, gpu_stats │
 NVML / smi ────▶│                      ┘                                     │                  │
                 │                                                            ▼                  │
 DDS ──────────▶ │ RobotLink.snapshot() ── utop-robot thread (robot_hz) ──▶ robot: RobotState    │
 (rt/lowstate …) │                                                            │                  │
                 │                                  History (ring buffers, 240 samples) ◀────────┘
                 └───────────────────────────────────────────────────────────────────────────────┘
                                                      │ read
                                                      ▼
                         UnitreeTopGUI (gui/__init__.py) ── redraw at page hz ── Page.draw()
```

- **`core` does not depend on `gui`.** `--json` and the Python API use `UnitreeTop` directly.
- **No locks between threads.** Collector threads publish new objects by plain attribute assignment
  (`self.robot = st`), which is atomic in Python, so readers always see a complete snapshot.
- **Sampling follows the page.** When the page or its rate changes, the GUI sets `ut.robot_hz = max(--robot-hz, page hz)`.

## Modules

| File | Responsibility |
|---|---|
| `_sdk.py` | puts the bundled `third_party/unitree_sdk2_python` (submodule) ahead of any installed SDK; `UNITREETOP_SDK=system` turns this off |
| `core/system.py` | psutil: CPU (incl. per-core frequency), memory, disk, NIC rates, temperatures, processes |
| `core/gpu.py` | GPU/board backends `JtopBackend`, `TegraBackend`, `NvidiaBackend` (NVML / nvidia-smi) and `NullBackend`; every `read()` returns the same shape |
| `core/models.py` | robot model table (DDS family, joint names, `None` = unused slot), `guess_model()`, remote button names |
| `core/robot.py` | `RobotLink`: DDS discovery, subscriptions and snapshots; `RobotState` dataclasses; 40-byte remote decoding |
| `core/control.py` | teleop: `Backend` implementations (`SportBackend` for go2/b2, `LocoBackend` for g1/h1, `DemoBackend`) and the `Teleop` state machine with its sender thread |
| `core/demo.py` | `DemoLink`: synthetic data with the same interface as `RobotLink` |
| `core/__init__.py` | `UnitreeTop`: the two collector threads, history buffers, `ok()`, `as_dict()` |
| `gui/common.py` | drawing primitives: theme and 256-color mapping, `panel`, `meter`, `smeter`, braille `graph`, `graph_panel` |
| `gui/pages.py` | one class per page; each declares `name`, `hz`, `hz_step`, `hz_min`, `hz_max` |
| `gui/__init__.py` | main loop: timed redraw, keys, header, menu bar |

## DDS details

1. `ChannelFactoryInitialize(domain, iface)` is called only to build the CycloneDDS interface configuration;
   unitreetop then creates its own `DomainParticipant`.
2. A `BuiltinDataReader(DCPSPublication)` keeps collecting the topic name → type name mapping.
3. The lowstate family comes from `--robot` if given. Otherwise unitreetop waits for `rt/lowstate` to be discovered
   (at most 3 s) and falls back to the go family.
4. Subscriptions (`RobotLink._sub`):

   ```python
   DataReader(dp, Topic(dp, name, T),
              qos=Qos(Policy.History.KeepLast(1)),
              listener=Listener(on_data_available=count_only))
   ```

   - The listener only counts arrivals, which gives the topic rate.
   - `snapshot()` calls `reader.take(N=1)` and decodes only the newest sample.
5. Auxiliary topics are matched by **type**, not by name: `SportModeState_`, `unitree_hg BmsState_`, `MainBoardState_`.
   - When several topics share a type, the full-rate topic wins over the `rt/lf/*` low-rate mirror.
   - The discovery thread keeps subscribing to topics that appear later.

> The SDK's `ChannelSubscriber` is not used, for two reasons. It `take()`s and decodes every sample in Python, which
> costs about 70% of a core at 500 Hz. It also prints `[Reader] take sample error` to stdout on shutdown, which corrupts the curses screen.

### Units

All physical quantities in `RobotState` are SI:

| Quantity | Unit | Note |
|---|---|---|
| joint position q | rad | |
| joint velocity dq | rad/s | |
| joint torque tau | N·m | |
| temperature | °C | |
| battery voltage | V | |
| battery current | A | negative = discharging |
| cell voltage | V | |

Raw fields are converted in `RobotLink._fill_go()` and `RobotLink._fill_hg()`:

- go family: BMS `current` and `cell_vol` are mA and mV; pack voltage comes from `power_v`.
- hg family: `bmsvoltage[0]` is treated as mV when it is above 1000.

## Teleop

`UnitreeTop.get_teleop()` builds the controller lazily, the first time the operator arms page ⁹. The SDK RPC client is
therefore never created in a monitoring-only session.

```
 UI thread (CtrlPage.capture)                        utop-teleop thread (Teleop._loop)
 ─────────────────────────────                       ─────────────────────────────────
 Enter ──▶ get_teleop() / arm()                      queued jobs first: "stop" (StopMove if moving),
 w/s a/d q/e ──▶ drive(): steps ±1                     then "sit" / "stand" / "damp"
   (from 0: START_STEPS; clamped to limits)          locked velocity != 0 ? Move every 0.1 s
 space ──▶ stop(): steps = 0, queue "stop"             : one StopMove when it returns to 0
 z/x/p ──▶ action(): clear + queue posture           Move error -> velocity cleared
   (same key < 0.65 s ignored; p sets damped,        every reply -> log (0 ok, 31xx/32xx RPC errors)
    velocity keys locked until x succeeds)
 Esc / page change / quit / SIGHUP ──▶ disarm()
```

Further guarantees:

- `UnitreeTop._robot_loop` disarms when the robot is no longer online.
- `UnitreeTop.close()` (quit, Ctrl-C, SIGHUP, SIGTERM) disarms and waits for the final StopMove.
- `stop()` and `disarm()` are no-ops unless armed, so a session that never armed sends nothing.

The GUI gives pages two hooks for this:

- `Page.capture(ch)` runs **before** the global key handling. The armed control page uses it to own `q`, `p` and `Esc`, and sets
  `modal`, which hides "pause/quit" in the menu bar.
- `Page.on_leave()` runs on every page change.

To support a new robot API, subclass `Backend` with `move(vx, vy, wz)`, `stop_move()`, `action(name)` for
`sit`/`stand`/`damp`, plus `labels` and `limits`, and return it from `make_backend()`.

## Rendering

- **Colors.** Hex colors in `common.THEME` and `common.GRADIENTS` are mapped at runtime to the nearest xterm-256
  entry, or to the 8 basic colors on poor terminals.
  - Color pairs are allocated lazily and cached. Python's `color_pair()` can only encode 255 pairs, so each gradient has 12 steps.
- **Braille graphs.** Each character cell holds 2 samples across and 4 levels up. Cells come from a 5×5 lookup table,
  and each row is colored along the gradient by its height.
- **Performance.** `put()` is the hottest function, so the screen size is read once per frame (`set_dims`). `meter`
  batches same-colored cells into one `addstr`. The JOINTS page takes about 4 ms per frame on an Orin NX.
- **Repair.** `redrawwin()` runs every 2 s to undo kernel and syslog broadcasts written over the screen.

## Extending

### Add a robot model

1. Add an entry to `MODELS` in `core/models.py`:

   ```python
   "x1": RobotModel("x1", "X1", GO, ["joint0", "joint1", None, "joint3"], "quadruped"),
   ```

   - The list index is the `motor_state` slot; `None` marks an unused slot.
   - The third argument is the DDS family: `GO` or `HG`.
2. For auto-detection, add a rule to `guess_model()`, based on which motor slots carry data.
3. The CLI's `-r` choices pick the new model up automatically.

### Add a message type

1. Define the type name in `core/robot.py`, e.g. `T_XXX = "unitree_go::msg::dds_::Xxx_"`.
2. Register it in the `roles` map of `_subscribe_extra()` and import its IDL class there.
3. Read `self._latest["<role>"].last` in `snapshot()` and copy what you need into a `RobotState` field.
   Add the field to the dataclass as well.

### Add a page

1. Subclass `Page` in `gui/pages.py`:
   - set `name`, and optionally `hz`, `hz_step`, `hz_min`, `hz_max`;
   - implement `draw(win, y, x, h, w)`, and optionally `key(ch)` and `help()`;
   - draw panels with `panel()`, which returns the inner rectangle `(iy, ix, ih, iw)`.
2. Append the class to `PAGES`; its position is its number.
3. Add its name to `PAGE_NAMES` in `__main__.py` so `-p` can select it.
4. If the page needs graphs, record values with `history.push(key, value)` in `UnitreeTop._robot_loop()` or `_sys_loop()`.

## Testing

```bash
python3 -m unitreetop --demo -r g1                       # UI only, no DDS
python3 tools/fake_robot.py --family go -d 7 -i lo &     # go-family DDS path incl. sportmodestate + fake sport RPC
python3 -m unitreetop -d 7 -i lo --json --wait 5
python3 -m unitreetop -d 7 -i lo -p ctrl                 # control page against the fake RPC service
```
