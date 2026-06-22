/** 高景气价值策略 — 股池占位组件 */

interface Props {
  selectedStock: { ts_code: string; name: string } | null;
  onSelectStock: (ts_code: string, name: string) => void;
  onToggleSidebar: () => void;
}

export default function ProsperityStockPool({ onToggleSidebar }: Props) {
  // 汉堡图标
  const HamburgerIcon = () => (
    <svg width="18" height="14" viewBox="0 0 18 14" fill="none"
      stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <line x1="1" y1="1" x2="17" y2="1" />
      <line x1="1" y1="7" x2="17" y2="7" />
      <line x1="1" y1="13" x2="17" y2="13" />
    </svg>
  );

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
    }}>
      <div style={{
        padding: '12px 16px',
        borderBottom: '1px solid var(--border-subtle)',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
      }}>
        <button
          onClick={onToggleSidebar}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--text-secondary)',
            cursor: 'pointer',
            padding: 4,
          }}
        >
          <HamburgerIcon />
        </button>
        <span style={{ fontWeight: 600, fontSize: 15 }}>高景气价值股策略</span>
      </div>
      <div style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'var(--text-tertiary)',
        padding: 40,
        textAlign: 'center',
      }}>
        <div>
          <h3 style={{ margin: 0, marginBottom: 8, color: 'var(--text-secondary)' }}>
            高景气价值股策略
          </h3>
          <p style={{ margin: 0, fontSize: 14 }}>开发中，敬请期待</p>
        </div>
      </div>
    </div>
  );
}
