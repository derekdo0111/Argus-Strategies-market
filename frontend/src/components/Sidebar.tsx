import styles from './Sidebar.module.css';

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

const strategies = [
  { id: 'turtle', name: '龟龟策略', icon: 'turtle', active: true },
  { id: 'growth', name: '高景气价值股策略', icon: 'growth', badge: '预留' },
];

interface SidebarProps {
  collapsed?: boolean;
}

export default function Sidebar({ collapsed = false }: SidebarProps) {
  return (
    <aside className={`${styles.sidebar} ${collapsed ? styles.collapsed : ''}`}>
      <div className={styles.header}>
        <div className={styles.logo}>
          <span className={styles.logoIcon}>A</span>
          {!collapsed && 'Argus'}
        </div>
        {!collapsed && <span className={styles.subtitle}>Investment Strategy v0.6.7</span>}
      </div>

      <nav className={styles.nav}>
        {!collapsed && <div className={styles.navLabel}>策略</div>}
        {strategies.map((s) => (
          <div
            key={s.id}
            className={`${styles.navItem} ${s.active ? styles.active : ''}`}
            title={collapsed ? s.name : undefined}
          >
            <span className={styles.navIcon}>
              <StrategyIcon type={s.icon} active={s.active} />
            </span>
            {!collapsed && <span className={styles.navName}>{s.name}</span>}
            {!collapsed && s.badge && <span className={styles.badge}>{s.badge}</span>}
          </div>
        ))}
      </nav>

      {!collapsed && (
        <div className={styles.footer}>
          数据来源：Tushare · 2026-06-19
        </div>
      )}
    </aside>
  );
}
