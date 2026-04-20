import os
import json

HDRS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}

NO_ANS = [
    "not in the context", "does not contain", "no relevant",
    "not mentioned", "cannot find", "no information",
    "doesn't contain", "not found in the", "the context does not",
    "not present in", "geen relevante", "niet in de context",
]


def sse(tp, **kw):
    return "data: " + json.dumps({"type": tp, **kw}) + "\n\n"


def get_pi_stats():
    s = {}
    try:
        with open("/proc/meminfo") as f:
            mi = f.read()
        for l in mi.split("\n"):
            if l.startswith("MemTotal:"):
                s["ram_total"] = int(l.split()[1]) // 1024
            elif l.startswith("MemAvailable:"):
                s["ram_available"] = int(l.split()[1]) // 1024
    except Exception:
        pass
    try:
        st = os.statvfs("/")
        s["disk_total"] = (st.f_blocks * st.f_frsize) // (1024 ** 3)
        s["disk_free"]  = (st.f_bavail * st.f_frsize) // (1024 ** 3)
    except Exception:
        pass
    try:
        s["load"] = [round(l, 2) for l in os.getloadavg()]
    except Exception:
        pass
    try:
        with open("/proc/uptime") as f:
            up = float(f.read().split()[0])
        s["uptime"] = f"{int(up // 86400)}d {int((up % 86400) // 3600)}h {int((up % 3600) // 60)}m"
    except Exception:
        pass
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            s["cpu_temp"] = round(int(f.read().strip()) / 1000, 1)
    except Exception:
        pass
    s["hostname"] = os.uname().nodename
    return s
