/**
 * AnalyticsDashboard.jsx
 * ----------------------
 * Aggregated analytics pulled from GET /api/analytics.
 * SVG bar chart for violation type breakdown, top plates table,
 * hourly trend sparkline, and summary stat tiles.
 */

import { useState, useEffect, useCallback } from 'react';
import { usePipeline } from '../context/PipelineContext';

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

const TYPE_COLORS = {
  WithoutHelmet: { hex: '#ef4444', label: 'No Helmet' },
  TripleRiding:  { hex: '#f97316', label: 'Triple Riding' },
  IllegalParking:{ hex: '#8b5cf6', label: 'Illegal Parking' },
};

// ─── SVG Bar Chart ────────────────────────────────────────────────────────

function BarChart({ data }) {
  const entries = Object.entries(data);
  if (!entries.length) {
    return <div className="flex items-center justify-center h-28 text-xs text-slate-600">No data yet</div>;
  }
  const max = Math.max(...entries.map(([, v]) => v), 1);
  const BAR_W = 72, GAP = 16, PAD = 12;
  const SVG_W = entries.length * (BAR_W + GAP) + PAD * 2;
  const SVG_H = 110;
  const MAX_BAR = 70;

  return (
    <svg viewBox={`0 0 ${SVG_W} ${SVG_H}`} className="w-full" style={{ height: 110 }}>
      {entries.map(([type, count], i) => {
        const barH = Math.max(4, (count / max) * MAX_BAR);
        const x = PAD + i * (BAR_W + GAP);
        const y = MAX_BAR + 4 - barH;
        const color = TYPE_COLORS[type]?.hex ?? '#64748b';
        const label = TYPE_COLORS[type]?.label ?? type;
        return (
          <g key={type}>
            <rect x={x} y={y} width={BAR_W} height={barH} fill={color} rx={5} fillOpacity={0.85} />
            <text x={x + BAR_W / 2} y={MAX_BAR + 16} textAnchor="middle" fill="#94a3b8" fontSize={9} fontFamily="monospace">
              {label}
            </text>
            <text x={x + BAR_W / 2} y={y - 5} textAnchor="middle" fill="#e2e8f0" fontSize={11} fontWeight="bold" fontFamily="monospace">
              {count}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ─── Hourly Sparkline ─────────────────────────────────────────────────────

function HourlySparkline({ hourly }) {
  const entries = Object.entries(hourly).sort(([a], [b]) => a.localeCompare(b)).slice(-24);
  if (entries.length < 2) {
    return <div className="flex items-center justify-center h-16 text-xs text-slate-600">Not enough data</div>;
  }
  const values = entries.map(([, v]) => v);
  const max = Math.max(...values, 1);
  const W = 400, H = 56, PAD = 4;
  const pts = entries.map(([, v], i) => {
    const x = PAD + (i / (entries.length - 1)) * (W - PAD * 2);
    const y = H - PAD - ((v / max) * (H - PAD * 2));
    return `${x},${y}`;
  }).join(' ');
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 60 }}>
      <polyline points={pts} fill="none" stroke="#3b82f6" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      {entries.map(([, v], i) => {
        const x = PAD + (i / (entries.length - 1)) * (W - PAD * 2);
        const y = H - PAD - ((v / max) * (H - PAD * 2));
        return <circle key={i} cx={x} cy={y} r={3} fill="#3b82f6" />;
      })}
    </svg>
  );
}

// ─── Stat tile ────────────────────────────────────────────────────────────

function StatTile({ label, value, sub, color }) {
  const colors = {
    red:    'border-red-500/30 text-red-400',
    emerald:'border-emerald-500/30 text-emerald-400',
    blue:   'border-blue-500/30 text-blue-400',
    amber:  'border-amber-500/30 text-amber-400',
  };
  return (
    <div className={`rounded-xl border ${colors[color] ?? colors.blue} bg-slate-900/60 p-4`}>
      <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">{label}</p>
      <p className={`text-2xl font-bold font-mono mt-1 ${colors[color]?.split(' ')[1]}`}>{value}</p>
      {sub && <p className="text-[10px] text-slate-600 mt-0.5">{sub}</p>}
    </div>
  );
}

// ─── AnalyticsDashboard ───────────────────────────────────────────────────

export default function AnalyticsDashboard() {
  const { state } = usePipeline();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [lastFetch, setLastFetch] = useState(null);

  const fetchAnalytics = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/analytics`);
      if (res.ok) { setData(await res.json()); setLastFetch(new Date()); }
    } catch {}
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetchAnalytics();
    const id = setInterval(fetchAnalytics, 30_000);
    return () => clearInterval(id);
  }, [fetchAnalytics]);

  // Re-fetch immediately when a new violation arrives (upload or WebSocket)
  useEffect(() => {
    if (state.refreshKey > 0) fetchAnalytics();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.refreshKey]);

  return (
    <div className="flex flex-col gap-5 h-full overflow-y-auto pr-1 scrollbar">
      {/* Header */}
      <div className="flex items-center gap-2 shrink-0">
        <div className="w-1 h-4 bg-blue-500 rounded-full" />
        <h2 className="text-xs font-bold tracking-widest uppercase text-slate-400">Analytics & Reporting</h2>
        <button
          onClick={fetchAnalytics}
          className="ml-auto text-[10px] font-mono text-slate-500 hover:text-slate-300 border border-slate-700 hover:border-slate-500 px-2 py-1 rounded transition-colors"
        >
          {loading ? 'Refreshing…' : `Refresh${lastFetch ? ` · ${lastFetch.toLocaleTimeString()}` : ''}`}
        </button>
      </div>

      {!data ? (
        <div className="flex-1 flex items-center justify-center text-slate-600 text-sm">
          {loading ? 'Loading analytics…' : 'Start the engine to see analytics.'}
        </div>
      ) : (
        <>
          {/* Stat tiles */}
          <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 shrink-0">
            <StatTile label="Total Violations" value={data.total_violations} sub="Since engine start" color="red" />
            <StatTile label="Vehicles Tracked" value={data.total_vehicles} sub="ByteTrack IDs" color="emerald" />
            <StatTile label="Avg FPS" value={data.avg_fps.toFixed(1)} sub="Processing rate" color="blue" />
            <StatTile label="OCR Success" value={`${data.ocr_success_rate}%`} sub={`${data.total_violations} violations total`} color="amber" />
          </div>

          {/* Violation type chart */}
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shrink-0">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-3">Violations by Type</p>
            {Object.keys(data.type_breakdown).length > 0
              ? <BarChart data={data.type_breakdown} />
              : <p className="text-xs text-slate-600 text-center py-4">No violations recorded</p>}
          </div>

          {/* Hourly trend */}
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shrink-0">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-3">Hourly Violation Trend</p>
            <HourlySparkline hourly={data.hourly_violations} />
          </div>

          {/* Two-col: top plates + uptime */}
          <div className="grid grid-cols-2 gap-3 shrink-0">
            {/* Top plates */}
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-3">Top Repeat Plates</p>
              {data.top_plates.length > 0 ? (
                <div className="space-y-1.5">
                  {data.top_plates.slice(0, 8).map((p, i) => (
                    <div key={p.plate} className="flex items-center gap-2">
                      <span className="text-[9px] text-slate-600 font-mono w-4">{i + 1}.</span>
                      <span className="flex-1 font-mono text-xs text-slate-200 tracking-widest bg-slate-800 rounded px-2 py-0.5 border border-slate-700 truncate">{p.plate}</span>
                      <span className="text-[10px] font-mono text-red-400 shrink-0">{p.count}×</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-slate-600">No plates read yet</p>
              )}
            </div>

            {/* Session info */}
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 space-y-3">
              <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">Session Info</p>
              {[
                { label: 'Uptime', value: `${Math.floor(data.uptime_seconds / 60)}m ${Math.floor(data.uptime_seconds % 60)}s` },
                { label: 'Vehicles seen', value: data.total_vehicles },
                { label: 'OCR success rate', value: `${data.ocr_success_rate}%` },
              ].map(({ label, value }) => (
                <div key={label} className="flex justify-between items-center">
                  <span className="text-[10px] text-slate-500">{label}</span>
                  <span className="text-xs font-mono text-slate-300">{value}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
