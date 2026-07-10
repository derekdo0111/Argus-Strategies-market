import { useState } from 'react';
import { SECTORS } from './prosperity-data';
import type { Sector } from './prosperity-types';
import styles from './SectorPanel.module.css';

const HEAT: Record<Sector['heat'], { dot: string; label: string }> = {
  hot:  { dot: '#ef3463', label: '🔥' },
  warm: { dot: '#f4a14d', label: '🌤' },
  cool: { dot: 'oklch(65% .03 250)', label: '❄' },
};

export default function SectorPanel() {
  const [activeIdx, setActiveIdx] = useState(0);

  return (
    <aside className={styles.panel}>
      <div className={styles.header}>概念板块</div>

      <div className={styles.list}>
        {SECTORS.map((s, i) => {
          const c = HEAT[s.heat];
          const isActive = i === activeIdx;
          return (
            <div
              key={s.name}
              className={`${styles.item} ${isActive ? styles.active : ''}`}
              onClick={() => setActiveIdx(i)}
            >
              <span className={styles.dot} style={{ backgroundColor: c.dot }} />
              <span className={styles.name}>{s.name}</span>
              <span className={styles.badge}>{s.stockCount}</span>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
