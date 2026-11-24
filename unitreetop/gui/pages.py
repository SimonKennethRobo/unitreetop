"""Pages of the curses UI (btop look). Each page draws into the area between header and menu."""
import curses
import math

from .common import (bg, c, grad, graph, graph_panel, meter, meter_row, panel, put, size, smeter, subtitle,
                     temp_attr, uptime)

DEG = 180.0 / math.pi
MOTOR_WARN, MOTOR_CRIT = 60, 75


class Page:
    name = "PAGE"
    # screen refresh rate of this page, changed at runtime with +/-
    hz = 1.0
    hz_step = 1.0
    hz_min = 1.0
    hz_max = 10.0

    def __init__(self, ut):
        self.ut = ut

    def key(self, ch):
        return False

    def draw(self, win, y, x, h, w):
        raise NotImplementedError

    def help(self):
        return []  # list of (key, text)


# ----------------------------------------------------------------------------
# shared widgets
# ----------------------------------------------------------------------------

def sel_attr():
    return bg("selected_fg", "selected_bg") | curses.A_BOLD


def motor_temp_attr(t):
    if t >= MOTOR_CRIT:
        return c("crit", True)
    if t >= MOTOR_WARN:
        return c("warn", True)
    return temp_attr(t, crit=MOTOR_CRIT + 10)


def status_attr(status):
    return {"online": c("ok", True), "demo": c("label", True), "stale": c("warn", True),
            "waiting": c("warn"), "discovering": c("warn")}.get(status, c("crit", True))


def kv(win, y, x, w, key, value, kw=12, vattr=None):
    put(win, y, x, key[:kw].ljust(kw), c("graph_text"))
    put(win, y, x + kw, str(value), c("main_fg") if vattr is None else vattr, maxw=max(0, w - kw))


def cpu_panel(win, ut, y, x, h, w, key=None, title="cpu"):
    """btop cpu box: braille graph on the left, core list in an inner box on the right."""
    cpu = ut.cpu
    cores = cpu.get("cores", [])
    temps = dict(ut.gpu_stats.get("temp", {}))
    ctemp = temps.get("CPU") or next((v for k, v in ut.stats.get("temp", {}).items()
                                      if "coretemp" in k or "k10temp" in k or "cpu" in k.lower()), None)
    right = "{:.0f}°C".format(ctemp) if ctemp else ""
    iy, ix, ih, iw = panel(win, y, x, h, w, title, key, "cpu_box", right)
    if ih <= 0:
        return
    n = len(cores)
    ncol = 1
    while ncol < 4 and int(math.ceil(n / float(ncol))) + 4 > ih:
        ncol += 1
    rows = int(math.ceil(n / float(ncol))) if n else 0
    lw = min(iw - 10, ncol * 24 + 2, max(30, int(iw * 0.55)))
    gw = iw - lw - 1
    if gw >= 10:
        graph(win, iy, ix, ih, gw, ut.history.get("cpu"), 0, 100, "cpu")
        put(win, iy, ix, "100%", c("graph_text"))
        put(win, iy + ih - 1, ix, "0%", c("graph_text"))
        lx = ix + gw + 1
    else:
        lw, lx = iw, ix
    by, bx, bh, bwid = panel(win, iy, lx, min(ih, rows + 4), lw, "", None, "div_line")
    if bh <= 0:
        return
    total = cpu.get("total", 0.0)
    meter_row(win, by, bx, bwid, "CPU", total, "{:>3.0f}%".format(total), "cpu", lw=4, vw=5)
    colw = bwid // ncol
    any_f = any(core["freq"] for core in cores) and colw - 1 >= 20
    for i, core in enumerate(cores):
        r, k = i % max(rows, 1), i // max(rows, 1)
        yy = by + 1 + r
        if yy >= by + bh - 1:
            continue
        xx = bx + k * colw
        ww = colw - 1
        freq = core["freq"] / 1000.0 if core["freq"] else 0
        val = "{:>4.0f}%".format(core["load"])
        mw = max(1, ww - 4 - len(val) - (5 if any_f else 0))
        put(win, yy, xx, "C{:<2}".format(i), c("main_fg"))
        meter(win, yy, xx + 4, mw, core["load"], "cpu")
        put(win, yy, xx + 4 + mw, val, c("main_fg"))
        if any_f:
            put(win, yy, xx + 4 + mw + len(val), " {:.1f}G".format(freq) if freq else "   - ", c("graph_text"))
    la = cpu.get("load", (0, 0, 0))
    put(win, by + bh - 1, bx, "Load avg {:.2f} {:.2f} {:.2f}".format(*la), c("graph_text"), maxw=bwid)


def mem_lines(win, ut, y, x, w, rows):
    s = ut.stats
    out = []
    m, sw, d = s.get("mem", {}), s.get("swap", {}), s.get("disk", {})
    if m:
        out.append(("Mem", m["percent"], "{}/{}".format(size(m["used"]), size(m["total"])), "used"))
    if sw and sw.get("total"):
        out.append(("Swap", sw["percent"], "{}/{}".format(size(sw["used"]), size(sw["total"])), "cached"))
    if d:
        out.append(("Disk", d["percent"], "{}/{}".format(size(d["used"]), size(d["total"])), "available"))
    for g in ut.gpu:
        val = "{:.0f}%".format(g["load"]) + (" {:.0f}MHz".format(g["freq"]) if g.get("freq") else "")
        out.append(("GPU", g["load"], val, "gpu"))
        if g.get("mem_total"):
            out.append(("VRAM", 100.0 * g["mem_used"] / g["mem_total"],
                        "{}/{}".format(size(g["mem_used"]), size(g["mem_total"])), "used"))
    n = 0
    for label, pct, val, gname in out[:max(rows, 0)]:
        meter_row(win, y + n, x, w, label, pct, val, gname, lw=5, vw=max(len(val) + 1, 14))
        n += 1
    return n


def battery_lines(win, ut, y, x, w):
    b = ut.robot.battery
    if not b.valid and not b.voltage:
        put(win, y, x, "battery: no data", c("inactive_fg"))
        return 1
    if b.valid:
        meter_row(win, y, x, w, "BAT", b.soc, "{:.0f}%".format(b.soc), "battery", lw=5, vw=6)
    else:
        put(win, y, x, "BAT  SOC n/a ({})".format(b.source), c("warn"), maxw=w)
    state = "charging" if b.current > 0.05 else ("discharging" if b.current < -0.05 else "idle")
    x2 = x + 5
    x2 += put(win, y + 1, x2, "{:.2f}V ".format(b.voltage), c("title", True))
    x2 += put(win, y + 1, x2, "{:+.2f}A ".format(b.current), c("main_fg"))
    x2 += put(win, y + 1, x2, "{:.1f}W ".format(abs(b.power)), c("warn", True))
    put(win, y + 1, x2, state, c("graph_text"))
    return 2


def rpy_lines(win, ut, y, x, w):
    imu = ut.robot.imu
    for i, (n, v, rng) in enumerate(zip(("Roll", "Pitch", "Yaw"), imu.rpy, (45, 45, 180))):
        d = v * DEG
        put(win, y + i, x, "{:<6}".format(n), c("main_fg"))
        put(win, y + i, x + 6, "{:>+8.2f}°".format(d), c("title", True))
        smeter(win, y + i, x + 17, max(5, w - 17), d, rng)
    return 3


class JointScale:
    def __init__(self):
        self.tau = 5.0

    def update(self, motors):
        m = max([abs(j.tau) for j in motors] + [0.0])
        self.tau = max(self.tau * 0.995, m * 1.1, 5.0)


def joint_table(win, motors, y, x, w, h, scale):
    """Compact joint list with a signed tau meter. Returns rows used."""
    if h < 2:
        return 0
    hdr = "{:>2} {:<16} {:>7} {:>7} {:>7} {:>4}".format("#", "Joint", "q", "dq", "tau", "T°C")
    put(win, y, x, hdr, c("title", True))
    bw = w - len(hdr) - 1
    if bw >= 9:
        put(win, y, x + len(hdr) + 1, "tau ±{:.0f}Nm".format(scale).center(bw), c("title", True))
    n = 1
    for k, m in enumerate(motors):
        if n >= h:
            put(win, y + h - 1, x + w - 12, "(+{} more)".format(len(motors) - k + 1), c("warn"))
            break
        base = c("main_fg") if m.active else c("inactive_fg")
        line = "{:>2} {:<16} {:>+7.3f} {:>+7.2f} {:>+7.2f} ".format(m.index, m.name[:16], m.q, m.dq, m.tau)
        put(win, y + n, x, line, base)
        put(win, y + n, x + len(line), "{:>4.0f}".format(m.temp), motor_temp_attr(m.temp))
        if bw >= 9:
            smeter(win, y + n, x + len(hdr) + 1, bw, m.tau, scale)
        n += 1
    return n


# ----------------------------------------------------------------------------
# 1 ALL
# ----------------------------------------------------------------------------

class AllPage(Page):
    name = "all"

    def __init__(self, ut):
        Page.__init__(self, ut)
        self.scale = JointScale()

    def draw(self, win, y, x, h, w):
        ut, r = self.ut, self.ut.robot
        motors = r.active_motors
        self.scale.update(motors)
        two_col = w >= 120 and len(motors) > 14
        jrows = ((int(math.ceil(len(motors) / 2.0)) if two_col else len(motors)) + 1) if motors else 1
        side = w >= 90
        mid_h = 10
        mids = mid_h if side else 2 * mid_h
        jh = jrows + 2
        cpu_h = max(6, h - mids - jh)
        cpu_panel(win, ut, y, x, cpu_h, w, 1)
        my = y + cpu_h
        lw = w // 2 if side else w
        # mem / gpu panel
        iy, ix, ih, iw = panel(win, my, x, mid_h, lw, "mem", 4, "mem_box")
        used = mem_lines(win, ut, iy, ix, iw, ih - 1)
        if ih > 0:
            pw = ut.gpu_stats.get("power", {})
            temps = dict(ut.gpu_stats.get("temp", {}))
            if len(temps) < 3:
                temps.update(ut.stats.get("temp", {}))
            tx, ty = ix, iy + min(used, ih - 1)
            if pw:
                tx += put(win, ty, tx, "Board ", c("graph_text"))
                tx += put(win, ty, tx, "{:.1f}W  ".format(pw.get("total", 0)), c("warn", True))
            for k, v in list(temps.items())[:8]:
                if tx + 12 > ix + iw:
                    break
                tx += put(win, ty, tx, "{} ".format(k[:6]), c("graph_text"))
                tx += put(win, ty, tx, "{:.0f}°  ".format(v), temp_attr(v))
        # robot panel
        rx, rw, ry = (x + lw, w - lw, my) if side else (x, w, my + mid_h)
        mdl = r.model.name if r.model else "robot"
        rate = r.rates.get(r.lowstate_topic, 0.0)
        right = "{} {:.0f}Hz".format(r.lowstate_topic, rate) if r.lowstate_topic else ""
        iy, ix, ih, iw = panel(win, ry, rx, mid_h, rw, mdl, 6, "robot_box", right)
        if ih > 0:
            row = iy
            put(win, row, ix, "● " + r.status, status_attr(r.status))
            if r.error:
                put(win, row, ix + 12, r.error, c("crit"), maxw=iw - 12)
            row += 1
            if not r.online and r.status != "stale":
                put(win, row, ix, self._hint(r), c("warn"), maxw=iw)
            else:
                row += battery_lines(win, ut, row, ix, iw)
                row += rpy_lines(win, ut, row, ix, iw)
                parts = []
                if r.foot_force:
                    parts.append("Foot " + " ".join("{:>4}".format(int(f)) for f in r.foot_force))
                if r.sport.valid:
                    parts.append("v=({:+.2f},{:+.2f}) wz={:+.2f}".format(
                        r.sport.velocity[0], r.sport.velocity[1], r.sport.yaw_speed))
                if parts and row < iy + ih:
                    put(win, row, ix, "   ".join(parts), c("main_fg"), maxw=iw)
                    row += 1
                if r.remote.valid and row < iy + ih:
                    put(win, row, ix, "Remote L({:+.2f},{:+.2f}) R({:+.2f},{:+.2f}) {}".format(
                        r.remote.lx, r.remote.ly, r.remote.rx, r.remote.ry, " ".join(r.remote.buttons)),
                        c("graph_text"), maxw=iw)
        # joints
        jy = my + mids
        jh = y + h - jy
        if jh < 3:
            return
        hot = max(motors, key=lambda m: m.temp) if motors else None
        right = "hottest {} {:.0f}°C".format(hot.name, hot.temp) if hot else ""
        iy, ix, ih, iw = panel(win, jy, x, jh, w, "joints", 5, "proc_box", right)
        if not motors:
            put(win, iy, ix, "no joint data", c("inactive_fg"))
            return
        if two_col:
            half = int(math.ceil(len(motors) / 2.0))
            cw = iw // 2
            joint_table(win, motors[:half], iy, ix, cw - 1, ih, self.scale.tau)
            for k in range(ih):
                put(win, iy + k, ix + cw, "│", c("div_line"))
            joint_table(win, motors[half:], iy, ix + cw + 2, iw - cw - 2, ih, self.scale.tau)
        else:
            joint_table(win, motors, iy, ix, iw, ih, self.scale.tau)

    @staticmethod
    def _hint(r):
        if r.status == "disabled":
            return "robot monitoring disabled"
        if r.status == "error":
            return "check --interface / CycloneDDS installation"
        return "waiting for {} ... (is -i <iface> correct? domain id?)".format(r.lowstate_topic or "rt/lowstate")


# ----------------------------------------------------------------------------
# 2 CPU
# ----------------------------------------------------------------------------

class CpuPage(Page):
    name = "cpu"

    def __init__(self, ut):
        Page.__init__(self, ut)
        self.sort = "cpu"

    def key(self, ch):
        if ch == ord("s"):
            self.sort = {"cpu": "mem", "mem": "pid", "pid": "cpu"}[self.sort]
            return True
        return False

    def help(self):
        return [("s", "sort " + self.sort)]

    def draw(self, win, y, x, h, w):
        ut = self.ut
        ch = max(8, int(h * 0.45))
        cpu_panel(win, ut, y, x, ch, w, 2)
        procs = list(ut.stats.get("procs", []))
        key = {"cpu": lambda p: -p["cpu"], "mem": lambda p: -p["mem"], "pid": lambda p: p["pid"]}[self.sort]
        procs.sort(key=key)
        iy, ix, ih, iw = panel(win, y + ch, x, h - ch, w, "proc", None, "proc_box",
                               "{} shown  sort:{}".format(len(procs), self.sort))
        if ih <= 1:
            return
        hdr = "{:>7}  {:<24} {:<10} {:>4} {:>9} {:>6}".format("Pid:", "Program:", "User:", "Thr:", "MemB", "Cpu%")
        put(win, iy, ix, hdr, c("title", True))
        mw = min(16, iw - len(hdr) - 2)
        if not procs:
            put(win, iy + 1, ix, "collecting...", c("inactive_fg"))
        for i, p in enumerate(procs[:ih - 1]):
            frac = min(1.0, p["cpu"] / 100.0)
            line = "{:>7}  {:<24} {:<10} {:>4} {:>9} ".format(p["pid"], p["name"][:24], p["user"][:10],
                                                                p["threads"], size(p["mem"]))
            put(win, iy + 1 + i, ix, line, c("main_fg"))
            put(win, iy + 1 + i, ix + len(line), "{:>6.1f}".format(p["cpu"]), grad("process", frac))
            if mw >= 4:
                meter(win, iy + 1 + i, ix + len(hdr) + 2, mw, min(100.0, p["cpu"]), "process")


# ----------------------------------------------------------------------------
# 3 GPU / board
# ----------------------------------------------------------------------------

class GpuPage(Page):
    name = "gpu"

    def draw(self, win, y, x, h, w):
        ut = self.ut
        gs = ut.gpu_stats
        gpus = ut.gpu
        row = y
        if not gpus:
            iy, ix, ih, iw = panel(win, row, x, 3, w, "gpu", 3, "mem_box")
            put(win, iy, ix, "no GPU backend ({})".format("; ".join(ut.gpu_errors) or "none"), c("warn"), maxw=iw)
            row += 3
        gh = max(6, (h // 2) // max(1, len(gpus))) if gpus else 0
        for i, g in enumerate(gpus):
            right = "{:.0f}/{:.0f}MHz".format(g.get("freq") or 0, g.get("max_freq") or 0)
            if g.get("temp") is not None:
                right += " {:.0f}°C".format(g["temp"])
            if g.get("power") is not None:
                right += " {:.1f}W".format(g["power"])
            right += "  {:.0f}%".format(g["load"])
            graph_panel(win, row, x, gh, w, ut.history.get("gpu{}".format(i)), g["name"], right, 0, 100, "gpu",
                        "mem_box", 3 if i == 0 else None, unit="%")
            row += gh
        bh = y + h - row
        if bh < 3:
            return
        cw = w // 3
        temps = dict(gs.get("temp", {})) or ut.stats.get("temp", {})
        iy, ix, ih, iw = panel(win, row, x, bh, cw, "temps", None, "cpu_box")
        for i, (k, v) in enumerate(sorted(temps.items())[:ih]):
            meter_row(win, iy + i, ix, iw, k[:10], (v - 20) / 0.8, "{:.1f}°C".format(v), "temp", lw=11, vw=8)
        pw = gs.get("power", {})
        iy, ix, ih, iw = panel(win, row, x + cw, bh, cw, "power", None, "net_box",
                               "{:.2f}W".format(pw.get("total", 0)) if pw else "")
        if pw:
            tot = max(pw.get("total", 0), 1e-3)
            rails = sorted(pw.get("rails", {}).items())
            for i, (k, v) in enumerate(rails[:ih]):
                meter_row(win, iy + i, ix, iw, k[:14], 100 * v / tot, "{:.2f}W".format(v), "download", lw=15, vw=8)
            gy = iy + len(rails) + 1
            if iy + ih - gy >= 2 and ut.history.get("board_power"):
                graph(win, gy, ix, iy + ih - gy, iw, ut.history.get("board_power"), 0, None, "download")
        elif ih > 0:
            put(win, iy, ix, "n/a", c("inactive_fg"))
        iy, ix, ih, iw = panel(win, row, x + 2 * cw, bh, w - 2 * cw, "board", None, "proc_box")
        items = list(gs.get("info", {}).items()) + [("fan " + k, "{:.0f}%".format(v)) for k, v in gs.get("fan", {}).items()]
        items += [(k, v) for k, v in gs.get("engines", {}).items()]
        for i, (k, v) in enumerate(items[:max(ih, 0)]):
            kv(win, iy + i, ix, iw, k, v, 14)


# ----------------------------------------------------------------------------
# 4 MEM / NET
# ----------------------------------------------------------------------------

class SysPage(Page):
    name = "mem"

    def draw(self, win, y, x, h, w):
        ut = self.ut
        m = ut.stats.get("mem", {})
        mh = max(8, h // 2)
        iy, ix, ih, iw = panel(win, y, x, mh, w, "mem", 4, "mem_box",
                               "{} / {}".format(size(m.get("used")), size(m.get("total"))))
        if ih > 0:
            lw = min(56, iw // 2)
            mem_lines(win, ut, iy, ix, lw, ih)
            graph(win, iy, ix + lw + 1, ih, iw - lw - 1, ut.history.get("ram"), 0, 100, "used")
        nets = ut.stats.get("net", {})
        sel = ut.interface if ut.interface in nets else (
            max(nets, key=lambda n: nets[n]["rx"] + nets[n]["tx"]) if nets else None)
        info = "{} {}".format(sel, nets[sel]["ip"]) if sel else ""
        iy, ix, ih, iw = panel(win, y + mh, x, h - mh, w, "net", None, "net_box", info)
        if ih <= 0:
            return
        tw = min(56, iw // 2)
        put(win, iy, ix, "{:<10} {:<16} {:>12} {:>12}".format("Iface", "IPv4", "Down", "Up"), c("title", True))
        for i, (name, n) in enumerate(sorted(nets.items())[:ih - 1]):
            a = c("title", True) if name == sel else (c("main_fg") if n["up"] else c("inactive_fg"))
            put(win, iy + 1 + i, ix, "{:<10} {:<16} ".format(name[:10], n["ip"]), a)
            put(win, iy + 1 + i, ix + 28, "{:>12}".format(size(n["rx"], "/s")), grad("download", 1))
            put(win, iy + 1 + i, ix + 41, "{:>12}".format(size(n["tx"], "/s")), grad("upload", 1))
        if sel and iw - tw > 12:
            gx, gw = ix + tw + 1, iw - tw - 1
            top = ih // 2
            rx, tx = ut.history.get("rx:" + sel), ut.history.get("tx:" + sel)
            hi = max(list(rx) + list(tx) + [1024.0])
            graph(win, iy, gx, top, gw, rx, 0, hi, "download")
            graph(win, iy + top, gx, ih - top, gw, tx, 0, hi, "upload", invert=True)
            put(win, iy, gx, "▼ {}".format(size(nets[sel]["rx"], "/s")), c("title", True))
            put(win, iy + ih - 1, gx, "▲ {}".format(size(nets[sel]["tx"], "/s")), c("title", True))
            put(win, iy, gx + gw - len(size(hi, "/s")), size(hi, "/s"), c("graph_text"))


# ----------------------------------------------------------------------------
# 5 JOINTS
# ----------------------------------------------------------------------------

class JointPage(Page):
    name = "joints"
    hz, hz_step, hz_min, hz_max = 50.0, 10.0, 10.0, 200.0

    def __init__(self, ut):
        Page.__init__(self, ut)
        self.sel = 0
        self.top = 0
        self.show_all = False
        self.scale = JointScale()

    def help(self):
        return [("↑↓", "select"), ("a", "hide idle" if self.show_all else "show idle")]

    def key(self, ch):
        if ch in (curses.KEY_UP, ord("k")):
            self.sel = max(0, self.sel - 1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.sel += 1
        elif ch == curses.KEY_PPAGE:
            self.sel = max(0, self.sel - 10)
        elif ch == curses.KEY_NPAGE:
            self.sel += 10
        elif ch == ord("a"):
            self.show_all = not self.show_all
        else:
            return False
        return True

    def draw(self, win, y, x, h, w):
        r = self.ut.robot
        motors = r.motors if self.show_all else r.active_motors
        # table as tall as needed, graphs take the rest (at least 9 rows when there is room)
        th = min(h - 9, len(motors) + 3) if h >= 26 else h
        gh = h - th
        mdl = r.model.name if r.model else "robot"
        rate = r.rates.get(r.lowstate_topic, 0.0)
        iy, ix, ih, iw = panel(win, y, x, th, w, "joints", 5, "proc_box",
                               "{} · {} motors · {:.0f}Hz".format(mdl, len(motors), rate))
        if ih <= 0:
            return
        if not motors:
            put(win, iy, ix, "no joint data ({})".format(r.status), c("warn"))
            return
        self.scale.update(motors)
        self.sel = min(self.sel, len(motors) - 1)
        hg = any(m.vol is not None for m in motors)
        rows = ih - 1
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + rows:
            self.top = self.sel - rows + 1
        hdr = "{:>2} {:<18} {:>4} {:>8} {:>8} {:>8} {:>8} {:>5}".format(
            "#", "Joint", "Mode", "q rad", "q deg", "dq", "tau", "T°C")
        hdr += " {:>5} {:>6} {:>8}".format("T2", "V", "Error") if hg else " {:>7}".format("Lost")
        put(win, iy, ix, hdr, c("title", True))
        bx = ix + len(hdr) + 1
        bw = (iw - len(hdr) - 2) // 2
        if bw >= 8:
            put(win, iy, bx, "q ±π".center(bw), c("title", True))
            put(win, iy, bx + bw + 1, "tau ±{:.0f}Nm".format(self.scale.tau).center(bw), c("title", True))
        for i, m in enumerate(motors[self.top:self.top + rows]):
            k = self.top + i
            yy = iy + 1 + i
            is_sel = k == self.sel
            if is_sel:
                put(win, yy, ix, " " * iw, sel_attr())
            base = sel_attr() if is_sel else (c("main_fg") if m.active else c("inactive_fg"))
            line = "{:>2} {:<18} {:>4} {:>+8.3f} {:>+8.1f} {:>+8.2f} {:>+8.2f} ".format(
                m.index, m.name[:18], m.mode, m.q, m.q * DEG, m.dq, m.tau)
            put(win, yy, ix, line, base)
            cx = ix + len(line)
            put(win, yy, cx, "{:>5.0f}".format(m.temp), base if is_sel else motor_temp_attr(m.temp))
            cx += 5
            if hg:
                err = "0x{:x}".format(m.error) if m.error else "-"
                put(win, yy, cx, " {:>5.0f} {:>6.2f} ".format(m.temp2 or 0, m.vol or 0), base)
                put(win, yy, cx + 14, "{:>8}".format(err), c("crit", True) if m.error else base)
            else:
                put(win, yy, cx, " {:>7}".format(m.lost), base)
            if bw >= 8:
                smeter(win, yy, bx, bw, m.q, math.pi)
                smeter(win, yy, bx + bw + 1, bw, m.tau, self.scale.tau)
        if len(motors) > rows:
            put(win, iy + ih, ix + 2, "┤ {}-{} of {} ├".format(self.top + 1, min(self.top + rows, len(motors)),
                                                             len(motors)), c("warn"))
        if gh:
            m = motors[self.sel]
            pw = w // 3
            gy = y + h - gh
            hist = self.ut.history
            graph_panel(win, gy, x, gh, pw, hist.get("q{}".format(m.index)), m.name + " q",
                        "{:+.3f}rad".format(m.q), gname="cpu", color="cpu_box", scale_fmt="{:+.2f}")
            graph_panel(win, gy, x + pw, gh, pw, hist.get("dq{}".format(m.index)), "dq",
                        "{:+.2f}rad/s".format(m.dq), gname="download", color="net_box", scale_fmt="{:+.2f}")
            graph_panel(win, gy, x + 2 * pw, gh, w - 2 * pw, hist.get("tau{}".format(m.index)), "tau",
                        "{:+.2f}Nm".format(m.tau), gname="process", color="proc_box", scale_fmt="{:+.1f}")


# ----------------------------------------------------------------------------
# 6 IMU / motion
# ----------------------------------------------------------------------------

class ImuPage(Page):
    name = "imu"
    hz, hz_step, hz_min, hz_max = 50.0, 10.0, 10.0, 200.0

    def draw(self, win, y, x, h, w):
        r = self.ut.robot
        if not r.online and r.status != "stale":
            iy, ix, ih, iw = panel(win, y, x, 3, w, "imu", 6, "robot_box")
            put(win, iy, ix, "no IMU data ({})".format(r.status), c("warn"))
            return
        imu = r.imu
        lw = min(w, 66) if w >= 110 else w
        row = y
        iy, ix, ih, iw = panel(win, row, x, 6, lw, "orientation", 6, "robot_box", "IMU {:.0f}°C".format(imu.temp))
        rpy_lines(win, self.ut, iy, ix, iw)
        put(win, iy + 3, ix, "quat  w {:+.4f}  x {:+.4f}  y {:+.4f}  z {:+.4f}".format(*imu.quat),
            c("graph_text"), maxw=iw)
        row += 6
        iy, ix, ih, iw = panel(win, row, x, 10, lw, "inertial", None, "net_box",
                               "|a| {:.3f}".format(math.sqrt(sum(a * a for a in imu.acc))))
        subtitle(win, iy, ix, iw, "gyro rad/s", "net_box")
        for i, (n, v) in enumerate(zip("xyz", imu.gyro)):
            put(win, iy + 1 + i, ix, "{}  {:>+8.3f}".format(n, v), c("main_fg"))
            smeter(win, iy + 1 + i, ix + 14, iw - 14, v, 5.0)
        subtitle(win, iy + 4, ix, iw, "accel m/s²", "net_box")
        for i, (n, v) in enumerate(zip("xyz", imu.acc)):
            put(win, iy + 5 + i, ix, "{}  {:>+8.3f}".format(n, v), c("main_fg"))
            smeter(win, iy + 5 + i, ix + 14, iw - 14, v, 20.0)
        row += 10
        mh = y + h - row
        if mh >= 3:
            iy, ix, ih, iw = panel(win, row, x, mh, lw, "motion", None, "mem_box",
                                   r.sport.source if r.sport.valid else "")
            yy = iy
            if r.sport.valid and yy + 3 <= iy + ih:
                s = r.sport
                kv(win, yy, ix, iw, "mode/gait", "{} / {}   err {}   body_h {:.3f}m".format(
                    s.mode, s.gait, s.error_code, s.body_height))
                kv(win, yy + 1, ix, iw, "pos", "({:+.2f}, {:+.2f}, {:+.2f})".format(*s.position))
                kv(win, yy + 2, ix, iw, "vel", "({:+.2f}, {:+.2f}, {:+.2f})  wz {:+.2f}".format(
                    *(s.velocity + [s.yaw_speed])))
                yy += 3
            if r.foot_force and yy + 4 <= iy + ih:
                mx = max(max(r.foot_force), 100)
                for i, (leg, f) in enumerate(zip(("FR", "FL", "RR", "RL"), r.foot_force)):
                    meter_row(win, yy + i, ix, iw, leg, 100.0 * f / mx, "{}".format(int(f)), "cached", lw=3, vw=6)
                yy += 4
            if r.remote.valid and yy + 5 <= iy + ih:
                self._remote(win, yy, ix, r.remote)
        if lw < w:
            px, pw = x + lw, w - lw
            gh = h // 3
            hist = self.ut.history
            graph_panel(win, y, px, gh, pw, [v * DEG for v in hist.get("roll")], "roll",
                        "{:+.2f}°".format(imu.rpy[0] * DEG), gname="cpu", color="cpu_box",
                        scale_fmt="{:+.1f}", unit="°")
            graph_panel(win, y + gh, px, gh, pw, [v * DEG for v in hist.get("pitch")], "pitch",
                        "{:+.2f}°".format(imu.rpy[1] * DEG), gname="download", color="net_box",
                        scale_fmt="{:+.1f}", unit="°")
            graph_panel(win, y + 2 * gh, px, h - 2 * gh, pw, hist.get("gz"), "gyro z",
                        "{:+.3f}rad/s".format(imu.gyro[2]), gname="process", color="proc_box", scale_fmt="{:+.2f}")

    @staticmethod
    def _remote(win, y, x, rm):
        for k, (sx, sy, name) in enumerate(((rm.lx, rm.ly, "L"), (rm.rx, rm.ry, "R"))):
            bx = x + k * 12
            panel(win, y, bx, 5, 11, name, None, "div_line")
            cx = bx + 5 + int(round(max(-1, min(1, sx)) * 4))
            cy = y + 2 - int(round(max(-1, min(1, sy)) * 1))
            put(win, cy, cx, "●", c("warn", True))
        put(win, y + 1, x + 25, "buttons", c("graph_text"))
        put(win, y + 2, x + 25, " ".join(rm.buttons) or "-", c("title", True))


# ----------------------------------------------------------------------------
# 7 POWER
# ----------------------------------------------------------------------------

class PowerPage(Page):
    name = "power"

    def draw(self, win, y, x, h, w):
        r, ut = self.ut.robot, self.ut
        b = r.battery
        lw = min(w, 62) if w >= 110 else w
        iy, ix, ih, iw = panel(win, y, x, 6, lw, "battery", 7, "mem_box", b.source or "n/a")
        if ih > 0:
            battery_lines(win, ut, iy, ix, iw)
            extra = "cycles {}   status {}   fw {}".format(b.cycle, b.status, b.version or "-")
            if b.soh is not None:
                extra += "   SOH {}%".format(b.soh)
            put(win, iy + 2, ix, extra, c("main_fg"), maxw=iw)
            tx = ix
            if b.temps:
                tx += put(win, iy + 3, tx, "temps ", c("graph_text"))
                for t in b.temps:
                    tx += put(win, iy + 3, tx, "{:.0f}° ".format(t), temp_attr(t, crit=60))
        row = y + 6
        if b.cells:
            vmin, vmax = min(b.cells), max(b.cells)
            ch = min(len(b.cells) + 2, max(3, y + h - row - 4))
            iy, ix, ih, iw = panel(win, row, x, ch, lw, "cells", None, "cpu_box",
                                   "min {:.3f}  max {:.3f}  Δ {:.0f}mV".format(vmin, vmax, (vmax - vmin) * 1000))
            for i, cv in enumerate(b.cells[:max(ih, 0)]):
                pct = (cv - 3.0) / (4.25 - 3.0) * 100
                meter_row(win, iy + i, ix, iw, "c{}".format(i + 1), pct, "{:.3f}V".format(cv), "battery", lw=4, vw=8)
                if cv == vmin and vmax - vmin > 0.05:
                    put(win, iy + i, ix + iw - 9, "!", c("crit", True))
            row += ch
        if r.board and y + h - row >= 3:
            iy, ix, ih, iw = panel(win, row, x, y + h - row, lw, "robot board", None, "proc_box")
            for i, (k, v) in enumerate(list(r.board.items())[:ih]):
                kv(win, iy + i, ix, iw, k, v, 16)
        if lw < w:
            px, pw = x + lw, w - lw
            gh = h // 3
            hist = ut.history
            graph_panel(win, y, px, gh, pw, hist.get("bat_power"), "battery draw", "{:.1f}W".format(-b.power),
                        gname="process", color="proc_box", unit="W")
            graph_panel(win, y + gh, px, gh, pw, hist.get("bat_voltage"), "battery voltage",
                        "{:.2f}V".format(b.voltage), gname="battery", color="mem_box", scale_fmt="{:.2f}", unit="V")
            pwr = ut.gpu_stats.get("power", {})
            graph_panel(win, y + 2 * gh, px, h - 2 * gh, pw, hist.get("board_power"), "compute board",
                        "{:.1f}W".format(pwr.get("total", 0)) if pwr else "n/a", 0, None, "download", "net_box",
                        scale_fmt="{:.1f}", unit="W")


# ----------------------------------------------------------------------------
# 8 INFO
# ----------------------------------------------------------------------------

class InfoPage(Page):
    name = "info"

    def __init__(self, ut):
        Page.__init__(self, ut)
        self.scroll = 0

    def help(self):
        return [("↑↓", "scroll")]

    def key(self, ch):
        if ch in (curses.KEY_UP, ord("k")):
            self.scroll = max(0, self.scroll - 1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.scroll += 1
        elif ch == curses.KEY_NPAGE:
            self.scroll += 10
        elif ch == curses.KEY_PPAGE:
            self.scroll = max(0, self.scroll - 10)
        else:
            return False
        return True

    def draw(self, win, y, x, h, w):
        ut, r = self.ut, self.ut.robot
        s = ut._sys.static
        lw = min(w // 2, 64) if w >= 100 else w
        host = [("hostname", s.get("hostname")), ("distro", s.get("distro")), ("kernel", s.get("kernel")),
                ("arch", s.get("machine")), ("board", s.get("board")), ("python", s.get("python")),
                ("uptime", uptime(ut.stats.get("uptime", 0))),
                ("gpu backend", ut.gpu_backend.name if ut.gpu_backend else "-")]
        host += list(ut.gpu_stats.get("info", {}).items())
        host += [("note", e) for e in ut.gpu_errors[-2:]]
        host = [(k, v) for k, v in host if v not in (None, "")]
        robot = [("model", r.model.name if r.model else "?"), ("family", r.family), ("status", r.status),
                 ("interface", ut.interface or "auto"), ("domain", ut.domain), ("lowstate", r.lowstate_topic),
                 ("fw version", r.version), ("tick", r.tick),
                 ("motors", "{} active / {}".format(len(r.active_motors), len(r.motors)))]
        if r.error:
            robot.append(("error", r.error))
        robot += [("rate", "{:<26} {:>6.1f}Hz".format(t, hz)) for t, hz in sorted(r.rates.items())]
        hh = max(4, min(len(host) + 2, h - len(robot) - 2))
        iy, ix, ih, iw = panel(win, y, x, hh, lw, "host", 8, "cpu_box")
        for i, (k, v) in enumerate(host[:max(ih, 0)]):
            kv(win, iy + i, ix, iw, k, v, 14)
        rh = h - hh if lw < w else min(len(robot) + 2, h - hh)
        iy, ix, ih, iw = panel(win, y + hh, x, rh, lw, "robot", None, "robot_box")
        for i, (k, v) in enumerate(robot[:max(ih, 0)]):
            kv(win, iy + i, ix, iw, k, v, 14, status_attr(r.status) if k == "status" else None)
        if lw < w:
            tx, tw, ty, th = x + lw, w - lw, y, h
        else:
            tx, tw, ty, th = x, w, y + hh + rh, h - hh - rh
        if th < 3:
            return
        topics = sorted(r.topics.items())
        iy, ix, ih, iw = panel(win, ty, tx, th, tw, "dds topics", None, "net_box", str(len(topics)))
        self.scroll = min(self.scroll, max(0, len(topics) - ih))
        for i, (t, typ) in enumerate(topics[self.scroll:self.scroll + ih]):
            short = typ.split("::")[0] + "/" + typ.split("::")[-1] if "::" in typ else typ
            sub = t in r.rates
            put(win, iy + i, ix, "●" if sub else " ", c("ok", True))
            put(win, iy + i, ix + 2, "{:<34}".format(t), c("title", True) if sub else c("main_fg"), maxw=iw - 2)
            put(win, iy + i, ix + 37, short, c("graph_text"), maxw=max(0, iw - 37))


PAGES = [AllPage, CpuPage, GpuPage, SysPage, JointPage, ImuPage, PowerPage, InfoPage]
