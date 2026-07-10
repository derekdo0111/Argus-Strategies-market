import { useState, useMemo } from 'react';
import { STOCKS } from './prosperity-data';
import type { StockItem } from './prosperity-types';
import styles from './ProsperityStockPanel.module.css';

type SectorTab = 'upstream' | 'midstream' | 'downstream';

const TAB_LABELS: Record<SectorTab, string> = {
  upstream: '上游设备 · 6',
  midstream: '中游设计 · 6',
  downstream: '下游模组 · 6',
};

const RADAR_DIMS = [
  { key: 'adapterScore' as const, label: '景气适配', format: (v: number) => v.toFixed(2) },
  { key: 'qualityScore' as const, label: '基本面质量', format: (v: number) => v.toFixed(2) },
  { key: 'deductedProfitGrowth' as const, label: '扣非净利增速', format: (v: number) => v.toFixed(1) + '%' },
  { key: 'roe' as const, label: 'ROE', format: (v: number) => v.toFixed(1) + '%' },
  { key: 'grossMargin' as const, label: '毛利率', format: (v: number) => v.toFixed(1) + '%' },
  { key: 'revenueGrowth' as const, label: '营收增速', format: (v: number) => v.toFixed(1) + '%' },
];

// 归一化到 0-1
function normalize(v: number, min: number, max: number): number {
  return Math.max(0, Math.min(1, (v - min) / (max - min)));
}

// 六边形雷达图坐标
function radarPoints(values: number[]): string {
  const angles = [-90, -30, 30, 90, 150, 210];
  return values
    .map((v, i) => {
      const rad = (angles[i] * Math.PI) / 180;
      const r = 4 + v * 68;
      return `${(100 + r * Math.cos(rad)).toFixed(1)},${(100 + r * Math.sin(rad)).toFixed(1)}`;
    })
    .join(' ');
}

// 雷达网格：三个同心六边形
function RadarGrid(): JSX.Element {
  const levels = [1, 2, 3];
  return (
    <>
      {levels.map((lvl) => (
        <polygon
          key={lvl}
          points={radarPoints([1, 1, 1, 1, 1, 1].map(() => lvl * 0.25))}
          fill="none"
          stroke="var(--border-subtle)"
          strokeWidth={0.5}
        />
      ))}
    </>
  );
}

function RadarChart({ stock }: { stock: StockItem }) {
  const values = useMemo(() => {
    // 各维度归一化范围
    const ranges = [
      { val: stock.adapterScore, min: 0, max: 2.2 },
      { val: stock.qualityScore, min: 0, max: 1 },
      { val: stock.deductedProfitGrowth, min: -400, max: 800 },
      { val: Math.abs(stock.roe), min: -5, max: 70 },
      { val: stock.grossMargin, min: 0, max: 70 },
      { val: stock.revenueGrowth, min: 0, max: 500 },
    ];
    return ranges.map((r) => normalize(r.val, r.min, r.max));
  }, [stock]);

  const points = radarPoints(values);
  const angles = [-90, -30, 30, 90, 150, 210];
  const cx = 100, cy = 100;

  return (
    <div className={styles.radarOverlay}>
      <div className={styles.radarName}>{stock.name}</div>
      <div className={styles.radarBrief}>{stock.reason}</div>

      <svg className={styles.radarSvg} viewBox="0 0 200 200">
        {/* 网格 */}
        <RadarGrid />
        {/* 轴线 */}
        <line x1={cx} y1={28} x2={cx} y2={172} stroke="var(--border-subtle)" strokeWidth={0.5} />
        <line x1={162} y1={64} x2={38} y2={136} stroke="var(--border-subtle)" strokeWidth={0.5} />
        <line x1={162} y1={136} x2={38} y2={64} stroke="var(--border-subtle)" strokeWidth={0.5} />
        {/* 数据多边形 */}
        <polygon
          points={points}
          fill="oklch(52% 0.16 250 / 0.15)"
          stroke="var(--accent-primary)"
          strokeWidth={1.8}
        />
        {/* 数据点 */}
        {values.map((_, i) => {
          const rad = (angles[i] * Math.PI) / 180;
          const r = 4 + values[i] * 68;
          const px = cx + r * Math.cos(rad);
          const py = cy + r * Math.sin(rad);
          return <circle key={i} cx={px} cy={py} r={3} fill="var(--accent-primary)" />;
        })}
        {/* 标签 */}
        <text x={cx} y={12} textAnchor="middle" fontSize={8} fill="var(--text-tertiary)" fontWeight={600}>景气适配</text>
        <text x={173} y={58} textAnchor="start" fontSize={8} fill="var(--text-tertiary)">基本面质量</text>
        <text x={173} y={142} textAnchor="start" fontSize={8} fill="var(--text-tertiary)">扣非净利增速</text>
        <text x={cx} y={186} textAnchor="middle" fontSize={8} fill="var(--text-tertiary)">ROE</text>
        <text x={27} y={142} textAnchor="end" fontSize={8} fill="var(--text-tertiary)">毛利率</text>
        <text x={27} y={58} textAnchor="end" fontSize={8} fill="var(--text-tertiary)">营收增速</text>
      </svg>

      <div className={styles.radarMetrics}>
        {RADAR_DIMS.map((dim) => (
          <div key={dim.key} className={styles.radarMetric}>
            <span className={styles.rmLabel}>{dim.label}</span>
            <span className={styles.rmVal}>{dim.format(Number(stock[dim.key]))}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── 主组件 ──
interface ProsperityStockPanelProps {
  selectedStock?: { ts_code?: string; name?: string } | null;
  onSelectStock?: (ts_code: string, name: string) => void;
}

export default function ProsperityStockPanel({ onSelectStock }: ProsperityStockPanelProps) {
  const [activeTab, setActiveTab] = useState<SectorTab>('upstream');
  // 默认选中 Rank 1 的股票，雷达图始终可见
  const [selectedName, setSelectedName] = useState<string>(STOCKS.upstream[0].name);

  const stocks = STOCKS[activeTab];
  const selected = stocks.find((s) => s.name === selectedName) || stocks[0];

  const handleSelect = (stock: StockItem) => {
    setSelectedName(stock.name);
    if (onSelectStock) {
      // 高景气策略可能没有 ts_code，用 name 做标识
      onSelectStock(stock.name, stock.name);
    }
  };

  return (
    <div className={styles.container}>
      {/* 头部 */}
      <div className={styles.header}>
        股池 <span className={styles.count}>18 只</span>
        <span className={styles.scoreHint}>分数 = 景气适配分</span>
      </div>

      {/* 扇区 Tab */}
      <div className={styles.tabs}>
        {(Object.keys(TAB_LABELS) as SectorTab[]).map((tab) => (
          <div
            key={tab}
            className={`${styles.tab} ${activeTab === tab ? styles.tabActive : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {TAB_LABELS[tab]}
          </div>
        ))}
      </div>

      {/* 股票列表 */}
      <div className={styles.stockList}>
        {stocks.map((stock) => (
          <div
            key={stock.name}
            className={`${styles.stockItem} ${selectedName === stock.name ? styles.selected : ''}`}
            onClick={() => handleSelect(stock)}
          >
            <span className={`${styles.stockRank} ${stock.rank <= 3 ? styles.rankTop : ''}`}>
              {stock.rank}
            </span>
            <div className={styles.stockInfo}>
              <div className={styles.stockName}>{stock.name}</div>
              <div className={styles.stockReason}>{stock.reason}</div>
            </div>
            <div className={styles.stockScore}>
              <span className={`${styles.scoreVal} ${stock.compositeScore >= 0.9 ? styles.scoreGold : ''}`}>
                {stock.compositeScore.toFixed(2)}
              </span>
              <span className={styles.scoreUnit}>景气适配分</span>
            </div>
          </div>
        ))}
      </div>

      {/* 雷达图 — 始终显示 */}
      <RadarChart stock={selected} />
    </div>
  );
}
