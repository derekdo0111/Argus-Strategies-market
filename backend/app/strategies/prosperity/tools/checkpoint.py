"""CheckpointStore — 管道中间状态持久化，支持分段验证回放。

将 Coordinator 各步骤的中间输出保存为 YAML checkpoint，后续可从任意步骤
加载 checkpoint 并仅重跑下游 Agent，无需重复 Tavily 搜索和历史 LLM 调用。

目录结构：
  data/prosperity/raw/{industry}/checkpoints/
    ├── search.checkpoint.yaml
    ├── hypothesize.checkpoint.yaml
    ├── verify.checkpoint.yaml
    ├── counter.checkpoint.yaml
    ├── screening.checkpoint.yaml
    └── report.checkpoint.yaml
"""

import copy
import yaml
from datetime import datetime
from pathlib import Path
from typing import Optional

# 步骤名称 → checkpoint 文件名
STEP_FILES = {
    "search":       "search.checkpoint.yaml",
    "hypothesize":  "hypothesize.checkpoint.yaml",
    "verify":       "verify.checkpoint.yaml",
    "counter":      "counter.checkpoint.yaml",
    "screening":    "screening.checkpoint.yaml",
    "report":       "report.checkpoint.yaml",
}

# 步骤的输入依赖（上一个步骤）
STEP_DEPENDENCY = {
    "hypothesize": "search",
    "verify":      "hypothesize",
    "counter":     "verify",
    "screening":   "counter",
    "report":      "screening",
}


class CheckpointStore:
    """管道中间状态持久化。"""

    def __init__(self, data_dir: Path, industry_name: str):
        self.data_dir = data_dir
        self.industry_name = industry_name
        self.checkpoint_dir = data_dir / "raw" / industry_name / "checkpoints"

    def ensure_dir(self) -> None:
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, step: str) -> Path:
        filename = STEP_FILES.get(step, f"{step}.checkpoint.yaml")
        return self.checkpoint_dir / filename

    # ── 写入 ──────────────────────────────────────

    def save(self, step: str, **kwargs) -> None:
        """保存某步骤的 checkpoint。

        自动添加时间戳和行业名。
        """
        self.ensure_dir()
        data = {
            "industry": self.industry_name,
            "step": step,
            "saved_at": datetime.now().isoformat(),
            **kwargs,
        }
        with open(self._path(step), "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    # ── 读取 ──────────────────────────────────────

    def load(self, step: str) -> Optional[dict]:
        """加载某步骤的 checkpoint。返回 dict 或 None（文件不存在）。"""
        path = self._path(step)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def load_deepcopy(self, step: str):
        """加载并 deepcopy（安全修改不回写原始文件）。"""
        data = self.load(step)
        if data is None:
            return None
        return copy.deepcopy(data)

    # ── 步骤依赖 ──────────────────────────────────

    def dependency_chain(self, target_step: str) -> list[str]:
        """返回从 search 到 target_step 之前的所有步骤名（用于 record 时判断是否需要重拉）。"""
        chain = []
        step = target_step
        while step in STEP_DEPENDENCY:
            dep = STEP_DEPENDENCY[step]
            chain.insert(0, dep)
            step = dep
        return chain

    def missing_dependencies(self, target_step: str) -> list[str]:
        """返回 target_step 所需但缺失的 checkpoint 列表。"""
        return [s for s in self.dependency_chain(target_step) if self.load(s) is None]

    def all_checkpoints_exist(self, target_step: str = "report") -> bool:
        """检查从 search 到 target_step 的所有 checkpoint 是否已存在。"""
        steps_to_check = ["search"] + self.dependency_chain(target_step) + [target_step]
        for s in steps_to_check:
            if s not in self.dependency_chain(target_step) and s not in ["search", target_step]:
                continue
            if self.load(s) is None:
                return False
        # 专门检查每一步
        for s in steps_to_check:
            if not self._path(s).exists():
                return False
        return True

    # ── 列表 ──────────────────────────────────────

    def list_checkpoints(self) -> list[str]:
        """列出已存在的 checkpoint 步骤名。"""
        if not self.checkpoint_dir.exists():
            return []
        result = []
        for step, filename in STEP_FILES.items():
            if (self.checkpoint_dir / filename).exists():
                result.append(step)
        return result

    def clear(self) -> None:
        """清除该行业的所有 checkpoint。"""
        if self.checkpoint_dir.exists():
            for f in self.checkpoint_dir.glob("*.checkpoint.yaml"):
                f.unlink()
