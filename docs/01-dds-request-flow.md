# 《1》DDS 请求流分析

> 仓库根：`/tmp/tutti_task/ros2_hzj`（下文所有相对路径均相对于该根）。
>
> 本文回答一个问题：**一条请求（publish）从用户代码出发，在代码库里如何逐层流进 DDS、又是如何异步地流回用户 callback 的。** 不修改任何源码，只做路径分析与陷阱标注。
>
> 两条独立链路（双链契约，见 `docs/architecture/ros2-dds-r0-interface-freeze.md`）：
>
> | 链 | RMW / DDS | 域 | 配置 |
> |----|-----------|----|------|
> | **链 A（导航 Fast-DDS）** | `rmw_fastrtps_cpp` → Fast-DDS | **42** | `config/env/chain_a.sh` + `config/fastdds.xml` |
> | **链 B（DimOS Cyclone）** | `rmw_cyclonedds_cpp` / 原生 Cyclone Python | **0** | `config/env/chain_b.sh`；默认不设 `CYCLONEDDS_URI` |
>
> **版本事实（先读，避免整套误判）：**
> - `vendor/` 是整树文件拷贝（见 `vendor/VERSIONS.md`、`vendor/MANIFEST.md`）：`rmw` 7.11.2、`rmw_fastrtps` rolling、Fast-DDS `master` 快照（近旁 tag v3.6.2）、`rmw_cyclonedds` 4.2.1、CycloneDDS tag **11.0.1**。
> - 运行时是 **Humble**（`docker/ros/`，`ROS_DISTRO=humble`；Fast-DDS 2.6.x）。**本仓没有 vendor `rcl` / `rclcpp` / `rclpy`**——Executor、`rcl_publish`、`rcl_wait` 在 Humble 发行版 `/opt/ros/humble`，不在 `vendor/`。
> - 下文凡标注「（发行版，不在 vendor）」的文件，路径只作定位说明，本仓内不存在；凡标注 `vendor/...` 的文件均已核对真实存在。
> - 调用链函数名与上游行号引用飞书《ROS2官方源码深挖》（doc3，2026-07-14 Rolling 快照）；本仓 `vendor/` 同名文件为对照阅读快照，**行号会漂移，符号以 `scripts/check_source_map.py` 允许清单为准**。

---

## 1. 请求流经 DDS 的完整路径

ROS 2 **没有**一个包办所有消息的「中心转发进程」。每条消息实际走三条互相独立又在 History 汇合的链：

```
发布链（同步调用栈，publish() 内完成）
  app publish → rcl → rmw_implementation 动态分派 → RMW → DDS DataWriter → WriterHistory → RTPS → transport

接收链（DDS 后台线程，与发布链无关）
  NIC/SHM → Fast-DDS 接收线程 → RTPS Reader → ReaderHistory → StatusCondition/Listener

等待/取数链（Executor 线程，异步触发）
  Executor → WaitSet → rcl_wait → rmw_wait → DDS WaitSet 唤醒 → rmw_take → DataReader.take → 反序列化 → 用户 callback
```

### 1.1 发布链：从 `rclcpp::Publisher::publish` 到 transport

最短主链（doc3 §2）：

```cpp
rclcpp::Publisher<T>::publish(msg)
  -> rcl_publish(...)                      // 发行版 rcl，不在 vendor
  -> rmw_implementation::rmw_publish(...)  // 按 RMW_IMPLEMENTATION 动态分派
  -> rmw_fastrtps_cpp::rmw_publish(...)    // wrapper
  -> __rmw_publish(...)                   // ordinary fallback
  -> DataWriter::write_w_timestamp(...)
  -> DataWriterImpl::create_new_change_with_params(...)
  -> WriterHistory / RTPS / transport
```

| 跳 | 层 | 函数与职责 | 本仓真实路径 |
|----|----|-----------|--------------|
| ① | rclcpp（发行版，不在 vendor） | `Publisher::do_inter_process_publish`：类型化 C++ 消息进入 C ABI 的边界 | 无（Humble `/opt/ros/humble`） |
| ② | rcl（发行版，不在 vendor） | `rcl_publish`：句柄/参数检查后调 `rmw_publish`（doc3 publisher.c L268-L289） | 无（Humble `librcl.so`） |
| ③ | rmw 接口声明 | `rmw_publish` / `rmw_get_implementation_identifier` 声明所在 | `vendor/rmw/rmw/include/rmw/rmw.h` |
| ④ | rmw_implementation 装载器 | `load_library()` 读 `RMW_IMPLEMENTATION`→`DEFAULT_RMW_IMPLEMENTATION`，按符号名转发 `rmw_publish`（doc3 functions.cpp L77-L143 / L320-L323） | `vendor/rmw_implementation/rmw_implementation/src/functions.cpp` |
| ⑤ | rmw_fastrtps 导出 wrapper | 链 A `rmw_publish`；Rolling 上先检查 Buffer-aware，不满足回退 shared `__rmw_publish`（doc3 §5.2） | `vendor/rmw_fastrtps/rmw_fastrtps_cpp/src/rmw_publish.cpp` |
| ⑥ | shared RMW | `__rmw_publish` 包装 SerializedData，调 `data_writer_->write_w_timestamp`（doc3 rmw_publish.cpp L34-L70） | `vendor/rmw_fastrtps/rmw_fastrtps_shared_cpp/src/rmw_publish.cpp` |
| ⑦ | 类型支持 | `serializeROSmessage`：写 encapsulation 后经回调表调 `cdr_serialize`（doc3 TypeSupport_impl.cpp L122-L146） | `vendor/rmw_fastrtps/rmw_fastrtps_shared_cpp/src/TypeSupport_impl.cpp`（L140 调用点） |
| ⑧ | Fast-DDS API | `DataWriter::write_w_timestamp` 转入 `DataWriterImpl`（doc3 DataWriter.cpp L117-L123） | `vendor/Fast-DDS/src/cpp/fastdds/publisher/DataWriter.cpp` |
| ⑨ | Fast-DDS 内核 | `DataWriterImpl::write_w_timestamp` → `create_new_change_with_params` → `perform_create_new_change`：分配 payload、序列化、建 CacheChange（doc3 L750-L772 / L1044-L1135） | `vendor/Fast-DDS/src/cpp/fastdds/publisher/DataWriterImpl.cpp` |
| ⑩ | DDS 层 Writer History | `DataWriterHistory::add_pub_change` 把 CacheChange 纳入历史与资源限制（doc3 L273-L298） | `vendor/Fast-DDS/src/cpp/fastdds/publisher/DataWriterHistory.cpp` |
| ⑪ | RTPS Writer History | `WriterHistory::add_change_` 通知 RTPS writer 有新 unsent change（doc3 L201-L228） | `vendor/Fast-DDS/src/cpp/rtps/history/WriterHistory.cpp` |
| ⑫ | RTPS Writer 策略 | 可靠走 `StatefulWriter`（reader proxy、ACK/NACK、重传、flow controller）；best-effort 走 `StatelessWriter` 另一分支（doc3 L333-L409 / L276-L314） | `vendor/Fast-DDS/src/cpp/rtps/writer/StatefulWriter.cpp`、`.../rtps/writer/StatelessWriter.cpp` |
| ⑬ | transport | UDP / SHM / DataSharing 由 Fast-DDS 配置、匹配端点、QoS、同机/跨机关系决定；**进入 WriterHistory 不等于已上网**（doc3 §2.1 callout） | `vendor/Fast-DDS/src/cpp/rtps/transport/`（builtin UDP；SHM/DataSharing 随 profile） |

**链 B 对照（Cyclone）：** 同一 ROS 2 语义落到完全不同的函数（doc3 §4.4，证明 RMW 是真实抽象边界）：

| 跳 | 链 B 落点 | 本仓真实路径 |
|----|-----------|--------------|
| RMW publish | `rmw_publish` 直接调 `dds_write_ts`（doc3 rmw_node.cpp L2012-L2034） | `vendor/rmw_cyclonedds/rmw_cyclonedds_cpp/src/rmw_node.cpp` |
| DDS write | `dds_write` / `dds_write_ts` / `dds_write_impl` | `vendor/CycloneDDS/src/core/ddsc/src/dds_write.c` |
| Writer History | `ddsi_write_sample_gc` → `ddsi_whc_insert` | `vendor/CycloneDDS/src/core/ddsi/src/ddsi_whc.c` |

> ⚠️ **关键认知：** `publish()` 返回 `RMW_RET_OK` 只说明**本端**已接受/入队（doc3 §10.1）。之后走哪条 transport、何时发、对端收没收到，都不在这次调用栈里。

### 1.2 接收链：从 NIC/SHM 到用户 callback

doc3 §3 主链（注意它**不是**发布链的倒放）：

```cpp
Executor::spin()
  -> wait_for_work()                      // 发行版，不在 vendor
  -> get_next_executable()                // 发行版，不在 vendor
  -> execute_subscription()               // 发行版，不在 vendor
  -> SubscriptionBase::take_type_erased() // 发行版，不在 vendor
  -> rcl_take()                           // 发行版，不在 vendor
  -> rmw_take_with_info()
  -> DataReader::take()
  -> deserializeROSmessage()
  -> Subscription::handle_message(callback)
```

接收侧其实分三段，中间隔着 DDS 后台线程：

**(a) 网络/本机 ingress —— 跑在 Fast-DDS 接收线程，早于任何 ROS callback（doc3 §10.2）：**

| 跳 | 函数与职责 | 本仓真实路径 |
|----|-----------|--------------|
| ① | NIC/SHM/DataSharing 收包 → RTPS 层 | `vendor/Fast-DDS/src/cpp/rtps/reader/StatefulReader.cpp` |
| ② | `StatefulReader::process_data_msg` 处理 RTPS DATA 子消息（doc3 L568-L699） | 同上 |
| ③ | `change_received` 接纳 CacheChange（doc3 L1086-L1200） | 同上 |
| ④ | `DataReaderHistory::received_change` / `ReaderHistory::add_change` 入 Reader History（doc3 L191-L224） | `vendor/Fast-DDS/src/cpp/fastdds/subscriber/history/DataReaderHistory.cpp`、`vendor/Fast-DDS/src/cpp/rtps/history/ReaderHistory.cpp` |
| ⑤ | 标记 unread，`NotifyChanges` 通知 listener/StatusCondition（doc3 L1237-L1305） | `StatefulReader.cpp` |
| ⑥ | best-effort 走另一条 `StatelessReader` 分支 | `vendor/Fast-DDS/src/cpp/rtps/reader/StatelessReader.cpp` |

**(b) 取数 —— 跑在 Executor 线程（详见 1.3 等待链唤醒后）：**

| 跳 | 函数与职责 | 本仓真实路径 |
|----|-----------|--------------|
| ⑦ | `__rmw_take` 调 `data_reader_->take` | `vendor/rmw_fastrtps/rmw_fastrtps_shared_cpp/src/rmw_take.cpp`（doc3 L68-L133） |
| ⑧ | `DataReaderImpl::take` / `read_or_take` 在 Reader History 筛选并取出样本（doc3 L528-L605 / L644-L655） | `vendor/Fast-DDS/src/cpp/fastdds/subscriber/DataReaderImpl.cpp` |
| ⑨ | `deserializeROSmessage` 把 payload 反序列化进 ROS 消息（doc3 TypeSupport_impl L181-L206） | `vendor/rmw_fastrtps/rmw_fastrtps_shared_cpp/src/TypeSupport_impl.cpp`（L196 调用点） |

**(c) 用户 callback —— 发行版，不在 vendor：**

| 跳 | 函数与职责 | 本仓 |
|----|-----------|------|
| ⑩ | `Subscription::handle_message` 按 callback 类型与 MessageInfo 执行用户函数 | 无（Humble `rclcpp`/`rclpy`） |

**链 B 对照：** `rmw_take` → `rmw_take_int` → `dds_take`（doc3 L3344-L3435 / L3765-L3781）：

| 跳 | 链 B 落点 | 本仓真实路径 |
|----|-----------|--------------|
| 收包入 RHC | Cyclone `rhc_store` → 默认 RHC | `vendor/CycloneDDS/src/core/ddsi/src/ddsi_rhc.c`、`vendor/CycloneDDS/src/core/ddsc/src/dds_rhc_default.c`、`vendor/CycloneDDS/src/core/ddsc/src/dds_rhc.c` |
| take | `dds_take` | `vendor/CycloneDDS/src/core/ddsc/src/dds_read.c` |

> ⚠️ **入 Reader History ≠ 用户 callback 已跑。** 样本可以停在 reader cache 里，直到 Executor 被唤醒、`rmw_take` 才把它拿走。

### 1.3 等待/就绪通知链（独立链路）

doc3 §4.1 明确：**就绪通知链不是取数链**。它只负责回答「谁就绪了」，不负责拿数据。

```cpp
Executor::wait_for_work()        // 发行版，不在 vendor
  -> rclcpp::WaitSet::wait()     // 发行版，不在 vendor
  -> rcl_wait()                  // 发行版，不在 vendor（doc3 wait.c L538-L741，rmw_wait 在 L701）
  -> rmw_wait()
  -> FastDDS::WaitSet::wait()    // 或 Cyclone dds_waitset_wait
  -> ready handles
  -> Executor::get_next_ready_executable()
```

| 位置 | 实现事实 | 本仓真实路径 |
|------|----------|--------------|
| Executor `wait_for_work` | 先按需重建实体集合，再调 `wait_set_.wait(timeout)`（doc3 executor.cpp L758-L786） | 无（Humble `rclcpp`） |
| rcl 整理等待集 | `rcl_wait` 整理 subscription / guard condition / service / client / event / timer，调 `rmw_wait`（doc3 wait.c L538-L741） | 无（Humble `librcl.so`） |
| 链 A `rmw_wait` | 把各 DataReader StatusCondition、事件、guard condition 附加到 Fast-DDS WaitSet；等待后检查首个未取样本，未就绪槽位置空（doc3 rmw_wait.cpp L124-L258；就绪探测 `DataReader::get_first_untaken_info`） | `vendor/rmw_fastrtps/rmw_fastrtps_shared_cpp/src/rmw_wait.cpp`（外层 wrapper：`vendor/rmw_fastrtps/rmw_fastrtps_cpp/src/rmw_wait.cpp`） |
| 链 A DDS WaitSet | `WaitSet::wait` / `WaitSetImpl::wait` | `vendor/Fast-DDS/src/cpp/fastdds/core/condition/WaitSet.cpp`、`vendor/Fast-DDS/src/cpp/fastdds/core/condition/WaitSetImpl.cpp` |
| 链 B `rmw_wait` | subscription/service/client/event 附加到 Cyclone `dds_waitset`（doc3 L4486-L4576） | `vendor/rmw_cyclonedds/rmw_cyclonedds_cpp/src/rmw_node.cpp` |
| 链 B DDS waitset | `dds_waitset_attach` / `dds_waitset_wait` | `vendor/CycloneDDS/src/core/ddsc/src/dds_waitset.c` |
| DimOS 原生链 B | **不走** `rmw_wait` / ROS Executor：Cyclone Python `Listener.on_data_available` 里直接 `reader.take()` | `dimos_bridge/dimos/protocol/pubsub/impl/ddspubsub.py`（`_DDSMessageListener.on_data_available` L73） |

---

## 2. 模块职责划分

分层口径与 `docs/architecture/feishu-sink-layers.md`（app / rcl / rmw / DDS / executor / memory 六层）一致。

### 2.1 传输层（DDS / RTPS / transport）

| 模块 | 职责 | 本仓路径 |
|------|------|----------|
| Fast-DDS DataWriter/WriterHistory | 发送侧缓存、可靠/不可靠发送、重传、flow controller | `vendor/Fast-DDS/src/cpp/fastdds/publisher/`、`vendor/Fast-DDS/src/cpp/rtps/writer/`、`vendor/Fast-DDS/src/cpp/rtps/history/WriterHistory.cpp` |
| Fast-DDS DataReader/ReaderHistory | 接收侧缓存、去重、ACK/NACK、匹配 reader proxy | `vendor/Fast-DDS/src/cpp/fastdds/subscriber/`、`vendor/Fast-DDS/src/cpp/rtps/reader/`、`vendor/Fast-DDS/src/cpp/rtps/history/ReaderHistory.cpp` |
| Fast-DDS transport | UDP（builtin）、SHM/DataSharing 的实际收发；`config/fastdds.xml` 仅为只读契约种子 | `vendor/Fast-DDS/src/cpp/rtps/transport/`；配置 `config/fastdds.xml` |
| CycloneDDS write/read/waitset/WHC/RHC | 链 B 等价数据面 | `vendor/CycloneDDS/src/core/ddsc/src/dds_write.c`、`dds_read.c`、`dds_waitset.c`、`vendor/CycloneDDS/src/core/ddsi/src/ddsi_whc.c`、`ddsi_rhc.c` |
| 发现（SPDP/SEDP 内置元流量） | 节点/topic/端点发现、匹配、QoS 兼容判定 | 两端 DDS 内部（Fast-DDS 监听线程 / Cyclone DDSI 线程） |

### 2.2 抽象层（rcl / rclcpp / rmw）

| 模块 | 职责 | 本仓路径 |
|------|------|----------|
| rclcpp | Node / Publisher / Subscription / Executor / WaitSet 的 C++ API | **不在本仓**（Humble `/opt/ros/humble`） |
| rcl | 语言无关 C 公共客户端层；`rcl_publish` / `rcl_take` / `rcl_wait` 句柄检查与转发 | **不在本仓**（Humble `librcl.so`） |
| rmw | 中间件抽象接口、QoS 与公共数据结构的**声明** | `vendor/rmw/rmw/include/rmw/rmw.h`、`vendor/rmw/rmw/include/rmw/types.h`、`vendor/rmw/rmw/include/rmw/qos_profiles.h` |
| rmw_implementation | 运行时按 `RMW_IMPLEMENTATION` 动态装载具体 RMW `.so` 并符号转发 | `vendor/rmw_implementation/rmw_implementation/src/functions.cpp` |
| rmw_fastrtps | ROS 2 → Fast-DDS 适配（QoS 映射、序列化边界、wait/take） | `vendor/rmw_fastrtps/rmw_fastrtps_cpp/`、`rmw_fastrtps_shared_cpp/` |
| rmw_cyclonedds | ROS 2 → Cyclone 适配 | `vendor/rmw_cyclonedds/rmw_cyclonedds_cpp/src/rmw_node.cpp` |
| 类型支持（TypeSupport） | ROS 消息 ↔ CDR payload 编解码的胶水；真正逐字段编码是 rosidl 编译期生成（本仓未 vendor rosidl） | `vendor/rmw_fastrtps/rmw_fastrtps_shared_cpp/src/TypeSupport_impl.cpp` |

### 2.3 业务逻辑层（用户 callback、Executor 调度）

| 模块 | 职责 | 本仓路径 |
|------|------|----------|
| Executor 调度 | SingleThreaded/MultiThreaded：收集可执行实体、等待就绪、挑选工作、执行 callback | **不在本仓**（Humble） |
| 用户 callback | 感知/规划/控制等真实业务计算 | 应用代码（本仓 DimOS 桥接只读副本内的订阅回调） |
| CallbackGroup | 约束同组 callback **能否并发**（MutuallyExclusive / Reentrant），不提供优先级 | **不在本仓**（Humble） |
| DimOS ROS 桥 | 用发行版 `SingleThreadedExecutor.spin_once(timeout_sec=0.01)` 驱动链 A 的 ROS 侧 | `dimos_bridge/dimos/protocol/pubsub/impl/rospubsub.py`（`RawROS._spin` L170-L177） |

### 2.4 dimos_bridge 在双链中的位置与作用

`dimos_bridge/` 是上游 `topsun_dimos` 的**整文件只读拷贝**（`dimos_bridge/SOURCE.md`，SHA `a5259958...`），**不是**新中间件，且本仓硬约束：**不改其运行时行为**。

| 文件 | 在双链中的位置 | 作用 |
|------|----------------|------|
| `dimos_bridge/dimos/core/transport.py` | 应用侧传输抽象基类 `PubSubTransport`（旁挂 LCM/SHM 等本仓范围外实现） | 定义广播/订阅/start/stop 接口；业务节点面向它，不面向具体 DDS |
| `dimos_bridge/dimos/protocol/pubsub/impl/rospubsub.py` | **链 A 的应用侧**：`RawROS` / `DimosROS` 走当前 `RMW_IMPLEMENTATION`（链 A 时即 Fast-DDS，域 42） | 持有 `SingleThreadedExecutor`，`publish` 调 rclpy publisher，订阅回调由 `spin_once` 驱动 |
| `dimos_bridge/dimos/protocol/pubsub/impl/ddspubsub.py` | **链 B 的应用侧**：`DDS` 类直接用原生 Cyclone Python，绕过 RMW/Executor | `_DDSMessageListener.on_data_available` → `reader.take()` → 用户 callback；发布走 `DDS.publish`（L112） |
| `dimos_bridge/dimos/protocol/service/ddsservice.py` | 链 B 的 service 封装 | 见 SOURCE.md 拷贝清单 |

> 一句话：**dimos_bridge 是业务侧的双栈适配器**——链 A 经它落到「ROS2 API → RMW → Fast-DDS」，链 B 经它落到「原生 Cyclone listener」；两条栈在它这里汇合，但它本身不碰 vendor 源码、不做传输优化。

---

## 3. 数据验证点

### 3.1 参数 / 句柄验证（publish / take 入口检查）

| 位置 | 验证内容 | 本仓路径 |
|------|----------|----------|
| `rcl_publish`（发行版） | publisher handle、message、类型一致性检查后才进 `rmw_publish`（doc3 publisher.c L268-L289） | 无（Humble） |
| `rcl_take`（发行版） | subscription handle、msg 指针检查后转 `rmw_take_with_info`（doc3 subscription.c L580-L616） | 无（Humble） |
| `rcl_wait`（发行版） | 整理等待集、逐项核对实体有效性（doc3 wait.c L538-L741） | 无（Humble） |
| `rmw_publish` 声明 | 返回码契约：`RMW_RET_OK` / `RMW_RET_INVALID_ARGUMENT` / `RMW_RET_ERROR` 等 | `vendor/rmw/rmw/include/rmw/rmw.h` |
| `rmw_implementation` 装载期 | `rmw_init` 阶段把整族导出符号**集中预取**，缺符号在初始化就暴露，而非每次 publish 才 dlopen（doc3 §9.1） | `vendor/rmw_implementation/rmw_implementation/src/functions.cpp` |

### 3.2 QoS 兼容性验证

| 位置 | 验证内容 | 本仓路径 |
|------|----------|----------|
| RMW 层 QoS 映射 | ROS QoS → Fast-DDS/Cyclone QoS 的转换与合法性整理 | 链 A：`vendor/rmw_fastrtps/rmw_fastrtps_shared_cpp/src/qos.cpp`、`rmw_qos.cpp`；链 B：`vendor/rmw_cyclonedds/rmw_cyclonedds_cpp/src/rmw_node.cpp` |
| 端点匹配 | publish/subscriber 匹配时按 QoS 规则判定是否可互通（reliability/durability 兼容矩阵）；不匹配产生 `incompatible_qos` 事件 | 头文件枚举：`vendor/rmw/rmw/include/rmw/events_statuses/incompatible_qos.h`、`incompatible_type.h`；匹配逻辑在 DDS 发现层 |
| 事件通知 | 不兼容 QoS 通过 `rmw_event` 上报，Executor/WaitSet 可感知 | `vendor/rmw_fastrtps/rmw_fastrtps_shared_cpp/src/rmw_event.cpp` |

### 3.3 序列化 / 反序列化验证

| 位置 | 验证内容 | 本仓路径 |
|------|----------|----------|
| 发送 | `TypeSupport_impl.cpp` 调 `serializeROSmessage`（L140），写 CDR encapsulation 后经回调表 `cdr_serialize` | `vendor/rmw_fastrtps/rmw_fastrtps_shared_cpp/src/TypeSupport_impl.cpp` |
| 接收 | `deserializeROSmessage`（L196）经 `cdr_deserialize` 回填 ROS 消息 | 同上 |
| 回调表绑定 | 把 untyped `void*` 转回具体 C++ 类型，函数指针交 RMW TypeSupport（doc3 §5.1；逐字段编码由 rosidl 模板生成，本仓未 vendor） | 生成侧不在本仓；胶水侧见 `TypeSupport_impl.cpp` 与 `vendor/rmw_fastrtps/rmw_fastrtps_cpp/src/type_support_common.cpp` |
| Fast CDR 底层 | 序列化字节流本身的编解码库 | `vendor/Fast-DDS/thirdparty/fastcdr/` |

### 3.4 这些验证强制执行了哪些假设

1. **`publish()` 成功 = 本端接受**，不是「对端收到」。RMW 返回码只覆盖到入队。
2. **类型闭环靠编译期生成**：跨进程/跨架构能互操作，前提是双方用**同一份消息定义**生成的 `cdr_serialize` 家族；改消息定义或自定义 typesupport，就同时进 ABI、字节序、对齐、bounded/plain 判定、rosbag2/RViz、跨版本互通风险（doc3 §5.1 callout）。
3. **QoS 兼容是声明期/匹配期假设**：best-effort 订阅 + reliable 发布可以共存但语义降级；`ros2 topic` 能连上 ≠ QoS 语义如你所想（doc3 §10.3）。
4. **句柄有效假设只在调用栈内成立**：跨线程销毁 publisher/subscription 后旧句柄的行为不在 `rcl_publish` 检查覆盖范围。

---

## 4. 主要陷阱（更改前最需注意）

### 4.1 `publish` 返回 ≠ 对端已收到

`publish()` / `rmw_publish()` 返回 `RMW_RET_OK` 只是本进程把样本交给了 DataWriter / `dds_write_*`（`docs/architecture/ros2-source-map.md` 开篇原话）。端到端送达要另走 wait→take→executor。可靠 QoS 也只是「尽最大努力重传」，不是无界等待或绝不丢（doc3 §10.3）。

### 4.2 接收不是发布调用栈的倒放，是两条异步链在 History 汇合

发布链在调用线程内跑完（到 WriterHistory/transport）；接收侧 ingress 跑在 **DDS 后台接收线程**，把样本放进 ReaderHistory；Executor 线程再通过 wait/take 取走。三者没有同步关系。**入 ReaderHistory ≠ callback 已跑**，样本可以在 cache 里排队等 Executor。

### 4.3 RMW 等待接口与 DDS 原生等待接口的不匹配

doc2（CycloneDDS 瓶颈研究）引核心开发者原话：`rcl_wait` 开销大，根源是 **ROS 2 RMW 等待接口与 DDS 底层原生等待接口之间「彻底的不匹配（total mismatch）」**。本仓对应实现：链 A `__rmw_wait`（`vendor/rmw_fastrtps/rmw_fastrtps_shared_cpp/src/rmw_wait.cpp`）要把 RMW 统一等待模型摊到 Fast-DDS WaitSet/StatusCondition 上，再逐项回填就绪槽位——这层映射本身就是开销，也是 doc2 建议「回调隔离 Executor 或绕过 RMW 直接调 DDS」的原因。

### 4.4 动态数据类型导致零拷贝失效

doc2 核心结论：ROS 高带宽消息（Image/PointCloud2）内部大量 `std::vector` / `std::string` 动态结构，**只有编译期定长 POD 类型才能在 SHM/Iceoryx 里真正零拷贝**；非定长消息仍要发送端序列化进共享内存、接收端反序列化拷出。Iceoryx 18+ 订阅者时延迟可指数爆炸（doc2 issue #525）。doc3 §5.3 把五种常被混称为「零拷贝」的机制（intra-process / Loaned / DDS SHM / Data Sharing / BufferBackend）逐一列出边界——**「开了 SHM」不等于零拷贝生效**。本仓 `vendor/CycloneDDS/src/psmx_iox/` 带 Iceoryx 适配源码，但 Iceoryx 本体未 vendor，`AUTO ≠ 已开零拷`（`feishu-sink-layers.md` memory 层）。

### 4.5 发现风暴问题

DDS 要求节点加入网络时用内置发现流量（SPDP/SEDP）广播存活与 topic 信息；节点/发布订阅数量激增时，基于组播的全对全发现会形成**发现风暴**，挤占业务带宽（doc2 第二章）。缓解手段「单进程复用 DomainParticipant（node-to-participant mapping）」只能缓解单进程内，多进程/多主机仍在。WiFi/弱网下组播脆弱性是 doc2 建议跨网段场景迁移 `rmw_zenoh` 的依据之一——**本仓对 zenoh 是 Hold，不 vendor、不启用**。

### 4.6 版本差异：Humble vs Rolling 的 WaitSet/Buffer 分支不同（本仓最大坑）

doc3 §11 版本矩阵 + 本仓 `vendor/MANIFEST.md`：

- 本仓运行时 **Humble**（Fast-DDS 2.6.x、Cyclone 0.10.x 语义）；vendor 是 **rolling / master** 快照（Fast-DDS ~3.6、Cyclone 11.0.1）。
- Rolling 的 `rmw_fastrtps_cpp` 导出符号多一层 **Buffer-aware wrapper**（`vendor/rmw_fastrtps/rmw_fastrtps_cpp/src/rmw_publish.cpp` / `rmw_take.cpp`），遇 legacy 端点回退 shared `__rmw_*`；**Humble/Jazzy 同名 wrapper 不同，不能把 Rolling 的 Buffer 分支当 Humble 已有能力**（doc3 §5.2 callout）。
- Executor 的 WaitSet/WaitResult 细节三代都不同（Humble 旧 MemoryStrategy + 原始 `rcl_wait_set_t`）。**严禁在 Rolling 上改完直接把文件覆盖进 Humble**；正确做法是选目标发行版 → 语义 diff → 最小补丁回移。
- 另：`config/fastdds.xml` 头注释记录过 Humble Fast-DDS 2.6 的 schema 坑——History QoS 必须写在 `<topic><historyQos>`，写 `<qos><history>` 会 `loadXMLFile` 失败（iter1 教训）。

### 4.7 CallbackGroup 不是线程优先级

doc3 §4.3：`MutuallyExclusive`（同组不并发）/`Reentrant`（同组可并发）只约束**能否同时执行**，不提供截止期、优先级、WCET 或 CPU 亲和保证。MultiThreadedExecutor 加线程 ≠ 确定性提高；`get_next_ready_executable` 的扫描顺序不是实时优先级保证，过载时可能饥饿或抖动。改 Executor 前必须先 trace 证明瓶颈在等待/扫描/锁/callback 哪一段。

---

## 5. 接下来应阅读的文件清单（按优先级）

路径相对仓库根 `/tmp/tutti_task/ros2_hzj`。标注「不在本仓」的是 Humble 发行版位置，用于对照阅读。

### 5.1 总览先行（5 分钟）

| 优先级 | 文件 | 读什么 |
|--------|------|--------|
| P0 | `vendor/VERSIONS.md`、`vendor/MANIFEST.md` | 双链 vendor SHA 钉扎；rolling 快照 ≠ Humble 运行时的语义 |
| P0 | `docs/architecture/ros2-source-map.md` | 三条链在本仓的已核对路径总图（本文与它对齐） |
| P0 | `docs/architecture/feishu-executor-waitset.md` | WaitSet → `rmw_wait` → take → callback 的双链身份地图 |

### 5.2 发布链

| 优先级 | 文件：函数 | 看什么 |
|--------|-----------|--------|
| P1 | `vendor/rmw_implementation/rmw_implementation/src/functions.cpp`：`load_library`、`rmw_publish` 转发 | `RMW_IMPLEMENTATION` 如何决定最终 `.so` |
| P1 | `vendor/rmw_fastrtps/rmw_fastrtps_cpp/src/rmw_publish.cpp` | Buffer-aware / fallback 分支（Rolling 特性，勿套 Humble） |
| P1 | `vendor/rmw_fastrtps/rmw_fastrtps_shared_cpp/src/rmw_publish.cpp`：`__rmw_publish` | SerializedData 包装、调 `write_w_timestamp` |
| P1 | `vendor/Fast-DDS/src/cpp/fastdds/publisher/DataWriterImpl.cpp`：`write_w_timestamp` / `perform_create_new_change` | CacheChange 创建与序列化发生点 |
| P2 | `vendor/Fast-DDS/src/cpp/fastdds/publisher/DataWriterHistory.cpp`：`add_pub_change`；`vendor/Fast-DDS/src/cpp/rtps/history/WriterHistory.cpp`：`add_change_` | 入队即返回的边界 |
| P2 | `vendor/Fast-DDS/src/cpp/rtps/writer/StatefulWriter.cpp` / `StatelessWriter.cpp` | 可靠 vs 尽力发送分支 |
| P2 | `vendor/CycloneDDS/src/core/ddsc/src/dds_write.c`、`vendor/CycloneDDS/src/core/ddsi/src/ddsi_whc.c` | 链 B 对照 |

### 5.3 接收链 / ingress

| 优先级 | 文件：函数 | 看什么 |
|--------|-----------|--------|
| P1 | `vendor/Fast-DDS/src/cpp/rtps/reader/StatefulReader.cpp`：`process_data_msg` / `change_received` / `NotifyChanges` | 后台线程如何把样本放进 History 并通知 |
| P1 | `vendor/Fast-DDS/src/cpp/fastdds/subscriber/history/DataReaderHistory.cpp`：`received_change`；`vendor/Fast-DDS/src/cpp/rtps/history/ReaderHistory.cpp` | ReaderHistory 接纳点 |
| P2 | `vendor/Fast-DDS/src/cpp/fastdds/subscriber/DataReaderImpl.cpp`：`read_or_take` / `take` | Executor 侧真正取样本的函数 |
| P2 | `vendor/CycloneDDS/src/core/ddsi/src/ddsi_rhc.c`、`vendor/CycloneDDS/src/core/ddsc/src/dds_rhc_default.c`、`vendor/CycloneDDS/src/core/ddsc/src/dds_read.c` | 链 B RHC 与 take 对照 |

### 5.4 等待链

| 优先级 | 文件：函数 | 看什么 |
|--------|-----------|--------|
| P1 | `vendor/rmw_fastrtps/rmw_fastrtps_shared_cpp/src/rmw_wait.cpp`：`__rmw_wait` | RMW↔DDS 等待接口映射（4.3 的不匹配就长在这里） |
| P1 | `vendor/Fast-DDS/src/cpp/fastdds/core/condition/WaitSetImpl.cpp`：`wait` | DDS 原生等待如何被唤醒 |
| P2 | `vendor/rmw_cyclonedds/rmw_cyclonedds_cpp/src/rmw_node.cpp`：`rmw_wait` / `rmw_take` / `rmw_publish` | 链 B 三个面的集中落点 |
| P2 | `vendor/CycloneDDS/src/core/ddsc/src/dds_waitset.c` | Cyclone `dds_waitset_attach` / `wait` |
| P3 | Humble 发行版（不在本仓）：`rcl/src/rcl/wait.c`、`rclcpp/src/rclcpp/executor.cpp`、`single_threaded_executor.cpp` | doc3 §3/§4 的 Executor 侧函数（`get_next_executable`、`execute_subscription`） |

### 5.5 序列化

| 优先级 | 文件 | 看什么 |
|--------|------|--------|
| P1 | `vendor/rmw_fastrtps/rmw_fastrtps_shared_cpp/src/TypeSupport_impl.cpp`：`serializeROSmessage` / `deserializeROSmessage` | 发送/接收序列化调用点（L140 / L196） |
| P2 | `vendor/rmw_fastrtps/rmw_fastrtps_cpp/src/type_support_common.cpp` | 静态 TypeSupport 如何桥到 `cdr_serialize` |
| P2 | `vendor/Fast-DDS/thirdparty/fastcdr/` | CDR 编解码本体 |

### 5.6 Executor / 业务桥

| 优先级 | 文件 | 看什么 |
|--------|------|--------|
| P2 | `dimos_bridge/dimos/protocol/pubsub/impl/rospubsub.py`：`RawROS._spin`（L170-L177，`spin_once(0.01)`） | 链 A 业务侧如何驱动 Executor（只读，不改） |
| P2 | `dimos_bridge/dimos/protocol/pubsub/impl/ddspubsub.py`：`_DDSMessageListener.on_data_available`（L73）、`DDS.publish`（L112） | 链 B 原生 listener 路径（不经 Executor） |
| P3 | `dimos_bridge/dimos/core/transport.py`：`PubSubTransport` | 业务侧传输抽象基类 |
| P3 | `config/env/chain_a.sh` / `chain_b.sh` / `load.py`、`config/fastdds.xml`、`config/topics.yaml` | 双链切换契约与 topic 常量 |

---

## 6. 应运行的测试或检查

### 6.1 12 个闸门脚本（仓库根执行；无 ROS 环境下也应 exit 0）

全部命令（登记见 `AGENTS.md`、`docs/architecture/ci-cd-gates.md`）：

```bash
cd /tmp/tutti_task/ros2_hzj

# ① 身份闸：当前进程会加载哪个 RMW（doc3 §6.3；环境/字符串检查，不是改过的 .so）
python3 scripts/prove_rmw.py

# ② 源码地图闸：本文引用路径与允许清单符号是否还在
python3 scripts/check_source_map.py

# ③ bench 指针闸：bench 产物指针/STATUS 是否仍 blocked（不读数字）
python3 scripts/print_bench_gates.py

# ④ 风险矩阵闸（doc3 §9.4 层序）
python3 scripts/check_risk_matrix.py

# ⑤ Executor/WaitSet 身份地图闸
python3 scripts/check_executor_map.py

# ⑥ 运行时出处闸（underlay vs overlay vs vendor 快照；Humble ≠ rolling）
python3 scripts/check_runtime_provenance.py

# ⑦ Unitree Cyclone 换库闸（bundled 0.10.2 vs vendor 11.0.1 = drop-in FAIL）
python3 scripts/check_unitree_cyclone_swap.py

# ⑧ 三链复现诚实性闸（map≠reproduce；必须保持 STATUS: blocked）
python3 scripts/check_three_chain_repro.py

# ⑨ 下沉层闸（app/rcl/rmw/DDS/executor/memory 的 Hold vs allowed）
python3 scripts/check_sink_layers.py

# ⑩ 双链基线闸（FastDDS + Cyclone 基线指针；不改 XML/SCOREBOARD）
python3 scripts/check_dual_chain_baseline.py

# ⑪ DoD 证据诚实闸（DoD: unmet / STATUS: blocked）
python3 scripts/check_dod_evidence.py

# ⑫ Cega/Bridge Hold 闸（不集成 Cega、不改 dimos_bridge 运行时）
python3 scripts/check_cega_bridge_hold.py

# 链切换 env 打印（import load.py 不写 os.environ，须显式 source/apply）
python3 config/env/load.py print-a
python3 config/env/load.py print-b
```

> 约定：行号过期但符号还在 → 警告；文件或符号消失 → 失败。**不要为了本地绿去编译 vendor、改 XML 或填假分位数。**

### 6.2 bench 测试流程（入口 `docs/usage/benchmark-dds.md`、`scripts/bench/`）

拓扑标签每个 run **只标一个**：`same-process` / `same-host` / `cross-host-UDP`。链 A 与链 B **分目录、分表**，禁止合成 A/B 对照表。产物三件套：`summary.md`（p50/p95/p99，RTT）+ `raw.json` + `environment.md`。

```bash
cd /tmp/tutti_task/ros2_hzj

# 链 B（原生 Cyclone / 域 0；不要 source chain_a.sh）
./scripts/bench/run_chain_b.sh
TOPOLOGY=same-host ./scripts/bench/run_chain_b.sh            # 可选同机两进程
ICEORYX=off TOPOLOGY=same-host ./scripts/bench/run_chain_b.sh

# 链 A（需要 Humble + rmw_fastrtps_cpp；推荐 Docker 配方）
./scripts/bench/docker_chain_a.sh
# 本机已有 Humble 时：
# source /opt/ros/humble/setup.bash && source config/env/chain_a.sh && ./scripts/bench/run_chain_a.sh

# 大包（雷达/图像量级，约 100 KiB–1 MiB）——单独跑，不与默认闭包混表
BENCH_DATE=<UTC>-iter2-large-baseline ./scripts/bench/run_large_packet.sh

# IMU 高频小包（64 B / 200 Hz）——单独跑，不与大包表混表
BENCH_DATE=<UTC>-iter6-imu-baseline ./scripts/bench/run_imu_hf.sh

# 跨机 UDP（链 A，域 42；单机只记 blocked，禁止填假分位数）
# Host B（responder，先起）：
ROLE=responder QOS=high_throughput BENCH_TOPIC_PREFIX=hzj_cross_host ./scripts/bench/run_cross_host_a.sh
# Host A（client）：
ROLE=client CROSS_HOST_PEER=<host-B> QOS=high_throughput BENCH_TOPIC_PREFIX=hzj_cross_host ./scripts/bench/run_cross_host_a.sh
```

pytest 直跑（依赖补齐时）：`pytest dimos_bridge/dimos/protocol/pubsub/benchmark/test_benchmark.py -m tool -k dds -v`（`-k dds` 选中的是 **Cyclone 链 B** 用例，不是 Fast-DDS）。注意：上游 Latency 列是 drain time，**不是** per-message 分位；分位数只来自 `scripts/bench/pingpong.py`。

### 6.3 修改后应验证的接口矩阵（doc3 §9.1 / §12.2）

任何触及 RMW/DDS 的改动后，至少复核：

| 维度 | 覆盖点 |
|------|--------|
| RMW 接口族 | init/shutdown、node、publisher、subscription、**wait/guard/event**、service/client、graph/discovery、TypeSupport、错误码（doc3 §9.1 九族） |
| 消息类型 | 小控制包 / 中状态包 / 大图像点云；plain vs bounded vs unbounded；嵌套数组与字符串（零拷贝边界由此决定） |
| QoS | BestEffort/Reliable、KeepLast/KeepAll、不同 depth、durability、deadline/lifespan/liveliness |
| Executor | Single/Multi、MutuallyExclusive/Reentrant、长 callback 与 timer/service 并存 |
| 拓扑 | same-process / same-host / cross-host-UDP；单/多 pub 与 sub；x86_64↔aarch64 |
| 故障 | 断网/抖动/丢包、对端重启、队列满、发现风暴、慢订阅者 |
| 工具生态 | `ros2 topic/node`、RViz、rosbag2、component、lifecycle（doc3 §7.4） |
| 版本 | 改在 Rolling vendor 阅读 ≠ Humble 运行时生效；目标分支必须逐文件 diff（4.6） |

---

## 7. 业务逻辑 vs 传输层 / UI 层的界定

### 7.1 谁负责实际业务逻辑

- **用户 callback**（感知/规划/控制计算）：在 Humble `rclcpp`/`rclpy` Executor 线程里执行——**不在本仓**。本仓只能看到 DimOS 桥接侧的注册点：链 A `rospubsub.py` 的订阅回调挂在 `SingleThreadedExecutor.spin_once` 上；链 B 原生 `ddspubsub.py` 的回调挂在 Cyclone listener 上。
- **调度策略**：Executor 如何挑下一个工作、CallbackGroup 并发约束——Humble `rclcpp`，**不在本仓**。
- **本仓的业务侧代码**（`dimos_bridge/`）只是桥接与传输抽象，**不**包含真实感知/控制算法；它本身被列为只读，不许改运行时。

### 7.2 哪些是传输层

- 链 A：`rmw_implementation` → `rmw_fastrtps_cpp` → Fast-DDS（DataWriter/Reader、History、RTPS、transport），配置 `config/fastdds.xml`。
- 链 B：`rmw_cyclonedds_cpp` 或原生 Cyclone Python → CycloneDDS（ddsc/ddsi、WHC/RHC）。
- 传输层**不**理解业务语义：它只按 topic/QoS/domain 分发字节流；`publish` 一个导航指令和发一帧点云，在传输层眼里只是不同大小的样本。

### 7.3 哪些容易被忽略的后台任务（不在 publish 调用栈里）

| 后台任务 | 跑在哪 | 影响 |
|----------|--------|------|
| **发现线程**（SPDP/SEDP） | 两端 DDS 进程内 | 节点上下线、端点匹配、QoS 兼容判定；规模一大就是发现风暴（4.5） |
| **接收线程**（ingress） | Fast-DDS / Cyclone 进程内 | NIC/SHM 收包 → ReaderHistory；与 publish 线程、Executor 线程**三者不同线程** |
| **可靠重传** | StatefulWriter 后台 | ACK/NACK、丢包重传、flow controller；best-effort 走 StatelessWriter 无此负担 |
| **Executor 线程** | 用户进程（链 A/B 的 ROS 侧） | `spin_once` 轮询；长 callback 会阻塞同 Executor 的 timer/service |
| **DimOS 原生 listener 线程**（链 B） | `ddspubsub.py` `on_data_available` | 不经 Executor，回调在 Cyclone listener 上下文直接执行 |
| **定时器/timer** | Executor | 与 subscription 竞争同一个 Executor 的注意力 |

> 归因纪律（`docs/architecture/latency-attribution.md`）：先跑 `prove_rmw.py` 确认加载了谁、`check_source_map.py` 确认地图还在，**再**谈「是 Fast-DDS 还是 Cyclone 的问题」；vendor SHA 不能当性能证据，`same-host` 分位数不能代替现场/跨机证明。

---

## 附：与上游方案文档的对应

- 发布→Executor→WaitSet→callback 完整调用链、版本矩阵、接口族、DoD：飞书《ROS2 官方源码深挖》（doc3）。本文逐跳函数名与其 §2/§3/§4/§10 一致，行号以其 Rolling 快照为准，本仓 vendor 同名文件路径已核对存在。
- 四大瓶颈（内核网络栈开销 / 动态类型零拷贝失效 / RMW 等待接口不匹配 / 发现风暴）与行业对照（Tier IV Agnocast、宇树、大陆 eCAL、百度 CyberRT、Zenoh）：飞书《DDS 优化研究》（doc2）。本仓对 Agnocast/zenoh/eCAL/DPDK/Cega 一律 **Hold**。
- 中间件路线（ROS2 主线 + 差异化下沉到 RMW/DDS/Executor，不重写整套中间件；`RMW_IMPLEMENTATION` 进程级切换）：飞书《通信中间件》（doc1）。
