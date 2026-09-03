#!/usr/bin/env python3
"""A small dependency-free CPU health diagnostic agent for Linux.

Run:
    python3 cpu_doctor_agent.py
    python3 cpu_doctor_agent.py --json
    python3 cpu_doctor_agent.py --interval 1.0 --top 8

Exit codes:
    0 - healthy
    1 - warning
    2 - critical
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any


JIFFIES_PER_SECOND = 100


@dataclass
class ProcessSnapshot:
    pid: int
    name: str
    cpu_seconds: float
    memory_mb: float


@dataclass
class ProcessUsage:
    pid: int
    name: str
    cpu_percent: float
    memory_mb: float


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    recommendation: str


@dataclass
class CpuReport:
    timestamp_utc: str
    hostname: str
    cpu_count: int
    cpu_percent: float | None
    load_1m: float | None
    load_per_cpu: float | None
    memory_percent: float | None
    memory_available_mb: float | None
    uptime_seconds: float | None
    top_processes: list[ProcessUsage]
    findings: list[Finding]
    overall_status: str


def read_text(path: str) -> str | None:
    """Read a procfs file, returning None when it disappears during a scan."""
    try:
        with open(path, encoding="utf-8") as file:
            return file.read()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def parse_cpu_times() -> tuple[int, int] | None:
    """Return total and idle jiffies from /proc/stat."""
    content = read_text("/proc/stat")
    if not content:
        return None

    first_line = content.splitlines()[0] if content.splitlines() else ""
    fields = first_line.split()
    if len(fields) < 5 or fields[0] != "cpu":
        return None

    try:
        values = [int(value) for value in fields[1:]]
    except ValueError:
        return None

    # user, nice, system, idle, iowait, irq, softirq, steal, ...
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def sample_cpu_percent(interval: float) -> float | None:
    """Measure aggregate CPU usage over a short sampling interval."""
    first = parse_cpu_times()
    if first is None:
        return None
    time.sleep(interval)
    second = parse_cpu_times()
    if second is None:
        return None

    total_delta = second[0] - first[0]
    idle_delta = second[1] - first[1]
    if total_delta <= 0:
        return None
    return round(max(0.0, min(100.0, (1 - idle_delta / total_delta) * 100)), 1)


def read_load() -> tuple[float | None, float | None]:
    try:
        load_1m = os.getloadavg()[0]
    except (AttributeError, OSError):
        return None, None

    cpu_count = max(1, os.cpu_count() or 1)
    return round(load_1m, 2), round(load_1m / cpu_count, 2)


def read_memory() -> tuple[float | None, float | None]:
    content = read_text("/proc/meminfo")
    if not content:
        return None, None

    values: dict[str, int] = {}
    for line in content.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                values[parts[0].rstrip(":")] = int(parts[1])
            except ValueError:
                continue

    total_kb = values.get("MemTotal")
    available_kb = values.get("MemAvailable", values.get("MemFree"))
    if not total_kb or available_kb is None:
        return None, None

    used_percent = (1 - available_kb / total_kb) * 100
    return round(max(0.0, min(100.0, used_percent)), 1), round(available_kb / 1024, 1)


def read_uptime() -> float | None:
    content = read_text("/proc/uptime")
    if not content:
        return None
    try:
        return round(float(content.split()[0]), 1)
    except (IndexError, ValueError):
        return None


def parse_process(pid: int) -> ProcessSnapshot | None:
    stat = read_text(f"/proc/{pid}/stat")
    if not stat:
        return None

    # The process name can contain spaces and parentheses. The final ")" is
    # the delimiter before the state field in procfs' stat format.
    closing_name = stat.rfind(")")
    if closing_name < 0:
        return None
    fields = stat[closing_name + 2 :].split()
    if len(fields) < 22:
        return None

    try:
        utime = int(fields[11])
        stime = int(fields[12])
        rss_pages = int(fields[21])
    except ValueError:
        return None

    page_size = os.sysconf("SC_PAGE_SIZE")
    name = stat[stat.find("(") + 1 : closing_name]
    return ProcessSnapshot(
        pid=pid,
        name=name,
        cpu_seconds=(utime + stime) / JIFFIES_PER_SECOND,
        memory_mb=(rss_pages * page_size) / (1024 * 1024),
    )


def snapshot_processes() -> dict[int, ProcessSnapshot]:
    processes: dict[int, ProcessSnapshot] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        process = parse_process(int(entry))
        if process:
            processes[process.pid] = process
    return processes


def measure_processes(interval: float) -> list[ProcessUsage]:
    first = snapshot_processes()
    time.sleep(interval)
    second = snapshot_processes()
    cpu_count = max(1, os.cpu_count() or 1)

    usages: list[ProcessUsage] = []
    for pid, current in second.items():
        previous = first.get(pid)
        if previous is None:
            continue
        cpu_delta = max(0.0, current.cpu_seconds - previous.cpu_seconds)
        # Process CPU time is reported against one CPU. This matches tools
        # such as top and allows values over 100% on multi-threaded processes.
        cpu_percent = round(cpu_delta / interval * 100, 1)
        usages.append(
            ProcessUsage(
                pid=pid,
                name=current.name,
                cpu_percent=round(cpu_percent, 1),
                memory_mb=round(current.memory_mb, 1),
            )
        )

    usages.sort(key=lambda process: process.cpu_percent, reverse=True)
    return usages


def build_findings(
    cpu_percent: float | None,
    load_per_cpu: float | None,
    memory_percent: float | None,
    top_processes: list[ProcessUsage],
) -> list[Finding]:
    findings: list[Finding] = []

    if cpu_percent is not None:
        if cpu_percent >= 95:
            findings.append(
                Finding(
                    "critical",
                    "cpu-saturated",
                    f"CPU is saturated at {cpu_percent:.1f}%.",
                    "Inspect the top process list and check for runaway loops, retries, or an unexpected workload.",
                )
            )
        elif cpu_percent >= 85:
            findings.append(
                Finding(
                    "warning",
                    "cpu-high",
                    f"CPU usage is high at {cpu_percent:.1f}%.",
                    "Review the top process list and watch whether the load remains high over several scans.",
                )
            )

    if load_per_cpu is not None:
        if load_per_cpu >= 1.5:
            findings.append(
                Finding(
                    "critical",
                    "load-critical",
                    f"1-minute load is {load_per_cpu:.2f} per CPU.",
                    "Look for CPU-bound work or processes blocked on disk I/O; compare with the top process list.",
                )
            )
        elif load_per_cpu >= 0.9:
            findings.append(
                Finding(
                    "warning",
                    "load-high",
                    f"1-minute load is {load_per_cpu:.2f} per CPU.",
                    "Check whether the load is sustained and whether latency-sensitive services are affected.",
                )
            )

    if memory_percent is not None:
        if memory_percent >= 95:
            findings.append(
                Finding(
                    "critical",
                    "memory-critical",
                    f"Memory usage is {memory_percent:.1f}%.",
                    "Find memory-heavy processes and reduce the workload before the system starts swapping.",
                )
            )
        elif memory_percent >= 85:
            findings.append(
                Finding(
                    "warning",
                    "memory-high",
                    f"Memory usage is {memory_percent:.1f}%.",
                    "Review resident memory in the top process list and monitor for continued growth.",
                )
            )

    if top_processes and top_processes[0].cpu_percent >= 50:
        top = top_processes[0]
        findings.append(
            Finding(
                "warning",
                "process-hotspot",
                f"{top.name} (PID {top.pid}) used {top.cpu_percent:.1f}% CPU during the scan.",
                "Confirm that the process is expected; inspect its logs, inputs, and recent deployments.",
            )
        )

    return findings


def collect_report(interval: float, top_count: int) -> CpuReport:
    cpu_percent = sample_cpu_percent(interval)
    process_usages = measure_processes(interval)
    load_1m, load_per_cpu = read_load()
    memory_percent, memory_available_mb = read_memory()
    findings = build_findings(cpu_percent, load_per_cpu, memory_percent, process_usages)
    statuses = {finding.severity for finding in findings}
    overall_status = (
        "critical" if "critical" in statuses else "warning" if "warning" in statuses else "healthy"
    )

    return CpuReport(
        timestamp_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        hostname=os.uname().nodename,
        cpu_count=max(1, os.cpu_count() or 1),
        cpu_percent=cpu_percent,
        load_1m=load_1m,
        load_per_cpu=load_per_cpu,
        memory_percent=memory_percent,
        memory_available_mb=memory_available_mb,
        uptime_seconds=read_uptime(),
        top_processes=process_usages[:top_count],
        findings=findings,
        overall_status=overall_status,
    )


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unavailable"
    days, remainder = divmod(int(seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    return f"{hours}h {minutes}m"


def metric(value: float | None, suffix: str = "") -> str:
    return "unavailable" if value is None else f"{value:.1f}{suffix}"


def render_text(report: CpuReport) -> str:
    status_label = report.overall_status.upper()
    lines = [
        f"CPU Doctor Agent — {status_label}",
        f"Host: {report.hostname} | CPUs: {report.cpu_count} | Uptime: {format_duration(report.uptime_seconds)}",
        "",
        f"CPU usage: {metric(report.cpu_percent, '%')}",
        f"Load (1m): {metric(report.load_1m)} ({metric(report.load_per_cpu)} per CPU)",
        f"Memory: {metric(report.memory_percent, '%')} used | {metric(report.memory_available_mb, ' MB')} available",
        "",
        "Top processes:",
    ]
    if report.top_processes:
        lines.extend(
            f"  {process.cpu_percent:6.1f}% CPU  {process.memory_mb:8.1f} MB  "
            f"PID {process.pid:<7} {process.name}"
            for process in report.top_processes
        )
    else:
        lines.append("  unavailable")

    lines.append("")
    if report.findings:
        lines.append("Findings:")
        lines.extend(
            f"  [{finding.severity.upper()}] {finding.message}\n"
            f"      Recommendation: {finding.recommendation}"
            for finding in report.findings
        )
    else:
        lines.append("Findings: no CPU or memory pressure detected.")
    return "\n".join(lines)


def report_as_json(report: CpuReport) -> dict[str, Any]:
    return asdict(report)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect CPU, load, memory, uptime, and top Linux processes."
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.5,
        help="Seconds used for CPU and process sampling (default: 0.5).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=5,
        help="Number of top processes to include (default: 5).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable JSON report.",
    )
    args = parser.parse_args()
    if not 0.1 <= args.interval <= 10:
        parser.error("--interval must be between 0.1 and 10 seconds")
    if not 1 <= args.top <= 50:
        parser.error("--top must be between 1 and 50")
    return args


def main() -> int:
    args = parse_args()
    report = collect_report(args.interval, args.top)
    if args.json:
        print(json.dumps(report_as_json(report), indent=2))
    else:
        print(render_text(report))

    return {"healthy": 0, "warning": 1, "critical": 2}[report.overall_status]


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nScan cancelled.", file=sys.stderr)
        raise SystemExit(130)