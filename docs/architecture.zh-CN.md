# 架构说明

[English](architecture.md) | **中文**

本文介绍 unitreetop 的模块划分、线程模型、DDS 细节和扩展方法，读者对象是想修改或扩展本项目的开发者。

## 数据流

```
                 ┌──────────────────────── UnitreeTop (core/__init__.py) ────────────────────────┐
                 │                                                                               │
 psutil ────────▶│ SystemStats.read()  ─┐                                                        │
 jtop / sysfs ──▶│ GpuBackend.read()   ─┼─ utop-sys 线程 (--interval，默认 0.5 s) ─▶ stats, gpu_stats
 NVML / smi ────▶│                      ┘                                     │                  │
                 │                                                            ▼                  │
 DDS ──────────▶ │ RobotLink.snapshot() ── utop-robot 线程 (robot_hz) ──▶ robot: RobotState      │
 (rt/lowstate …) │                                                            │                  │
                 │                                    History (环形缓冲, 240 点) ◀──────────────┘
                 └───────────────────────────────────────────────────────────────────────────────┘
                                                      │ 读取
                                                      ▼
                         UnitreeTopGUI (gui/__init__.py) ── 按当前页 hz 重绘 ── Page.draw()
```

- **`core` 不依赖 `gui`。** 命令行的 `--json` 和 Python API 直接使用 `UnitreeTop`。
- **线程之间不加锁。** 采集线程每次把新对象整体赋给属性（例如 `self.robot = st`），读取方拿到的是某一时刻的完整快照；
  Python 中属性赋值是原子的。
- **采样频率跟随页面。** GUI 切换页面或调节刷新率时，把 `ut.robot_hz` 设为 `max(--robot-hz, 页面 hz)`。

## 模块

| 文件 | 职责 |
|---|---|
| `core/system.py` | psutil：CPU（含每核频率）、内存、磁盘、网卡速率、温度、进程表 |
| `core/gpu.py` | GPU/板卡后端：`JtopBackend`、`TegraBackend`、`NvidiaBackend`（NVML / nvidia-smi）、`NullBackend`，所有后端的 `read()` 返回相同结构 |
| `core/models.py` | 机器人型号表（DDS 家族、关节名，`None` 表示空槽位）、`guess_model()`、遥控器按键定义 |
| `core/robot.py` | `RobotLink`：DDS 发现、订阅与快照；`RobotState` 等数据类；遥控器 40 字节数据解析 |
| `core/control.py` | 键盘控制：`Backend` 的各个实现（go2/b2 用 `SportBackend`，g1/h1 用 `LocoBackend`，以及 `DemoBackend`），和 `Teleop` 状态机及其发送线程 |
| `core/demo.py` | `DemoLink`：合成数据，接口与 `RobotLink` 相同 |
| `_sdk.py` | 让内置的 `third_party/unitree_sdk2_python`（submodule）优先于系统安装的 SDK；`UNITREETOP_SDK=system` 可关闭 |
| `core/__init__.py` | `UnitreeTop`：组织两个采集线程，管理历史缓冲，提供 `ok()` 和 `as_dict()` |
| `gui/common.py` | 绘图原语：主题与 256 色映射、`panel`、`meter`、`smeter`、`graph`（braille）、`graph_panel` |
| `gui/pages.py` | 各页面类，每个类声明自己的 `name`、`hz`、`hz_step`、`hz_min`、`hz_max` |
| `gui/__init__.py` | 主循环：定时重绘、按键处理、顶栏、底栏菜单 |

## DDS 细节

1. 调用 `ChannelFactoryInitialize(domain, iface)`，只用它生成 CycloneDDS 的网卡配置；之后自己创建 `DomainParticipant`。
2. 用 `BuiltinDataReader(DCPSPublication)` 持续收集话题名到类型名的映射。
3. 确定 lowstate 的家族：`--robot` 已指定型号时直接使用；否则等到发现 `rt/lowstate`，最多等 3 秒，之后默认为 go 家族。
4. 订阅方式（`RobotLink._sub`）：

   ```python
   DataReader(dp, Topic(dp, name, T),
              qos=Qos(Policy.History.KeepLast(1)),
              listener=Listener(on_data_available=count_only))
   ```

   - 回调只做计数，用于计算话题频率。
   - `snapshot()` 中调用 `reader.take(N=1)`，只解析最新的一条。

5. 辅助话题按**类型**匹配，不写死话题名：`SportModeState_`、`unitree_hg BmsState_`、`MainBoardState_`。
   - 同一类型有多个话题时，优先选全速话题，而不是 `rt/lf/*` 低频镜像。
   - 发现线程会持续补订阅后来才出现的话题。

> 不使用 SDK 的 `ChannelSubscriber`，原因有两个：它对每条消息都会 `take()` 并在 Python 中解析（500 Hz 时约占 70% 单核）；
> 关闭时还会往 stdout 打印 `[Reader] take sample error`，弄乱 curses 画面。

### 单位约定

`RobotState` 中的物理量统一使用 SI 单位：

| 物理量 | 单位 | 备注 |
|---|---|---|
| 关节位置 q | rad | |
| 关节速度 dq | rad/s | |
| 关节力矩 tau | N·m | |
| 温度 | °C | |
| 电池电压 | V | |
| 电池电流 | A | 负值表示放电 |
| 电芯电压 | V | |

原始字段的换算在 `RobotLink._fill_go()` 和 `RobotLink._fill_hg()` 中完成：
- go 家族：BMS 的 `current` 和 `cell_vol` 单位是 mA、mV，电压取 `power_v`。
- hg 家族：`bmsvoltage[0]` 大于 1000 时按 mV 处理。

## 键盘控制

`UnitreeTop.get_teleop()` 采用延迟创建：直到操作者第一次在第 ⁹ 页解锁时才创建控制器。因此纯监控的会话里根本不会创建 SDK 的 RPC 客户端。

```
 界面线程（CtrlPage.capture）                        utop-teleop 线程（Teleop._loop）
 ─────────────────────────────                       ─────────────────────────────────
 Enter ──▶ get_teleop() / arm()                      先执行队列中的任务："stop"（移动中则发 StopMove），
 w/s a/d q/e ──▶ drive()：档位 ±1                      然后是 "sit" / "stand" / "damp"
   （从 0 开始时跳到 START_STEPS；按上限限幅）       锁定速度不为 0 时：每 0.1 s 发一次 Move
 space ──▶ stop()：档位清零，加入 "stop"               回到 0 时：只发一次 StopMove
 z/x/p ──▶ action()：先清零，再加入姿态指令          Move 失败：清零速度
   （同一按键 0.65 s 内重复则忽略；p 置 damped，     每条返回都写入日志（0 成功，31xx/32xx 为 RPC 错误）
    之后速度键被锁住，直到 x 成功）
 Esc / 切换页面 / 退出 / SIGHUP ──▶ disarm()
```

其它保证：

- `UnitreeTop._robot_loop` 发现机器人不在线时会自动上锁。
- `UnitreeTop.close()`（退出、Ctrl-C、SIGHUP、SIGTERM）会上锁并等待最后一条 StopMove 发出。
- `stop()` 和 `disarm()` 在未解锁时什么都不做，所以从未解锁过的会话不会发出任何指令。

界面为此给页面提供了两个钩子：

- `Page.capture(ch)` 在全局按键处理**之前**运行。解锁状态下，控制页用它接管 `q`、`p`、`Esc`，并设置 `modal`，让菜单栏不再显示"暂停/退出"。
- `Page.on_leave()` 在每次切换页面时运行。

要支持新的机器人接口，只需继承 `Backend`，实现 `move(vx, vy, wz)`、`stop_move()`，以及处理 `sit`/`stand`/`damp` 的 `action(name)`，
并提供 `labels` 和 `limits`，然后在 `make_backend()` 中返回它。

## 界面绘制

- **配色**：`common.THEME` 和 `common.GRADIENTS` 中的十六进制颜色，在运行时映射到最接近的 xterm-256 颜色；只有 8 色时映射到 8 种基本色。
  - 颜色对按需分配并缓存。Python 的 `color_pair()` 最多只能编码 255 个颜色对，所以每个渐变只取 12 级。
- **braille 曲线**：每个字符单元横向容纳 2 个采样、纵向容纳 4 级。字符通过 5×5 的查找表生成；每行颜色按高度沿渐变取值。
- **性能**：`put()` 是调用最多的函数，每帧只读一次屏幕尺寸（`set_dims`）；`meter` 把同色的连续格子合并成一次 `addstr`。
  在 Orin NX 上，JOINTS 页每帧绘制约 4 ms。
- **画面恢复**：每 2 秒调用一次 `redrawwin()`，用来修复内核或 syslog 广播造成的花屏。

## 扩展

### 添加机器人型号

1. 在 `core/models.py` 的 `MODELS` 中添加一项：

   ```python
   "x1": RobotModel("x1", "X1", GO, ["joint0", "joint1", None, "joint3"], "quadruped"),
   ```

   - 列表的下标就是 `motor_state` 的槽位，`None` 表示该槽位未使用。
   - 第三个参数是 DDS 家族：`GO` 或 `HG`。

2. 如需自动识别，在 `guess_model()` 中加入判断规则（依据是哪些电机槽位有数据）。
3. 命令行的 `-r` 选项会自动包含新型号。

### 添加新的消息类型

1. 在 `core/robot.py` 中定义类型名常量（例如 `T_XXX = "unitree_go::msg::dds_::Xxx_"`）。
2. 在 `_subscribe_extra()` 的 `roles` 中登记这个类型，并在同一函数里导入对应的 IDL 类。
3. 在 `snapshot()` 中通过 `self._latest["<role>"].last` 读取数据，写入 `RobotState` 的字段（新字段要同时加到对应的 dataclass 里）。

### 添加页面

1. 在 `gui/pages.py` 中继承 `Page`：
   - 设置 `name`；如有需要，设置 `hz`、`hz_step`、`hz_min`、`hz_max`。
   - 实现 `draw(win, y, x, h, w)`；可选实现 `key(ch)` 和 `help()`。
   - 用 `panel()` 画面板，它会返回内部区域 `(iy, ix, ih, iw)`。
2. 把新类加入 `PAGES` 列表，页面编号就是它在列表中的位置。
3. 在 `__main__.py` 的 `PAGE_NAMES` 中加上页面名，`-p` 选项才能选到它。
4. 如果页面需要曲线数据，在 `UnitreeTop._robot_loop()` 或 `_sys_loop()` 中用 `history.push(key, value)` 记录。

## 测试

```bash
python3 -m unitreetop --demo -r g1                       # 不依赖 DDS 的界面测试
python3 tools/fake_robot.py --family go -d 7 -i lo &     # 测试 go 家族 DDS 路径（含 sportmodestate）
python3 -m unitreetop -d 7 -i lo --json --wait 5
```
