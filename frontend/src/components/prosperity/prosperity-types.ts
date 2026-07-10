// ── 高景气策略前端类型 ──

/** 假设卡片 */
export interface HypothesisCard {
  id: string;
  title: string;
  statement: string;
  chainLevel: number; // 0-3
  status: 'confirmed' | 'partial' | 'unverified' | 'broken';
  derivesFrom: string[]; // 上游依赖
  timeHorizon: string;
  verification: {
    strength: 'strong' | 'moderate' | 'broken' | 'weak';
    note: string;
  };
  reasoning: string;  // 推理链（带 → 符号）
  tracking: { name: string; freq: string }[];
}

/** 股票 */
export interface StockItem {
  name: string;
  reason: string;
  rank: number;
  // 筛选分数
  compositeScore: number;  // 景气适配分
  adapterScore: number;
  qualityScore: number;
  // 财务指标
  roe: number;
  grossMargin: number;
  revenueGrowth: number;
  deductedProfitGrowth: number;
  risk: number;
  // 雷达维度归一化 0-1 在组件内计算
}

/** 扇区 */
export interface Sector {
  name: string;
  heat: 'hot' | 'warm' | 'cool';
  stockCount: number;
}

/** 行业知识图谱 */
export interface KgData {
  spotlight: string[];
  grid: { key: string; value: string }[];
  chips: { label: string; highlight: boolean }[];
}

/** 景气摘要 */
export interface ProsperitySummary {
  industry: string;
  signal: string; // "高景气" | "中景气" | "低景气"
  date: string;
  hypothesisCount: number;
  stockCount: number;
}
