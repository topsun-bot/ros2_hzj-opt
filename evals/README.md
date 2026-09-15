# evals/ — Promptfoo 评估套件

针对「**ROS2 DDS 技术问答与配置推荐代理**」的输出质量做回归评估。该代理基于
`ros2_hzj-opt` 双链仓库（FastDDS 链 A / Cyclone 链 B）的知识，回答 DDS 架构、
配置调优、性能瓶颈、RMW 切换、场景化配置推荐等问题。

> 本目录只做**评估**，不修改任何生产提示词或应用行为；不修改 vendor 源码。

## 快速开始

```bash
cd evals
npm install            # 首次（已锁定 promptfoo ^0.123.0）
npm run evals          # 跑评估（默认 echo provider，无需 API key）
npm run evals:view     # 打开本地 Web 报告
```

## Provider 现状（重要）

| 项 | 值 |
|---|---|
| 默认 provider | `echo`（promptfoo 内置，把用户问题原样当"回答"） |
| 真实 LLM | **未配置**（环境无 OPENAI_API_KEY） |
| 当前基线含义 | 框架冒烟：验证配置加载、8 用例、断言接线、结构化输出链路正确 |

因此基线报告里大部分**内容断言会失败**——这是预期的：echo 不产生真实技术回答，
失败恰好证明断言在工作。接入真实 LLM 后再跑一次，才是有意义的质量基线。

### 接入真实 LLM

1. 设置 key：`export OPENAI_API_KEY=sk-...`
2. 编辑 `promptfoo.yaml`，把 `providers` 里的 `echo` 注释掉、取消 `openai:gpt-4o-mini`
   块的注释。
3. `npm run evals`。

## 评估维度

1. **回答质量**：技术准确性、完整性、基于仓库事实。
2. **检索依据充分性**：是否引用正确文件路径（`config/optimized/fastdds-base.xml`、
   `config/env/chain_a.sh`）、参数名（`maxMessageSize`、`send_buffers`）、域名（42/0）。
3. **业务硬约束**：不改 vendor、不集成 Agnocast/zenoh/Cega、双链域隔离、
   bench 数字真实（无环境写 `blocked`）。
4. **任务完成度**：是否完整回答并给出可操作建议（结构断言：非空、够长、低延迟）。

## 用例列表（8 个）

| 文件 | 主题 |
|---|---|
| `prompts/01-request-flow.txt` | DDS 请求流：发布链/接收链 + 时延分段归因 |
| `prompts/02-dual-chain.txt` | 双链配置差异（域 42 vs 域 0）与混用后果 |
| `prompts/03-jitter-bottleneck.txt` | IMU 抖动瓶颈分析、保留旋钮、禁止重试旋钮 |
| `prompts/04-rmw-switch.txt` | RMW 切换方法（RMW_IMPLEMENTATION + source） |
| `prompts/05-xml-params.txt` | fastdds.xml 关键参数解释 |
| `prompts/06-hard-constraints.txt` | 硬约束遵守 |
| `prompts/07-imu-hf.txt` | IMU 高频场景配置推荐 |
| `prompts/08-lidar-large.txt` | 激光雷达大包（1 MiB）场景配置推荐 |

## 目录结构

```
evals/
├── package.json            # 依赖 + `npm run evals`
├── promptfoo.yaml          # 主配置（provider / 8 用例 / 断言）
├── prompts/
│   ├── system.txt          # 代理角色与硬约束（system prompt）
│   ├── question.txt        # 唯一模板 {{question}}
│   └── 01..08-*.txt        # 8 个用户问题（与 tests vars.question 对齐）
├── tests/
│   └── assertions.yaml     # 断言矩阵（人类可读参考）
├── eval-out/               # 运行产物（results.json）
└── results/
    └── baseline-results.md # 基线评估结果
```

基线结论见 [`results/baseline-results.md`](results/baseline-results.md)
与 [`../EVAL-REPORT.md`](../EVAL-REPORT.md)。
