# unitreetop

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![Platform](https://img.shields.io/badge/platform-Jetson%20%7C%20Linux-lightgrey)

**unitreetop** 是面向宇树（Unitree）机器人的终端监控工具，灵感来自
[jetson_stats / jtop](https://github.com/rbonghi/jetson_stats)，界面风格参照 [btop](https://github.com/aristocratos/btop)。

除了 CPU、GPU、内存、温度、功耗等常规指标，它还通过 [`unitree_sdk2py`](https://github.com/unitreerobotics/unitree_sdk2_python)（CycloneDDS）
实时显示机器人自身状态：**关节、电池 BMS、IMU、足端力、遥控器、运动状态**。它只读取数据，不发送任何控制命令。

![all](docs/screenshot-all.png)
![joints](docs/screenshot-joints.png)

<sub>Go2 真机画面（终端截图转 PNG）。</sub>

---

## 目录

- [功能](#功能)
- [支持的机器人](#支持的机器人)
- [快速开始](#快速开始)
- [安装](#安装)
- [使用](#使用)
- [页面说明](#页面说明)
- [JSON 输出与 Python API](#json-输出与-python-api)
- [工作原理](#工作原理)
- [故障排查](#故障排查)
- [已知限制](#已知限制)
- [开发与测试](#开发与测试)
- [许可证与致谢](#许可证与致谢)

## 功能

- **主机监控**：各核 CPU 负载与频率、负载均值、内存/交换/磁盘、网卡速率、进程表、温度。
- **GPU / 板卡**：在 Jetson 上通过 jtop 获取 GPU 负载与频率、功耗轨（VDD_IN 等）、风扇、nvpmodel、jetson_clocks、
  各硬件引擎以及 CUDA/TensorRT 版本；桌面 GPU 用 NVML 或 `nvidia-smi`。
- **机器人状态**（通过 DDS）：
  - 关节：q（rad/°）、dq、tau、温度、模式、丢包计数或错误码，选中关节的 q/dq/tau 历史曲线；
  - 电池：SOC、电压、电流、功率、循环次数、SOH、BMS 温度、每节电芯电压与压差；
  - IMU：RPY、四元数、角速度、加速度及其模长、IMU 温度；
  - 足端力、遥控器摇杆与按键、运动模式状态（sportmodestate）；
  - DDS 发现的全部话题及类型、各订阅话题的实际频率。
- **自动识别**：通过 DDS 发现机制判断机器人家族和型号；自动选择机器人内网（192.168.123.x）所在的网卡。
- **btop 风格界面**：圆角面板、上标快捷键、`■` 渐变条、braille 点阵曲线、256 色主题。
- **每页独立刷新率**：用 `+`/`-` 调节；JOINTS/IMU 默认 50 Hz，其余页面默认 1 Hz。
- **低开销**：在 Go2 的 Orin NX 上，1 Hz 页面只占单核约 8%。
- 也可以输出 JSON 快照，或作为 Python 库使用；附带演示模式和 DDS 模拟发布器。

## 支持的机器人

| 型号 | DDS 消息家族 | 关节数 | 电池来源 | 状态 |
|---|---|---|---|---|
| Go2 | `unitree_go` | 12 | `LowState_.bms_state` | ✅ 真机验证 |
| Go2-W | `unitree_go` | 16（含轮） | `LowState_.bms_state` | 按 SDK 定义实现 |
| B2 / B2-W | `unitree_go` | 12 / 16 | `LowState_.bms_state` | 按 SDK 定义实现，需加 `-r b2` / `-r b2w` |
| H1 | `unitree_go` | 19 | `LowState_.bms_state` | 按 SDK 定义实现 |
| G1（23/29 自由度） | `unitree_hg` | 23 / 29 | `BmsState_` 话题 | 用模拟 DDS 数据验证 |
| H1-2 | `unitree_hg` | 27 | `BmsState_` 话题 | 用模拟 DDS 数据验证 |

关节名和顺序取自 `unitree_sdk2_python` 的示例程序（`example/*/low_level`）。

## 快速开始

在机器人的 Jetson 上（Go2 扩展坞或 G1/H1 的 PC2，`unitree_sdk2py` 通常已安装）：

```bash
git clone git@github.com:SimonKennethRobo/unitreetop.git ~/Apps/unitreetop
ln -s ~/Apps/unitreetop/bin/unitreetop ~/.local/bin/unitreetop
unitreetop
```

没有机器人时，可以先用演示数据看看界面：

```bash
python3 -m unitreetop --demo -r g1
```

## 安装

### 依赖

| 依赖 | 说明 |
|---|---|
| Python ≥ 3.8 | Go2 自带的 Ubuntu 20.04 为 Python 3.8 |
| `psutil` | 主机监控 |
| `unitree_sdk2py` + `cyclonedds==0.10.x` | 机器人数据；不在 PyPI 上，见下文 |
| `jetson-stats`（可选） | Jetson 上提供更完整的 GPU/功耗/风扇信息，需要 `jtop.service` 在运行 |
| `nvidia-ml-py`（可选） | 桌面 NVIDIA GPU；不装时退回 `nvidia-smi` |

安装 `unitree_sdk2py`（参见[官方说明](https://github.com/unitreerobotics/unitree_sdk2_python#installation)）：

```bash
git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
cd unitree_sdk2_python && pip3 install -e .
# 若提示找不到 CycloneDDS：先编译安装 cyclonedds 0.10.x，再 export CYCLONEDDS_HOME=<安装目录>
```

### 方式一：直接运行脚本（推荐）

`bin/unitreetop` 直接从源码目录运行，不需要 pip 安装，`git pull` 后立即生效。

```bash
ln -s "$PWD/bin/unitreetop" ~/.local/bin/unitreetop
ln -s "$PWD/bin/unitreetop" ~/.local/bin/untop      # 可选的短命令
```

确认 `~/.local/bin` 在 `PATH` 中（Ubuntu 的 `~/.profile` 默认会加入）。

### 方式二：pip 安装

```bash
pip3 install -e .              # 提供 unitreetop / untop 命令
pip3 install -e ".[jetson]"    # 同时安装 jetson-stats
```

## 使用

```bash
unitreetop                       # 自动选择 IP 为 192.168.123.x 的网卡
unitreetop -i eth1               # 手动指定网卡（Go2 扩展坞的内网口通常是 eth1）
unitreetop -i enp3s0 -r g1       # 外部 PC 网线直连 G1，并指定型号
unitreetop -p joints             # 直接打开 JOINTS 页
unitreetop --json                # 输出一次 JSON 快照后退出
unitreetop --demo -r h1_2        # 演示数据，不需要机器人和 DDS
unitreetop -d 1 -i lo            # 连接 unitree_mujoco 仿真（domain 1）
```

### 命令行参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `-i`, `--interface` | 自动 | 连接机器人的网卡。默认选 IP 为 192.168.123.x 的网卡，找不到时交给 CycloneDDS 自动选择 |
| `-d`, `--domain` | `0` | DDS domain id（真机为 0，unitree_mujoco 默认 1） |
| `-r`, `--robot` | `auto` | `auto` / `go2` / `go2w` / `b2` / `b2w` / `h1` / `g1` / `h1_2`，决定关节命名和布局 |
| `--lowstate-topic` | `rt/lowstate` | 也可以用 `rt/lf/lowstate`（低频镜像） |
| `--gpu` | `auto` | GPU/板卡后端：`auto` / `jtop` / `tegra` / `nvidia` / `none` |
| `-p`, `--page` | `all` | 启动页面：`all` `cpu` `gpu` `mem` `joints` `imu` `power` `info` |
| `--interval` | `0.5` | 主机统计的采样周期（秒） |
| `--robot-hz` | `20` | 机器人快照频率的下限（高刷新率页面会自动提高） |
| `--no-robot` | | 只监控主机 |
| `--demo` | | 使用合成的机器人数据 |
| `--json` / `--wait N` | / `2` | 采集 N 秒后输出一次 JSON 并退出 |
| 环境变量 `UNITREETOP_IFACE`、`UNITREETOP_DOMAIN` | | 分别作为 `-i`、`-d` 的默认值 |

### 按键

| 按键 | 作用 |
|---|---|
| `1`–`8`、`←` `→` `Tab`、鼠标点击底栏 | 切换页面 |
| `+` / `-` | 调节当前页的刷新率 |
| `p` | 暂停/继续刷新 |
| `q` / `Esc` | 退出 |
| `↑` `↓` / `PgUp` `PgDn`（JOINTS） | 选择关节，下方曲线显示该关节的历史 |
| `a`（JOINTS） | 显示/隐藏没有数据的电机槽位 |
| `s`（CPU） | 进程排序：CPU → 内存 → PID |
| `↑` `↓`（INFO） | 滚动 DDS 话题列表 |

### 刷新率

每个页面的刷新率独立保存，切换页面后不会丢失。底栏的 `+- 50Hz` 显示当前值；终端跟不上时会附上实际帧率，如 `50Hz(~38)`。

| 页面 | 默认 | 步长 | 范围 |
|---|---|---|---|
| JOINTS、IMU | 50 Hz | 10 Hz | 10–200 Hz |
| ALL、CPU、GPU、MEM、POWER、INFO | 1 Hz | 1 Hz | 1–10 Hz |

机器人数据的采样频率会跟随当前页面（不低于 `--robot-hz`），所以 50 Hz 页面显示的确实是 50 Hz 的新数据。
曲线保存最近 240 个点，50 Hz 时约 4.8 秒。

**CPU 开销**（Go2 Orin NX，占单核）：1 Hz 页面约 8%，50 Hz 页面约 48%，大致与刷新率成正比。

终端需要支持 256 色（`xterm-256color`、`tmux-256color` 等），否则自动降级为 8 色。

## 页面说明

| 页 | 内容 |
|---|---|
| ¹ **all** | CPU 曲线和各核负载；内存/交换/磁盘/GPU 条、板载功耗和温度；机器人状态、电池、RPY、足端力、遥控器；全部关节一览 |
| ² **cpu** | CPU 曲线、各核负载与频率、进程表（每 2 秒刷新，只在本页打开时才扫描） |
| ³ **gpu** | 每块 GPU 的负载曲线与频率；温度、功耗轨（附整板功耗曲线）、板卡信息（型号、L4T、CUDA、TensorRT、nvpmodel、风扇、引擎） |
| ⁴ **mem** | 内存曲线、各网卡 IP 与收发速率；机器人网卡的下载/上传双向曲线 |
| ⁵ **joints** | 所有关节的 mode、q（rad/°）、dq、tau、温度、丢包（go 家族）或第二温度/电压/错误码（hg 家族），q 和 tau 的正负条；选中关节的 q/dq/tau 曲线 |
| ⁶ **imu** | RPY 与四元数、角速度、加速度及其模长；sportmodestate（有发布时）、足端力、遥控器摇杆和按键；roll/pitch/gyro-z 曲线 |
| ⁷ **power** | 电池 SOC、电压、电流、功率、循环次数、SOH、BMS 温度、各节电芯电压与压差；机器人主板信息（母线电压、NTC、风扇）；电池功率、电池电压、计算板功耗曲线 |
| ⁸ **info** | 主机与软件版本；机器人型号、DDS 家族、固件版本、tick、各订阅话题的频率；DDS 发现的全部话题（● 表示已订阅） |

温度配色：关节温度 ≥ 60 °C 显示黄色，≥ 75 °C 显示红色。

## JSON 输出与 Python API

### JSON

```bash
unitreetop --json --wait 3 | jq '.robot.battery'
```

输出包含三部分：
- `system`：cpu、mem、swap、disk、net、temp、uptime
- `gpu`：gpus、power、temp、fan、info、engines
- `robot`：status、model、family、rates、motors[]、imu、battery、sport、remote、foot_force、board

适合写日志或接入其它脚本。

### Python API（接口风格与 `jtop` 一致）

```python
from unitreetop import UnitreeTop

with UnitreeTop(interface="eth1") as ut:       # 参数同命令行：domain、robot、demo、gpu ...
    while ut.ok():                             # 阻塞直到有新数据
        r = ut.robot                           # RobotState
        print(ut.cpu["total"], ut.gpu, r.battery.soc, r.imu.rpy)
        for m in r.active_motors:              # Motor: index name q dq tau temp ...
            if m.temp > 70:
                print("hot joint", m.name, m.temp)
```

`ut.history.get(key)` 提供曲线用的环形缓冲，key 包括：
- 主机：`cpu`、`cpu<N>`、`ram`、`gpu<N>`、`board_power`、`rx:<iface>`、`tx:<iface>`
- IMU：`roll`、`pitch`、`yaw`、`gx` 等
- 电池：`bat_power`、`bat_voltage`
- 关节：`q<N>`、`dq<N>`、`tau<N>`、`temp<N>`

## 工作原理

更完整的说明见 [docs/architecture.md](docs/architecture.md)。

- **话题发现**：读取 DDS 内置的 `DCPSPublication` 话题，拿到网络上每个话题的类型名。
  - `rt/lowstate` 的类型是 `unitree_go::…::LowState_` 时，判定为 Go2/B2/H1 家族；是 `unitree_hg::…::LowState_` 时，判定为 G1/H1-2 家族。
  - 电池（`unitree_hg BmsState_`）、主板（`MainBoardState_`）和运动状态（`SportModeState_`）按类型找话题，不写死话题名。
  - 运动模式中途开启时，会自动补上订阅。
- **型号推断**：看哪些电机槽位有数据。go 家族：12 个 → Go2，16 个 → Go2-W，17 个以上 → H1；hg 家族根据槽位分布区分 G1 和 H1-2。
- **低开销接收**：lowstate 以 500 Hz 发布。读取器只保留最新一条（`KeepLast(1)`），回调里只计数（用来显示 Hz），
  界面需要时才解析最新样本。逐条在 Python 中解析会占单核约 70%，现在约 5%。
- **GPU 后端**：Jetson 上优先使用 jtop；没有 jtop 时读取 tegra sysfs；桌面 GPU 用 NVML 或 `nvidia-smi`。
- **抗干扰**：机器人 Jetson 上的内核或 syslog 广播会直接写入终端、打乱画面，所以每 2 秒强制全屏重绘一次。

## 故障排查

| 现象 | 处理 |
|---|---|
| 一直显示 `waiting for rt/lowstate` | 用 `-i` 指定连接机器人的网卡，并确认该网卡 IP 在 192.168.123.0/24、`-d` 与机器人的 domain 一致。外部 PC 上还要检查防火墙是否拦截了 UDP 组播 |
| `DDS init failed: … CycloneDDS library could not be located` | `cyclonedds` Python 包找不到 C 库：编译安装 CycloneDDS 0.10.x，并设置 `CYCLONEDDS_HOME` |
| 型号识别错误（例如 B2 被识别为 Go2） | 用 `-r` 指定型号 |
| GPU 页显示 `no GPU backend` | Jetson：安装 jetson-stats 并启动 `jtop.service`；桌面：确认 `nvidia-smi` 可用 |
| 颜色只有 8 种 / 方块显示异常 | 设置 `TERM=xterm-256color`，并使用支持 Unicode 的等宽字体 |
| 50 Hz 页面 CPU 占用偏高 | 按 `-` 降低该页刷新率；监控长期开着时停在 ALL 页（1 Hz） |
| G1 的电池数值看起来不对 | 见[已知限制](#已知限制)，欢迎提 issue 并附上 `unitreetop --json` 的输出 |

## 已知限制

- Go2 与 B2（以及 Go2-W 与 B2-W）的 lowstate 结构完全相同，无法自动区分，B2 需要加 `-r b2`。
- G1/H1-2 的 BMS 字段单位（电压 mV、电流 mA）是根据 SDK IDL 推断的，尚未在真机上核对。没有 BMS 话题时，电池电压用电机母线电压估算。
- 机器人数据只读，不支持下发命令（这是有意的设计）。
- 每次只监控一台机器人（一个 DDS domain + 网卡）。

## 开发与测试

```
unitreetop/
├── bin/unitreetop          # 免安装启动脚本
├── tools/fake_robot.py     # DDS 模拟发布器（go / hg 家族）
├── unitreetop/
│   ├── __main__.py         # 命令行入口
│   ├── core/               # 数据采集：system / gpu / robot(DDS) / models / demo
│   └── gui/                # curses 界面：common（绘图原语、主题）/ pages / 主循环
└── docs/architecture.md    # 架构与扩展说明
```

没有机器人时测试 DDS 路径：

```bash
python3 tools/fake_robot.py --family hg -d 1 -i lo &    # 模拟 G1：29 个关节 + rt/lf/bmsstate
unitreetop -d 1 -i lo
```

如何添加新机器人型号或新页面，见 [docs/architecture.md](docs/architecture.md#扩展)。

## 许可证与致谢

本项目以 [MIT 许可证](LICENSE)发布。

- [jetson_stats](https://github.com/rbonghi/jetson_stats)（rbonghi）：jtop 的整体思路，以及 Jetson 上的数据来源
- [btop](https://github.com/aristocratos/btop)（aristocratos）：界面风格与默认配色主题
- [unitree_sdk2_python](https://github.com/unitreerobotics/unitree_sdk2_python)：DDS 消息定义与关节布局

本项目与宇树科技（Unitree Robotics）、NVIDIA 无隶属关系。
