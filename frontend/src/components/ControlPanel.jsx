/**
 * ControlPanel.jsx
 * ----------------
 * Pipeline start / stop controls, video source input, and
 * live confidence-threshold slider that patches the backend in real-time.
 */

import { useState, useRef } from 'react';
import { usePipeline } from '../context/PipelineContext';

const API = 'http://localhost:8000';

const PRESETS = [
  { label: 'Webcam 0', value: '0' },
  { label: 'Webcam 1', value: '1' },
];

export default function ControlPanel() {
  const { state } = usePipeline();
  const [source, setSource] = useState('0');
  const [confidence, setConfidence] = useState(0.40);
  const [frameSkip, setFrameSkip] = useState(3);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [cfgMsg, setCfgMsg] = useState('');
  const debounceRef = useRef(null);

  const handleStart = async () => {
    setLoading(true); setError('');
    try {
      const res = await fetch(`${API}/api/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_path: source.trim(), frame_skip: frameSkip }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Failed to start');
      }
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const handleStop = async () => {
    setLoading(true); setError('');
    try {
      const res = await fetch(`${API}/api/stop`, { method: 'POST' });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Failed to stop');
      }
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const patchConfig = (payload) => {
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      try {
        await fetch(`${API}/api/config`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        setCfgMsg('Saved');
        setTimeout(() => setCfgMsg(''), 1500);
      } catch {}
    }, 400);
  };

  const handleConfidence = (e) => {
    const val = parseFloat(e.target.value);
    setConfidence(val);
    patchConfig({ confidence_threshold: val });
  };

  const handleFrameSkip = (e) => {
    const val = parseInt(e.target.value, 10);
    setFrameSkip(val);
    patchConfig({ frame_skip: val });
  };

  const running = state.engineRunning;

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 space-y-4">
      <div className="flex items-center gap-2">
        <div className="w-1 h-4 bg-cyan-500 rounded-full" />
        <h2 className="text-xs font-bold tracking-widest uppercase text-slate-400">Pipeline Control</h2>
        {cfgMsg && <span className="ml-auto text-[10px] text-emerald-400 font-mono">{cfgMsg}</span>}
      </div>

      {/* Source input */}
      <div className="space-y-1.5">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Video Source</label>
        <div className="flex gap-1.5">
          <input
            value={source}
            onChange={e => setSource(e.target.value)}
            placeholder="0  or  /path/video.mp4  or  rtsp://..."
            disabled={running}
            className="flex-1 text-xs bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-600 disabled:opacity-50 font-mono"
          />
        </div>
        <div className="flex gap-1">
          {PRESETS.map(p => (
            <button
              key={p.value}
              onClick={() => setSource(p.value)}
              disabled={running}
              className="text-[10px] px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-600 disabled:opacity-40 transition-colors"
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Frame skip */}
      <div className="space-y-1.5">
        <div className="flex justify-between">
          <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Frame Skip</label>
          <span className="text-[10px] font-mono text-slate-400">{frameSkip}x</span>
        </div>
        <input
          type="range" min={1} max={10} step={1}
          value={frameSkip}
          onChange={handleFrameSkip}
          className="w-full accent-cyan-500 cursor-pointer"
        />
        <div className="flex justify-between text-[9px] text-slate-600">
          <span>1 (max fps)</span><span>10 (low cpu)</span>
        </div>
      </div>

      {/* Confidence threshold */}
      <div className="space-y-1.5">
        <div className="flex justify-between">
          <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Confidence Threshold</label>
          <span className="text-[10px] font-mono text-blue-400">{(confidence * 100).toFixed(0)}%</span>
        </div>
        <input
          type="range" min={0.10} max={0.95} step={0.05}
          value={confidence}
          onChange={handleConfidence}
          className="w-full accent-blue-500 cursor-pointer"
        />
        <div className="flex justify-between text-[9px] text-slate-600">
          <span>10% (sensitive)</span><span>95% (strict)</span>
        </div>
      </div>

      {/* Start / Stop */}
      <div className="flex gap-2 pt-1">
        <button
          onClick={handleStart}
          disabled={running || loading}
          className="flex-1 py-2 rounded-lg text-xs font-bold uppercase tracking-wider bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-lg shadow-emerald-900/30"
        >
          {loading && !running ? 'Starting…' : 'Start Engine'}
        </button>
        <button
          onClick={handleStop}
          disabled={!running || loading}
          className="flex-1 py-2 rounded-lg text-xs font-bold uppercase tracking-wider bg-red-600/80 hover:bg-red-600 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-lg shadow-red-900/30"
        >
          {loading && running ? 'Stopping…' : 'Stop Engine'}
        </button>
      </div>

      {error && (
        <p className="text-[11px] text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 font-mono">
          {error}
        </p>
      )}
    </div>
  );
}
