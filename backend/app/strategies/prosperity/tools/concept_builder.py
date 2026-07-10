"""搜索引擎自建概念板块 — Bocha 主搜索 + Tavily 备用，LLM + Tushare 交叉验证

用于 get_industry_ts_codes() 第 5 层兜底：当 stock_basic / 申万 / Tushare 概念 / 同花顺
都匹配不上时，用搜索引擎 + LLM 构建自定义概念板块，再经 Tushare stock_basic 交叉验证。

v0.23.3: Bocha 优先（中文覆盖更优，摘要更长），Tavily 降级为备用。

流程：
  1. 查 YAML 缓存 data/prosperity/concept_boards/{theme}.yaml → 命中直接返回
  2. Bocha 搜索 "{theme} 概念股 A股 上市公司"（无 Key 则降级 Tavily）
  3. LLM 提取: 股票名称 + 代码 → 结构化列表（含产业链位置）
  4. Tushare stock_basic 交叉验证 → 过滤无效代码
  5. 写入缓存 → 秒出
"""

import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from app.core.config import settings

logger = logging.getLogger(__name__)

# 缓存目录
CACHE_DIR = settings.PROSPERITY_DATA_DIR / "concept_boards"

# 搜索关键词模板
SEARCH_QUERY = "{theme} 概念股 A股 上市公司 产业链"

# LLM 提取 prompt
EXTRACTION_PROMPT = """你是一个 A 股研究员。请从以下搜索结果中提取「{theme}」概念板块的 A 股上市公司。

要求：
1. 只提取搜索结果中明确提到的 A 股上市公司（有股票代码的优先）
2. 如果搜索结果提到了股票代码（如 688122.SH, 600875），必须包含代码
3. 如果只提到了股票名称没有代码，也列出名称，标注 code 为 null
4. 按产业链位置分类：上游(材料/设备)、中游(核心设备/部件)、下游(系统集成/运营)
5. 去重（同一家公司只出现一次）
6. 【重要】对每只股票判断与「{theme}」的真实业务关联性：
   - relevant: true → 搜索结果明确描述该公司在{theme}产业中的业务、产品、合同或技术
   - relevant: false → 仅因市场行情（涨停/跌幅）、资金流向、指数成分被提及，无具体业务描述
   - 示例：可控核聚变 → 西部超导(高温超导带材供应商) → relevant: true
   - 示例：可控核聚变 → 雪人集团(因当天涨停被提及，主营制冷设备) → relevant: false

返回 JSON 数组格式（不要任何其他文字）：
```json
[
  {{"code": "688122.SH", "name": "西部超导", "chain": "上游-超导材料", "relevant": true}},
  {{"code": "002639.SZ", "name": "雪人集团", "chain": "中游-核心设备", "relevant": false}}
]
```

搜索结果：
{search_results}"""


def search_concept_stocks(theme: str) -> list[dict]:
    """搜索引擎自建概念板块 — 主入口

    Args:
        theme: 概念名称，如 "可控核聚变", "固态电池", "低空经济"

    Returns:
        [{"ts_code": "688122.SH", "name": "西部超导", "chain": "上游-超导材料"}, ...]
        失败返回空列表
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 查缓存
    cache_file = CACHE_DIR / f"{theme}.yaml"
    cached = _load_cache(cache_file)
    if cached:
        logger.info(f"概念板块 '{theme}': 缓存命中 ({len(cached)} 只)")
        return cached

    # 2. 搜索引擎搜索 (Bocha > Tavily)
    engine = _detect_engine()
    logger.info(f"概念板块 '{theme}': 缓存未命中，启动搜索引擎构建（{engine}）...")
    if engine == "bocha":
        search_results = _bocha_search(theme)
        if not search_results:
            logger.warning(f"概念板块 '{theme}': Bocha 搜索无结果，降级 Tavily...")
            search_results = _tavily_search(theme)
    elif engine == "tavily":
        search_results = _tavily_search(theme)
    else:
        logger.warning(f"概念板块 '{theme}': 无可用搜索引擎（BOCHA_API_KEY/TAVILY_API_KEY 均未配置）")
        return []
    if not search_results:
        logger.warning(f"概念板块 '{theme}': 搜索无结果")
        return []

    # 3. LLM 提取股票列表
    stocks = _llm_extract(theme, search_results)
    if not stocks:
        logger.warning(f"概念板块 '{theme}': LLM 未提取到股票")
        return []

    # 4. Tushare stock_basic 交叉验证
    verified = _cross_validate(stocks)

    # 4.5 过滤 irrelevant 股票（仅因行情/指数被提及，无真实业务关联）
    n_irrelevant = sum(1 for s in verified if not s.get("relevant", True))
    verified = [s for s in verified if s.get("relevant", True)]

    logger.info(
        f"概念板块 '{theme}': LLM 提取 {len(stocks)} → "
        f"stock_basic 验证通过 {len(verified) + n_irrelevant} 只 "
        f"（过滤 {n_irrelevant} 只不相关）→ 最终 {len(verified)} 只"
    )

    # 5. 写入缓存
    _save_cache(cache_file, theme, verified)

    return verified


def _load_cache(cache_file: Path) -> Optional[list[dict]]:
    """加载 YAML 缓存（缓存永不过期，手动删除刷新）"""
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and "stocks" in data:
            return data["stocks"]
    except Exception as e:
        logger.debug(f"加载概念缓存失败 {cache_file}: {e}")
    return None


def _save_cache(cache_file: Path, theme: str, stocks: list[dict]):
    """写入 YAML 缓存"""
    data = {
        "theme": theme,
        "built_at": datetime.utcnow().isoformat(),
        "source": "web_search + LLM + Tushare stock_basic",
        "count": len(stocks),
        "stocks": stocks,
    }
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        logger.info(f"概念缓存已写入: {cache_file} ({len(stocks)} 只)")
    except Exception as e:
        logger.error(f"写入概念缓存失败: {e}")


def _detect_engine() -> str:
    """检测使用哪个搜索引擎: bocha > tavily > none"""
    if getattr(settings, "BOCHA_API_KEY", ""):
        return "bocha"
    if getattr(settings, "TAVILY_API_KEY", ""):
        return "tavily"
    return "none"


def _bocha_search(theme: str) -> str:
    """Bocha 搜索，返回拼接的搜索结果文本（v0.23.3: 主搜索引擎）

    API 文档: https://open.bochaai.com/
    端点: POST https://api.bochaai.com/v1/web-search
    """
    import requests

    api_key = getattr(settings, "BOCHA_API_KEY", "")
    if not api_key:
        logger.warning(f"BOCHA_API_KEY 未配置，无法搜索概念 '{theme}'")
        return ""

    query = SEARCH_QUERY.format(theme=theme)

    try:
        resp = requests.post(
            "https://api.bochaai.com/v1/web-search",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "freshness": "oneYear",
                "summary": True,       # 返回详细摘要，中文覆盖更优
                "count": 10,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        web_pages = data.get("data", {}).get("webPages", {}).get("value", [])

        parts = []
        for page in web_pages:
            # Bocha: summary 是详细摘要（仅 summary=true 时），优先用 summary
            content = page.get("summary", "") or page.get("snippet", "")
            parts.append(
                f"【{page.get('name', '')}】\n"
                f"{content}\n"
                f"URL: {page.get('url', '')}"
            )

        combined = "\n\n---\n\n".join(parts)
        logger.debug(f"Bocha 搜索 '{query}': {len(web_pages)} 条结果")
        return combined
    except Exception as e:
        logger.warning(f"Bocha 搜索失败: {e}")
        return ""


def _tavily_search(theme: str) -> str:
    """Tavily 搜索（v0.23.3: 降级为备用），返回拼接的搜索结果文本"""
    import requests

    api_key = getattr(settings, "TAVILY_API_KEY", "")
    if not api_key:
        logger.warning(f"TAVILY_API_KEY 未配置，无法搜索概念 '{theme}'")
        return ""

    query = SEARCH_QUERY.format(theme=theme)
    url = "https://api.tavily.com/search"
    headers = {"Content-Type": "application/json"}
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "advanced",
        "max_results": 10,
        "include_answer": True,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        parts = []
        if data.get("answer"):
            parts.append(data["answer"])

        for r in data.get("results", []):
            parts.append(f"【{r.get('title', '')}】\n{r.get('content', '')}\nURL: {r.get('url', '')}")

        combined = "\n\n---\n\n".join(parts)
        logger.debug(f"Tavily 搜索 '{query}': {len(data.get('results', []))} 条结果")
        return combined
    except Exception as e:
        logger.warning(f"Tavily 搜索失败: {e}")
        return ""


def _llm_extract(theme: str, search_results: str) -> list[dict]:
    """LLM 提取股票列表"""
    import json

    api_key = getattr(settings, "LLM_API_KEY", "")
    if not api_key:
        logger.warning(f"LLM_API_KEY 未配置，无法提取概念股票")
        return _fallback_regex_extract(search_results)

    prompt = EXTRACTION_PROMPT.format(theme=theme, search_results=search_results[:8000])

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url=settings.LLM_API_BASE,
        )

        start = time.monotonic()
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
        elapsed = time.monotonic() - start
        content = response.choices[0].message.content
        if not content:
            finish = response.choices[0].finish_reason
            logger.warning(
                f"LLM 返回空内容 (finish_reason={finish}, "
                f"usage={response.usage}), 回退到正则提取"
            )
            return _fallback_regex_extract(search_results)
        content = content.strip()
        logger.debug(f"LLM 提取概念股票: {elapsed:.1f}s, tokens={response.usage.total_tokens}")

        # 提取 JSON 块
        stocks = _try_parse_json(content)
        if stocks:
            logger.info(f"LLM 提取 '{theme}': {len(stocks)} 只 (JSON)")
            return stocks

        # JSON 解析失败 → 回退到正则提取
        logger.warning(f"LLM JSON 解析失败，回退正则提取")
        return _fallback_regex_extract(search_results)

    except Exception as e:
        logger.warning(f"LLM 提取失败: {e}")
        return _fallback_regex_extract(search_results)


def _try_parse_json(content: str) -> Optional[list[dict]]:
    """鲁棒 JSON 解析：处理 LLM 输出截断/格式不完整"""
    import json

    strategies = [
        # 1. 标准 ```json ... ```
        lambda c: re.search(r"```json\s*([\s\S]*?)\s*```", c),
        # 2. 裸 JSON 数组
        lambda c: re.search(r"\[[\s\S]*\]", c),
        # 3. ``` ... ``` (无 json 标注)
        lambda c: re.search(r"```\s*([\s\S]*?)\s*```", c),
    ]

    for strategy in strategies:
        match = strategy(content)
        if not match:
            continue
        raw_json = match.group(1).strip() if match.lastindex else match.group(0).strip()

        # 截断修复：找到最后一个完整的 } 或 ]
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            # 尝试用宽松解析找到所有可解析的对象
            data = _extract_valid_json_objects(raw_json)

        if data and isinstance(data, list):
            result = []
            for s in data:
                if isinstance(s, dict) and s.get("name"):
                    result.append({
                        "code": s.get("code"),
                        "name": s.get("name", ""),
                        "chain": s.get("chain", ""),
                        "relevant": s.get("relevant", True),  # 默认相关（兼容旧缓存）
                    })
            if result:
                return result

    return None


def _extract_valid_json_objects(raw_json: str) -> list:
    """宽松解析：从可能被截断的 JSON 中提取每个有效对象"""
    import json
    objects = []
    # 匹配每个 { ... } 对象（允许跨行，relevant 可选）
    pattern = r'\{\s*"code"\s*:\s*(?:"[^"]*"|null)\s*,\s*"name"\s*:\s*"([^"]+)"\s*,\s*"chain"\s*:\s*"([^"]*)"(?:\s*,\s*"relevant"\s*:\s*(true|false))?\s*\}'
    for match in re.finditer(pattern, raw_json):
        name = match.group(1)
        chain = match.group(2)
        relevant_str = match.group(3)
        relevant = relevant_str == "true" if relevant_str else True  # 默认相关
        # 提取 code
        code_match = re.search(r'"code"\s*:\s*"([^"]*)"', match.group(0))
        code = code_match.group(1) if code_match else None
        objects.append({"code": code, "name": name, "chain": chain, "relevant": relevant})
    return objects


def _fallback_regex_extract(text: str) -> list[dict]:
    """纯正则兜底：从文本中提取股票名称（中文公司名 + 可选代码）

    策略：
    1. 先匹配 "代码 + 名称" 组合（如 688122.SH 西部超导）
    2. 提取中文公司名列表 → 后续由 _cross_validate 用 stock_basic 反查代码
    """
    stocks = []
    seen_names = set()

    # 策略1: 6位数字代码 + 中文名
    code_name_pairs = re.findall(
        r"(\d{6}(?:\.(?:SH|SZ|BJ))?)\s*[（(]?([\u4e00-\u9fff]{2,8})[）)]?",
        text
    )
    for code_raw, name in code_name_pairs:
        code = code_raw if "." in code_raw else _infer_suffix(code_raw)
        if name not in seen_names:
            seen_names.add(name)
            stocks.append({"code": code, "name": name, "chain": ""})

    # 策略2: 从顿号/逗号分隔列表中提取中文公司名（特征：2-5字全中文 + 行业后缀）
    name_pattern = re.compile(r"[\u4e00-\u9fff]{2,5}(?:科技|电气|股份|新材|集团|重工|核电|光电|智能|装备|能源|材料|特种|机电|动力|超导|电力|控制|通信|电子|集成|精工|电工)")
    for match in name_pattern.finditer(text):
        name = match.group(0)
        if name not in seen_names and not _is_common_word(name):
            seen_names.add(name)
            stocks.append({"code": None, "name": name, "chain": ""})

    # 策略3: 从"XX股份"等4字公司名中捡漏（不在策略2列表中的）
    short_name_pattern = re.compile(r"[\u4e00-\u9fff]{2,4}(?:股份|实业|建设|发展)")
    for match in short_name_pattern.finditer(text):
        name = match.group(0)
        if name not in seen_names and not _is_common_word(name):
            seen_names.add(name)
            stocks.append({"code": None, "name": name, "chain": ""})

    return stocks


_CACHED_COMMON_WORDS: set[str] = None


def _is_common_word(name: str) -> bool:
    """过滤常见非公司名中文词汇"""
    global _CACHED_COMMON_WORDS
    if _CACHED_COMMON_WORDS is None:
        _CACHED_COMMON_WORDS = {
            "上市公司", "概念股", "相关概念", "有限公司", "研究报告",
            "投资价值", "产业链", "重点关注", "具体如下", "未来五年",
            "受益个股", "新浪财经", "券商研报", "A股市场", "资金关注",
            "涉及领域", "包层领域", "第一壁", "磁体馈线", "冷却系统",
            "真空室", "偏滤器", "环向场", "五月以来", "根据华泰",
            "涉及企业", "梳理如下", "行情掀起", "资金追逐", "实现扭亏",
            "业绩增长", "新能源汽车", "光伏产业", "半导体行业",
            "可控核聚变", "超导材料", "特种电源", "设备领域",
            "同时拥有", "净利润为", "年初迄今", "最大涨幅", "公司股价",
            "主营产品", "拥有订单", "预计未来", "获得新进",
            "为您发掘", "海量信息", "投资机会", "对于以上",
            "并不代表", "法律责任", "公开资料", "风险自担",
            "文章内容", "仅供参考", "入市需谨慎", "投资需谨慎",
            "本文内容", "投资有风险", "免责条款",
        }
    return name in _CACHED_COMMON_WORDS


def _infer_suffix(code: str) -> str:
    """根据 6 位纯数字代码推断交易所后缀"""
    if code.startswith(("6", "688", "689")):
        return f"{code}.SH"
    return f"{code}.SZ"


def _cross_validate(stocks: list[dict]) -> list[dict]:
    """用 Tushare stock_basic 交叉验证股票代码，过滤无效股票

    Returns:
        [{"ts_code": "688122.SH", "name": "西部超导", "chain": "上游"}, ...]
    """
    if not stocks:
        return []

    try:
        from app.services.tushare_client import TushareClient

        client = TushareClient()
        stock_basic = client.get_stock_basic()
        if stock_basic is None or stock_basic.empty:
            logger.warning("stock_basic 拉取失败，跳过交叉验证")
            # 无 stock_basic 兜底 → 仍返回但标记未验证
            return [
                {"ts_code": s.get("code", ""), "name": s.get("name", ""),
                 "chain": s.get("chain", ""), "verified": False,
                 "relevant": s.get("relevant", True)}
                for s in stocks if s.get("code")
            ]

        valid_codes = set(stock_basic["ts_code"].tolist())
        code_to_name = dict(zip(stock_basic["ts_code"], stock_basic["name"]))

        verified = []
        for s in stocks:
            code = s.get("code", "")
            if not code:
                # 没有代码 → 尝试通过名称反查
                name = s.get("name", "")
                matching = stock_basic[stock_basic["name"] == name]
                if not matching.empty:
                    code = matching.iloc[0]["ts_code"]
                else:
                    logger.debug(f"交叉验证: 无法匹配 '{name}'，跳过")
                    continue

            if code in valid_codes:
                official_name = code_to_name[code]
                verified.append({
                    "ts_code": code,
                    "name": official_name,
                    "chain": s.get("chain", ""),
                    "verified": True,
                    "relevant": s.get("relevant", True),
                })
            else:
                logger.debug(f"交叉验证: '{code}' 不在 stock_basic 中，跳过")

        return verified

    except Exception as e:
        logger.warning(f"交叉验证失败: {e}")
        return [
            {"ts_code": s.get("code", ""), "name": s.get("name", ""),
             "chain": s.get("chain", ""), "verified": False,
             "relevant": s.get("relevant", True)}
            for s in stocks if s.get("code")
        ]
