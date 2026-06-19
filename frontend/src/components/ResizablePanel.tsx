import { useState, useCallback, useEffect, useRef, type ReactNode } from 'react';
import styles from './ResizablePanel.module.css';

interface ResizablePanelProps {
  defaultLeftWidth: number;
  minLeftWidth: number;
  maxLeftWidth: number;
  storageKey?: string;
  left: ReactNode;
  right: ReactNode;
  className?: string;
}

export default function ResizablePanel({
  defaultLeftWidth,
  minLeftWidth,
  maxLeftWidth,
  storageKey,
  left,
  right,
  className,
}: ResizablePanelProps) {
  const [leftWidth, setLeftWidth] = useState(() => {
    if (storageKey) {
      const saved = localStorage.getItem(`panel-width-${storageKey}`);
      if (saved) {
        const n = parseInt(saved, 10);
        if (!isNaN(n) && n >= minLeftWidth && n <= maxLeftWidth) return n;
      }
    }
    return defaultLeftWidth;
  });

  const [dragging, setDragging] = useState(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(0);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      setDragging(true);
      startXRef.current = e.clientX;
      startWidthRef.current = leftWidth;
    },
    [leftWidth],
  );

  useEffect(() => {
    if (!dragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      const delta = e.clientX - startXRef.current;
      const next = Math.min(maxLeftWidth, Math.max(minLeftWidth, startWidthRef.current + delta));
      setLeftWidth(next);
    };

    const handleMouseUp = () => {
      setDragging(false);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [dragging, minLeftWidth, maxLeftWidth]);

  // 持久化
  useEffect(() => {
    if (storageKey && leftWidth !== defaultLeftWidth) {
      localStorage.setItem(`panel-width-${storageKey}`, String(leftWidth));
    }
  }, [leftWidth, storageKey, defaultLeftWidth]);

  return (
    <div className={`${styles.container}${className ? ` ${className}` : ''}`}>
      <div className={styles.left} style={{ width: leftWidth }}>
        {left}
      </div>
      <div
        className={`${styles.divider}${dragging ? ` ${styles.dividerActive}` : ''}`}
        onMouseDown={handleMouseDown}
      />
      <div className={styles.right}>{right}</div>
    </div>
  );
}
