#!/usr/bin/env python3
"""《3》改进项5：优化配置一致性闸门 check_optimized_configs.py.

Vanilla box (no ROS): exit 0 when every file under config/optimized/ is
  - well-formed XML, and
  - carries the key parameters its doc header claims.
It also asserts config/optimized/fastdds-base.xml (the iter7 seed) is NOT
mutated: it keeps its known iter7 markers.

It does NOT run ROS, does NOT measure latency, and does NOT claim any
optimized profile is merged or benchmarked. Missing file / malformed XML /
missing key parameter / base-seed drift: FAIL (exit 1).
On success print a line containing exactly:
    optimized configs: consistent (blocked, unmeasured)
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


OPT_DIR = Path("config/optimized")
BASE_SEED = OPT_DIR / "fastdds-base.xml"

FASTDDS_NS = "http://www.eprosima.com"
CYCLONE_NS = "https://cdds.io/config"

# (file, root local-name, required (tag-suffix, substring) checks on parsed tree,
#  required plain-text substrings in the raw file)
CHECKS: list[dict] = [
    {
        "file": "fastdds-iter1.xml",
        "root": "profiles",
        "ns": FASTDDS_NS,
        "tags": [
            "domainId",                 # 42
            "sendSocketBufferSize",     # 8388608
            "listenSocketBufferSize",
            "preallocated_number",      # 32
            "healthy_check_timeout_ms",  # 10000
        ],
        "text": [
            "8388608",          # doc2 建议 8 MiB
            "280000",           # shm_midsize kept
            "STATUS: blocked",
        ],
    },
    {
        "file": "cyclone-iter1.xml",
        "root": "CycloneDDS",
        "ns": CYCLONE_NS,
        "tags": [
            "Domain",
            "SocketBufferSize",   # 8388608
        ],
        "text": [
            "id=\"0\"",
            "8388608",
            "STATUS: blocked",
        ],
    },
    {
        "file": "fastdds-imu-hf.xml",
        "root": "profiles",
        "ns": FASTDDS_NS,
        "tags": [
            "data_writer",
            "data_reader",
            "historyQos",
            "depth",
        ],
        "text": [
            "BEST_EFFORT",   # IMU best-effort
            "1",             # KeepLast depth 1
            "STATUS: blocked",
        ],
    },
    {
        "file": "fastdds-lidar-large.xml",
        "root": "profiles",
        "ns": FASTDDS_NS,
        "tags": [
            "data_writer",
            "data_reader",
            "reliability",
            "sendSocketBufferSize",
        ],
        "text": [
            "RELIABLE",      # lidar reliable
            "8388608",       # 8 MiB burst buffer
            "flow_controllers",
            "STATUS: blocked",
        ],
    },
]

# fastdds-base.xml is the frozen iter7 seed. These substrings must still be present.
BASE_SEED_MARKERS = (
    "shm_midsize",
    "280000",
    "healthy_check_timeout_ms",
    "10000",
    "sendSocketBufferSize",
    "2097152",
    "preallocated_number",
    "32",
    "dynamic",
    "false",
)

SUCCESS_MARKER = "optimized configs: consistent (blocked, unmeasured)"


def _root_here() -> Path:
    cwd = Path.cwd()
    here = Path(__file__).resolve().parent
    for cand in (cwd, here.parent):
        if (cand / OPT_DIR).is_dir():
            return cand
    sys.exit("cannot find repo root (config/optimized/ missing from cwd or parent)")


def _localname(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _has_tag(tree: ET.Element, localname: str) -> bool:
    for el in tree.iter():
        if _localname(el.tag) == localname:
            return True
    return False


def main() -> int:
    root = _root_here()
    failures: list[str] = []
    lines: list[str] = ["# check_optimized_configs 《3》"]

    # 1) optimized XML files well-formed + key tags
    for spec in CHECKS:
        path = root / OPT_DIR / spec["file"]
        if not path.is_file():
            failures.append(f"missing optimized config `{spec['file']}`")
            lines.append(f"- **FAIL missing:** `{spec['file']}`")
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ET.fromstring(raw)
        except ET.ParseError as exc:
            failures.append(f"`{spec['file']}` not well-formed XML: {exc}")
            lines.append(f"- **FAIL XML parse:** `{spec['file']}` ({exc})")
            continue
        if _localname(tree.tag) != spec["root"]:
            failures.append(
                f"`{spec['file']}` root is <{_localname(tree.tag)}>, "
                f"expected <{spec['root']}>"
            )
            lines.append(
                f"- **FAIL root:** `{spec['file']}` root <{_localname(tree.tag)}>"
                f" != <{spec['root']}>"
            )
        missing_tags = [t for t in spec["tags"] if not _has_tag(tree, t)]
        if missing_tags:
            failures.append(
                f"`{spec['file']}` missing tag(s): {', '.join(missing_tags)}"
            )
            lines.append(
                f"- **FAIL tag:** `{spec['file']}` need {', '.join(missing_tags)}"
            )
        missing_text = [t for t in spec["text"] if t not in raw]
        if missing_text:
            failures.append(
                f"`{spec['file']}` missing text marker(s): {', '.join(missing_text)}"
            )
            lines.append(
                f"- **FAIL text:** `{spec['file']}` need {', '.join(missing_text)}"
            )
        if not missing_tags and not missing_text:
            lines.append(
                f"- **ok:** `{spec['file']}` well-formed, root <{spec['root']}>"
                f", {len(spec['tags'])} tag(s) + {len(spec['text'])} marker(s) present"
            )

    # 2) base seed NOT mutated
    if not BASE_SEED.is_file():
        failures.append(f"base seed missing: `{BASE_SEED}`")
        lines.append(f"- **FAIL missing:** `{BASE_SEED}`")
    else:
        base_raw = BASE_SEED.read_text(encoding="utf-8", errors="replace")
        drift = [m for m in BASE_SEED_MARKERS if m not in base_raw]
        if drift:
            failures.append(
                f"fastdds-base.xml lost iter7 marker(s): {', '.join(drift)}"
            )
            lines.append(
                f"- **FAIL base drift:** `fastdds-base.xml` need {', '.join(drift)}"
            )
        else:
            lines.append(
                "- **ok base seed:** `fastdds-base.xml` still the iter7 seed "
                "(shm_midsize 280000/2MiB, healthy_check 10000, sockets 2MiB, "
                "send_buffers 32/dynamic=false)"
            )

    lines.append("")
    lines.append(
        "XML well-formedness + key-parameter presence only. This is **not** a "
        "ROS run, not a latency/jitter measurement, and not a merge. All "
        "optimized profiles stay proposals; bench numbers remain STATUS: blocked."
    )
    lines.append("")

    if failures:
        lines.append("FAIL:")
        for item in failures:
            lines.append(f"- {item}")
        lines.append("")
        lines.append(
            "Restore well-formed XML with the claimed key parameters, or the "
            "fastdds-base.xml iter7 markers. Exit 1."
        )
        sys.stdout.write("\n".join(lines) + "\n")
        return 1

    lines.append(f"- **{SUCCESS_MARKER}**")
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
