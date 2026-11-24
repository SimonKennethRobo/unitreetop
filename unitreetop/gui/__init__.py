"""Curses front-end (header + pages + tab bar), modelled on jtop's UI."""
import curses
import locale
import time

from .common import SUPERSCRIPT, bg, c, grad, init_colors, put, set_dims, uptime
from .pages import PAGES, motor_temp_attr, status_attr


class UnitreeTopGUI:
    def __init__(self, stdscr, ut, start_page=0):
        self.scr = stdscr
        self.ut = ut
        self.pages = [P(ut) for P in PAGES]
        self.page = max(0, min(start_page, len(self.pages) - 1))
        self.paused = False
        self._tabs = []  # (x0, x1, index) for mouse clicks
        self._last_full = 0.0
        self._next_draw = 0.0
        self._fps = 0.0
        self._last_frame = None
        init_colors()
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
        stdscr.keypad(True)
        self._apply_rate()

    @property
    def cur(self):
        return self.pages[self.page]

    def _apply_rate(self):
        """Robot snapshots follow the screen rate so a 100 Hz page shows 100 Hz data."""
        self.ut.robot_hz = max(self.ut.robot_hz_base, self.cur.hz)
        self._next_draw = 0.0
        self._last_frame = None
        self._fps = 0.0

    def _change_rate(self, sign):
        p = self.cur
        p.hz = max(p.hz_min, min(p.hz_max, p.hz + sign * p.hz_step))
        self._apply_rate()

    def run(self):
        while True:
            now = time.monotonic()
            if now >= self._next_draw:
                if not self.paused:
                    self.draw()
                    if self._last_frame is not None:
                        dt = now - self._last_frame
                        self._fps = 1.0 / dt if not self._fps else 0.9 * self._fps + 0.1 / max(dt, 1e-6)
                    self._last_frame = now
                period = 1.0 / self.cur.hz
                self._next_draw = max(self._next_draw + period, now)  # no catch-up bursts
                if self._next_draw <= now:
                    self._next_draw = now + period
            self.scr.timeout(max(1, int((self._next_draw - time.monotonic()) * 1000)))
            ch = self.scr.getch()
            if ch == -1:
                continue
            page_before = self.page
            if ch in (ord("q"), ord("Q"), 27):
                return
            if ord("1") <= ch <= ord("9") and ch - ord("1") < len(self.pages):
                self.page = ch - ord("1")
            elif ch in (curses.KEY_RIGHT, ord("\t"), ord("l")):
                self.page = (self.page + 1) % len(self.pages)
            elif ch in (curses.KEY_LEFT, curses.KEY_BTAB, ord("h")):
                self.page = (self.page - 1) % len(self.pages)
            elif ch == ord("p"):
                self.paused = not self.paused
            elif ch in (ord("+"), ord("="), getattr(curses, "KEY_PLUS", -2)):
                self._change_rate(+1)
            elif ch in (ord("-"), ord("_"), getattr(curses, "KEY_MINUS", -2)):
                self._change_rate(-1)
            elif ch == curses.KEY_MOUSE:
                self._mouse()
            elif ch == curses.KEY_RESIZE:
                self.scr.erase()
            else:
                self.cur.key(ch)
            if self.page != page_before:
                self._apply_rate()
            self.draw()  # immediate feedback for any key; the schedule is unchanged

    def _mouse(self):
        try:
            _, mx, my, _, state = curses.getmouse()
        except curses.error:
            return
        h, _ = self.scr.getmaxyx()
        if my == h - 1:
            for x0, x1, i in self._tabs:
                if x0 <= mx < x1:
                    self.page = i
                    self._apply_rate()
                    return

    def draw(self):
        scr = self.scr
        scr.erase()
        now = time.monotonic()
        if now - self._last_full > 2.0:
            # repaint everything now and then: wall/syslog broadcasts (common on the
            # robots' Jetson) write straight to the tty behind curses' back
            scr.redrawwin()
            self._last_full = now
        h, w = scr.getmaxyx()
        set_dims(h, w)
        if h < 12 or w < 60:
            put(scr, 0, 0, "terminal too small ({}x{}), need 60x12".format(w, h), c("crit", True))
            scr.refresh()
            return
        self.ut.want_procs = self.cur.name == "cpu"
        self._header(scr, w)
        try:
            self.cur.draw(scr, 1, 0, h - 2, w)
        except Exception as e:  # keep the UI alive whatever a page does
            put(scr, 2, 2, "page error: {}".format(e), c("crit", True))
        self._menu(scr, h, w)
        scr.refresh()

    def _sep(self, scr, x):
        return put(scr, 0, x, " │ ", c("div_line"))

    def _header(self, scr, w):
        ut, r = self.ut, self.ut.robot
        s = ut._sys.static
        x = put(scr, 0, 0, " unitree", c("hi_fg", True))
        x += put(scr, 0, x, "top", c("title", True))
        x += put(scr, 0, x, "  " + s.get("hostname", ""), c("main_fg"))
        x += self._sep(scr, x)
        mdl = r.model.name if r.model else "robot"
        x += put(scr, 0, x, "● ", status_attr(r.status))
        x += put(scr, 0, x, mdl + " ", c("title", True))
        x += put(scr, 0, x, r.status, status_attr(r.status))
        if r.online and r.battery.valid:
            b = r.battery
            x += self._sep(scr, x)
            x += put(scr, 0, x, "BAT ", c("graph_text"))
            x += put(scr, 0, x, "{:.0f}%".format(b.soc), grad("battery", b.soc / 100.0) | curses.A_BOLD)
            x += put(scr, 0, x, " {:.1f}V {:+.1f}A".format(b.voltage, b.current), c("main_fg"))
        if r.online and r.motors:
            hot = max(r.active_motors or r.motors, key=lambda m: m.temp)
            x += self._sep(scr, x)
            x += put(scr, 0, x, "hottest ", c("graph_text"))
            x += put(scr, 0, x, "{} {:.0f}°C".format(hot.name, hot.temp), motor_temp_attr(hot.temp))
        right = time.strftime("%H:%M:%S")
        info = "up {}  ".format(uptime(ut.stats.get("uptime", 0)))
        if self.paused:
            info = "PAUSED  " + info
        rx = w - len(right) - 1
        if rx - len(info) > x + 2:
            put(scr, 0, rx - len(info), info, c("warn", True) if self.paused else c("graph_text"))
        if rx > x + 1:
            put(scr, 0, rx, right, c("title", True))

    def _menu(self, scr, h, w):
        y = h - 1
        x = 1
        self._tabs = []
        for i, p in enumerate(self.pages):
            sel = i == self.page
            x0 = x
            a_key = bg("hi_fg", "selected_bg") | curses.A_BOLD if sel else c("hi_fg", True)
            a_txt = bg("selected_fg", "selected_bg") | curses.A_BOLD if sel else c("main_fg")
            x += put(scr, y, x, " " + SUPERSCRIPT[i + 1], a_key)
            x += put(scr, y, x, p.name + " ", a_txt)
            self._tabs.append((x0, x, i))
        p = self.cur
        items = [("+-", "{:g}Hz".format(p.hz) + ("(~{:.0f})".format(self._fps)
                                                  if self._fps and self._fps < p.hz * 0.9 else ""))]
        items += list(p.help()) + [("p", "pause"), ("q", "quit")]
        text_len = sum(len(k) + len(t) + 3 for k, t in items)
        hx = max(x + 2, w - text_len - 1)
        for k, t in items:
            if hx + len(k) + len(t) + 2 > w:
                break
            hx += put(scr, y, hx, k, c("hi_fg", True))
            hx += put(scr, y, hx, " " + t + "  ", c("warn", True) if k == "+-" else c("graph_text"))


def run_gui(ut, start_page=0):
    locale.setlocale(locale.LC_ALL, "")
    curses.wrapper(lambda scr: UnitreeTopGUI(scr, ut, start_page).run())
