/** 策略信息 */
export interface Strategy {
  id: string;
  name: string;
  description: string;
  status: 'active' | 'inactive';
}

/** QRV 评分维度 */
export interface QrvScores {
  Q1_business: number;
  Q2_moat: number;
  Q3_growth: number;
  R1_environment: number;
  R2_management: number;
  R3_control?: number;
  V1_value_trap: number;
  V2_percentile?: number;
  V3_stress_test: number;
  total: number;
  Q_weighted?: number;
  R_weighted?: number;
  V_weighted?: number;
}

/** 股池条目 */
export interface StockPoolItem {
  ts_code: string;
  name: string;
  industry: string;
  pr: number;
  pe: number;
  pb: number;
  dividend_yield: number;
  market_cap: number;
  /** 门控结果 */
  cq_passed?: boolean;
  pr_passed?: boolean;
  /** 是否有 QRV 分析报告 */
  has_report?: boolean;
  /** QRV 评分 (可选，未分析则无) */
  scores?: QrvScores;
}

/** 门控结果 */
export interface GateResult {
  cash_quality: {
    overall_passed: boolean;
    failed_dimensions: number[];
    dimension_1_opcf_to_netprofit: { passed: boolean; avg_3y: number };
    dimension_2_fcf_positive_years: { passed: boolean; positive_count: number };
    dimension_3_receivables_ratio: { passed: boolean; avg_3y: number };
    dimension_4_inventory_stability: { passed: boolean; cv: number };
    dimension_5_ocf_stability: { passed: boolean; cv: number };
  };
  penetration_return: {
    pr_result: {
      pr: number;
      risk_free_rate: number;
      threshold: number;
      passed: boolean;
    };
    disposable_cash: { disposable_cash: number };
    distribution_ratio: { ratio: number };
    repurchase: { avg_repurchase_3y: number };
  };
  qrv_summary?: string;
  scores?: QrvScores;
}

/** 分析报告 */
export interface AnalysisReport {
  ts_code: string;
  name: string;
  report_markdown: string;
  generated_at: string;
}
