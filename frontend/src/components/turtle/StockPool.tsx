import { useRef, useCallback, useState, Fragment } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';
import type { StockPoolItem, GateResult, AnalysisReport } from '../../types';
import ScoreCard from './ScoreCard';
import styles from './StockPool.module.css';

// ── 汉堡图标 ─────────────────────────────────────
function HamburgerIcon() {
  return (
    <svg width="18" height="14" viewBox="0 0 18 14" fill="none"
      stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <line x1="1" y1="1" x2="17" y2="1" />
      <line x1="1" y1="7" x2="17" y2="7" />
      <line x1="1" y1="13" x2="17" y2="13" />
    </svg>
  );
}

interface StockPoolProps {
  selectedStock: { ts_code: string; name: string } | null;
  onSelectStock: (ts_code: string, name: string) => void;
  onToggleSidebar: () => void;
}

export default function StockPool({ selectedStock, onSelectStock, onToggleSidebar }: StockPoolProps) {
  const queryClient = useQueryClient();
  const hoverTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const HOVER_DELAY = 250; // 悬停 250ms 后预加载

  const [highlightIdx, setHighlightIdx] = useState(-1);

  const {
    data: pool = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery<StockPoolItem[]>({
    queryKey: ['stockPool', 'turtle'],
    queryFn: async () => {
      const { data } = await axios.get('/api/turtle/pool?limit=200');
      return data;
    },
    staleTime: 5 * 60 * 1000,
  });

  // 拉取选中股票的门控结果（含 scores）
  const { data: expandedGate } = useQuery<GateResult>({
    queryKey: ['gates', selectedStock?.ts_code],
    queryFn: async () => {
      const { data } = await axios.get(`/api/turtle/${selectedStock!.ts_code}/gates`);
      return data;
    },
    enabled: !!selectedStock,
    staleTime: 10 * 60 * 1000,
  });

  const prefetchStock = useCallback((ts_code: string, has_report: boolean) => {
    if (!has_report) return; // 没有报告不浪费请求

    // 预加载门控结果
    queryClient.prefetchQuery({
      queryKey: ['gates', ts_code],
      queryFn: async () => {
        const { data } = await axios.get<GateResult>(`/api/turtle/${ts_code}/gates`);
        return data;
      },
      staleTime: 10 * 60 * 1000,
    });

    // 预加载分析报告
    queryClient.prefetchQuery({
      queryKey: ['analysis', ts_code],
      queryFn: async () => {
        const { data } = await axios.get<AnalysisReport>(`/api/turtle/${ts_code}/analysis`);
        return data;
      },
      staleTime: 10 * 60 * 1000,
    });
  }, [queryClient]);

  const handleMouseEnter = useCallback((item: StockPoolItem) => {
    const timer = setTimeout(() => {
      prefetchStock(item.ts_code, item.has_report ?? false);
      hoverTimers.current.delete(item.ts_code);
    }, HOVER_DELAY);
    hoverTimers.current.set(item.ts_code, timer);
  }, [prefetchStock]);

  const handleMouseLeave = useCallback((ts_code: string) => {
    const timer = hoverTimers.current.get(ts_code);
    if (timer) {
      clearTimeout(timer);
      hoverTimers.current.delete(ts_code);
    }
  }, []);

  // P2: 键盘快捷键 ↑↓ 浏览 Enter 选中 Esc 取消
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlightIdx(prev => Math.min(prev + 1, Math.max(pool.length - 1, 0)));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlightIdx(prev => Math.max(prev - 1, -1));
    } else if (e.key === 'Enter' && highlightIdx >= 0 && highlightIdx < pool.length) {
      const item = pool[highlightIdx];
      onSelectStock(item.ts_code, item.name);
    } else if (e.key === 'Escape') {
      if (highlightIdx >= 0) setHighlightIdx(-1);
    }
  }, [pool, highlightIdx, onSelectStock]);

  return (
    <div className={styles.container} tabIndex={0} onKeyDown={handleKeyDown}>
      <div className={styles.header}>
        <button className={styles.hamburger} onClick={onToggleSidebar} title="切换侧边栏">
          <HamburgerIcon />
        </button>
        <span className={styles.meta}>
          {pool.length} 只标的
        </span>
      </div>

      <div className={styles.tableWrap}>
        {isLoading ? (
          <div className={styles.loading}>加载中...</div>
        ) : isError ? (
          <div className={styles.error}>
            <span>加载失败：{(error as Error)?.message || '无法连接到后端'}</span>
            <button onClick={() => refetch()} className={styles.retryBtn}>
              重试
            </button>
          </div>
        ) : pool.length === 0 ? (
          <div className={styles.empty}>暂无数据</div>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>名称 / 代码</th>
                <th>QRV评分</th>
                <th>穿透回报率</th>
                <th>门控</th>
                <th>行业</th>
              </tr>
            </thead>
            <tbody>
              {pool.map((item, i) => {
                const isSelected = selectedStock?.ts_code === item.ts_code;
                const hasScores = item.scores && item.scores.total > 0;
                const scorePct = hasScores ? item.scores!.total * 10 : 0;

                return (
                  <Fragment key={item.ts_code}>
                    <tr
                      className={`${styles.row} ${isSelected ? styles.selected : ''} ${i === highlightIdx ? styles.highlighted : ''}`}
                      onClick={() => onSelectStock(item.ts_code, item.name)}
                      onMouseEnter={() => handleMouseEnter(item)}
                      onMouseLeave={() => handleMouseLeave(item.ts_code)}
                    >
                      <td>
                        <div className={styles.nameCol}>{item.name}</div>
                        <div className={styles.codeCol}>{item.ts_code}</div>
                      </td>
                      <td>
                        {hasScores ? (
                          <div className={styles.scoreInline}>
                            <div className={styles.scoreBar}>
                              <div
                                className={styles.scoreFill}
                                style={{ width: `${scorePct}%` }}
                              />
                            </div>
                            <span className={styles.scoreNum}>
                              {item.scores!.total.toFixed(1)}
                            </span>
                          </div>
                        ) : (
                          <span className={styles.noScore}>
                            {item.has_report ? '—' : '点击分析 →'}
                          </span>
                        )}
                      </td>
                      <td>
                        <span
                          className={
                            item.pr >= 5.5 ? styles.prGood : styles.prWarn
                          }
                        >
                          {item.pr.toFixed(2)}%
                        </span>
                      </td>
                      <td>
                        <div className={styles.gateGroup}>
                          <span
                            className={`${styles.gateBadge} ${
                              item.cq_passed ? styles.gatePass : styles.gateFail
                            }`}
                          >
                            CQ
                          </span>
                          <span
                            className={`${styles.gateBadge} ${
                              item.pr_passed ? styles.gatePass : styles.gateFail
                            }`}
                          >
                            PR
                          </span>
                        </div>
                      </td>
                      <td>{item.industry}</td>
                    </tr>

                    {/* 选中时展开打分卡 */}
                    {isSelected && expandedGate?.scores && expandedGate.scores.total > 0 && (
                      <tr className={styles.expandedRow}>
                        <td colSpan={5} className={styles.expandedCell}>
                          <div className={styles.expandedInner}>
                            <ScoreCard scores={expandedGate.scores} compact />
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
