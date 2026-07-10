# Wiki-Centric 架构 v1.0 — 实施计划

> 日期: 2026-07-09 | 关联 Spec: `docs/specs/2026-06-29-prosperity-strategy-design.md` §11  
> 版本: v1.0.0 | 状态: Phase 0+1 实施中

## 概述

将 wiki 从流水线末端「归档输出」升级为所有 agent 共用的「中枢知识库」。
Phase 0+1 聚焦**基础设施**：定义 YAML 协议 + 学习层产出 YAML + coordinator 加载链路 + agent 签名预留。
Phase 2+（Hypothesize/Verify/Counter 分析飞轮）另案讨论。

---

## Phase 0：YAML Schema + LearningAgent 扩写

### 改动文件

| 文件 | 动作 | 说明 |
|------|------|------|
| `data/prosperity/wiki/industries/存储芯片.yaml` | **新增** | 样本 YAML（基于已有 存储芯片.md 手工翻译） |
| `backend/rules/prosperity/prompts/learning_prompt.md` | **修改** | 新增 §8 YAML 输出要求 |
| `backend/app/strategies/prosperity/agents/learning_agent.py` | **修改** | `learn()` 从 LLM 输出中分离 Markdown + YAML，分别写入 |

### 详细

#### 1. 样本 YAML
- 路径: `data/prosperity/wiki/industries/存储芯片.yaml`
- 内容: 基于已有 `存储芯片.md` 的 7 节内容手工翻译为结构化 YAML
- 用途: 作为 Schema 的参考实现 + 供 Phase 1 `_load_chain_model()` 测试

#### 2. Learning Prompt 改动
- 新增 §8：「同时输出 YAML 格式的产业链结构化数据」
- YAML 须放在 ` ```yaml ` 代码块中
- LLM 提示：基于前 7 节的 Markdown 内容，提取为结构化 YAML

#### 3. LearningAgent 改动
- `learn()` 返回值从 `str`（纯 Markdown）改为 `tuple[str, dict | None]` → `(markdown, yaml_dict)`
- 新增 `_extract_yaml()` 方法：从 LLM 输出中解析 ` ```yaml ` 代码块
- `_clean_output()` 不再丢弃 YAML 块（已有逻辑只找 `## 产业图谱`）
- Coordinator 侧 `_run_learning_agent()` 负责写入 YAML 文件

---

## Phase 1：Coordinator `_load_chain_model()` + Agent 签名预留

### 改动文件

| 文件 | 动作 | 说明 |
|------|------|------|
| `backend/app/strategies/prosperity/coordinator.py` | **修改** | 新增 `_load_chain_model()`；所有 agent 调用传入 `chain_model` |
| `backend/app/strategies/prosperity/agents/hypothesize_agent.py` | **修改** | 签名新增 `chain_model=None` 参数（pass-through，Phase 2 消费） |
| `backend/app/strategies/prosperity/agents/verify_agent.py` | **修改** | 签名新增 `chain_model=None` 参数 |
| `backend/app/strategies/prosperity/agents/counter_agent.py` | **修改** | 签名新增 `history=None, chain_model=None` 两个参数 |
| `backend/app/strategies/prosperity/agents/screening_agent.py` | **修改** | 签名新增 `chain_model=None` 参数 |

### 详细

#### 1. `_load_chain_model()`
```python
def _load_chain_model(self, industry_name: str) -> dict | None:
    yaml_path = self.data_dir / "wiki" / "industries" / f"{industry_name}.yaml"
    if yaml_path.exists():
        import yaml
        return yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    return None
```
- 首次研究时 YAML 不存在 → 返回 `None`，各 agent 降级到当前行为
- 后续研究时自动加载

#### 2. `_run_learning_agent()` 改动
- 当前只写 Markdown → 新增写 YAML 文件
- 调用 `yaml.dump(yaml_dict, allow_unicode=True)` 写入

#### 3. Agent 签名变更（仅参数预留，不消费）
- `_run_hypothesize_agent()` → 传入 `chain_model`
- `_run_verify_agent()` → 传入 `chain_model`
- `_run_counter_agent()` → 传入 `chain_model` + `history`（**修复：Counter 之前没 history**）
- `_run_screening_agent()` → 传入 `chain_model`

每个 agent 的 `run` 方法新增 `chain_model=None` 参数，**Phase 1 只传不消费**（= None 时走现有逻辑，有值时 Phase 2 消费）。

#### 4. CounterAgent 补 `history`
这是 v0.10.0 遗留缺陷——CounterAgent 做上下游级联裁决却不知道历史上下文。Phase 1 先补签名，Phase 2 消费。

---

## 测试影响

- 现有测试可能因签名变更而需要更新传入参数
- `chain_model=None` 作为默认值，若无其他逻辑变更，应零回归

---

## 后续（Phase 2+，另案讨论）

- HypothesizeAgent 如何消费 YAML → 假设锚定产业链结构
- VerifyAgent 如何消费 YAML → 瓶颈表交叉验证
- CounterAgent 如何消费 YAML → 产业链感知级联（严重性最高）
- ScreeningAgent 如何消费 YAML → 多桶输出 + 角色标签
