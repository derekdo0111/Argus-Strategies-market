import { useState, useCallback } from 'react';
import Sidebar from './Sidebar';
import StockPool from './StockPool';
import ReportViewer from './ReportViewer';
import ResizablePanel from './ResizablePanel';
import styles from './Layout.module.css';

export default function Layout() {
  const [selectedStock, setSelectedStock] = useState<{
    ts_code: string;
    name: string;
  } | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
  const [sidebarHovered, setSidebarHovered] = useState(false);

  const handleSelectStock = useCallback((ts_code: string, name: string) => {
    setSelectedStock((prev) => {
      if (prev?.ts_code === ts_code) return prev;
      return { ts_code, name };
    });
    setSidebarCollapsed(true);   // 选股 → 自动缩进
    setSidebarHovered(false);
  }, []);

  const handleToggleSidebar = useCallback(() => {
    setSidebarCollapsed(prev => !prev);  // 汉堡 → 手动切换
  }, []);

  const effectiveCollapsed = sidebarCollapsed && !sidebarHovered;

  return (
    <div className={styles.layout}>
      {/* Sidebar: 独立可折叠面板，不影响右侧主内容 */}
      <div
        className={`${styles.sidebarPanel} ${effectiveCollapsed ? styles.sidebarCollapsed : ''}`}
        onMouseEnter={() => setSidebarHovered(true)}
        onMouseLeave={() => setSidebarHovered(false)}
      >
        <Sidebar collapsed={effectiveCollapsed} />
      </div>

      {/* 主内容区：始终可见，不受 Sidebar 折叠影响 */}
      <div className={styles.contentArea}>
        <ResizablePanel
          defaultLeftWidth={380}
          minLeftWidth={220}
          maxLeftWidth={720}
          storageKey="layout-stockpool"
          left={
            <StockPool
              selectedStock={selectedStock}
              onSelectStock={handleSelectStock}
              onToggleSidebar={handleToggleSidebar}
            />
          }
          right={
            <ReportViewer selectedStock={selectedStock} />
          }
        />
      </div>
    </div>
  );
}
