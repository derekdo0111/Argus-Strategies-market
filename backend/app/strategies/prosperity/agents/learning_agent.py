"""LearningAgent — 产业学习层（v2 — Wiki-Centric Phase 0）

在假设生成之前，系统地学习行业产业链结构。
输出产业图谱 Markdown + 伴生 YAML 结构化文件。

核心原则：
1. 一次 LLM 调用 — prompt 模板独立文件，不硬编码
2. 双重输出 — Markdown（人类可读）+ YAML（Agent 可消费）
3. 信源必引用 — 每条事实标注 [信源N]，无信源不写（反幻觉）
4. 只输出内容 — 不写数据库，不操作文件（Coordinator 负责）

v2 变更：
- learn() 返回 tuple[(str, dict|None)] → (markdown, yaml_dict)
- 新增 _extract_yaml() 从 LLM 输出中解析 ```yaml 代码块
- _clean_output() 新增 strip_yaml 参数，保留 YAML 块供解析
"""

import logging
import re
import requests
import yaml
from pathlib import Path
from typing import Optional, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)


class LearningAgent:
    """产业图谱构建 Agent — 从搜索素材中提取结构化行业知识"""

    def __init__(self, rules_dir: Optional[Path] = None):
        self.rules_dir = rules_dir or settings.PROSPERITY_RULES_DIR
        self._load_template()

    def _load_template(self) -> None:
        """加载 prompt 模板"""
        template_path = self.rules_dir / "prompts" / "learning_prompt.md"
        if template_path.exists():
            self.template = template_path.read_text(encoding="utf-8")
            logger.debug(f"Loaded learning prompt template from {template_path}")
        else:
            logger.warning(f"Learning prompt template not found: {template_path}")
            self.template = ""

    def learn(self, industry_name: str, search_result: dict) -> Tuple[str, Optional[dict]]:
        """
        从搜索结果中构建产业图谱。

        Args:
            industry_name: 行业名称（如「可控核聚变」）
            search_result: SearchAgent 返回的搜索结果

        Returns:
            (产业图谱 Markdown, 结构化 YAML dict)，失败返回 ("", None)
        """
        logger.info(f"LearningAgent: building industry model for {industry_name}")

        if not self.template:
            logger.error("LearningAgent: prompt template not loaded")
            return "", None

        # 格式化搜索素材
        search_text = self._format_search_results(search_result)
        if not search_text:
            logger.warning("LearningAgent: no search results to learn from")
            return "", None

        # 构建 prompt
        prompt = self.template.format(
            industry_name=industry_name,
            search_results=search_text,
        )

        # 调用 LLM
        print(f"  [learning] 等待LLM返回（构建产业图谱+YAML...）")
        llm_output = self._call_llm(prompt)

        if not llm_output:
            return "", None

        # 提取 YAML（在清理 Markdown 前，保留完整输出）
        yaml_dict = self._extract_yaml(llm_output, industry_name)

        # 清理 Markdown 输出（去掉 YAML 块，保留纯 Markdown）
        model_md = self._clean_output(llm_output)

        logger.info(
            f"LearningAgent: industry model generated "
            f"(md={len(model_md)} chars, yaml={'ok' if yaml_dict else 'missing'})"
        )
        return model_md, yaml_dict

    def _extract_yaml(self, llm_output: str, industry_name: str) -> Optional[dict]:
        """从 LLM 输出中提取 ```yaml 代码块并解析"""
        # 匹配 ```yaml ... ``` 代码块
        yaml_match = re.search(r"```yaml\s*\n(.*?)```", llm_output, re.DOTALL)
        if not yaml_match:
            logger.warning("LearningAgent: no YAML block found in LLM output")
            return None

        yaml_text = yaml_match.group(1).strip()
        try:
            parsed = yaml.safe_load(yaml_text)
            if not isinstance(parsed, dict):
                logger.warning("LearningAgent: YAML parsed as non-dict, ignoring")
                return None
            # 确保 industry 字段存在
            if "industry" not in parsed:
                parsed["industry"] = industry_name
            logger.info(
                f"LearningAgent: YAML parsed successfully, "
                f"segments={len(parsed.get('chain', {}).get('segments', []))}"
            )
            return parsed
        except yaml.YAMLError as e:
            logger.warning(f"LearningAgent: YAML parse error: {e}")
            return None

    def _format_search_results(self, search_result: dict) -> str:
        """将搜索结果格式化为编号文本，供 prompt 模板使用"""
        results = search_result.get("results", [])
        if not results:
            return ""

        lines = []
        for i, r in enumerate(results):
            title = r.get("title", "")
            content = r.get("content", "")[:400]
            url = r.get("url", "")

            lines.append(f"[{i + 1}] {title}")
            if content:
                lines.append(f"    {content}")
            if url:
                lines.append(f"    来源: {url}")
            lines.append("")

        return "\n".join(lines)

    def _call_llm(self, prompt: str) -> str:
        """调用 DeepSeek LLM（temperature=0 确保输出确定性）"""
        api_key = getattr(settings, "LLM_API_KEY", "")
        if not api_key:
            logger.warning("LLM_API_KEY not configured, LearningAgent skipped")
            return ""

        try:
            resp = requests.post(
                f"{settings.LLM_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.LLM_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "你是行业研究分析师。请基于搜索素材构建产业图谱，严格按要求的结构输出。"
                                "先输出 Markdown 7 节，再输出 YAML 结构化数据。"
                                "不要输出要求之外的任何内容（不要开场白、不要总结）。"
                                "每条事实必须标注信源编号。"
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": settings.LLM_MAX_TOKENS,
                },
                timeout=180,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            else:
                logger.error(f"LLM returned {resp.status_code}: {resp.text[:300]}")
                return ""
        except Exception as e:
            logger.error(f"LearningAgent LLM call failed: {e}")
            return ""

    def _clean_output(self, llm_output: str) -> str:
        """清理 LLM 输出 —— 切除开场白 + 移除 YAML 块，保留纯 Markdown"""
        # 找第一个 ## 产业图谱 标题
        match = re.search(r"##\s+产业图谱", llm_output)
        if match:
            llm_output = llm_output[match.start():]

        # 如果输出以 ### 开头（缺少父级标题），补上
        if llm_output.strip().startswith("###"):
            llm_output = "## 产业图谱\n\n" + llm_output

        # 移除 YAML 代码块（Markdown 页面不需要 YAML）
        llm_output = re.sub(r"```yaml\s*\n.*?```", "", llm_output, flags=re.DOTALL)

        return llm_output.strip()
