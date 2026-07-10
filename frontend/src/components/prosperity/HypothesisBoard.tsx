import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import styles from './HypothesisBoard.module.css';

interface Hypothesis {
  id: string;
  title: string;
  statement: string;
  chain_level: number;
  derives_from: string | null;
  status: string;
  confidence: number;
  time_horizon?: string;
  investment_implication?: string;
}

interface SessionInfo {
  id: number;
  industry: string;
  status: 'running' | 'completed' | 'failed';
  current_step: string;
}

interface HypothesisBoardProps {
  selectedStock?: { ts_code?: string; name?: string } | null;
  onSelectStock?: (ts_code: string, name: string) => void;
  onToggleSidebar?: () => void;
}

const LEVEL_LABELS: Record<number, { label: string; color: string }> = {
  0: { label: 'L0 现状诊断', color: '#0891b2' },
  1: { label: 'L1 一阶推演', color: '#2563eb' },
  2: { label: 'L2 二阶推演', color: '#7c3aed' },
  3: { label: 'L3 投资落点', color: '#dc2626' },
};

const STATUS_EMOJI: Record<string, string> = {
  CONFIRMED: '✅',
  PARTIAL: '⚠️',
  DISPUTED: '❌',
  UNVERIFIED: '🔍',
  UNREACHABLE: '🚫',
  OVERTURNED: '⚰️',
};

function groupByLevel(hypotheses: Hypothesis[]): Map<number, Hypothesis[]> {
  const map = new Map<number, Hypothesis[]>();
  for (const h of hypotheses) {
    const list = map.get(h.chain_level) || [];
    list.push(h);
    map.set(h.chain_level, list);
  }
  // Sort levels
  return new Map([...map.entries()].sort((a, b) => a[0] - b[0]));
}

export default function HypothesisBoard({ onToggleSidebar }: HypothesisBoardProps) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [loading, setLoading] = useState(false);

  // 加载历史会话列表
  useEffect(() => {
    axios
      .get('/api/prosperity/sessions')
      .then((r) => {
        if (r.data?.sessions) setSessions(r.data.sessions);
      })
      .catch(() => {});
  }, []);

  // 加载选中会话的假设
  const loadHypotheses = useCallback(async (sessionId: number) => {
    setLoading(true);
    try {
      const r = await axios.get(`/api/prosperity/session/${sessionId}/hypotheses`);
      setHypotheses(r.data?.hypotheses || []);
      setActiveSessionId(sessionId);
    } catch {
      setHypotheses([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const grouped = groupByLevel(hypotheses);

  return (
    <div className={styles.container}>
      {/* 会话选择器 */}
      {sessions.length > 0 && (
        <div className={styles.sessionBar}>
          <select
            className={styles.sessionSelect}
            value={activeSessionId || ''}
            onChange={(e) => {
              const id = Number(e.target.value);
              if (id) loadHypotheses(id);
            }}
          >
            <option value="">选择研究会话...</option>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.industry} — {s.status === 'completed' ? '✅' : '🔄'} {s.current_step}
              </option>
            ))}
          </select>
        </div>
      )}

      {loading && <div className={styles.loading}>加载假设中...</div>}

      {/* 推理链看板 */}
      {activeSessionId && !loading && (
        <div className={styles.board}>
          {hypotheses.length === 0 ? (
            <div className={styles.empty}>暂无疑设数据</div>
          ) : (
            [...grouped.entries()].map(([level, items]) => {
              const meta = LEVEL_LABELS[level] || {
                label: `L${level}`,
                color: '#999',
              };
              return (
                <div key={level} className={styles.levelSection}>
                  <h3 className={styles.levelHeader} style={{ color: meta.color }}>
                    {meta.label}
                    <span className={styles.count}>{items.length}</span>
                  </h3>
                  {items.map((h) => (
                    <div
                      key={h.id}
                      className={`${styles.card} ${h.status === 'UNREACHABLE' ? styles.unreachable : ''}`}
                    >
                      <div className={styles.cardHeader}>
                        <span className={styles.cardId}>{h.id}</span>
                        <span className={styles.cardStatus}>
                          {STATUS_EMOJI[h.status] || '🔍'} {h.status}
                        </span>
                        {h.confidence > 0 && (
                          <span className={styles.confidence}>
                            {Math.round(h.confidence * 100)}%
                          </span>
                        )}
                      </div>
                      <p className={styles.statement}>{h.statement}</p>
                      {h.derives_from && (
                        <div className={styles.derives}>
                          ← 源自 {h.derives_from}
                        </div>
                      )}
                      {h.time_horizon && (
                        <div className={styles.horizon}>⏱ {h.time_horizon}</div>
                      )}
                      {h.investment_implication && (
                        <div className={styles.implication}>
                          💡 {h.investment_implication}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              );
            })
          )}
        </div>
      )}

      {!activeSessionId && sessions.length === 0 && (
        <div className={styles.placeholder}>
          输入行业名称开始研究
        </div>
      )}
    </div>
  );
}
