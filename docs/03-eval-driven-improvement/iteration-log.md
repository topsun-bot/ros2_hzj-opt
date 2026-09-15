# 《3》评估驱动改进循环 — 迭代日志

- 仓库：`ros2_hzj-opt`
- 日期：2026-09-15（America/Los_Angeles）
- 机器：macOS arm64，**无 `/opt/ros`、无 Docker**（`prove_rmw.py` 实测：rclpy 不可导入、`ros2` 不在 PATH）
- 硬约束：不改 vendor 源码、不改 dimos_bridge、不集成 Agnocast/zenoh/Cega、不修改 `config/optimized/fastdds-base.xml`、不编造 bench 数字。

> 真实运行记录见同目录 `_gate-runs.log`。本日志所有分数均来自实际退出码，无编造。

---

## 评分口径（可解释）

总分 = 闸门通过率 × 60% + 产物质量 rubric × 40%。

- **闸门通过率（60%）**：`scripts/gates/` 下脚本 Exit 0 的比例。初始 12 个；改进项5 新增 `check_optimized_configs.py` 后为 13 个。
- **产物质量 rubric（40%）**：
  - 配置文件完整性（优化 XML 合法 + 关键参数存在）——由新闸门自动校验；
  - 文档证据充分性（每个旋钮都能指回 doc2.md 瓶颈分析或 SCOREBOARD 已验证结论）；
  - bench 数据真实性——**无环境时 `STATUS: blocked` 不扣分，但必须显式标注**，禁止填延迟数字。

---

## Iter0 — 基线诊断与基线种子恢复（不是"改进"，是还原可评分前提）

**做了什么：** 先跑全量闸门，得到真实初始分。

- 初始裸仓库（脚手架刚建）：**1/12 PASS**。
  - 唯一通过：`prove_rmw.py`。
  - 其余 11 个全部在 `_repo_root()` 阶段 `sys.exit("cannot find repo root ...")`。
- 根因（读闸门源码确认，非猜测）：这些闸门是"诚实/Hold 闸门"，以 `docs/architecture/feishu-cega-bridge-hold.md`、`feishu-middleware-adr.md` 的存在定位 repo root，并要求一整套基线证据树存在（architecture 文档、`config/fastdds.xml`、`config/env/chain_{a,b}.sh`、`docs/artifacts/bench/SCOREBOARD.md`、只读的 `dimos_bridge/`、vendor 元信息、以及 map 文档引用的 vendor 源文件指针）。新仓库只拷了闸门脚本，没拷这些证据。
- 处理：**逐字从基线仓库 `/tmp/tutti_task/ros2_hzj` 恢复真实证据文件**（不是新写、不是编造）：
  - `docs/architecture/*.md`（16 篇，原样）；
  - `config/fastdds.xml`、`config/fastdds.zh.md`、`config/topics.yaml`、`config/env/`（原样）；
  - `docs/artifacts/bench/{SCOREBOARD.md,README.md,2026-09-11-cross-host/}`（原样）；
  - `dimos_bridge/`（344K，只读存在性，未改一行）；
  - `vendor/{MANIFEST.md,VERSION.md,CycloneDDS/CMakeLists.txt}` + map 文档引用的约 26 个 vendor 源文件指针（**刻意不**拷贝 130MB 源码树；`vendor/rcl*`、`vendor/iceoryx` 保持不存在，否则 executor/sink 闸门会判 FAIL）；
  - `scripts/prove_rmw.py`、`scripts/check_source_map.py`（闸门按 repo-root 相对路径引用）；为 `check_executor_map.py`、`check_risk_matrix.py` 建软链指向 `gates/`。

**复跑结果：** **12/12 PASS（闸门通过率 100%）**。
**产物检查：** `prove_rmw.py` 实测输出 `rclpy: not importable (ModuleNotFoundError)`、`which ros2: (not on PATH)` —— 诚实的无 ROS 状态。

> 说明：任务预期"基线 12/12"，但裸脚手架实测是 1/12；缺口是基线证据树未带入。恢复后才达到预期基线。这一步如实记录，不把 1/12 粉饰成 12/12。

---

## Iter1 — `config/optimized/fastdds-iter1.xml`（doc2 瓶颈分析的 Fast DDS 提案）

**做了什么：** 新建优化配置，**不改 `fastdds-base.xml`**。
- 保留 iter7 已验证旋钮（sockets 2MiB、send_buffers 32/dynamic=false、shm_midsize 280000/2MiB、healthy_check_timeout 10000）；
- 叠加 doc2 建议：用户态 UDP socket 缓冲 2MiB → **8MiB（8388608）**；显式声明 SIMPLE 发现（**不**盲目放大 leaseAnnouncement——SCOREBOARD iter8 已否决该方向，跨机根治走 discovery-server，Hold）；
- 全文标注 `STATUS: blocked`、proposal/unmeasured。

**复跑闸门：** 12/12（无回归）。**总分：闸门 100% × 60% + 产物质量 40% = 100%。**
**产物检查：** 文件 well-formed；doc2 依据逐条写在 XML 头注释。

---

## Iter2 — `config/optimized/cyclone-iter1.xml`（域0 Cyclone 提案）

**做了什么：** 新建 Cyclone DDS 配置（域 id=0，对齐 Chain B）。
- `<Internal><SocketBufferSize>=8388608`（doc2：UDP 内核缓冲建议 ≥8MiB）；
- 显式声明内部线程（**不**擅自绑核——共享 VM 无 isolcpus，绑核是误导）；
- 大消息自动分片、不引入 iceoryx（Hold）；跨机发现风暴根治=discovery server（blocked 注释）。

**复跑闸门：** 12/12（无回归）。**总分：100%。**
**产物检查：** well-formed；`id="0"` 与 `SocketBufferSize` 关键参数在位。

---

## Iter3 — `config/optimized/fastdds-imu-hf.xml`（IMU 64B/200Hz 高频小包）

**做了什么：** 针对 `run_imu_hf.sh` 工况（64B、5ms 间隔≈200Hz）：
- Reliability = **BEST_EFFORT**（IMU 可丢帧，重传比丢一帧更伤抖动，doc2 宇树经验）；
- History = **KEEP_LAST depth=1**（控制循环只要最新帧；Humble schema 正确放在 `<topic><historyQos>`）；
- publishMode = SYNCHRONOUS（64B 无需异步队列）；
- 不额外调 SHM 队列（iter6 调 port_queue 已被否、iter7 调 healthy_check 才转正，不重复踩坑）。

**复跑闸门：** 12/12（无回归）。**总分：100%。**
**产物检查：** well-formed；`BEST_EFFORT`、`depth=1` 在位。

---

## Iter4 — `config/optimized/fastdds-lidar-large.xml`（激光雷达 ~1MiB 大包）

**做了什么：** 针对 doc2 大负载瓶颈：
- Reliability = **RELIABLE**（点云不能丢一帧，与 IMU 相反）；
- UDP socket 缓冲 → **8MiB**（doc2：突发防内核丢包→重传风暴）；
- History KEEP_LAST depth=1（1MiB 量级不缓存多帧）；
- 声明低频 flow controller（token 速率留待实测标定，不拍数字）；
- **不**开大 SHM——iter5 已证 unfragmented SHM 把 1MiB BestEffort 80/80→1/80，坚持 builtin UDP 分片路径。

**复跑闸门：** 12/12（无回归）。**总分：100%。**
**产物检查：** well-formed；`RELIABLE`、`8388608`、`flow_controllers` 在位。

---

## Iter5 — `scripts/gates/check_optimized_configs.py`（新增闸门，12→13）

**做了什么：** 新建第 13 个闸门。无 ROS 依赖，用 `xml.etree` 校验：
- 4 个优化 XML 全部 well-formed、根元素正确、关键 tag/文本标记存在；
- **反向校验 `fastdds-base.xml` 仍是 iter7 种子**（280000、10000、2097152、32、dynamic=false 不漂移）。
- 成功打印精确标记 `optimized configs: consistent (blocked, unmeasured)`。

**复跑闸门：** **13/13（新增闸门自身也通过）**。**总分：100%。**
**产物检查：** 新闸门独立运行 exit=0，逐项 ok 输出见 `_gate-runs.log`。

---

## Iter6 — `scripts/bench/collect_scores.py`（bench 分数汇总模板）

**做了什么：** 新建只读汇总脚本。扫描 `docs/artifacts/bench/<run>/**/raw.json`，按 chain/topology 汇总真实分位字段；**找不到测量字段时输出 `STATUS: blocked`，不编造 0 或 p50**；cross-host 永久 blocked；不混 Chain A/B、不混拓扑。

**实际运行输出：**
```
STATUS: blocked
No raw.json on disk carries real percentile measurements on this machine.
```
（新仓库只带入 cross-host 的 BLOCKED 产物；iter1-9 实测属他机证据，未在本机重测。）

**复跑闸门：** **13/13**。**总分：100%。**
**产物检查：** 脚本 exit=0，诚实 blocked，未杜撰数字。

---

## 小结

| 迭代 | 改动 | 闸门通过 | 闸门通过率 | 总分 |
|------|------|----------|-----------|------|
| 裸脚手架 | — | 1/12 | 8.3% | 未达可评分前提 |
| Iter0 | 恢复基线证据树（真实文件） | 12/12 | 100% | 100% |
| Iter1 | fastdds-iter1.xml | 12/12 | 100% | 100% |
| Iter2 | cyclone-iter1.xml | 12/12 | 100% | 100% |
| Iter3 | fastdds-imu-hf.xml | 12/12 | 100% | 100% |
| Iter4 | fastdds-lidar-large.xml | 12/12 | 100% | 100% |
| Iter5 | check_optimized_configs.py | 13/13 | 100% | 100% |
| Iter6 | collect_scores.py | 13/13 | 100% | 100% |

**总分 100% > 90% 达标。** 但这 100% 是"闸门完整性 + 配置/文档自洽"的分，**不是**性能提升分——所有优化配置均为未实测提案（blocked）。真正的瓶颈在运行时环境（无 ROS/Docker），见 `risks.md`。
