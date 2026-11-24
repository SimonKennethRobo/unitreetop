"""Curses front-end (header + pages + tab bar), modelled on jtop's UI."""
import curses
import locale
import time

from .common import col, init_colors, put, uptime
from .pages import PAGES, status_attr


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
        if h < 10 or w < 40:
            put(scr, 0, 0, "terminal too small ({}x{})".format(w, h), col("red"))
            scr.refresh()
            return
        self.ut.want_procs = self.pages[self.page].name == "CPU"
        self._header(scr, w)
        try:
            self.pages[self.page].draw(scr, 2, 1, h - 3, w - 2)
        except Exception as e:  # keep the UI alive whatever a page does
            put(scr, 3, 1, "page error: {}".format(e), col("red"))
        self._tabbar(scr, h, w)
        scr.refresh()

    def _header(self, scr, w):
        ut, r = self.ut, self.ut.robot
        s = ut._sys.static
        x = put(scr, 0, 0, " unitreetop ", col("bg_green") | curses.A_BOLD)
        x += put(scr, 0, x, " {} ".format(s.get("hostname", "")), curses.A_BOLD)
        x += put(scr, 0, x, "│ ", col("dim"))
        mdl = r.model.name if r.model else "robot"
        x += put(scr, 0, x, "{} {} ".format(mdl, r.status.upper()), status_attr(r.status))
        if r.online and r.battery.valid:
            b = r.battery
            c = col("green") if b.soc > 40 else (col("yellow") if b.soc > 20 else col("red"))
            x += put(scr, 0, x, "│ ", col("dim"))
            x += put(scr, 0, x, "BAT {:.0f}% {:.1f}V {:+.1f}A ".format(b.soc, b.voltage, b.current), c)
        if r.online and r.motors:
            hot = max(r.active_motors or r.motors, key=lambda m: m.temp)
            x += put(scr, 0, x, "│ ", col("dim"))
            x += put(scr, 0, x, "hottest {} {:.0f}°C ".format(hot.name, hot.temp),
                     col("red") if hot.temp >= 75 else (col("yellow") if hot.temp >= 60 else 0))
        right = "CPU {:.0f}%  up {}  {}".format(ut.cpu.get("total", 0), uptime(ut.stats.get("uptime", 0)),
                                                time.strftime("%H:%M:%S"))
        if self.paused:
            right = "[PAUSED] " + right
        put(scr, 0, max(x + 1, w - len(right) - 1), right, col("dim"))

    def _tabbar(self, scr, h, w):
        y = h - 1
        x = 0
        self._tabs = []
        for i, p in enumerate(self.pages):
            label = " {}{} ".format(i + 1, p.name)
            attr = col("bg_cyan") | curses.A_BOLD if i == self.page else 0
            n = put(scr, y, x, label, attr)
            self._tabs.append((x, x + n, i))
            x += n
        p = self.cur
        rate = "+/-:{:g}Hz".format(p.hz)
        if self._fps and self._fps < p.hz * 0.9:  # say so when the terminal can't keep up
            rate += "(~{:.0f})".format(self._fps)
        hint = p.help()
        hint = (hint + "  " if hint else "") + "p:pause q:quit"
        hx = max(x + 1, w - len(hint) - len(rate) - 3)
        n = put(scr, y, hx, rate, col("yellow") | curses.A_BOLD)
        put(scr, y, hx + n + 2, hint, col("dim"))


def run_gui(ut, start_page=0):
    locale.setlocale(locale.LC_ALL, "")
    curses.wrapper(lambda scr: UnitreeTopGUI(scr, ut, start_page).run())
