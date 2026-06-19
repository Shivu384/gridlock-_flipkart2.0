/**
 * MetricsPanel.jsx
 * ----------------
 * 2×2 grid of animated metric tiles showing:
 *  1. Active Vehicles  (emerald)
 *  2. Total Violations (red)
 *  3. Average FPS      (blue)
 *  4. OCR Success Rate (amber)
 */

import { useEffect, useRef, useState } from 'react';
import { usePipeline } from '../context/PipelineContext';

// ─── Animated number ─────────────────────────────────────────────────────

function AnimatedNumber({ value, suffix = '' }) {
  const [display, setDisplay] = useState(value);
  const prevRef = useRef(value);
  const [flash, setFlash] = useState(false);

  useEffect(() => {
    if (value !== prevRef.current) {
      prevRef.current = value;
      setFlash(true);
      const id = setTimeout(() => setFlash(false), 400);
      return () => clearTimeout(id);
    }
  }, [value]);

  useEffect(() => { setDisplay(value); }, [value]);

  return (
    <span className={`font-mono font-bold transition-all ${flash ? 'animate-count text-blue-400' : ''}`}>
      {display}{suffix}
    </span>
  );
}

// ─── Metric tile ─────────────────────────────────────────────────────────

function MetricTile({ icon, label, value, suffix, colour, subLabel, trend }) {
  const colours = {
    emerald: { border: 'border-emerald-500/30', glow: 'bg-emerald-500/10', text: 'text-emerald-400', icon: 'text-emerald-500', bar: 'bg-emerald-500' },
    red:     { border: 'border-red-500/30',     glow: 'bg-red-500/10',     text: 'text-red-400',     icon: 'text-red-500',     bar: 'bg-red-500' },
    blue:    { border: 'border-blue-500/30',    glow: 'bg-blue-500/10',    text: 'text-blue-400',    icon: 'text-blue-500',    bar: 'bg-blue-500' },
    amber:   { border: 'border-amber-500/30',   glow: 'bg-amber-500/10',   text: 'text-amber-400',   icon: 'text-amber-500',   bar: 'bg-amber-500' },
  };
  const c = colours[colour] ?? colours.blue;

  return (
    <div className={`relative rounded-xl border ${c.border} bg-slate-900/60 p-4 overflow-hidden`}>
      {/* Background glow */}
      <div className={`absolute top-0 right-0 w-16 h-16 rounded-full ${c.glow} blur-2xl -translate-y-4 translate-x-4`} />

      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <span className={`text-xs font-semibold tracking-widest uppercase text-slate-500`}>{label}</span>
        <span className={`${c.icon} p-1.5 rounded-lg ${c.glow}`}>{icon}</span>
      </div>

      {/* Value */}
      <div className={`text-3xl font-bold font-mono ${c.text}`}>
        <AnimatedNumber value={value} suffix={suffix} />
      </div>

      {/* Sub-label */}
      {subLabel && (
        <div className="mt-1 text-[11px] text-slate-600 font-medium">{subLabel}</div>
      )}

      {/* Trend bar (if 0-100) */}
      {trend !== undefined && (
        <div className="mt-3 h-1 bg-slate-800 rounded-full overflow-hidden">
          <div
            className={`h-full ${c.bar} rounded-full transition-all duration-700`}
            style={{ width: `${Math.min(100, trend)}%` }}
          />
        </div>
      )}
    </div>
  );
}

// ─── Icons ────────────────────────────────────────────────────────────────

const IconVehicle = () => (
  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
    <path d="M8 16.5a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0zM15 16.5a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0z"/>
    <path d="M3 4a1 1 0 00-1 1v10a1 1 0 001 1h1.05a2.5 2.5 0 014.9 0H10a1 1 0 001-1V5a1 1 0 00-1-1H3zM14 7h-1V5a1 1 0 00-1-1H9v2h3v3.5a1 1 0 001 1h2a1 1 0 001-1V9l-1.5-2H14z"/>
  </svg>
);

const IconAlert = () => (
  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
    <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd"/>
  </svg>
);

const IconFPS = () => (
  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd"/>
  </svg>
);

const IconOCR = () => (
  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
    <path fillRule="evenodd" d="M3 4a1 1 0 011-1h3a1 1 0 011 1v3a1 1 0 01-1 1H4a1 1 0 01-1-1V4zm2 2V5h1v1H5zM3 13a1 1 0 011-1h3a1 1 0 011 1v3a1 1 0 01-1 1H4a1 1 0 01-1-1v-3zm2 2v-1h1v1H5zM13 3a1 1 0 00-1 1v3a1 1 0 001 1h3a1 1 0 001-1V4a1 1 0 00-1-1h-3zm1 2v1h1V5h-1z" clipRule="evenodd"/>
    <path d="M11 4a1 1 0 10-2 0v1a1 1 0 002 0V4zM10 7a1 1 0 011 1v1h2a1 1 0 110 2h-3a1 1 0 01-1-1V8a1 1 0 011-1zM16 9a1 1 0 100 2 1 1 0 000-2zM9 13a1 1 0 011-1h1a1 1 0 110 2v2a1 1 0 11-2 0v-3zM7 11a1 1 0 100-2H4a1 1 0 100 2h3zM17 13a1 1 0 01-1 1h-2a1 1 0 110-2h2a1 1 0 011 1zM16 17a1 1 0 100-2h-3a1 1 0 100 2h3z"/>
  </svg>
);

// ─── MetricsPanel ─────────────────────────────────────────────────────────

export default function MetricsPanel() {
  const { state, ocrSuccessRate } = usePipeline();
  const m = state.metrics;

  return (
    <div className="shrink-0">
      <div className="flex items-center gap-2 mb-3 px-1">
        <div className="w-1 h-4 bg-blue-500 rounded-full" />
        <h2 className="text-xs font-bold tracking-widest uppercase text-slate-400">
          System Metrics
        </h2>
        {m.is_running && (
          <span className="ml-auto text-[10px] font-mono text-emerald-500">
            {m.uptime_seconds > 0 ? `${Math.floor(m.uptime_seconds)}s uptime` : 'Starting…'}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <MetricTile
          icon={<IconVehicle />}
          label="Active Vehicles"
          value={m.vehicles_tracked}
          colour="emerald"
          subLabel="ByteTrack IDs"
        />
        <MetricTile
          icon={<IconAlert />}
          label="Total Violations"
          value={m.total_violations}
          colour="red"
          subLabel="Since start"
        />
        <MetricTile
          icon={<IconFPS />}
          label="Avg FPS"
          value={m.fps > 0 ? m.fps.toFixed(1) : '0.0'}
          colour="blue"
          subLabel="Processing rate"
          trend={(m.fps / 30) * 100}
        />
        <MetricTile
          icon={<IconOCR />}
          label="OCR Rate"
          value={ocrSuccessRate}
          suffix="%"
          colour="amber"
          subLabel={`${m.ocr_reads} plates read`}
          trend={ocrSuccessRate}
        />
      </div>
    </div>
  );
}
