"""btop-style drawing primitives: theme, gradient meters, braille graphs, rounded panels.

Colors follow btop's "Default" theme. With a 256-color terminal every hex color is
mapped to the nearest xterm-256 entry; on 8-color terminals to the nearest basic color.
Pairs are allocated lazily and cached (Python's color_pair() only encodes 255 pairs).
"""
import curses

SUPERSCRIPT = "⁰¹²³⁴⁵⁶⁷⁸⁹"

THEME = {
    "main_fg": "#cccccc",
    "title": "#eeeeee",
    "hi_fg": "#b54040",          # hotkey letters / numbers
    "selected_bg": "#6a2f2f",
    "selected_fg": "#eeeeee",
    "inactive_fg": "#404040",
    "graph_text": "#606060",
    "meter_bg": "#404040",
    "proc_misc": "#0de756",
    "div_line": "#303030",
    "cpu_box": "#556d59",
    "mem_box": "#6c6c4b",
    "net_box": "#5c588d",
    "proc_box": "#805252",
    "robot_box": "#4f6a8a",
    "ok": "#77ca9b",
    "warn": "#cbc06c",
    "crit": "#dc4c4c",
    "label": "#8a9bb0",
}

GRADIENTS = {
    "cpu": ["#77ca9b", "#cbc06c", "#dc4c4c"],
    "temp": ["#4897d4", "#5474e8", "#ff40b6"],
    "free": ["#384f21", "#b5e685"],
    "cached": ["#163350", "#74e6fc"],
    "available": ["#4e3f0e", "#ffd77a"],
    "used": ["#592b26", "#ff7f6e"],
    "download": ["#291f75", "#4f43a3", "#b0a9de"],
    "upload": ["#620665", "#7d4180", "#dcafde"],
    "process": ["#80d0a3", "#dcd179", "#d45454"],
    "battery": ["#dc4c4c", "#cbc06c", "#77ca9b"],   # low SOC red -> full green
    "pos": ["#2b4a5c", "#74c7ec"],                  # signed bars, positive side
    "neg": ["#5c2b4a", "#e88ad0"],                  # signed bars, negative side
    "gpu": ["#6c4bb0", "#b07ee8", "#ff8ad8"],
}
STEPS = 12


class _Palette:
    def __init__(self):
        self.ok = False
        self.n256 = False
        self.pairs = {}
        self.next_pair = 1
        self.limit = 255

    def init(self):
        curses.start_color()
        try:
            curses.use_default_colors()
            self.bg = -1
        except curses.error:
            self.bg = curses.COLOR_BLACK
        self.n256 = curses.COLORS >= 256
        self.limit = min(255, curses.COLOR_PAIRS - 1)
        self.ok = True

    def color_index(self, hexstr):
        r, g, b = (int(hexstr[i:i + 2], 16) for i in (1, 3, 5))
        if not self.n256:
            # nearest of the 8 basic colors (brightness folded in with A_BOLD by callers)
            basic = [(0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238), (205, 0, 205),
                     (0, 205, 205), (229, 229, 229)]
            m = max(r, g, b) or 1
            k = 1.0 if m < 60 else 205.0 / m  # compare hue, not brightness
            rr, gg, bb = r * k, g * k, b * k
            return min(range(8), key=lambda i: (basic[i][0] - rr) ** 2 + (basic[i][1] - gg) ** 2 +
                       (basic[i][2] - bb) ** 2)
        levels = [0, 95, 135, 175, 215, 255]

        def q(v):
            return min(range(6), key=lambda i: abs(levels[i] - v))
        ci = 16 + 36 * q(r) + 6 * q(g) + q(b)
        cr, cg, cb = levels[q(r)], levels[q(g)], levels[q(b)]
        gray = int(round((r + g + b) / 3.0))
        gi = max(0, min(23, int(round((gray - 8) / 10.0))))
        gv = 8 + gi * 10
        d_cube = (cr - r) ** 2 + (cg - g) ** 2 + (cb - b) ** 2
        d_gray = (gv - r) ** 2 + (gv - g) ** 2 + (gv - b) ** 2
        return 232 + gi if d_gray < d_cube else ci

    def attr(self, fg, bg=None):
        if not self.ok:
            return 0
        key = (fg, bg)
        a = self.pairs.get(key)
        if a is not None:
            return a
        if self.next_pair > self.limit:
            return 0
        fi = self.color_index(fg) if fg else -1
        bi = self.color_index(bg) if bg else self.bg
        try:
            curses.init_pair(self.next_pair, fi, bi)
            a = curses.color_pair(self.next_pair)
        except curses.error:
            a = 0
        self.next_pair += 1
        self.pairs[key] = a
        return a


PAL = _Palette()
_GRAD_CACHE = {}


def init_colors():
    PAL.init()
    _GRAD_CACHE.clear()
    for name in GRADIENTS:  # pre-allocate so pair ids are stable
        _grad_table(name)


def c(name, bold=False):
    """Theme color attribute by name."""
    a = PAL.attr(THEME[name])
    if bold or not PAL.n256 and name in ("title", "hi_fg"):
        a |= curses.A_BOLD
    return a


def bg(fg_name, bg_name):
    return PAL.attr(THEME[fg_name], THEME[bg_name])


def _lerp(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join("{:02x}".format(int(round(x + (y - x) * t))) for x, y in zip(a, b))


def _grad_table(name):
    stops = GRADIENTS[name]
    table = []
    for step in range(STEPS):
        t = step / (STEPS - 1.0) * (len(stops) - 1)
        i = min(int(t), len(stops) - 2)
        table.append(PAL.attr(_lerp(stops[i], stops[i + 1], t - i)))
    _GRAD_CACHE[name] = table
    return table


def grad(name, frac):
    """Attribute for position ``frac`` (0..1) along a named gradient (hot path: table lookup)."""
    table = _GRAD_CACHE.get(name) or _grad_table(name)
    if frac >= 1.0:
        return table[-1]
    if frac > 0.0:
        return table[int(frac * (STEPS - 1) + 0.5)]
    return table[0]  # also NaN


# compat helpers used by older code paths
def col(name):
    return {"red": c("crit"), "green": c("ok"), "yellow": c("warn"), "cyan": c("label"),
            "blue": c("net_box"), "magenta": grad("gpu", 1), "white": c("title"),
            "dim": c("inactive_fg")}.get(name, 0)


_DIMS = [None]


def set_dims(h, w):
    """Cache the screen size for the current frame (put() is the hottest function)."""
    _DIMS[0] = (h, w)


def put(win, y, x, text, attr=0, maxw=None):
    """addstr that never raises and clips to the window. Returns chars written."""
    h, w = _DIMS[0] or win.getmaxyx()
    if y < 0 or y >= h or x >= w or x < 0:
        return 0
    room = w - x - (1 if y == h - 1 else 0)
    if maxw is not None:
        room = min(room, maxw)
    if room <= 0:
        return 0
    s = str(text)[:room]
    try:
        win.addstr(y, x, s, attr)
    except curses.error:
        pass
    return len(s)


# ----------------------------------------------------------------------------
# panels
# ----------------------------------------------------------------------------

def panel(win, y, x, h, w, title="", key=None, color="cpu_box", right=""):
    """Rounded box with btop-style title ``╭─┐¹title┌───┐right┌─╮``. Returns inner rect."""
    if h < 2 or w < 4:
        return y, x, 0, 0
    a = c(color)
    put(win, y, x, "╭" + "─" * (w - 2) + "╮", a)
    for r in range(1, h - 1):
        put(win, y + r, x, "│", a)
        put(win, y + r, x + w - 1, "│", a)
    put(win, y + h - 1, x, "╰" + "─" * (w - 2) + "╯", a)
    if title:
        tx = x + 2
        tx += put(win, y, tx, "┐", a)
        if key is not None:
            tx += put(win, y, tx, SUPERSCRIPT[key % 10], c("hi_fg", True))
        tx += put(win, y, tx, title, c("title", True))
        put(win, y, tx, "┌", a)
    if right:
        rx = x + w - 3 - len(right)
        if rx > x + len(title) + 6:
            put(win, y, rx - 1, "┐", a)
            put(win, y, rx, right, c("title"))
            put(win, y, rx + len(right), "┌", a)
    return y + 1, x + 1, h - 2, w - 2


def subtitle(win, y, x, w, text, color="cpu_box"):
    """Horizontal divider with a label: ``─┐text┌────``"""
    a = c(color)
    put(win, y, x, "─" * w, a)
    put(win, y, x + 1, "┐", a)
    n = put(win, y, x + 2, text, c("title", True))
    put(win, y, x + 2 + n, "┌", a)


# ----------------------------------------------------------------------------
# meters & graphs
# ----------------------------------------------------------------------------

def _runs(win, y, x, n, attr_of, ch="■", reverse=False):
    """Draw ``n`` cells, batching consecutive cells that share a colour into one addstr."""
    i = 0
    while i < n:
        a = attr_of(i)
        j = i + 1
        while j < n and attr_of(j) == a:
            j += 1
        if reverse:  # cells grow leftwards from x
            put(win, y, x - j + 1, ch * (j - i), a)
        else:
            put(win, y, x + i, ch * (j - i), a)
        i = j


def meter(win, y, x, w, pct, gname="cpu"):
    """btop meter: ``■■■■■■■■■■■■`` filled cells coloured along the gradient."""
    if w <= 0:
        return
    pct = 0.0 if pct != pct else max(0.0, min(100.0, pct))
    fill = int(round(w * pct / 100.0))
    _runs(win, y, x, fill, lambda i: grad(gname, (i + 1) / float(w)))
    if fill < w:
        put(win, y, x + fill, "■" * (w - fill), c("meter_bg"))


def meter_row(win, y, x, w, label, pct, value, gname="cpu", lw=None, vw=None):
    """``label ■■■■■■■■■■ value`` on one line."""
    lw = lw if lw is not None else len(label) + 1
    vw = vw if vw is not None else len(value) + 1
    put(win, y, x, label[:lw].ljust(lw), c("main_fg"))
    mw = w - lw - vw
    if mw >= 3:
        meter(win, y, x + lw, mw, pct, gname)
    put(win, y, x + w - vw, value.rjust(vw)[:vw], c("main_fg"))


def smeter(win, y, x, w, v, vmax):
    """Signed meter centred at zero (negative to the left, positive to the right)."""
    if w < 3:
        return
    half = (w - 1) // 2
    v = 0.0 if v != v else v
    frac = min(1.0, abs(v) / vmax) if vmax else 0.0
    n = int(round(frac * half))
    put(win, y, x, "■" * half, c("meter_bg"))
    put(win, y, x + half, "┃", c("graph_text"))
    put(win, y, x + half + 1, "■" * (w - half - 1), c("meter_bg"))
    if v < 0:
        _runs(win, y, x + half - 1, n, lambda i: grad("neg", (i + 1) / float(half)), reverse=True)
    else:
        _runs(win, y, x + half + 1, n, lambda i: grad("pos", (i + 1) / float(half)))


_LEFT = (0x40, 0x04, 0x02, 0x01)   # braille dots of the left column, bottom -> top
_RIGHT = (0x80, 0x20, 0x10, 0x08)


def graph(win, y, x, h, w, values, vmin=None, vmax=None, gname="cpu", invert=False):
    """Braille area graph: 2 samples per cell horizontally, 4 levels per cell vertically.

    Rows are coloured along ``gname`` by height (bottom = start of gradient).
    ``invert`` draws hanging from the top (btop's upload graph style).
    """
    if h <= 0 or w <= 0:
        return
    vals = list(values)[-(2 * w):]
    if not vals:
        return
    lo = min(vals) if vmin is None else vmin
    hi = max(vals) if vmax is None else vmax
    if hi - lo < 1e-9:
        pad = max(abs(hi) * 0.01, 1e-3)
        if vmin is None:
            lo -= pad
        if vmax is None:
            hi += pad
        if hi - lo < 1e-9:
            hi = lo + 1.0
    levels = h * 4
    k = levels / (hi - lo)
    # level per sample; a value above the floor always shows at least one dot
    lv = [levels if v >= hi else ((int((v - lo) * k + 0.5) or 1) if v > lo else 0) for v in vals]
    if len(lv) % 2:
        lv.insert(0, 0)
    left, right = lv[0::2], lv[1::2]
    ncell = len(left)
    x0 = x + w - ncell
    lut = _LUT_INV if invert else _LUT
    # clamp table: CL[v + levels] == min(4, max(0, v)) for v in [-levels, levels]
    cl = [min(4, max(0, v)) for v in range(-levels, levels + 1)]
    for r in range(h):  # r = 0 is the bottom row
        off = levels - r * 4
        s = "".join([lut[cl[a + off]][cl[b + off]] for a, b in zip(left, right)])
        st = s.lstrip(" ")
        if not st:
            continue
        attr = grad(gname, (r + 0.5) / h)
        row_y = y + r if invert else y + h - 1 - r
        # blanks inside the run are harmless (erase() already cleared the cell)
        put(win, row_y, x0 + len(s) - len(st), st.rstrip(" "), attr)


def _build_lut(invert):
    lut = []
    for na in range(5):
        row = []
        for nb in range(5):
            bits = 0
            for k in range(na):
                bits |= _LEFT[3 - k] if invert else _LEFT[k]
            for k in range(nb):
                bits |= _RIGHT[3 - k] if invert else _RIGHT[k]
            row.append(chr(0x2800 + bits) if bits else " ")
        lut.append(row)
    return lut


_LUT = _build_lut(False)
_LUT_INV = _build_lut(True)


def graph_panel(win, y, x, h, w, values, title, value_text="", vmin=None, vmax=None, gname="cpu",
                color="cpu_box", key=None, scale_fmt="{:.0f}", unit=""):
    """Panel containing a braille graph with min/max labels."""
    iy, ix, ih, iw = panel(win, y, x, h, w, title, key, color, value_text)
    if ih <= 0:
        return
    vals = list(values)
    graph(win, iy, ix, ih, iw, vals, vmin, vmax, gname)
    if vals:
        lo = min(vals[-2 * iw:]) if vmin is None else vmin
        hi = max(vals[-2 * iw:]) if vmax is None else vmax
        hs, ls = scale_fmt.format(hi), scale_fmt.format(lo)
        if hs == ls and hi != lo:  # tiny range: show enough decimals to tell them apart
            hs, ls = "{:+.4f}".format(hi), "{:+.4f}".format(lo)
        put(win, iy, ix, hs + unit, c("graph_text"))
        if ih > 1:
            put(win, iy + ih - 1, ix, ls + unit, c("graph_text"))
    else:
        put(win, iy + ih // 2, ix + max(0, iw // 2 - 3), "no data", c("inactive_fg"))


# ----------------------------------------------------------------------------
# formatting
# ----------------------------------------------------------------------------

def size(n, suffix="B"):
    if n is None:
        return "-"
    n = float(n)
    for unit in ("", "K", "M", "G", "T"):
        if abs(n) < 1024.0:
            return "{:.1f}{}{}".format(n, unit, suffix) if unit else "{:.0f}{}".format(n, suffix)
        n /= 1024.0
    return "{:.1f}P{}".format(n, suffix)


def uptime(sec):
    sec = int(sec)
    d, sec = divmod(sec, 86400)
    h, sec = divmod(sec, 3600)
    m, s = divmod(sec, 60)
    return ("{}d ".format(d) if d else "") + "{:02d}:{:02d}:{:02d}".format(h, m, s)


def temp_attr(t, warn=60.0, crit=85.0):
    """Temperature colour: blue (cool) -> purple -> pink (hot)."""
    return grad("temp", (t - 20.0) / max(crit - 20.0, 1.0))


def level_attr(t, warn, crit):
    if t >= crit:
        return c("crit", True)
    if t >= warn:
        return c("warn")
    return c("main_fg")
