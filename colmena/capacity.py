import os

DEFAULT_PER_TURN_MB = 600
_MIN_RESERVE_KB = 1.5 * 1024 * 1024


def parse_meminfo(text):
    mem = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts:
            mem[key] = int(parts[0])
    return mem


def read_meminfo():
    with open("/proc/meminfo") as f:
        return parse_meminfo(f.read())


def max_running(mem, per_turn_mb, override=None):
    if override:
        return override
    reserve = max(_MIN_RESERVE_KB, 0.15 * mem["MemTotal"])
    return max(1, int((mem["MemAvailable"] - reserve) / (per_turn_mb * 1024)))


def _ppid(proc, pid):
    with open(f"{proc}/{pid}/stat") as f:
        # comm may contain spaces and parentheses; fields resume after the last ")"
        return int(f.read().rsplit(")", 1)[1].split()[1])


def _rss_kb(proc, pid):
    with open(f"{proc}/{pid}/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    return 0


def descendants_rss_kb(pid, proc="/proc"):
    children = {}
    for name in os.listdir(proc):
        if name.isdigit():
            try:
                children.setdefault(_ppid(proc, name), []).append(int(name))
            except (OSError, IndexError, ValueError):
                pass
    total, stack = 0, list(children.get(pid, []))
    while stack:
        p = stack.pop()
        try:
            total += _rss_kb(proc, p)
        except OSError:
            pass
        stack.extend(children.get(p, []))
    return total


def ema(avg, sample, alpha=0.3):
    return avg * (1 - alpha) + sample * alpha
