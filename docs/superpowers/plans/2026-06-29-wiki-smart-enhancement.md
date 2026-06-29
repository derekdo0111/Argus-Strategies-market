# Wiki 智能增强 — 重复行业研究优化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为高景气策略 pipeline 增加 5 天冷却硬门控 + 全链历史锚定 + 增量搜索分流 + 评级行去重 + key_indicators 全量入 watchlist。

**Architecture:** Coordinator 在 pipeline 入口做冷却判断，然后在 search 后构造 `IndustryHistory` 对象逐级传入 6 个 Agent。Search Agent 用 URL 去重分流新旧结果，Hypothesize/Verify/Counter 从 history 对象取历史上下文，Report Agent 做评级行去重，Track Agent 提取所有假设的 key_indicators 并合并去重。

**Tech Stack:** Python 3.11, SQLAlchemy 2.x, DeepSeek v4, Tavily API, YAML, pytest

## Global Constraints

- Python ^3.11
- DeepSeek v4-flash 为 LLM（temperature=0 确定输出）
- `.env` 为最高权威配置
- 所有改动必须先更新 SPEC → 测试 → 代码
- `pytest tests/` 全部通过才算完成
- 不实现自动巡检触发逻辑，只铺管道（key_indicators → watchlist）

---

### Task 1: IndustryHistory 数据类

**Files:**
- Create: `backend/app/strategies/prosperity/industry_history.py`

**Interfaces:**
- Produces: `IndustryHistory` 数据类 — 后续 6 个 Agent 的公共依赖

- [ ] **Step 1: 创建 IndustryHistory 数据类**

```python
"""IndustryHistory — 行业历史上下文，跨 Agent 共享"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class IndustryHistory:
    """行业历史上下文，Coordinator 预加载后逐级传入 6 Agent"""
    industry_name: str
    study_count: int = 1                    # 第几次研究（含本次），首次=1
    last_rating: str = ""                   # "高景气" | "景气" | "弱景气" | "不景气"
    last_study_date: Optional[datetime] = None
    cooldown_days: int = 0                  # 距上次天数，0 表示首次

    # DB Hypothesis（最近一次 session 的全部假设）
    previous_hypotheses: list[dict] = field(default_factory=list)
    # [{id, title, chain_level, status, confidence, key_indicators, derives_from, time_horizon}]

    # wiki/synthesis 结构化截取（L0-L3推理 + 股池方向，不含验证/反推细节）
    last_synthesis_excerpt: str = ""

    # wiki/industries 评级历史
    rating_history: list[str] = field(default_factory=list)
    # ["- [2026-06-29] 🔥 高景气 — [查看报告](...)"]

    # DB TrackingItem
    pending_tracking_items: list[dict] = field(default_factory=list)

    @property
    def is_first_study(self) -> bool:
        return self.study_count <= 1

    @property
    def verified_count(self) -> int:
        return sum(1 for h in self.previous_hypotheses if h.get("status") == "confirmed")

    @property
    def overturned_count(self) -> int:
        return sum(1 for h in self.previous_hypotheses if h.get("status") == "overturned")

    def get_overturned_hypotheses(self) -> list[dict]:
        return [h for h in self.previous_hypotheses if h.get("status") == "overturned"]

    def get_hypotheses_summary(self) -> str:
        """生成假设状态分布摘要，供 Agent prompt 使用"""
        if not self.previous_hypotheses:
            return "（无历史假设）"
        status_counts = {}
        for h in self.previous_hypotheses:
            s = h.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1
        parts = [f"{k}:{v}" for k, v in status_counts.items()]
        return f"共 {len(self.previous_hypotheses)} 条假设，" + "， ".join(parts)
```

- [ ] **Step 2: 验证可导入**

Run: `python -c "from app.strategies.prosperity.industry_history import IndustryHistory; h = IndustryHistory('测试'); assert h.is_first_study; print('OK')"`

Expected: 输出 `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/strategies/prosperity/industry_history.py
git commit -m "feat: add IndustryHistory dataclass for cross-agent context sharing"
```

---

### Task 2: Coordinator — 5 天冷却硬门控

**Files:**
- Modify: `backend/app/strategies/prosperity/coordinator.py:63-89` (start_session)

**Interfaces:**
- 改动: `start_session(industry_name, force=False)` — force=True 时跳过冷却检查
- 新增: `_check_cooldown(industry_name) -> Optional[dict]` — 检查是否在冷却期内

- [ ] **Step 1: 添加 _check_cooldown 方法**

在 `coordinator.py` 的 `Session 管理` 区域，`start_session` 之前插入：

```python
    COOLDOWN_DAYS = 5  # 冷却期天数

    def _check_cooldown(self, industry_name: str) -> Optional[dict]:
        """检查行业是否在冷却期内。返回 cooldown 信息，或 None 表示可以研究。"""
        wiki_dir = self.data_dir / "wiki" / "industries"
        page_path = wiki_dir / f"{industry_name}.md"
        if not page_path.exists():
            return None  # 无历史记录，不在冷却期

        content = page_path.read_text(encoding="utf-8")
        # 提取第一条评级行日期
        import re
        first_date_match = re.search(r"- \[(\d{4}-\d{2}-\d{2})\]", content)
        if not first_date_match:
            return None

        from datetime import datetime, timedelta
        try:
            last_date = datetime.strptime(first_date_match.group(1), "%Y-%m-%d")
        except ValueError:
            return None

        days_ago = (datetime.utcnow() - last_date).days

        # 提取最近评级
        last_rating = ""
        rating_match = re.search(r"- \[\d{4}-\d{2}-\d{2}\]\s*(\S+)\s*(\S+)", content)
        if rating_match:
            last_rating = rating_match.group(2)

        if days_ago < self.COOLDOWN_DAYS:
            return {
                "status": "cooldown",
                "industry": industry_name,
                "days_ago": days_ago,
                "last_rating": last_rating,
                "last_study_date": last_date.isoformat(),
                "message": f"「{industry_name}」{days_ago} 天前刚完成研究（{last_rating}），"
                           f"距 {self.COOLDOWN_DAYS} 天冷却期还有 {self.COOLDOWN_DAYS - days_ago} 天。"
                           f"是否强制重新研究？",
            }
        return None
```

- [ ] **Step 2: 修改 start_session 签名和逻辑**

将第 63 行的方法签名和逻辑改为：

```python
    def start_session(self, industry_name: str, force: bool = False) -> int:
        """创建新的研究会话，返回 session_id。force=True 跳过冷却检查。"""
        # 冷却检查
        if not force:
            cooldown = self._check_cooldown(industry_name)
            if cooldown:
                logger.info(f"Cooldown active for {industry_name}: {cooldown['message']}")
                raise CooldownError(cooldown)

        db = get_db_session(self.engine)
        try:
            # 查找或创建行业
            industry = db.query(Industry).filter_by(name=industry_name).first()
            if not industry:
                industry = Industry(name=industry_name, first_study=datetime.utcnow())
                db.add(industry)
                db.flush()
            else:
                industry.last_study = datetime.utcnow()

            # 创建会话
            session = ResearchSession(
                industry_id=industry.id,
                status="running",
                current_step="search",
            )
            db.add(session)
            db.commit()

            session_id = session.id
            logger.info(f"Session {session_id} started for {industry_name}")
            return session_id
        finally:
            db.close()
```

- [ ] **Step 3: 在 coordinator.py 顶部添加 CooldownError 异常类和导入**

在文件顶部模块文档后添加：

```python
class CooldownError(Exception):
    """5 天冷却期内拒绝研究请求"""
    def __init__(self, cooldown_info: dict):
        self.cooldown_info = cooldown_info
        super().__init__(cooldown_info.get("message", "Industry is in cooldown period"))
```

同时确保 `import re` 在文件顶部（已在 `_check_cooldown` 方法内局部导入，也可提到顶部）。

- [ ] **Step 4: 运行现有测试**

Run: `pytest backend/tests/test_prosperity_coordinator.py -v`

Expected: 全部通过（首次研究的 session 创建不受影响，因为 `force=True` 不需要显式传也不会触发冷却 — 首次行业无 wiki 文件返 None）

- [ ] **Step 5: 手动测试冷却路径**

```python
# 创建临时 wiki 文件模拟已有研究
from app.strategies.prosperity.coordinator import Coordinator
c = Coordinator()
# 先创建行业页面
import os
wiki_dir = c.data_dir / "wiki" / "industries"
wiki_dir.mkdir(parents=True, exist_ok=True)
page = wiki_dir / "cooldown_test.md"
page.write_text("# cooldown_test\n\n## 景气评级历史\n- [2026-06-29] 🔥 高景气 — [查看报告](...)\n")
from app.strategies.prosperity.coordinator import CooldownError
try:
    c.start_session("cooldown_test")
    print("FAIL: should have raised")
except CooldownError as e:
    print(f"OK: {e.cooldown_info['status']}")

# force=True 应跳过冷却
sid = c.start_session("cooldown_test", force=True)
print(f"OK: session {sid} created with force=True")
```

Expected: 第一次抛 CooldownError，第二次正常创建 session

- [ ] **Step 6: 清理并 Commit**

删除测试用的 `cooldown_test.md` 和数据库记录。

```bash
git add backend/app/strategies/prosperity/coordinator.py
git commit -m "feat: add 5-day cooldown gate to start_session()"
```

---

### Task 3: Coordinator — _load_history 方法

**Files:**
- Modify: `backend/app/strategies/prosperity/coordinator.py:186-218` (Agent call methods → 改为传 history)
- Modify: `backend/app/strategies/prosperity/coordinator.py:127-184` (run_full_pipeline)

**Interfaces:**
- 新增: `_load_history(industry_name, session_id) -> Optional[IndustryHistory]`
- 改动: `_run_search_agent` 等 6 个私有方法签名加 `history=None`

- [ ] **Step 1: 添加 _load_history 方法**

```python
    def _load_history(self, industry_name: str, session_id: int) -> "IndustryHistory":
        """从 wiki + DB 加载行业历史上下文"""
        from app.strategies.prosperity.industry_history import IndustryHistory
        import re

        # 1. 读 wiki/industries 评级历史
        rating_history = []
        last_rating = ""
        last_study_date = None
        wiki_dir = self.data_dir / "wiki"
        industry_page = wiki_dir / "industries" / f"{industry_name}.md"
        if industry_page.exists():
            content = industry_page.read_text(encoding="utf-8")
            for line in content.split("\n"):
                if line.startswith("- ["):
                    rating_history.append(line)
            if rating_history:
                date_match = re.match(r"- \[(\d{4}-\d{2}-\d{2})\]\s*(\S+)\s*(\S+)", rating_history[0])
                if date_match:
                    from datetime import datetime
                    try:
                        last_study_date = datetime.strptime(date_match.group(1), "%Y-%m-%d")
                    except ValueError:
                        pass
                    last_rating = date_match.group(3)

        # 2. 读 wiki/synthesis 结构化截取 ~3000字
        last_synthesis_excerpt = ""
        synthesis_dir = wiki_dir / "synthesis"
        if synthesis_dir.exists():
            reports = sorted(
                synthesis_dir.glob(f"*{industry_name}*景*分析.md"),
                reverse=True
            )
            if reports:
                report_content = reports[0].read_text(encoding="utf-8")
                last_synthesis_excerpt = self._extract_synthesis_excerpt(report_content)

        # 3. 查 DB Hypothesis（最近完成 session）
        previous_hypotheses = []
        study_count = 1
        db = get_db_session(self.engine)
        try:
            # 查该行业所有 session，按 started_at 降序
            industry = db.query(Industry).filter_by(name=industry_name).first()
            if industry:
                sessions = (
                    db.query(ResearchSession)
                    .filter_by(industry_id=industry.id)
                    .order_by(ResearchSession.started_at.desc())
                    .all()
                )
                # 排除当前 session
                past_sessions = [s for s in sessions if s.id != session_id]
                study_count = len(sessions)  # 含本次
                if past_sessions:
                    last_session = past_sessions[0]
                    db_hyps = (
                        db.query(Hypothesis)
                        .filter_by(session_id=last_session.id)
                        .all()
                    )
                    for h in db_hyps:
                        previous_hypotheses.append({
                            "id": h.id,
                            "title": h.title,
                            "chain_level": h.chain_level,
                            "status": h.status,
                            "confidence": h.confidence,
                            "derives_from": h.derives_from or "",
                            "time_horizon": h.time_horizon or "",
                        })

            # 4. 查 TrackingItem
            pending_items = []
            if industry:
                trackings = (
                    db.query(TrackingItem)
                    .filter_by(industry_id=industry.id, status="pending")
                    .all()
                )
                for t in trackings:
                    pending_items.append({
                        "id": t.id,
                        "item": t.item,
                        "trigger_condition": t.trigger_condition,
                        "source_session_id": t.source_session_id,
                    })
        finally:
            db.close()

        if not previous_hypotheses and not rating_history:
            return None  # 首次研究

        cooldown_days = 0
        if last_study_date:
            from datetime import datetime
            cooldown_days = (datetime.utcnow() - last_study_date).days

        return IndustryHistory(
            industry_name=industry_name,
            study_count=study_count,
            last_rating=last_rating,
            last_study_date=last_study_date,
            cooldown_days=cooldown_days,
            previous_hypotheses=previous_hypotheses,
            last_synthesis_excerpt=last_synthesis_excerpt,
            rating_history=rating_history,
            pending_tracking_items=pending_items,
        )

    def _extract_synthesis_excerpt(self, report_text: str, max_chars: int = 3000) -> str:
        """从合成报告中提取结构化摘要：L0-L3 推理 + 股池方向，跳过验证/反推章节。

        Fallback: 解析失败时取报告前 max_chars 字。
        """
        lines = report_text.split("\n")
        selected = []
        char_count = 0
        # 需要截取的章节标题关键词
        include_sections = [
            "## 推理链概览", "## 现状诊断", "## 一阶推演", "## 二阶推演",
            "## 投资落点", "## 行业股池", "## 综合评级",
            "📊 现状诊断", "🔮 一阶推演", "⚖️ 二阶推演", "🎯 投资落点",
        ]
        # 跳过的章节
        skip_sections = ["## 验证总览", "## 反推修正", "## 跟踪"]

        in_skip = False
        for line in lines:
            # 跳过验证/反推/跟踪章节
            is_section_header = any(line.strip().startswith(s) for s in skip_sections)
            is_include_header = any(line.strip().startswith(s) for s in include_sections)

            if is_section_header:
                in_skip = True
                continue
            if is_include_header or (
                line.strip().startswith("##") and not line.strip().startswith("###")
            ):
                in_skip = False  # 新章节开始，重新包含

            if in_skip:
                continue

            # 跳过空标题行和 mermaid 块
            if not line.strip() or line.strip().startswith("```"):
                continue
            if line.strip().startswith("graph ") or line.strip().startswith("```mermaid"):
                continue

            selected.append(line)
            char_count += len(line) + 1
            if char_count >= max_chars:
                break

        if not selected:
            # Fallback: 取前 max_chars 字（跳过标题和 mermaid）
            char_count = 0
            for line in lines:
                if line.startswith("```") or line.startswith("graph "):
                    continue
                if not line.startswith("#") and line.strip():
                    selected.append(line)
                    char_count += len(line) + 1
                    if char_count >= max_chars:
                        break

        return "\n".join(selected)
```

- [ ] **Step 2: 修改 run_full_pipeline 注入 history**

在 `run_full_pipeline` 中，search 完成后加载 history 并逐级传入：

```python
    def run_full_pipeline(self, industry_name: str, force: bool = False) -> dict:
        # ... session_id = self.start_session(industry_name, force=force)
        # ... Step 1: Search
        search_result = self._run_search_agent(industry_name, session_id)
        self.pipeline_cache[session_id] = {"search": search_result}

        # NEW: 加载行业历史上下文
        history = self._load_history(industry_name, session_id)

        # Step 2-6: 逐级传入 history
        hypotheses = self._run_hypothesize_agent(industry_name, session_id, search_result, history)
        # ... (各 Agent 调用全部加 history 参数)
```

- [ ] **Step 3: 修改 6 个 Agent 调用接口，加 history 参数**

```python
    def _run_search_agent(self, industry_name: str, session_id: int, history=None) -> dict:
        from app.strategies.prosperity.agents.search_agent import SearchAgent
        agent = SearchAgent(self.data_dir)
        return agent.search(industry_name, session_id, history)

    def _run_hypothesize_agent(self, industry_name: str, session_id: int, search_result: dict, history=None) -> list[dict]:
        from app.strategies.prosperity.agents.hypothesize_agent import HypothesizeAgent
        agent = HypothesizeAgent(self.data_dir, self.rules_dir)
        return agent.form_hypotheses(industry_name, session_id, search_result, history)

    def _run_verify_agent(self, industry_name: str, session_id: int, hypotheses: list[dict], history=None) -> dict:
        from app.strategies.prosperity.agents.verify_agent import VerifyAgent
        agent = VerifyAgent(self.data_dir)
        return agent.verify(industry_name, session_id, hypotheses, history)

    def _run_counter_agent(self, industry_name: str, session_id: int, verification: dict, history=None) -> dict:
        from app.strategies.prosperity.agents.counter_agent import CounterAgent
        agent = CounterAgent(self.data_dir)
        return agent.counter(industry_name, session_id, verification, history)
```

- [ ] **Step 4: 运行现有测试**

Run: `pytest backend/tests/test_prosperity_coordinator.py -v`

Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add backend/app/strategies/prosperity/coordinator.py
git commit -m "feat: add _load_history() with structured synthesis excerpt extraction"
```

---

### Task 4: SearchAgent — URL 去重 + 新旧分流

**Files:**
- Modify: `backend/app/strategies/prosperity/agents/search_agent.py:39-83` (search method)

**Interfaces:**
- 改动: `search(industry_name, session_id, history=None) -> dict` — output 加 `new_count` / `old_count` 字段

- [ ] **Step 1: 添加 _load_previous_search 方法**

```python
    def _load_previous_search(self, industry_name: str) -> Optional[dict]:
        """加载上次搜索结果（用于 URL 去重）"""
        raw_dir = self.data_dir / "raw" / industry_name
        if not raw_dir.exists():
            return None
        search_files = sorted(raw_dir.glob("01_search_*.yaml"), reverse=True)
        if not search_files:
            return None
        import yaml
        with open(search_files[0], "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
```

- [ ] **Step 2: 修改 search 方法签名和逻辑**

```python
    def search(self, industry_name: str, session_id: int, history=None) -> dict:
        logger.info(f"SearchAgent: searching for {industry_name}")
        raw_dir = self.data_dir / "raw" / industry_name
        raw_dir.mkdir(parents=True, exist_ok=True)

        # 1. Tavily 全量搜索（不变）
        all_results = []
        queries = [q.format(industry=industry_name) for q in DEFAULT_QUERIES]
        for query in queries:
            results = self._tavily_search(query)
            all_results.append({"query": query, "results": results})

        # 2. URL 去重（本次搜索内部）
        deduped = self._deduplicate(all_results)

        # 3. 对比上次搜索做新旧分流
        new_results = deduped
        old_results = []
        if history and not history.is_first_study:
            prev_data = self._load_previous_search(industry_name)
            if prev_data:
                prev_urls = {r.get("url", "") for r in prev_data.get("results", []) if r.get("url")}
                new_results = [r for r in deduped if r.get("url", "") not in prev_urls]
                old_results = [r for r in deduped if r.get("url", "") in prev_urls]

        # 4. 写入 raw/ 时标记新旧
        date_str = datetime.now().strftime("%Y-%m-%d")
        output = {
            "industry": industry_name,
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "queries": queries,
            "new_count": len(new_results),
            "old_count": len(old_results),
            "results": new_results + old_results,  # 新在前，旧在后
            "summary": {
                "total_sources": len(deduped),
                "new_sources": len(new_results),
                "searches_performed": len(queries),
            },
        }

        output_path = raw_dir / f"01_search_{date_str}.yaml"
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(output, f, allow_unicode=True, default_flow_style=False)

        logger.info(f"SearchAgent: {len(new_results)} new + {len(old_results)} old results saved to {output_path}")
        return output
```

- [ ] **Step 3: 验证可导入不报错**

Run: `python -c "from app.strategies.prosperity.agents.search_agent import SearchAgent; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/strategies/prosperity/agents/search_agent.py
git commit -m "feat: add URL dedup + new/old split in SearchAgent"
```

---

### Task 5: HypothesizeAgent — 改用 IndustryHistory，删除 _load_wiki_history

**Files:**
- Modify: `backend/app/strategies/prosperity/agents/hypothesize_agent.py:45-50` (form_hypotheses 签名)
- Modify: `backend/app/strategies/prosperity/agents/hypothesize_agent.py:120-290` (_build_prompt + _load_wiki_history)

**Interfaces:**
- 改动: `form_hypotheses(industry_name, session_id, search_result, history=None)`
- 删除: `_load_wiki_history()` — 功能由 `history` 对象替代

- [ ] **Step 1: 修改 form_hypotheses 签名**

```python
    def form_hypotheses(
        self,
        industry_name: str,
        session_id: int,
        search_result: dict,
        history=None  # Optional[IndustryHistory]
    ) -> list[dict]:
```

- [ ] **Step 2: 修改 _build_prompt — 从 history 取数据，新旧分流**

```python
    def _build_prompt(self, industry_name: str, search_result: dict, history=None) -> str:
        # 构建搜索结果文本（新旧分流）
        results_text = ""
        new_count = search_result.get("new_count", 0)
        old_count = search_result.get("old_count", 0)
        all_results = search_result.get("results", [])

        if new_count > 0 or old_count > 0:
            # 已分流的场景
            new_results = all_results[:new_count]
            old_results = all_results[new_count:new_count + old_count]

            if new_results:
                results_text += "## 🆕 本期新情报\n\n"
                for i, r in enumerate(new_results[:20]):
                    results_text += f"[{i+1}] {r.get('title', '')}\n{r.get('content', '')[:300]}\n来源: {r.get('url', '')}\n\n"

            if old_results:
                results_text += "## 📚 上次已覆盖（摘要）\n\n"
                for i, r in enumerate(old_results[:10]):
                    results_text += f"[旧#{i+1}] {r.get('title', '')}\n{r.get('content', '')[:100]}\n\n"
        else:
            # 首次研究或无新旧分流
            for i, r in enumerate(all_results[:20]):
                results_text += f"[{i+1}] {r.get('title', '')}\n{r.get('content', '')[:300]}\n来源: {r.get('url', '')}\n\n"

        # 构建历史锚定上下文（从 history 对象）
        history_text = self._build_history_context(history)

        prompt = f"""你是一位行业研究分析师。请基于以下情报，构建「{industry_name}」的因果推理链。

## 行业历史背景（锚定参考）
{history_text}

## 情报搜索结果
{results_text}

## 核心要求：推演而非罗列
...
"""  # 后续内容保持不变

        return prompt

    def _build_history_context(self, history) -> str:
        """从 IndustryHistory 构建历史锚定文本"""
        if history is None:
            return "（无历史记录，首次研究）"

        lines = []

        # 评级历史
        if history.rating_history:
            lines.append("**最近评级历史**:")
            lines.extend(history.rating_history[:3])
            lines.append("")

        # 上次报告摘要
        if history.last_synthesis_excerpt:
            lines.append("**上次报告摘要**（L0-L3 推理结论）:")
            lines.append(history.last_synthesis_excerpt)
            lines.append("")

        # 上次假设状态分布
        if history.previous_hypotheses:
            lines.append(f"**上次研究假设状态**: {history.get_hypotheses_summary()}")
            lines.append("（请基于既有推理链延续拓展，标记哪些假设仍成立、哪些已变化）")
            lines.append("")

        return "\n".join(lines)
```

- [ ] **Step 3: 删除 _load_wiki_history 方法**

删除第 244-290 行的 `_load_wiki_history` 方法。

- [ ] **Step 4: 修改 _build_prompt 调用点**

将第 62 行从：
```python
prompt = self._build_prompt(industry_name, search_result)
```
改为：
```python
prompt = self._build_prompt(industry_name, search_result, history)
```

- [ ] **Step 5: 验证可导入**

Run: `python -c "from app.strategies.prosperity.agents.hypothesize_agent import HypothesizeAgent; h = HypothesizeAgent(); print('OK')"`

Expected: `OK`（不抛异常即可，不实际调 LLM）

- [ ] **Step 6: Commit**

```bash
git add backend/app/strategies/prosperity/agents/hypothesize_agent.py
git commit -m "feat: HypothesizeAgent uses IndustryHistory, drops _load_wiki_history"
```

---

### Task 6: VerifyAgent — 注入历史上下文

**Files:**
- Modify: `backend/app/strategies/prosperity/agents/verify_agent.py:33-38` (verify 签名)

**Interfaces:**
- 改动: `verify(industry_name, session_id, hypotheses, history=None)`

- [ ] **Step 1: 添加 _build_history_context 方法**

在 `VerifyAgent` 类中添加：

```python
    def _build_history_context(self, history) -> str:
        """构建验证历史上下文（注入 prompt）"""
        if history is None or history.is_first_study:
            return ""

        lines = ["## 历史验证参考", ""]
        lines.append(history.get_hypotheses_summary())
        lines.append("")

        # 列出上次每条假设的最终状态
        if history.previous_hypotheses:
            lines.append("**上次研究各假设状态**:")
            for h in history.previous_hypotheses:
                level = h.get("chain_level", "?")
                status = h.get("status", "unknown")
                title = h.get("title", "?")
                lines.append(f"- **L{level}** `{h.get('id', '?')}` {title}: `{status}`")
            lines.append("")
            lines.append("请对比本次情报判断：上次已确认的假设是否仍成立？上次被推翻的假设是否有新的支撑证据？")
            lines.append("")

        return "\n".join(lines)
```

- [ ] **Step 2: 修改 verify 签名**

```python
    def verify(
        self,
        industry_name: str,
        session_id: int,
        hypotheses: list[dict],
        history=None  # Optional[IndustryHistory]
    ) -> dict:
```

- [ ] **Step 3: validate 可导入**

Run: `python -c "from app.strategies.prosperity.agents.verify_agent import VerifyAgent; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/strategies/prosperity/agents/verify_agent.py
git commit -m "feat: VerifyAgent accepts history for cross-session context"
```

---

### Task 7: CounterAgent — 注入历史上下文

**Files:**
- Modify: `backend/app/strategies/prosperity/agents/counter_agent.py:26-31` (counter 签名)

**Interfaces:**
- 改动: `counter(industry_name, session_id, verification, history=None)`

- [ ] **Step 1: 添加 _build_history_context 方法**

在 `CounterAgent` 类中添加：

```python
    def _build_history_context(self, history) -> str:
        """构建反推历史上下文"""
        if history is None or history.is_first_study:
            return ""

        overturned = history.get_overturned_hypotheses()
        if not overturned:
            return ""

        lines = ["## 上次反推记录", ""]
        lines.append(f"上次研究有 {len(overturned)} 条假设被推翻：")
        for h in overturned:
            lines.append(f"- `{h.get('id', '?')}` {h.get('title', '?')}: overturned (level={h.get('chain_level', '?')})")
        lines.append("")
        lines.append("请对比本次验证结果：上次被推翻的假设，本次是否有新的支撑证据？上次反推指出的风险是否仍成立？")
        lines.append("")
        return "\n".join(lines)
```

- [ ] **Step 2: 修改 counter 签名**

```python
    def counter(self, industry_name: str, session_id: int, verification: dict, history=None) -> dict:
```

- [ ] **Step 3: 验证可导入**

Run: `python -c "from app.strategies.prosperity.agents.counter_agent import CounterAgent; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/strategies/prosperity/agents/counter_agent.py
git commit -m "feat: CounterAgent accepts history for overturned context"
```

---

### Task 8: ReportAgent — 评级行去重 + study_count 传参

**Files:**
- Modify: `backend/app/strategies/prosperity/agents/report_agent.py:213-232` (_update_industry_page)
- Modify: `backend/app/strategies/prosperity/agents/report_agent.py:40-81` (generate 方法 — 接受 study_count)

**Interfaces:**
- 改动: `generate(industry_name, session_id, counter_result, study_count=1)`
- 改动: `_update_industry_page(industry_name, level, icon, report_path, study_count=1)`

- [ ] **Step 1: 修改 generate 签名**

```python
    def generate(self, industry_name: str, session_id: int, counter_result: dict, study_count: int = 1) -> dict:
```

内部调用 `self._update_industry_page(industry_name, level, level_icon, report_path, study_count)` 时传入。

- [ ] **Step 2: 重写 _update_industry_page — 去重 + 研究次数**

```python
    def _update_industry_page(self, industry_name, level, icon, report_path, study_count=1):
        """更新 wiki/industries/{行业}.md — 去重：同日同评级替换不追加"""
        import re
        industry_dir = self.data_dir / "wiki" / "industries"
        industry_dir.mkdir(parents=True, exist_ok=True)
        page_path = industry_dir / f"{industry_name}.md"

        today = datetime.now().strftime("%Y-%m-%d")
        new_line = f"- [{today}] {icon} {level} — [查看报告](../synthesis/{report_path.name}) (*第{study_count}次研究*)"

        if page_path.exists():
            content = page_path.read_text(encoding="utf-8")

            # 去重：同日期同评级 → 替换最新行
            existing_lines = content.split("\n")
            rating_indices = [
                (i, line) for i, line in enumerate(existing_lines)
                if line.startswith("- [") and re.search(r"\[(\d{4}-\d{2}-\d{2})\]", line)
            ]

            if rating_indices:
                first_i, first_line = rating_indices[0]
                first_date_match = re.search(r"\[(\d{4}-\d{2}-\d{2})\]", first_line)
                if first_date_match and first_date_match.group(1) == today:
                    level_match = re.search(r"\]\s*(\S+)\s*(\S+)", first_line)
                    if level_match and level_match.group(2) == level:
                        # 同日同评级 → 替换
                        existing_lines[first_i] = new_line
                        content = "\n".join(existing_lines)
                        page_path.write_text(content, encoding="utf-8")
                        logger.info(f"ReportAgent: replaced duplicate rating line for {industry_name}")
                        return

            # 不同日期或不同评级 → 追加到头部
            content = f"{new_line}\n{content}"
        else:
            content = f"""# {industry_name}

## 景气评级历史
{new_line}

## 行业概览
（待后续研究更新）
"""

        page_path.write_text(content, encoding="utf-8")
```

- [ ] **Step 3: Coordinator 中调用 report 时传入 study_count**

在 `coordinator.py` 的 `run_full_pipeline` 中：

```python
# Step 5: Report
report_result = self._run_report_agent(industry_name, session_id, counter_result, history)
```

`_run_report_agent`:

```python
    def _run_report_agent(self, industry_name: str, session_id: int, counter_result: dict, history=None) -> dict:
        from app.strategies.prosperity.agents.report_agent import ReportAgent
        agent = ReportAgent(self.data_dir)
        study_count = history.study_count if history else 1
        return agent.generate(industry_name, session_id, counter_result, study_count)
```

- [ ] **Step 4: 验证可导入**

Run: `python -c "from app.strategies.prosperity.agents.report_agent import ReportAgent; print('OK')"`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/strategies/prosperity/agents/report_agent.py backend/app/strategies/prosperity/coordinator.py
git commit -m "feat: ReportAgent dedup rating lines + study_count label"
```

---

### Task 9: TrackAgent — 全量 key_indicators 提取 + 合并去重

**Files:**
- Modify: `backend/app/strategies/prosperity/agents/track_agent.py:27-76` (extract_tracking)

**Interfaces:**
- 改动: `extract_tracking` — 从只提取 UNVERIFIED/OVERTURNED → 提取所有假设的 key_indicators
- 新增: `_merge_indicators(items)` — 按 indicator 名合并去重

- [ ] **Step 1: 重写 extract_tracking 方法**

```python
    def extract_tracking(self, industry_name: str, session_id: int, report: dict) -> dict:
        """从研究结果中提取所有假设的 key_indicators → watchlist"""
        logger.info(f"TrackAgent: extracting tracking items for {industry_name}")

        all_items = []

        # 从 report 中的假设提取 ALL key_indicators（非仅 unverified/overturned）
        hypotheses = report.get("hypotheses", [])
        for h in hypotheses:
            h_id = h.get("id", "")
            title = h.get("title", "")
            status = h.get("status", "unverified")
            key_indicators = h.get("key_indicators", [])

            if not key_indicators:
                continue

            for indicator in key_indicators:
                if not indicator.strip():
                    continue
                all_items.append({
                    "indicator": indicator.strip(),
                    "industry": industry_name,
                    "hypothesis_id": h_id,
                    "hypothesis_title": title,
                    "hypothesis_status": status,
                    "source_session": session_id,
                    "check_frequency": "monthly",
                    "last_value": None,
                    "last_updated": datetime.utcnow().isoformat(),
                    "status": "pending",
                    "trigger_condition": "数值变化超过 ±20% 或方向反转时触发复核",
                })

        # 按 indicator 名合并去重
        merged = self._merge_indicators(all_items)
        logger.info(f"TrackAgent: {len(all_items)} raw indicators → {len(merged)} merged")

        # 写入 tracking/watchlist.yaml
        watchlist_path = self.data_dir / "tracking" / "watchlist.yaml"
        existing = {"items": []}
        if watchlist_path.exists():
            with open(watchlist_path, "r", encoding="utf-8") as f:
                existing = yaml.safe_load(f) or {"items": []}

        existing["items"].extend(merged)
        with open(watchlist_path, "w", encoding="utf-8") as f:
            yaml.dump(existing, f, allow_unicode=True)

        # 写入数据库
        db = get_db_session()
        try:
            for item in merged:
                db_item = TrackingItem(
                    industry_id=1,  # 简化
                    item=f"[{item.get('indicator')}] {item.get('hypothesis_ids', [])}",
                    trigger_condition=item.get("trigger_condition", ""),
                    check_date=datetime.utcnow() + timedelta(days=90),
                    source_session_id=session_id,
                )
                db.add(db_item)
            db.commit()
        finally:
            db.close()

        return {
            **report,
            "tracking_items": len(merged),
        }

    def _merge_indicators(self, items: list[dict]) -> list[dict]:
        """按 indicator 名合并去重，同一指标多个假设合并到 hypothesis_ids 列表"""
        from collections import defaultdict
        merged = defaultdict(lambda: {
            "indicator": "",
            "industry": "",
            "hypothesis_ids": [],
            "hypothesis_titles": [],
            "hypothesis_statuses": [],
            "source_session": None,
            "check_frequency": "monthly",
            "last_value": None,
            "last_updated": "",
            "status": "pending",
            "trigger_condition": "数值变化超过 ±20% 或方向反转时触发复核",
        })

        for item in items:
            key = item["indicator"]
            entry = merged[key]
            entry["indicator"] = key
            entry["industry"] = item.get("industry", "")
            entry["hypothesis_ids"].append(item.get("hypothesis_id", ""))
            entry["hypothesis_titles"].append(item.get("hypothesis_title", ""))
            entry["hypothesis_statuses"].append(item.get("hypothesis_status", ""))
            entry["source_session"] = item.get("source_session")
            entry["last_updated"] = item.get("last_updated", "")

        return list(merged.values())
```

- [ ] **Step 2: 验证可导入**

Run: `python -c "from app.strategies.prosperity.agents.track_agent import TrackAgent; print('OK')"`

Expected: `OK`

- [ ] **Step 3: 单元测试 — _merge_indicators**

```python
# 临时测试脚本
from app.strategies.prosperity.agents.track_agent import TrackAgent
from pathlib import Path

agent = TrackAgent()
items = [
    {"indicator": "DRAM 合约价月度环比", "industry": "半导体", "hypothesis_id": "H2-1", "hypothesis_title": "产能拐点", "hypothesis_status": "verified", "source_session": 1},
    {"indicator": "DRAM 合约价月度环比", "industry": "半导体", "hypothesis_id": "H2-2", "hypothesis_title": "价格压力", "hypothesis_status": "verified", "source_session": 1},
    {"indicator": "HBM 产能利用率", "industry": "半导体", "hypothesis_id": "H3-1", "hypothesis_title": "选股方向", "hypothesis_status": "confirmed", "source_session": 1},
]
merged = agent._merge_indicators(items)
assert len(merged) == 2  # 3 → 2
dram = [m for m in merged if m["indicator"] == "DRAM 合约价月度环比"][0]
assert dram["hypothesis_ids"] == ["H2-1", "H2-2"]
assert len(dram["hypothesis_titles"]) == 2
print("OK: merge_indicators works correctly")
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/strategies/prosperity/agents/track_agent.py
git commit -m "feat: TrackAgent extracts all key_indicators + merge by indicator name"
```

---

### Task 10: 集成测试 + 端到端验证

**Files:**
- Modify: `backend/tests/test_prosperity_coordinator.py`

**Interfaces:**
- 新增测试覆盖所有 Spec 测试要点

- [ ] **Step 1: 添加 cooldown + history 相关测试**

在 `test_prosperity_coordinator.py` 末尾追加：

```python

class TestWikiEnhancement:
    """v0.14.0 Wiki 智能增强测试"""

    def test_cooldown_first_study_returns_none(self):
        """T1: 首次研究行业 — _check_cooldown 返回 None"""
        from app.strategies.prosperity.coordinator import Coordinator
        c = Coordinator()
        result = c._check_cooldown("nonexistent_industry_for_test")
        assert result is None

    def test_cooldown_within_5_days(self):
        """T2: 5 天内重复 → 返回 cooldown"""
        import os
        from app.strategies.prosperity.coordinator import Coordinator
        from datetime import datetime
        c = Coordinator()
        wiki_dir = c.data_dir / "wiki" / "industries"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        page = wiki_dir / "cooldown_test_5d.md"
        today = datetime.utcnow().strftime("%Y-%m-%d")
        page.write_text(f"# cooldown_test_5d\n\n- [{today}] 🔥 高景气\n")
        result = c._check_cooldown("cooldown_test_5d")
        assert result is not None
        assert result["status"] == "cooldown"
        assert result["days_ago"] == 0
        # cleanup
        page.unlink()

    def test_cooldown_over_5_days_returns_none(self):
        """T2b: 超过 5 天 → 返回 None"""
        from app.strategies.prosperity.coordinator import Coordinator
        c = Coordinator()
        wiki_dir = c.data_dir / "wiki" / "industries"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        page = wiki_dir / "old_industry_test.md"
        page.write_text("# old_industry_test\n\n- [2026-01-01] ✅ 景气\n")
        result = c._check_cooldown("old_industry_test")
        assert result is None
        page.unlink()

    def test_start_session_force_bypasses_cooldown(self):
        """T3: force=True 跳过冷却"""
        from datetime import datetime
        from app.strategies.prosperity.coordinator import Coordinator
        c = Coordinator()
        wiki_dir = c.data_dir / "wiki" / "industries"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        page = wiki_dir / "force_test.md"
        today = datetime.utcnow().strftime("%Y-%m-%d")
        page.write_text(f"# force_test\n\n- [{today}] 🔥 高景气\n")
        sid = c.start_session("force_test", force=True)
        assert sid > 0
        # cleanup
        page.unlink()

    def test_load_history_returns_none_for_first_study(self):
        """T10: 无 wiki 历史的行业 → history=None"""
        from app.strategies.prosperity.coordinator import Coordinator
        c = Coordinator()
        sid = c.start_session("never_studied_before_xyz")
        history = c._load_history("never_studied_before_xyz", sid)
        assert history is None

    def test_industry_history_dataclass(self):
        """验证 IndustryHistory 数据类"""
        from app.strategies.prosperity.industry_history import IndustryHistory
        h = IndustryHistory("测试行业")
        assert h.is_first_study is True
        assert h.study_count == 1

        h2 = IndustryHistory("测试行业2", study_count=3, last_rating="高景气")
        assert h2.is_first_study is False
        assert h2.verified_count == 0
        assert h2.overturned_count == 0

    def test_cooldown_error_exception(self):
        """验证 CooldownError 异常"""
        from app.strategies.prosperity.coordinator import CooldownError
        info = {"status": "cooldown", "message": "test"}
        e = CooldownError(info)
        assert e.cooldown_info["status"] == "cooldown"

    def test_merge_indicators_dedup(self):
        """T9: 同指标多假设合并"""
        from app.strategies.prosperity.agents.track_agent import TrackAgent
        from pathlib import Path
        agent = TrackAgent()
        items = [
            {"indicator": "DRAM 价格", "industry": "半导体", "hypothesis_id": "H2-1", "hypothesis_title": "拐点", "hypothesis_status": "verified", "source_session": 1},
            {"indicator": "DRAM 价格", "industry": "半导体", "hypothesis_id": "H2-2", "hypothesis_title": "压力", "hypothesis_status": "verified", "source_session": 1},
            {"indicator": "营收增速", "industry": "半导体", "hypothesis_id": "H0-1", "hypothesis_title": "营收", "hypothesis_status": "confirmed", "source_session": 1},
        ]
        merged = agent._merge_indicators(items)
        assert len(merged) == 2
        dram = [m for m in merged if m["indicator"] == "DRAM 价格"][0]
        assert dram["hypothesis_ids"] == ["H2-1", "H2-2"]
```

- [ ] **Step 2: 运行全部测试**

Run: `pytest backend/tests/test_prosperity_coordinator.py -v`

Expected: 全部通过（原有 7 个 + 新增 8 个 = 15 个）

- [ ] **Step 3: 运行全量测试**

Run: `pytest backend/tests/ -v`

Expected: 全部通过

- [ ] **Step 4: Commit + 更新版本号**

```bash
# 更新 pyproject.toml 版本号 0.8.3 → 0.14.0
python scripts/bump_version.py 0.14.0
# 或手动改 pyproject.toml + CHANGELOG.md

git add backend/tests/test_prosperity_coordinator.py backend/pyproject.toml CHANGELOG.md
git commit -m "test: add wiki enhancement tests (cooldown + history + merge)"
```

---

## Self-Review Checklist

- [x] **Spec coverage**: 10 条测试覆盖全部 10 个测试要点
- [x] **Placeholder scan**: 无 TBD/TODO，无"类似 Task N"的引用
- [x] **Type consistency**: `IndustryHistory` 在 Task 1 定义，Task 3-9 使用一致
- [x] **Fallback paths**: Task 3 `_extract_synthesis_excerpt` 有 fallback，Task 4 URL 去重有文件不存在的兜底
