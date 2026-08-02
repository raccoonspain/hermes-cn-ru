"""Метрики VPS для /api/admin/overview — только stdlib (/proc, shutil),
без psutil: в проекте нет requirements.txt, пакеты в venv ставятся
вручную, лишнюю зависимость заводить не хочется без нужды."""
from __future__ import annotations

import asyncio
import shutil


def read_cpu_times(stat_path: str = "/proc/stat") -> tuple:
    with open(stat_path, "r", encoding="utf-8") as fh:
        first_line = fh.readline()
    values = [int(v) for v in first_line.split()[1:]]
    # /proc/stat cpu-строка: user nice system idle iowait irq softirq steal guest guest_nice
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return idle, total


def compute_cpu_percent(idle_before: int, total_before: int, idle_after: int, total_after: int) -> float:
    idle_delta = idle_after - idle_before
    total_delta = total_after - total_before
    if total_delta <= 0:
        return 0.0
    return round((1 - idle_delta / total_delta) * 100, 1)


async def cpu_percent(stat_path: str = "/proc/stat", sample_interval: float = 0.1) -> float:
    idle1, total1 = read_cpu_times(stat_path)
    await asyncio.sleep(sample_interval)
    idle2, total2 = read_cpu_times(stat_path)
    return compute_cpu_percent(idle1, total1, idle2, total2)


def ram_usage(meminfo_path: str = "/proc/meminfo") -> dict:
    values = {}
    with open(meminfo_path, "r", encoding="utf-8") as fh:
        for line in fh:
            key, _, rest = line.partition(":")
            if key in ("MemTotal", "MemAvailable"):
                values[key] = int(rest.strip().split()[0]) * 1024  # kB -> bytes
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    return {"used_bytes": total - available, "total_bytes": total}


def disk_usage(path: str) -> dict:
    usage = shutil.disk_usage(path)
    return {"used_bytes": usage.used, "total_bytes": usage.total, "path": path}
