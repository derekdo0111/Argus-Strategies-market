# 高景气策略 — 产业学习层（Learning Agent）设计

> 版本: 设计稿 v1 | 日期: 2026-07-02 | 状态: 设计完成，待实现
>
> 产出流程: brainstorming → 根因诊断（LLM 三处波动源）→ 方案选型 → 本 Spec
>
> 前置 Spec: `2026-07-02-signal-quality-fusion.md`（v0.18.3 信号质量融合）

---

## 0. 问题概述

### 背景

当前高景气 Pipeline 存在 **三处 LLM 波动源**，从上游往下游级联放大：

```
搜索素材 ─→ HypothesizeAgent(LLM) ─→ 12条假设
                │                        │
                │  波动源头 #1            │  假设内容、id、sentiment 波动
                │                        ↓
                │          VerifyAgent(LLM) ─→ 验证结果
                │               │               │
                │  波动源头 #2  │               │  反例搜索词 + 验证判断波动
                │               │               │
                │               ↓               ↓
                │          活跃L3假设 ──→ ScreeningAgent(LLM)
                │                                │
                │                   波动源头 #3   │  方向匹配 + 业务线匹配 → 股池波动
                │                                ↓
                │                           最终报告（15 只 vs 8 只）
```

**根因**：LLM 在**没有结构化知识背景的情况下做因果推理**——这是最不稳定、最容易出错的使用方式。HypothesizeAgent 拿到 45 篇搜索碎片，凭空构建 4 层推理链，推理质量取决于训练数据中的先验知识（可能过时、可能有幻觉）。

### 核心问题：Pipeline 少了一步

```
当前: Search ─→ Hypothesize ─→ Verify ─→ Screening ─→ Report
        ↑              LLM 在无结构化知识背景下做因果推理

补上: Search ─→ Learn ─→ Hypothesize ─→ Verify ─→ Screening ─→ Report
                     ↑
              构建产业图谱 → LLM 在已知框架内找边际变化
```

**Learning Agent 是一个前置步骤**：在生成假设之前，先系统地学习这个行业的产业链结构、供需格局、技术路径、政策催化、关键瓶颈和不确定性。产出的**产业图谱**作为稳定的知识锚点，下游所有 Agent 自动消费。

### 改进原则

1. **不改变现有 Agent 的分工**：Hypothesize / Verify / Screening 保持不变，只是多了一个前置知识源
2. **一次 LLM 调用**：避免多步调用增加不稳定性和复杂度
3. **只写一次**：产业图谱生成后写入 wiki 页面，后续研究直接复用（除非搜索素材变化超过阈值）
4. **信源必须引用**：每条判断标注 `[信源N]`，没有信源 → 不写（反幻觉机制）
5. **对所有行业通用**：7 节结构不针对任何特定行业，半导体/光伏/AI/预制菜都能填

---

## 1. 设计总览

### Learning Agent 位置

```
coordinator.py
  │
  ├─ Phase 1: Search (已有)
  │     └─ search_result: 45 条文章 + 成分股列表
  │
  ├─ Phase 1.5: Learn ← 新增！静默执行
  │     ├─ 检查 wiki/industries/{name}.md 是否已有「## 产业图谱」
  │     ├─ 已有 → 跳过
  │     └─ 没有 → LLM 生成 → 追加写入
  │
  ├─ Phase 2: Hypothesize (已有)
  │     └─ _load_history() 自然读到产业图谱 → 知识锚定
  │
  └─ ... 后续不变
```

### 关键设计决策

| # | 决策 | 选型 | 理由 |
|---|------|------|------|
| 1 | 生成方式 | 一次 LLM 调用 | 多步调用增加不稳定性，prompt 写好一次就够了 |
| 2 | 存储位置 | `wiki/industries/{name}.md` 的 `## 产业图谱` 节 | 下游 Agent 已在读 wiki，零架构改动 |
| 3 | Prompt 组织 | `backend/rules/prosperity/prompts/learning_prompt.md` | 模板文件独立迭代，git diff 清晰可读 |
| 4 | 更新策略 | 首次生成 + 手动触发重建 | 产业链结构本质稳定，不需要自动更新 |
| 5 | 信源归属 | 每条事实标注 `[信源N]` | 可追溯，反幻觉 |

---

## 2. 输出结构：产业图谱（7 节）

### 2.1 价值链

按上游→中游→下游梳理产业链。每个环节包含：
- **角色**：这个环节做什么
- **上市公司及代码**：如西部超导 688122.SH
- **当前状态**：基于搜索素材的判断
- **引用信源编号**：如 `[信源1,5]`

### 2.2 供需格局

使用表格，分别列出：

**需求端**：驱动力、类型（政策/资本/出口等）、确定性（高/中/低）、时间窗口

**供给端**：环节、当前供给状态、扩产周期、关键约束

末尾给出「供需判断」一段话：当前 → 趋势 → 风险

### 2.3 技术路径与成熟度

使用表格列出所有技术路径：路径名称、成熟度（科学验证/工程验证/商业示范/规模化）、代表项目或公司、优势、风险

### 2.4 政策催化

使用表格列出关键政策或事件：名称、时间、影响环节、力度评估（强/中/弱）

### 2.5 关键瓶颈

使用表格列出产业瓶颈：瓶颈描述、严重程度（高/中/低）、影响环节、证据信源

### 2.6 跟踪指标

使用表格列出可跟踪的公开指标：指标名称、巡检频率（daily/weekly/monthly/quarterly）、含义

> 此节供给 TrackAgent 使用

### 2.7 ⚠️ 不确定区域

用自然语言列出：基于当前搜索素材，哪些关键问题无法回答或存在分歧。

> 此节是**强制反幻觉机制**——没有这节，LLM 会假装什么都知道

---

## 3. Prompt 模板

### 3.1 文件位置

```
backend/rules/prosperity/prompts/learning_prompt.md
```

### 3.2 模板内容

见 `backend/rules/prosperity/prompts/learning_prompt.md`（与 Spec 同时创建）

### 3.3 核心规则（模板中强制要求）

1. **每条事实性陈述必须引用信源编号**，格式 `[信源N]`
2. **没有信源的判断不要写**，宁可少写不编造
3. 某节若无足够信息，写「暂无足够信息」
4. 只列在搜索素材中出现过的上市公司，不凭空添加
5. 不要写市场规模的具体数字，除非搜索素材中明确给出
6. **7 节顺序固定，不自由发挥**

---

## 4. 代码实现要点

### 4.1 LearningAgent 类

```python
# backend/app/strategies/prosperity/agents/learning_agent.py （新文件）

class LearningAgent:
    def __init__(self, rules_dir: Path):
        template_path = rules_dir / "prompts" / "learning_prompt.md"
        self.template = template_path.read_text(encoding="utf-8")
    
    def learn(self, industry_name: str, search_result: dict) -> str:
        """返回产业图谱 Markdown"""
        search_text = self._format_search(search_result)
        prompt = self.template.format(
            industry_name=industry_name,
            search_results=search_text,
        )
        return self._call_llm(prompt)
```

### 4.2 Coordinator 集成

```python
# coordinator.py 中新增方法
def _run_learning_agent(self, industry_name, search_result):
    wiki_page = self.data_dir / "wiki" / "industries" / f"{industry_name}.md"
    content = wiki_page.read_text(encoding="utf-8")
    
    # 已有产业图谱 → 跳过
    if "## 产业图谱" in content:
        return
    
    agent = LearningAgent(self.rules_dir)
    model_md = agent.learn(industry_name, search_result)
    wiki_page.write_text(content + "\n" + model_md, encoding="utf-8")
```

### 4.3 下游消费（零改动）

HypothesizeAgent 的 `_load_history()` 已在读 wiki 页面。产业图谱作为页面的一部分，自动流入 context。

VerifyAgent 同理。

ScreeningAgent 同理。

---

## 5. 对不稳定性的影响

| 波动源 | 改前 | 改后 |
|--------|------|------|
| HypothesisAgent | 凭空推演 12 条假设 | 在产业图谱框架内找边际变化 |
| VerifyAgent | 不知道查什么数据 | 产业图谱标注了跟踪指标 + 瓶颈 |
| ScreeningAgent | 每次重新判断业务关联 | 产业图谱已列出每环节的上市公司 |

**效果**：
- 同一天内重复跑（搜索素材没变）→ 假设层更稳定（产业图谱锚定）
- 隔几天少量新素材 → 产业图谱复用，只重跑匹配层
- 隔几周大量新素材 → 产业图谱可能需要更新，但框架不变

---

## 6. 后续工作

本 Spec 是讨论中三方案的**第一块**。后续两块：

| # | 方案 | 状态 |
|---|------|------|
| 1 | **Learning Agent**（本 Spec）| 设计完成 |
| 2 | **多源验证矩阵** — VerifyAgent 按假设类型分4类验证（量化/事实/技术/逻辑），硬数据锚 + LLM 解读 | 脑暴完成，待 Spec |
| 3 | **全链路缓存** — Layer 0-3 逐层缓存，相同输入 100% 确定性 | 脑暴完成，待 Spec |

---

## 7. 改动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/rules/prosperity/prompts/learning_prompt.md` | **新增** | Prompt 模板 |
| `backend/app/strategies/prosperity/agents/learning_agent.py` | **新增** | LearningAgent 类 |
| `backend/app/strategies/prosperity/coordinator.py` | 修改 | 集成 `_run_learning_agent()` Phase 1.5 |
| `backend/tests/test_prosperity_coordinator.py` | 修改 | 新增 Learning Agent 测试用例 |
