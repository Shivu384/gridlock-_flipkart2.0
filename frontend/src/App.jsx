import React, { useState } from 'react';
import { PipelineProvider, usePipeline } from './context/PipelineContext';
import { useWebSocket } from './hooks/useWebSocket';
import Header from './components/Header';
import VideoFeed from './components/VideoFeed';
import MetricsPanel from './components/MetricsPanel';
import ViolationFilters from './components/ViolationFilters';
import ViolationCard from './components/ViolationCard';
import ControlPanel from './components/ControlPanel';
import AnalyticsDashboard from './components/AnalyticsDashboard';
import HeatmapView from './components/HeatmapView';
import UploadPanel from './components/UploadPanel';
import ViolationTable from './components/ViolationTable';

// ─── Tab definitions ────────────────────────────────────────────────────────

const TABS = [
  {
    id: 'monitor',
    label: 'Live Monitor',
    icon: (
      <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
        <path fillRule="evenodd" d="M3 5a2 2 0 012-2h10a2 2 0 012 2v8a2 2 0 01-2 2h-2.22l.123.489.804.804A1 1 0 0113 18H7a1 1 0 01-.707-1.707l.804-.804L7.22 15H5a2 2 0 01-2-2V5zm5.771 7H5V5h10v7H8.771z" clipRule="evenodd" />
      </svg>
    ),
  },
  {
    id: 'analytics',
    label: 'Analytics',
    icon: (
      <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
        <path d="M2 11a1 1 0 011-1h2a1 1 0 011 1v5a1 1 0 01-1 1H3a1 1 0 01-1-1v-5zM8 7a1 1 0 011-1h2a1 1 0 011 1v9a1 1 0 01-1 1H9a1 1 0 01-1-1V7zM14 4a1 1 0 011-1h2a1 1 0 011 1v12a1 1 0 01-1 1h-2a1 1 0 01-1-1V4z" />
      </svg>
    ),
  },
  {
    id: 'analysis',
    label: 'Image Analysis',
    icon: (
      <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
        <path fillRule="evenodd" d="M4 3a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V5a2 2 0 00-2-2H4zm12 12H4l4-8 3 6 2-4 3 6z" clipRule="evenodd" />
      </svg>
    ),
  },
];

// ─── Tab bar ────────────────────────────────────────────────────────────────

function TabBar({ active, onChange }) {
  return (
    <div className="shrink-0 flex items-center gap-1 px-4 py-2 border-b border-slate-800/80 bg-slate-950/60 backdrop-blur-sm relative z-10">
      {TABS.map(tab => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all duration-150 select-none
            ${active === tab.id
              ? 'bg-slate-800 text-slate-100 border border-slate-700 shadow-sm'
              : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800/50 border border-transparent'
            }`}
        >
          {tab.icon}
          {tab.label}
        </button>
      ))}
    </div>
  );
}

// ─── Live Monitor tab ────────────────────────────────────────────────────────

function MonitorTab() {
  const { filteredViolations } = usePipeline();
  return (
    <main className="flex-1 flex flex-col md:flex-row gap-4 p-4 min-h-0 relative z-10">
      {/* Left – video */}
      <section className="flex-1 md:flex-[7] flex flex-col min-h-0">
        <VideoFeed />
      </section>

      {/* Right – controls + metrics + violations */}
      <section className="w-full md:w-[380px] md:flex-[3] flex flex-col gap-3 min-h-0 bg-cmd-surface/40 backdrop-blur-md border border-slate-800/80 rounded-xl p-4 shadow-xl overflow-y-auto scrollbar">
        <ControlPanel />
        <hr className="border-slate-800" />
        <MetricsPanel />
        <hr className="border-slate-800" />
        <ViolationFilters />

        {/* Live incident log */}
        <div className="flex-1 flex flex-col min-h-0">
          <div className="flex items-center gap-2 mb-2 px-1">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
            <h2 className="text-xs font-bold tracking-widest uppercase text-slate-400">Live Incident Log</h2>
          </div>
          <div className="flex-1 overflow-y-auto pr-1 flex flex-col gap-2 min-h-0 scrollbar">
            {filteredViolations.length > 0 ? (
              filteredViolations.map(v => <ViolationCard key={v._id} violation={v} isNew={true} />)
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center gap-3 text-slate-600 py-10 border border-dashed border-slate-800/85 rounded-lg bg-slate-950/20">
                <svg className="w-10 h-10 animate-pulse text-slate-700" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
                <div className="text-center">
                  <p className="text-xs font-bold uppercase tracking-widest text-slate-500">Scanning Horizon…</p>
                  <p className="text-[11px] mt-0.5 text-slate-600">No traffic violations reported</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}

// ─── Analytics tab ───────────────────────────────────────────────────────────

function AnalyticsTab() {
  return (
    <main className="flex-1 flex flex-col lg:flex-row gap-4 p-4 min-h-0 relative z-10">
      <section className="flex-1 lg:flex-[6] min-h-0">
        <AnalyticsDashboard />
      </section>
      <section className="w-full lg:w-[420px] lg:flex-[4] flex flex-col min-h-0 bg-cmd-surface/40 backdrop-blur-md border border-slate-800/80 rounded-xl p-4 shadow-xl">
        <HeatmapView />
      </section>
    </main>
  );
}

// ─── Image Analysis tab ──────────────────────────────────────────────────────

function AnalysisTab() {
  return (
    <main className="flex-1 flex flex-col lg:flex-row gap-4 p-4 min-h-0 relative z-10">
      <section className="w-full lg:w-[480px] lg:flex-[4] flex flex-col min-h-0 bg-cmd-surface/40 backdrop-blur-md border border-slate-800/80 rounded-xl p-4 shadow-xl">
        <UploadPanel />
      </section>
      <section className="flex-1 lg:flex-[6] flex flex-col min-h-0 bg-cmd-surface/40 backdrop-blur-md border border-slate-800/80 rounded-xl p-4 shadow-xl">
        <ViolationTable />
      </section>
    </main>
  );
}

// ─── Root dashboard ──────────────────────────────────────────────────────────

function Dashboard() {
  const { dispatch } = usePipeline();
  const [activeTab, setActiveTab] = useState('monitor');

  useWebSocket(dispatch);

  return (
    <div className="flex flex-col h-full bg-cmd-bg text-slate-300 font-sans antialiased overflow-hidden bg-grid">
      <Header />
      <TabBar active={activeTab} onChange={setActiveTab} />

      {activeTab === 'monitor'   && <MonitorTab />}
      {activeTab === 'analytics' && <AnalyticsTab />}
      {activeTab === 'analysis'  && <AnalysisTab />}
    </div>
  );
}

export default function App() {
  return (
    <PipelineProvider>
      <Dashboard />
    </PipelineProvider>
  );
}
