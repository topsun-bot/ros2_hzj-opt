# 《2》ros2_hzj 现代化重构计划

> 输入：
> - 选型会议纪要（2026-07-10 智能纪要）：评价标准 = **低延迟且抖动小 / CPU 低 / 丢包少 / 100 小时不崩 / ROS 生态兼容**，且必须基于激光雷达大包、IMU 高频等**真实业务场景**测试；最优路径 = 把自研中间件包成 **RMW 适配层**，上层应用无感、环境变量切换。
> - 基线仓库：`/tmp/tutti_task/ros2_hzj`（以下「本仓」）。
>
> 硬约束（继承自仓库 R0 冻结与 AGENTS.md）：
> - **不改 `vendor/` 源码行为**（整树普通目录拷贝，SHA 钉在 `vendor/VERSIONS.md`）。
> - **不改 `dimos_bridge/` 运行时**（整文件拷贝，相对路径不变）。
> - **公共 API 保持稳定**：R0 冻结表（域 42/0、topic 名、QoS 种子）不变。
> - 本计划是**文档/计划**，不直接改 vendor 代码；所有「改」都落在本仓自有面（`config/`、`scripts/`、`docs/`、CI 闸门、Docker 配方）。
> - 跨机 UDP 仍 `STATUS: blocked`（单机 / yixin Docker DOWN）；不写假分位数。

---

## 0. 为什么要重构：变更速度在被什么拖慢

本仓当前状态是一个**契约先行、行为冻结**的工作区：R1–R5 结构抽出已落地（env helper、XML 种子、Dockerfile 拆分、topic 常量、bench 说明），但「可对照的面」建得很快，「可演进的面」还没建起来。7/10 会议把目标定得很清楚——**原生 ROS 2 延迟波动大、CPU 高、偶发消息追击，行业量产普遍魔改**——而本仓现在的结构还停留在「把上游原样拷进来 + 文档记账」的阶段。

下面第 1 节先把**拖慢变更速度**的结构性问题逐个点名（具体到文件/模块），第 2 节给出小步、可审查的重构步骤，第 3–7 节拆分工作、冻结 API、单列迁移任务、列前置规范、给路线图。

---

## 1. 问题识别（具体到文件/模块）

### 1.1 `vendor/` 整树普通目录拷贝，非 submodule

**现状（可核对）：**

- `vendor/VERSIONS.md` 开篇即声明：「本目录是**整树文件拷贝**，不是 git submodule，也不是 subtree 远端跟踪……浅克隆后去掉 `.git`，禁止 gitlink。」
- 体积：`du -sh vendor/*` 实测 `vendor/Fast-DDS` = **102M**、`vendor/CycloneDDS` = 24M、`vendor/rmw_fastrtps` = 1.7M、`vendor/rmw` = 1.0M、`vendor/rmw_cyclonedds` = 556K、`vendor/rmw_implementation` = 492K；`find vendor -type f | wc -l` = **7617 个文件**。
- SHA 钉在一张表里（`rmw` rolling `1e58706…`、`Fast-DDS` master `343f155…`、`CycloneDDS` tag `11.0.1` `e54e991…` 等），上游 URL 只用于追溯。
- `vendor/Fast-DDS/thirdparty/*` 原本是 gitlink，已「摊成普通目录」，SHA 另列一表。

**拖慢变更的点：**

1. **升级 = 重新整树覆盖 + 手抄 SHA。** 上游打 patch 版本时，本仓没有 `git submodule update` 这种机制，只能人肉比对拷贝；7617 个文件的 diff 无法靠 `git log` 看出「本仓改了什么」。
2. **本仓自有改动和上游代码混在一棵树里。** 一旦有人在 `vendor/` 下手滑改一行，没有上游 `.git` 兜底，也没有 submodule 边界能机械区分「上游代码 vs 本地补丁」——这正是 R0 文档反复强调「不要把 vendor 落盘当时延根因」的根因。
3. **CI 不编译 vendor 树**（README 明说「CI **不**完整编译这些树」），所以 vendor 内部编译错误要等到真跑 colcon 才爆，反馈链长。

> 注意：本节**只**识别维护成本，**不**建议立即换 submodule。硬约束是「不改 vendor 源码行为」，换 submodule 会动构建来源，属于第 5 节的**独立迁移任务**，本阶段先把「升级流程」写成文档。

### 1.2 双链（Fast DDS 域 42 + Cyclone 域 0）配置重复与漂移风险

**现状（可核对）：**

- 域/QoS 真值分散在**至少五处**：
  1. `docs/architecture/ros2-dds-r0-interface-freeze.md` §1 冻结表；
  2. `config/fastdds.xml` 第 108 行 `<domainId>42</domainId>`；
  3. `config/env/chain_a.sh` 写死 `export ROS_DOMAIN_ID=42`、`export RMW_IMPLEMENTATION=rmw_fastrtps_cpp`；
  4. `config/topics.yaml` `discovery.chain_a_ros_domain_id: 42` / `chain_b_cyclone_domain_id: 0`；
  5. `dimos_bridge/dimos/protocol/dds_topics.py`（R4 说「与 topics.yaml 对齐」）。
- 链 B 还有第三处来源：`DDSConfig.domain_id`（DimOS 拷贝模块里**写死默认 0**）与 Unitree `ChannelFactoryInitialize(0)`；`chain_b.sh` 注释自己承认「原生 DimOS DDS 读的是 DDSConfig.domain_id，不是这些 ROS 变量」。

**拖慢变更的点：** 改一次域 ID 或 RMW 名要同时改 5 个文件，且其中两个（`DDSConfig.domain_id`、Unitree 调用点）在**只读拷贝**里，改不了——这意味着「双链配置」本质上是**双向漂移**：本仓能改的 3 处和上游写死的 2 处之间没有机械约束。`check_dual_chain_baseline.py` 只是指针闸，不做跨文件一致性。

### 1.3 `dimos_bridge/` 整文件拷贝的同步问题

**现状（可核对）：**

- `dimos_bridge/SOURCE.md`：上游 `topsun_dimos` main @ `a5259958db23c8ea6648544ed138eab19726ce93`，「整文件拷贝，本 PR 不做功能重构」；列出 11 个拷贝文件 + 已删死代码清单 + 占位 stub 清单。
- 67 个 `.py` 文件、332K。其中 `__init__.py` 和多个 ImportError stub「不是运行时」。
- `README.md` 自己警告：「完整 DimOS 依赖仍在上游；本仓缺依赖时命令会在 import 处失败——那是环境问题，不是『已经测过』。」

**拖慢变更的点：**

1. **上游演进看不见。** `topsun_dimos` 继续提交时，本仓这 11 个文件是死快照；没有任何脚本提示「上游某文件已经比我们新」。
2. **stub 与真实现同名。** `__init__.py` / ImportError stub 让人在 IDE 里以为模块存在，实际 import 即炸——新人第一次跑 bench 最容易踩。
3. **「已删死代码」靠 Markdown 记账。** `SOURCE.md` §已删列了 `encoders.py`、`patterns.py`、foxglove LCM viewer 等，但没有机器校验保证它们没被人重新拷回来。

### 1.4 RMW 层抽象开销（`rcl_wait` 与 DDS 等待接口不匹配）

**现状（来自 doc2.md §2 源码级结论，对照本仓 RMW 栈）：**

- 核心开发者明确指出 `rcl_wait` 开销异常显著，源于 **RMW 等待接口与 DDS 原生等待接口「彻底不匹配（total mismatch）」**。
- 本仓 RMW 栈 = `vendor/rmw`（rolling `7.11.2`）→ `rmw_implementation` → `vendor/rmw_fastrtps` / `vendor/rmw_cyclonedds`。`docs/architecture/feishu-executor-waitset.md` 已有 WaitSet→callback 身份图，但**明确注明 Humble `rclcpp`/`rclpy` 不在 vendor 里**。

**拖慢变更的点：** 这条瓶颈在本仓**无法直接改**（改 `rcl_wait` = 改 vendor/发行版 rcl，违反硬约束），但它决定了**上层 Executor 选型**是本仓唯一能动的旋钮。当前仓里只有地图、没有「回调隔离 Executor / 自定义 wait set」的对照实验方案文档——优化主张停在 doc2 的转述，没落成可执行的本仓建议。

### 1.5 序列化机制与动态类型零拷贝失效

**现状：**

- `config/topics.yaml` / R0 冻结表里的高带宽 topic：Go2 `lidar` / `global_map` = `sensor_msgs/PointCloud2`，`color_image` = `sensor_msgs/Image`——正是 doc2 §2 点名的「内含 `std::vector` / `uint8[]` 动态数组、Iceoryx 只对定长 POD 真零拷」的类型。
- `config/fastdds.xml` iter5 注释已记录一次相关试错：加了 `shm_midsize`（`maxMessageSize=280000` / `segment_size=2MiB`），**1MiB 点云仍走 builtin fragment 路径**（sample > 280000 被分片）。iter5/iter6/iter7 反复围绕中包 SHM 抖动调参。

**拖慢变更的点：** XML 注释（95 行迭代史）是**好记账**，但它把「为什么 1MiB 零拷没生效」这条因果埋在 XML 注释里，而不是在架构文档里。下次有人想再调 SHM，要重翻 XML 注释才能知道「大 SHM 段试过、丢了 1MiB BestEffort、已废弃」。

### 1.6 发现风暴与节点到参与者映射

**现状：**

- doc2 §2：DDS 内置发现流量随节点/Pub/Sub 数呈 O(N²) 多播风暴；`node-to-participant mapping`（单进程共享 Participant）只能缓解单进程内问题。
- 本仓双链本身就是**两个 Participant**（域 42 + 域 0），没有跨 Participant 共享；`fastdds.xml` iter8 试过 `leaseAnnouncement 3s→15s` 压发现，**因 arrival jitter 变宽被回退**（XML 注释 77–84 行有完整记录）。

**拖慢变更的点：** 发现调参在本仓已经证明「单旋钮调 lease 会伤 jitter」，但这条教训只存在 XML 注释里；架构文档没有一页「发现风暴在本仓的边界 + 哪些旋钮试过且被否决」的速查表。

### 1.7 Executor 调度的长尾抖动

**现状：**

- 7/10 会议把「**延迟波动小**」和「低延迟绝对值」并列列为第一评价标准；doc2 指出 Executor 重度依赖 WaitSet，长尾由调度不确定性 + `rcl_wait` 不匹配共同造成。
- 本仓 bench（`scripts/bench/`、`docs/artifacts/bench/`）已经**以 jitter 为主指标**做过 iter6（64B/200Hz IMU，gate 是 p95/到达间隔而非 p50）——这是对的方向，但 bench 只覆盖「同机同拓扑 ping-pong」，**没有覆盖多节点并发下的长尾**（doc4 要求「激光雷达大包 + IMU 高频」混合场景）。

**拖慢变更的点：** 长尾没有混合负载基线，任何 Executor 改动都无法证伪「是不是更差了」。

### 1.8 配置文件（`fastdds.xml`）与代码的耦合

**现状：**

- `config/fastdds.xml` 用 95 行 XML 注释记录了 iter1–iter9 全部旋钮史（含被回退的 iter8/iter9、被废弃的 iter3/iter6 探针）。
- 同时 `config/fastdds.zh.md` 是中文说明；`config/env/chain_a.sh` 又用环境变量指回这个 XML；`topics.yaml` 是第三份 topic/QoS。
- AGENTS.md 明令：「Do not edit `config/fastdds.xml` or `docs/artifacts/bench/SCOREBOARD.md`」——即 XML 是**冻结资产**，但它同时又是**开发记录本**，两个角色冲突。

**拖慢变更的点：** 一个「冻结契约文件」里塞了半份实验日志，review 任何一行 XML 都要通读 95 行注释才能判断「这行是契约还是临时探针」。

---

## 2. 重构步骤（每步：当前行为 → 结构性改进 → 验证检查）

> 原则：每步**单独可 PR、单独可回滚、行为不变**；先把「账」从代码里搬到 docs/CI，再谈演进。

### R6 — 把 `fastdds.xml` 的迭代史从 XML 注释外移

- **当前行为**：`config/fastdds.xml` 第 2–95 行是 iter1–iter9 旋钮史（含回退/废弃记录），XML 本体只剩 96–132 行。
- **结构性改进**：把这段史**逐字**搬到 `docs/architecture/fastdds-xml-tuning-log.md`；XML 顶部注释只留三行：契约种子指 R0 冻结表 + 指 tuning log + 指 `fastdds.zh.md`。XML **数值一个不动**（仍 iter7：`shm_midsize` 280000/2MiB/`healthy_check_timeout_ms=10000`、socket 2MiB、send_buffers 32/dynamic=false）。
- **验证检查**：
  1. `diff <(grep -v '^\s*<!--' fastdds.xml | grep -v '^\s*-->' | grep -v '^\s*$')` 前后一致（XML 有效节点集合不变）；
  2. `xmllint --noout config/fastdds.xml`（或 Fast-DDS XMLPARSER 等价校验）通过；
  3. 新增 CI 脚本 `check_fastdds_xml_frozen.py`：对契约节点（`domainId`、两个 socket buffer、`maxMessageSize`、`segment_size`、`healthy_check_timeout_ms`、`preallocated_number`、`dynamic`）做**值断言**，动一个就红。

### R7 — 双链契约「单一事实源」抽取

- **当前行为**：域/RMW/topic/QoS 散在 §1.2 列的五处。
- **结构性改进**：以 `config/topics.yaml` 为**唯一机器可读契约**（它已是 R4 产物），做两件事：
  1. 写 `config/env/contract.py`（纯读取、不写 `os.environ`），从 `topics.yaml` 读 `chain_a_ros_domain_id` / `chain_b_cyclone_domain_id`，`chain_a.sh` / `chain_b.sh` / `load.py` 改为**生成自**这个 contract（或至少 `load.py` 启动时 assert 自己的常量 == YAML 常量）；
  2. `dds_topics.py` 顶部加一行 assert，启动时与 `topics.yaml` 对一次哈希；不一致即 fail-fast（不改 runtime 行为，只在 import 期报警）。
- **验证检查**：
  1. 新 CI `check_contract_consistency.py`：对比 `topics.yaml`、`load.py` 常量、`chain_*.sh`、`dds_topics.py` 四处域/RMW 名，任一漂移即红；
  2. `python3 config/env/load.py print-a` / `print-b` 输出与现状逐字节一致。

### R8 — `dimos_bridge` 上游漂移巡检脚本

- **当前行为**：`SOURCE.md` 手抄上游 SHA `a5259958…`，无机器巡检。
- **结构性改进**：加 `scripts/check_dimos_upstream_drift.py`（只读、无网络也能跑离线模式）：
  1. 离线：把 `SOURCE.md` 列出的 11 个拷贝文件做成清单 + 本仓文件 sha256 表；
  2. 可选在线（显式 `--fetch`）：只读 `topsun_dimos` main 对应路径，比对 mtime/SHA，输出「上游已更新但本仓未同步」清单；
  3. 把「已删死代码」清单（`encoders.py`、`patterns.py`、foxglove viewer 等）变成 CI 负向断言：这些路径若在 `dimos_bridge/` 下重现即红。
- **验证检查**：
  1. 离线模式在本仓 HEAD 上必须全绿；
  2. 人为 touch 一个已删死代码路径 → CI 必须红；
  3. stub 文件清单（`__init__.py` / ImportError stub）从 SOURCE.md 机读，确保「stub 不是运行时」在 CI 里可枚举。

### R9 — vendor 升级流程文档化（不改树）

- **当前行为**：`vendor/VERSIONS.md` 是唯一 SHA 表；升级靠人肉。
- **结构性改进**：写 `docs/architecture/vendor-upgrade-playbook.md`，把「升级某一链」拆成可执行清单：
  1. 选定上游 tag/commit → 更新 `VERSIONS.md` 两行；
  2. 重新整树覆盖（保留「无 `.git`、无 gitlink」约束）；
  3. `git diff --stat vendor/<tree>` 评审；
  4. 在 docker 镜像里跑一次编译冒烟（不进 PR 门，只进 nightly）；
  5. 明确**什么算本仓自有补丁**：vendor 树下**不允许**出现本仓非上游 diff；如必须改，走第 5 节迁移任务，不在 vendor 树里改。
- **验证检查**：
  1. 新 CI `check_vendor_no_local_patch.py`：对 `vendor/*` 跑 `git diff` 之外的轻量指纹（如每树一份 `FILES.sha256`，由升级流程生成），检测非预期改动；
  2. 文档中明确「submodule 化是独立迁移任务，见第 5.1」，本步**不做**。

### R10 — 发现/Executor 调参「试过且否决」速查表

- **当前行为**：iter8（leaseAnnouncement）、iter9（WLP off）、iter3 大 SHM 段、iter6 `port_queue_capacity` 全部「试过、jitter 门没过、已回退/废弃」，记录散在 `fastdds.xml` 注释里。
- **结构性改进**：新建 `docs/architecture/tuned-and-rejected.md`，一张表收编：旋钮名 / 试过的值 / 当时 gate（p95、arrival |I−5ms|） / 结论（保留/回退/废弃） / 下次要不要重试。
- **验证检查**：
  1. 表中每一行可被 `docs/artifacts/bench/` 产物（p50/p95/p99 文件）反查；
  2. CI `check_tuning_log_refs.py`：表中引用的 bench 产物路径必须真实存在；
  3. 今后任何新旋钮 PR 必须先在这张表登记「试什么、gate 是什么」，否则模板检查红。

### R11 — 长尾/混合负载 bench 基线（文档 + 脚本骨架）

- **当前行为**：bench 是单 topic ping-pong；缺「激光雷达大包（~1–8MB PointCloud2）× IMU 200Hz 并发」的混合场景（doc4 硬要求）。
- **结构性改进**：
  1. 扩 `docs/usage/benchmark-dds.md`：定义混合负载 profile（payload 分布、频率、并发 topic 数、长尾指标 = p99 与 max，**不是 p50**）；
  2. 在 `scripts/bench/` 加 `run_mixed_profile.sh` 骨架：能跑就跑，跑不了（无 Humble / 无 Docker）就照现有惯例写 `STATUS: blocked`，**不造数**；
  3. 明确「100 小时不崩」怎么测：长稳 runner + 崩溃/丢包计数，先写定义，不承诺结果。
- **验证检查**：
  1. 脚本在无 Humble 环境下退出码与现有 `run_chain_*.sh` 一致（blocked 不红）；
  2. 产物目录新增 `mixed/` 占位 README，沿用「缺环境写 blocked」规则。

### R12 — RMW/WaitSet 抽象开销的本仓对照建议（纯文档）

- **当前行为**：§1.4 瓶颈只在 doc2 转述，本仓没有「在硬约束内能动什么」的结论页。
- **结构性改进**：在 `docs/architecture/` 加 `rmw-waitset-overhead.md`，明确三栏：
  - **不能动**：`rcl_wait`、`rmw` C ABI（vendor/发行版）；
  - **文档级建议**：上层用回调隔离 Executor（CallbackIsolatedGroup / 每回调一个线程），避免长回调拖长尾——这是 doc2 给的缓解策略，本仓只做对照建议不改代码；
  - **未来钩子**：会议定的「自研中间件包成 RMW」路径，见第 5.2 独立迁移任务，本步不集成。
- **验证检查**：文档每条主张标注来源（doc2 章节号 / 本仓 `feishu-executor-waitset.md`），CI 检查无悬空引用。

---

## 3. 工作拆分（小步、可审查）

按「风险从低到高、纯文档/脚本在前」排序，每步都是一个 PR：

| 序号 | 步骤 | 体量 | 行为变更 | 依赖 |
|------|------|------|----------|------|
| R6 | XML 迭代史外移 + XML 值断言 CI | ~1 文件搬注释 + 1 个新 CI 脚本 | 无 | 无 |
| R7 | 双链契约单一事实源（YAML 为唯一真） | 1 新 `contract.py` + 改 3 个 env helper | 无（只加 assert） | R6 |
| R10 | 「试过且否决」速查表 | 1 新 md + 1 引用检查脚本 | 无 | R6 |
| R8 | dimos_bridge 上游漂移巡检 + 死代码负向断言 | 1 新脚本 + SOURCE.md 机读 | 无 | 无 |
| R9 | vendor 升级 playbook（不改树） | 1 新 md + 1 指纹脚本 | 无 | 无 |
| R12 | RMW/WaitSet 本仓对照建议（纯文档） | 1 新 md | 无 | 无 |
| R11 | 混合负载 bench 骨架 + 长尾定义 | 1 脚本骨架 + 改 bench 文档 | 无（blocked 不红） | R10 |

> 删除死代码、简化控制流：本仓死代码已被 `SOURCE.md` 显式删除过一轮（§已删清单），**新一轮「删死代码」就是 R8 把它变成 CI 负向断言**——不需要再人肉翻代码，而是机器守门。提取辅助函数：R7 的 `contract.py`、R9 的指纹脚本都是「从重复配置里提一个 helper」的标准动作。替换过时模式：`fastdds.xml` 注释即「过时的实验记录混在契约里」，R6 把它移出，即替换完成。

---

## 4. 公共 API 稳定性

### 4.1 保持不变（R0 冻结，不许动）

| 面 | 契约 | 出处 |
|----|------|------|
| 链 A RMW 名 | `rmw_fastrtps_cpp` | R0 冻结表 / `chain_a.sh` |
| 链 A 域 | `ROS_DOMAIN_ID=42` | R0 / `fastdds.xml` / `topics.yaml` |
| 链 B 域 | Cyclone `domain_id=0`（DimOS 写死）/ `ChannelFactoryInitialize(0)` | R0 / Unitree 调用点 |
| `/foxglove_teleop→/cmd_vel`、`/goal_pose`、`/way_point`、`/joy` 的 topic 名与 QoS | 见 `topics.yaml` | R0 §2 |
| Go2 四流（`lidar`/`global_map`/`odom`/`color_image`）类型 | `PointCloud2`/`PoseStamped`/`Image` | `unitree_go2_ros.py` 绑定 |
| `source config/env/chain_a.sh` / `chain_b.sh` 的**语义** | 只导出当前 shell、不静默改默认 | env README |
| `import load.py` 不改 `os.environ` | 现状契约 | AGENTS.md |
| `prove_rmw.py`、13 个 `check_*.py` 的退出码语义 | 无 ROS 也退出 0（或契约性红） | AGENTS.md |
| vendor / dimos_bridge 文件行为 | 整文件拷贝、行为不变 | R0 |

### 4.2 允许变更（且仅限本仓自有面）

| 面 | 允许变什么 | 不允许变什么 |
|----|-----------|--------------|
| `config/fastdds.xml` | 注释外移到 tuning log；**契约数值冻结**（R6 的断言锁死） | 动任何旋钮值 |
| `config/env/load.py` / `chain_*.sh` | 增加「自校验 assert」、从 YAML 读常量 | 改导出的实际值；改 import 副作用 |
| `config/topics.yaml` | 作为唯一真源被机器读取 | 与 `dds_topics.py` 漂移 |
| `scripts/` | 新增巡检/断言脚本 | 改既有 check 脚本的退出语义 |
| `docs/` | 新增架构/计划文档 | 改 SCOREBOARD 已记账数字 |
| `docker/ros/` | 仅 R3 式拆分（安装语义不变） | 镜像里写死 RMW/域（README 已禁止） |

---

## 5. 独立迁移任务（不混在 R6–R12 里）

> 这些都是**架构级**或**依赖级**变动，风险面与「文档/脚本重构」完全不同，单独立项、单独评审、单独 Go/No-Go。

### 5.1 vendor 从「整树拷贝」迁到 git submodule / subtree —— 独立任务

- **动机**：§1.1。
- **为什么不在本阶段做**：会动构建来源；Humble Docker 镜像配方、CI、`prove_rmw.py` 都假设「vendor 是普通目录」；硬约束要求不改 vendor 行为。
- **前置**：R9 升级 playbook 先跑通至少一次「文档化的人肉升级」，证明流程本身能走。
- **判据**：当且仅当出现「上游 patch 需要频繁跟」时再启动；启动前出一份 ADR（submodule vs subtree vs 继续整树）。

### 5.2 自研中间件包成 RMW（会议定的最优路径）—— 独立任务

- **会议结论**：「把自研中间件封装为 ROS 2 的 RMW 适配层组件，上层应用无感，环境变量切换底层通信」。
- **本仓现状**：明确「没有自定义 RMW」（AGENTS.md、README 多处重复）；`ZenohTransport` 是空 stub。
- **为什么不在本计划落地**：这是**第三栈**，而 §1.2 双链漂移还没收敛；先把两栈契约对齐（R7），再谈第三栈。
- **前置**：R7 契约单一事实源 + R11 长尾混合负载基线（否则新 RMW 没有可比基准）。
- **边界**：即便立项，也只做**新增** RMW 名，不改 `rmw_fastrtps_cpp` / `rmw_cyclonedds_cpp` 现有行为；跨机 UDP 仍 blocked。

### 5.3 发行版升级（Humble → Jazzy）/ RMW 栈版本升级 —— 独立任务

- **现状**：vendor `rmw*` 取的是 upstream `rolling` 快照，却跑在 Humble 运行时上（`feishu-runtime-provenance.md` 已警告「Humble `/opt/ros/humble` ≠ rolling `vendor/`」）；这本身就是一个 underlay/overlay 漂移源。
- **为什么独立**：rebase 发行版会动 QoS 默认、XML schema（Humble Fast-DDS 2.6 要求 History 写在 `<topic><historyQos>`，iter1 就踩过）、RMW ABI。
- **前置**：R9 playbook + R11 混合负载基线先存在，否则升级前后无法证明行为没变。

### 5.4 跨机 UDP / 多机协同 —— 独立任务，当前 blocked

- **现状**：单机 + yixin Docker DOWN，`STATUS: blocked`。
- **为什么独立**：需要真实多机环境；DDS 发现风暴在多机下才是 doc2 说的 O(N²) 重灾区。
- **前置**：先有一台可复现的第二机；在此之前**不**写任何多机配置建议。

### 5.5 硬实时用户态网络（DPDK/XDP 类）—— 独立任务，当前不吸收

- 见工作 B（`cn-jp-ros2-absorb-extended.md`）：MTU 分片限制 + 独占 CPU 核，与端侧 ARM 机器人硬约束冲突。仅文档级跟踪。

---

## 6. 前置文档 / 规范 / 一致性检查（范围广，先写规范再动手）

在 R6–R12 真正落地前，先补这几份「规矩」，否则每个 PR 都会重新争论一次：

1. **《契约变更流程》ADR**（新增 `docs/architecture/adr-contract-change.md`）：
   - 谁能动 R0 冻结表？走什么 PR 模板？
   - 「改一个域 ID 必须同时改哪几处」清单（就是 R7 的目标状态）。
2. **《bench 诚实性规范》**（扩 `docs/usage/benchmark-dds.md`）：
   - 缺环境一律 `STATUS: blocked`；
   - 混合负载 profile 定义；
   - 长尾指标 = p99/max，不看 p50；
   - 「100 小时不崩」的可测定义。
3. **《vendor 改动零容忍规则》**（并入 R9 playbook）：
   - vendor 树下禁止非上游 diff；必须改时走 5.1/5.2 独立任务。
4. **CI 一致性检查矩阵**（扩 `ci-cd-gates.md`）：
   - 把 R6/R7/R8/R10 新增的 check 脚本登记进去，明确哪个 job 跑哪个、`allow-hold-bypass` 何时允许。
5. **《dimos_bridge 同步责任》说明**（并入 SOURCE.md 或新页）：
   - 谁负责定期巡检上游；stub 清单怎么维护；已删死代码不再引入。

---

## 7. 执行计划（分阶段路线图）

> 优先级：P0 = 无风险、立即止血；P1 = 收敛漂移、为后续打基线；P2 = 架构演进的前置；P3 = 独立迁移任务，待 Go/No-Go。

### 阶段一（P0，1 周内）：把「账」从代码里搬出来

- R6 XML 迭代史外移 + XML 值断言。
- R10 「试过且否决」速查表。
- 前置文档 6.1 / 6.4。

**出口标准**：`fastdds.xml` 只剩契约；任何旋钮改动被 CI 断言拦住；历史旋钮全部可在文档反查。

### 阶段二（P1，2–3 周）：收敛双链漂移 + 守门

- R7 契约单一事实源。
- R8 dimos 漂移巡检 + 死代码负向断言。
- R9 vendor 升级 playbook（不改树）。
- 前置文档 6.2 / 6.3 / 6.5。

**依赖**：R7 依赖 R6（XML 已经是干净契约后再读它）。
**出口标准**：域/RMW 名漂移 → CI 红；上游 dimos 漂移 → 报告可见；vendor 升级有书面流程。

### 阶段三（P1.5，3–4 周）：建立可演进的测量基线

- R11 混合负载 + 长尾 bench 骨架。
- R12 RMW/WaitSet 本仓对照建议（纯文档）。

**依赖**：R11 依赖 R10（「试过什么」已登记，新 profile 才知道和谁比）。
**出口标准**：激光雷达大包 × IMU 高频混合场景有定义；跑不了就诚实 blocked；长尾指标进产物。

### 阶段四（P2，独立评审，不定排期）：架构演进前置

- 5.1 vendor submodule 化 ADR。
- 5.2 自研 RMW 立项评审（会议定的最优路径）。
- 5.3 Humble→Jazzy rebase 预研。

**出口标准**：每项都有独立 Go/No-Go 结论；在结论出来前，本仓维持「双链 + 无自定义 RMW」现状。

### 阶段五（P3，外部条件触发）

- 5.4 跨机 UDP：第二台可用机器到位后启动。
- 5.5 DPDK/XDP：仅当出现「独占 CPU 核 + 固定 MTU 帧」的硬实时专线需求时预研。

---

## 8. 一页结论

- **本仓当前最大的风险不是「调参没调好」，而是「账散在五处、升级靠人肉、历史旋钮埋在 XML 注释里」**——这些不直接改性能，但直接决定下一个人能不能在一周内安全改东西。
- 阶段一+二（R6–R10）全是**行为不变**的文档/脚本工作，符合硬约束，可立即启动。
- 真正影响延迟/CPU/抖动的动作（自研 RMW、vendor 升级、跨机）**全部在第 5 节单独立项**，不在本计划里顺手做——这正是 7/10 会议「先把评价标准和基线立住」的要求。
