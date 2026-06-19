import type { QrvScores } from '../types';
import styles from './ScoreCard.module.css';

interface ScoreCardProps {
  scores: QrvScores;
  compact?: boolean;
}

interface DimItem {
  key: string;
  label: string;
  value: number;
  group: 'Q' | 'R' | 'V';
}

const DIMENSIONS: DimItem[] = [
  { key: 'Q1', label: '生意本质', value: 0, group: 'Q' },
  { key: 'Q2', label: '护城河', value: 0, group: 'Q' },
  { key: 'Q3', label: '增长引擎', value: 0, group: 'Q' },
  { key: 'R1', label: '外部环境', value: 0, group: 'R' },
  { key: 'R2', label: '管理层', value: 0, group: 'R' },
  { key: 'R3', label: '控股结构', value: 0, group: 'R' },
  { key: 'V1', label: '价值陷阱', value: 0, group: 'V' },
  { key: 'V2', label: '历史分位', value: 0, group: 'V' },
  { key: 'V3', label: '压力测试', value: 0, group: 'V' },
];

const SCORE_MAP: Record<string, keyof QrvScores> = {
  Q1: 'Q1_business',
  Q2: 'Q2_moat',
  Q3: 'Q3_growth',
  R1: 'R1_environment',
  R2: 'R2_management',
  R3: 'R3_control',
  V1: 'V1_value_trap',
  V2: 'V2_percentile',
  V3: 'V3_stress_test',
};

function getScoreColor(value: number): string {
  if (value >= 8) return styles.barHigh;
  if (value >= 5) return styles.barMid;
  return styles.barLow;
}

export default function ScoreCard({ scores, compact = false }: ScoreCardProps) {
  const dims = DIMENSIONS.map((d) => ({
    ...d,
    value: scores[SCORE_MAP[d.key]] ?? 0,
  }));

  const groups = [
    { key: 'Q', label: 'Q 质量', dims: dims.filter((d) => d.group === 'Q'), subscore: scores.Q_weighted ?? 0 },
    { key: 'R', label: 'R 韧性', dims: dims.filter((d) => d.group === 'R'), subscore: scores.R_weighted ?? 0 },
    { key: 'V', label: 'V 估值', dims: dims.filter((d) => d.group === 'V'), subscore: scores.V_weighted ?? 0 },
  ];

  return (
    <div className={`${styles.card} ${compact ? styles.compact : ''}`}>
      <div className={styles.header}>
        <div className={styles.titleRow}>
          <span className={styles.title}>QRV 综合打分卡</span>
          <span className={styles.totalScore}>{scores.total.toFixed(1)}<span className={styles.totalMax}>/10</span></span>
        </div>
        <div className={styles.totalBar}>
          <div
            className={styles.totalFill}
            style={{ width: `${scores.total * 10}%` }}
          />
        </div>
      </div>

      <div className={styles.groups}>
        {groups.map((g) => (
          <div key={g.key} className={styles.group}>
            <div className={styles.groupHeader}>
              <span className={styles.groupLabel}>{g.label}</span>
              <span className={styles.groupScore}>{g.subscore.toFixed(1)}</span>
            </div>
            {g.dims.map((d) => (
              <div key={d.key} className={styles.dim}>
                <span className={styles.dimLabel}>{d.label}</span>
                <div className={styles.dimBar}>
                  <div
                    className={`${styles.dimFill} ${getScoreColor(d.value)}`}
                    style={{ width: `${d.value * 10}%` }}
                  />
                </div>
                <span className={styles.dimValue}>{d.value.toFixed(1)}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
