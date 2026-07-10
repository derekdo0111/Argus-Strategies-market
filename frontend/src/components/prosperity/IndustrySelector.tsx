import { useState, useCallback } from 'react';
import axios from 'axios';
import styles from './IndustrySelector.module.css';

const STEPS = [
  { key: 'idle', label: '' },
  { key: 'search', label: '情报搜索' },
  { key: 'hypothesize', label: '假设形成' },
  { key: 'verify', label: '交叉验证' },
  { key: 'counter', label: '反推修正' },
  { key: 'report', label: '生成报告' },
  { key: 'done', label: '完成' },
];

export interface SessionInfo {
  id: number;
  industry: string;
  status: 'running' | 'completed' | 'failed';
  current_step: string;
}

interface IndustrySelectorProps {
  onSessionStart: (session: SessionInfo) => void;
}

export default function IndustrySelector({ onSessionStart }: IndustrySelectorProps) {
  const [industry, setIndustry] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleStart = useCallback(async () => {
    const trimmed = industry.trim();
    if (!trimmed) {
      setError('请输入行业名称');
      return;
    }
    setError('');
    setLoading(true);

    try {
      // 创建研究会话
      const resp = await axios.post('/api/prosperity/start', { industry: trimmed });
      const session: SessionInfo = resp.data;
      onSessionStart(session);
    } catch (e: any) {
      setError(e?.response?.data?.detail || '启动研究失败');
    } finally {
      setLoading(false);
    }
  }, [industry, onSessionStart]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !loading) handleStart();
    },
    [handleStart, loading],
  );

  return (
    <div className={styles.container}>
      <h2 className={styles.title}>行业景气研究</h2>
      <p className={styles.subtitle}>
        6 Agent 因果推理链 · 4层假设 (L0→L3)
      </p>

      <div className={styles.form}>
        <input
          className={styles.input}
          type="text"
          placeholder="输入行业名称，如：半导体、新能源、医药..."
          value={industry}
          onChange={(e) => setIndustry(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading}
        />
        <button
          className={styles.btn}
          onClick={handleStart}
          disabled={loading || !industry.trim()}
        >
          {loading ? '启动中...' : '开始研究'}
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.flow}>
        <span className={styles.flowArrow}>研究流程：</span>
        {STEPS.filter((s) => s.key !== 'idle').map((s, i, arr) => (
          <span key={s.key} className={styles.flowStep}>
            {s.label}
            {i < arr.length - 1 && <span className={styles.flowSep}> → </span>}
          </span>
        ))}
      </div>
    </div>
  );
}
