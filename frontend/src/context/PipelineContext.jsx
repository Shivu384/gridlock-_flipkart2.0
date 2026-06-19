/**
 * PipelineContext.jsx
 * -------------------
 * Central state management via React Context + useReducer.
 * Provides:
 *   - violations[]      – accumulated violation events (newest first)
 *   - metrics{}         – live stats from WebSocket heartbeats
 *   - wsStatus          – 'connecting' | 'connected' | 'disconnected' | 'error'
 *   - streamStatus      – 'active' | 'error' | 'inactive'
 *   - activeFilter      – null | 'WithoutHelmet' | 'TripleRiding' | 'IllegalParking'
 *   - engineRunning     – boolean
 */

import { createContext, useContext, useReducer, useCallback } from 'react';

// ─── Initial state ────────────────────────────────────────────────────────

const initialState = {
  violations:    [],        // ViolationEvent[]  (newest first, capped at 200)
  metrics: {
    fps:              0,
    total_violations: 0,
    vehicles_tracked: 0,
    ocr_reads:        0,
    frames_processed: 0,
    uptime_seconds:   0,
    is_running:       false,
    detections_count: 0,
  },
  wsStatus:      'connecting',   // connecting | connected | disconnected | error
  streamStatus:  'inactive',     // active | error | inactive
  activeFilter:  null,           // null = All
  engineRunning: false,
};

// ─── Action types ─────────────────────────────────────────────────────────

export const ACTIONS = {
  ADD_VIOLATION:    'ADD_VIOLATION',
  UPDATE_METRICS:   'UPDATE_METRICS',
  SET_WS_STATUS:    'SET_WS_STATUS',
  SET_STREAM_STATUS:'SET_STREAM_STATUS',
  SET_FILTER:       'SET_FILTER',
  SET_ENGINE:       'SET_ENGINE',
  RESET:            'RESET',
};

// ─── Reducer ──────────────────────────────────────────────────────────────

function reducer(state, action) {
  switch (action.type) {

    case ACTIONS.ADD_VIOLATION: {
      const violation = { ...action.payload, _id: crypto.randomUUID() };
      const next = [violation, ...state.violations].slice(0, 200);
      return {
        ...state,
        violations: next,
        metrics: {
          ...state.metrics,
          total_violations: state.metrics.total_violations + 1,
        },
      };
    }

    case ACTIONS.UPDATE_METRICS:
      return {
        ...state,
        metrics: { ...state.metrics, ...action.payload },
      };

    case ACTIONS.SET_WS_STATUS:
      return { ...state, wsStatus: action.payload };

    case ACTIONS.SET_STREAM_STATUS:
      return { ...state, streamStatus: action.payload };

    case ACTIONS.SET_FILTER:
      return { ...state, activeFilter: action.payload };

    case ACTIONS.SET_ENGINE:
      return { ...state, engineRunning: action.payload };

    case ACTIONS.RESET:
      return { ...initialState };

    default:
      return state;
  }
}

// ─── Context ──────────────────────────────────────────────────────────────

const PipelineContext = createContext(null);

export function PipelineProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  /** Filtered violations for the feed panel */
  const filteredViolations = state.activeFilter
    ? state.violations.filter(v => v.violation_type === state.activeFilter)
    : state.violations;

  /** OCR success rate (%) */
  const ocrSuccessRate = state.metrics.vehicles_tracked > 0
    ? Math.min(100, Math.round((state.metrics.ocr_reads / state.metrics.vehicles_tracked) * 100))
    : 0;

  const value = {
    state,
    dispatch,
    filteredViolations,
    ocrSuccessRate,
  };

  return (
    <PipelineContext.Provider value={value}>
      {children}
    </PipelineContext.Provider>
  );
}

// ─── Hook ─────────────────────────────────────────────────────────────────

export function usePipeline() {
  const ctx = useContext(PipelineContext);
  if (!ctx) throw new Error('usePipeline must be used inside <PipelineProvider>');
  return ctx;
}
