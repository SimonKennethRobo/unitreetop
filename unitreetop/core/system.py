"""Host statistics: CPU, memory, disk, network, temperatures, processes."""
import os
import platform
import socket
import time

import psutil


class SystemStats:
    def __init__(self):
        self._net_prev = None
        self._disk_prev = None
        psutil.cpu_percent(percpu=True)  # prime
        for p in psutil.process_iter():
            try:
                p.cpu_percent(None)
            except Exception:
                pass
        self.static = self._static()

    @staticmethod
    def _static():
        info = {
            "hostname": socket.gethostname(),
            "kernel": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "cpu_count": psutil.cpu_count(),
            "boot_time": psutil.boot_time(),
        }
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        info["distro"] = line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
        try:
            with open("/proc/device-tree/model") as f:
                info["board"] = f.read().strip("\x00\n ")
        except OSError:
            pass
        return info

    def read(self, with_procs=True):
        now = time.monotonic()
        out = {}
        per = psutil.cpu_percent(percpu=True)
        try:
            freqs = psutil.cpu_freq(percpu=True) or []
        except Exception:
            freqs = []
        cores = []
        for i, load in enumerate(per):
            f = freqs[i] if i < len(freqs) else None
            cores.append({
                "load": load,
                "freq": f.current if f else 0.0,
                "max": f.max if f else 0.0,
                "online": True,
            })
        out["cpu"] = {
            "total": sum(per) / len(per) if per else 0.0,
            "cores": cores,
            "load": os.getloadavg(),
        }
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        out["mem"] = {"used": vm.total - vm.available, "total": vm.total, "cached": getattr(vm, "cached", 0),
                      "percent": vm.percent}
        out["swap"] = {"used": sw.used, "total": sw.total, "percent": sw.percent}
        try:
            du = psutil.disk_usage("/")
            out["disk"] = {"used": du.used, "total": du.total, "percent": du.percent}
        except Exception:
            out["disk"] = {}
        # network rates per interface
        nio = psutil.net_io_counters(pernic=True)
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        net = {}
        if self._net_prev:
            t0, prev = self._net_prev
            dt = max(now - t0, 1e-3)
            for name, c in nio.items():
                p = prev.get(name)
                if p is None or name == "lo":
                    continue
                st = stats.get(name)
                ip = next((a.address for a in addrs.get(name, []) if a.family == socket.AF_INET), "")
                net[name] = {
                    "rx": (c.bytes_recv - p.bytes_recv) / dt,
                    "tx": (c.bytes_sent - p.bytes_sent) / dt,
                    "up": bool(st and st.isup),
                    "ip": ip,
                }
        self._net_prev = (now, nio)
        out["net"] = net
        # temperatures
        temps = {}
        try:
            for chip, entries in psutil.sensors_temperatures().items():
                for e in entries:
                    if e.current and e.current > -40:
                        key = chip if not e.label else "{}/{}".format(chip, e.label)
                        temps[key] = e.current
        except Exception:
            pass
        out["temp"] = temps
        out["uptime"] = time.time() - self.static["boot_time"]
        if with_procs:
            out["procs"] = self._procs()
        return out

    @staticmethod
    def _procs(n=40):
        rows = []
        for p in psutil.process_iter(["pid", "name", "username", "memory_info", "num_threads"]):
            try:
                cpu = p.cpu_percent(None)
                info = p.info
                rows.append({
                    "pid": info["pid"], "name": info["name"] or "?",
                    "user": (info["username"] or "?")[:10], "cpu": cpu,
                    "mem": info["memory_info"].rss if info["memory_info"] else 0,
                    "threads": info["num_threads"] or 0,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        rows.sort(key=lambda r: r["cpu"], reverse=True)
        return rows[:n]
