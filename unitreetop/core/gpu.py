"""GPU / board backends.

* ``JtopBackend``   - Jetson with jetson_stats installed and jtop.service running
                      (gives GPU, power rails, thermal zones, fan, nvpmodel, engines).
* ``TegraBackend``  - Jetson without jtop: reads GPU load / freq from sysfs.
* ``NvidiaBackend`` - desktop/dGPU: NVML (pynvml) or ``nvidia-smi``.

Every backend returns the same shape from ``read()``::

    {"gpus": [{"name", "load", "freq", "max_freq", "mem_used", "mem_total", "temp", "power"}],
     "power": {"rails": {name: watts}, "total": watts} | {},
     "temp": {name: C}, "fan": {name: pct}, "info": {...}, "engines": {name: str}}
"""
import glob
import os
import shutil
import subprocess


def _read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


class NullBackend:
    name = "none"

    def read(self):
        return {"gpus": [], "power": {}, "temp": {}, "fan": {}, "info": {}, "engines": {}}

    def close(self):
        pass


class JtopBackend(NullBackend):
    name = "jtop"

    def __init__(self):
        from jtop import jtop  # noqa
        self._j = jtop(interval=1.0)
        self._j.start()
        info = {}
        board = self._j.board or {}
        hw = board.get("hardware", {})
        for k in ("Model", "Module", "SoC", "L4T", "Jetpack", "CUDA Arch BIN"):
            v = str(hw.get(k, "")).strip()
            if v:
                info[k] = v
        for k, v in (board.get("libraries") or {}).items():
            if v:
                info[k] = str(v)
        self._info = info

    def read(self):
        j = self._j
        if hasattr(j, "is_alive") and not j.is_alive():
            raise RuntimeError("jtop service connection lost")
        out = NullBackend.read(self)
        for name, g in (j.gpu or {}).items():
            st, fr = g.get("status", {}), g.get("freq", {})
            out["gpus"].append({
                "name": name, "load": float(st.get("load", 0.0)),
                "freq": fr.get("cur", 0) / 1000.0, "max_freq": fr.get("max", 0) / 1000.0,
                "mem_used": None, "mem_total": None, "temp": None, "power": None,
            })
        pw = j.power or {}
        rails = {k: v.get("power", 0) / 1000.0 for k, v in pw.get("rail", {}).items() if v.get("online", True)}
        tot = pw.get("tot", {})
        out["power"] = {"rails": rails, "total": tot.get("power", 0) / 1000.0 if tot else sum(rails.values())}
        out["temp"] = {k: v["temp"] for k, v in (j.temperature or {}).items()
                       if v.get("online", True) and v.get("temp", -256) > -100}
        for name, f in (j.fan or {}).items():
            sp = f.get("speed") or []
            if sp:
                out["fan"][name] = sp[0]
        info = dict(self._info)
        try:
            info["nvpmodel"] = str(j.nvpmodel)
            info["jetson_clocks"] = "on" if j.jetson_clocks else "off"
        except Exception:
            pass
        out["info"] = info
        engines = {}
        for group, items in (j.engine or {}).items():
            for name, e in items.items():
                if e.get("online"):
                    engines[name] = "{:.0f}MHz".format(e.get("cur", 0) / 1000.0)
        out["engines"] = engines
        if j.memory and "EMC" in j.memory:
            emc = j.memory["EMC"]
            out["info"]["EMC"] = "{:.0f}%".format(emc.get("val", 0))
        return out

    def close(self):
        try:
            self._j.close()
        except Exception:
            pass


class TegraBackend(NullBackend):
    name = "tegra-sysfs"

    def __init__(self):
        loads = glob.glob("/sys/devices/platform/gpu.0/load") + glob.glob("/sys/devices/gpu.0/load") \
            + glob.glob("/sys/devices/platform/*/gpu.0/load")
        if not loads:
            raise RuntimeError("no tegra gpu load node")
        self._load = loads[0]
        dev = os.path.dirname(os.path.realpath(self._load))
        freqs = glob.glob(os.path.join(dev, "devfreq", "*", "cur_freq"))
        self._freq = freqs[0] if freqs else None
        self._info = {"Model": _read("/proc/device-tree/model", "").strip("\x00")}
        rel = _read("/etc/nv_tegra_release", "")
        if rel:
            self._info["L4T"] = rel.splitlines()[0][:40]

    def read(self):
        out = NullBackend.read(self)
        load = float(_read(self._load, "0")) / 10.0
        freq = float(_read(self._freq, "0")) / 1e6 if self._freq else 0.0
        mx = float(_read(self._freq.replace("cur_freq", "max_freq"), "0")) / 1e6 if self._freq else 0.0
        out["gpus"].append({"name": "gpu", "load": load, "freq": freq, "max_freq": mx,
                            "mem_used": None, "mem_total": None, "temp": None, "power": None})
        for z in glob.glob("/sys/class/thermal/thermal_zone*"):
            t = _read(z + "/temp")
            if t and t.lstrip("-").isdigit() and int(t) > -40000:
                out["temp"][_read(z + "/type", z)] = int(t) / 1000.0
        out["info"] = dict(self._info)
        return out


class NvidiaBackend(NullBackend):
    name = "nvidia"

    def __init__(self):
        self._nvml = None
        try:
            import pynvml
            pynvml.nvmlInit()
            self._nvml = pynvml
            self._handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(pynvml.nvmlDeviceGetCount())]
            self.name = "nvml"
        except Exception:
            if not shutil.which("nvidia-smi"):
                raise RuntimeError("no NVML and no nvidia-smi")
            self.name = "nvidia-smi"
            self._smi()  # raises if broken

    def _smi(self):
        q = "name,utilization.gpu,clocks.gr,clocks.max.gr,memory.used,memory.total,temperature.gpu,power.draw"
        res = subprocess.run(["nvidia-smi", "--query-gpu=" + q, "--format=csv,noheader,nounits"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3, check=True)
        gpus = []
        for line in res.stdout.decode().strip().splitlines():
            p = [x.strip() for x in line.split(",")]

            def f(x):
                try:
                    return float(x)
                except ValueError:
                    return None
            gpus.append({"name": p[0], "load": f(p[1]) or 0.0, "freq": f(p[2]) or 0.0, "max_freq": f(p[3]) or 0.0,
                         "mem_used": (f(p[4]) or 0) * 2**20, "mem_total": (f(p[5]) or 0) * 2**20,
                         "temp": f(p[6]), "power": f(p[7])})
        return gpus

    def read(self):
        out = NullBackend.read(self)
        if self._nvml is None:
            out["gpus"] = self._smi()
        else:
            n = self._nvml
            for h in self._handles:
                name = n.nvmlDeviceGetName(h)
                name = name.decode() if isinstance(name, bytes) else name
                util = n.nvmlDeviceGetUtilizationRates(h)
                mem = n.nvmlDeviceGetMemoryInfo(h)
                g = {"name": name, "load": float(util.gpu),
                     "freq": float(n.nvmlDeviceGetClockInfo(h, n.NVML_CLOCK_GRAPHICS)),
                     "max_freq": float(n.nvmlDeviceGetMaxClockInfo(h, n.NVML_CLOCK_GRAPHICS)),
                     "mem_used": mem.used, "mem_total": mem.total, "temp": None, "power": None}
                try:
                    g["temp"] = float(n.nvmlDeviceGetTemperature(h, n.NVML_TEMPERATURE_GPU))
                    g["power"] = n.nvmlDeviceGetPowerUsage(h) / 1000.0
                except Exception:
                    pass
                out["gpus"].append(g)
        for g in out["gpus"]:
            if g.get("temp") is not None:
                out["temp"][g["name"]] = g["temp"]
        return out


def make_backend(prefer="auto"):
    """Pick the best available backend. ``prefer`` in auto|jtop|tegra|nvidia|none."""
    order = {"auto": [JtopBackend, TegraBackend, NvidiaBackend], "jtop": [JtopBackend],
             "tegra": [TegraBackend], "nvidia": [NvidiaBackend], "none": []}[prefer]
    errors = []
    for cls in order:
        try:
            return cls(), errors
        except Exception as e:
            errors.append("{}: {}".format(cls.name, e))
    return NullBackend(), errors
