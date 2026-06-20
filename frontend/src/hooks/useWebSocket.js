/**
 * useWebSocket.js
 * ---------------
 * 
 *
 * Features:
 *  - Exponential backoff reconnection (1s → 2s → 4s … capped at 30s)
 *  - Dispatches typed events to PipelineContext
 *  - Sends periodic client-side heartbeat pings every 25s
 *  - Cleans up on unmount
 */

import { useEffect, useRef, useCallback } from 'react';
import { ACTIONS } from '../context/PipelineContext';

const WS_URL =
  import.meta.env.VITE_API_URL
    .replace("https://", "wss://")
    .replace("http://", "ws://") + "/ws/live";


const MAX_BACKOFF_MS = 30_000;
const PING_INTERVAL_MS = 25_000;

export function useWebSocket(dispatch) {
  const wsRef            = useRef(null);
  const reconnectRef     = useRef(null);
  const pingRef          = useRef(null);
  const attemptsRef      = useRef(0);
  const unmountedRef     = useRef(false);

  // ── Event dispatcher ────────────────────────────────────────────────────
  const handleEvent = useCallback((raw) => {
    let event;
    try {
      event = JSON.parse(raw);
    } catch {
      return;
    }

    const { type, payload } = event;

    switch (type) {
      case 'violation':
        dispatch({ type: ACTIONS.ADD_VIOLATION, payload });
        break;

      case 'frame_processed':
      case 'metrics':
        dispatch({ type: ACTIONS.UPDATE_METRICS, payload });
        break;

      case 'engine_started':
        dispatch({ type: ACTIONS.SET_ENGINE, payload: true });
        break;

      case 'engine_stopped':
        dispatch({ type: ACTIONS.SET_ENGINE, payload: false });
        break;

      case 'vehicle_tracked':
        // vehicles_tracked count is updated via frame_processed heartbeat events
        break;

      case 'ocr_completed':
        // Handled implicitly via metrics; could surface a toast here
        break;

      default:
        break;
    }
  }, [dispatch]);

  // ── Ping heartbeat ───────────────────────────────────────────────────────
  const startPing = useCallback(() => {
    clearInterval(pingRef.current);
    pingRef.current = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }));
      }
    }, PING_INTERVAL_MS);
  }, []);

  // ── Connect ─────────────────────────────────────────────────────────────
  const connect = useCallback(() => {
    if (unmountedRef.current) return;

    dispatch({ type: ACTIONS.SET_WS_STATUS, payload: 'connecting' });

    let ws;
    try {
      ws = new WebSocket(WS_URL);
    } catch {
      scheduleReconnect();
      return;
    }

    wsRef.current = ws;

    ws.onopen = () => {
      attemptsRef.current = 0;
      dispatch({ type: ACTIONS.SET_WS_STATUS, payload: 'connected' });
      startPing();
    };

    ws.onmessage = (e) => handleEvent(e.data);

    ws.onclose = (e) => {
      clearInterval(pingRef.current);
      if (!unmountedRef.current) {
        dispatch({ type: ACTIONS.SET_WS_STATUS, payload: 'disconnected' });
        scheduleReconnect();
      }
    };

    ws.onerror = () => {
      if (!unmountedRef.current) {
        dispatch({ type: ACTIONS.SET_WS_STATUS, payload: 'error' });
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dispatch, handleEvent, startPing]);

  // ── Reconnect scheduler ─────────────────────────────────────────────────
  function scheduleReconnect() {
    if (unmountedRef.current) return;
    const delay = Math.min(1000 * 2 ** attemptsRef.current, MAX_BACKOFF_MS);
    attemptsRef.current += 1;
    reconnectRef.current = setTimeout(connect, delay);
  }

  // ── Mount / unmount ─────────────────────────────────────────────────────
  useEffect(() => {
    unmountedRef.current = false;
    connect();

    return () => {
      unmountedRef.current = true;
      clearTimeout(reconnectRef.current);
      clearInterval(pingRef.current);
      if (wsRef.current) {
        wsRef.current.onclose = null; // prevent reconnect on intentional close
        wsRef.current.close();
      }
    };
  }, []); // connect is stable — no deps needed
}
