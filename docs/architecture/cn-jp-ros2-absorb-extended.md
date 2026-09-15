# 中日等地区优化 ROS 2 方案 · 吸收扩展分析

Status: **文档级对照 — 不落地旋钮、不集成。**
基线：在基线仓既有 `docs/architecture/cn-jp-ros2-absorb.md`（路径 `/tmp/tutti_task/ros2_hzj/docs/architecture/cn-jp-ros2-absorb.md`，下称「基线吸收页」）之上**扩展**，不替代它。本新仓未复制该文件，引用时以基线仓路径为准。
依据：`/tmp/tutti_task/doc2.md`（《机器人行业 DDS 优化开源研究》）+ 本仓实际文件。
硬约束（继承 R0 冻结 / AGENTS.md）：**不改 `vendor/` 行为、不改 `dimos_bridge/` 运行时、不集成 Agnocast / zenoh / eCAL / CyberRT、公共 API 不变、跨机 UDP 仍 blocked。** 本文所有「可吸收点」仅限**低风险、行为不变的文档级建议**或**配置调优**，不写进 `config/fastdds.xml`，不改 SCOREBOARD。

---

## 0. 本仓双链基线（先对齐，再谈吸收）

| 链 | 角色 | 契约 | 本仓落点 |
|----|------|------|----------|
| **A — nav FastDDS** | 导航 / Foxglove / ROS 2 RMW | `rmw_fastrtps_cpp`，`ROS_DOMAIN_ID=42`，`config/fastdds.xml`（iter7 种子） | `vendor/rmw*`、`vendor/Fast-DDS` |
| **B — DimOS Cyclone** | DimOS 原生 DDS / Unitree | Cyclone **域 0**；Unitree `ChannelFactoryInitialize(0)`；ROS 2 侧 `rmw_cyclonedds_cpp` | `vendor/rmw_cyclonedds`、`vendor/CycloneDDS`（钉 tag `11.0.1`） |

评价标准（7/10 会议定）：**低延迟且抖动小 / CPU 低 / 丢包少 / 100 小时不崩 / ROS 生态兼容**，且必须在激光雷达大包、IMU 高频等真实业务场景下测。
本仓现状：跨机 UDP `STATUS: blocked`（单机 / yixin Docker DOWN）；同机同拓扑 ping-pong bench 已有 p50/p95/p99；**尚无**混合负载长尾基线。

> 阅读约定：每个方案按四段写——**核心优化机制 / 适用场景 / 对本仓双链的可吸收点 / 不吸收的硬约束**。最后第 9 节给「可吸收优化矩阵」。

---

## 1. Tier IV Agnocast（日本，Autoware）— 真零拷贝，LD_PRELOAD 堆劫持

### 核心优化机制
- 内核模块 `agnocast-kmod` + `LD_PRELOAD` 堆钩子 `agnocast-heaphook`，把发布者进程的 `malloc/free` 重定向到一段受管虚拟地址；订阅者把该段以**只读、相同偏移**映射进自己进程。
- 因为双方虚拟地址偏移一致，**含 `std::vector` 的未定长消息**（PointCloud2 / Image）内部指针在对端依然有效 → 无需序列化/反序列化，真零拷贝。
- `ipc_shared_ptr` 跨进程智能指针：单写者 + 所有者驱动回收，避免全局引用计数同步开销。
- **不是新 RMW**：与 ROS 2 栈共存；跨主机、rviz、rosbag 仍走原 RMW；与非 Agnocast 节点靠 Bridge。Autoware 用构建期 `ENABLE_AGNOCAST` 开关。

### 适用场景
- 单机、跨进程、**高频大数据量**节点间（多路激光雷达 / 4K 视觉流水线）。
- 要求**进程隔离**（不想要 ComponentContainer 同进程）又要真零拷贝。

### 对本仓双链的可吸收点（仅文档级）
- **不改代码、不装 kmod**，只把 Agnocast 的三条结论写进架构对照：
  1. 「未定长消息真零拷」在本仓只能靠它这类堆劫持方案——本仓链 A 的 PointCloud2/Image 走的是 iter5 SHM 分片路径（1MiB sample > 280000 仍分片），**预期内不零拷**，文档应诚实标注；
  2. Agnocast 跨机仍回退 DDS → 与本仓「同机 SHM ≠ 跨机 UDP 解锁」的现有结论一致，可互相印证；
  3. 会议定的「自研中间件包成 RMW」与 Agnocast「不是 RMW、是共存层」是两条不同路线，文档应记录二者差异，避免混淆。
- 基线吸收页 §2.1 已记 **Hold**（不 vendor、不装 kmod、不加第三链）。本扩展维持该结论。

### 不吸收的原因（硬约束）
- 需要装/加载内核模块 + `LD_PRELOAD` 改堆分配——直接违反「不改 vendor/运行时行为」「不动 dimos_bridge」。
- 侵入智能指针命名空间 + launch 配置，破坏「上层应用无感」之前先要改一堆源码。
- 跨机/rviz/rosbag 仍回退 DDS，本仓跨机又 blocked，收益无法在本仓环境验证。

---

## 2. 宇树科技 unitree_sdk2 + 纯 Socket 方案（中国）

### 核心优化机制
- 早期 `unitree_dds_wrapper`（Python/C++ 高度封装 CycloneDDS）→ 官方废弃并重构精简为 **`unitree_sdk2` / `unitree_sdk2_python`**，内部仍集成 CycloneDDS **0.10.2**，但暴露更细粒度 QoS 配置接口。
- 在最关键的高频控制回路（上肢灵巧手遥操作、RL 平衡控制 500–1000Hz），第三方项目（如 Cerebro-Control）**干脆剥离 DDS**，「主要依赖纯 Sockets」做点对点指令发送，规避 WiFi 丢包→可靠性重传→动作僵死。

### 适用场景
- 双足/四足**硬实时高频控制**（扭矩/关节指令，小包、超高频率、抖动零容忍）。
- WiFi/弱网遥操作，DDS 重传机制反而成为负担的场景。

### 对本仓双链的可吸收点（仅文档级 + 一条既有事实）
- **本仓已有硬结论**：`docs/architecture/unitree-sdk2-dds-swap.md` 记录 Unitree 自带 Cyclone **0.10.2 ≠ 本仓 vendor 11.0.1 的 drop-in**（drop-in FAIL / wire UNPROVEN）；合法换库走 `unitree_sdk2_hzj` + opt-in `UNITREE_DDS_PROVIDER=external`，**不是** in-place overwrite。本文不重复、不改该结论。
- 文档级建议：
  1. 高频控制小包（对照本仓 IMU 64B/200Hz）的抖动门，与宇树「控制回路剥离 DDS」的动机同源——本仓 R11 混合负载基线应把「控制小包与感知大包并发」单列；
  2. 「纯 Socket 兜底」**仅作反面教材记录**：本仓不引入，但应在文档里说明「为什么我们不走这条路」——因为会议要求**ROS 生态兼容**，纯 Socket 会失去 rviz/rosbag/tooling。

### 不吸收的原因（硬约束）
- 换 Unitree Cyclone 版本会动链 B 运行时（`dimos_bridge/.../dds_sdk.py` 域 0 / `ChannelFactoryInitialize(0)`），违反「不改 dimos_bridge」。
- 纯 Socket 控制点对点 = 放弃 ROS 生态，与会议「尽量兼容 ROS 生态」的评价标准直接冲突。

---

## 3. 大陆集团 eCAL（德国，对中日路线的对照参照）

### 核心优化机制
- **完全抛弃 OMG DDS 标准**：自研 eCAL，底层不是 RTPS 实现；高级 API 受 ROS 启发，并提供 `rmw_ecal` 作为 ROS 2 替代 RMW 插件。
- IPC 原生用**内存映射文件**：发布者写共享内存文件 → 信号通知订阅者 → 订阅者直接读。比 Iceoryx/Agnocast 多一次拷贝，但管理逻辑极薄。
- 序列化**弃 IDL**，原生支持 Protobuf / FlatBuffers / **Cap'n Proto**（内存中近乎零解析读取）。
- 发现**弃 SPDP/SEDP**，改用轻量本地注册表 / 集中目录，根治多节点发现风暴。

### 适用场景
- 车内多 HPC（高性能计算平台）原型车队，**只在内部网络**，互操作性不重要、吞吐最重要。
- 已有 Protobuf/Cap'n Proto 数据树、愿放弃 DDS 互操作的团队。

### 对本仓双链的可吸收点（仅文档级）
- eCAL 与 Agnocast 方向相反（一个抛弃标准、一个共存于标准），文档应把二者**并列为「两端极端」**，帮助选型讨论：
  - 本仓评价标准含「ROS 生态兼容」→ eCAL 抛弃 IDL/RTPS 的代价，本仓不付；
  - 但其**「轻量注册表替代 SPDP」**与 doc2 发现风暴结论一致，可作为 R10/R12 文档里「发现问题的另一种解法」引用，不实现。
- `rmw_ecal` 是「把别的中间件包成 RMW」的**先例**，恰好佐证会议定的「自研中间件包成 RMW」路线可行——但本仓不集成。

### 不吸收的原因（硬约束）
- 引入 eCAL = 第三栈 + 新序列化体系，违反「无自定义 RMW / 不加第三链」现状与硬约束。
- 内存映射文件虽好，但本仓跨机 blocked，且 eCAL 车规级运维体系（注册表/监控）超出本仓一个月范围。

---

## 4. 百度 CyberRT（中国，Apollo）

### 核心优化机制
- 弃 DDS 基于 TCP/UDP 的封包拆包，自研 CyberRT 底层：**预分配共享内存** + 内置**无锁队列（lock-free queue）**，直接绕过网络栈做进程间通信。
- 典型「组件 + 数据流图」编程模型，节点间走共享内存队列而非 DDS topic 语义。

### 适用场景
- Apollo 式**单车内大规模自研模块**流水线，数据量巨大、模块都在本机。

### 对本仓双链的可吸收点（仅文档级）
- 「预分配 + 无锁队列」是 doc2 里「CPU 占用高」的对症思路之一；文档可记录：
  1. 本仓 iter4 已经无意中踩到同类问题——`dynamic=true` 时 Fast-DDS 在热路径分配 RTPSMessageGroup，mid-size 同机 Reliable 有 +23–24% 税，于是钉死 `preallocated_number=32 / dynamic=false`（`fastdds.xml` iter4 注释）。**这条经验与 CyberRT「预分配」理念同向，可作为本仓「预分配优于热路径分配」的内部佐证。**
  2. 但 CyberRT 整体换栈 = 又一次抛弃 ROS 生态，同 eCAL，不吸收。

### 不吸收的原因（硬约束）
- CyberRT 不是 DDS/RMW 体系，接入即重写应用层；违反「上层应用无感」「ROS 生态兼容」。
- 本仓无 Apollo 式多模块自研流水线的前提，收益无法落地。

---

## 5. Eclipse Zenoh（跨网段协同，rmw_zenoh Tier 1）

### 核心优化机制
- **不是 DDS 另一实现**，而是面向边缘/物联网/广域网的路由协议；用**单播/受控多播 + 路由节点**替代 DDS 全对全 SPDP，把发现复杂度从 O(N²) 压下去。
- 网络穿透强：跨网段/VPN/WiFi 下远比依赖 UDP 组播的 DDS 稳；可连微控制器（ESP32/micro-ROS）到云。
- ROS 2 官方已将 `rmw_zenoh` 升为 **Tier 1**（Jazzy/Rolling 推广）。
- **但**：社区 2025–2026 benchmark 显示，单机 localhost 微观场景下，打磨十余年的 `rmw_cyclonedds` 在订阅端 CPU、高频图像流抖动上仍**优于** `rmw_zenoh`（后者 SHM 在补齐）。

### 适用场景
- 多机器人跨网段协同（AMR 蜂群、仓库编队）、弱网/广域遥操作、云边端一体。
- **不是**单机 IPC 极致吞吐场景。

### 对本仓双链的可吸收点（仅文档级）
- 基线吸收页 §3.3 已记 openEuler 24.0.3 引入 Jazzy + `rmw_zenoh` 预览，本仓结论 **Hold**（不引入 `rmw_zenoh`、不 rebase Jazzy）。本扩展补充 doc2 的两面性：
  1. **跨机协同**这条 Zenoh 的主场，本仓恰恰 blocked（单机）——所以 Zenoh 在本仓**无当前可验证收益**；
  2. 文档应明确：Zenoh 是**阶段五（跨机/多机）触发后**的候选，不是阶段一/二的动作。
- 本仓 `ZenohTransport` 是空 stub（README 已点名「不是可用路径」），不启用。

### 不吸收的原因（硬约束）
- 新增 RMW = 第三栈，违反「无自定义 RMW」现状；且单机 benchmark 上 cyclonedds 仍更优，本仓当前痛点（单机抖动）它不解。
- 引入它需要 Jazzy，而发行版 rebase 是独立迁移任务（见重构计划 §5.3）。

---

## 6. ros2_shm_msgs（中国，ZhenshengLee）— 强制定长消息激活零拷贝

### 核心优化机制
- 不改 CycloneDDS 核心，只在 **IDL/消息定义层**动手：放弃 `sensor_msgs/Image`/PointCloud2 的动态 `uint8[]`，改成编译期定长的大消息（`Image1m/2m/4m`、`PointCloud8k/1m` 等 POD 定长结构）。
- 定长 POD 一旦满足，CycloneDDS+Iceoryx 的 **Loan API 真零拷**被激活：发送端在共享内存池上直接构造，接收端拿指针即读。
- 实测：1MB 图像跨进程 IPC 从 loopback ~1.4ms 降到 ~0.3ms（约 80% 改善）。

### 适用场景
- 资源受限平台（Jetson 类）高频机器视觉流；消息尺寸可预估、愿为定长容器付内存碎片代价的场景。
- 代价：为留余量分配比实际大得多的容器，内存浪费；动态分辨率传感器不灵活。

### 对本仓双链的可吸收点（仅文档级，**不改消息定义**）
- 这是七方案里**与本仓现状最贴近**、也最值得写清楚边界的一条：
  1. 本仓链 A 的 `color_image`/`lidar`/`global_map` 正是 `sensor_msgs/Image`/`PointCloud2` 动态类型 → 这正是 iter5 SHM「1MiB 仍分片、没真零拷」的**根因**；ros2_shm_msgs 给出了「如果想在不改 RMW 的前提下激活零拷，唯一杠杆是改消息定义」的清晰因果。
  2. **但本仓不改消息定义**：R0 冻结表把 Go2 四流类型冻成 `PointCloud2`/`Image`，改消息类型 = 改公共 API，违反硬约束。
  3. 文档级建议：把 ros2_shm_msgs 列为「**若未来 Go2 驱动可控、且愿牺牲标准 PointCloud2 生态兼容**」的候选，记录其取舍，不在本阶段动。

### 不吸收的原因（硬约束）
- 改 `.msg` 定长 = 破坏标准消息类型，失去 ROS 生态兼容（会议评价标准之一），且冻结表不允许。
- 定长大容器的内存碎片在端侧 ARM 上是已知代价。

---

## 7. caps-tum/cyclonedds-dpdk-xdp（德国 TUM，用户态网络重构）

### 核心优化机制
- 把 CycloneDDS 第二层搬到**用户态网络**：
  - **DPDK**：接管网卡、CPU 核轮询、绕过内核 TCP/IP 栈、DMA 直接映射到用户态内存池；
  - **XDP/eBPF**：在网卡驱动进内核栈之前跑极轻量过滤，高优先级 DDS 流量直接路由到关键内存。
- 中间件层再加固定优先级非抢占调度器，防发现流量阻塞关键数据。
- 论文：混合关键负载下 >250k samples/s，压缩 WCET 与抖动。

### 适用场景
- **硬实时专线**：可独占网卡 + 独占 CPU 核、报文能塞进单个帧的场景。

### 对本仓双链的可吸收点（仅文档级）
- 仅作「极致路线」记录，证明内核网络栈开销确有理论解（doc2 §2 第一条瓶颈）。
- 本仓不吸收，理由见下；但它印证了 doc2「系统调用/上下文切换/多拷贝是长尾抖动来源」的诊断，可在 R12/R11 文档里作为「为什么长尾要单独建基线」的旁证。

### 不吸收的原因（硬约束）
- **MTU 硬限制**：序列化后样本必须放进单个 DPDK/XDP 帧（≈1500B），超限直接丢——**本仓 1–8MB 激光雷达点云根本传不了**。
- DPDK 轮询要**独占至少一个 CPU 核 100% 满载**，端侧 ARM 机器人算力/功耗不允许。
- 与「CPU 低」「不崩」两条评价标准直接冲突。

---

## 8. 横向对照小结

| 方案 | 根问题打的是哪条瓶颈 | 对本仓双链 |
|------|----------------------|------------|
| Agnocast | 序列化/动态类型零拷失效 | 文档级印证「动态类型不能真零拷」；Hold |
| 宇树 sdk2+Socket | 高频小包抖动 / WiFi 重传风暴 | 已有 drop-in FAIL 结论；纯 Socket 作反面教材 |
| eCAL | DDS 协议冗余 + 发现风暴 | 「包成 RMW」先例；不集成 |
| CyberRT | 封包拆包 CPU 开销 | 「预分配」理念与 iter4 同向；不换栈 |
| Zenoh | 跨网段发现风暴 + 网络穿透 | 跨机 blocked，无当前收益；阶段五候选 |
| ros2_shm_msgs | 动态类型零拷失效（改 IDL 曲线救国） | 根因解释；改消息=改 API，不吸收 |
| DPDK/XDP | 内核网络栈系统调用开销 | MTU/独占 CPU 硬冲突；仅理论参考 |

---

## 9. 可吸收优化矩阵（结论表）

> 三档：
> - **【配置可调优】** = 不改行为、可在隔离实验/文档内讨论（但本仓仍不写进现网 XML，除非另起 Go/No-Go）。
> - **【文档级建议】** = 只进架构文档，不改代码、不改配置。
> - **【硬约束暂不吸收】** = 违反 R0 冻结 / 硬约束 / 当前环境，仅跟踪。

| # | 方案 / 旋钮 | 档位 | 落到本仓哪里 | 为什么 |
|---|-------------|------|--------------|--------|
| 1 | Orbbec Fast DDS 大缓冲（1048576 socket buffer） | 【配置可调优】 | 仅 example only，不写 `fastdds.xml`（基线吸收页已定） | 本仓 iter2 已自选 2MiB；数字不抄进现网 |
| 2 | Autoware Cyclone recv window 10MB | 【配置可调优】 | 链 B 默认仍不设 `CYCLONEDDS_URI` | 只引 URL，example only |
| 3 | Loaned Messages + Fast DDS Data Sharing | 【配置可调优】 | 文档对照：same-host 零拷，**非**跨机解锁 | Humble 需 POD + XML 开启；本仓动态消息不满足 |
| 4 | CyberRT 式「预分配优于热路径分配」 | 【文档级建议】 | 印证 iter4 `send_buffers=32/dynamic=false` 的正确性 | 理念一致，不需新动作 |
| 5 | eCAL / Zenoh「轻量发现替代 SPDP」 | 【文档级建议】 | R10/R12 文档引用为发现风暴的另一解法 | 本仓发现调参（iter8/9）已证明单旋钮调 lease 伤抖动 |
| 6 | Agnocast 真零拷（未定长消息） | 【硬约束暂不吸收】 | 仅文档对照 | 需 kmod+LD_PRELOAD，违反运行时不改 |
| 7 | 宇树纯 Socket 控制回路 | 【硬约束暂不吸收】 | 反面教材 | 放弃 ROS 生态，与评价标准冲突 |
| 8 | eCAL 整体栈 / rmw_ecal | 【硬约束暂不吸收】 | 仅「包成 RMW」先例引用 | 第三栈 + 弃 DDS 标准 |
| 9 | CyberRT 整体换栈 | 【硬约束暂不吸收】 | 不引用为落地项 | 重写应用层 |
| 10 | rmw_zenoh / Jazzy rebase | 【硬约束暂不吸收】 | 阶段五（跨机）候选 | 单机 cyclonedds 仍更优；rebase 是独立迁移任务 |
| 11 | ros2_shm_msgs 定长消息 | 【硬约束暂不吸收】 | 仅根因解释 | 改 `.msg` = 改公共 API，破 PointCloud2 生态 |
| 12 | cyclonedds-dpdk-xdp | 【硬约束暂不吸收】 | 仅理论旁证 | MTU 装不下点云 + 独占 CPU 核 |

**一句话结论**：七套外部方案里，**没有一套**在本阶段可以低风险落地——它们要么要 kmod/新栈/新 RMW/改消息类型（硬约束挡死），要么主场在跨机/多机（本仓 blocked）。本阶段真正「可吸收」的只有第 1–5 行：**把已有的调优旋钮与理念，诚实写进文档与对照表**，不碰现网 XML、不加链、不改 dimos_bridge。真正的吸收窗口在重构计划的阶段四/五（自研 RMW 立项、跨机解锁）打开之后。

---

## 10. 引用（均来自 doc2.md 与本仓实际文件）

本仓文件：
- 双链契约：`docs/architecture/ros2-dds-r0-interface-freeze.md`（基线仓内）
- 链 A XML 种子：`config/fastdds.xml`（iter1–iter9 旋钮史）
- Unitree swap 结论：`docs/architecture/unitree-sdk2-dds-swap.md`（0.10.2 vs 11.0.1 drop-in FAIL）
- 基线吸收页：`docs/architecture/cn-jp-ros2-absorb.md`（Agnocast Hold / Orbbec / Cyclone window / Loaned / openEuler）
- vendor 钉版：`vendor/VERSIONS.md`

doc2.md 对应章节：
- §2 标准 CycloneDDS 瓶颈（内核网络栈 / 序列化零拷失效 / RMW 等待接口不匹配 / 发现风暴）
- §3 DPDK-XDP（caps-tum）、ros2_shm_msgs
- §4 Agnocast（Tier IV）、unitree_sdk2 + 纯 Socket、eCAL（Continental）、CyberRT（Baidu）
- §5 Eclipse Zenoh（Tier 1 / 跨网段 / 单机 cyclonedds 仍优）
