/** 高景气价值策略 — 报告占位组件 */

interface Props {
  selectedStock: { ts_code: string; name: string } | null;
}

export default function ProsperityReportViewer({ selectedStock }: Props) {
  return (
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
          高景气价值报告
        </h3>
        <p style={{ margin: 0, fontSize: 14 }}>
          {selectedStock
            ? `选中: ${selectedStock.name} (${selectedStock.ts_code})`
            : '请点击左侧股池选择标的'
          }
        </p>
      </div>
    </div>
  );
}
