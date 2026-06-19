/**
 * ViolationFilters.jsx
 * --------------------
 * Filter buttons for the violation feed.
 * Selecting a filter hides non-matching violation cards.
 */

import { usePipeline, ACTIONS } from '../context/PipelineContext';

const FILTERS = [
  {
    key:    null,
    label:  'All',
    icon:   '◈',
    active: 'bg-slate-600 text-slate-100 border-slate-500',
    hover:  'hover:bg-slate-700',
  },
  {
    key:    'WithoutHelmet',
    label:  'No Helmet',
    icon:   '⛑',
    active: 'bg-red-500/20 text-red-400 border-red-500/50',
    hover:  'hover:bg-red-500/10',
  },
  {
    key:    'TripleRiding',
    label:  'Triple',
    icon:   '🏍',
    active: 'bg-amber-500/20 text-amber-400 border-amber-500/50',
    hover:  'hover:bg-amber-500/10',
  },
  {
    key:    'IllegalParking',
    label:  'Parking',
    icon:   '🅿',
    active: 'bg-violet-500/20 text-violet-400 border-violet-500/50',
    hover:  'hover:bg-violet-500/10',
  },
];

export default function ViolationFilters() {
  const { state, dispatch, filteredViolations } = usePipeline();

  const handleFilter = (key) => {
    dispatch({ type: ACTIONS.SET_FILTER, payload: key });
  };

  return (
    <div className="shrink-0">
      <div className="flex items-center gap-2 mb-2 px-1">
        <div className="w-1 h-4 bg-violet-500 rounded-full" />
        <h2 className="text-xs font-bold tracking-widest uppercase text-slate-400">
          Filter
        </h2>
        <span className="ml-auto font-mono text-[10px] text-slate-600">
          {filteredViolations.length} shown
        </span>
      </div>

      <div className="flex gap-1.5 flex-wrap">
        {FILTERS.map(f => {
          const isActive = state.activeFilter === f.key;
          // Count for this filter
          const count = f.key === null
            ? state.violations.length
            : state.violations.filter(v => v.violation_type === f.key).length;

          return (
            <button
              key={String(f.key)}
              onClick={() => handleFilter(f.key)}
              className={`
                flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                border transition-all duration-150 select-none
                ${isActive
                  ? `${f.active} shadow-sm`
                  : `border-slate-700 text-slate-500 bg-slate-900/50 ${f.hover} hover:text-slate-300 hover:border-slate-600`
                }
              `}
            >
              <span className="leading-none">{f.icon}</span>
              <span>{f.label}</span>
              {count > 0 && (
                <span className={`
                  ml-0.5 px-1.5 py-0.5 rounded-full font-mono text-[9px] font-bold
                  ${isActive ? 'bg-white/20' : 'bg-slate-800 text-slate-500'}
                `}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
