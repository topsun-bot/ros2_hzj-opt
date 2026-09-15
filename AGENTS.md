# AGENTS — ros2_hzj-opt

本仓库是 `ros2_hzj` 的优化产物仓库，独立于 `topsun_dimos`。

## 硬约束（Hold）

- **不修改 vendor 源码行为**：`vendor-ref/` 仅为版本引用，不做源码补丁。
- **不集成 Agnocast / zenoh / Cega**：不引入 vendor 树、内核模块或 `rmw_zenoh`。
- **不改 dimos_bridge 运行时**：DimOS 双链桥接不在本仓库修改范围。
- **不修改基线种子**：`config/optimized/fastdds-base.xml` 是从 ros2_hzj 复制的基线，优化配置另存新文件。
- **bench 数字必须真实测量**：无环境时写 `STATUS: blocked`，禁止编造分数。

## 允许的优化面

- DDS XML 配置调优（发现、QoS、SHM、传输参数）——另存新文件
- Executor / WaitSet 调度策略文档与配置建议
- 评估驱动的配置迭代循环
- 文档级中日优化吸收（低风险、行为不变）
- 重构计划（不直接改 vendor 代码，输出可审查的步骤文档）
- 安全审计（只读 CVE 核查）
- Promptfoo 评估套件

## 验证闸门

```bash
cd /Users/zhang/Doubao/chats/2026-09-15/new-chat-1/ros2_hzj-opt
python3 scripts/gates/prove_rmw.py
python3 scripts/gates/check_source_map.py
# ... 共 12 个，见 README
```

## 参考路径

- 基线仓库：`/tmp/tutti_task/ros2_hzj`
- 方案文档：`/tmp/tutti_task/doc1.md` ~ `doc4.md`（JSON 包裹，content 字段为正文）
