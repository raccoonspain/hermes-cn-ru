import pytest

from hermes_web import admin_metrics


def test_read_cpu_times_parses_proc_stat_line(tmp_path):
    stat_path = tmp_path / "stat"
    stat_path.write_text(
        "cpu  100 0 50 800 10 0 0 0 0 0\n"
        "cpu0 100 0 50 800 10 0 0 0 0 0\n"
    )
    idle, total = admin_metrics.read_cpu_times(str(stat_path))
    # idle = idle-поле (800) + iowait (10)
    assert idle == 810
    assert total == 100 + 0 + 50 + 800 + 10


def test_compute_cpu_percent_from_deltas():
    result = admin_metrics.compute_cpu_percent(
        idle_before=100, total_before=1000, idle_after=150, total_after=1100,
    )
    assert result == 50.0


def test_compute_cpu_percent_zero_total_delta_returns_zero():
    result = admin_metrics.compute_cpu_percent(
        idle_before=100, total_before=1000, idle_after=100, total_after=1000,
    )
    assert result == 0.0


@pytest.mark.asyncio
async def test_cpu_percent_samples_twice_and_computes_percentage(monkeypatch):
    samples = iter([(800, 1000), (850, 1100)])
    monkeypatch.setattr(admin_metrics, "read_cpu_times", lambda stat_path="/proc/stat": next(samples))

    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr(admin_metrics.asyncio, "sleep", fake_sleep)
    result = await admin_metrics.cpu_percent()
    assert result == 50.0


def test_ram_usage_parses_proc_meminfo(tmp_path):
    meminfo_path = tmp_path / "meminfo"
    meminfo_path.write_text(
        "MemTotal:        8388608 kB\n"
        "MemFree:          200000 kB\n"
        "MemAvailable:    3000000 kB\n"
        "Buffers:           50000 kB\n"
    )
    result = admin_metrics.ram_usage(str(meminfo_path))
    assert result == {
        "used_bytes": (8388608 - 3000000) * 1024,
        "total_bytes": 8388608 * 1024,
    }


def test_disk_usage_returns_used_and_total_for_real_path(tmp_path):
    result = admin_metrics.disk_usage(str(tmp_path))
    assert result["path"] == str(tmp_path)
    assert result["total_bytes"] > 0
    assert 0 <= result["used_bytes"] <= result["total_bytes"]
