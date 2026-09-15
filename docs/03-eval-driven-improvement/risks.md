# 《3》剩余风险与薄弱环节 risks.md

更新：2026-09-15 · 机器 macOS arm64 · 无 `/opt/ros`、无 Docker、无第二条机器

## R1. 无 ROS 运行时，无法端到端验证（最高风险）

- **事实：** `prove_rmw.py` 实测 `rclpy: not importable (ModuleNotFoundError)`、`which ros2: (not on PATH)`、`ROS_DISTRO/(unset)`。
- **后果：** 本循环产出的 4 个优化 XML 全部是**配置级提案**，没有一个被 ROS 进程加载过，没有一次 ping-pong 被真正跑过。XML 的正确性只到"well-formed + 关键参数在位"，不代表 Fast DDS 2.6 / Cyclone 11.0.1 会按预期解析并生效。
- **缓解/下一步：** 必须在装了 Humble + Docker 的 Linux（x86_64 或 aarch64）机器上：
  1. `source config/env/chain_a.sh`，把 `FASTRTPS_DEFAULT_PROFILES_FILE` 指向优化 XML；
  2. 跑 `scripts/bench/run_chain_a.sh`，以 `config/fastdds.xml`（iter7）为对照；
  3. 按 SCOREBOARD 口径看 jitter（RTT p95/p99 + arrival |I−gap| p95），**不是 p50**；
  4. 任一旋钮回退 1MiB 或 arrival jitter 变差即丢弃（沿用 iter8/iter9 的否决纪律）。

## R2. 配置优化未经真实测量，参数取值是工程推断不是证据

- 8MiB socket 缓冲、depth=1、flow controller token 周期等取值，依据是 doc2.md 的内核网络栈分析与 SCOREBOARD 已验证档位，**没有本机复测**。
- 风险：Fast DDS 2.6 对 `<flow_controllers>`、`<builtin><discovery_config>` 的 schema 支持需要实测；Humble 上某些标签名可能与 Rolling 不同（doc3.md 警告：不能把 Rolling 标签套到 Humble）。
- **缓解：** 合并前用 `FASTRTPS_LOG_CATEGORY=ALL` 或 `-l trace` 确认 XML 被解析、目标 transport 被选中（doc3 §1.1：publish 后必须抓实际 transport 分支，不能只看调用栈）。

## R3. 跨机 UDP blocked（单 VM，单网卡）

- `docs/artifacts/bench/2026-09-11-cross-host/BLOCKED.txt` 原文："cross-host-UDP needs a second machine; this runner is single-host"。
- doc2.md 的核心结论——发现风暴、多播脆弱性、跨机重传——**全部无法在本机验证**。跨机 discovery-server / StaticEndpoint 建议停留在注释层。
- **缓解：** 需第二台机器 + PTP/NTP 时钟同步后再测；doc3.md 警告：跨机延迟先校时钟，否则"网络延迟"可能只是时钟偏差。

## R4. 基线证据树是"恢复"进来的，非本仓原生

- Iter0 从 `/tmp/tutti_task/ros2_hzj` 逐字拷贝了 architecture 文档、dimos_bridge、vendor 指针文件。这些是**他机/他仓证据**，本仓库未重新生成。
- 风险：`/tmp` 可能被清理；拷贝是只读快照，与上游 `topsun-bot/ros2_hzj` 后续 commit 可能漂移。
- **缓解：** 真正落库时应把这套基线证据固化为本仓的 `docs/architecture/` 与 `vendor-ref/VERSIONS.md` 引用，而非依赖 /tmp。本循环已把它们落在本仓库内，但仍属"快照拷贝"，需在正式 PR 中对上游 commit 做 diff 复核。

## R5. 软链与脚本双份

- `scripts/check_executor_map.py`、`scripts/check_risk_matrix.py` 是指向 `scripts/gates/` 的软链；`scripts/prove_rmw.py`、`scripts/check_source_map.py` 是实体副本（闸门按 repo-root 相对路径引用）。
- 风险：后续改了 `scripts/gates/` 下的实现而忘记软链/副本一致性。
- **缓解：** 软链无漂移；实体副本应与 `gates/` 保持同一内容，改闸门时同步。

## R6. 被刻意不做的方向（纪律，非缺陷）

按 SCOREBOARD iter10 与 AGENTS.md Hold，以下方向**本循环没有碰**，避免重蹈已否决旋钮：
- 不调 `leaseAnnouncement`/`leaseDuration`（iter8 否决）；
- 不关 WLP（iter9 否决）；
- 不调 SHM `port_queue_capacity`（iter6 否决）；
- 不开 exclusive/oversized SHM（iter5 回退 1MiB）；
- 不绑核/不设 affinity（共享 VM 无 isolcpus，噪声不可分离）；
- 不引入 Agnocast / zenoh / iceoryx / Cega（Hold）；
- 不修改 vendor 源码、不改 dimos_bridge、不改 `fastdds-base.xml`。

## 结论

闸门 13/13 全绿、总分 100%，但**这是配置与文档自洽的分**。性能闭环的真正门槛在 R1——把优化 XML 搬到有 ROS 的机器上做对照复测，并用 `collect_scores.py` 汇总真实 raw.json。在那之前，所有优化配置都应被视为"待验证提案"，不得对外宣称性能提升。
