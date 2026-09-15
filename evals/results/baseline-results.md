# 基线评估结果（baseline）

- 运行时间：2026-09-15
- 配置：`evals/promptfoo.yaml`，provider = `echo-mock`（**未接真实 LLM**）
- 命令：`cd evals && ./node_modules/.bin/promptfoo eval -c promptfoo.yaml --no-cache -j 4 --output eval-out/results.json`
- Eval ID：`eval-r26-2026-09-15T16:31:09`
- 运行时长：~30 ms，0 error

## 汇总

| 指标 | 值 |
|---|---|
| 用例数 | 8 |
| 用例通过（全部断言满足） | 1（12.5%） |
| 用例失败 | 7（87.5%） |
| 断言总数 | 49 |
| 断言通过 | 结构断言全部通过（8/8 时延、8/8 长度） |

## 诚实说明

`echo` provider 把用户问题原样当作"代理回答"返回。因此：

- **结构断言（时延 <10s、回答长度 ≥40 字）全部通过** —— 框架链路、配置加载、
  并发与输出落盘均正常。
- **内容断言大部分失败** —— 这是**预期且正确**的：echo 没有产生任何技术内容，
  失败恰好证明「回答必须包含 `healthy_check_timeout` / `maxMessageSize=280000` /
  域名 42 / `RMW_IMPLEMENTATION` 等事实」这些断言接线是对的。
- 唯一"内容通过"的用例 #01（6/6）是因为它的问题文本本身就含 `History`、
  `分段`、`回调`、`P99` 等词，被 echo 原样命中——**不代表代理真的答对了**。

> 结论：**评估框架已就绪；LLM provider 未配置，以下数字仅为框架冒烟基线。
> 配置 OPENAI_API_KEY 并切换 provider 后重跑，才是有效质量基线。**

## 逐用例明细（echo 下）

| # | 用例 | 断言通过/总数 | 失败的断言（echo 缺什么） |
|---|---|---|---|
| 01 | 请求流 | 6/6 ✅ | 无（问题文本自含命中，非真实答对） |
| 02 | 双链差异 | 3/8 ❌ | 缺 `fastrtps`、`cyclonedds`、`42`、`chain_b.sh`、`discovery` |
| 03 | 抖动瓶颈 | 3/6 ❌ | 缺 `healthy_check_timeout`、`p95`、已丢弃旋钮名 |
| 04 | RMW 切换 | 3/6 ❌ | 缺 `RMW_IMPLEMENTATION`、`chain_a.sh`、`chain_b.sh` |
| 05 | XML 参数 | 5/7 ❌ | 缺 `280000`、`分片/builtin` 路径解释 |
| 06 | 硬约束 | 4/6 ❌ | 缺「不集成/不改」表态、「blocked/不编造」表态 |
| 07 | IMU 高频 | 4/6 ❌ | 缺 `healthy_check`、`64/200` 场景参数 |
| 08 | 激光雷达大包 | 3/6 ❌ | 缺 `send_buffers/socket`、`280000`、`分片/builtin` |

每个失败项的语义都是「合格代理本应在回答里写出这条仓库事实」。
