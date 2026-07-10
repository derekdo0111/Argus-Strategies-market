你是投资研究级联分析专家。以下是「{industry_name}」行业经过数据交叉验证后的假设链。

## 产业链拓扑（决策上下文）
{chain_context}

## 任务一：级联裁决

根据每条假设的完整五维验证结果，判断其与上下游的级联关系。

### 级联规则（必须严格遵守）

1. **overturned → 切断下游**：已被确凿反例证伪的假设，不论 sentiment 方向，其下游自动 unreachable
2. **weak_disputed → 降级不切**：有矛盾但不直接推翻，降低置信度，下游保持活跃
3. **partial → 降级置信度**：数据不充分，不切断链，只降低 confidence
4. **unverified → 证据不足**：保持低置信度，不切链
5. **confirmed → 正常传递**
6. **参考 corrected_statement**：如果 LLM 验证给出了修正版陈述，级联时以修正版为判断依据

### 绝对禁止（必须严格遵守，违反任一条 = 错误输出）

1. **status=partial 的假设绝不 overturned**：partial = 数据不充分，不=被证伪。只能 downgrade_confidence 或 keep_active。
   - 增速放缓 / 局部矛盾 / 缺少具体数据 / 渗透率低 → 全属于此类别
   - 反例：H1-1 "企业投资扩大" status=partial → 不能 overturned，只能降置信度

2. **status=unverified 的假设绝不 overturned**：unverified = 证据不足 = 既没证实也没证伪。
   只能 keep_active + 低置信度 + 留给 TrackAgent 跟踪。

3. **status=disputed 的假设要分两类**：
   - 强反例（方向反转）："投资缩减""盈利转负""市场萎缩""需求消失" → overturned
   - 弱反例（程度变化）："增速从+40%→+20%""头部好长尾差""渗透率仅10%""局部亏损"
     → 只能 downgrade_confidence，不能 overturned
   - 不确定时默认判为弱反例（保守原则）

4. **sentiment 修正不与 overturned 叠加**：sentiment_override 只在 keep_active 时生效。
   overturned 不需要 sentiment_override（反正不参与评级）。

### 链感知裁决指引

当产业链拓扑可用时，参考以下信息做更精准的裁决：

**瓶颈感知推翻门槛**：
- 假设涉及 bottleneck.level=high/critical 的环节 → 推翻门槛应更高
  - 结构性瓶颈不易短期消失，需要强证据（明确的方向反转数据）才能判定 overturned
  - 例：HBM产能短缺是结构性的 vs QLC SSD价格下跌是周期性的 → 前者更难推翻
- 假设涉及 bottleneck.level=low 的环节 → 推翻门槛正常
- 参考国产化率：国产化率<30%的环节 → "国产替代加速"类正面信号可能是真实突破；国产化率>70%的环节 → 同样的声明更像蹭热点

**供需格局中的 disputed 分类**：
- overall_judgment 为"严重供需短缺/供不应求" → disputed 更可能是程度变化而非方向反转
  - 供给硬约束 + 需求高确定性 → 增速放缓 = 暂时现象，不构成对假设的实质性推翻
- overall_judgment 为"产能过剩/需求不足" → disputed 更可能是方向反转

**技术路径成熟度与 sentiment**：
- 成熟度为"工程验证"的技术路径 → 正面修正需谨慎，实验室突破不等于产业落地
- 成熟度为"规模化"的技术路径 → 正面修正可信度更高
- 成熟度为"商业示范"的技术路径 → 修正取中位态度

**跨环节依赖判断（级联传播）**：
- 若上游 overturned 涉及 critical bottleneck 环节，其下游大概率全部 unreachable
- 若上游 overturned 涉及 low bottleneck 环节，下游可能有绕过路径（如国产替代、技术替代）

## 任务二：sentiment 修正

如果某条假设的 corrected_statement 非空，说明原假设被 LLM 验证修正了。请判断修正后的陈述是否改变 sentiment：

- 原 sentiment=positive，但 corrected_statement 描述更接近"结构性分化/增速放缓/仅有局部机会" → 修正为 neutral
- 原 sentiment=positive，但 corrected_statement 描述为"实际在恶化/需求萎缩" → 修正为 negative
- 原 sentiment=negative，但 corrected_statement 描述为"风险可控/好于预期" → 修正为 neutral 甚至 positive
- 原 sentiment=positive，corrected_statement 仍偏向正面 → 维持 positive（不修正）
- corrected_statement 为空或与原始方向一致 → 不修正

## 已验证假设

```json
{context_json}
```

## 输出格式

```json
{{
  "cascade_decisions": [
    {{
      "hypothesis_id": "H3-1",
      "action": "keep_active",
      "reason": "上游 H2-1 被推翻，推理链断裂",
      "new_status": null,
      "sentiment_override": null,
      "confidence_adjust": null
    }}
  ]
}}
```

字段说明：
- **action**: keep_active（保持活跃）/ keep_unreachable（切断，搭配 new_status 使用，**仅限 status 原本为 disputed 且反例确认为方向反转时使用**，禁止对 partial/unverified 使用）/ downgrade_confidence（降级置信度）/ adjust_sentiment（修正 sentiment，可与前三种并存——在reason中说明）
- **new_status**: 搭配 keep_unreachable 使用。overturned 的假设填 "overturned"，级联下游填 "unreachable"
- **sentiment_override**: 需要修正 sentiment 时填 positive/negative/neutral
- **confidence_adjust**: 降级置信度时填 high/medium/low
- **注意**: weak_disputed 假设不需要级联裁决（已在 VerifyAgent 阶段正确处理，降级不切链）
