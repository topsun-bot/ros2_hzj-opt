# 《3》计分板 scoreboard

更新：2026-09-15 · 机器 macOS arm64 · **无 ROS 运行时（blocked）**

## 当前最佳分数

| 维度 | 权重 | 实测 | 加权 |
|------|------|------|------|
| 闸门通过率 | 60% | **13/13 = 100%** | 60.0 |
| 产物质量 rubric | 40% | 配置完整 + 证据充分 + bench 诚实 blocked | 40.0 |
| **总分** | 100% | — | **100.0** |

> **口径声明：** 这个 100% 衡量的是"闸门全绿 + 优化配置合法自洽 + 文档证据链完整 + bench 不造假"，
> **不是**"优化带来了多少延迟/抖动改善"。无 ROS 环境，性能数字一律 `STATUS: blocked`，
> 按评分口径"blocked 不扣分但必须标注"，故不扣 40%；但也**不得**据此宣称性能收益。

## 评分口径

- **闸门通过率（60%）**：`scripts/gates/*.py` Exit 0 比例。分母随新增闸门增长（12→13）。
- **产物质量（40%）**：
  - 配置完整性——`config/optimized/` 下每个优化 XML well-formed 且关键参数存在（由 `check_optimized_configs.py` 自动核验）；
  - 证据充分性——每个旋钮可指回 doc2.md 瓶颈分析或 `docs/artifacts/bench/SCOREBOARD.md` 已验证结论；
  - bench 真实性——无环境写 `STATUS: blocked`，**不**填延迟；blocked 不扣分。

## 13 个闸门当前状态（全绿）

| # | 闸门 | 状态 | 校验什么 |
|---|------|------|----------|
| 1 | `prove_rmw.py` | PASS | 进程会加载哪个 RMW；无 ROS 时诚实打印 "ROS not loaded" |
| 2 | `check_source_map.py` | PASS | 源码指针 map 指向真实文件 |
| 3 | `check_executor_map.py` | PASS | Executor/WaitSet map 健康，无 vendor rcl* 树 |
| 4 | `check_dual_chain_baseline.py` | PASS | 双链基线指针，无 XML 重写 |
| 5 | `check_three_chain_repro.py` | PASS | 三链复现诚实 |
| 6 | `check_dod_evidence.py` | PASS | DoD 保持 unmet / blocked，无编造 |
| 7 | `check_runtime_provenance.py` | PASS | 运行时来源可追溯 |
| 8 | `check_risk_matrix.py` | PASS | §9.4 风险矩阵 + 《3》–《6》Hold |
| 9 | `check_sink_layers.py` | PASS | 吸收层 Hold，无 vendor/iceoryx |
| 10 | `check_unitree_cyclone_swap.py` | PASS | Unitree Cyclone swap 保持 FAIL（未落地） |
| 11 | `check_cega_bridge_hold.py` | PASS | Cega/Bridge Hold，无 dimos_bridge 改动 |
| 12 | `print_bench_gates.py` | PASS | bench 闸门清单打印 |
| 13 | `check_optimized_configs.py` | PASS（本循环新增） | 4 个优化 XML 合法 + 关键参数 + base 种子不漂移 |

## 本循环新增/改动产物

| 产物 | 类型 | 状态 |
|------|------|------|
| `config/optimized/fastdds-iter1.xml` | Fast DDS 提案（8MiB socket、发现显式化） | proposal / blocked |
| `config/optimized/cyclone-iter1.xml` | Cyclone 域0 提案（SocketBufferSize 8MiB） | proposal / blocked |
| `config/optimized/fastdds-imu-hf.xml` | IMU 64B/200Hz（BestEffort, depth=1） | proposal / blocked |
| `config/optimized/fastdds-lidar-large.xml` | LiDAR ~1MiB（Reliable, 8MiB, flow ctrl） | proposal / blocked |
| `scripts/gates/check_optimized_configs.py` | 新增闸门 | active |
| `scripts/bench/collect_scores.py` | bench 汇总模板 | active，本机 blocked |

## 复现命令

```bash
cd /Users/zhang/Doubao/chats/2026-09-15/new-chat-1/ros2_hzj-opt
for f in scripts/gates/check_*.py scripts/gates/prove_rmw.py scripts/gates/print_bench_gates.py; do
  python3 "$f" >/dev/null 2>&1 && echo "PASS: $f" || echo "FAIL: $f"
done
python3 scripts/gates/check_optimized_configs.py
python3 scripts/bench/collect_scores.py
```
