# 高景气策略 v0.18.3 — 选股信号质量感知融合

> 版本: v0.18.3 | 日期: 2026-07-02 | 状态: 设计已完成
>
> 产出流程: brainstorming → 缺陷诊断（8个结构性问题）→ 方案选型（B：信号质量感知）→ 本 Spec
>
> 前置 Spec: `2026-07-01-prosperity-strategy-v16-enhancement.md`（v0.16 ScreeningAgent 引入）

---

## 0. 问题概述

### 背景

ScreeningAgent 的两个 LLM 调用（方向匹配 Stage 1 + 业务纯度打分 Stage 2）存在 **信息割裂**：

```
Stage 1（有搜索上下文）："哈焊华通=核聚变特种焊接 → direction=0.85"
Stage 2（无搜索上下文）："Tushare 分类只有'焊接材料'→ 无法确认是核聚变相关 → purity=0"

搜索素材已知的信息不会被传递给 Stage 2。
```

同时，三个结构性问题彼此叠加放大：
- **概念构建入口过松**：雪人集团（制冷）、王子新材（包装）等非相关股票也进入股池
- **H3-3 规避方向无负向信号**：纯概念炒作匹配到 H3-3 后没有被惩罚
- **排名只按纯度**：purity=0 的 22 只股票（65%）随机排列，方向置信度被完全丢弃

### 改进原则

1. **不改变两个 LLM 的分工**：方向匹配 vs 纯度打分的职责分离是正确的
2. **只改融合阶段的信任分配**：让定性信号（direction）在定量信号（purity）不足时自动补位
3. **对成熟行业零影响**：线缆、白酒等 purity 高的行业排名不受任何影响
4. **信息共享靠 prompt 增强**：不引入新 LLM 调用，只在已有 prompt 中注入搜索上下文

---

## 1. 改进总览

| # | 改动 | 影响 | 解决什么问题 |
|----|------|------|-----------|
| 1 | 概念构建加相关性门 | `concept_builder.py` | Q1：非相关股票在入口过滤 |
| 2 | L3 方向加极性标注 | `screening_agent.py` Stage 1 prompt | Q7：H3-3 负向信号 |
| 3 | 搜索上下文注入纯度打分 | `purity_scorer.py` prompt + 新函数 | Q3/Q4：信息割裂 |
| 4 | Tuple sort 排名 + 硬过滤 | `screening_agent.py` Stage 4 | Q2/Q5/Q6：零区有序、垃圾过滤 |

四个改动相互独立，可逐个部署、逐个回滚。

---

## 2. 详细设计

### 2.1 概念构建相关性门 — `concept_builder.py`

#### 改动点

LLM 提取 prompt 新增 `relevant` 字段：

```json
[
  {"code": "688122.SH", "name": "西部超导", "chain": "上游-超导材料", "relevant": true},
  {"code": "002639.SZ", "name": "雪人集团", "chain": "中游-核心设备", "relevant": false}
]
```

判断规则：
- `relevant: true` → 搜索结果明确描述该公司在行业中的业务、产品、合同或技术
- `relevant: false` → 仅因市场行情（涨停/跌幅）、资金流向、指数成分被提及，无具体业务描述

执行：`_cross_validate` 之后过滤掉 `relevant: false` 的股票。

#### 影响

- 无额外 LLM 调用（prompt 指令增加，不增加 token 轮数）
- 旧缓存不受影响（默认 `relevant: true`）
- 依赖旧缓存的概念板块需手动删除 YAML 文件触发重建

#### 回滚

删除 `_cross_validate` 后的 `relevant` 过滤行即可恢复旧行为。

---

### 2.2 L3 极性标注 — `screening_agent.py` Stage 1

#### 改动点

**新函数 `_detect_polarity()`**：判断 L3 假设的极性
- 优先读假设的 `polarity` 字段（未来 HypotheziseAgent 可输出）
- 回退：关键词检测（"规避""排除""炒作""概念炒作"）

**L3 方向文本**：在 prompt 中加 polarity tag：

```
**H3-1** [✅ 推荐方向]: 聚焦超导材料龙头
**H3-2** [✅ 推荐方向]: 优选设备与工程服务标的
**H3-3** [⚠️ 规避方向]: 规避纯概念炒作暴露
```

**判断规则更新**：

```diff
- 股票与 L3 排除方向匹配 → 0.0~0.3
+ 股票匹配到「⚠️ 规避方向」→ score: 0.0~0.2（负向信号，越低越应规避）
```

#### 影响

- 匹配到 H3-3 的股票方向分从 0.0~0.3 降为 0.0~0.2，在零区排名中更靠后
- 正向方向（H3-1/H3-2）的匹配评分不变

---

### 2.3 搜索上下文注入纯度打分 — `purity_scorer.py`

#### 改动点

**新函数 `_build_search_context_for_purity()`**：

```python
def _build_search_context_for_purity(search_result, name_map) -> str:
    """从搜索素材中提取与成分股相关的上下文片段
    
    遍历搜索素材，找到提到每只股票名称的段落
    截取股票名前后各 30-40 字的上下文
    去重后注入 prompt
    """
```

**Prompt 新增**：

```diff
+## 搜索素材中的相关公司信息（帮你判断业务线的实际用途）
+- 「哈焊华通」: ...哈焊华通解决特殊焊接难题——订单背后...
+- 「合锻智能」: ...合锻智能为BEST提供重型压力机...

判断规则：
...
+- 业务线名称虽不直接相关，但【搜索素材】中明确描述了该公司的相关业务 → 匹配
```
#### 影响

- 使 LLM 能在 Tushare 分类名（"焊接材料"）和实际用途（核聚变特种焊接）之间做语义跳跃
- 搜索素材中从未被提到的公司不受影响（无 context snippet → 仍靠 Tushare 分类名匹配）
- 函数是纯文本处理（O(n)），不调 LLM

---

### 2.4 Tuple sort 排名 + 硬过滤 — `screening_agent.py` Stage 4

#### 改动点

**排名公式**：

```python
# 旧
stock_pool.sort(key=lambda x: x["purity_score"], reverse=True)

# 新
stock_pool.sort(key=lambda x: (x["purity_score"], x["direction_score"]), reverse=True)
```

**硬过滤门**：

```python
stock_pool = [
    s for s in stock_pool
    if not (s.get("matched_l3") is None and s["purity_score"] == 0)
]
```

#### 排名原则

```
purity > 0 → 按纯度排（物理意义优先）
purity = 0 + direction > 0 → 同一零区内按 direction 排（打破随机）
matched_l3 = null + purity = 0 → 完全无关，剔除
```

#### 对可控核聚变的效果

```
当前（purity 单键）：
  排名 13~34：随机排列（22 只纯度=0 的股票）

新（tuple sort）：
  排名 1~12：纯度 > 0（不变，有数据支撑的股票不受影响）
  排名 13~22：纯度=0 direction > 0 → 有序排列
    13. 哈焊华通  purity=0  dir=0.85  ← 搜索明确确认
    14. 联创光电  purity=0  dir=0.60
    23~34：硬过滤移除（matched_l3=null + purity=0）
```

---

## 3. 改动文件清单

| 文件 | 改动量 | 改动内容 |
|------|:--:|---------|
| `backend/app/strategies/prosperity/tools/concept_builder.py` | ~30 行 | EXTRACTION_PROMPT 加 relevant 字段，过滤逻辑 |
| `backend/app/strategies/prosperity/agents/screening_agent.py` | ~25 行 | `_detect_polarity()` 函数、极性 tag、tuple sort、硬过滤 |
| `backend/app/strategies/prosperity/tools/purity_scorer.py` | ~50 行 | `_detect_polarity()` 函数、`_build_search_context_for_purity()`、prompt 注入 |
| `CHANGELOG.md` | ~15 行 | 版本记录 |
| `pyproject.toml` | 1 行 | v0.9.6 → v0.9.7 |

**不修改**：
- 两个 LLM 的调用逻辑（不需要合并 Stage 1/2）
- coordinator.py（管道不变）
- 测试文件（若新增测试需评估）

---

## 4. 对成熟行业的影响验证

| 行业 | 特征 | 影响 |
|------|------|------|
| 普通制造/有线缆 | purity > 0 股票占比高 | **零影响** — tuple sort 主键 purity 不变，direction 在零区才生效 |
| 成熟新兴（半导体设备） | 大部分 purity > 0 | **极小影响** — 零区内 direction 排序更合理 |
| 前沿新兴（固态电池/低空经济） | 类似核聚变 purity=0 比例高 | **正向影响** — 自动切换模式 |

自动判断的数据质量感知不依赖人工指定，完全由筛选结果自动触发。

---

## 5. 失败场景与兜底

| 场景 | 兜底 |
|------|------|
| 搜索素材为空/失败 | `_build_search_context_for_purity` 返回空字符串，prompt 无搜索上下文段 → 回退到旧行为 |
| LLM 不遵守 polarity 规则 | 极性 tag 是 prompt 提示而非强制，LLM 可忽略。H3-3 匹配后 stage4 通过 direction 自然排低 |
| 所有股票 matched_l3=null | 硬过滤移除所有股票保 → 返回空股池（合理：概念板块无相关标的） |
| 概念缓存旧字段 | 旧缓存无 `relevant` 字段 → 默认 True，不删除 |

---

## 6. 设计决策记录

1. **不合并 Stage 1/2**：方向匹配回答"是不是"、纯度打分回答"有多少"，两个问题不同层，分开是正确分工。问题在融合阶段而非分工阶段。

2. **不引入新 LLM 调用**：概念构建加 irrelevant 过滤是在已有 prompt 加指令，不是新调用。搜索上下文提取是纯文本处理。

3. **Tuple sort 而非加权融合**：purity 有物理意义（实际收入占比），direction 是 LLM 置信度。加权加法会混淆两类信号，tuple sort 保持 purity 的优先性。

4. **硬过滤而非软**：`matched_l3=null + purity=0` 意味着"LLM 不认为它属于任何方向 + Tushare 数据也找不到相关业务"，两个证据同时证伪，应该彻底排除而非排在末尾。

5. **极性关键词检测回退**：当前假设的 `polarity` 字段尚未内置命中，用关键词回退（"规避"等）以避免依赖 HypothesizeAgent 先行修改。
