#!/usr/bin/env python3
"""《3》改进项6：bench 分数汇总模板 collect_scores.py.

用途：未来在有 ROS Humble + Docker 的机器上跑完 scripts/bench/*_chain*.sh 后，
扫描 docs/artifacts/bench/<run>/ 下的 raw.json，按 chain/topology 汇总
延迟分位数，输出一张对照表。本仓当前无 ROS 运行时：本脚本不会编造数字，
它只汇总磁盘上已存在的真实 raw.json；找不到测量字段时如实标注
STATUS: blocked。

设计原则（与 SCOREBOARD / dod 闸门一致）：
  - 只读 raw.json，不写、不改任何配置。
  - 主指标是 jitter（RTT p95/p99 + arrival |I-gap| p95），p50 仅次级。
  - 不把 Chain A 与 Chain B、same-process/same-host/cross-host 混进一张表。
  - cross-host UDP 永远按 STATUS: blocked 处理（单机 VM）。
  - 不杜撰 p50/p95/p99；字段缺失 = blocked，不是 0。

用法：
  python3 scripts/bench/collect_scores.py                 # 扫描默认 bench 根
  python3 scripts/bench/collect_scores.py --bench-root docs/artifacts/bench
  python3 scripts/bench/collect_scores.py --run 2026-09-11-iter7
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# raw.json 里可能出现的分位数字段（pingpong.py 写入；不同 iter 命名略有差异）.
PCT_KEYS = ("p50", "p95", "p99", "p99.9", "max", "mean", "stdev",
            "arrival_p95", "arrival_abs_gap_p95")


def _root_here() -> Path:
    here = Path(__file__).resolve()
    # scripts/bench/collect_scores.py -> repo root = parents[2]
    return here.parents[2]


def _load_raw(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None


def _metric_row(raw: dict[str, Any]) -> dict[str, str]:
    """Pull whatever percentile keys actually exist; never invent."""
    row = {
        "chain": str(raw.get("chain", "?")),
        "topology": str(raw.get("topology", "?")),
        "rmw": str(raw.get("rmw", "?")),
        "status": str(raw.get("status", "?")),
    }
    # raw.json may nest stats under a "metrics" / "rtt" block or be flat.
    blobs: list[dict[str, Any]] = [raw]
    for key in ("metrics", "rtt", "stats"):
        if isinstance(raw.get(key), dict):
            blobs.append(raw[key])
    found: dict[str, str] = {}
    for blob in blobs:
        for pk in PCT_KEYS:
            if pk in blob and pk not in found:
                found[pk] = str(blob[pk])
    row["pct"] = ", ".join(f"{k}={v}" for k, v in sorted(found.items())) or "none"
    return row


def collect(bench_root: Path, only_run: str | None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    runs = [only_run] if only_run else sorted(
        p.name for p in bench_root.iterdir()
        if p.is_dir() and (p / "chain_a_same_host").exists()
        or (p.is_dir() and list(p.rglob("raw.json")))
    )
    for run in runs:
        run_dir = bench_root / run
        for raw_path in sorted(run_dir.rglob("raw.json")):
            raw = _load_raw(raw_path)
            if not raw:
                continue
            row = _metric_row(raw)
            row["run"] = run
            # cross-host is structurally blocked on a single VM
            if "cross" in row["topology"].lower():
                row["status"] = "blocked(cross-host single VM)"
            rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Aggregate real bench raw.json scores.")
    ap.add_argument("--bench-root", default="docs/artifacts/bench")
    ap.add_argument("--run", default=None, help="only one run dir name")
    args = ap.parse_args()

    repo = _root_here()
    bench_root = repo / args.bench_root
    lines: list[str] = ["# collect_scores — real raw.json aggregation only"]

    if not bench_root.is_dir():
        lines.append(f"STATUS: blocked — bench root not found: `{bench_root}`")
        lines.append("No ROS run has been executed on this machine; no numbers invented.")
        sys.stdout.write("\n".join(lines) + "\n")
        return 0

    rows = collect(bench_root, args.run)
    # Only count rows that carry real percentile measurements.
    measured = [r for r in rows if r["pct"] != "none" and not r["status"].startswith("blocked")]

    if not measured:
        lines.append("STATUS: blocked")
        lines.append(
            "No raw.json on disk carries real percentile measurements on this "
            "machine. This box has no /opt/ros and no Docker, so ping-pong was "
            "never executed here. Existing artifacts under docs/artifacts/bench/ "
            "are copies from the baseline run (other machine / other host) and are "
            "cited as evidence, not re-measured here."
        )
        lines.append(
            "When a real ROS run lands, put raw.json per topology under "
            "docs/artifacts/bench/<run>/chain_a_<topo>/ and re-run this script."
        )
        lines.append("")
        lines.append(
            "Note: cross-host-UDP stays blocked (single VM). Do not mix Chain A "
            "and Chain B, or same-process/same-host/cross-host, in one table."
        )
        sys.stdout.write("\n".join(lines) + "\n")
        return 0

    # Real measured rows exist -> print a grouped table.
    lines.append(f"Measured runs found: {len(measured)}")
    lines.append("")
    lines.append("| run | chain | topology | rmw | pct (us) |")
    lines.append("|-----|-------|----------|-----|----------|")
    for r in measured:
        lines.append(
            f"| {r['run']} | {r['chain']} | {r['topology']} | {r['rmw']} | {r['pct']} |"
        )
    lines.append("")
    lines.append(
        "These numbers are copied verbatim from raw.json; units microseconds. "
        "Primary gate is jitter (p95/p99 + arrival gap), not p50. Not Feishu "
        "field proof; not cross-host."
    )
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
