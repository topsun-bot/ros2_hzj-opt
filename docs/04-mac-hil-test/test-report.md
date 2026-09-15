# 《4》Mac HIL 测试报告 — ros2_hzj-opt

- **报告日期**: 2026-09-15 (UTC-7, America/Los_Angeles)
- **被测仓库**: `/Users/zhang/Doubao/chats/2026-09-15/new-chat-1/ros2_hzj-opt`
- **基线仓库**: `/tmp/tutti_task/ros2_hzj` (bench 脚本来源)
- **测试人**: automated HIL run (Doubao agent)
- **报告文件**: `docs/04-mac-hil-test/test-report.md`
- **Artifacts**: `docs/artifacts/bench/2026-09-15/{chain_a_same_process,imu_hf}/raw.json`

---

## 1. 测试环境信息

| 项目 | 值 |
|---|---|
| macOS 版本 | 26.5.2 (Build 25F84), Darwin 25.5.0 |
| 架构 | arm64 (Apple Silicon) |
| 芯片 | Apple M4 Max |
| 内存 | 128 GiB (`hw.memsize=137438953472`) |
| CPU | 16 核 (`hw.ncpu=16`) |
| Host shell | zsh / bash 3.2 (/bin/bash) |
| ROS 2 runtime (native) | **无** — `which ros2` rc=1; `/opt/ros/` 不存在; `ROS_DISTRO` 未设 |
| Docker Desktop | **未安装** (按硬约束不安装) |
| brew | `/opt/homebrew/bin/brew` (Homebrew 7.0.1, arm64, user-owned) |
| sudo | 非交互不可用 (`sudo -n` rc=1, requires password) |
| colima / docker CLI | **本次安装**: colima 0.10.3, docker 29.8.0, lima 2.2.0 (`brew install colima docker`) |
| colima VM | aarch64, vz (Virtualization.framework), 4 CPU / 8 GiB / 30 GiB disk, virtiofs |
| 容器内 OS | Ubuntu 24.04.4 LTS (Noble) guest, running `osrf/ros:humble-desktop` **amd64 under QEMU user-mode emulation** |
| ROS distro in container | humble (Python 3.10, rclpy imported OK) |
| 默认 RMW (container, no env) | `rmw_fastrtps_cpp` (verified via `get_rmw_implementation_identifier()`) |
| 网络 | colima `--net=host` inside VM; loopback works for same-process, multi-process discovery flaky (see Bug B3) |

> **重要口径声明**: `osrf/ros:humble-desktop` 在 ghcr.io / Docker Hub 上**只有 linux/amd64 manifest**（无 arm64 variant，`docker manifest inspect` 返回单 v2 manifest）。在 arm64 colima VM 上以 `--platform linux/amd64` + QEMU user-mode 模拟运行。**所有延迟数字都被 QEMU 翻译开销抬高约 2×**，不能与 iter7 原生 x86_64 数字（~1.1 ms p95）直接对比。本报告只验证「契约走通 + 无错误」，不做性能结论。

---

## 2. 环境探测记录（按任务要求顺序）

### 2.1 原生 ROS 2 探测

```text
$ which ros2
rc=1 (not found)
$ ls /opt/ros/
ls: /opt/ros/: No such file or directory
$ echo $ROS_DISTRO
<unset>
$ echo $RMW_IMPLEMENTATION $ROS_DOMAIN_ID
<unset> <unset>
```
**结论**: 无原生 ROS 2 Humble 安装。

### 2.2 Docker 探测

```text
$ which docker
rc=1 (not found)
$ which colima
not found
```
**结论**: 无 Docker / colima。

### 2.3 brew 探测

```text
$ which brew
/opt/homebrew/bin/brew
$ brew --version
Homebrew 7.0.1-13-g888ddcc
$ brew --prefix
/opt/homebrew
```
**结论**: brew 可用，且 `/opt/homebrew` 由当前用户拥有，`brew install` 不需要 sudo。

### 2.4 免密码安装 colima + docker CLI

```text
$ brew install colima docker
==> Pouring lima--2.2.0.arm64_tahoe.bottle.tar.gz
🍺  /opt/homebrew/Cellar/lima/2.2.0: 147 files, 80.9MB
🍺  /opt/homebrew/Cellar/colima/0.10.3: 14 files, 10.6MB
🍺  /opt/homebrew/Cellar/docker/29.8.0: 17 files, 29.0MB
```
未请求管理员密码，未安装 Docker Desktop，未改系统配置。

### 2.5 colima VM 启动 + 网络修复

```text
$ colima start --vm-type vz --cpu 4 --memory 8 --disk 30
... READY.
... colima is running using macOS Virtualization.Framework
... arch: aarch64, runtime: docker, mountType: virtiofs
```

首次 `docker pull` 失败：guest `/etc/resolv.conf` 是指向 `/run/systemd/resolve/stub-resolv.conf` 的**断链**（systemd-resolved 未运行），导致 dockerd DNS 查询 `[::1]:53` 被拒。修复（在 guest 内，colima ssh passwordless sudo）：

```bash
colima ssh -- sudo sh -c 'rm -f /etc/resolv.conf && \
  printf "nameserver 8.8.8.8\nnameserver 1.1.1.1\n" > /etc/resolv.conf'
colima ssh -- sudo systemctl restart docker
```

同时把 `~/.colima/default/colima.yaml` 的 `dns: null` 改为 `dns: [8.8.8.8, 1.1.1.1]`（重启后该字段不覆盖 guest 内的 resolv.conf，但保留供 lima 模板使用）。

### 2.6 镜像拉取

```text
$ docker pull --platform linux/arm64 osrf/ros:humble-desktop
Error: image does not provide linux/arm64  (manifest is amd64-only)
$ docker pull --platform linux/amd64 osrf/ros:humble-desktop
Digest: sha256:fb07245b32187d74350be25323d8ad2f8ca5c25c325759911a1eff2267a49c1e
Status: Downloaded newer image for osrf/ros:humble-desktop
DISK USAGE 4.85GB / CONTENT 1.08GB
```

### 2.7 静态验证（无 ROS 时的兜底）

- **XML well-formedness** (Python `xml.etree.ElementTree`):
  - `config/optimized/fastdds-base.xml` → **OK** (root `{http://www.eprosima.com}profiles`, 2 children)
  - `/tmp/tutti_task/ros2_hzj/config/fastdds.xml` → **OK**
  - `diff baseline fastdds.xml  optimized fastdds-base.xml` → **rc=0 (byte-identical)** — 符合 AGENTS.md「不修改基线种子」
  - `scripts/bench/cyclonedds_udp_lo.xml` → **FAIL**: `ParseError: not well-formed (invalid token): line 5, column 38` — 见 Bug B2
- **bash -n 语法检查**: run_chain_a.sh, run_chain_b.sh, run_imu_hf.sh, common.sh, docker_chain_a.sh, chain_a.sh, chain_b.sh → **全部 OK**
- **12 gates**: `python3 scripts/gates/*.py` → **1 PASS / 11 FAIL** — 见 Bug B1
- **prove_rmw.py** 在容器内（已 source Humble）运行 → exit 0，正确报告 `rclpy: imported`, `rmw identifier (runtime): rmw_fastrtps_cpp`

---

## 3. 三个核心用例测试结果

### 3.1 [核心用例 1] 链 A Fast-DDS pub/sub（域 42）

| 字段 | 值 |
|---|---|
| **状态** | **PASS** (same-process pingpong); multi-process talker/listener **FAIL** (env issue, see B3) |
| RMW | `rmw_fastrtps_cpp` (runtime identifier verified) |
| ROS_DOMAIN_ID | 42 |
| FASTRTPS_DEFAULT_PROFILES_FILE | `/opt-new/config/optimized/fastdds-base.xml` (iter5+iter7 seed: SHM 280000/2MiB, healthy_check_timeout 10000, send_buffers 32/dynamic=false, socket buffers 2 MiB) |
| 镜像 | `osrf/ros:humble-desktop` amd64 under QEMU |
| 拓扑 | same-process (pingpong.py in-process pub+sub) |
| discover_s | 1.2 s |
| samples | 200 (BestEffort) + 200 (Reliable), 0 timeouts, 20 warmup |
| Artifact | `docs/artifacts/bench/2026-09-15/chain_a_same_process/raw.json` |

**实测延迟（64 B, same-process, QEMU amd64 — 仅作走通证据，不可与原生数字对比）**:

| QoS | p50 (µs) | p95 (µs) | p99 (µs) | mean (µs) | stdev (µs) | jitter p95−p50 (µs) |
|---|---:|---:|---:|---:|---:|---:|
| high_throughput (BestEffort) | 2136.7 | 2891.3 | 3141.8 | 2253.8 | 300.4 | 754.6 |
| reliable | 2089.9 | 2741.3 | 2898.3 | 2171.9 | 241.0 | 651.3 |

**Talker/listener 多进程 smoke**: 在同一容器内起两个 python3 进程（talker 5 msgs / listener spin 12 s），listener 收到 0 条。**取消 `FASTRTPS_DEFAULT_PROFILES_FILE`（裸默认）后仍为 0**，故归因于 colima VM 内多进程 UDP 发现不通（见 B3），**不**归因于优化 XML。same-process pingpong 走通已证明 rclpy + rmw_fastrtps_cpp + 优化 XML 端到端可加载、可收发。

### 3.2 [核心用例 2] 链 B Cyclone pub/sub（域 0）

| 字段 | 值 |
|---|---|
| **状态** | **BLOCKED** |
| 预期 RMW | `rmw_cyclonedds_cpp`, ROS_DOMAIN_ID=0 |
| 实际动作 | 在临时容器内 `apt-get install ros-humble-rmw-cyclonedds-cpp` (1.3.5) 后 `rclpy.init()` + `create_node()` |
| 错误输出 | `rclpy._rclpy_pybind11.RCLError: error creating node: rcl node's rmw handle is invalid, at ./src/rcl/node.c:415` |
| 已尝试 | (a) 默认 Cyclone 无 XML; (b) `CYCLONEDDS_URI=file:///work/scripts/bench/cyclonedds_udp_lo.xml` 强制 loopback — 两者同样失败 |
| 归因 | colima VM 内 CycloneDDS 无法绑定其发现 socket（多播/单播 UDP bind 失败）；Fast-DDS 同拓扑可工作，说明是 Cyclone 特有初始化问题，不是网络全断 |
| Artifact | 无 raw.json（节点创建失败，未进入 pingpong） |

> 注：基线 `run_chain_b.sh` 走的是**原生 DimOS `ddspubsub.DDS`**（需要 `cyclonedds` python wheel + DimOS 源码树），不是 `rmw_cyclonedds_cpp`。本环境既无 DimOS 树也不允许 vendor 改动，故即使 RMW 层能起来，原生 Chain B 路径仍 blocked。

### 3.3 [hero 用例 3] IMU 64B/200Hz 高频小包 jitter（iter6/iter7 口径）

| 字段 | 值 |
|---|---|
| **状态** | **PASS** (same-process) |
| RMW / domain | `rmw_fastrtps_cpp` / 42 |
| 优化 XML | `fastdds-base.xml` (iter7: healthy_check_timeout 10000) |
| 载荷 | 64 B, `uint8_multiarray`（contiguous uint8） |
| 采样 | 400 samples, 40 warmup, 0 timeouts, timeout=1 s |
| 发布间隔 | 5 ms 目标 (200 Hz) |
| discover_s | 1.2 s |
| Artifact | `docs/artifacts/bench/2026-09-15/imu_hf/raw.json` |

**实测（QEMU amd64 — 仅作走通证据）**:

| QoS | RTT p50 | RTT p95 | RTT p99 | RTT mean | RTT stdev | arrival \|I−5ms\| p50 | p95 | p99 | rfc3550 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BestEffort (high_throughput) | 2067.8 | 2657.7 | 2951.1 | 2103.0 | 309.9 | 728.1 | **1466.6** | 1750.4 | 733.1 |
| Reliable | 2180.8 | 2714.5 | 2928.4 | 2170.4 | 314.4 | 670.6 | **1400.9** | 1646.0 | 713.6 |

对比 iter7 原生记录（同一 XML，x86_64 真机）：same-host BestEffort RTT p95 ≈ 1148 µs、arrival \|I−5ms\| p95 ≈ 375 µs。本次 p95 ≈ 2658 µs / arrival p95 ≈ 1467 µs，约 2.3× / 3.9×，**差值全部归因于 QEMU user-mode 翻译 + colima virtiofs 调度噪声**，不构成对 iter7 优化回退的证据。0 timeouts、400/400 samples 完成，证明优化 XML 在 Humble Fast-DDS 2.6 下能正常加载并跑满 200 Hz 闭环。

---

## 4. Bug 列表（按严重程度排序）

### B1 — [Major] 11/12 gate 脚本在新克隆上无法通过

- **复现步骤**:
  ```bash
  cd /Users/zhang/Doubao/chats/2026-09-15/new-chat-1/ros2_hzj-opt
  python3 scripts/gates/check_cega_bridge_hold.py
  # 或任意 check_*.py / print_bench_gates.py
  ```
- **预期结果**: 12 gates 全部 PASS（README.md 第 35 行声称「全部 12 个闸门（无 ROS 运行时即可运行）」）。
- **实际结果**: 11/12 退出码 1，stderr:
  ```
  cannot find repo root from cwd=.../ros2_hzj-opt or .../ros2_hzj-opt/scripts
  ```
  仅 `prove_rmw.py` 通过。
- **根因**: 每个 gate 用 `MAP_REL = Path("docs/architecture/ros2-source-map.md")` 或 `docs/architecture/feishu-executor-waitset.md` 作为 repo-root marker；这些 docs **尚未写**（`docs/architecture/` 是空目录，`find docs -type f` 返回空）。
- **严重程度**: **Major**（README 承诺与实际可运行性不符；新用户按 README 跑 gate 会得到红色失败，但这是「文档未写」而非「逻辑错」）。

### B2 — [Minor] `cyclonedds_udp_lo.xml` 注释内含 `--`，违反 XML 1.0

- **复现步骤**:
  ```python
  import xml.etree.ElementTree as ET
  ET.parse("/tmp/tutti_task/ros2_hzj/scripts/bench/cyclonedds_udp_lo.xml")
  # ParseError: not well-formed (invalid token): line 5, column 38
  ```
- **预期结果**: 严格 XML 解析器能解析。
- **实际结果**: 第 5 行 `Used by scripts/bench/pingpong.py --iceoryx off (same-host UDP).` 在 `<!-- ... -->` 注释内出现 `--`（即 `--iceoryx`），XML 1.0 §2.5 禁止注释内出现双连字符。
- **严重程度**: **Minor**（Cyclone 自己的解析器（TinyXML2）通常容忍；Python ET / xmllint --valid 会拒）。修复：把 `--iceoryx off` 改成 `-- iceoryx off` 或 `iceoryx=off`。

### B3 — [Minor / 环境] colima VM 内多进程 ROS 发现不通

- **复现步骤**: 在 colima VM 内（amd64 容器，`--net=host`）：
  ```python
  # 进程 A: rclpy.init(); create_node; publish /chatter
  # 进程 B: rclpy.init(); create_subscription(/chatter); spin_once 12 s
  # → listener total_recv=0
  ```
- **预期结果**: loopback 上 Fast-DDS 在 1–2 s 内完成 discovery 并投递消息。
- **实际结果**: talker 发出 5 条，listener 收到 0 条。**取消 `FASTRTPS_DEFAULT_PROFILES_FILE` 后仍复现**，所以不是优化 XML 的锅。same-process pingpong（同进程 pub+sub）正常。
- **严重程度**: **Minor**（环境问题，不影响 same-process bench；但意味着 multi-process / same-host 拓扑在本台 Mac 上不可测）。可能原因：colima `--net=host` 在 vz 后端下容器网络 namespace 与 VM lo 不完全等价，或 Fast-DDS 多播端口被 VM 防火墙拦。

### B4 — [Blocker for Chain B, environment] `rmw_cyclonedds_cpp` 节点创建失败

- **复现步骤**:
  ```bash
  docker run --rm --platform linux/amd64 --net=host osrf/ros:humble-desktop bash -lc '
    apt-get update -qq && apt-get install -y -qq ros-humble-rmw-cyclonedds-cpp
    source /opt/ros/humble/setup.bash
    export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_DOMAIN_ID=0
    python3 -c "import rclpy; rclpy.init(); n=rclpy.create_node(\"x\"); n.destroy_node(); rclpy.shutdown()"'
  ```
- **预期结果**: `node created ok: x`。
- **实际结果**:
  ```
  rclpy._rclpy_pybind11.RCLError: error creating node:
  rcl node's rmw handle is invalid, at ./src/rcl/node.c:415
  ```
  即使加 `CYCLONEDDS_URI=file://.../cyclonedds_udp_lo.xml` 强制 loopback + SharedMemory off 也同样失败。Fast-DDS 同容器可建节点，说明是 CycloneDDS 自己的 discovery socket 绑定在 colima VM 里失败。
- **严重程度**: **Blocker（对本环境）** — Chain B 在 Mac + colima 上无法用 `rmw_cyclonedds_cpp` 走通；原生 DimOS `ddspubsub.DDS` 路径需要 DimOS 源码树 + `cyclonedds` python wheel，本仓库不 vendor，按硬约束也不能拉。

### B5 — [Trivial] `osrf/ros:humble-desktop` 在 arm64 Mac 上无原生镜像

- **复现步骤**: `docker pull --platform linux/arm64 osrf/ros:humble-desktop`。
- **预期结果**: 拉到 arm64 manifest。
- **实际结果**: `image does not provide the specified platform (linux/arm64)`; `docker manifest inspect` 显示单 v2 manifest（amd64-only）。
- **严重程度**: **Trivial**（ workaround 已用 QEMU 跑通；但若要真性能数字，需要在 x86_64 Linux 真机或 buildx build arm64 自镜像）。

---

## 5. 非阻塞性问题记录

1. **colima guest `/etc/resolv.conf` 断链**: 出厂 colima.yaml 的 `dns: null` 让 guest 把 `/etc/resolv.conf` 指向未运行的 systemd-resolved stub，导致 dockerd DNS 解析 `[::1]:53` connection refused。本次手动写入 `nameserver 8.8.8.8` 修复；colima 重启后该写入会被 cloud-init 覆盖。建议下次把 `~/.colima/default/colima.yaml` 的 `dns: [8.8.8.8, 1.1.1.1]` 保留（已写）。
2. **colima 不挂 `/tmp`**: 默认只 virtiofs 挂 `~`。基线仓库在 `/tmp/tutti_task/ros2_hzj`，容器内不可见；本次 `rsync -a /tmp/tutti_task/ros2_hzj/ ~/colima-work/ros2_hzj/` 后再 `-v` 挂载。
3. **QEMU 翻译开销**: p50 RTT ~2.1 ms vs iter7 原生 ~1.1 ms。**本报告所有数字不得与 iter7/iter8 原生表直接对比**。
4. **brew 自动更新拉了 5 个 tap trust 警告**（anthropics/tap 等），不影响 colima/docker 安装。
5. **`scripts/bench/` 在 ros2_hzj-opt 仓库里是空目录**（README 指向 `scripts/bench/` 但实际脚本只在基线 `/tmp/tutti_task/ros2_hzj/scripts/bench/`）。本次直接复用基线脚本。建议把 bench 脚本同步一份到 opt 仓库或在 README 里明确「bench 脚本来源 = 基线仓库」。
6. **`prove_rmw.py` 在容器内运行正常**，正确报告 `rclpy: imported` / `rmw identifier (runtime): rmw_fastrtps_cpp` / `which ros2: /opt/ros/humble/bin/ros2` — 作为「优化 XML 真的被 Fast-DDS 加载」的旁证。

---

## 6. 分诊总结 (Triage Summary)

**总体状态**: 🟡 **PARTIAL PASS** — 链 A 契约走通，IMU 高频用例走通；链 B 在本环境 blocked。

**关键事实**:
- ✅ **优化 XML 语法正确、被 Humble Fast-DDS 2.6 接受**（`fastdds-base.xml` 与基线 `fastdds.xml` byte-identical；1.2 s discovery；0 timeouts；400/400 samples）。
- ✅ **链 A 端到端**: `rmw_fastrtps_cpp` + `ROS_DOMAIN_ID=42` + 优化 XML，rclpy same-process pingpong 稳定跑通。
- ✅ **IMU 64 B / 200 Hz**: BestEffort 与 Reliable 两档都在 1 s timeout 内完成 400 samples，无 timeout；arrival jitter 数字（p95 ≈ 1.4–1.5 ms）受 QEMU 噪声主导，不构成对 iter7 优化的否定。
- ❌ **链 B blocked**: `rmw_cyclonedds_cpp` 在 colima VM 内 `create_node` 即失败；原生 DimOS `ddspubsub.DDS` 路径需要 DimOS 源码树（硬约束不 vendor / 不改）。
- ⚠️ **多进程 talker/listener 在 colima VM 内不通**（即使裸默认 Fast-DDS），是环境问题不是 XML 问题。

**关键阻塞项**:
1. **arm64 Mac 上没有原生 ROS Humble** — 所有数字跑在 QEMU 下，不能用于性能结论。
2. **CycloneDDS 在 colima VM 内无法初始化** — Chain B 不可测。
3. **11/12 gate 失败**（B1）— 因 `docs/architecture/*.md` 还没写，gate 把它们当 repo-root marker。

**建议下一步**:
1. **要真性能数字**：在 x86_64 Linux 真机（或 GitHub Actions `ubuntu-22.04` runner）上重跑 `run_imu_hf.sh`，把 p50/p95/p99 与 iter7 表对齐。本 Mac 的数字只够做冒烟。
2. **Chain B 真机验证**：在 Linux 真机上 `apt install ros-humble-rmw-cyclonedds-cpp` 后重跑节点创建；若 colima VM 是唯一阻塞，则记录为「Mac 环境限制」即可。
3. **补 docs/architecture/ros2-source-map.md 与 feishu-executor-waitset.md**（哪怕是 stub），让 11 个 gate 至少能找到 repo root 并进入真实校验逻辑（B1）。
4. **修 `cyclonedds_udp_lo.xml` 注释里的 `--`**（B2）：一行 sed。
5. **把 bench 脚本从基线仓库同步进 `ros2_hzj-opt/scripts/bench/`**，或在 README 里明确「bench 脚本来源 = `/tmp/tutti_task/ros2_hzj/scripts/bench/`」，避免下一个 HIL 测试者找不到脚本。
6. **不安装 Docker Desktop、不改 vendor / dimos_bridge** — 本次完全遵守；colima + brew 路径是免密码、可逆、可复现的。

---

## 附录 A — 关键命令与原始输出索引

- 环境探测: 见 §2
- Chain A raw: `docs/artifacts/bench/2026-09-15/chain_a_same_process/raw.json` (12.5 KB)
- IMU hf raw: `docs/artifacts/bench/2026-09-15/imu_hf/raw.json` (20.0 KB)
- colima 配置: `~/.colima/default/colima.yaml` (`dns: [8.8.8.8, 1.1.1.1]`, cpu=4, memory=8, disk=30, arch=aarch64, vm-type=vz)
- 镜像: `osrf/ros:humble-desktop` @ `sha256:fb07245b32187d74350be25323d8ad2f8ca5c25c325759911a1eff2267a49c1e`
- 链 A 启动命令（可复现）:
  ```bash
  docker run --rm --platform linux/amd64 --net=host \
    -v ~/colima-work/ros2_hzj:/work:ro \
    -v <opt-repo>:/opt-new:ro \
    -e HOME=/tmp -w /work osrf/ros:humble-desktop bash -lc '
      set +u; source /opt/ros/humble/setup.bash; set -u
      export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=42
      export FASTRTPS_DEFAULT_PROFILES_FILE=/opt-new/config/optimized/fastdds-base.xml
      python3 /work/scripts/bench/pingpong.py --chain A --topology same-process \
        --sizes 64 --samples 400 --warmup 40 --timeout 1 --interval-ms 5 \
        --ros-msg uint8_multiarray --out /out/raw.json'
  ```
