# unitreetop

[English](README.md) | **中文**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![Platform](https://img.shields.io/badge/platform-Jetson%20%7C%20Linux-lightgrey)

宇树机器人的终端控制台：[jtop](https://github.com/rbonghi/jetson_stats) 风格的监控，[btop](https://github.com/aristocratos/btop) 外观，外加键盘控制面板。

- **监控**：除主机指标（CPU、GPU、内存、温度、功耗）外，通过 [`unitree_sdk2py`](https://github.com/unitreerobotics/unitree_sdk2_python)（CycloneDDS）实时显示机器人状态：关节、电池/BMS、IMU、足端力、遥控器、运动状态及全部 DDS 话题。
- **控制**：第 ⁹ 页通过高层 sport/loco API 用键盘控制机器人。未解锁前不发送任何指令，`--no-control` 可彻底关闭。

![all](docs/screenshot-all.png)
![joints](docs/screenshot-joints.png)

## 支持的机器人

| 型号 | DDS 族 | 关节数 | 控制 API | 状态 |
|---|---|---|---|---|
| Go2 | `unitree_go` | 12 | `SportClient` | ✅ 监控已在真机测试 |
| Go2-W、B2 / B2-W、H1 | `unitree_go` | 16 / 12 / 16、19 | `SportClient` / `LocoClient` | 按 SDK 定义实现 |
| G1（23/29 自由度）、H1-2 | `unitree_hg` | 23 / 29、27 | `LocoClient`（H1-2 仅监控） | 已用模拟 DDS 数据测试 |

控制功能仅在模拟 RPC 服务（`tools/fake_robot.py`）上测试过，**尚未在真机上验证**。Go2 与 B2 的 lowstate 布局相同，B2 请加 `-r b2`。

## 快速开始

```bash
git clone --recurse-submodules git@github.com:SimonKennethRobo/unitreetop.git ~/Apps/unitreetop
ln -s ~/Apps/unitreetop/bin/unitreetop ~/.local/bin/unitreetop
unitreetop                          # 在机器人的 Jetson 上
python3 -m unitreetop --demo -r g1  # 无需机器人
```

依赖：Python ≥ 3.8、`psutil`、`cyclonedds==0.10.x`。宇树 SDK 已作为子模块内置（忘记 `--recurse-submodules` 时执行 `git submodule update --init`；`UNITREETOP_SDK=system` 使用系统已安装的版本）。可选：`jetson-stats`（Jetson GPU/功耗）、`nvidia-ml-py`（桌面 GPU）。也可 `pip3 install -e .`（`".[jetson]"` 额外安装 jetson-stats）。

## 用法

```bash
unitreetop -i eth1               # 指定网卡（默认选有 192.168.123.x 地址的网卡）
unitreetop -i enp3s0 -r g1       # 外接 PC 连 G1，强制指定型号
unitreetop -p joints             # 直接打开某页
unitreetop --json --wait 3       # 输出一次 JSON 快照后退出
unitreetop -d 1 -i lo            # unitree_mujoco 仿真
```

主要选项（`unitreetop -h` 查看全部）：

| 选项 | 说明 |
|---|---|
| `-i`、`-d` | 网卡与 DDS domain（真机 0，unitree_mujoco 1）；环境变量 `UNITREETOP_IFACE` / `UNITREETOP_DOMAIN` |
| `-r` | `auto` `go2` `go2w` `b2` `b2w` `h1` `g1` `h1_2` |
| `-p` | 起始页：`all cpu gpu mem joints imu power info ctrl` |
| `--no-robot` / `--demo` | 仅主机 / 合成机器人数据 |
| `--no-control` | 仅监控，绝不发送任何指令 |
| `--vel-step`、`--max-vx/vy/wz` | 遥控步长与速度上限 |

按键：`1`–`9` / `←` `→` / 鼠标切换页面，`+` `-` 调刷新率，`p` 暂停，`q` 退出；`↑` `↓` 选关节（JOINTS）或滚动话题（INFO），`s` 切换进程排序（CPU），`a` 显示空电机槽（JOINTS）。

页面：¹ all、² cpu、³ gpu、⁴ mem、⁵ joints、⁶ imu、⁷ power、⁸ info、⁹ ctrl。JOINTS/IMU 默认 50 Hz（约占 Orin NX 单核 48%），其余 1 Hz（约 8%）。

## 键盘控制

> ⚠️ 这会让真实机器人运动。请清场，手边备好官方遥控器（或其他急停），人形机器人在摸清行为前请挂在吊架上。

打开第 ⁹ 页，确认机器人 **online**，按 **Enter** 解锁。速度键用于*调整*锁定的速度，与 `go2_keyboard_ctrl` 一致：从零开始第一次按键直接跳到 0.3 m/s（`vx`/`vy`）或 0.5 rad/s（`wz`），之后每次按键增减一个 `--vel-step`；反向键会先减速、过零再反向。速度按型号限幅，非零速度以 10 Hz 发送。

| 按键 | 指令 |
|---|---|
| `W` `S` / `A` `D` / `Q` `E` | `vx` / `vy` / `wz` ± 一步 |
| `Space` | 清零速度（StopMove） |
| `Z` / `X` | 坐下或趴下 / 站起（同时退出阻尼） |
| `P` | 阻尼：电机卸力，站立的机器人会倒下 |
| `Esc` / `Enter` | 上锁 |

**安全机制**：未解锁时不发送任何指令，机器人离线时拒绝解锁。按 `Esc`、离开页面、退出、Ctrl-C、SIGHUP/SIGTERM，或机器人离线/数据过期时，面板自动上锁并停止机器人。按住姿态键只触发一次，`P` 之后速度键保持锁定直到 `X` 成功，Move 失败会清零速度。sport 服务必须在运行；若没有 `rt/sportmodestate`，指令会超时。

## JSON 与 Python API

```python
from unitreetop import UnitreeTop

with UnitreeTop(interface="eth1") as ut:       # 参数与命令行一致
    while ut.ok():
        r = ut.robot
        print(ut.cpu["total"], r.battery.soc, r.imu.rpy)
```

`--json` 输出 `system`、`gpu`、`robot` 三部分；`ut.history.get(key)` 返回图表背后的环形缓冲。工作原理及如何添加机器人或页面见 [docs/architecture.md](docs/architecture.md)。

## 故障排查

| 现象 | 解决 |
|---|---|
| 卡在 `waiting for rt/lowstate` | 用 `-i` 指定能连到机器人的网卡（192.168.123.0/24），检查 `-d`；外接 PC 还需检查防火墙是否拦截 UDP 组播 |
| `CycloneDDS library could not be located` | 编译 CycloneDDS 0.10.x 并设置 `CYCLONEDDS_HOME` |
| `No module named unitree_sdk2py` | `git submodule update --init` |
| 型号识别错误 | 用 `-r` 强制指定 |
| 无 GPU 后端 | Jetson：启动 `jtop.service`；桌面：确认 `nvidia-smi` 可用 |
| 颜色/符号错乱 | `TERM=xterm-256color`，并使用支持 Unicode 的等宽字体 |

G1/H1-2 的 BMS 单位由 SDK IDL 推断，尚未在真机验证。控制仅使用高层 API（无关节指令），每个实例仅支持一台机器人（一个 DDS domain 和网卡）。

## 开发

无需机器人即可测试，请使用与真机不同的 domain，避免测试指令误达真机：

```bash
python3 tools/fake_robot.py --family go -d 7 -i lo &   # 模拟 Go2（G1 用 --family hg）
unitreetop -d 7 -i lo -p ctrl
```

## 许可与致谢

[MIT](LICENSE)；内置的 unitree_sdk2_python 保留其 BSD-3-Clause 许可。感谢 [jetson_stats](https://github.com/rbonghi/jetson_stats)、[btop](https://github.com/aristocratos/btop) 与 [unitree_sdk2_python](https://github.com/unitreerobotics/unitree_sdk2_python)。与宇树科技及 NVIDIA 无关联。
