"""Curses drawing helpers (bars, plots, boxes) in the spirit of jtop."""
import curses

BLOCKS = " ▁▂▃▄▅▆▇█"
C = {}  # color name -> attr


def init_colors():
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    names = [("red", curses.COLOR_RED), ("green", curses.COLOR_GREEN), ("yellow", curses.COLOR_YELLOW),
             ("blue", curses.COLOR_BLUE), ("magenta", curses.COLOR_MAGENTA), ("cyan", curses.COLOR_CYAN),
             ("white", curses.COLOR_WHITE)]
    for i, (n, col) in enumerate(names, 1):
        curses.init_pair(i, col, bg)
        C[n] = curses.color_pair(i)
    base = len(names) + 1
    for i, (n, col) in enumerate(names):
        curses.init_pair(base + i, curses.COLOR_BLACK, col)
        C["bg_" + n] = curses.color_pair(base + i)
    C["dim"] = curses.A_DIM
    C["bold"] = curses.A_BOLD


def col(name):
    return C.get(name, 0)


def put(win, y, x, text, attr=0, maxw=None):
    """addstr that never raises and clips to the window."""
    h, w = win.getmaxyx()
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


def level_color(pct, warn=60, crit=85):
    if pct >= crit:
        return col("red")
    if pct >= warn:
        return col("yellow")
    return col("green")


def bar(win, y, x, w, pct, label="", value=None, color=None, warn=60, crit=85, lw=None):
    """``LABEL [||||||||        value]``"""
    pct = max(0.0, min(100.0, pct if pct == pct else 0.0))
    if label:
        lw = lw or len(label) + 1
        put(win, y, x, label.ljust(lw)[:lw], col("cyan") | curses.A_BOLD)
        x += lw
        w -= lw
    inner = w - 2
    if inner < 3:
        return
    value = "{:.0f}%".format(pct) if value is None else value
    fill = int(round(inner * pct / 100.0))
    attr = color if color is not None else level_color(pct, warn, crit)
    put(win, y, x, "[")
    put(win, y, x + 1, "|" * fill, attr | curses.A_BOLD)
    put(win, y, x + 1 + fill, " " * (inner - fill))
    vx = x + 1 + inner - len(value)
    if vx > x:
        put(win, y, vx, value, curses.A_BOLD)
    put(win, y, x + inner + 1, "]")


def sbar(win, y, x, w, v, vmax, color=None):
    """Signed bar centred on zero: ``[    ███|      ]``"""
    inner = w - 2
    if inner < 3:
        return
    half = inner // 2
    v = max(-vmax, min(vmax, v)) if vmax else 0
    n = int(round(abs(v) / vmax * half)) if vmax else 0
    attr = color if color is not None else (col("magenta") if v < 0 else col("cyan"))
    cells = [" "] * inner
    cells[half] = "│"
    put(win, y, x, "[")
    put(win, y, x + 1, "".join(cells))
    if v < 0:
        put(win, y, x + 1 + half - n, "█" * n, attr)
    elif n:
        put(win, y, x + 2 + half, "█" * min(n, inner - half - 1), attr)
    put(win, y, x + inner + 1, "]")


def plot(win, y, x, h, w, values, vmin=None, vmax=None, color=None, title="", unit="", fmt="{:.1f}"):
    """Multi-row block chart of the most recent ``w`` samples, with frame and scale."""
    if h < 3 or w < 12:
        return
    vals = list(values)[-(w - 2):]
    box(win, y, x, h, w, title)
    if not vals:
        put(win, y + h // 2, x + 2, "no data", col("dim"))
        return
    lo = min(vals) if vmin is None else vmin
    hi = max(vals) if vmax is None else vmax
    if hi - lo < 1e-9:  # flat signal: centre it instead of pinning it to the floor
        pad = max(abs(hi) * 0.01, 1e-3)
        lo, hi = (lo if vmin is not None else lo - pad), (hi if vmax is not None else hi + pad)
        if hi - lo < 1e-9:
            hi = lo + 1.0
    rows = h - 2
    attr = color if color is not None else col("green")
    x0 = x + 1 + (w - 2 - len(vals))
    for i, v in enumerate(vals):
        lvl = (min(max(v, lo), hi) - lo) / (hi - lo) * rows * 8
        for r in range(rows):
            cell = lvl - r * 8
            ch = "█" if cell >= 8 else BLOCKS[int(max(cell, 0))]
            if ch != " ":
                put(win, y + h - 2 - r, x0 + i, ch, attr)
    hi_s, lo_s, cur = fmt.format(hi) + unit, fmt.format(lo) + unit, fmt.format(vals[-1]) + unit
    put(win, y, x + w - len(cur) - 3, " " + cur + " ", curses.A_BOLD)
    put(win, y + 1, x + 1, hi_s, col("dim"))
    put(win, y + h - 2, x + 1, lo_s, col("dim"))


def box(win, y, x, h, w, title="", attr=None):
    attr = col("blue") if attr is None else attr
    if h < 2 or w < 2:
        return
    put(win, y, x, "┌" + "─" * (w - 2) + "┐", attr)
    for r in range(1, h - 1):
        put(win, y + r, x, "│", attr)
        put(win, y + r, x + w - 1, "│", attr)
    put(win, y + h - 1, x, "└" + "─" * (w - 2) + "┘", attr)
    if title:
        put(win, y, x + 2, " " + title + " ", col("cyan") | curses.A_BOLD)


def size(n, suffix="B"):
    if n is None:
        return "-"
    n = float(n)
    for unit in ("", "k", "M", "G", "T"):
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


def temp_color(t, warn=60, crit=80):
    return level_color(t, warn, crit)
