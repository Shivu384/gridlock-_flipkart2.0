/**
 * Header.jsx
 * ----------
 * Top command-bar with branding, live clock, and connection status badges.
 */

import { useState, useEffect } from 'react';
import { usePipeline } from '../context/PipelineContext';

// ─── WS status pill ───────────────────────────────────────────────────────

const WS_STATUS = {
  connected:    { label: 'WS LIVE',         bg: 'bg-emerald-500/20', text: 'text-emerald-400', dot: 'bg-emerald-400 animate-pulse-glow-green' },
  connecting:   { label: 'CONNECTING…',     bg: 'bg-amber-500/20',   text: 'text-amber-400',   dot: 'bg-amber-400 animate-pulse' },
  disconnected: { label: 'WS OFFLINE',      bg: 'bg-red-500/20',     text: 'text-red-400',     dot: 'bg-red-400' },
  error:        { label: 'WS ERROR',        bg: 'bg-red-500/20',     text: 'text-red-400',     dot: 'bg-red-500 animate-pulse' },
};

function StatusPill({ status, label, dotCls, bg, text }) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold font-mono ${bg} ${text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${dotCls}`} />
      {label}
    </span>
  );
}

// ─── Live clock ───────────────────────────────────────────────────────────

function LiveClock() {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const hh = String(time.getHours()).padStart(2, '0');
  const mm = String(time.getMinutes()).padStart(2, '0');
  const ss = String(time.getSeconds()).padStart(2, '0');
  const date = time.toLocaleDateString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
  });

  return (
    <div className="text-center">
      <div className="font-mono text-slate-100 text-lg font-bold tracking-widest leading-none">
        {hh}:{mm}:{ss}
      </div>
      <div className="text-slate-500 text-xs font-mono mt-0.5 tracking-wide">{date}</div>
    </div>
  );
}

// ─── Header ───────────────────────────────────────────────────────────────

export default function Header() {
  const { state } = usePipeline();
  const wsInfo = WS_STATUS[state.wsStatus] || WS_STATUS.disconnected;

  return (
    <header className="relative z-20 flex items-center justify-between px-6 py-3 border-b border-slate-800 bg-cmd-surface/80 backdrop-blur-sm shrink-0">

      {/* ── Left: Branding ── */}
      <div className="flex items-center gap-3">
        {/* Shield icon */}
        <div className="relative w-9 h-9 flex items-center justify-center">
          <svg viewBox="0 0 24 24" className="w-9 h-9 text-blue-500" fill="currentColor">
            <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z"/>
          </svg>
          <svg viewBox="0 0 24 24" className="absolute w-4 h-4 text-slate-900" fill="currentColor">
            <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/>
          </svg>
        </div>

        <div>
          <div className="flex items-center gap-2">
            <span className="text-slate-100 font-black text-xl tracking-widest uppercase">
              Gridlock
            </span>
            <span className="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 text-[10px] font-bold font-mono tracking-wider border border-blue-500/30">
              AI
            </span>
          </div>
          <div className="text-slate-500 text-[11px] font-medium tracking-widest uppercase">
            Traffic Enforcement Command Center
          </div>
        </div>
      </div>

      {/* ── Center: Clock ── */}
      <LiveClock />

      {/* ── Right: Status badges ── */}
      <div className="flex items-center gap-3">
        {/* Engine status */}
        <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold font-mono
          ${state.engineRunning
            ? 'bg-blue-500/20 text-blue-400'
            : 'bg-slate-700/50 text-slate-500'
          }`}>
          <span className={`w-1.5 h-1.5 rounded-full ${state.engineRunning ? 'bg-blue-400 animate-pulse' : 'bg-slate-600'}`} />
          {state.engineRunning ? 'ENGINE ACTIVE' : 'ENGINE IDLE'}
        </span>

        {/* WebSocket status */}
        <StatusPill
          label={wsInfo.label}
          bg={wsInfo.bg}
          text={wsInfo.text}
          dotCls={wsInfo.dot}
        />
      </div>
    </header>
  );
}
