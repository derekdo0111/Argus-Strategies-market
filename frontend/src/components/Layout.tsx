import { useState, useCallback } from 'react';
import Sidebar from './Sidebar';
import TurtleStockPool from './turtle/StockPool';
import TurtleReportViewer from './turtle/ReportViewer';
import ProsperityHypothesisBoard from './prosperity/HypothesisBoard';
import ProsperityReportViewer from './prosperity/ReportViewer';
import ResizablePanel from './ResizablePanel';
import styles from './Layout.module.css';

// 策略组件映射表 — 加新策略只需在此注册一行
const poolComponents: Record<string, React.ComponentType<any>> = {
  turtle: TurtleStockPool,
  prosperity: ProsperityHypothesisBoard,
};

const reportComponents: Record<string, React.ComponentType<any>> = {
  turtle: TurtleReportViewer,
  prosperity: ProsperityReportViewer,
};

export default function Layout() {
  const [selectedStrategy, setSelectedStrategy] = useState('turtle');
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
    setSidebarCollapsed(true);
    setSidebarHovered(false);
  }, []);

  const handleToggleSidebar = useCallback(() => {
    setSidebarCollapsed(prev => !prev);
  }, []);

  const handleStrategyChange = useCallback((id: string) => {
    setSelectedStrategy(id);
    setSelectedStock(null);  // 切换策略时清除当前选中股票
  }, []);

  const effectiveCollapsed = sidebarCollapsed && !sidebarHovered;

  const PoolComponent = poolComponents[selectedStrategy] || TurtleStockPool;
  const ReportComponent = reportComponents[selectedStrategy] || TurtleReportViewer;

  return (
    <div className={styles.layout}>
      <div
        className={`${styles.sidebarPanel} ${effectiveCollapsed ? styles.sidebarCollapsed : ''}`}
        onMouseEnter={() => setSidebarHovered(true)}
        onMouseLeave={() => setSidebarHovered(false)}
      >
        <Sidebar
          collapsed={effectiveCollapsed}
          selectedStrategy={selectedStrategy}
          onStrategyChange={handleStrategyChange}
        />
      </div>

      <div className={styles.contentArea}>
        <ResizablePanel
          defaultLeftWidth={380}
          minLeftWidth={220}
          maxLeftWidth={720}
          storageKey="layout-stockpool"
          left={
            <PoolComponent
              selectedStock={selectedStock}
              onSelectStock={handleSelectStock}
              onToggleSidebar={handleToggleSidebar}
            />
          }
          right={
            <ReportComponent selectedStock={selectedStock} />
          }
        />
      </div>
    </div>
  );
}
