/**
 * UploadPanel.jsx
 * ---------------
 * Drag-and-drop image upload for on-demand YOLO detection.
 * Sends image to POST /api/upload and displays the annotated result
 * alongside a detection evidence table.
 */

import { useState, useRef, useCallback } from 'react';
import { usePipeline } from '../context/PipelineContext';
import { ACTIONS } from '../context/PipelineContext';

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

const CLASS_COLORS = {
  WithHelmet:    { bg: 'bg-emerald-500/20', text: 'text-emerald-400', border: 'border-emerald-500/40' },
  WithoutHelmet: { bg: 'bg-red-500/20',     text: 'text-red-400',     border: 'border-red-500/40' },
  TripleRiding:  { bg: 'bg-orange-500/20',  text: 'text-orange-400',  border: 'border-orange-500/40' },
  Plate:         { bg: 'bg-yellow-500/20',  text: 'text-yellow-400',  border: 'border-yellow-500/40' },
};

function DetectionBadge({ det }) {
  const c = CLASS_COLORS[det.class_name] || { bg: 'bg-slate-700', text: 'text-slate-300', border: 'border-slate-600' };
  return (
    <div className={`flex items-center justify-between gap-3 px-3 py-2 rounded-lg border ${c.bg} ${c.border}`}>
      <div className="flex items-center gap-2">
        <span className={`text-xs font-bold font-mono ${c.text}`}>{det.class_name}</span>
        {det.plate_text && (
          <span className="text-[10px] font-mono bg-slate-800 text-slate-200 border border-slate-700 px-2 py-0.5 rounded tracking-widest">
            {det.plate_text}
          </span>
        )}
        {det.track_id != null && (
          <span className="text-[10px] text-slate-500 font-mono">#{det.track_id}</span>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <div className="w-16 h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div className="h-full bg-blue-500 rounded-full" style={{ width: `${Math.round(det.confidence * 100)}%` }} />
        </div>
        <span className="text-[10px] font-mono text-slate-400">{Math.round(det.confidence * 100)}%</span>
      </div>
    </div>
  );
}

export default function UploadPanel() {
  const { dispatch } = usePipeline();
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState(null);
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef(null);

  const acceptFile = useCallback((f) => {
    if (!f || !f.type.startsWith('image/')) { setError('Please drop an image file (JPEG or PNG).'); return; }
    setFile(f);
    setResult(null);
    setError('');
    const reader = new FileReader();
    reader.onload = e => setPreview(e.target.result);
    reader.readAsDataURL(f);
  }, []);

  const onDrop = useCallback((e) => {
    e.preventDefault(); setDragging(false);
    acceptFile(e.dataTransfer.files[0]);
  }, [acceptFile]);

  const onDragOver = (e) => { e.preventDefault(); setDragging(true); };
  const onDragLeave = () => setDragging(false);

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true); setError('');
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetch(`${API}/api/upload`, { method: 'POST', body: form });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Upload failed');
      }
      const result = await res.json();
      setResult(result);
      // Signal all dashboard panels to re-fetch their data
      dispatch({ type: ACTIONS.REFRESH_SIGNAL });
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const handleReset = () => { setFile(null); setPreview(null); setResult(null); setError(''); };

  return (
    <div className="flex flex-col gap-4 h-full">
      <div className="flex items-center gap-2">
        <div className="w-1 h-4 bg-violet-500 rounded-full" />
        <h2 className="text-xs font-bold tracking-widest uppercase text-slate-400">Image Evidence Analysis</h2>
        {result && (
          <span className="ml-auto text-[10px] font-mono text-emerald-400">
            {result.detection_count} object{result.detection_count !== 1 ? 's' : ''} detected — {result.width}×{result.height}px
          </span>
        )}
      </div>

      {/* Drop zone */}
      {!preview && (
        <div
          onDrop={onDrop} onDragOver={onDragOver} onDragLeave={onDragLeave}
          onClick={() => inputRef.current?.click()}
          className={`flex-1 flex flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed cursor-pointer transition-all
            ${dragging ? 'border-violet-500 bg-violet-500/10' : 'border-slate-700 bg-slate-900/40 hover:border-slate-600 hover:bg-slate-800/30'}`}
        >
          <input ref={inputRef} type="file" accept="image/*" className="hidden" onChange={e => acceptFile(e.target.files[0])} />
          <div className="w-14 h-14 rounded-2xl bg-slate-800 border border-slate-700 flex items-center justify-center">
            <svg className="w-7 h-7 text-slate-500" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
            </svg>
          </div>
          <div className="text-center">
            <p className="text-sm font-semibold text-slate-400">Drop an image here</p>
            <p className="text-xs text-slate-600 mt-1">or click to browse · JPEG / PNG</p>
          </div>
        </div>
      )}

      {/* Preview + result side by side */}
      {preview && (
        <div className="flex flex-col gap-3 flex-1 min-h-0">
          <div className="grid grid-cols-2 gap-3">
            {/* Original */}
            <div className="space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 px-1">Original</p>
              <img src={preview} alt="original" className="w-full rounded-lg border border-slate-700 object-cover max-h-52" />
            </div>
            {/* Annotated */}
            <div className="space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 px-1">
                {result ? 'Annotated Result' : 'Awaiting analysis…'}
              </p>
              {result ? (
                <img
                  src={`data:image/jpeg;base64,${result.annotated_image_b64}`}
                  alt="annotated"
                  className="w-full rounded-lg border border-violet-500/40 object-cover max-h-52"
                />
              ) : (
                <div className="w-full max-h-52 rounded-lg border border-slate-800 bg-slate-900/60 flex items-center justify-center aspect-video">
                  {loading
                    ? <span className="text-xs text-slate-500 animate-pulse">Running detection…</span>
                    : <span className="text-xs text-slate-600">Click Analyse to run</span>}
                </div>
              )}
            </div>
          </div>

          {/* Detection cards */}
          {result && result.detections.length > 0 && (
            <div className="flex-1 overflow-y-auto space-y-1.5 min-h-0 pr-1 scrollbar">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 px-1">Detections</p>
              {result.detections.map((det, i) => <DetectionBadge key={i} det={det} />)}
            </div>
          )}
          {result && result.detections.length === 0 && (
            <p className="text-xs text-slate-500 text-center py-4">No detections above threshold</p>
          )}

          {error && <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">{error}</p>}

          <div className="flex gap-2">
            <button
              onClick={handleUpload}
              disabled={loading}
              className="flex-1 py-2 rounded-lg text-xs font-bold uppercase tracking-wider bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-50 transition-colors"
            >
              {loading ? 'Analysing…' : 'Analyse Image'}
            </button>
            <button
              onClick={handleReset}
              className="px-4 py-2 rounded-lg text-xs font-semibold text-slate-400 border border-slate-700 hover:border-slate-500 hover:text-slate-200 transition-colors"
            >
              Clear
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
