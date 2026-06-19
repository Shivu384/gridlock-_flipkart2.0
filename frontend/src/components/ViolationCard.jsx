/**
 * ViolationCard.jsx
 * -----------------
 * Individual violation event card with color-coded type, timestamp,
 * plate, and track ID. Slides in from the top on mount.
 */

import { useState, useEffect } from 'react';

// ─── Type config ──────────────────────────────────────────────────────────

const TYPE_CONFIG = {
  WithoutHelmet: {
    label:      'NO HELMET',
    border:     'border-l-red-500',
    badge:      'bg-red-500/20 text-red-400 border-red-500/30',
    icon:       '⛑',
    glow:       'shadow-red-900/30',
    iconBg:     'bg-red-500/10',
  },
  TripleRiding: {
    label:      'TRIPLE RIDING',
    border:     'border-l-amber-500',
    badge:      'bg-amber-500/20 text-amber-400 border-amber-500/30',
    icon:       '🏍',
    glow:       'shadow-amber-900/30',
    iconBg:     'bg-amber-500/10',
  },
  IllegalParking: {
    label:      'ILLEGAL PARKING',
    border:     'border-l-violet-500',
    badge:      'bg-violet-500/20 text-violet-400 border-violet-500/30',
    icon:       '🅿',
    glow:       'shadow-violet-900/30',
    iconBg:     'bg-violet-500/10',
  },
};

const UNKNOWN_TYPE = {
  label:  'VIOLATION',
  border: 'border-l-slate-500',
  badge:  'bg-slate-700 text-slate-300 border-slate-600',
  icon:   '⚠',
  glow:   'shadow-slate-900/30',
  iconBg: 'bg-slate-700',
};

// ─── Relative timestamp ───────────────────────────────────────────────────

function useRelativeTime(isoTimestamp) {
  const [label, setLabel] = useState('Just now');

  useEffect(() => {
    const ts = new Date(isoTimestamp);

    function update() {
      const diffMs = Date.now() - ts.getTime();
      const s = Math.floor(diffMs / 1000);
      if (s < 5)        setLabel('Just now');
      else if (s < 60)  setLabel(`${s}s ago`);
      else if (s < 3600) setLabel(`${Math.floor(s / 60)}m ago`);
      else              setLabel(`${Math.floor(s / 3600)}h ago`);
    }

    update();
    const id = setInterval(update, 5000);
    return () => clearInterval(id);
  }, [isoTimestamp]);

  return label;
}

// ─── ViolationCard ────────────────────────────────────────────────────────

export default function ViolationCard({ violation, isNew }) {
  const cfg = TYPE_CONFIG[violation.violation_type] ?? UNKNOWN_TYPE;
  const relTime = useRelativeTime(violation.timestamp);

  const absTime = new Date(violation.timestamp).toLocaleTimeString('en-IN', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  });

  return (
    <div
      className={`
        relative flex items-stretch gap-0
        bg-slate-900/80 rounded-lg overflow-hidden
        border border-slate-800 border-l-4 ${cfg.border}
        shadow-lg ${cfg.glow}
        ${isNew ? 'animate-slide-in' : ''}
        transition-colors duration-200 hover:bg-slate-800/80
        group
      `}
    >
      {/* Icon */}
      <div className={`flex items-center justify-center w-12 shrink-0 ${cfg.iconBg}`}>
        <span className="text-lg leading-none select-none">{cfg.icon}</span>
      </div>

      {/* Content */}
      <div className="flex-1 p-3 min-w-0">
        {/* Row 1: Type badge + time */}
        <div className="flex items-center justify-between gap-2 mb-2">
          <span className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono tracking-wider border ${cfg.badge}`}>
            {cfg.label}
          </span>
          <span className="text-slate-600 text-[10px] font-mono" title={absTime}>
            {relTime}
          </span>
        </div>

        {/* Row 2: Plate + Track ID */}
        <div className="flex items-center justify-between gap-2">
          {/* Plate */}
          <div className="flex items-center gap-1.5 min-w-0">
            {violation.plate_text ? (
              <div className="flex items-center gap-1 bg-slate-800 rounded px-2 py-1 border border-slate-700">
                <svg className="w-3 h-3 text-slate-500 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M4 4a2 2 0 00-2 2v8a2 2 0 002 2h12a2 2 0 002-2V8a2 2 0 00-2-2h-5L9 4H4zm7 5a1 1 0 10-2 0v1H8a1 1 0 100 2h1v1a1 1 0 102 0v-1h1a1 1 0 100-2h-1V9z" clipRule="evenodd"/>
                </svg>
                <span className="font-mono text-xs font-bold text-slate-100 tracking-widest truncate">
                  {violation.plate_text}
                </span>
              </div>
            ) : (
              <span className="font-mono text-xs text-slate-600 italic">No plate</span>
            )}
          </div>

          {/* Track ID */}
          {violation.track_id != null && (
            <span className="shrink-0 font-mono text-[10px] text-slate-500 bg-slate-800/80 px-1.5 py-0.5 rounded border border-slate-700/50">
              #{violation.track_id}
            </span>
          )}
        </div>

        {/* Row 3: confidence + frame */}
        <div className="flex items-center gap-3 mt-1.5">
          <div className="flex items-center gap-1">
            <div className="w-12 h-1 bg-slate-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all"
                style={{ width: `${Math.round(violation.confidence * 100)}%` }}
              />
            </div>
            <span className="font-mono text-[10px] text-slate-600">
              {Math.round(violation.confidence * 100)}%
            </span>
          </div>
          <span className="font-mono text-[10px] text-slate-700">
            f/{violation.frame_id}
          </span>
          <span className="font-mono text-[10px] text-slate-700 ml-auto">{absTime}</span>
        </div>
      </div>
    </div>
  );
}
