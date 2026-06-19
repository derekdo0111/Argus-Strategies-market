# ADR-0003: 混合模式 Coordinator

- **日期**: 2026-06-15
- **状态**: 已接受

## 上下文

龟龟策略涉及多步骤流程（选股 → 数据拉取 → 现金质量门 → PR门 → 基本面 → 估值），需要编排机制。两种候选方案：
- **纯 Markdown**: Coordinator 完全由 LLM 读取 markdown 文件后自主执行
- **纯 Python**: Coordinator 完全由 Python 代码硬编码流程

## 决策

采用**混合模式**：
- `turtle-coordinator.md`: 流程定义文档，给 LLM 读取的"说明书"，描述每个 Step 的输入/输出/判定标准
- `coordinator.py`: Python 编排执行器，执行硬逻辑（数据校验、步骤跳转、错误处理），按需加载子模块

Python 脚本负责：
1. 确定性计算（不需要 LLM 参与）
2. 步骤间数据完整性校验
3. 错误处理和重试逻辑
4. 调用 LLM Agent 进行软门分析

## 后果

- LLM 可通过 markdown 理解完整流程，但不会"失控"
- Python 硬逻辑保证数据质量和流程可靠性
- 需要维护两份文档的一致性（md 和 py 必须同步）
