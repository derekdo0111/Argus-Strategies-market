# LLM 确定性验证 + 纯度分去 LLM 化 — 设计 Spec

> 版本: v1.0 | 日期: 2026-07-04 | 状态: 设计中

## 1. 动机

### 问题根因

高景气策略管道存在系统性 LLM 非确定性，造成两次运行同一行业结果不同：

| 症状 | 根因 | 严重度 |
|------|------|--------|
| 验证结果跳动 (confirmed ↔ partial) | LLM 一次调用输出 status，全局判断黑箱 | P0 |
| 纯度分剧烈跳动 (寒武纪 1% → 25%) | LLM 一次性判断所有股票业务线匹配 | P0 |

根因非单一 bug，而是全链路设计假设了「temperature=0 时 LLM 输出确定」——但 DeepSeek 等 LLM 在 temperature=0 时仍非完全确定（GPU 浮点非确定性 + Tavily 搜索变化）。

### 设计原则

**压缩 LLM 自由度**：把「一次性全局判断」拆为「N 个原子化事实提取 + 确定性规则合成」。

LLM 不再做综合判断者（裁判），降级为信息提取者（记分员）。判断权交给确定性代码。

---

## 2. Layer 1：VerifyAgent 验证原子化

**改 2 个文件**：`verify_prompt.md`、`verify_agent.py`

### 2.1 核心变化

| | 现状 | 改造后 |
|---|---|---|
| LLM 输出什么 | `status: "confirmed"/"partial"/...` | `source_count: 3`, `data_alignment: "支持"`, `counter_conflict: "no"` |
| status 谁说了算 | LLM | 代码 `_synthesize_status()` |
| 为什么稳 | —— | 每个子问题边界极窄（计数/方向/是否冲突），答案几乎不可能漂移 |

### 2.2 Prompt 改造

`verify_prompt.md` 中：

**删除**：输出格式中的 `"status"` 字段、`"confidence"` 字段（也由代码合成）。

**新增**：三个事实性子问题，LLM 逐条回答：

```
Q1 source_count: 搜索素材中有几个独立信源明确提供了支持该陈述的具体数据或直接陈述？
   - 只计数直接陈述该事实的信源，不算间接推理
   - 回答一个整数: 3 / 2 / 1 / 0

Q2 data_alignment: Tushare 行业财务数据的方向是否与该假设一致？
   - 营收增速、净利增速、资本支出增速大多数为正 → "支持"
   - 部分为正部分为负 → "部分支持"
   - 大多为负 → "不支持"
   - 无相关数据 → "无相关数据"

Q3 counter_conflict: 反例搜索证据中，是否有直接推翻该陈述的证据？
   - 必须是直接推翻，间接怀疑不算
   - 回答: "yes" 或 "no"
```

**保留字段**：`reason`、`corrected_statement`、`causality_strength`、`causality_note` 保持不变（这些是描述性字段，LLM 擅长且方差低）。

### 2.3 新输出格式

```json
{
  "chain_label": "链路1",
  "hypotheses": [
    {
      "id": "H0-1",
      "source_count": 2,
      "data_alignment": "支持",
      "counter_conflict": "no",
      "reason": "信源 [1] 明确提到日均Token调用突破30万亿...",
      "corrected_statement": null,
      "causality_strength": "strong",
      "causality_note": "上游L0成立且搜索素材数据明确支撑"
    }
  ]
}
```

### 2.4 确定性合成规则

在 `verify_agent.py` 新增 `_synthesize_status()` 函数：

```python
def _synthesize_status(source_count: int, data_alignment: str,
                       counter_conflict: str) -> str:
    """从 LLM 事实输出合成假设状态。纯 Python 确定性函数。"""
    
    # 优先级 1: 反例直接推翻 → disputed
    if counter_conflict == "yes":
        return "disputed"
    
    # 优先级 2: 零信源 → 完全无法验证
    if source_count == 0:
        return "unverified"
    
    # 优先级 3: 信源不足或数据不支持 → partial
    if source_count == 1 or data_alignment == "不支持":
        return "partial"
    
    # 优先级 4: 2+ 信源 + 数据方向支持 → confirmed
    if source_count >= 2 and data_alignment in ("支持", "部分支持"):
        return "confirmed"
    
    # 兜底
    return "partial"
```

### 2.5 置信度合成（新增）

`confidence` 字段也改为代码合成，不依赖 LLM 判断：

```python
def _synthesize_confidence(source_count: int, data_alignment: str,
                           counter_conflict: str) -> str:
    """从事实输出合成置信度"""
    if counter_conflict == "yes":
        return "high"  # 被推翻的置信度反而高——证据非常确定
    
    if source_count >= 3 and data_alignment == "支持":
        return "high"
    if source_count >= 2 and data_alignment in ("支持", "部分支持"):
        return "high"
    if source_count >= 1 and data_alignment in ("支持", "部分支持"):
        return "medium"
    if source_count >= 1:
        return "medium"
    return "low"
```

### 2.6 解析改造

`_parse_verification_result()` 中，LLM 返回后回填 `status` 和 `confidence`：

```python
for vh in verified_hyps:
    sc = vh.get("source_count", 0)
    da = vh.get("data_alignment", "无相关数据")
    cc = vh.get("counter_conflict", "no")
    
    # 确定性合成
    vh["status"] = _synthesize_status(sc, da, cc)
    vh["confidence"] = _synthesize_confidence(sc, da, cc)
```

### 2.7 边界条件表（16 种关键组合）

| source_count | data_alignment | counter_conflict | → status | confidence |
|---|---|---|---|---|
| 3 | 支持 | no | confirmed | high |
| 2 | 支持 | no | confirmed | high |
| 2 | 部分支持 | no | confirmed | high |
| 1 | 支持 | no | partial | medium |
| 0 | 支持 | no | unverified | low |
| 0 | 无相关数据 | no | unverified | low |
| 1 | 不支持 | no | partial | medium |
| 2 | 不支持 | no | partial | high |
| 3 | 支持 | yes | disputed | high |
| 0 | 无相关数据 | yes | disputed | high |
| 2 | 部分支持 | yes | disputed | high |
| 1 | 无相关数据 | no | partial | medium |
| 0 | 不支持 | no | unverified | low |
| 2 | 无相关数据 | no | confirmed (≥2信源+兜底) | high |
| 3 | 部分支持 | no | confirmed | high |
| 1 | 部分支持 | no | partial | medium |

---

## 3. Layer 2：纯度分去 LLM 化

**改 1 个文件**：`purity_scorer.py`

### 3.1 核心变化

| | 现状 | 改造后 |
|---|---|---|
| 业务匹配怎么做 | LLM 一次判断所有股票 | embedding 余弦相似度 |
| 为什么稳 | —— | 同样输入永远同样输出（确定性矩阵运算） |
| 寒武纪 | LLM 两次判断不同 → 1% vs 25% | 永远相同（embedding 向量不变） |
| 成本 | 1 次 LLM 调用 ~$0.01 | ~$0.0001（便宜 100 倍） |

### 3.2 技术方案

使用 `text-embedding-3-small` (OpenAI) 或本地 `bge-large-zh` 模型：

```python
def match_business_to_l3_embedding(
    industry_name: str,
    ts_codes: list[str],
    name_map: dict[str, str],
    mainbz_data: dict[str, list[dict]],
    hypotheses: list[dict],
    search_result: dict | None = None,
) -> dict[str, dict]:
    """Embedding 确定性匹配：每股业务线 → L3 方向"""
    
    # 1. 提取 L3 投资含义
    l3_hyps = _extract_l3_hypotheses(hypotheses)
    l3_texts = {
        h["id"]: h.get("investment_implication", "") or h.get("statement", "")
        for h in l3_hyps
    }
    
    # 2. 计算所有 L3 方向 embedding
    l3_embeddings = {}
    for l3_id, text in l3_texts.items():
        l3_embeddings[l3_id] = get_embedding(text)
    
    # 3. 对每只股票每条业务线，计算与每个 L3 方向的相似度
    result = {}
    for ts_code in ts_codes:
        items = mainbz_data.get(ts_code, [])
        related_items = []
        matched_l3 = None
        best_score = 0.0
        
        for item in items:
            biz_emb = get_embedding(item["bz_item"])
            for l3_id, l3_emb in l3_embeddings.items():
                score = cosine_similarity(biz_emb, l3_emb)
                if score > 0.75 and score > best_score:
                    best_score = score
                    matched_l3 = l3_id
                    related_items.append(item["bz_item"])
        
        result[ts_code] = {
            "related_items": related_items,
            "matched_l3": matched_l3,
        }
    
    return result
```

### 3.3 Embedding API 选择

推荐 `text-embedding-3-small` (OpenAI)，理由：
- 中英文双语支持好
- 价格 $0.02/1M tokens，一个行业 200 只股票 ≈ 2000 条业务线 ≈ ~5K tokens ≈ $0.0001
- 完全确定性（同输入同输出）

备选：本地 `bge-large-zh-v1.5` (BAAI)，通过 `sentence-transformers` 加载，零 API 成本但需要 ~1.3GB 模型下载。

### 3.4 降级策略

```python
try:
    from openai import OpenAI
    client = OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_API_BASE)
except ImportError:
    # 无 openai SDK → 回退 keyword
    return _keyword_fallback(ts_codes, mainbz_data, hypotheses)
```

### 3.5 保留搜索上下文增强

embedding 匹配已具备精度优势，但搜索素材中的公司-业务映射关系仍有用——在 embedding score 接近阈值（0.72~0.78）时作为辅助信号提升匹配。

这步可以通过在 `search_result` 中提取公司-业务关系对，与 embedding 结果做 OR 合并实现。

---

## 4. 测试计划

### 4.1 `_synthesize_status` 16 个组合测试

```python
class TestV019DeterministicVerification:
    """v0.19: LLM 确定性验证"""
    
    @pytest.mark.parametrize("sc,da,cc,expected", [
        (3, "支持", "no", "confirmed"),
        (2, "支持", "no", "confirmed"),
        (2, "部分支持", "no", "confirmed"),
        (1, "支持", "no", "partial"),
        (0, "支持", "no", "unverified"),
        (0, "无相关数据", "no", "unverified"),
        (1, "不支持", "no", "partial"),
        (2, "不支持", "no", "partial"),
        (3, "支持", "yes", "disputed"),
        (0, "无相关数据", "yes", "disputed"),
        (2, "部分支持", "yes", "disputed"),
        (1, "无相关数据", "no", "partial"),
        (0, "不支持", "no", "unverified"),
        (2, "无相关数据", "no", "confirmed"),  # ≥2信源 + 兜底
        (3, "部分支持", "no", "confirmed"),
        (1, "部分支持", "no", "partial"),
    ])
    def test_synthesize_status(self, sc, da, cc, expected):
        from app.strategies.prosperity.agents.verify_agent import _synthesize_status
        assert _synthesize_status(sc, da, cc) == expected
```

### 4.2 `_synthesize_confidence` 测试

10 个典型组合，验证 high/medium/low 三种输出。

### 4.3 纯度分 embedding 确定性测试

```python
def test_embedding_matching_deterministic(self):
    """同样输入两次 → 同样输出"""
    mainbz_data = { ... }  # 寒武纪真实数据
    result1 = match_business_to_l3_embedding(...)
    result2 = match_business_to_l3_embedding(...)
    assert result1 == result2  # 逐字段比对
```

### 4.4 回归：管道端到端

现有 152 个测试全部保留，新增 ~30 个测试。

---

## 5. 改动文件清单

| 文件 | 改动类型 | 行数估算 |
|------|---------|----------|
| `rules/prosperity/prompts/verify_prompt.md` | 重写输出格式 | ~50 行变更 |
| `agents/verify_agent.py` | 新增 `_synthesize_status()` + `_synthesize_confidence()` + 解析改造 | ~+60 行 |
| `tools/purity_scorer.py` | 新增 `match_business_to_l3_embedding()` + embedding 调用 | ~+80 行 |
| `tests/test_prosperity_coordinator.py` | 新增 TestV019DeterministicVerification 类 | ~+80 行 |
| `CHANGELOG.md` | v0.19.0 条目 | ~+30 行 |
| `pyproject.toml` | 版本 + openai 依赖 | +1 行 |
| `requirements.txt` | openai 依赖 | +1 行 |

**不改动**：coordinator.py、其他 Agent、模型层（Status 枚举不变）。

---

## 6. 版本号

v0.18.9 → v0.19.0 (minor bump：确定性验证是管道核心逻辑变更)。

---

## 7. 设计决策

1. **不冻结 Search 输入** — Search 冻结（Layer 1 输入冻结）单独评估。先做 验证原子化 + 纯度去 LLM，这两块与 Search 独立，不冲突。
2. **保留 causality_strength 给 LLM** — 因果判断是 LLM 的强项（语义推理），且方差低（strong/moderate/weak 三档区分清晰），不做原子化。
3. **embedding 阈值 0.75** — 基于经验，可在 .env 配置。业务线名称与方向关键词的语义距离通常在这个范围。
4. **_synthesize_confidence 依赖前三个变量** — 不新增 LLM 调用，置信度完全从已验证的中间变量合成。
