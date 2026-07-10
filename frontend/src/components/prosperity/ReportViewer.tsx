import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import styles from './ReportViewer.module.css';

interface ReportViewerProps {
  selectedStock?: { ts_code?: string; name?: string } | null;
}

interface SessionInfo {
  id: number;
  industry: string;
  status: 'running' | 'completed' | 'failed';
  current_step: string;
}

export default function ProsperityReportViewer({ selectedStock }: ReportViewerProps) {
  const [report, setReport] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [viewedSessionId, setViewedSessionId] = useState<number | null>(null);

  // 加载会话列表
  useEffect(() => {
    axios
      .get('/api/prosperity/sessions')
      .then((r) => {
        if (r.data?.sessions) {
          setSessions(r.data.sessions);
          // 自动加载最新完成的报告
          const latest = r.data.sessions
            .filter((s: SessionInfo) => s.status === 'completed')
            .sort((a: SessionInfo, b: SessionInfo) => b.id - a.id)[0];
          if (latest) {
            loadReport(latest.id);
          }
        }
      })
      .catch(() => {});
  }, []);

  const loadReport = useCallback(async (sessionId: number) => {
    setLoading(true);
    setViewedSessionId(sessionId);
    try {
      const r = await axios.get(`/api/prosperity/session/${sessionId}/report`);
      setReport(r.data?.markdown || r.data?.report || '暂无报告内容');
    } catch {
      setReport('报告加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  if (loading) {
    return <div className={styles.loading}>加载报告中...</div>;
  }

  if (!report) {
    return (
      <div className={styles.container}>
        {sessions.filter((s) => s.status === 'completed').length > 0 && (
          <div className={styles.sessionList}>
            <h3 className={styles.listTitle}>已完成的研究</h3>
            {sessions
              .filter((s) => s.status === 'completed')
              .sort((a, b) => b.id - a.id)
              .map((s) => (
                <button
                  key={s.id}
                  className={`${styles.sessionBtn} ${viewedSessionId === s.id ? styles.active : ''}`}
                  onClick={() => loadReport(s.id)}
                >
                  📊 {s.industry} 景气分析
                </button>
              ))}
          </div>
        )}
        {sessions.filter((s) => s.status === 'completed').length === 0 && (
          <div className={styles.placeholder}>开始研究后将在此展示综合报告</div>
        )}
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <div className={styles.report}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeRaw]}
        >
          {report}
        </ReactMarkdown>
      </div>
    </div>
  );
}
