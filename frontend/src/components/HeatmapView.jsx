/**
 * HeatmapView.jsx
 * ---------------
 * Canvas-based violation heatmap.  Fetches bbox-centre points from
 * GET /api/heatmap and renders each as a coloured radial gradient blob.
 * Colours are coded by violation type.
 */

import { useEffect, useRef, useState, useCallback } from 'react';

const API = 'http://localhost:8000';

const TYPE_COLORS = {
  WithoutHelmet:  [239, 68,  68],
  TripleRiding:   [249, 115, 22],
  IllegalParking: [139, 92,  246],
};

const LEGEND = [
  { key: 'WithoutHelmet',  label: 'No Helmet',      color: 'bg-red-500' },
  { key: 'TripleRiding',   label: 'Triple Riding',   color: 'bg-orange-500' },
  { key: 'IllegalParking', label: 'Illegal Parking', color: 'bg-violet-500' },
];

const REF_W = 1280;
const REF_H = 720;
const BLOB_R = 36;

function drawHeatmap(canvas, points) {
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.width;
  const H = canvas.height;

  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(0, 0, W, H);

  // Grid overlay
  ctx.strokeStyle = 'rgba(51,65,85,0.4)';
  ctx.lineWidth = 1;
  const COLS = 16, ROWS = 9;
  for (let c = 0; c <= COLS; c++) {
    ctx.beginPath(); ctx.moveTo((c / COLS) * W, 0); ctx.lineTo((c / COLS) * W, H); ctx.stroke();
  }
  for (let r = 0; r <= ROWS; r++) {
    ctx.beginPath(); ctx.moveTo(0, (r / ROWS) * H); ctx.lineTo(W, (r / ROWS) * H); ctx.stroke();
  }

  if (!points.length) {
    ctx.fillStyle = 'rgba(100,116,139,0.5)';
    ctx.font = '14px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('No violation data', W / 2, H / 2);
    return;
  }

  // Draw blobs
  points.forEach(pt => {
    const x = (pt.x / REF_W) * W;
    const y = (pt.y / REF_H) * H;
    const rgb = TYPE_COLORS[pt.violation_type] ?? [100, 116, 139];

    const g = ctx.createRadialGradient(x, y, 0, x, y, BLOB_R);
    g.addColorStop(0,   `rgba(${rgb.join(',')}, 0.75)`);
    g.addColorStop(0.5, `rgba(${rgb.join(',')}, 0.35)`);
    g.addColorStop(1,   `rgba(${rgb.join(',')}, 0)`);

    ctx.beginPath();
    ctx.arc(x, y, BLOB_R, 0, Math.PI * 2);
    ctx.fillStyle = g;
    ctx.fill();
  });

  // Hot-spot circles for dense clusters (draw solid core)
  points.forEach(pt => {
    const x = (pt.x / REF_W) * W;
    const y = (pt.y / REF_H) * H;
    const rgb = TYPE_COLORS[pt.violation_type] ?? [100, 116, 139];
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(${rgb.join(',')}, 0.9)`;
    ctx.fill();
  });
}

export default function HeatmapView() {
  const canvasRef = useRef(null);
  const [points, setPoints] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [lastFetch, setLastFetch] = useState(null);

  const fetchHeatmap = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/heatmap`);
      if (res.ok) {
        const data = await res.json();
        setPoints(data.points);
        setTotal(data.total);
        setLastFetch(new Date());
      }
    } catch {}
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetchHeatmap();
    const id = setInterval(fetchHeatmap, 15_000);
    return () => clearInterval(id);
  }, [fetchHeatmap]);

  useEffect(() => {
    drawHeatmap(canvasRef.current, points);
  }, [points]);

  // Redraw on resize
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ro = new ResizeObserver(() => {
      canvas.width  = canvas.offsetWidth;
      canvas.height = canvas.offsetHeight;
      drawHeatmap(canvas, points);
    });
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [points]);

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* Header */}
      <div className="flex items-center gap-2 shrink-0">
        <div className="w-1 h-4 bg-orange-500 rounded-full" />
        <h2 className="text-xs font-bold tracking-widest uppercase text-slate-400">Violation Heatmap</h2>
        <span className="ml-2 text-[10px] font-mono text-slate-500">{total} points</span>
        <button
          onClick={fetchHeatmap}
          className="ml-auto text-[10px] font-mono text-slate-500 hover:text-slate-300 border border-slate-700 hover:border-slate-500 px-2 py-1 rounded transition-colors"
        >
          {loading ? 'Refreshing…' : `Refresh${lastFetch ? ` · ${lastFetch.toLocaleTimeString()}` : ''}`}
        </button>
      </div>

      {/* Canvas */}
      <div className="flex-1 rounded-xl border border-slate-800 overflow-hidden relative min-h-0">
        <canvas
          ref={canvasRef}
          className="w-full h-full block"
          style={{ display: 'block' }}
        />
        {total === 0 && !loading && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-600 pointer-events-none gap-2">
            <svg className="w-8 h-8 text-slate-700" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 6.75V15m6-6v8.25m.503 3.498l4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 00-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 2.497z" />
            </svg>
            <p className="text-xs">Run the engine to populate the heatmap</p>
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 shrink-0 px-1">
        {LEGEND.map(l => (
          <div key={l.key} className="flex items-center gap-1.5">
            <span className={`w-2.5 h-2.5 rounded-full ${l.color}`} />
            <span className="text-[10px] text-slate-500">{l.label}</span>
          </div>
        ))}
        <span className="ml-auto text-[10px] text-slate-600 font-mono">ref: {REF_W}×{REF_H}px</span>
      </div>
    </div>
  );
}
