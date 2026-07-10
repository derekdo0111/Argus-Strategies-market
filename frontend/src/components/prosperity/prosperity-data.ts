// ── 高景气策略 Mock 数据（存储芯片行业）──
// 后续接后端 API 替换

import type { HypothesisCard, StockItem, Sector, KgData, ProsperitySummary } from './prosperity-types';

export const SECTORS: Sector[] = [
  { name: '存储芯片', heat: 'hot', stockCount: 18 },
  { name: 'AI算力', heat: 'hot', stockCount: 24 },
  { name: '半导体设备', heat: 'warm', stockCount: 15 },
  { name: '先进封装', heat: 'warm', stockCount: 12 },
  { name: '新能源', heat: 'cool', stockCount: 31 },
  { name: '医疗器械', heat: 'cool', stockCount: 19 },
  { name: '消费电子', heat: 'warm', stockCount: 22 },
];

export const SUMMARY: ProsperitySummary = {
  industry: '存储芯片行业景气分析',
  signal: '高景气',
  date: '2026-07-10',
  hypothesisCount: 12,
  stockCount: 18,
};

export const KG_DATA: KgData = {
  spotlight: ['HBM缺口 4-5%', 'AI存储年增 60%+', 'DDR5渗透 >50%', '两长扩产提速', 'HBM4 2026量产'],
  grid: [
    { key: '市场规模', value: '2026年全球存储芯片 ~$200B，DRAM占55%，NAND占40%' },
    { key: '增长驱动', value: 'AI服务器存储需求年增60%+，HBM 2024-2028 CAGR 45%+' },
    { key: '供需格局', value: 'HBM严重短缺(缺口4-5%)，通用存储供给被压缩' },
    { key: '技术路线', value: 'HBM4预计2026量产，DDR5渗透率超50%，3D NAND向300层+' },
    { key: '中国位置', value: '国产化率35%，长江存储232层NAND量产，长鑫科技DDR5突破' },
    { key: '竞争格局', value: '三星/SK海力士/美光占DRAM 95%+，HBM近乎双寡头' },
    { key: '上游设备', value: '刻蚀/薄膜沉积/CMP/测试四大类，国产化率<30%，两长拉动需求' },
    { key: '下游应用', value: 'AI服务器(最大增量)+手机+PC+汽车，模组厂直接受益涨价' },
  ],
  chips: [
    { label: 'HBM3E', highlight: true }, { label: 'DDR5', highlight: true },
    { label: '3D NAND', highlight: true }, { label: '先进封装', highlight: false },
    { label: '国产替代', highlight: true }, { label: '两长扩产', highlight: true },
    { label: 'AI算力', highlight: true }, { label: '库存周期', highlight: false },
  ],
};

export const HYPOTHESES: HypothesisCard[] = [
  // ── L0 · 现状诊断 ──
  {
    id: 'H0-1', chainLevel: 0, status: 'confirmed', derivesFrom: [], timeHorizon: '当前',
    title: 'AI与算力驱动存储芯片进入超级景气周期',
    statement: 'AI与算力需求驱动存储芯片进入超级景气周期，2026年全品类涨价贯穿全年，HBM赛道景气有望延续至2028年。',
    reasoning: 'AI服务器与数据中心扩容 → 直接拉动存储容量与带宽需求 → 全品类涨价、头部公司业绩高增',
    verification: { strength: 'strong', note: '因果链强 — 多信源交叉验证\n信源[1][4][7][9]确认；行业营收增速中位23.21%、净利增速21.72%' },
    tracking: [
      { name: '全球存储芯片月度销售额', freq: '月' },
      { name: 'DRAM合约价月度环比', freq: '月' },
    ],
  },
  {
    id: 'H0-2', chainLevel: 0, status: 'partial', derivesFrom: [], timeHorizon: '当前',
    title: '全球HBM产能严重短缺，通用型存储供需缺口创15年新高',
    statement: '全球HBM产能严重短缺，原厂将七成以上先进产能投向HBM，通用型存储供给大幅压缩，DRAM/NAND供需缺口创15年新高。',
    reasoning: 'HBM生产复杂、单颗晶圆消耗是传统DRAM的3倍以上 → 原厂优先保障HBM → 通用DRAM/NAND产能不足，供需缺口扩大至4%~5%',
    verification: { strength: 'strong', note: '因果链强 — 产业共识\n信源[7]指出15年最严重供需短缺；Tushare行业数据与高景气方向一致' },
    tracking: [
      { name: 'HBM产能利用率', freq: '季' },
      { name: 'DRAM/NAND供需缺口', freq: '季' },
    ],
  },
  {
    id: 'H0-3', chainLevel: 0, status: 'confirmed', derivesFrom: [], timeHorizon: '当前',
    title: '中国存储产业链加速扩产，国产化率提升至35%',
    statement: '长江存储、长鑫科技资本开支提升，国产化率提升至35%，设备企业订单爆发。',
    reasoning: '存储高景气 + 国产替代战略 → 两长加大资本开支 → 国产设备采购占比显著提升至35%',
    verification: { strength: 'strong', note: '因果链强 — 政策+产业双重驱动\n信源[5][6][9]确认扩产加速，国产化率35%有明确数据支撑' },
    tracking: [
      { name: '国产设备采购占比', freq: '季' },
      { name: '长鑫科技资本开支', freq: '季' },
    ],
  },

  // ── L1 · 一阶推演 ──
  {
    id: 'H1-1', chainLevel: 1, status: 'unverified', derivesFrom: ['H0-1', 'H0-2'], timeHorizon: '2026-2027Q1',
    title: '全品类涨价超预期，Q3 DRAM合约价环比涨幅上调至10-20%',
    statement: '原厂产能向HBM倾斜放大通用存储供需矛盾，消费级存储涨价超预期。',
    reasoning: 'H0-1景气叠加H0-2结构性缺货 → 原厂将更多产能分配给HBM → 消费级存储供给压缩 → 合约价涨幅超预期上修',
    verification: { strength: 'moderate', note: '因果链中等 — 缺乏具体数据支撑\nTrendforce预计Q3涨幅13-18%，与假设区间重叠但未体现「超预期上调」过程' },
    tracking: [
      { name: 'Mobile DRAM合约价环比', freq: '月' },
      { name: 'Enterprise SSD合约价环比', freq: '月' },
    ],
  },
  {
    id: 'H1-2', chainLevel: 1, status: 'partial', derivesFrom: ['H0-3'], timeHorizon: '2026-2027',
    title: '国产设备业绩爆发，北方华创、中微公司等进入爆发期',
    statement: '本土存储扩产直接拉动设备采购，设备龙头新增订单和营收进入爆发期。',
    reasoning: 'H0-3中两长资本开支大幅提升，国产设备采购占比升至35% → 刻蚀、薄膜沉积等核心设备需求旺盛 → 龙头营收利润高增',
    verification: { strength: 'strong', note: '因果链强 — 订单数据可验证\n信源[5][9]确认两长扩产拉动设备；北方华创收入订单稳步增长' },
    tracking: [
      { name: '北方华创新增订单金额', freq: '季' },
      { name: '中微公司刻蚀市占率', freq: '季' },
    ],
  },
  {
    id: 'H1-3', chainLevel: 1, status: 'confirmed', derivesFrom: ['H0-1', 'H0-2'], timeHorizon: '当前-2027H1',
    title: '模组厂库存红利期，低价库存释放利润',
    statement: '存储芯片涨价周期中，模组厂低价库存释放利润，佰维存储、江波龙等直接受益。',
    reasoning: 'H0-1全品类涨价 + H0-2供给短缺 → 模组厂备有低价库存 → 销售价格随市价提升 → 毛利率大幅扩张',
    verification: { strength: 'strong', note: '因果链强 — 财报已有体现\n信源[1][8]提及佰维存储、江波龙等积极扩产并受益涨价周期' },
    tracking: [
      { name: '模组厂库存周转天数', freq: '季' },
      { name: '模组厂毛利率', freq: '季' },
    ],
  },

  // ── L2 · 二阶矛盾 ──
  {
    id: 'H2-1', chainLevel: 2, status: 'broken', derivesFrom: ['H1-1'], timeHorizon: '2028-2029',
    title: '远期产能过剩隐忧 — 因果链证伪，不参与评分',
    statement: '原厂大幅扩产后新产能导致供给过剩的推论不成立。',
    reasoning: '原厂扩产 → 但HBM芯片面积损耗大、设备交期长 → 实际供给仅增长约13% → 「产能过剩」因果链断裂',
    verification: { strength: 'broken', note: '因果链断裂 — 不参与选股评分\n摩根大通等指出实际供应仅增长约13%，与产能过剩推论直接矛盾' },
    tracking: [
      { name: '原厂资本开支增速', freq: '季' },
      { name: '2028年DRAM供需增速预测', freq: '年' },
    ],
  },
  {
    id: 'H2-2', chainLevel: 2, status: 'unverified', derivesFrom: ['H1-2'], timeHorizon: '2027年后',
    title: '设备订单持续性考验 — 经CounterAgent修正',
    statement: '设备订单增速趋于平稳，但受益于长期国产替代和产能瓶颈，龙头新增订单具备较强持续性。',
    reasoning: 'H1-2受益于两长扩产 → 扩产有周期性 → 但国产替代提供长期增量，龙头在手订单充裕',
    verification: { strength: 'moderate', note: '因果链经修正 — CounterAgent: neutral→negative\n北方华创中长期订单获取能力看好；产业链供需格局严重短缺，扩产需求长期存在' },
    tracking: [
      { name: '设备企业在手订单覆盖年限', freq: '季' },
      { name: '长鑫/长江后续CAPEX', freq: '年' },
    ],
  },
  {
    id: 'H2-3', chainLevel: 2, status: 'unverified', derivesFrom: ['H1-3'], timeHorizon: '2027H2-2028',
    title: '模组厂库存风险积聚，高成本库存或面临减值',
    statement: '模组厂在涨价期大量囤货，若价格涨势趋缓或反转，高成本库存可能导致减值风险。',
    reasoning: 'H1-3模组厂享受低价库存红利的同时加大备货 → 库存余额快速膨胀 → 一旦价格下跌 → 面临跌价准备计提压力',
    verification: { strength: 'moderate', note: '因果链中等 — 周期规律，逻辑合理\n无直接信源支持，但库存风险属半导体周期铁律' },
    tracking: [
      { name: '存储器价格月环比', freq: '月' },
      { name: '模组厂存货跌价准备', freq: '季' },
    ],
  },

  // ── L3 · 投资落点 ──
  {
    id: 'H3-1', chainLevel: 3, status: 'partial', derivesFrom: ['H2-1'], timeHorizon: '2027-2028',
    title: 'HBM绑定标的弹性：太极实业、雅克科技等',
    statement: '直接绑定HBM供应或封装的标的保留高弹性，HBM产业链不受一般存储产能过剩冲击。',
    reasoning: 'H2-1提示远期过剩 → 但HBM需求持续强劲 → HBM封测、材料等绑定标的更安全',
    verification: { strength: 'moderate', note: '因果链中等 — 受上游H2-1证伪影响\nHBM景气延续至2028年，产能持续短缺；受益环节：HBM封装、前驱体、测试设备' },
    tracking: [
      { name: 'HBM渗透率', freq: '季' },
      { name: '绑定标的HBM相关营收占比', freq: '季' },
    ],
  },
  {
    id: 'H3-2', chainLevel: 3, status: 'unverified', derivesFrom: ['H2-2'], timeHorizon: '2027-2028',
    title: '设备龙头寻确定性：北方华创、中微公司',
    statement: '优选已获长期订单且国产替代确定性强的龙头，业绩持续性优于二线厂商。',
    reasoning: '技术领先、与两长深度绑定的龙头 → 在手订单充裕 → 国产替代提供新增量 → 确定性更高',
    verification: { strength: 'strong', note: '因果链强 — 龙头地位+在手订单支撑\n北方华创收入订单稳步增长；受益环节：刻蚀、薄膜沉积设备龙头' },
    tracking: [
      { name: '北方华创刻蚀设备市占率', freq: '季' },
      { name: '中微公司新增订单中两长占比', freq: '季' },
    ],
  },
  {
    id: 'H3-3', chainLevel: 3, status: 'unverified', derivesFrom: ['H2-3'], timeHorizon: '2027-2028',
    title: '优选库存管理模组厂：江波龙等库存审慎者',
    statement: '优选库存管理谨慎、跌价准备计提充分的模组厂，在周期波动中维持业绩稳定性。',
    reasoning: 'H2-3揭示库存减值风险 → 不同模组厂库存管理能力差异 → 优选存货周转快、跌价准备覆盖充分的',
    verification: { strength: 'moderate', note: '因果链中等 — 选股逻辑合理\n属合理选股思路；受益环节：模组厂中库存管控优秀者' },
    tracking: [
      { name: '模组厂存货周转天数', freq: '季' },
      { name: '跌价准备/存货比值', freq: '季' },
    ],
  },
];

// ── 股票数据：上游6 / 中游6 / 下游6 ──
export const STOCKS: Record<'upstream' | 'midstream' | 'downstream', StockItem[]> = {
  upstream: [
    { name: '中微公司', reason: '刻蚀设备龙头，深度受益存储扩产及国产替代', rank: 1, compositeScore: 0.91, adapterScore: 1.63, qualityScore: 0.49, roe: 4.0, grossMargin: 39.9, revenueGrowth: 34.1, deductedProfitGrowth: 197.2, risk: 0.0 },
    { name: '拓荆科技', reason: 'CVD/PVD设备龙头，存储扩产核心受益者', rank: 2, compositeScore: 0.52, adapterScore: 0.79, qualityScore: 0.66, roe: 8.2, grossMargin: 41.7, revenueGrowth: 57.0, deductedProfitGrowth: 488.3, risk: 0.0 },
    { name: '快克智能', reason: '封装设备供应商，受益存储封装产能扩张', rank: 3, compositeScore: 0.44, adapterScore: 0.66, qualityScore: 0.56, roe: 5.3, grossMargin: 49.8, revenueGrowth: 33.1, deductedProfitGrowth: 16.1, risk: 0.0 },
    { name: '长川科技', reason: '半导体测试设备龙头，存储扩产驱动测试需求增长', rank: 4, compositeScore: 0.33, adapterScore: 0.37, qualityScore: 0.73, roe: 7.2, grossMargin: 56.8, revenueGrowth: 69.1, deductedProfitGrowth: 217.6, risk: 0.0 },
    { name: '华海清科', reason: 'CMP设备独供，存储工艺关键设备需求爆发', rank: 5, compositeScore: 0.30, adapterScore: 0.41, qualityScore: 0.48, roe: 3.3, grossMargin: 42.3, revenueGrowth: 31.7, deductedProfitGrowth: 5.9, risk: 0.0 },
    { name: '中科飞测', reason: '量测检测设备领先者，存储制造良率提升必备', rank: 6, compositeScore: 0.28, adapterScore: 0.36, qualityScore: 0.50, roe: -1.3, grossMargin: 47.8, revenueGrowth: 34.6, deductedProfitGrowth: -354.3, risk: 0.0 },
  ],
  midstream: [
    { name: '北京君正', reason: '车载存储芯片龙头，供需缺口下业绩弹性显著', rank: 1, compositeScore: 0.52, adapterScore: 0.80, qualityScore: 0.58, roe: 2.5, grossMargin: 43.5, revenueGrowth: 47.1, deductedProfitGrowth: 331.6, risk: 0.0 },
    { name: '恒烁股份', reason: '高增长NOR Flash设计公司，涨价周期业绩弹性大', rank: 2, compositeScore: 0.29, adapterScore: 0.35, qualityScore: 0.61, roe: 3.7, grossMargin: 41.8, revenueGrowth: 192.1, deductedProfitGrowth: 284.7, risk: 0.0 },
    { name: '兆易创新', reason: 'NOR Flash/DRAM龙头，全品类涨价直接增厚利润', rank: 3, compositeScore: 0.29, adapterScore: 0.29, qualityScore: 0.72, roe: 6.6, grossMargin: 57.1, revenueGrowth: 119.4, deductedProfitGrowth: 522.8, risk: 0.0 },
    { name: '东芯股份', reason: 'NAND/MCP存储设计先锋，涨价周期量价弹性突出', rank: 4, compositeScore: 0.28, adapterScore: 0.28, qualityScore: 0.67, roe: 3.9, grossMargin: 53.2, revenueGrowth: 236.9, deductedProfitGrowth: 333.4, risk: 0.0 },
    { name: '澜起科技', reason: 'DDR5内存接口芯片霸主，AI算力驱动量价齐升', rank: 5, compositeScore: 0.22, adapterScore: 0.24, qualityScore: 0.52, roe: 5.0, grossMargin: 69.8, revenueGrowth: 19.5, deductedProfitGrowth: 61.3, risk: 0.0 },
    { name: '伟测科技', reason: '第三方存储测试龙头，扩产周期测试需求爆发', rank: 6, compositeScore: 0.18, adapterScore: 0.14, qualityScore: 0.55, roe: 2.0, grossMargin: 35.0, revenueGrowth: 71.8, deductedProfitGrowth: 173.4, risk: 0.0 },
  ],
  downstream: [
    { name: '江波龙', reason: '模组龙头库存管理审慎，跌价准备计提充分', rank: 1, compositeScore: 1.19, adapterScore: 2.07, qualityScore: 0.97, roe: 38.5, grossMargin: 55.5, revenueGrowth: 132.8, deductedProfitGrowth: 2644.0, risk: 0.15 },
    { name: '香农芯创', reason: '电子元器件分销规模领先，存储涨价带动分销弹性', rank: 2, compositeScore: 0.50, adapterScore: 0.71, qualityScore: 0.72, roe: 31.5, grossMargin: 9.1, revenueGrowth: 200.6, deductedProfitGrowth: 7835.1, risk: 0.0 },
    { name: '大普微', reason: '企业级SSD模组稀缺标的，AI算力与存储涨价双击', rank: 3, compositeScore: 0.41, adapterScore: 0.49, qualityScore: 0.88, roe: 60.7, grossMargin: 37.6, revenueGrowth: 341.0, deductedProfitGrowth: 398.9, risk: 0.04 },
    { name: '德明利', reason: '移动/嵌入式/SSD模组全覆盖，低价库存释放高利润弹性', rank: 4, compositeScore: 0.31, adapterScore: 0.24, qualityScore: 0.99, roe: 67.6, grossMargin: 57.4, revenueGrowth: 502.1, deductedProfitGrowth: 4943.4, risk: 0.02 },
    { name: '中电港', reason: '存储器分销收入占比极高，直接映射行业景气度', rank: 5, compositeScore: 0.20, adapterScore: 0.25, qualityScore: 0.38, roe: 2.9, grossMargin: 2.8, revenueGrowth: 144.4, deductedProfitGrowth: 87.4, risk: 0.0 },
    { name: '佰维存储', reason: '嵌入式及PC存储模组主力，直接受益消费级存储涨价', rank: 6, compositeScore: 0.20, adapterScore: 0.01, qualityScore: 0.96, roe: 41.6, grossMargin: 53.3, revenueGrowth: 341.5, deductedProfitGrowth: 1567.9, risk: 0.0 },
  ],
};
