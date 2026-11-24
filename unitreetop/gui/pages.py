"""Pages of the curses UI. Each page draws into the area between header and tab bar."""
import curses
import math

from .common import bar, box, col, plot, put, sbar, size, temp_color, uptime

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
        return ""


# ----------------------------------------------------------------------------
# shared widgets
# ----------------------------------------------------------------------------

def cpu_cores(win, ut, y, x, h, w):
    cores = ut.cpu.get("cores", [])
    if not cores:
        return 0
    ncol = 1 if (len(cores) <= h or w < 60) else 2
    per = int(math.ceil(len(cores) / float(ncol)))
    cw = w // ncol
    for i, c in enumerate(cores):
        r, k = i % per, i // per
        if r >= h:
            continue
        freq = " {:.1f}G".format(c["freq"] / 1000.0) if c["freq"] else ""
        bar(win, y + r, x + k * cw, cw - 1, c["load"], "{:>2}".format(i + 1),
            "{:.0f}%{}".format(c["load"], freq), lw=3)
    return min(per, h)


def mem_bars(win, ut, y, x, w):
    s = ut.stats
    m, sw, d = s.get("mem", {}), s.get("swap", {}), s.get("disk", {})
    n = 0
    if m:
        bar(win, y + n, x, w, m["percent"], "Mem", "{}/{}".format(size(m["used"]), size(m["total"])), lw=5)
        n += 1
    if sw and sw.get("total"):
        bar(win, y + n, x, w, sw["percent"], "Swp", "{}/{}".format(size(sw["used"]), size(sw["total"])), lw=5)
        n += 1
    if d:
        bar(win, y + n, x, w, d["percent"], "Dsk", "{}/{}".format(size(d["used"]), size(d["total"])),
            warn=80, crit=92, lw=5)
        n += 1
    return n


def gpu_bars(win, ut, y, x, w):
    n = 0
    for g in ut.gpu:
        val = "{:.0f}%".format(g["load"])
        if g.get("freq"):
            val += " {:.0f}MHz".format(g["freq"])
        bar(win, y + n, x, w, g["load"], "GPU", val, color=col("magenta") if g["load"] < 85 else col("red"), lw=5)
        n += 1
        if g.get("mem_total"):
            pct = 100.0 * g["mem_used"] / g["mem_total"]
            bar(win, y + n, x, w, pct, "VRM", "{}/{}".format(size(g["mem_used"]), size(g["mem_total"])), lw=5)
            n += 1
    return n


def battery_widget(win, ut, y, x, w):
    b = ut.robot.battery
    if not b.valid and not b.voltage:
        put(win, y, x, "Battery: no data", col("dim"))
        return 1
    if b.valid:
        color = col("green") if b.soc > 40 else (col("yellow") if b.soc > 20 else col("red"))
        bar(win, y, x, w, b.soc, "BAT", "{:.0f}%".format(b.soc), color=color, lw=5)
    else:
        put(win, y, x, "BAT  SOC n/a ({})".format(b.source), col("yellow"))
    state = "charging" if b.current > 0.05 else ("discharging" if b.current < -0.05 else "idle")
    put(win, y + 1, x, "     {:.2f}V {:+.2f}A {:.1f}W {}".format(b.voltage, b.current, abs(b.power), state))
    return 2


def status_attr(status):
    return {"online": col("green"), "demo": col("cyan"), "stale": col("yellow"),
            "waiting": col("yellow"), "discovering": col("yellow")}.get(status, col("red")) | curses.A_BOLD


def rpy_lines(win, ut, y, x, w):
    imu = ut.robot.imu
    for i, (n, v, rng) in enumerate(zip(("Roll", "Pitch", "Yaw"), imu.rpy, (45, 45, 180))):
        d = v * DEG
        put(win, y + i, x, "{:<5}{:>+8.2f}°".format(n, d), col("cyan"))
        sbar(win, y + i, x + 15, max(5, w - 15), d, rng)
    return 3


class JointScale:
    def __init__(self):
        self.tau = 5.0

    def update(self, motors):
        m = max([abs(j.tau) for j in motors] + [0.0])
        self.tau = max(self.tau * 0.995, m * 1.1, 5.0)


def joint_rows(win, motors, y, x, w, h, scale, sel=None, show_extra=True):
    """Compact joint table. Returns rows used."""
    if h < 2:
        return 0
    hdr = "{:>2} {:<16} {:>7} {:>7} {:>7} {:>4}".format("#", "joint", "q[rad]", "dq", "tau", "T°C")
    put(win, y, x, hdr, col("cyan") | curses.A_BOLD | curses.A_UNDERLINE)
    bw = w - len(hdr) - 1
    if bw >= 10 and show_extra:
        put(win, y, x + len(hdr) + 1, "tau".center(bw), col("cyan") | curses.A_BOLD | curses.A_UNDERLINE)
    n = 1
    for k, m in enumerate(motors):
        if n >= h:
            put(win, y + n - 1, x + w - 12, " (+{} more) ".format(len(motors) - k), col("yellow"))
            break
        attr = curses.A_REVERSE if sel is not None and k == sel else 0
        if not m.active:
            attr |= col("dim")
        line = "{:>2} {:<16} {:>+7.3f} {:>+7.2f} {:>+7.2f} ".format(m.index, m.name[:16], m.q, m.dq, m.tau)
        put(win, y + n, x, line, attr)
        put(win, y + n, x + len(line), "{:>4.0f}".format(m.temp), temp_color(m.temp, MOTOR_WARN, MOTOR_CRIT) | attr)
        if bw >= 10 and show_extra:
            sbar(win, y + n, x + len(hdr) + 1, bw, m.tau, scale)
        n += 1
    return n


# ----------------------------------------------------------------------------
# 1 ALL
# ----------------------------------------------------------------------------

class AllPage(Page):
    name = "ALL"

    def __init__(self, ut):
        Page.__init__(self, ut)
        self.scale = JointScale()

    def draw(self, win, y, x, h, w):
        ut, r = self.ut, self.ut.robot
        lw = w // 2 if w >= 100 else w
        # left: host
        ncores = len(ut.cpu.get("cores", []))
        core_rows = min(ncores if lw < 60 else int(math.ceil(ncores / 2.0)), max(1, h // 3))
        row = y
        row += cpu_cores(win, ut, row, x, core_rows, lw - 1)
        row += mem_bars(win, ut, row, x, lw - 1)
        row += gpu_bars(win, ut, row, x, lw - 1)
        temps = dict(ut.gpu_stats.get("temp", {}))
        if len(temps) < 3:
            temps.update(ut.stats.get("temp", {}))
        tline = "  ".join("{} {:.0f}°".format(k[:8], v) for k, v in list(temps.items())[:8])
        pw = ut.gpu_stats.get("power", {})
        if pw:
            tline = "Board {:.1f}W  ".format(pw.get("total", 0)) + tline
        put(win, row, x, tline, col("dim"), maxw=lw - 1)
        row += 1
        # right (or below): robot
        if lw < w:
            ry, rx, rw = y, x + lw + 1, w - lw - 1
        else:
            ry, rx, rw = row + 1, x, w
        rrow = ry
        mdl = r.model.name if r.model else "?"
        put(win, rrow, rx, "Robot ", col("cyan") | curses.A_BOLD)
        put(win, rrow, rx + 6, "{} [{}]".format(mdl, r.status), status_attr(r.status))
        rate = r.rates.get(r.lowstate_topic, 0.0)
        if r.lowstate_topic:
            put(win, rrow, rx + 8 + len(mdl) + len(r.status) + 2, "{} {:.0f}Hz".format(r.lowstate_topic, rate),
                col("dim"))
        rrow += 1
        if r.error:
            put(win, rrow, rx, r.error, col("red"), maxw=rw)
            rrow += 1
        if not r.online and r.status != "stale":
            put(win, rrow, rx, self._hint(r), col("yellow"), maxw=rw)
            return
        rrow += battery_widget(win, ut, rrow, rx, rw)
        rrow += rpy_lines(win, ut, rrow, rx, rw)
        if r.foot_force:
            put(win, rrow, rx, "Foot ", col("cyan"))
            put(win, rrow, rx + 5, " ".join("{:>5}".format(int(f)) for f in r.foot_force))
            rrow += 1
        if r.sport.valid:
            s = r.sport
            put(win, rrow, rx, "Sport mode {} gait {} v=({:+.2f},{:+.2f}) wz={:+.2f} h={:.2f}".format(
                s.mode, s.gait, s.velocity[0], s.velocity[1], s.yaw_speed, s.body_height), maxw=rw)
            rrow += 1
        if r.remote.valid:
            put(win, rrow, rx, "Remote L({:+.2f},{:+.2f}) R({:+.2f},{:+.2f}) {}".format(
                r.remote.lx, r.remote.ly, r.remote.rx, r.remote.ry, " ".join(r.remote.buttons)), maxw=rw)
            rrow += 1
        # joints across the bottom
        jy = max(row, rrow) + 1
        motors = r.active_motors
        self.scale.update(motors)
        rows_left = y + h - jy
        if rows_left < 3 or not motors:
            return
        if len(motors) + 1 > rows_left and w >= 2 * 62:
            half = int(math.ceil(len(motors) / 2.0))
            cw = w // 2
            joint_rows(win, motors[:half], jy, x, cw - 1, rows_left, self.scale.tau)
            joint_rows(win, motors[half:], jy, x + cw, cw - 1, rows_left, self.scale.tau)
        else:
            joint_rows(win, motors, jy, x, w, rows_left, self.scale.tau)

    @staticmethod
    def _hint(r):
        if r.status == "disabled":
            return "robot monitoring disabled"
        if r.status == "error":
            return "check --interface / CycloneDDS installation"
        if r.status in ("discovering", "waiting"):
            return "waiting for {} ... (is -i <iface> correct? domain id?)".format(r.lowstate_topic or "rt/lowstate")
        return ""


# ----------------------------------------------------------------------------
# 2 CPU
# ----------------------------------------------------------------------------

class CpuPage(Page):
    name = "CPU"

    def __init__(self, ut):
        Page.__init__(self, ut)
        self.sort = "cpu"

    def key(self, ch):
        if ch in (ord("s"),):
            self.sort = {"cpu": "mem", "mem": "pid", "pid": "cpu"}[self.sort]
            return True
        return False

    def help(self):
        return "s:sort({})".format(self.sort)

    def draw(self, win, y, x, h, w):
        ut = self.ut
        ph = max(6, h // 3)
        la = ut.cpu.get("load", (0, 0, 0))
        plot(win, y, x, ph, w, ut.history.get("cpu"), 0, 100, col("green"),
             "CPU total  load {:.2f} {:.2f} {:.2f}".format(*la), "%", "{:.0f}")
        row = y + ph
        ncores = len(ut.cpu.get("cores", []))
        crow = min(int(math.ceil(ncores / 2.0)) if w >= 60 else ncores, max(2, h // 3))
        row += cpu_cores(win, ut, row, x, crow, w)
        row += 1
        procs = list(ut.stats.get("procs", []))
        key = {"cpu": lambda p: -p["cpu"], "mem": lambda p: -p["mem"], "pid": lambda p: p["pid"]}[self.sort]
        procs.sort(key=key)
        hdr = "{:>7} {:<10} {:>6} {:>8} {:>4}  {}".format("PID", "USER", "CPU%", "MEM", "THR", "NAME")
        put(win, row, x, hdr.ljust(w), col("bg_cyan"))
        for i, p in enumerate(procs[: y + h - row - 1]):
            put(win, row + 1 + i, x, "{:>7} {:<10} {:>6.1f} {:>8} {:>4}  {}".format(
                p["pid"], p["user"], p["cpu"], size(p["mem"]), p["threads"], p["name"]), maxw=w)


# ----------------------------------------------------------------------------
# 3 GPU / board
# ----------------------------------------------------------------------------

class GpuPage(Page):
    name = "GPU"

    def draw(self, win, y, x, h, w):
        ut = self.ut
        gs = ut.gpu_stats
        gpus = ut.gpu
        row = y
        if not gpus:
            put(win, row, x, "No GPU backend ({})".format("; ".join(ut.gpu_errors) or "none"), col("yellow"),
                maxw=w)
            row += 2
        ph = max(6, (h // 2) // max(1, len(gpus))) if gpus else 0
        for i, g in enumerate(gpus):
            title = "{} {:.0f}/{:.0f}MHz".format(g["name"], g.get("freq") or 0, g.get("max_freq") or 0)
            if g.get("temp") is not None:
                title += " {:.0f}°C".format(g["temp"])
            if g.get("power") is not None:
                title += " {:.1f}W".format(g["power"])
            plot(win, row, x, ph, w, ut.history.get("gpu{}".format(i)), 0, 100, col("magenta"), title, "%", "{:.0f}")
            row += ph
            if g.get("mem_total"):
                bar(win, row, x, w, 100.0 * g["mem_used"] / g["mem_total"], "VRAM",
                    "{}/{}".format(size(g["mem_used"]), size(g["mem_total"])), lw=6)
                row += 1
        row += 1
        cw = w // 3
        # temperatures
        temps = dict(gs.get("temp", {})) or ut.stats.get("temp", {})
        put(win, row, x, "Temperatures", col("cyan") | curses.A_BOLD | curses.A_UNDERLINE)
        for i, (k, v) in enumerate(sorted(temps.items())[: y + h - row - 1]):
            put(win, row + 1 + i, x, "{:<16}".format(k[:16]))
            put(win, row + 1 + i, x + 17, "{:>6.1f}°C".format(v), temp_color(v))
        # power rails
        pw = gs.get("power", {})
        put(win, row, x + cw, "Power", col("cyan") | curses.A_BOLD | curses.A_UNDERLINE)
        prow = row + 1
        if pw:
            for k, v in sorted(pw.get("rails", {}).items()):
                put(win, prow, x + cw, "{:<16}{:>7.2f}W".format(k[:16], v), maxw=cw - 1)
                prow += 1
            put(win, prow, x + cw, "{:<16}{:>7.2f}W".format("TOTAL", pw.get("total", 0)), curses.A_BOLD)
            prow += 1
        else:
            put(win, prow, x + cw, "n/a", col("dim"))
        # misc
        put(win, row, x + 2 * cw, "Board", col("cyan") | curses.A_BOLD | curses.A_UNDERLINE)
        mrow = row + 1
        items = list(gs.get("info", {}).items()) + [("fan " + k, "{:.0f}%".format(v)) for k, v in gs.get("fan", {}).items()]
        items += [(k, v) for k, v in gs.get("engines", {}).items()]
        for k, v in items[: y + h - mrow]:
            put(win, mrow, x + 2 * cw, "{:<14}{}".format(k[:13], v), maxw=w - 2 * cw)
            mrow += 1


# ----------------------------------------------------------------------------
# 4 SYS (memory / disk / network)
# ----------------------------------------------------------------------------

class SysPage(Page):
    name = "MEM"

    def draw(self, win, y, x, h, w):
        ut = self.ut
        ph = max(6, h // 3)
        m = ut.stats.get("mem", {})
        plot(win, y, x, ph, w, ut.history.get("ram"), 0, 100, col("cyan"),
             "RAM {}/{}".format(size(m.get("used")), size(m.get("total"))), "%", "{:.0f}")
        row = y + ph
        row += mem_bars(win, ut, row, x, w) + 1
        put(win, row, x, "{:<12} {:<16} {:>4} {:>12} {:>12}".format("iface", "ipv4", "up", "rx/s", "tx/s").ljust(w),
            col("bg_cyan"))
        row += 1
        for name, n in sorted(ut.stats.get("net", {}).items()):
            if row >= y + h:
                break
            hl = curses.A_BOLD if name == ut.interface else 0
            put(win, row, x, "{:<12} {:<16} {:>4} {:>12} {:>12}".format(
                name[:12], n["ip"], "yes" if n["up"] else "no", size(n["rx"], "B/s"), size(n["tx"], "B/s")), hl)
            row += 1
        row += 1
        put(win, row, x, "uptime {}   load {:.2f} {:.2f} {:.2f}".format(
            uptime(ut.stats.get("uptime", 0)), *ut.cpu.get("load", (0, 0, 0))), col("dim"))


# ----------------------------------------------------------------------------
# 5 JOINTS
# ----------------------------------------------------------------------------

class JointPage(Page):
    name = "JOINTS"
    hz, hz_step, hz_min, hz_max = 50.0, 10.0, 10.0, 200.0

    def __init__(self, ut):
        Page.__init__(self, ut)
        self.sel = 0
        self.top = 0
        self.show_all = False
        self.scale = JointScale()

    def help(self):
        return "↑↓:select a:{}".format("hide idle" if self.show_all else "show idle")

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
        if not motors:
            put(win, y, x, "No joint data ({}).".format(r.status), col("yellow"))
            return
        self.scale.update(motors)
        self.sel = min(self.sel, len(motors) - 1)
        hg = any(m.vol is not None for m in motors)
        ph = 8 if h >= 24 else 0
        th = h - ph - 1
        rows = th - 1
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + rows:
            self.top = self.sel - rows + 1
        hdr = "{:>2} {:<18} {:>4} {:>8} {:>8} {:>8} {:>8} {:>5}".format(
            "#", "joint", "mode", "q[rad]", "q[deg]", "dq", "tau", "T°C")
        hdr += " {:>5} {:>6} {:>10}".format("T2", "V", "error") if hg else " {:>8}".format("lost")
        put(win, y, x, hdr.ljust(w), col("bg_cyan"))
        bx = x + len(hdr) + 1
        bw = (w - len(hdr) - 2) // 2
        if bw >= 8:
            put(win, y, bx, "q".center(bw) + " " + "tau".center(bw), col("bg_cyan"))
        for i, m in enumerate(motors[self.top:self.top + rows]):
            k = self.top + i
            attr = curses.A_REVERSE if k == self.sel else 0
            if not m.active:
                attr |= col("dim")
            line = "{:>2} {:<18} {:>4} {:>+8.3f} {:>+8.1f} {:>+8.2f} {:>+8.2f} ".format(
                m.index, m.name[:18], m.mode, m.q, m.q * 180 / math.pi, m.dq, m.tau)
            put(win, y + 1 + i, x, line, attr)
            cx = x + len(line)
            put(win, y + 1 + i, cx, "{:>5.0f}".format(m.temp), temp_color(m.temp, MOTOR_WARN, MOTOR_CRIT) | attr)
            cx += 5
            if hg:
                extra = " {:>5.0f} {:>6.2f} {:>10}".format(m.temp2 or 0, m.vol or 0,
                                                          "0x{:x}".format(m.error) if m.error else "-")
                put(win, y + 1 + i, cx, extra, (col("red") if m.error else 0) | attr)
            else:
                put(win, y + 1 + i, cx, " {:>8}".format(m.lost), attr)
            if bw >= 8:
                sbar(win, y + 1 + i, bx, bw, m.q, math.pi, col("green"))
                sbar(win, y + 1 + i, bx + bw + 1, bw, m.tau, self.scale.tau)
        if len(motors) > rows:
            put(win, y + th, x, " rows {}-{} of {} (↑↓ to scroll) ".format(
                self.top + 1, min(self.top + rows, len(motors)), len(motors)), col("yellow"))
        if ph:
            m = motors[self.sel]
            pw = w // 3
            py = y + h - ph
            hist = self.ut.history
            plot(win, py, x, ph, pw, hist.get("q{}".format(m.index)), None, None, col("green"),
                 "{} q".format(m.name), "", "{:+.2f}")
            plot(win, py, x + pw, ph, pw, hist.get("dq{}".format(m.index)), None, None, col("yellow"),
                 "dq", "", "{:+.2f}")
            plot(win, py, x + 2 * pw, ph, w - 2 * pw, hist.get("tau{}".format(m.index)), None, None, col("magenta"),
                 "tau", "Nm", "{:+.1f}")


# ----------------------------------------------------------------------------
# 6 IMU / motion
# ----------------------------------------------------------------------------

class ImuPage(Page):
    name = "IMU"
    hz, hz_step, hz_min, hz_max = 50.0, 10.0, 10.0, 200.0

    def draw(self, win, y, x, h, w):
        r = self.ut.robot
        if not r.online and r.status != "stale":
            put(win, y, x, "No IMU data ({}).".format(r.status), col("yellow"))
            return
        imu = r.imu
        lw = min(w, 64)
        row = y
        put(win, row, x, "Orientation", col("cyan") | curses.A_BOLD | curses.A_UNDERLINE)
        row += 1
        row += rpy_lines(win, self.ut, row, x, lw)
        put(win, row, x, "quat  w={:+.4f} x={:+.4f} y={:+.4f} z={:+.4f}".format(*imu.quat))
        row += 2
        put(win, row, x, "Gyroscope [rad/s]", col("cyan") | curses.A_BOLD | curses.A_UNDERLINE)
        row += 1
        for i, (n, v) in enumerate(zip("xyz", imu.gyro)):
            put(win, row, x, "{}  {:>+8.3f}".format(n, v))
            sbar(win, row, x + 14, lw - 14, v, 5.0)
            row += 1
        row += 1
        put(win, row, x, "Accelerometer [m/s²]  |a|={:.3f}".format(math.sqrt(sum(a * a for a in imu.acc))),
            col("cyan") | curses.A_BOLD | curses.A_UNDERLINE)
        row += 1
        for i, (n, v) in enumerate(zip("xyz", imu.acc)):
            put(win, row, x, "{}  {:>+8.3f}".format(n, v))
            sbar(win, row, x + 14, lw - 14, v, 20.0)
            row += 1
        put(win, row, x, "IMU temperature {:.0f}°C".format(imu.temp), col("dim"))
        row += 2
        # sport / foot / remote
        if r.sport.valid:
            s = r.sport
            put(win, row, x, "Sport state ({})".format(s.source), col("cyan") | curses.A_BOLD | curses.A_UNDERLINE)
            put(win, row + 1, x, "mode {}  gait {}  err {}  body_h {:.3f}m".format(s.mode, s.gait, s.error_code,
                                                                              s.body_height))
            put(win, row + 2, x, "pos ({:+.2f}, {:+.2f}, {:+.2f})  vel ({:+.2f}, {:+.2f}, {:+.2f})  wz {:+.2f}".format(
                *(s.position + s.velocity + [s.yaw_speed])), maxw=lw)
            row += 4
        if r.foot_force:
            put(win, row, x, "Foot force", col("cyan") | curses.A_BOLD | curses.A_UNDERLINE)
            mx = max(max(r.foot_force), 100)
            for i, (leg, f) in enumerate(zip(("FR", "FL", "RR", "RL"), r.foot_force)):
                bar(win, row + 1 + i, x, lw, 100.0 * f / mx, leg, "{}".format(int(f)), color=col("blue"), lw=3)
            row += 6
        if r.remote.valid and row + 6 < y + h:
            self._remote(win, row, x, r.remote)
        # plots on the right
        if w - lw > 30:
            px, pw = x + lw + 2, w - lw - 2
            ph = max(5, h // 3)
            hist = self.ut.history
            for i, (k, c, t) in enumerate((("roll", "green", "roll [rad]"), ("pitch", "yellow", "pitch [rad]"),
                                          ("gz", "magenta", "gyro z [rad/s]"))):
                plot(win, y + i * ph, px, ph, pw, hist.get(k), None, None, col(c), t, "", "{:+.3f}")

    @staticmethod
    def _remote(win, y, x, rm):
        put(win, y, x, "Wireless remote", col("cyan") | curses.A_BOLD | curses.A_UNDERLINE)
        for k, (sx, sy, name) in enumerate(((rm.lx, rm.ly, "L"), (rm.rx, rm.ry, "R"))):
            bx = x + k * 14
            box(win, y + 1, bx, 5, 11, name)
            cx = bx + 5 + int(round(max(-1, min(1, sx)) * 4))
            cy = y + 3 - int(round(max(-1, min(1, sy)) * 1))
            put(win, cy, cx, "●", col("yellow") | curses.A_BOLD)
        put(win, y + 2, x + 28, "buttons: " + (" ".join(rm.buttons) or "-"))


# ----------------------------------------------------------------------------
# 7 POWER
# ----------------------------------------------------------------------------

class PowerPage(Page):
    name = "POWER"

    def draw(self, win, y, x, h, w):
        r, ut = self.ut.robot, self.ut
        b = r.battery
        lw = min(w, 60) if w >= 100 else w
        row = y
        put(win, row, x, "Battery ({})".format(b.source or "n/a"), col("cyan") | curses.A_BOLD | curses.A_UNDERLINE)
        row += 1
        row += battery_widget(win, ut, row, x, lw)
        extra = "cycles {}  status {}  fw {}".format(b.cycle, b.status, b.version or "-")
        if b.soh is not None:
            extra += "  SOH {}%".format(b.soh)
        put(win, row, x, extra)
        row += 1
        if b.temps:
            put(win, row, x, "temps " + " ".join("{:.0f}°".format(t) for t in b.temps), col("dim"))
            row += 1
        row += 1
        if b.cells:
            vmin, vmax = min(b.cells), max(b.cells)
            put(win, row, x, "Cells  min {:.3f}V  max {:.3f}V  Δ {:.0f}mV".format(vmin, vmax, (vmax - vmin) * 1000),
                col("cyan") | curses.A_BOLD | curses.A_UNDERLINE)
            row += 1
            delta_attr = col("red") if vmax - vmin > 0.05 else None
            for i, c in enumerate(b.cells):
                if row >= y + h:
                    break
                pct = (c - 3.0) / (4.25 - 3.0) * 100
                bar(win, row, x, lw, pct, "c{:<2}".format(i + 1), "{:.3f}V".format(c),
                    color=delta_attr if c == vmin and delta_attr else col("green"), lw=4)
                row += 1
            row += 1
        if r.board and row < y + h:
            put(win, row, x, "Robot board", col("cyan") | curses.A_BOLD | curses.A_UNDERLINE)
            row += 1
            for k, v in r.board.items():
                if row >= y + h:
                    break
                put(win, row, x, "{:<16}{}".format(k, v), maxw=lw)
                row += 1
        # right: plots
        if lw < w:
            px, pw = x + lw + 2, w - lw - 2
            ph = max(5, h // 3)
            hist = ut.history
            plot(win, y, px, ph, pw, hist.get("bat_power"), None, None, col("yellow"), "battery power (draw)", "W",
                 "{:.0f}")
            plot(win, y + ph, px, ph, pw, hist.get("bat_voltage"), None, None, col("green"), "battery voltage", "V",
                 "{:.2f}")
            if hist.get("board_power"):
                plot(win, y + 2 * ph, px, ph, pw, hist.get("board_power"), 0, None, col("magenta"),
                     "compute board power", "W", "{:.1f}")


# ----------------------------------------------------------------------------
# 8 INFO
# ----------------------------------------------------------------------------

class InfoPage(Page):
    name = "INFO"

    def __init__(self, ut):
        Page.__init__(self, ut)
        self.scroll = 0

    def help(self):
        return "↑↓:scroll topics"

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
        lw = min(w // 2, 60) if w >= 100 else w
        rows = [("Host", None), ("hostname", s.get("hostname")), ("distro", s.get("distro")),
                ("kernel", s.get("kernel")), ("arch", s.get("machine")), ("board", s.get("board")),
                ("python", s.get("python")), ("uptime", uptime(ut.stats.get("uptime", 0))),
                ("gpu backend", ut.gpu_backend.name if ut.gpu_backend else "-")]
        for k, v in ut.gpu_stats.get("info", {}).items():
            rows.append((k, v))
        rows += [("", None), ("Robot", None), ("model", r.model.name if r.model else "?"),
                 ("family", r.family), ("status", r.status), ("interface", ut.interface or "auto"),
                 ("domain", ut.domain), ("lowstate", r.lowstate_topic), ("fw version", r.version),
                 ("tick", r.tick), ("motors", "{} active / {}".format(len(r.active_motors), len(r.motors)))]
        for t, hz in sorted(r.rates.items()):
            rows.append(("  rate", "{:<26} {:>7.1f} Hz".format(t, hz)))
        if r.error:
            rows.append(("error", r.error))
        for e in ut.gpu_errors[-3:]:
            rows.append(("gpu note", e))
        row = y
        for k, v in rows:
            if row >= y + h:
                break
            if v == "" or (v is None and not k):
                if not k:
                    row += 1
                continue
            if v is None:
                put(win, row, x, k, col("cyan") | curses.A_BOLD | curses.A_UNDERLINE)
            else:
                put(win, row, x, "{:<14}".format(k[:14]), col("dim"))
                put(win, row, x + 15, str(v), maxw=lw - 15)
            row += 1
        # topics
        if lw < w:
            tx, tw, ty, th = x + lw + 2, w - lw - 2, y, h
        else:
            tx, tw, ty, th = x, w, row + 1, y + h - row - 1
        topics = sorted(r.topics.items())
        put(win, ty, tx, "DDS topics ({})".format(len(topics)), col("cyan") | curses.A_BOLD | curses.A_UNDERLINE)
        self.scroll = min(self.scroll, max(0, len(topics) - (th - 1)))
        for i, (t, typ) in enumerate(topics[self.scroll:self.scroll + th - 1]):
            short = typ.split("::")[0] + "/" + typ.split("::")[-1] if "::" in typ else typ
            attr = curses.A_BOLD if t in r.rates else 0
            put(win, ty + 1 + i, tx, "{:<34} {}".format(t, short), attr, maxw=tw)


PAGES = [AllPage, CpuPage, GpuPage, SysPage, JointPage, ImuPage, PowerPage, InfoPage]
