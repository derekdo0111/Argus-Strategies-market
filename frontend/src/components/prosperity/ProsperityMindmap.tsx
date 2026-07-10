import { useState } from 'react';
import { HYPOTHESES, KG_DATA, SUMMARY } from './prosperity-data';
import type { HypothesisCard } from './prosperity-types';
import styles from './ProsperityMindmap.module.css';

// ── 层级配置 ──
const LEVELS = [
  { level: 0, label: 'L0 · 现状诊断', role: '— 可观测的产业事实', cssVar: '--l0' },
  { level: 1, label: 'L1 · 一阶推演', role: '— 从事实推导的判断', cssVar: '--l1' },
  { level: 2, label: 'L2 · 二阶矛盾', role: '— 前瞻风险', cssVar: '--l2' },
  { level: 3, label: 'L3 · 投资落点', role: '— 可执行策略', cssVar: '--l3' },
];

const STATUS_CONFIG: Record<string, { emoji: string; tag: string; cls: string }> = {
  confirmed: { emoji: '✅', tag: '已确认', cls: 'tagConfirmed' },
  partial: { emoji: '⚠️', tag: '部分验证', cls: 'tagPartial' },
  unverified: { emoji: '🔍', tag: '待验证', cls: 'tagUnverified' },
  broken: { emoji: '⚡', tag: '已证伪', cls: 'tagBroken' },
};

const STRENGTH_CONFIG: Record<string, { cls: string }> = {
  strong: { cls: 'strStrong' },
  moderate: { cls: 'strModerate' },
  broken: { cls: 'strBroken' },
  weak: { cls: 'strWeak' },
};

const CONNECTOR_LABELS = ['事实→推演', '推演→矛盾', '矛盾→策略'];

// ── 分组假设卡片按层级 ──
function groupByLevel(hs: HypothesisCard[]): Map<number, HypothesisCard[]> {
  const map = new Map<number, HypothesisCard[]>();
  for (const h of hs) {
    const list = map.get(h.chainLevel) || [];
    list.push(h);
    map.set(h.chainLevel, list);
  }
  return map;
}

// ── 推理链 → 高亮箭头 ──
function renderReasoning(text: string): JSX.Element[] {
  const parts = text.split(/( → )/);
  return parts.map((p, i) =>
    p === ' → ' ? <span key={i} className={styles.arr}>→</span> : <span key={i}>{p}</span>,
  );
}

// ── 子组件：假设卡片 ──
function HypothesisCardView({ card }: { card: HypothesisCard }) {
  const [expanded, setExpanded] = useState(false);
  const st = STATUS_CONFIG[card.status] || STATUS_CONFIG.unverified;

  return (
    <div
      className={`${styles.card} ${expanded ? styles.cardExpanded : ''}`}
      onClick={() => setExpanded(!expanded)}
    >
      <div className={styles.cardHeader}>
        <span className={styles.cardStatus}>{st.emoji}</span>
        <div className={styles.cardBody}>
          <div className={styles.cardId}>{card.id}</div>
          <div className={styles.cardTitle}>{card.title}</div>
          <div className={styles.cardTags}>
            <span className={`${styles.cardTag} ${styles[st.cls]}`}>{st.tag}</span>
            {card.timeHorizon && (
              <span className={`${styles.cardTag} ${styles.tagTime}`}>{card.timeHorizon}</span>
            )}
          </div>
        </div>
      </div>

      {expanded && (
        <div className={styles.cardDetail}>
          <div className={styles.dSection}>
            <div className={styles.dLabel}>📌 假设陈述</div>
            <div className={styles.dStmt}>{card.statement}</div>
          </div>

          <div className={styles.dSection}>
            <div className={styles.dLabel}>🔗 推理链</div>
            <div className={styles.dReason}>{renderReasoning(card.reasoning)}</div>
          </div>

          <div className={styles.dSection}>
            <div className={styles.dLabel}>🔬 验证诊断</div>
            <div className={styles.dVerify}>
              <span className={`${styles.strength} ${styles[STRENGTH_CONFIG[card.verification.strength].cls]}`}>
                {card.verification.strength}
              </span>
              {card.verification.note.split('\n').map((line, i) => (
                <span key={i}>{line}<br /></span>
              ))}
            </div>
          </div>

          <div className={styles.dSection}>
            <div className={styles.dLabel}>📊 跟踪指标</div>
            <div className={styles.dTrack}>
              {card.tracking.map((t, i) => (
                <span key={i}>
                  <b>{t.name}</b>（{t.freq}）{i < card.tracking.length - 1 ? ' · ' : ''}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── 知识图谱区块 ──
function KgSection() {
  return (
    <div className={styles.kgSection}>
      <div className={styles.kgTitle}>
        📚 行业知识图谱
        <span className={styles.kgTitleNote}>— 存储芯片产业链核心认知</span>
      </div>

      <div className={styles.kgSpotlight}>
        <span className={styles.kgSpotlightBadge}>🔥 当前最景气点</span>
        {KG_DATA.spotlight.map((item, i) => (
          <span key={i} className={styles.kgSpotlightItem}>{item}</span>
        ))}
      </div>

      <div className={styles.kgGrid}>
        {KG_DATA.grid.map((item, i) => (
          <div key={i} className={styles.kgItem}>
            <span className={styles.kgKey}>{item.key}</span>
            <span className={styles.kgVal}>{item.value}</span>
          </div>
        ))}
      </div>

      <div className={styles.kgChips}>
        {KG_DATA.chips.map((chip, i) => (
          <span
            key={i}
            className={`${styles.kgChip} ${chip.highlight ? styles.kgChipHighlight : ''}`}
          >
            {chip.label}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── 主组件 ──
export default function ProsperityMindmap() {
  const grouped = groupByLevel(HYPOTHESES);

  return (
    <div className={styles.container}>
      {/* 摘要卡片 */}
      <div className={styles.summaryCard}>
        <div className={styles.summaryInfo}>
          <h1 className={styles.summaryTitle}>{SUMMARY.industry}</h1>
          <div className={styles.summaryMeta}>
            <span>{SUMMARY.date}</span>
            <span>{SUMMARY.hypothesisCount}条假设 / 4层推理</span>
            <span>{SUMMARY.stockCount}只精选标的</span>
          </div>
        </div>
        <div
          className={`${styles.summarySignal} ${SUMMARY.signal === '高景气' ? styles.signalHot : SUMMARY.signal === '中景气' ? styles.signalWarm : styles.signalCool}`}
        >
          <span className={styles.signalIcon}>🔥</span>
          <span className={styles.signalLabel}>{SUMMARY.signal}</span>
        </div>
      </div>

      {/* 知识图谱 */}
      <KgSection />

      {/* L0-L3 推理链 */}
      {LEVELS.map((lv, idx) => {
        const items = grouped.get(lv.level) || [];
        if (items.length === 0) return null;

        return (
          <div key={lv.level}>
            <div className={styles.layerHeader}>
              <span
                className={styles.layerDot}
                style={{ backgroundColor: `var(${lv.cssVar})` }}
              />
              <span className={styles.layerTitle}>{lv.label}</span>
              <span className={styles.layerRole}>{lv.role}</span>
            </div>

            <div className={`${styles.cardRow} ${styles[`l${lv.level}`]}`}>
              {items.map((card) => (
                <div key={card.id} className={styles.cardCol}>
                  {card.derivesFrom.length > 0 && (
                    <span className={styles.depHint}>↑ {card.derivesFrom.join(', ')}</span>
                  )}
                  <HypothesisCardView card={card} />
                </div>
              ))}
            </div>

            {/* 连接线 */}
            {idx < LEVELS.length - 1 && (
              <div className={styles.connectorZone}>
                <svg viewBox="0 0 800 34" className={styles.connectorSvg}>
                  {items.map((_, ci) => {
                    const x = (ci + 0.5) * (800 / items.length);
                    return (
                      <line
                        key={ci}
                        x1={x}
                        y1={10}
                        x2={x}
                        y2={24}
                        stroke="var(--border-strong)"
                        strokeWidth={1}
                        opacity={0.4}
                      />
                    );
                  })}
                  <text
                    x={400}
                    y={18}
                    textAnchor="middle"
                    className={styles.flowText}
                  >
                    ⏬ {CONNECTOR_LABELS[idx] || ''}
                  </text>
                </svg>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
