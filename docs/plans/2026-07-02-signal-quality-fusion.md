# 选股信号质量感知融合 — 实施计划

> 对应 Spec: `docs/specs/2026-07-02-signal-quality-fusion.md`
> 日期: 2026-07-02 | 当前版本: v0.18.2 → v0.18.3

---

## 执行步骤

### 步骤 1 — `concept_builder.py` 相关性门

**文件**: `backend/app/strategies/prosperity/tools/concept_builder.py`

**改动**:
1. EXTRACTION_PROMPT 新增 `relevant` 字段 + 判断规则 + 示例
2. `_try_parse_json()` 解析时保留 relevant 字段
3. `_extract_valid_json_objects()` 正则模式扩展捕获 relevant
4. `_cross_validate()` 三处返回路径在 dict 中保留 `relevant` 字段
5. `search_concept_stocks()` 在 `_cross_validate` 后过滤 `relevant=false`

**验证**: 旧缓存自动兼容（`default true`），需删除 YAML 缓存触发重建

---

### 步骤 2 — `screening_agent.py` Stage 1 极性标注

**文件**: `backend/app/strategies/prosperity/agents/screening_agent.py`

**改动**:
1. 新增模块级函数 `_detect_polarity()` — 关键词检测（"规避""炒作"等）
2. L3 方向文本构建改为带极性 tag（✅推荐/⚠️规避）
3. prompt 判断规则更新：规避方向 score 0.0~0.2

---

### 步骤 3 — `screening_agent.py` Stage 4 排名优化

**文件**: `backend/app/strategies/prosperity/agents/screening_agent.py`

**改动**:
1. 增加硬过滤：`matched_l3=null AND purity=0` 的股票从股池移除
2. 排序改为 tuple sort：`(purity_score, direction_score)`

---

### 步骤 4 — `purity_scorer.py` 搜索上下文注入

**文件**: `backend/app/strategies/prosperity/tools/purity_scorer.py`

**改动**:
1. 新增模块级函数 `_detect_polarity()`（与 screening_agent 一致）
2. 新增函数 `_build_search_context_for_purity()` — 从搜索素材提取公司上下文
3. `match_business_to_l3()` 增加 `search_result` 参数
4. prompt 新增「搜索素材中的相关公司信息」段落
5. prompt 判断规则新增"搜索素材可作为匹配依据"
6. `screening_agent.py` 的 `_compute_purity()` 透传 `search_result`

---

### 步骤 5 — 版本号 + CHANGELOG

**文件**: `backend/pyproject.toml`, `CHANGELOG.md`

**改动**:
- `pyproject.toml`: `version = "0.9.6"` → `"0.9.7"`
- `CHANGELOG.md`: 追加 v0.18.3 章节

---

### 步骤 6 — 测试验证

```bash
cd backend
pytest tests\ -v
```

确认所有已有测试通过后结束。

---

## 进度追踪

| 步骤 | 状态 | 预期行数 |
|------|------|:--:|
| 1. concept_builder 相关性门 | 已完成 | ~30 |
| 2. screening_agent 极性标注 | 已完成 | ~15 |
| 3. screening_agent Stage 4 排名 | 已完成 | ~10 |
| 4. purity_scorer 搜索上下文 | 待实现 | ~50 |
| 5. 版本号 + CHANGELOG | 待实现 | ~15 |
| 6. 测试验证 | 待运行 | — |
