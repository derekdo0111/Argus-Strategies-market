import {
  createContext,
  useContext,
  useRef,
  useEffect,
  useState,
  useMemo,
  useCallback,
  type ReactNode,
} from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import ResizablePanel from '../ResizablePanel';
import ScoreCard from './ScoreCard';
import type { GateResult, AnalysisReport } from '../../types';
import styles from './ReportViewer.module.css';

// ── Types ──────────────────────────────────────────────

interface ReportSection {
  id: string;
  title: string;
  content: string;
}

interface TocItem {
  id: string;
  title: string;
  children: TocItem[];
}

// ── Minimum stage display gate (v0.6.22) ──────────────
// 防止快状态（computing<0.5s / websearch缓存<0.1s）在2秒轮询间隔中被跳过
// 当后端状态跨越2+级时，前端注入中间阶段，每阶段至少显示 MIN_STAGE_MS

const STAGE_ORDER = ['fetching', 'computing', 'websearch', 'analyzing'] as const;

const STAGE_DEFAULTS: Record<string, { progress: number; message: string }> = {
  fetching:  { progress: 10, message: '正在拉取财务数据...' },
  computing: { progress: 30, message: '正在计算 CQ+PR...' },
  websearch: { progress: 60, message: '正在搜索外部信息...' },
  analyzing: { progress: 80, message: '正在调用 LLM 分析...' },
};

const MIN_STAGE_MS = 1500;

// ── Helpers ────────────────────────────────────────────

function slugify(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^\w\u4e00-\u9fff]+/g, '-')
    .replace(/(^-|-$)/g, '')
    || 'section';
}

/** 结构性切除：找到第一个 ## 标题，之前的内容全部丢弃。
 *  不再用正则猜 LLM 会说什么废话（regex 打地鼠），
 *  只要 prompt 要求 LLM 用 ## 开始正文，preamble 天然被隔离。 */
function stripPreamble(md: string): string {
  const firstH2 = md.search(/^## /m);
  if (firstH2 > 0) return md.slice(firstH2);
  return md;
}

/** 预处理 markdown：
 *  1. [REF001] → <cite data-ref="REF001" id="cite-REF001">[REF001]</cite>
 *  2. [任意文字](#锚点) → [任意文字](#user-content-锚点) — 同步 rehype-sanitize 的 id 前缀，
 *     匹配所有 markdown 内部链接（不仅引用格式），保证 href 与 <a id="user-content-xxx"> 锚点匹配。
 *     rehype-sanitize 会自动给所有 id 加 "user-content-" 前缀（安全机制），无法关闭。 */
function preprocessCitations(md: string): string {
  // Step 1: [REF001] standalone → <cite>（不含括号后缀说明不是 markdown 链接）
  md = md.replace(
    /\[([A-Z][-\w]*\d+)\](?!\()/g,
    '<cite data-ref="$1" id="cite-$1">[$1]</cite>'
  );
  // Step 2: 任意 markdown 内部链接 [text](#anchor) → href 加 user-content- 前缀匹配 sanitize 输出
  md = md.replace(
    /\[([^\]]+)\]\(#(?!user-content-)([^)]+)\)/g,
    '[$1](#user-content-$2)'
  );
  return md;
}

/** v0.7.9: rehype-sanitize schema — 允许未加前缀的 a[id/name] 锚点 + cite 标签 + cite[data-ref/id]
 *  v0.7.6 的 bug：直接把 'id' 加到 attributes.a 中，rehype-sanitize 会自动加 "user-content-" 前缀
 *  导致 <a href="#a1"> 和 <a id="user-content-a1"> 不匹配，跳转失效。
 *  正确做法：用正则数组形式 ['id', RegExp('.*')] → 允许任意 id 值且不加前缀。
 *  cite 默认不在 tagNames 中，需显式加入。 */
const sanitizeSchema = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames || []), 'cite'],
  attributes: {
    ...defaultSchema.attributes,
    a: [...((defaultSchema.attributes?.a || ['href']) as Array<string | [string, RegExp]>), ['id', /.*/], ['name', /.*/]],
    cite: ['dataRef', 'id', 'className'],
  },
};

function parseMarkdown(md: string): { header: string; sections: ReportSection[] } {
  const processed = preprocessCitations(md);
  const lines = processed.split('\n');
  const headerLines: string[] = [];
  const sections: ReportSection[] = [];

  let inSection = false;
  let sectionTitle = '';
  let sectionLines: string[] = [];

  for (const line of lines) {
    const h2Match = line.match(/^## (.+)/);
    if (h2Match) {
      if (inSection) {
        sections.push({
          id: slugify(sectionTitle),
          title: sectionTitle,
          content: sectionLines.join('\n'),
        });
      }
      sectionTitle = h2Match[1];
      sectionLines = [];
      inSection = true;
    } else if (inSection) {
      sectionLines.push(line);
    } else {
      headerLines.push(line);
    }
  }

  if (inSection) {
    sections.push({
      id: slugify(sectionTitle),
      title: sectionTitle,
      content: sectionLines.join('\n'),
    });
  }

  return { header: headerLines.join('\n'), sections };
}

function extractToc(sections: ReportSection[]): TocItem[] {
  return sections.map((s) => {
    const children: TocItem[] = [];
    const lines = s.content.split('\n');
    for (const line of lines) {
      const m = line.match(/^### (.+)/);
      if (m) {
        children.push({ id: slugify(m[1]), title: m[1], children: [] });
      }
    }
    return { id: s.id, title: s.title, children };
  });
}

function isDefaultExpanded(title: string): boolean {
  if (/摘要|打分|研判|建议|参考来源|资料来源|引用/.test(title)) return true;
  return false;
}

// ── ScoreBar ───────────────────────────────────────────

function ScoreBar({ value }: { value: number }) {
  return (
    <span className={styles.scoreBar} aria-hidden>
      <span
        className={styles.scoreFill}
        style={{ width: `${Math.min(value * 10, 100)}%` }}
      />
    </span>
  );
}

// ── Table context：区分评分表 vs 数据表 ─────────────────

const TableContext = createContext({ isScoreTable: false });

/** 评分表表头关键词 — 命中任一个即判定为评分表 */
const SCORE_HEADER_KEYWORDS = ['得分', '评分', '分数', '权重', '维度', '打分'];

/** 递归遍历 React children，检查 th 元素内容是否命中评分关键词 */
function detectScoreTable(children: ReactNode): boolean {
  const stack: ReactNode[] = [children];
  while (stack.length > 0) {
    const node = stack.pop();
    if (node == null) continue;
    if (Array.isArray(node)) {
      stack.push(...node);
      continue;
    }
    // React element
    if (typeof node === 'object' && 'type' in node && 'props' in node) {
      const el = node as { type: unknown; props: { children?: ReactNode } };
      if (el.type === 'th') {
        const text = typeof el.props.children === 'string'
          ? el.props.children
          : '';
        if (SCORE_HEADER_KEYWORDS.some((kw) => text.includes(kw))) {
          return true;
        }
      }
      if (el.props.children != null) {
        stack.push(el.props.children);
      }
    }
  }
  return false;
}

// ── Table custom renderers ─────────────────────────────

function TableRenderer({ children }: { children?: ReactNode }) {
  const isScoreTable = useMemo(() => detectScoreTable(children), [children]);

  return (
    <TableContext.Provider value={{ isScoreTable }}>
      <div className={styles.tableWrap}>
        <table className={styles.table}>{children}</table>
      </div>
    </TableContext.Provider>
  );
}

/** 趋势判断关键词 → CSS class 映射 */
const TREND_MAP: Record<string, string> = {
  up: 'trendUp',
  down: 'trendDown',
  stable: 'trendStable',
  '吃老本': 'trendDown',
  '收缩': 'trendDown',
  '快速增长': 'trendUp',
  '中速增长': 'trendUp',
  '缓慢增长': 'trendUp',
};

function TdRenderer({ children }: { children?: ReactNode }) {
  const { isScoreTable } = useContext(TableContext);
  const text = typeof children === 'string' ? children : '';

  if (text === 'PASS' || text === '[PASS]') {
    return (
      <td className={styles.tdPass}>
        <span className={styles.badge}>PASS</span>
      </td>
    );
  }
  if (text === 'FAIL' || text === '[FAIL]') {
    return (
      <td className={styles.tdFail}>
        <span className={styles.badge}>FAIL</span>
      </td>
    );
  }

  // 趋势判断列着色 (v0.7.14: pill badges)
  const trendClass = TREND_MAP[text];
  if (trendClass) {
    const label =
      text === 'up' ? '▲ 上升'
      : text === 'down' ? '▼ 下降'
      : text === 'stable' ? '─ 持平'
      : text === '快速增长' ? '▲ 快速增长'
      : text === '中速增长' ? '▲ 中速增长'
      : text === '缓慢增长' ? '▲ 缓慢增长'
      : text === '吃老本' ? '▼ 吃老本'
      : text === '收缩' ? '▼ 收缩'
      : text;
    return (
      <td>
        <span className={`${styles.trendBadge} ${styles[trendClass] || styles.trendStable}`}>
          {label}
        </span>
      </td>
    );
  }

  // 数字列右对齐检测：纯数字 / 带% / 带亿/万单位
  const isNumeric = /^-?[\d,]+(\.\d+)?[%亿万千百]?$/.test(text.trim()) && text.trim().length > 0;
  if (isNumeric) {
    return <td className={styles.tdNumeric}>{children}</td>;
  }

  // 仅在评分表中才渲染 ScoreBar，避免把 YoY、固定资产占比等数据误判为评分
  if (isScoreTable) {
    const num = parseFloat(text);
    if (!isNaN(num) && num >= 0 && num <= 10 && /^\d+(\.\d)?$/.test(text)) {
      return (
        <td className={styles.tdScore}>
          <ScoreBar value={num} />
          <span className={styles.scoreNum}>{text}</span>
        </td>
      );
    }
  }

  return <td>{children}</td>;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function TrRenderer({ children }: any) {
  let hasFail = false;
  let rowId: string | undefined;

  if (Array.isArray(children)) {
    hasFail = children.some(
      (c: any) =>
        typeof c?.props?.children === 'string' &&
        (c.props.children === 'FAIL' || c.props.children === '[FAIL]')
    );
    // 检测参考来源行：首列包含 <cite data-ref="REF001"> 时添加 row id
    const firstTd = children[0];
    const tdChildren = firstTd?.props?.children;
    const citeChild = Array.isArray(tdChildren)
      ? tdChildren.find((c: any) => c?.type === 'cite' && c?.props?.['data-ref'])
      : tdChildren?.type === 'cite' && tdChildren?.props?.['data-ref'] ? tdChildren : null;
    if (citeChild?.props?.['data-ref']) {
      rowId = `ref-row-${citeChild.props['data-ref']}`;
    }
  }

  const cls = [hasFail ? styles.trFail : '', rowId ? styles.refRow : ''].filter(Boolean).join(' ');
  return <tr id={rowId} className={cls || undefined}>{children}</tr>;
}

// ── TOC Panel (v0.7.13 redesign) ───────────────────────

function TocPanel({
  toc,
  expandedSet,
  activeId,
  onScrollTo,
  onToggle,
  onExpandAll,
  onCollapseAll,
}: {
  toc: TocItem[];
  expandedSet: Set<string>;
  activeId: string;
  onScrollTo: (id: string) => void;
  onToggle: (id: string) => void;
  onExpandAll: () => void;
  onCollapseAll: () => void;
}) {
  return (
    <div className={styles.toc}>
      {/* ── Header ── */}
      <div className={styles.tocHeader}>
        <h3 className={styles.tocTitle}>报告目录</h3>
        <div className={styles.tocActions}>
          <button
            className={styles.tocActionBtn}
            onClick={onExpandAll}
            title="展开全部章节"
            aria-label="展开全部章节"
          >
            <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
              <path d="M4.5 6.5l3 3 3-3" stroke="currentColor" strokeWidth="1.6"
                strokeLinecap="round" strokeLinejoin="round" />
              <path d="M4.5 10.5l3 3 3-3" stroke="currentColor" strokeWidth="1.6"
                strokeLinecap="round" strokeLinejoin="round" opacity="0.35" />
            </svg>
          </button>
          <button
            className={styles.tocActionBtn}
            onClick={onCollapseAll}
            title="折叠全部章节"
            aria-label="折叠全部章节"
          >
            <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
              <path d="M4.5 6.5l3-3 3 3" stroke="currentColor" strokeWidth="1.6"
                strokeLinecap="round" strokeLinejoin="round" />
              <path d="M4.5 10.5l3-3 3 3" stroke="currentColor" strokeWidth="1.6"
                strokeLinecap="round" strokeLinejoin="round" opacity="0.35" />
            </svg>
          </button>
        </div>
      </div>

      {/* ── Nav ── */}
      <nav className={styles.tocNav}>
        {toc.map((item) => {
          const isExpanded = expandedSet.has(item.id);
          const hasChildren = item.children.length > 0;
          const isActive = activeId === item.id
            || item.children.some((c) => c.id === activeId);

          return (
            <div key={item.id} className={styles.tocGroup}>
              {/* Parent row: chevron + title + badge */}
              <div
                className={`${styles.tocRow} ${isActive ? styles.tocRowActive : ''}`}
              >
                <button
                  className={`${styles.tocChevron} ${isExpanded ? styles.tocChevronOpen : ''} ${!hasChildren ? styles.tocChevronHidden : ''}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (hasChildren) onToggle(item.id);
                  }}
                  aria-label={isExpanded ? '折叠子章节' : '展开子章节'}
                  tabIndex={hasChildren ? 0 : -1}
                >
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                    <path
                      d="M4.5 2.5L8 6l-3.5 3.5"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>

                <button
                  className={styles.tocLabel}
                  onClick={() => onScrollTo(item.id)}
                  title={item.title}
                >
                  {item.title}
                </button>

                {hasChildren && (
                  <span className={styles.tocBadge}>{item.children.length}</span>
                )}
              </div>

              {/* Children — always rendered for CSS transition */}
              {hasChildren && (
                <div className={`${styles.tocChildren} ${isExpanded ? styles.tocChildrenOpen : ''}`}>
                  {item.children.map((sub) => (
                    <button
                      key={sub.id}
                      className={`${styles.tocChildItem} ${activeId === sub.id ? styles.tocChildActive : ''}`}
                      onClick={() => onScrollTo(sub.id)}
                      title={sub.title}
                    >
                      {sub.title}
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </nav>
    </div>
  );
}

// ── Gate Badges ────────────────────────────────────────

function GateSummary({ data }: { data?: GateResult }) {
  if (!data) {
    return <div className={styles.gateSection}><span className={styles.noData}>门控数据加载中...</span></div>;
  }
  const cqPassed = data.cash_quality?.overall_passed ?? false;
  const prPassed = data.penetration_return?.pr_result?.passed ?? false;
  const pr = data.penetration_return?.pr_result?.pr;

  return (
    <div className={styles.gateSection}>
      <span className={`${styles.gateBadge} ${cqPassed ? styles.gatePass : styles.gateFail}`}>
        CQ {cqPassed ? 'PASS' : 'FAIL'}
      </span>
      <span className={`${styles.gateBadge} ${prPassed ? styles.gatePass : styles.gateFail}`}>
        PR {pr != null ? `${pr.toFixed(2)}% ` : ''}{prPassed ? 'PASS' : 'FAIL'}
      </span>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────

interface ReportViewerProps {
  selectedStock: { ts_code: string; name: string } | null;
}

export default function ReportViewer({ selectedStock }: ReportViewerProps) {
  // Fetch gate results
  const { data: gateData } = useQuery<GateResult>({
    queryKey: ['gates', selectedStock?.ts_code],
    queryFn: async () => {
      const { data } = await axios.get(`/api/turtle/${selectedStock!.ts_code}/gates`);
      return data;
    },
    enabled: !!selectedStock,
    retry: 1,
  });

  // Fetch analysis report
  const {
    data: reportData,
    isLoading: reportLoading,
    isError: reportError,
    refetch: refetchReport,
  } = useQuery<AnalysisReport>({
    queryKey: ['analysis', selectedStock?.ts_code],
    queryFn: async () => {
      const { data } = await axios.get(`/api/turtle/${selectedStock!.ts_code}/analysis`);
      return data;
    },
    enabled: !!selectedStock,
    placeholderData: (prev, prevQuery) => {
      // 仅同股票 refetch 时保留旧数据，切换股票时清空避免闪烁旧报告
      if (prevQuery?.queryKey?.[1] === selectedStock?.ts_code) return prev;
      return undefined;
    },
    retry: 1,
  });

  // ── Analysis progress tracking (multi-stock parallel) ──

  type AnalysisEntry = { status: string; progress: number; message: string; _errType?: string };

  const [analysisMap, setAnalysisMap] = useState<Record<string, AnalysisEntry>>({});
  const analysisMapRef = useRef(analysisMap);
  analysisMapRef.current = analysisMap;



  // ── Guard ④: startedAt tracking for 10-min timeout detection ──
  const [startedAtMap, setStartedAtMap] = useState<Record<string, number>>({});
  const startedAtMapRef = useRef(startedAtMap);
  startedAtMapRef.current = startedAtMap;

  // ── v0.6.22: Minimum stage display gate refs ──
  // displayedStageRef: 当前 UI 显示的是哪个阶段（用于检测跨越）
  const displayedStageRef = useRef<Record<string, string>>({});
  // stageTimerRef: 注入中间阶段的定时器（切换代码时需清理）
  const stageTimerRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  // backendTargetRef: 后端最终目标阶段（注入完成后显示的真实消息）
  const backendTargetRef = useRef<Record<string, { progress: number; message: string }>>({});

  // 组件卸载时清理所有定时器
  useEffect(() => {
    return () => {
      Object.values(stageTimerRef.current).forEach((t) => clearTimeout(t));
    };
  }, []);

  // ── Guard ③: consecutive poll failure counter ──
  const [consecutiveFailures, setConsecutiveFailures] = useState(0);

  // Keep refetchReport stable across polls
  const refetchReportRef = useRef(refetchReport);
  refetchReportRef.current = refetchReport;

  // Persistent poller: runs for component lifetime, uses refs to avoid dep churn
  useEffect(() => {
    // v0.6.22: 阶段链注入工具 — 当后端跳过多阶段时，按 MIN_STAGE_MS 间隔逐个显示
    const scheduleStageChain = (code: string, fromIdx: number, toIdx: number) => {
      // 清除旧定时器（后端状态又推进了）
      if (stageTimerRef.current[code]) {
        clearTimeout(stageTimerRef.current[code]);
      }
      let delay = 0;
      for (let i = fromIdx; i <= toIdx; i++) {
        const stageName = STAGE_ORDER[i];
        const isLast = i === toIdx;
        const defaults = STAGE_DEFAULTS[stageName];
        if (!defaults) continue;

        stageTimerRef.current[code] = setTimeout(() => {
          // 最后阶段用后端真实消息，中间阶段用默认消息
          const target = isLast ? backendTargetRef.current[code] : null;
          const entry: AnalysisEntry = isLast && target
            ? { status: stageName, progress: target.progress, message: target.message }
            : { status: stageName, progress: defaults.progress, message: defaults.message };

          setAnalysisMap(prev => {
            // 避免重复设置：如果已经是同一状态且同一进度就跳过
            const cur = prev[code];
            if (cur?.status === entry.status && cur?.progress === entry.progress) return prev;
            return { ...prev, [code]: entry };
          });
          displayedStageRef.current[code] = stageName;
          if (isLast) {
            delete stageTimerRef.current[code];
            delete backendTargetRef.current[code];
          }
        }, delay);
        delay += MIN_STAGE_MS;
      }
    };

    const interval = setInterval(async () => {
      const map = analysisMapRef.current;
      const activeCodes = Object.entries(map)
        .filter(([, v]) => v.status !== 'done' && v.status !== 'error')
        .map(([code]) => code);

      if (activeCodes.length === 0) return;

      const results = await Promise.allSettled(
        activeCodes.map(async (code) => {
          const { data } = await axios.get(`/api/turtle/${code}/analyze/status`);
          return [code, data] as const;
        }),
      );

      // Guard ③: track consecutive poll failures
      const allFailed = results.every(r => r.status === 'rejected');
      if (allFailed && results.length > 0) {
        setConsecutiveFailures(prev => prev + 1);
      } else {
        setConsecutiveFailures(0);
      }

      setAnalysisMap(prev => {
        const next = { ...prev };
        let changed = false;
        for (const r of results) {
          if (r.status === 'fulfilled') {
            const [code, data] = r.value;
            const entry: AnalysisEntry = {
              status: data.status as string,
              progress: (data.progress ?? 0) as number,
              message: (data.message ?? '') as string,
            };
            const old = prev[code];

            // v0.6.21: guard — 轮询返回 not_started 时不覆盖 onMutate 乐观状态
            if (entry.status === 'not_started' && old?.status === 'fetching') continue;

            // v0.6.22: 终态 → 立即显示，清除所有注入定时器
            if (['done', 'error', 'timeout'].includes(entry.status)) {
              if (stageTimerRef.current[code]) {
                clearTimeout(stageTimerRef.current[code]);
                delete stageTimerRef.current[code];
              }
              delete displayedStageRef.current[code];
              delete backendTargetRef.current[code];
              if (!old || old.status !== entry.status || old.progress !== entry.progress) {
                next[code] = entry;
                changed = true;
              }
              continue;
            }

            // v0.6.22: 非终态 — 阶段跳过检测 + 注入
            const oldIdx = old ? (STAGE_ORDER as readonly string[]).indexOf(old.status) : -1;
            const newIdx = (STAGE_ORDER as readonly string[]).indexOf(entry.status);
            if (newIdx < 0) {
              // 未知状态：直接应用
              if (!old || old.status !== entry.status || old.progress !== entry.progress || old.message !== entry.message) {
                next[code] = entry;
                changed = true;
              }
              continue;
            }

            if (oldIdx < 0) {
              // 后端首次返回状态
              if (newIdx === 0) {
                // 正常从 fetching 开始
                next[code] = entry;
                changed = true;
                displayedStageRef.current[code] = entry.status;
              } else {
                // 后端已跳过 ≥1 阶段 — 从 fetching 开始注入
                backendTargetRef.current[code] = { progress: entry.progress, message: entry.message };
                scheduleStageChain(code, 0, newIdx);
              }
              continue;
            }

            // 已有旧状态
            if (newIdx <= oldIdx) {
              // 同级或回退：仅刷新进度/消息
              if (old.progress !== entry.progress || old.message !== entry.message) {
                next[code] = entry;
                changed = true;
              }
            } else if (newIdx === oldIdx + 1) {
              // 相邻推进 — 已至少有 2s 轮询间隔 ≥ MIN_STAGE_MS，直接显示
              if (stageTimerRef.current[code]) {
                clearTimeout(stageTimerRef.current[code]);
                delete stageTimerRef.current[code];
              }
              next[code] = entry;
              changed = true;
              displayedStageRef.current[code] = entry.status;
            } else {
              // 跨越 ≥2 阶段 — 注入中间阶段
              backendTargetRef.current[code] = { progress: entry.progress, message: entry.message };
              scheduleStageChain(code, oldIdx + 1, newIdx);
            }
          }
        }
        return changed ? next : prev;
      });
    }, 2000);

    return () => clearInterval(interval);
  }, []); // Empty deps — uses refs, negligible idle overhead

  // Auto-refetch report when current stock's analysis completes
  useEffect(() => {
    if (!selectedStock) return;
    const entry = analysisMap[selectedStock.ts_code];
    if (entry?.status === 'done') {
      refetchReportRef.current();
    }
  }, [analysisMap, selectedStock]);

  // Guard ⑥: clean up done entry only when reportData actually arrives
  useEffect(() => {
    if (!selectedStock || !reportData?.report_markdown) return;
    setAnalysisMap(prev => {
      if (prev[selectedStock.ts_code]?.status !== 'done') return prev;
      const next = { ...prev };
      delete next[selectedStock.ts_code];
      return next;
    });
    setStartedAtMap(prev => {
      if (!(selectedStock.ts_code in prev)) return prev;
      const next = { ...prev };
      delete next[selectedStock.ts_code];
      return next;
    });
  }, [reportData, selectedStock]);

  // ── Guard ②: mount-time status probe (F5 refresh recovery) ──
  useEffect(() => {
    if (!selectedStock) return;
    const code = selectedStock.ts_code;
    axios.get(`/api/turtle/${code}/analyze/status`)
      .then(({ data }) => {
        if (data.status && !['done', 'error', 'not_started'].includes(data.status)) {
          setAnalysisMap(prev => ({
            ...prev,
            [code]: {
              status: data.status,
              progress: data.progress ?? 0,
              message: data.message ?? '',
            },
          }));
        }
      })
      .catch(() => {}); // silent fail, polling will retry
  }, [selectedStock]);

  // ── Guard ⑧: visibilitychange refresh ──
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return;
      const map = analysisMapRef.current;
      const activeCodes = Object.keys(map).filter(k => !['done', 'error'].includes(map[k].status));
      if (activeCodes.length === 0) return;
      activeCodes.forEach(code => {
        axios.get(`/api/turtle/${code}/analyze/status`).then(({ data }) => {
          if (!data.status || ['done', 'error', 'not_started'].includes(data.status)) return;
          setAnalysisMap(prev => {
            const old = prev[code];
            const newProgress = data.progress ?? 0;
            if (old?.status === data.status && old?.progress === newProgress) return prev;
            return { ...prev, [code]: { status: data.status, progress: newProgress, message: data.message ?? '' } };
          });
        }).catch(() => {});
      });
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, []);

  // ── Guard ④: timeout detection (every 15s) ──
  useEffect(() => {
    const timer = setInterval(() => {
      const now = Date.now();
      const map = analysisMapRef.current;
      const startedAt = startedAtMapRef.current;
      let changed = false;
      const next = { ...map };
      for (const [code, entry] of Object.entries(map)) {
        if (['done', 'error', 'timeout'].includes(entry.status)) continue;
        if (startedAt[code] && now - startedAt[code] > 10 * 60 * 1000) {
          next[code] = { status: 'timeout', progress: 0, message: '分析超时（超过10分钟），请重试' };
          changed = true;
        }
      }
      if (changed) setAnalysisMap(next);
    }, 15000);
    return () => clearInterval(timer);
  }, []); // uses refs

  // Analyze mutation — per-stock tracking via analysisMap
  const analyzeMutation = useMutation({
    mutationFn: async (tsCode: string) => {
      await axios.post(`/api/turtle/${tsCode}/analyze`);
    },
    onMutate: (tsCode) => {
      // v0.6.21: 用 onMutate 提前设初始状态（mutationFn 执行前即触发），
      // 确保点击瞬间就看到进度提示，不等 POST 返回。
      setStartedAtMap(prev => ({ ...prev, [tsCode]: Date.now() }));
      setConsecutiveFailures(0);
      setAnalysisMap(prev => ({
        ...prev,
        [tsCode]: { status: 'fetching', progress: 0, message: '正在拉取财务数据...' },
      }));
    },
    onError: (error: unknown, tsCode) => {
      // Guard ⑦: distinguish POST failure vs Task failure
      let errMsg = '请求失败，请确认后端服务已启动';
      let errType = 'mutation';
      if (error && typeof error === 'object') {
        const axiosErr = error as { response?: { data?: { detail?: string }; status?: number }; message?: string };
        if (axiosErr.response?.status === 409 || axiosErr.response?.data?.detail?.includes('已在运行中')) {
          errMsg = axiosErr.response?.data?.detail || '分析任务已在运行中';
          errType = 'task';
        } else {
          errMsg = axiosErr.response?.data?.detail || axiosErr.message || errMsg;
        }
      }
      setAnalysisMap(prev => ({
        ...prev,
        [tsCode]: { status: 'error', progress: 0, message: errMsg, _errType: errType },
      }));
    },
  });

  // Derived: current selected stock's analysis status
  const currentStatus = selectedStock ? analysisMap[selectedStock.ts_code] : undefined;

  // ── Button state derivation ──
  const isAnalyzing = currentStatus &&
    !['done', 'error', 'timeout'].includes(currentStatus.status);
  const isError = currentStatus?.status === 'error';
  const isTimeout = currentStatus?.status === 'timeout';
  const isSuccess = currentStatus?.status === 'done';
  const showNetworkWarning = consecutiveFailures >= 5 && isAnalyzing;

  // ── Empty State ────────────────────────
  if (!selectedStock) {
    return (
      <div className={styles.emptyState}>
        <svg className={styles.emptyIllustration} width="72" height="72" viewBox="0 0 72 72" fill="none">
          <rect x="10" y="14" width="52" height="44" rx="6" fill="var(--accent-light)" />
          <rect x="18" y="22" width="36" height="5" rx="2.5" fill="var(--accent-primary)" opacity="0.25" />
          <rect x="18" y="32" width="28" height="4" rx="2" fill="var(--text-tertiary)" opacity="0.15" />
          <rect x="18" y="40" width="32" height="4" rx="2" fill="var(--text-tertiary)" opacity="0.15" />
          <rect x="18" y="48" width="22" height="4" rx="2" fill="var(--text-tertiary)" opacity="0.15" />
          <circle cx="52" cy="20" r="10" fill="var(--bg-surface)" />
          <path d="M48 20l3 3 6-6" stroke="var(--accent-primary)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <div className={styles.emptyText}>从左侧股池选一只股票，查看深度分析报告</div>
        <div className={styles.emptyHint}>我们会帮你分析生意本质、护城河、增长引擎等 10 个维度</div>
      </div>
    );
  }

  if (reportLoading && !reportData) {
    return (
      <div className={styles.emptyState}>
        <GateSummary data={gateData} />
        <div className={styles.emptyText}>正在为你准备分析报告...</div>
        <div className={styles.emptyHint}>{selectedStock.name}（{selectedStock.ts_code}）正在获取数据</div>
      </div>
    );
  }

  if (!reportData?.report_markdown || reportError) {
    return (
      <div className={styles.emptyState}>
        <GateSummary data={gateData} />
        <div className={styles.emptyText}>
          {isAnalyzing ? '正在分析中...' : isTimeout ? '分析超时' : isError ? '分析失败' : isSuccess ? '分析完成' : '尚未生成分析报告'}
        </div>
        <div className={styles.emptyHint}>
          {isSuccess
            ? `${selectedStock.name}（${selectedStock.ts_code}）分析完成，正在加载报告...`
            : isAnalyzing
              ? `${selectedStock.name}（${selectedStock.ts_code}）${currentStatus?.message || ''}`
              : isTimeout
                ? `${selectedStock.name}（${selectedStock.ts_code}）后台任务超过10分钟未响应，可重新触发`
                : isError
                  ? currentStatus?.message || '未知错误'
                  : `${selectedStock.name}（${selectedStock.ts_code}）尚未生成分析报告`
          }
        </div>

        {(isAnalyzing || isTimeout) && (
          <div className={styles.progressBarWrap}>
            <div className={styles.progressBar} style={{ width: `${isTimeout ? 100 : currentStatus?.progress || 0}%` }} />
          </div>
        )}
        {isAnalyzing && (
          <div className={styles.progressLabel}>
            {currentStatus?.progress || 0}%
          </div>
        )}
        {isAnalyzing && (
          <div className={styles.phaseLabel}>
            {currentStatus?.message || '处理中...'}
          </div>
        )}

        <button
          className={
            isSuccess ? `${styles.analyzeBtn} ${styles.analyzeBtnSuccess}`
            : isError ? `${styles.analyzeBtn} ${styles.analyzeBtnError}`
            : isTimeout ? `${styles.analyzeBtn} ${styles.analyzeBtnError}`
            : isAnalyzing ? `${styles.analyzeBtn} ${styles.analyzeBtnProcessing}`
            : styles.analyzeBtn
          }
          disabled={isAnalyzing || isSuccess || analyzeMutation.isPending}
          onClick={() => {
            // Guard ⑤: clear error before retry
            if (isError || isTimeout) {
              setAnalysisMap(prev => {
                const next = { ...prev };
                delete next[selectedStock.ts_code];
                return next;
              });
            }
            analyzeMutation.mutate(selectedStock.ts_code);
          }}
        >
          {isAnalyzing ? (
            <><span className={styles.buttonSpinner} />{currentStatus?.message || '分析中...'}</>
          ) : analyzeMutation.isPending ? (
            <><span className={styles.buttonSpinner} />提交中...</>
          ) : isSuccess ? (
            '✅ 分析完成，加载报告中...'
          ) : isTimeout ? (
            '⚠️ 分析超时，点击重试'
          ) : isError ? (
            '⚠️ 分析失败，点击重试'
          ) : (
            '🔍 开始分析'
          )}
        </button>

        {/* Guard ③: network warning */}
        {showNetworkWarning && (
          <div className={styles.warningBox}>
            ⚠️ 无法获取分析进度，请检查网络连接（连续 {consecutiveFailures} 次失败）
          </div>
        )}

        {/* Guard ⑦: error detail for task failures */}
        {isError && (
          <div className={styles.errorBox}>
            <strong>{currentStatus?._errType === 'task'
              ? '⚠️ 任务错误'
              : '⚠️ 请求错误'
            }</strong>
            {currentStatus?.message || '请稍后重试'}
          </div>
        )}
      </div>
    );
  }

  return (
    <ReportContent
      key={selectedStock.ts_code}
      reportMarkdown={reportData.report_markdown}
      stockName={selectedStock.name}
      tsCode={selectedStock.ts_code}
      gateData={gateData}
      analysisStatus={currentStatus}
      isMutating={analyzeMutation.isPending}
      isError={isError}
      isTimeout={isTimeout || false}
      onReanalyze={() => {
        // Guard ⑤: clear error before retry
        if (isError || isTimeout) {
          setAnalysisMap(prev => {
            const next = { ...prev };
            delete next[selectedStock.ts_code];
            return next;
          });
        }
        analyzeMutation.mutate(selectedStock.ts_code);
      }}
    />
  );
}

// ── Internal Report Content ────────────────────────────

function ReportContent({
  reportMarkdown,
  stockName,
  tsCode,
  gateData,
  analysisStatus,
  isMutating,
  isError,
  isTimeout,
  onReanalyze,
}: {
  reportMarkdown: string;
  stockName: string;
  tsCode: string;
  gateData?: GateResult;
  analysisStatus?: {
    status: string;
    progress: number;
    message: string;
    _errType?: string;
  } | null;
  isMutating?: boolean;
  isError?: boolean;
  isTimeout?: boolean;
  onReanalyze?: () => void;
}) {
  const { header, sections } = useMemo(() => parseMarkdown(stripPreamble(reportMarkdown)), [reportMarkdown]);
  const toc = useMemo(() => extractToc(sections), [sections]);

  const [expandedSet, setExpandedSet] = useState<Set<string>>(() => {
    const init = new Set<string>();
    sections.forEach((s) => {
      if (isDefaultExpanded(s.title)) init.add(s.id);
    });
    return init;
  });
  const [activeId, setActiveId] = useState('');
  const [showBackTop, setShowBackTop] = useState(false);

  const sectionEls = useRef<Map<string, HTMLElement>>(new Map());
  const mountedRef = useRef(true);
  const mainRef = useRef<HTMLElement>(null);

  // 卸载守卫
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // IntersectionObserver
  useEffect(() => {
    const obs = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) setActiveId(e.target.id);
        }
      },
      { rootMargin: '-60px 0px -55% 0px' }
    );

    sectionEls.current.forEach((el) => obs.observe(el));
    return () => obs.disconnect();
  }, [sections]);

  // Scroll listener for floating back-to-top button
  useEffect(() => {
    const el = mainRef.current;
    if (!el) return;
    const onScroll = () => setShowBackTop(el.scrollTop > 400);
    el.addEventListener('scroll', onScroll);
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  const registerSection = useCallback(
    (id: string) => (el: HTMLHeadingElement | null) => {
      if (el) sectionEls.current.set(id, el);
    },
    []
  );

  /** v0.7.10: 统一点击处理器 — Path A (cite 引用) + Path B (内部链接 [A1](#a1))
   *  两路径共用金色闪烁动画 jumpFlash，高亮目标行 1.5s */
  const handleContentClick = useCallback(
    (e: React.MouseEvent) => {
      const target = e.target as HTMLElement;

      // ── 通用高亮工具：找到 target 的父 tr 行（整行高亮） ──
      const flashTarget = (el: HTMLElement) => {
        const row = el.closest('tr');
        const ht = row || el;
        ht.scrollIntoView({ behavior: 'smooth', block: 'center' });
        ht.classList.add(styles.refRowHighlight);
        setTimeout(() => ht.classList.remove(styles.refRowHighlight), 5000);
      };

      // ═══════════ Path A: cite 引用跳转 ═══════════
      const citeEl = target.closest('cite') as HTMLElement | null;
      if (citeEl?.dataset.ref) {
        const refId = citeEl.dataset.ref;
        const refSection = sections.find((s) => /参考来源|资料来源/.test(s.title));
        if (refSection) {
          setExpandedSet((prev) => {
            if (prev.has(refSection.id)) return prev;
            const next = new Set(prev);
            next.add(refSection.id);
            return next;
          });
        }
        setTimeout(() => {
          const row = document.getElementById(`ref-row-${refId}`);
          if (row) {
            flashTarget(row);
          } else if (refSection) {
            const el = sectionEls.current.get(refSection.id);
            el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            el?.classList.add(styles.sectionHighlight);
            setTimeout(() => el?.classList.remove(styles.sectionHighlight), 5000);
          }
        }, 350);
        return;
      }

      // ═══════════ Path B: 内部链接跳转 ([A1](#a1) → <a href="#user-content-a1">) ═══════════
      const linkEl = target.closest('a[href^="#"]') as HTMLAnchorElement | null;
      if (linkEl) {
        e.preventDefault();
        const href = linkEl.getAttribute('href');
        if (!href) return;
        const anchorId = href.slice(1); // 去掉 #

        const anchor = document.getElementById(anchorId);
        if (anchor) {
          flashTarget(anchor);
        } else {
          // 目标在折叠的 section 中 → 展开全部，延迟后重试
          setExpandedSet(new Set(sections.map((s) => s.id)));
          setTimeout(() => {
            const retry = document.getElementById(anchorId);
            if (retry) flashTarget(retry);
          }, 350);
        }
      }
    },
    [sections, styles.refRowHighlight, styles.sectionHighlight]
  );

  const toggleExpand = useCallback((id: string) => {
    setExpandedSet((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const scrollToSection = useCallback(
    (id: string) => {
      // 先确保父 section 展开（子标题需要父级展开才可见）
      const parentToc = toc.find(t => t.children.some(c => c.id === id));
      const parentId = parentToc?.id;
      setExpandedSet((prev) => {
        const needsExpand = parentId && !prev.has(parentId);
        const selfNeedsExpand = !prev.has(id);
        if (needsExpand || selfNeedsExpand) {
          const next = new Set(prev);
          if (needsExpand) next.add(parentId as string);
          if (selfNeedsExpand) next.add(id);
          return next;
        }
        return prev;
      });
      setTimeout(() => {
        // v0.7.6: 优先找 h3 子标题，再 fallback h2 section
        const h3 = document.querySelector(`h3[id="${CSS.escape(id)}"]`) as HTMLElement | null;
        if (h3) {
          h3.scrollIntoView({ behavior: 'smooth', block: 'start' });
          h3.classList.add(styles.sectionHighlight);
          setTimeout(() => h3.classList.remove(styles.sectionHighlight), 5000);
          return;
        }
        const el = sectionEls.current.get(id);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'start' });
          el.classList.add(styles.sectionHighlight);
          setTimeout(() => el.classList.remove(styles.sectionHighlight), 5000);
        }
      }, 80);
    },
    [toc]
  );

  const expandAll = () => setExpandedSet(new Set(sections.map((s) => s.id)));
  const collapseAll = () => setExpandedSet(new Set());

  const mdComponents = useMemo(
    () => ({
      table: TableRenderer,
      thead: ({ children }: { children?: ReactNode }) => (
        <thead className={styles.thead}>{children}</thead>
      ),
      th: ({ children }: { children?: ReactNode }) => (
        <th className={styles.th}>{children}</th>
      ),
      td: TdRenderer,
      tr: TrRenderer,
      strong: ({ children }: { children?: ReactNode }) => (
        <strong className={styles.highlight}>{children}</strong>
      ),
      // v0.7.14: blockquote → 结论洞察框
      blockquote: ({ children }: { children?: ReactNode }) => (
        <blockquote className={styles.insight}>
          <svg className={styles.insightIcon} width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
            <path d="M8 1.5a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13Z" stroke="currentColor" strokeWidth="1.3" />
            <path d="M8 5v4M8 11v.01" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
          <div className={styles.insightContent}>{children}</div>
        </blockquote>
      ),
      // v0.7.14: paragraph → better spacing + text-indent hint
      p: ({ children }: { children?: ReactNode }) => (
        <p className={styles.paragraph}>{children}</p>
      ),
      h3: ({ children }: { children?: ReactNode }) => {
        const id = typeof children === 'string' ? slugify(children) : undefined;
        return <h3 id={id} className={styles.h3}>{children}</h3>;
      },
      h4: ({ children }: { children?: ReactNode }) => (
        <h4 className={styles.h4}>{children}</h4>
      ),
      a: ({ href, children, ...rest }: { href?: string; children?: ReactNode }) => {
        const isExternal = href && /^https?:\/\//.test(href);
        return (
          <a
            href={href}
            target={isExternal ? '_blank' : undefined}
            rel={isExternal ? 'noopener noreferrer' : undefined}
            className={`${styles.link} ${isExternal ? styles.linkExternal : ''}`}
            {...rest}
          >
            {children}
            {isExternal && (
              <svg className={styles.linkArrow} width="10" height="10" viewBox="0 0 10 10" aria-hidden>
                <path d="M1 9l8-8M3 1h6v6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
          </a>
        );
      },
    }),
    []
  );

  return (
    <ResizablePanel
      defaultLeftWidth={200}
      minLeftWidth={100}
      maxLeftWidth={350}
      storageKey="report-toc"
      left={
        <TocPanel
          toc={toc}
          expandedSet={expandedSet}
          activeId={activeId}
          onScrollTo={scrollToSection}
          onToggle={toggleExpand}
          onExpandAll={expandAll}
          onCollapseAll={collapseAll}
        />
      }
      right={
        <main className={styles.main} ref={mainRef} onClick={handleContentClick}>
          <div className={styles.contentInner}>
            <h1 className={styles.reportH1}>
              {stockName} {tsCode}
            </h1>
            <GateSummary data={gateData} />
            {gateData?.scores && gateData.scores.total > 0 && (
              <ScoreCard scores={gateData.scores} />
            )}
            {onReanalyze && (
              <div style={{ marginTop: 0, marginBottom: 16 }}>
                <button
                  className={
                    isError ? `${styles.analyzeBtn} ${styles.analyzeBtnError}`
                    : isTimeout ? `${styles.analyzeBtn} ${styles.analyzeBtnError}`
                    : (analysisStatus && !['done', 'error', 'timeout'].includes(analysisStatus.status))
                      ? `${styles.analyzeBtn} ${styles.analyzeBtnProcessing}`
                    : `${styles.analyzeBtn} ${styles.analyzeBtnOutline}`
                  }
                  onClick={onReanalyze}
                  disabled={
                    isMutating ||
                    ((analysisStatus &&
                    !['done', 'error', 'timeout'].includes(analysisStatus.status)) ?? false)
                  }
                >
                  {(analysisStatus &&
                    !['done', 'error', 'timeout'].includes(analysisStatus.status)) ? (
                    <><span className={styles.buttonSpinner} />{analysisStatus.message}</>
                  ) : isMutating ? (
                    <><span className={styles.buttonSpinner} />提交中...</>
                  ) : isTimeout ? (
                    '⚠️ 分析超时，点击重试'
                  ) : isError ? (
                    '⚠️ 分析失败，点击重试'
                  ) : (
                    '🔄 重新生成报告'
                  )}
                </button>
                {analysisStatus &&
                  !['done', 'error', 'timeout'].includes(analysisStatus.status) && (
                    <div className={styles.progressBarWrap} style={{ marginTop: 8 }}>
                      <div
                        className={styles.progressBar}
                        style={{ width: `${analysisStatus.progress}%` }}
                      />
                    </div>
                  )}
                {analysisStatus &&
                  !['done', 'error', 'timeout'].includes(analysisStatus.status) && (
                    <div className={styles.phaseLabel}>
                      {analysisStatus.message}
                    </div>
                  )}
                {(isError || isTimeout) && (
                  <div className={styles.errorBox}>
                    <strong>{isTimeout ? '⏰ 超时错误' : '⚠️ 任务错误'}</strong>
                    {analysisStatus?.message || '分析未完成，请重试'}
                  </div>
                )}
              </div>
            )}

            {/* header — stripPreamble 已切除第一个 ## 之前的所有内容 */}
            {header.trim() && (
              <div className={styles.reportTitle}>
                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw, [rehypeSanitize, sanitizeSchema]]} components={mdComponents}>
                  {header}
                </ReactMarkdown>
              </div>
            )}

            {sections.map((sec) => {
              const open = expandedSet.has(sec.id);
              return (
                <section key={sec.id} id={sec.id} className={styles.section}>
                  <h2
                    className={styles.sectionH2}
                    onClick={() => toggleExpand(sec.id)}
                    ref={registerSection(sec.id)}
                  >
                    <svg
                      className={`${styles.toggle} ${open ? styles.toggleOpen : ''}`}
                      width="18" height="18" viewBox="0 0 18 18" fill="none"
                    >
                      <path
                        d="M7 5l4 4-4 4"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                    {sec.title}
                  </h2>
                  {open && (
                    <div className={styles.sectionBody}>
                      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw, [rehypeSanitize, sanitizeSchema]]} components={mdComponents}>
                        {sec.content}
                      </ReactMarkdown>
                    </div>
                  )}
                </section>
              );
            })}

            <button
              className={`${styles.floatingBack} ${showBackTop ? styles.visible : ''}`}
              onClick={() => mainRef.current?.scrollTo({ top: 0, behavior: 'smooth' })}
            >
              ↑ 回到顶部
            </button>
          </div>
        </main>
      }
    />
  );
}
