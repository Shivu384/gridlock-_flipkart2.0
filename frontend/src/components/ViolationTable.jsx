/**
 * ViolationTable.jsx
 * ------------------
 * Full paginated violation table with all metadata and OCR data.
 * Sortable columns, plate-text search, type filter, and CSV export.
 * Pulls from GET /api/violations with pagination.
 */

import { useState, useEffect, useCallback } from 'react';

const API = import.meta.env.VITE_API_URL;
const PAGE_SIZE = 20;

const TYPE_BADGE = {
  WithoutHelmet:  { label: 'NO HELMET',       cls: 'bg-red-500/20 text-red-400 border-red-500/30' },
  TripleRiding:   { label: 'TRIPLE RIDING',    cls: 'bg-orange-500/20 text-orange-400 border-orange-500/30' },
  IllegalParking: { label: 'ILLEGAL PARKING',  cls: 'bg-violet-500/20 text-violet-400 border-violet-500/30' },
};

const COLUMNS = [
  { key: 'violation_type', label: 'Type' },
  { key: 'timestamp',      label: 'Time' },
  { key: 'track_id',       label: 'Track' },
  { key: 'plate_text',     label: 'Plate' },
  { key: 'confidence',     label: 'Conf' },
  { key: 'frame_id',       label: 'Frame' },
];

function exportCsv(rows) {
  const headers = ['violation_type','timestamp','track_id','plate_text','confidence','frame_id','bbox'];
  const lines = [
    headers.join(','),
    ...rows.map(r => [
      r.violation_type,
      r.timestamp,
      r.track_id ?? '',
      r.plate_text ?? '',
      r.confidence.toFixed(4),
      r.frame_id,
      r.bbox ? `${r.bbox.x1}:${r.bbox.y1}:${r.bbox.x2}:${r.bbox.y2}` : '',
    ].join(','))
  ];
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = 'violations.csv'; a.click();
  URL.revokeObjectURL(url);
}

function SortIcon({ active, dir }) {
  if (!active) return <span className="text-slate-700 ml-1">⇅</span>;
  return <span className="text-blue-400 ml-1">{dir === 'asc' ? '↑' : '↓'}</span>;
}

export default function ViolationTable() {
  const [all, setAll]           = useState([]);
  const [loading, setLoading]   = useState(false);
  const [search, setSearch]     = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [sortCol, setSortCol]   = useState('timestamp');
  const [sortDir, setSortDir]   = useState('desc');
  const [page, setPage]         = useState(1);
  const [total, setTotal]       = useState(0);
  const [lastFetch, setLastFetch] = useState(null);

  const fetchViolations = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page_size: 500 });
      if (typeFilter) params.append('violation_type', typeFilter);
      const res = await fetch(`${API}/api/violations?${params}`);
      if (res.ok) {
        const data = await res.json();
        setAll(data.violations);
        setTotal(data.total);
        setLastFetch(new Date());
      }
    } catch {}
    finally { setLoading(false); }
  }, [typeFilter]);

  useEffect(() => { fetchViolations(); }, [fetchViolations]);

  const handleSort = (col) => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortCol(col); setSortDir('asc'); }
    setPage(1);
  };

  // Client-side filter + sort
  let rows = all.filter(r => {
    if (search && !((r.plate_text ?? '').toLowerCase().includes(search.toLowerCase()))) return false;
    return true;
  });
  rows.sort((a, b) => {
    const va = a[sortCol] ?? '';
    const vb = b[sortCol] ?? '';
    const cmp = String(va).localeCompare(String(vb), undefined, { numeric: true });
    return sortDir === 'asc' ? cmp : -cmp;
  });

  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const pageRows  = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 flex-wrap shrink-0">
        <div className="w-1 h-4 bg-amber-500 rounded-full" />
        <h2 className="text-xs font-bold tracking-widest uppercase text-slate-400">OCR & Violation Records</h2>
        <span className="text-[10px] text-slate-500 font-mono">{rows.length} records</span>

        {/* Search */}
        <input
          value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}
          placeholder="Search plate…"
          className="ml-2 text-xs bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-200 placeholder-slate-600 focus:outline-none focus:border-amber-600 font-mono w-36"
        />

        {/* Type filter */}
        <select
          value={typeFilter} onChange={e => { setTypeFilter(e.target.value); setPage(1); }}
          className="text-xs bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-slate-300 focus:outline-none focus:border-amber-600"
        >
          <option value="">All Types</option>
          <option value="WithoutHelmet">No Helmet</option>
          <option value="TripleRiding">Triple Riding</option>
          <option value="IllegalParking">Illegal Parking</option>
        </select>

        <button onClick={fetchViolations} className="text-[10px] font-mono text-slate-500 hover:text-slate-300 border border-slate-700 hover:border-slate-500 px-2 py-1 rounded transition-colors">
          {loading ? 'Loading…' : `Refresh${lastFetch ? ` · ${lastFetch.toLocaleTimeString()}` : ''}`}
        </button>

        <button onClick={() => exportCsv(rows)} className="ml-auto text-[10px] font-mono text-emerald-500 hover:text-emerald-400 border border-emerald-600/40 hover:border-emerald-500 px-3 py-1 rounded transition-colors">
          Export CSV
        </button>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto min-h-0 rounded-xl border border-slate-800 scrollbar">
        <table className="w-full text-xs border-collapse">
          <thead className="sticky top-0 z-10 bg-slate-900 border-b border-slate-800">
            <tr>
              {COLUMNS.map(col => (
                <th
                  key={col.key}
                  onClick={() => handleSort(col.key)}
                  className="text-left px-3 py-2.5 text-[10px] font-bold uppercase tracking-wider text-slate-400 cursor-pointer hover:text-slate-200 select-none whitespace-nowrap"
                >
                  {col.label}<SortIcon active={sortCol === col.key} dir={sortDir} />
                </th>
              ))}
              <th className="text-left px-3 py-2.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">BBox</th>
              <th className="text-left px-3 py-2.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">Meta</th>
            </tr>
          </thead>
          <tbody>
            {pageRows.length === 0 ? (
              <tr><td colSpan={8} className="px-3 py-10 text-center text-slate-600">{loading ? 'Loading…' : 'No records found'}</td></tr>
            ) : pageRows.map((r, i) => {
              const tb = TYPE_BADGE[r.violation_type] ?? { label: r.violation_type, cls: 'bg-slate-700 text-slate-300 border-slate-600' };
              const absTime = r.timestamp ? new Date(r.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '—';
              return (
                <tr key={r.frame_id + '_' + i} className="border-b border-slate-800/80 hover:bg-slate-800/40 transition-colors">
                  <td className="px-3 py-2">
                    <span className={`px-2 py-0.5 rounded text-[9px] font-bold font-mono tracking-wider border ${tb.cls}`}>{tb.label}</span>
                  </td>
                  <td className="px-3 py-2 font-mono text-slate-400 whitespace-nowrap">{absTime}</td>
                  <td className="px-3 py-2 font-mono text-slate-400">{r.track_id != null ? `#${r.track_id}` : '—'}</td>
                  <td className="px-3 py-2">
                    {r.plate_text
                      ? <span className="font-mono text-slate-100 bg-slate-800 border border-slate-700 px-2 py-0.5 rounded tracking-widest">{r.plate_text}</span>
                      : <span className="text-slate-600 italic">—</span>}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1.5">
                      <div className="w-10 h-1 bg-slate-800 rounded-full overflow-hidden">
                        <div className="h-full bg-blue-500 rounded-full" style={{ width: `${Math.round(r.confidence * 100)}%` }} />
                      </div>
                      <span className="font-mono text-slate-400">{Math.round(r.confidence * 100)}%</span>
                    </div>
                  </td>
                  <td className="px-3 py-2 font-mono text-slate-500">{r.frame_id}</td>
                  <td className="px-3 py-2 font-mono text-slate-600 text-[9px] whitespace-nowrap">
                    {r.bbox ? `${r.bbox.x1},${r.bbox.y1} → ${r.bbox.x2},${r.bbox.y2}` : '—'}
                  </td>
                  <td className="px-3 py-2 font-mono text-slate-600 text-[9px]">
                    {r.metadata && Object.keys(r.metadata).length > 0
                      ? Object.entries(r.metadata).filter(([k]) => k !== 'parking_roi').map(([k, v]) => `${k}:${v}`).join(' ')
                      : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center gap-2 shrink-0 px-1">
        <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}
          className="text-[10px] font-mono text-slate-400 hover:text-slate-200 border border-slate-700 hover:border-slate-500 px-2 py-1 rounded disabled:opacity-30 transition-colors">
          ← Prev
        </button>
        <span className="text-[10px] font-mono text-slate-500">Page {page} / {pageCount}</span>
        <button onClick={() => setPage(p => Math.min(pageCount, p + 1))} disabled={page >= pageCount}
          className="text-[10px] font-mono text-slate-400 hover:text-slate-200 border border-slate-700 hover:border-slate-500 px-2 py-1 rounded disabled:opacity-30 transition-colors">
          Next →
        </button>
        <span className="ml-auto text-[10px] text-slate-600 font-mono">{rows.length} total records</span>
      </div>
    </div>
  );
}
