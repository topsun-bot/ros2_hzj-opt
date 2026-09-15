# EVAL-REPORT — Promptfoo 评估套件交付报告

评估对象：**ROS2 DDS 技术问答与配置推荐代理**（基于 ros2_hzj-opt 双链知识）
交付日期：2026-09-15
基线状态：**框架已跑通；LLM provider 未配置（echo 冒烟）**

---

## 1. 已新增/更改的文件

全部位于 `evals/`（未触碰 vendor、未改任何生产提示词或应用行为）：

| 路径 | 说明 |
|---|---|
| `evals/package.json` | promptfoo ^0.123.0 依赖 + `evals`/`evals:view` 脚本 |
| `evals/promptfoo.yaml` | 主配置：provider、8 用例、断言 |
| `evals/prompts/system.txt` | 代理角色 + 硬约束 system prompt |
| `evals/prompts/question.txt` | 唯一提示词模板 `{{question}}` |
| `evals/prompts/01..08-*.txt` | 8 个测试问题文本 |
| `evals/tests/assertions.yaml` | 断言矩阵（人类可读） |
| `evals/README.md` | 套件说明 |
| `evals/results/baseline-results.md` | 基线结果 |
| `evals/eval-out/results.json` | 最近一次运行的机器可读结果 |
| `evals/EVAL-REPORT.md` | 本文件 |

根 `README.md` 增加一行运行命令。

## 2. Eval 命令运行记录

```bash
cd /Users/zhang/Doubao/chats/2026-09-15/new-chat-1/ros2_hzj-opt/evals
npm install            # 安装 promptfoo ^0.123.0（added 860 packages）
npm run evals          # = promptfoo eval -c promptfoo.yaml --no-cache -j 4
```

实际输出摘要（第二次、修正笛卡尔积后的干净运行）：

```
✓ Eval complete (ID: eval-r26-2026-09-15T16:31:09)
Results:
  ✓ 1 passed (12.50%)
  ✗ 7 failed (87.50%)
  0 errors (0%)
Duration: 0s
Writing output to eval-out/results.json
```

> 第一次运行暴露了两个配置问题并已修复：① promptfoo 要求 `-c` 指定非默认文件名；
> ② `prompts:` × `tests:` 被笛卡尔积成 64 组，已改为单模板 + 8 个 `vars.question`。
> ③ `javascript` 断言初版返回对象不符合校验，已改为返回布尔。

## 3. 通过 / 失败案例

| # | 用例 | 状态 | 原因（echo provider 下） |
|---|---|---|---|
| 01 | 请求流 | ✅ 通过（6/6） | 问题文本自含命中，非真实答对 |
| 02 | 双链差异 | ❌ 失败（3/8） | 回答缺 RMW 名、域名、脚本、discovery 后果 |
| 03 | 抖动瓶颈 | ❌ 失败（3/6） | 缺 `healthy_check_timeout`、p95、已丢弃旋钮 |
| 04 | RMW 切换 | ❌ 失败（3/6） | 缺 `RMW_IMPLEMENTATION`、两个 source 脚本 |
| 05 | XML 参数 | ❌ 失败（5/7） | 缺 `280000`、1MiB 分片路径解释 |
| 06 | 硬约束 | ❌ 失败（4/6） | 缺「不集成/不改」与「blocked/不编造」表态 |
| 07 | IMU 高频 | ❌ 失败（4/6） | 缺 `healthy_check`、64/200Hz 场景 |
| 08 | 激光雷达大包 | ❌ 失败（3/6） | 缺 send_buffers/socket、280000、builtin 分片 |

**结构性断言（时延、回答长度）8/8 全部通过**，证明框架与落盘正常。

## 4. 合规自检

- 未修改任何 vendor 源码；`vendor-ref/` 只读。
- 未集成 Agnocast / zenoh / Cega；未改 dimos_bridge 运行时。
- 未改任何生产提示词或应用行为（system.txt 仅在 evals 内被引用）。
- 夹具中无机密、无客户数据、无敏感个人数据。
- 跨机 UDP 等无环境测量保持 `STATUS: blocked` 口径，未编造分数。
- 如实标注：当前为 echo 冒烟，**不构成对真实 LLM 质量的结论**。

## 5. 建议下一步

1. **接入真实 LLM**：`export OPENAI_API_KEY=...`，在 `promptfoo.yaml` 启用
   `openai:gpt-4o-mini`，重跑并把数字写入 `results/` 新版本（勿覆盖 baseline）。
2. **加负面断言**：`not-contains` / `llm-rubric`，防止代理建议改 vendor、接 zenoh、
   编造跨机分位数、说错域名。
3. **加场景**：WaitSet/Executor 调度、topic QoS 冻结表（`/goal_pose` RELIABLE depth=5）、
   Cyclone 侧 `CYCLONEDDS_URI` 未设置的原因。
4. **更严断言**：用 `llm-rubric` 打分"是否引用了正确文件路径"，替代纯字符串包含。
5. **CI 集成**：把 `npm run evals` 挂到 gates，要求结构断言（时延/非空）恒通过；
   内容断言在接入真 LLM 后设阈值。
