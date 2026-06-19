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
import rehypeSanitize from 'rehype-sanitize';
import ResizablePanel from './ResizablePanel';
import ScoreCard from './ScoreCard';
import type { GateResult, AnalysisReport } from '../types';
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

// ── Helpers ────────────────────────────────────────────

function slugify(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^\w\u4e00-\u9fff]+/g, '-')
    .replace(/(^-|-$)/g, '')
    || 'section';
}

/** 过滤 LLM 角色身份文本 — 去掉 "好的，收到您的指令。作为一名拥有15年A股..." 这类段落 */
function stripLlmRole(text: string): string {
  return text
    // 匹配 LLM 自我角色设定段落，.{5,200} 覆盖最长约 120 字的中文角色陈述
    .replace(/^(好的[，,]?\s*)?(收到您的指令[。.]?\s*)?作为一名.{2,30}(资深CFA|分析师|价值投资|投资研究|持证人).{5,200}?\n+/gm, '')
    .replace(/^\*\*分析师[：:]\*\*.*\n+/gm, '')
    .replace(/^\*\*核心铁律[：:].*\n+/gm, '')
    .replace(/^在开始前[，,].*\n+/gm, '')
    .replace(/^我将严格遵循您的.*\n+/gm, '')
    .replace(/^我将以.{2,30}(身份|角色|分析师).{5,200}?\n+/gm, '')
    .replace(/^(我的|我们的)(任务目标|分析任务).{5,200}?\n+/gm, '')
    .trim();
}

/** 过滤 header 中的 # 一级标题行（避免与组件的股票名 H1 重复） */
function stripHeaderTitle(header: string): string {
  return header
    .replace(/^#\s+.+[\n]+/gm, '')
    .replace(/^##\s+QRV\s+深度分析报告\s*[\n]+/gm, '')
    .trim();
}

/** 预处理 markdown：将 [REF001] 转为 <cite> HTML 标签，由 rehype-raw 安全渲染。
 *  替代原来危险的 injectCitationElements + replaceChild 原生 DOM 操作。 */
function preprocessCitations(md: string): string {
  return md.replace(
    /\[([A-Z][-\w]*\d+)\]/g,
    '<cite data-ref="$1" id="cite-$1">[$1]</cite>'
  );
}

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
  if (/摘要|打分|研判|建议/.test(title)) return true;
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

// ── TOC Panel ──────────────────────────────────────────

function TocPanel({
  toc,
  expandedSet,
  activeId,
  onScrollTo,
  onExpandAll,
  onCollapseAll,
}: {
  toc: TocItem[];
  expandedSet: Set<string>;
  activeId: string;
  onScrollTo: (id: string) => void;
  onExpandAll: () => void;
  onCollapseAll: () => void;
}) {
  return (
    <div className={styles.toc}>
      <div className={styles.tocHeader}>
        <h3 className={styles.tocTitle}>报告目录</h3>
        <div className={styles.tocActions}>
          <button className={styles.tocBtn} onClick={onExpandAll} title="展开全部">
            展开
          </button>
          <button className={styles.tocBtn} onClick={onCollapseAll} title="折叠全部">
            折叠
          </button>
        </div>
      </div>
      <nav className={styles.tocNav}>
        {toc.map((item) => (
          <div key={item.id} className={styles.tocGroup}>
            <button
              className={`${styles.tocLink} ${activeId === item.id ? styles.tocLinkActive : ''}`}
              onClick={() => onScrollTo(item.id)}
            >
              {item.title}
            </button>
            {item.children.length > 0 && expandedSet.has(item.id) && (
              <div className={styles.tocSub}>
                {item.children.map((sub) => (
                  <button
                    key={sub.id}
                    className={styles.tocSubLink}
                    onClick={() => onScrollTo(item.id)}
                  >
                    {sub.title}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
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
      const { data } = await axios.get(`/api/stocks/${selectedStock!.ts_code}/gates`);
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
      const { data } = await axios.get(`/api/stocks/${selectedStock!.ts_code}/analysis`);
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

  type AnalysisEntry = { status: string; progress: number; message: string };

  const [analysisMap, setAnalysisMap] = useState<Record<string, AnalysisEntry>>({});
  const analysisMapRef = useRef(analysisMap);
  analysisMapRef.current = analysisMap;

  // Keep refetchReport stable across polls
  const refetchReportRef = useRef(refetchReport);
  refetchReportRef.current = refetchReport;

  // Persistent poller: runs for component lifetime, uses refs to avoid dep churn
  useEffect(() => {
    const interval = setInterval(async () => {
      const map = analysisMapRef.current;
      const activeCodes = Object.entries(map)
        .filter(([, v]) => v.status !== 'done' && v.status !== 'error')
        .map(([code]) => code);

      if (activeCodes.length === 0) return;

      const results = await Promise.allSettled(
        activeCodes.map(async (code) => {
          const { data } = await axios.get(`/api/stocks/${code}/analyze/status`);
          return [code, data] as const;
        }),
      );

      setAnalysisMap(prev => {
        const next = { ...prev };
        let changed = false;
        for (const r of results) {
          if (r.status === 'fulfilled') {
            const [code, data] = r.value;
            const entry = {
              status: data.status as string,
              progress: (data.progress ?? 0) as number,
              message: (data.message ?? '') as string,
            };
            const old = prev[code];
            if (!old || old.status !== entry.status || old.progress !== entry.progress || old.message !== entry.message) {
              next[code] = entry;
              changed = true;
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
      const timer = setTimeout(() => {
        refetchReportRef.current();
        // Clean up done entry so it doesn't re-trigger
        setAnalysisMap(prev => {
          if (prev[selectedStock.ts_code]?.status !== 'done') return prev;
          const next = { ...prev };
          delete next[selectedStock.ts_code];
          return next;
        });
      }, 800);
      return () => clearTimeout(timer);
    }
  }, [analysisMap, selectedStock]);

  // Analyze mutation — per-stock tracking via analysisMap
  const analyzeMutation = useMutation({
    mutationFn: async (tsCode: string) => {
      await axios.post(`/api/stocks/${tsCode}/analyze`);
    },
    onSuccess: (_data, tsCode) => {
      setAnalysisMap(prev => ({
        ...prev,
        [tsCode]: { status: 'fetching', progress: 0, message: '正在拉取财务数据...' },
      }));
    },
    onError: (error: unknown, tsCode) => {
      let errMsg = '请求失败，请确认后端服务已启动';
      if (error && typeof error === 'object') {
        const axiosErr = error as { response?: { data?: { detail?: string } }; message?: string };
        errMsg = axiosErr.response?.data?.detail || axiosErr.message || errMsg;
      }
      setAnalysisMap(prev => ({
        ...prev,
        [tsCode]: { status: 'error', progress: 0, message: errMsg },
      }));
    },
  });

  // Derived: current selected stock's analysis status
  const currentStatus = selectedStock ? analysisMap[selectedStock.ts_code] : undefined;

  // ── Empty State ────────────────────────
  if (!selectedStock) {
    return (
      <div className={styles.emptyState}>
        <div className={styles.emptyIcon}>📊</div>
        <div className={styles.emptyText}>请从股池选择一只股票</div>
        <div className={styles.emptyHint}>点击左侧股池中的个股查看 QRV 深度分析报告</div>
      </div>
    );
  }

  if (reportLoading && !reportData) {
    return (
      <div className={styles.emptyState}>
        <GateSummary data={gateData} />
        <div className={styles.emptyText}>加载报告中...</div>
        <div className={styles.emptyHint}>{selectedStock.name}（{selectedStock.ts_code}）正在获取分析报告</div>
      </div>
    );
  }

  if (!reportData?.report_markdown || reportError) {
    const isAnalyzing = currentStatus &&
      !['done', 'error'].includes(currentStatus.status);
    const isError = currentStatus?.status === 'error';

    return (
      <div className={styles.emptyState}>
        <GateSummary data={gateData} />
        <div className={styles.emptyText}>
          {isAnalyzing ? '正在分析中...' : isError ? '分析失败' : '暂无分析报告'}
        </div>
        <div className={styles.emptyHint}>
          {isAnalyzing
            ? `${selectedStock.name}（${selectedStock.ts_code}）${currentStatus.message}`
            : isError
              ? `${currentStatus.message}`
              : `${selectedStock.name}（${selectedStock.ts_code}）尚未生成 QRV 分析报告`
          }
        </div>

        {isAnalyzing && (
          <div className={styles.progressBarWrap}>
            <div className={styles.progressBar} style={{ width: `${currentStatus.progress}%` }} />
          </div>
        )}
        {isAnalyzing && (
          <div className={styles.progressLabel}>
            {currentStatus.progress}%
          </div>
        )}

        <button
          className={styles.analyzeBtn}
          disabled={isAnalyzing ?? false}
          onClick={() => analyzeMutation.mutate(selectedStock.ts_code)}
        >
          {analyzeMutation.isPending ? '提交中...' : isAnalyzing ? '⏳ 分析中...' : '🔍 分析个股'}
        </button>
        {isError && (
          <div className={styles.emptyHint} style={{ color: 'var(--negative)', marginTop: 8 }}>
            请稍后重试
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
      onReanalyze={() => {
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
  } | null;
  onReanalyze?: () => void;
}) {
  const { header, sections } = useMemo(() => parseMarkdown(reportMarkdown), [reportMarkdown]);
  const toc = useMemo(() => extractToc(sections), [sections]);

  const [expandedSet, setExpandedSet] = useState<Set<string>>(() => {
    const init = new Set<string>();
    sections.forEach((s) => {
      if (isDefaultExpanded(s.title)) init.add(s.id);
    });
    return init;
  });
  const [activeId, setActiveId] = useState('');

  const sectionEls = useRef<Map<string, HTMLElement>>(new Map());
  const mountedRef = useRef(true);

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

  const registerSection = useCallback(
    (id: string) => (el: HTMLHeadingElement | null) => {
      if (el) sectionEls.current.set(id, el);
    },
    []
  );

  const handleCiteClick = useCallback(
    (e: React.MouseEvent) => {
      const target = e.target as HTMLElement;
      const citeEl = target.closest('cite') as HTMLElement | null;
      if (!citeEl || !citeEl.dataset.ref) return;
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
      // 加大延迟确保 expand 动画完成 + DOM 渲染
      setTimeout(() => {
        const row = document.getElementById(`ref-row-${refId}`);
        if (row) {
          row.scrollIntoView({ behavior: 'smooth', block: 'center' });
          row.classList.add(styles.refRowHighlight);
          setTimeout(() => row.classList.remove(styles.refRowHighlight), 2000);
        } else if (refSection) {
          // 兜底：找不到具体行时滚动到参考来源 section
          const el = sectionEls.current.get(refSection.id);
          el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
          el?.classList.add(styles.sectionHighlight);
          setTimeout(() => el?.classList.remove(styles.sectionHighlight), 2000);
        }
      }, 350);
    },
    [sections]
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
      setExpandedSet((prev) => {
        if (prev.has(id)) return prev;
        const next = new Set(prev);
        next.add(id);
        return next;
      });
      setTimeout(() => {
        const el = sectionEls.current.get(id);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'start' });
          // 高亮动画 2 秒
          el.classList.add(styles.sectionHighlight);
          setTimeout(() => el.classList.remove(styles.sectionHighlight), 2000);
        }
      }, 80);
    },
    []
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
      h3: ({ children }: { children?: ReactNode }) => {
        const id = typeof children === 'string' ? slugify(children) : undefined;
        return <h3 id={id} className={styles.h3}>{children}</h3>;
      },
      h4: ({ children }: { children?: ReactNode }) => (
        <h4 className={styles.h4}>{children}</h4>
      ),
      a: ({ href, children }: { href?: string; children?: ReactNode }) => {
        const isExternal = href && /^https?:\/\//.test(href);
        return (
          <a
            href={href}
            target={isExternal ? '_blank' : undefined}
            rel={isExternal ? 'noopener noreferrer' : undefined}
            className={styles.link}
          >
            {children}
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
          onExpandAll={expandAll}
          onCollapseAll={collapseAll}
        />
      }
      right={
        <main className={styles.main} onClick={handleCiteClick}>
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
                  className={styles.analyzeBtn}
                  onClick={onReanalyze}
                  disabled={
                    (analysisStatus &&
                    !['done', 'error'].includes(analysisStatus.status)) ?? false
                  }
                >
                  {analysisStatus &&
                  !['done', 'error'].includes(analysisStatus.status)
                    ? `⏳ ${analysisStatus.message}`
                    : '🔄 重新分析'}
                </button>
                {analysisStatus &&
                  !['done', 'error'].includes(analysisStatus.status) && (
                    <div className={styles.progressBarWrap} style={{ marginTop: 8 }}>
                      <div
                        className={styles.progressBar}
                        style={{ width: `${analysisStatus.progress}%` }}
                      />
                    </div>
                  )}
                {analysisStatus?.status === 'error' && (
                  <div
                    className={styles.emptyHint}
                    style={{ color: 'var(--negative)', marginTop: 4 }}
                  >
                    {analysisStatus.message}
                  </div>
                )}
              </div>
            )}

            {/* 过滤后的 header（去掉 LLM 角色语 + # 标题） */}
            {(() => {
              const cleanHeader = stripLlmRole(stripHeaderTitle(header));
              if (cleanHeader.trim()) {
                return (
                  <div className={styles.reportTitle}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw, rehypeSanitize]} components={mdComponents}>
                      {cleanHeader}
                    </ReactMarkdown>
                  </div>
                );
              }
              return null;
            })()}

            {sections.map((sec) => {
              const open = expandedSet.has(sec.id);
              const cleanContent = stripLlmRole(sec.content);
              return (
                <section key={sec.id} id={sec.id} className={styles.section}>
                  <h2
                    className={styles.sectionH2}
                    onClick={() => toggleExpand(sec.id)}
                    ref={registerSection(sec.id)}
                  >
                    <span className={styles.toggle}>{open ? '▾' : '▸'}</span>
                    {sec.title}
                  </h2>
                  {open && (
                    <div className={styles.sectionBody}>
                      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw, rehypeSanitize]} components={mdComponents}>
                        {cleanContent}
                      </ReactMarkdown>
                    </div>
                  )}
                </section>
              );
            })}

            <button
              className={styles.backTop}
              onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
            >
              ↑ 回到顶部
            </button>
          </div>
        </main>
      }
    />
  );
}
