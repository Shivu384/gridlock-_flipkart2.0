/**
 * VideoFeed.jsx
 * -------------
 * MJPEG stream panel (70% of layout width).
 *
 * Features:
 *  - Serves stream from GET http://localhost:8000/api/stream
 *  - "LIVE" red dot indicator + camera icon overlay
 *  - FPS from WebSocket metrics in bottom overlay
 *  - Stream status indicator (Online / Reconnecting / Offline)
 *  - Error boundary with retry button
 *  - Maintains 16:9 aspect ratio letterboxed in available space
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { usePipeline } from '../context/PipelineContext';
import { ACTIONS } from '../context/PipelineContext';

const API = import.meta.env.VITE_API_URL;
const STREAM_URL = `${API}/api/stream`;

// ─── Status overlay configs ───────────────────────────────────────────────

const STREAM_STATES = {
  active:    { label: 'ONLINE',        colour: 'text-emerald-400', dot: 'bg-emerald-400 animate-pulse-glow-green' },
  error:     { label: 'RECONNECTING',  colour: 'text-amber-400',   dot: 'bg-amber-400 animate-pulse' },
  inactive:  { label: 'OFFLINE',       colour: 'text-slate-500',   dot: 'bg-slate-600' },
};

// ─── Overlay elements ─────────────────────────────────────────────────────

function TopOverlay({ streamStatus, fps }) {
  const ss = STREAM_STATES[streamStatus] || STREAM_STATES.inactive;

  return (
    <div className="absolute top-0 left-0 right-0 z-10 flex items-center justify-between px-4 py-3
                    bg-gradient-to-b from-black/70 to-transparent pointer-events-none">

      {/* Left: LIVE badge */}
      <div className="flex items-center gap-2">
        <span className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-red-600/90 text-white text-xs font-bold font-mono tracking-widest">
          <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
          LIVE
        </span>
        <span className="text-slate-300 text-xs font-mono tracking-wider">FEED-01 · CAM-A</span>
      </div>

      {/* Right: stream status */}
      <div className="flex items-center gap-2">
        <span className={`flex items-center gap-1.5 text-xs font-mono font-semibold ${ss.colour}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${ss.dot}`} />
          {ss.label}
        </span>
      </div>
    </div>
  );
}

function BottomOverlay({ fps, detections }) {
  return (
    <div className="absolute bottom-0 left-0 right-0 z-10 flex items-center justify-between px-4 py-3
                    bg-gradient-to-t from-black/70 to-transparent pointer-events-none">

      {/* Left: FPS counter */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-1.5">
          <svg className="w-3.5 h-3.5 text-blue-400" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd"/>
          </svg>
          <span className="font-mono text-xs text-slate-300">
            <span className="text-blue-400 font-bold">{fps > 0 ? fps.toFixed(1) : '–'}</span>
            <span className="text-slate-500"> FPS</span>
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <svg className="w-3.5 h-3.5 text-slate-500" fill="currentColor" viewBox="0 0 20 20">
            <path d="M10 12a2 2 0 100-4 2 2 0 000 4z"/>
            <path fillRule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clipRule="evenodd"/>
          </svg>
          <span className="font-mono text-xs text-slate-400">
            <span className="text-slate-200 font-semibold">{detections}</span>
            <span className="text-slate-500"> OBJECTS</span>
          </span>
        </div>
      </div>

      {/* Right: resolution tag */}
      <span className="font-mono text-[10px] text-slate-500 tracking-wider border border-slate-700 rounded px-2 py-0.5">
        1280 × 720
      </span>
    </div>
  );
}

// ─── Error / offline state ────────────────────────────────────────────────

function StreamOffline({ onRetry }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-slate-950/95 z-20">
      <div className="relative">
        <svg className="w-16 h-16 text-slate-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1}
            d="M15 10l4.553-2.069A1 1 0 0121 8.82v6.36a1 1 0 01-1.447.894L15 14M3 8a2 2 0 012-2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V8z"/>
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-10 h-0.5 bg-red-500 rotate-45 rounded" />
        </div>
      </div>
      <div className="text-center">
        <p className="text-slate-400 font-semibold">Stream Unavailable</p>
        <p className="text-slate-600 text-sm mt-1">Backend at localhost:8000 is unreachable</p>
      </div>
      <button
        onClick={onRetry}
        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500
                   text-white text-sm font-semibold transition-colors"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
        </svg>
        Reconnect
      </button>
    </div>
  );
}

// ─── VideoFeed ────────────────────────────────────────────────────────────

export default function VideoFeed() {
  const { state, dispatch } = usePipeline();
  const [streamKey, setStreamKey] = useState(0);
  const [hasError, setHasError] = useState(false);
  const retryTimerRef = useRef(null);

  const detectionCount = state.metrics?.detections_count ?? 0;

  const handleLoad = useCallback(() => {
    setHasError(false);
    dispatch({ type: ACTIONS.SET_STREAM_STATUS, payload: 'active' });
  }, [dispatch]);

  const handleError = useCallback(() => {
    setHasError(true);
    dispatch({ type: ACTIONS.SET_STREAM_STATUS, payload: 'error' });
    // Auto-retry after 5 seconds
    clearTimeout(retryTimerRef.current);
    retryTimerRef.current = setTimeout(() => {
      setStreamKey(k => k + 1);
    }, 5000);
  }, [dispatch]);

  const handleRetry = useCallback(() => {
    clearTimeout(retryTimerRef.current);
    setHasError(false);
    setStreamKey(k => k + 1);
  }, []);

  useEffect(() => () => clearTimeout(retryTimerRef.current), []);

  return (
    <div className="relative flex flex-col h-full bg-black rounded-xl overflow-hidden
                    border border-slate-800/80 shadow-2xl shadow-black/50">

      {/* Scanline texture */}
      <div className="scanlines absolute inset-0 z-[1] pointer-events-none" />

      {/* Top overlay */}
      <TopOverlay streamStatus={state.streamStatus} fps={state.metrics.fps} />

      {/* MJPEG img */}
      <div className="flex-1 relative flex items-center justify-center bg-slate-950 min-h-0">
        {!hasError ? (
          <img
            key={streamKey}
            src={`${STREAM_URL}?t=${streamKey}`}
            alt="Live traffic feed"
            className="max-w-full max-h-full w-full h-full object-contain"
            onLoad={handleLoad}
            onError={handleError}
          />
        ) : null}

        {hasError && <StreamOffline onRetry={handleRetry} />}

        {/* Corner HUD brackets */}
        {!hasError && (
          <>
            <span className="absolute top-10 left-3 w-5 h-5 border-t-2 border-l-2 border-blue-500/50 rounded-tl z-10" />
            <span className="absolute top-10 right-3 w-5 h-5 border-t-2 border-r-2 border-blue-500/50 rounded-tr z-10" />
            <span className="absolute bottom-10 left-3 w-5 h-5 border-b-2 border-l-2 border-blue-500/50 rounded-bl z-10" />
            <span className="absolute bottom-10 right-3 w-5 h-5 border-b-2 border-r-2 border-blue-500/50 rounded-br z-10" />
          </>
        )}
      </div>

      {/* Bottom overlay */}
      <BottomOverlay fps={state.metrics.fps} detections={detectionCount} />
    </div>
  );
}
