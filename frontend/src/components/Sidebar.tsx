import { useQuery } from '@tanstack/react-query';
import axios from 'axios';
import styles from './Sidebar.module.css';
import type { Strategy } from '../types';

// ── SVG 图标组件 ─────────────────────────────────────
function StrategyIcon({ type, active }: { type: string; active?: boolean }) {
  const color = active ? 'var(--accent-primary)' : 'var(--text-tertiary)';
  const w = 18, h = 18;

  if (type === 'turtle') {
    // 圆形靶心 + 十字准星
    return (
      <svg width={w} height={h} viewBox="0 0 18 18" fill="none"
        stroke={color} strokeWidth="1.4" strokeLinecap="round">
        <circle cx="9" cy="9" r="7" />
        <line x1="2" y1="9" x2="16" y2="9" />
        <line x1="9" y1="2" x2="9" y2="16" />
      </svg>
    );
  }
  // 上升趋势箭头
  return (
    <svg width={w} height={h} viewBox="0 0 18 18" fill="none"
      stroke={color} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="2,13 7,7 12,11 16,4" />
      <polyline points="12,4 16,4 16,8" />
    </svg>
  );
}

/** Argus 百眼巨人 Logo — 中央眼 + 环周"百眼" + 十字准星 */
function LogoIcon() {
  const eyes = [0, 45, 90, 135, 180, 225, 270, 315].map((deg) => {
    const rad = (deg * Math.PI) / 180;
    return { cx: (13 + 8 * Math.cos(rad)).toFixed(2), cy: (13 + 8 * Math.sin(rad)).toFixed(2) };
  });

  return (
    <svg width="26" height="26" viewBox="0 0 26 26" fill="none">
      <circle cx="13" cy="13" r="11" fill="var(--accent-primary)" />
      {eyes.map((e, i) => (
        <circle key={i} cx={e.cx} cy={e.cy} r="1.6" fill="#fff" opacity="0.85" />
      ))}
      <circle cx="13" cy="13" r="4.5" fill="none" stroke="#fff" strokeWidth="1.5" />
      <line x1="13" y1="1.5" x2="13" y2="6.5" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" />
      <line x1="13" y1="19.5" x2="13" y2="24.5" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" />
      <line x1="1.5" y1="13" x2="6.5" y2="13" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" />
      <line x1="19.5" y1="13" x2="24.5" y2="13" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

interface SidebarProps {
  collapsed?: boolean;
  selectedStrategy: string;
  onStrategyChange: (id: string) => void;
}

export default function Sidebar({ collapsed = false, selectedStrategy, onStrategyChange }: SidebarProps) {
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      const { data } = await axios.get('/api/health');
      return data as { version: string };
    },
    staleTime: Infinity,
  });

  // 动态策略列表 — 从 /api/strategies 获取
  const { data: strategies = [] } = useQuery<Strategy[]>({
    queryKey: ['strategies'],
    queryFn: async () => {
      const { data } = await axios.get('/api/strategies');
      return data;
    },
    staleTime: Infinity,
  });

  const { data: status } = useQuery({
    queryKey: ['status'],
    queryFn: async () => {
      const { data } = await axios.get('/api/turtle/status');
      return data as { data_updated_at: string };
    },
    staleTime: 60 * 60 * 1000,
  });

  return (
    <aside className={`${styles.sidebar} ${collapsed ? styles.collapsed : ''}`}>
      <div className={styles.header}>
        <div className={styles.logo}>
          <LogoIcon />
          {!collapsed && 'Argus'}
        </div>
        {!collapsed && <span className={styles.subtitle}>Investment Strategy {health?.version || 'v0.8.0'}</span>}
      </div>

      <nav className={styles.nav}>
        {!collapsed && <div className={styles.navLabel}>策略</div>}
        {strategies.map((s) => {
          const isActive = s.id === selectedStrategy;
          return (
            <div
              key={s.id}
              className={`${styles.navItem} ${isActive ? styles.active : ''}`}
              title={collapsed ? s.name : undefined}
              onClick={() => {
                if (s.status === 'active') {
                  onStrategyChange(s.id);
                }
              }}
              style={s.status === 'inactive' ? { opacity: 0.5, cursor: 'not-allowed' } : { cursor: 'pointer' }}
            >
              <span className={styles.navIcon}>
                <StrategyIcon type={s.icon || 'growth'} active={isActive} />
              </span>
              {!collapsed && <span className={styles.navName}>{s.name}</span>}
              {!collapsed && s.badge && <span className={styles.badge}>{s.badge}</span>}
            </div>
          );
        })}
      </nav>

      {!collapsed && (
        <div className={styles.footer}>
          数据来源：Tushare · {status?.data_updated_at || '—'}
        </div>
      )}
    </aside>
  );
}
