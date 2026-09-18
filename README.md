# ros2_hzj-opt

> **项目定位**：ROS2 DDS optimization workspace: dual-chain config tuning, eval-driven latency improvement, refactoring plan, security audit, Promptfoo evals, and Mac HIL test results. Independent from topsun_dimos.

ROS 2 DDS 优化工作区——在 `ros2_hzj` 双链基线之上，以证据驱动的方式进行配置调优、重构规划、评估循环、Mac HIL 测试、Promptfoo 评估套件与安全审计。

> 本仓库独立于 `topsun_dimos`，是 `topsun-bot/ros2_hzj` 的优化产物仓库。不修改 vendor 源码行为，不集成 Agnocast/zenoh/Cega，不改 dimos_bridge 运行时。

## 双链基线

| 链 | RMW | Domain | 配置 |
|---|---|---|---|
| Chain A | `rmw_fastrtps_cpp` | 42 | `config/optimized/fastdds-base.xml`（基线种子） |
| Chain B | `rmw_cyclonedds_cpp` | 0 | CycloneDDS 11.0.1 |

## 目录结构

```
├── docs/
│   ├── 01-dds-request-flow.md        # 《1》DDS 请求流分析
│   ├── 02-refactoring-plan.md        # 《2》现代化重构计划
│   ├── 03-eval-driven-improvement/   # 《3》评估驱动改进循环
│   ├── 04-mac-hil-test/              # 《4》Mac 系统测试报告
│   ├── 06-security-audit/            # 《6》安全审计报告
│   └── architecture/                  # 架构文档（含中日优化吸收扩展）
├── config/optimized/                  # 优化后的 DDS 配置（不修改基线种子）
├── scripts/gates/                     # 12 个验证闸门脚本
├── scripts/bench/                     # 基准测试脚本
├── evals/                             # 《5》Promptfoo 评估套件
└── vendor-ref/                        # vendor 版本引用（非源码拷贝）
```

## 验证闸门

```bash
# 全部 12 个闸门（无 ROS 运行时即可运行）
for f in scripts/gates/check_*.py scripts/gates/prove_rmw.py scripts/gates/print_bench_gates.py; do
  python3 "$f" && echo "PASS: $f" || echo "FAIL: $f"
done
```

## Promptfoo 评估套件

```bash
cd evals && npm install && npm run evals   # 默认 echo provider，无需 API key
```

详见 `evals/README.md` 与 `evals/EVAL-REPORT.md`。接入真实 LLM 前，内容断言失败属预期。

## 来源与证据

- 方案文档：飞书《通信中间件》《DDS 优化开源研究》《ROS 2 官方源码深挖》《7/10 选型会议纪要》
- 基线仓库：`topsun-bot/ros2_hzj`
- vendor 版本：见 `vendor-ref/VERSIONS.md`
