# Prosperity 知识库维护契约

> **v2.0** | LLM Agent 在编辑 wiki/ 下任何页面时必须遵守本契约。
>
> 本文件是 Prosperity 策略知识库的 **Single Source of Truth**。
> 所有 prompt 模板（learning / hypothesize / verify / counter / screening）的格式约束均派生自此文件。

---

## §1 假设页标准结构

每个 `wiki/hypotheses/{行业}-{标题}.md` 必须包含四章节：

### §1.1 假设
- 陈述（一句话）
- 推理链（A→B→C）
- 支撑信源（引用 raw/ 中的搜索结果，至少 2 个）
- 初始置信度：高/中/低

### §1.2 验证
- 多信源交叉验证结果
- 数据验证结果（引用 industry_metrics.py 输出）
- 反例搜索结果
- 验证状态：`✅ CONFIRMED` | `⚠️ PARTIAL` | `❌ DISPUTED` | `⚰️ OVERTURNED` | `🔍 UNVERIFIED` | `🚫 UNREACHABLE`

### §1.3 状态定义

| 状态 | 含义 | 级联 | 跟踪 | 例子 |
|------|------|:--:|:--:|------|
| `✅ CONFIRMED` | 多信源交叉验证一致，数据支撑成立 | 正常 | ✅ | 两条财报+行业报告都确认HBM出货量同比+300% |
| `⚠️ PARTIAL` | 部分证据支撑，但有模糊区/边界条件 | 正常 | ✅ | 一家公司扩产被财报确认，但另一家只有新闻稿没财报 |
| `❌ DISPUTED` | 证据矛盾或不充分，无法确认也无法推翻 | ❌ 不触发 | ✅ | AI需求数据支撑「存储景气」，但传统DRAM价格在跌 |
| `⚰️ OVERTURNED` | 反例证据明确推翻原始假设 | ⚠️ 触发下游 UNREACHABLE | ❌ | 假设「AI带动DRAM涨价」但Q2合约价实际环比-15% |
| `🔍 UNVERIFIED` | 无数据可验证（时间未到/数据不可得） | 正常 | ✅ | 「2027年核聚变成本将低于煤电」— 数据要2027才有 |
| `🚫 UNREACHABLE` | 上游假设被推翻，本条不可达 | — 被级联阻断 | ❌ | H1-3 被推翻 → 其下 H2-3/H3-3 全部 UNREACHABLE |

### §1.4 反推
- 对 OVERTURNED 的解释和推翻原因（DISPUTED 仅表示证据不足，不推翻）
- 对 PARTIAL 的边界修正
- 新产生的子假设

### §1.5 跟踪
- 需要持续关注的数据点
- 下次复核时间

---

## §2 原始资料只读原则

`raw/` 目录下的文件一旦写入，LLM 不得修改。
所有分析基于 raw/ 引用，不可凭空编造数据。

## §3 矛盾标注

被推翻的假设标注 `⚠️ OVERTURNED: {日期} — {推翻原因}`，不得删除。

---

## §4 产业链 YAML 结构

> 由 LearningAgent 产出 → 写入 `wiki/industries/{行业}.yaml`
> Prompt 模板: `learning_prompt.md` §8

### §4.1 顶层结构

```yaml
industry: 行业名称          # 必填
chain:                     # 必填 — 产业链环节
bottlenecks:               # 必填 — 全局瓶颈
supply_demand:             # 必填 — 供需格局
technology_paths:          # 必填 — 技术路径
tracking_indicators:       # 必填 — 跟踪指标
```

### §4.2 `chain.segments[]` — 产业链环节

| 字段 | 类型 | 枚举/说明 | Agent 消费方 |
|------|------|----------|-------------|
| `id` | string | 英文ID，下划线分隔，如 `upstream_silicon` | H/V/C |
| `name` | string | 中文名，如 `上游硅料` | H/V/C/S |
| `position` | enum | `upstream` / `mid` / `downstream` | H/V/C/S |
| `description` | string | 环节角色描述 | H/V/C |
| `bottleneck.level` | enum | `low` / `medium` / `high` / `critical` | **全 4 Agent** |
| `bottleneck.detail` | string | 瓶颈描述 | V/C |
| `bottleneck.localization_rate` | int | 国产化率粗估 %（如 `30`） | V/C/S |
| `representative_companies[]` | string[] | 上市公司名称（只列搜索素材中出现的） | H/S |

### §4.3 `bottlenecks[]` — 全局瓶颈

| 字段 | 类型 | 说明 | Agent 消费方 |
|------|------|------|-------------|
| `segment_id` | string | 对应 `chain.segments[].id` | V/C |
| `severity` | enum | `low` / `medium` / `high` / `critical` | V/C |
| `description` | string | 瓶颈描述 | V/C |

### §4.4 `supply_demand` — 供需格局

| 字段 | 类型 | 说明 | Agent 消费方 |
|------|------|------|-------------|
| `overall_judgment` | string | 如 `严重供需短缺` / `供需平衡` / `供给过剩` | H/V/C |
| `demand_drivers[].driver` | string | 需求驱动力名称 | H/V |
| `demand_drivers[].certainty` | enum | `low` / `medium` / `high` | H/V |
| `demand_drivers[].window` | string | 时间窗口，如 `2026-2028` | H |
| `supply_constraints[].constraint` | string | 供给约束名称 | V/C |
| `supply_constraints[].detail` | string | 约束详情 | V/C |

### §4.5 `technology_paths[]` — 技术路径

| 字段 | 类型 | 说明 | Agent 消费方 |
|------|------|------|-------------|
| `name` | string | 技术路径名称 | V/C |
| `maturity` | enum | `科学验证` / `工程验证` / `商业示范` / `规模化` | V/C |
| `representative` | string | 代表公司/项目 | V |

### §4.6 `tracking_indicators[]` — 跟踪指标

| 字段 | 类型 | 说明 | Agent 消费方 |
|------|------|------|-------------|
| `name` | string | 指标名称 | V |
| `frequency` | enum | `daily` / `weekly` / `monthly` / `quarterly` | V |
| `meaning` | string | 指标变化代表什么 | V |

---

## §5 Wiki-Centric Agent 消费架构

> v1.0.0+ 的核心设计：产业链 YAML 作为跨 Agent 的共享知识底座。

```
LearningAgent（Producer）
  └→ wiki/industries/{行业}.yaml  ← chain_model
       ├→ HypothesizeAgent  — 假设锚定到产业链环节 + 代表公司
       ├→ VerifyAgent       — Q1环节对口 / Q2指标对齐 / Q3瓶颈校准 / Q4情感联动 / Q5 chain_fit
       ├→ CounterAgent      — 级联裁决感知瓶颈/供需/技术 → 推翻门槛+disputed分类+sentiment校准
       └→ ScreeningAgent    — Stage1方向匹配：代表公司锚定 + 环节分类 + 瓶颈校准
```

### §5.1 各 Agent 消费的 YAML 路径细则

| Agent | 消费路径 | 用途 |
|-------|---------|------|
| **HypothesizeAgent** | `chain.segments[*]` / `supply_demand.*` / `bottlenecks[*]` / `technology_paths[*]` / `tracking_indicators[*]` | 3 个 prompt builder（单轮/骨架/填充）注入产业链上下文 |
| **VerifyAgent** | `chain.segments[*]` / `bottlenecks[*]` / `supply_demand.*` / `technology_paths[*]` / `tracking_indicators[*]` | Q1 环节对口过滤信源 / Q2 指标方向对齐 / Q3 瓶颈校准反例 / Q4 情感联动瓶颈 / Q5 整体链适配度 |
| **CounterAgent** | `chain.segments[*]` / `bottlenecks[*]` / `supply_demand.*` / `technology_paths[*]` | 级联裁决：推翻门槛（瓶颈高→严） / disputed 分类（供需短缺→程度变化 vs 产能过剩→方向反转） / sentiment 校准 |
| **ScreeningAgent** | `chain.segments[*]` / `bottlenecks[*]` | Stage1 方向匹配：代表公司正例锚点 / 环节描述股票分类 / 瓶颈校准规则 |

### §5.2 chain_model=None 降级

首次运行（LearningAgent 尚未产出 YAML）时 `chain_model=None`：
- 所有 Agent 的 `_format_chain_context()` 返回空字符串
- Prompt 中的 `{chain_context}` 替换为空
- 行为退化为 v0.x 链无感知模式，零破坏

---

## §6 文件布局

```
data/prosperity/
├── SCHEMA.md                     ← 本文件（唯一宪法）
├── raw/{行业}/                   ← 搜索原始素材（只读）
│   ├── 01_search_{date}_s{session}.yaml
│   └── stock_pool.yaml
├── wiki/
│   ├── hypotheses/{行业}-*.md    ← 假设页（§1 结构）
│   ├── industries/{行业}.md      ← 产业图谱（Markdown）
│   ├── industries/{行业}.yaml    ← 产业链结构化数据（§4 结构）
│   └── synthesis/*.md            ← 合成报告
└── tracking/watchlist/{行业}.yaml ← 巡检指标
```
