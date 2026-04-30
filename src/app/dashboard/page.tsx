"use client";
import { useEffect, useState, useMemo } from 'react';
import dynamic from 'next/dynamic';
import MetricsChart from './MetricsChart';
import RegimeChart from './RegimeChart';
import { TrendingUp, TrendingDown, BarChart3, Zap, Layers, Trophy, Info, ChevronDown, ChevronRight } from "lucide-react";
import { useTradingStore, type Position, type DailySummary } from '@/store/useTradingStore';
import { getTrainingMetrics } from '@/app/actions/getTrainingMetrics';

const Plot = dynamic(() => {
  if (typeof window !== 'undefined') {
    const d = Object.getOwnPropertyDescriptor(window, 'fetch');
    if (d && !d.set) {
      Object.defineProperty(window, 'fetch', {
        ...d,
        set: function() {}
      });
    }
  }
  return import('react-plotly.js');
}, { ssr: false });
const OrganismCanvas = dynamic(() => import('@/components/3d/OrganismCanvas'), { ssr: false });

// ── Static FTMO challenge metadata ─────────────────────────────────────────
const FTMO_META = {
  result:       'Ongoing',
  status:       'Active',
  type:         '2-Step',
  accountId:    '531260945',
  startDate:    '13 Apr 2026',
  endDate:      'Unlimited',
  accountSize:  70_000,
  accountType:  'Swing',
  platform:     'MT5',
  maxDailyLoss: 3_500,
  maxTotalLoss: 7_000,
  profitTarget: 7_000,
};

type MetricsData = {
  pass_rate:        number;
  daily_breach:     number;
  total_breach:     number;
  avg_pnl_pct:      number;
  avg_trades:       number;
  avg_days:         number;
  sharpe:           number;
  step:             number;
  pass_rate_pct?:   number;
  daily_breach_pct?: number;
  total_breach_pct?: number;
};

function formatDuration(openTime?: string): string {
  if (!openTime) return '—';
  const diff = Date.now() - new Date(openTime).getTime();
  const d = Math.floor(diff / 86_400_000);
  const h = Math.floor((diff % 86_400_000) / 3_600_000);
  const m = Math.floor((diff % 3_600_000) / 60_000);
  const s = Math.floor((diff % 60_000) / 1_000);
  return `${d}d ${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

function formatOpenTime(openTime?: string): string {
  if (!openTime) return '—';
  return new Date(openTime).toLocaleString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

export default function Dashboard() {
  const [metrics, setMetrics]           = useState<MetricsData | null>(null);
  const [history, setHistory]           = useState<MetricsData[]>([]);
  const [showObjectives, setObjectives] = useState(false);
  const [trainingOpen, setTrainingOpen] = useState(false);

  const primary       = useTradingStore(s => s.accounts['531260945']);
  const equity        = useTradingStore(s => s.equity);
  const equityHistory = useTradingStore(s => s.equityHistory);
  const drawdown      = useTradingStore(s => s.drawdown);

  const accountStats = useMemo(() => primary?.accountStats ?? {}, [primary?.accountStats]);
  const positions    = useMemo(() => primary?.positions    ?? [], [primary?.positions]);

  const _SYM: Record<string, string> = { GBP: '£', USD: '$', EUR: '€', JPY: '¥' };
  const cur = accountStats.currency ? (_SYM[accountStats.currency] ?? accountStats.currency) : '£';
  
  const fmt = (n?: number) => n != null
    ? n.toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : '--';
    
  const fmtSigned = (n?: number) => n == null ? '--'
    : `${n >= 0 ? '+' : ''}${cur}${fmt(Math.abs(n))}`;

  const balance       = primary?.balance ?? accountStats.balance ?? FTMO_META.accountSize;
  const unrealizedPnl = useMemo(() => positions.reduce((s, p) => s + (p.profit ?? 0), 0), [positions]);

  const pnlColor = (n: number) => n >= 0 ? 'text-emerald-400' : 'text-red-400';

  // ── Plotly chart data ─────────────────────────────────────────────────────
  const plotData = useMemo(() => {
    const equityValues = equityHistory.map(h => h.equity);
    const timestamps = equityHistory.map(h => h.timestamp);

    const minEq = equityValues.reduce((a, b) => Math.min(a, b), equityValues[0] ?? equity);
    const maxEq = equityValues.reduce((a, b) => Math.max(a, b), equityValues[0] ?? equity);
    const pad   = Math.max(200, (maxEq - minEq) * 0.15); 
    const bottom = minEq - pad;

    const traces: object[] = [
      {
        x: timestamps,
        y: equityValues.map(() => bottom),
        type: 'scatter', mode: 'lines',
        line: { width: 0, color: 'transparent' },
        hoverinfo: 'skip',
        showlegend: false,
      },
      {
        x: timestamps,
        y: equityValues,
        name: 'Equity', type: 'scatter', mode: 'lines',
        line: { color: '#22d3ee', width: 2, shape: 'spline' },
        fill: 'tonexty', fillcolor: 'rgba(34,211,238,0.04)', hoverinfo: 'y+name',
      },
      {
        x: timestamps,
        y: equityValues.map(() => balance),
        name: 'Balance', type: 'scatter', mode: 'lines',
        line: { color: 'rgba(255,255,255,0.35)', width: 1, dash: 'dot' }, hoverinfo: 'y+name',
      },
    ];
    if (showObjectives) {
      traces.push(
        { x: timestamps, y: equityValues.map(() => FTMO_META.accountSize), name: 'Account size', type: 'scatter', mode: 'lines', line: { color: 'rgba(148,163,184,0.5)', width: 1, dash: 'dashdot' }, hoverinfo: 'none' },
        { x: timestamps, y: equityValues.map(() => FTMO_META.accountSize - FTMO_META.maxTotalLoss), name: 'Max loss', type: 'scatter', mode: 'lines', line: { color: 'rgba(239,68,68,0.5)', width: 1, dash: 'dashdot' }, hoverinfo: 'none' },
        { x: timestamps, y: equityValues.map(() => FTMO_META.accountSize + FTMO_META.profitTarget), name: 'Profit target', type: 'scatter', mode: 'lines', line: { color: 'rgba(52,211,153,0.5)', width: 1, dash: 'dashdot' }, hoverinfo: 'none' },
      );
    }
    return traces;
  }, [equityHistory, balance, showObjectives, equity]);

  const plotLayout = useMemo(() => {
    return {
      autosize: true, margin: { l: 60, r: 10, t: 5, b: 30 },
      paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
      font: { color: '#64748b', size: 11 },
      legend: { orientation: 'h' as const, x: 0, y: 1.08, font: { color: '#94a3b8', size: 10 } },
      xaxis: { showgrid: false, zeroline: false, showticklabels: false },
      yaxis: {
        showgrid: true, gridcolor: 'rgba(255,255,255,0.04)', zeroline: false,
        tickprefix: cur, autorange: true,
      },
      hovermode: 'x unified' as const, dragmode: false as const, showlegend: true,
      uirevision: 'equity-chart',
    };
  }, [cur]);

  // ── Training WS ───────────────────────────────────────────────────────────
  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:8001';
    const wsUrl = base.replace(/^http/, 'ws') + '/ws/metrics';
    let ws: WebSocket | null = null;
    let mockInterval: ReturnType<typeof setInterval> | null = null;
    let destroyed = false;
    
    function connect() {
      if (destroyed) return;
      ws = new WebSocket(wsUrl);
      ws.onopen = () => { console.log("WS connected"); };
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          const nd = {
            ...data,
            pass_rate_pct:    data.pass_rate_pct    ?? (data.pass_rate    ? data.pass_rate    * 100 : 0),
            daily_breach_pct: data.daily_breach_pct ?? (data.daily_breach ? data.daily_breach * 100 : 0),
            total_breach_pct: data.total_breach_pct ?? (data.total_breach ? data.total_breach * 100 : 0),
            avg_pnl_pct:      data.avg_pnl_pct      ?? (data.avg_pnl      ? data.avg_pnl      * 100 : 0),
          };
          setMetrics(nd);
          setHistory(prev => { const n = [...prev, nd]; return n.length > 100 ? n.slice(n.length - 100) : n; });
        } catch {}
      };
      
      // Fallback for simulation if backend is offline
      ws.onclose = () => {
        ws = null;
        console.warn("WS closed, starting local file polling fallback...");
        // Start polling local log files via Server Action
        
        async function fetchLogs() {
          if (destroyed) return;
          try {
            const rawLogs = await getTrainingMetrics();
            if (rawLogs && rawLogs.length > 0) {
              const nd = {
                ...rawLogs[rawLogs.length - 1],
                pass_rate_pct:    rawLogs[rawLogs.length - 1].pass_rate_pct    ?? (rawLogs[rawLogs.length - 1].pass_rate    ? rawLogs[rawLogs.length - 1].pass_rate    * 100 : 0),
                daily_breach_pct: rawLogs[rawLogs.length - 1].daily_breach_pct ?? (rawLogs[rawLogs.length - 1].daily_breach ? rawLogs[rawLogs.length - 1].daily_breach * 100 : 0),
                total_breach_pct: rawLogs[rawLogs.length - 1].total_breach_pct ?? (rawLogs[rawLogs.length - 1].total_breach ? rawLogs[rawLogs.length - 1].total_breach * 100 : 0),
                avg_pnl_pct:      rawLogs[rawLogs.length - 1].avg_pnl_pct      ?? (rawLogs[rawLogs.length - 1].avg_pnl      ? rawLogs[rawLogs.length - 1].avg_pnl      * 100 : 0),
              };
              setMetrics(nd);
              
              const historyData = rawLogs.slice(-100).map((log: Partial<MetricsData>) => ({
                ...log,
                pass_rate_pct:    log.pass_rate_pct    ?? (log.pass_rate    ? log.pass_rate    * 100 : 0),
                daily_breach_pct: log.daily_breach_pct ?? (log.daily_breach ? log.daily_breach * 100 : 0),
                total_breach_pct: log.total_breach_pct ?? (log.total_breach ? log.total_breach * 100 : 0),
                avg_pnl_pct:      log.avg_pnl_pct      ?? (log.avg_pnl_pct  ? log.avg_pnl_pct  * 100 : 0),
              })) as MetricsData[];
              setHistory(historyData);
            }
          } catch (e) {
            console.error("Failed to fetch local stats:", e);
          }
        }
        
        void fetchLogs(); // Fetch immediately once
        mockInterval = setInterval(fetchLogs, 5000); // And then every 5 seconds

        if (!destroyed) { 
           // Disable retry loop so we stay in file-polling mode
        }
      };
      ws.onerror = () => ws?.close();
    }
    connect();
    return () => { 
      destroyed = true; 
      if (mockInterval) clearInterval(mockInterval); 
      ws?.close(); 
    };
  }, []);

  return (
    <div className="space-y-6">

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-black text-white mb-1">Live Deployment</h1>
          <p className="text-slate-500 text-sm">
            Alpha Account · {FTMO_META.accountId} · {cur}{FTMO_META.accountSize.toLocaleString('en-GB')} account size
          </p>
        </div>
        <div className={`px-4 py-2 rounded-full text-xs font-bold tracking-widest uppercase border ${
          primary?.isSimulated ? 'bg-purple-500/10 border-purple-500/20 text-purple-400'
          : primary?.isLive   ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
                               : 'bg-slate-500/10 border-slate-500/20 text-slate-400'
        }`}>
          <span className="inline-block w-2 h-2 rounded-full bg-current mr-2 animate-pulse" />
          {primary?.isSimulated ? 'Simulation' : primary?.isLive ? 'Live' : 'Offline'}
        </div>
      </header>

      {/* ── MAIN GRID: Hardcoded Flexbox Bypass ────────────────────────────── */}
      <div style={{ display: 'flex', width: '100%', gap: '24px', alignItems: 'flex-start' }} className="flex-col md:flex-row">

        {/* ── LEFT COLUMN (Forced to 66% width) ────────────────────────────── */}
        <div style={{ flex: '2 1 0%', minWidth: 0 }} className="flex flex-col gap-6 w-full">

          {/* Current Results + FTMO Challenge */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            
            {/* Current Results */}
            <div className="lg:col-span-2 glass-panel p-6 space-y-5">
              <h2 className="text-xs font-bold text-slate-500 uppercase tracking-widest">Current Results</h2>

              <div className="grid grid-cols-3 gap-4">
                {[
                  { label: 'Balance',        value: `${cur}${fmt(balance)}`,   color: 'text-white' },
                  { label: 'Equity',         value: `${cur}${fmt(equity)}`,    color: 'text-cyan-400' },
                  { label: 'Unrealized PnL', value: fmtSigned(unrealizedPnl),  color: pnlColor(unrealizedPnl) },
                ].map(k => (
                  <div key={k.label} className="bg-white/[0.03] border border-white/5 rounded-xl p-4">
                    <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-2">{k.label}</p>
                    <p className={`text-xl font-black ${k.color}`}>{k.value}</p>
                  </div>
                ))}
              </div>

              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-500">Trading Objective Lines</span>
                <button onClick={() => setObjectives(v => !v)} className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${showObjectives ? 'bg-cyan-500' : 'bg-slate-700'}`}>
                  <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${showObjectives ? 'translate-x-4' : 'translate-x-1'}`} />
                </button>
                <span className="text-[10px] text-slate-600">
                  Daily −{cur}{FTMO_META.maxDailyLoss.toLocaleString()} · Total −{cur}{FTMO_META.maxTotalLoss.toLocaleString()} · Target +{cur}{FTMO_META.profitTarget.toLocaleString()}
                </span>
              </div>

              <div className="h-[220px]">
                <Plot
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  data={plotData as any[]}
                  layout={plotLayout}
                  revision={equityHistory.length}
                  useResizeHandler
                  style={{ width: '100%', height: '100%' }}
                  config={{ displayModeBar: false }}
                />
              </div>

              <div className="flex items-center gap-4 text-xs text-slate-500 pt-1">
                <span>Peak DD: <span className={`font-bold ${drawdown > 5 ? 'text-red-400' : drawdown > 2 ? 'text-amber-400' : 'text-emerald-400'}`}>{drawdown.toFixed(2)}%</span></span>
                <span className="ml-auto">Net P&L: <span className={`font-bold ${(accountStats.net_pnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {accountStats.net_pnl != null ? `${fmtSigned(accountStats.net_pnl)} (${(accountStats.net_pnl_pct ?? 0).toFixed(2)}%)` : '--'}
                </span></span>
              </div>
            </div>

            {/* FTMO Challenge info */}
            <div className="glass-panel p-6 flex flex-col gap-4">
              <h2 className="text-xs font-bold text-slate-500 uppercase tracking-widest flex items-center gap-2">
                <Info className="w-3.5 h-3.5" /> FTMO Challenge
              </h2>
              <div className="flex-1 space-y-3">
                {[
                  { label: 'Result',       value: FTMO_META.result,   badge: true },
                  { label: 'Status',       value: FTMO_META.status },
                  { label: '2-Step',       value: FTMO_META.accountId },
                  { label: 'Start',        value: FTMO_META.startDate },
                  { label: 'End',          value: FTMO_META.endDate },
                  { label: 'Account size', value: `${cur}${FTMO_META.accountSize.toLocaleString('en-GB', { minimumFractionDigits: 2 })}` },
                  { label: 'Account type', value: FTMO_META.accountType },
                  { label: 'Platform',     value: FTMO_META.platform },
                ].map(row => (
                  <div key={row.label} className="flex items-center justify-between border-b border-white/[0.04] pb-3 last:border-0 last:pb-0">
                    <span className="text-xs text-slate-500">{row.label}</span>
                    {row.badge
                      ? <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-cyan-500/15 text-cyan-400 border border-cyan-500/20">{row.value}</span>
                      : <span className="text-xs font-bold text-white">{row.value}</span>}
                  </div>
                ))}
              </div>
              <div className="space-y-3 pt-1">
                {[
                  { label: 'Daily loss used',  used: Math.max(0, balance - equity),                       max: FTMO_META.maxDailyLoss,  color: 'bg-amber-400' },
                  { label: 'Total loss used',  used: Math.max(0, FTMO_META.accountSize - equity),         max: FTMO_META.maxTotalLoss,  color: 'bg-red-400' },
                  { label: 'Profit progress',  used: Math.max(0, equity - FTMO_META.accountSize),         max: FTMO_META.profitTarget,  color: 'bg-emerald-400' },
                ].map(b => (
                  <div key={b.label}>
                    <div className="flex justify-between text-[10px] text-slate-500 mb-1">
                      <span>{b.label}</span>
                      <span>{cur}{fmt(b.used)} / {cur}{b.max.toLocaleString()}</span>
                    </div>
                    <div className="h-1 bg-white/5 rounded-full overflow-hidden">
                      <div className={`h-full ${b.color} rounded-full transition-all`} style={{ width: `${Math.min(b.used / b.max * 100, 100)}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Open Trades */}
          <div className="glass-panel p-6">
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-3">
                <Layers className="w-4 h-4 text-cyan-400" />
                <h2 className="text-sm font-bold text-white">Open Trades</h2>
                {positions.length > 0 && (
                  <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">{positions.length}</span>
                )}
              </div>
              {positions.length > 0 && (
                <span className={`text-sm font-black ${unrealizedPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{fmtSigned(unrealizedPnl)}</span>
              )}
            </div>
            {positions.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-10 text-slate-600">
                <Layers className="w-8 h-8 mb-3 opacity-30" />
                <p className="text-sm">No open positions</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-[10px] text-slate-500 uppercase tracking-widest border-b border-white/5">
                      <th className="text-left pb-3 font-semibold">Type</th>
                      <th className="text-left pb-3 font-semibold">Open Time</th>
                      <th className="text-right pb-3 font-semibold">Volume</th>
                      <th className="text-left pb-3 pl-4 font-semibold">Symbol</th>
                      <th className="text-right pb-3 font-semibold">PnL</th>
                      <th className="text-right pb-3 font-semibold">Pips</th>
                      <th className="text-right pb-3 font-semibold">Duration</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.03]">
                    {positions.map((pos: Position, i: number) => (
                      <tr key={pos.id ?? `${pos.symbol}-${i}`} className="hover:bg-white/[0.02] transition-colors">
                        <td className="py-3">
                          <div className="flex items-center gap-1.5">
                            {pos.id && <span className="text-[10px] text-slate-600">{pos.id}</span>}
                            <span className={`flex items-center gap-1 text-xs font-bold ${pos.type === 'BUY' ? 'text-emerald-400' : 'text-red-400'}`}>
                              {pos.type === 'BUY' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                              {pos.type}
                            </span>
                          </div>
                        </td>
                        <td className="py-3 text-slate-400 text-xs">{formatOpenTime(pos.openTime)}</td>
                        <td className="py-3 text-right text-slate-300 font-mono">{pos.volume}</td>
                        <td className="py-3 pl-4 font-bold text-white">{pos.symbol}</td>
                        <td className={`py-3 text-right font-bold ${pos.profit >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {pos.profit >= 0 ? '+' : ''}{cur}{pos.profit.toFixed(2)}
                        </td>
                        <td className={`py-3 text-right font-mono text-xs ${(pos.pips ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {pos.pips != null ? pos.pips.toFixed(1) : '—'}
                        </td>
                        <td className="py-3 text-right text-slate-400 text-xs font-mono">{formatDuration(pos.openTime)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Daily Summary */}
          <div className="glass-panel p-6">
            <h2 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-4 flex items-center gap-2">
              <Trophy className="w-3.5 h-3.5" /> Daily Summary
            </h2>
            {(accountStats.daily_summary ?? []).length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-slate-600">
                <BarChart3 className="w-8 h-8 mb-3 opacity-30" />
                <p className="text-sm">No daily data yet</p>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[10px] text-slate-500 uppercase tracking-widest border-b border-white/5">
                    <th className="text-left pb-3 font-semibold">Date</th>
                    <th className="text-right pb-3 font-semibold">Trades</th>
                    <th className="text-right pb-3 font-semibold">Lots</th>
                    <th className="text-right pb-3 font-semibold">Result</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.03]">
                  {(accountStats.daily_summary as DailySummary[]).map((row, i) => (
                    <tr key={i} className="hover:bg-white/[0.02] transition-colors">
                      <td className="py-3 font-bold text-cyan-400">{row.date}</td>
                      <td className="py-3 text-right text-slate-300">{row.trades}</td>
                      <td className="py-3 text-right text-slate-300">{row.lots}</td>
                      <td className={`py-3 text-right font-bold ${row.result >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {row.result >= 0 ? '+' : '−'}{cur}{fmt(Math.abs(row.result))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Training Metrics (collapsible) */}
          <div className="glass-panel overflow-hidden">
            <button onClick={() => setTrainingOpen(v => !v)} className="w-full flex items-center justify-between p-6 hover:bg-white/[0.02] transition-colors">
              <div className="flex items-center gap-3">
                <Zap className="w-5 h-5 text-cyan-400" />
                <span className="text-base font-bold text-white">Training Simulation Metrics</span>
                {metrics && <span className="text-xs text-slate-500 font-normal">{(metrics.step / 1_000_000).toFixed(2)}M steps · Pass {(metrics.pass_rate_pct ?? metrics.pass_rate * 100).toFixed(1)}%</span>}
              </div>
              {trainingOpen ? <ChevronDown className="w-4 h-4 text-slate-500" /> : <ChevronRight className="w-4 h-4 text-slate-500" />}
            </button>
            {trainingOpen && (
              <div className="px-6 pb-6 space-y-6 border-t border-white/5">
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 pt-6">
                  <div className="lg:col-span-2">
                    <p className="text-xs text-slate-500 mb-4">From RL training logs — updates when training is running</p>
                    <div className="h-[280px]"><MetricsChart history={history} /></div>
                  </div>
                  <div className="flex flex-col items-center justify-center text-center">
                    <Zap className="w-10 h-10 text-cyan-400 mb-4" />
                    <div className="text-4xl font-black text-cyan-400 mb-2 tracking-tighter">
                      {metrics ? `${(metrics.step / 1_000_000).toFixed(2)}M` : '--'}
                    </div>
                    <p className="text-slate-500 text-xs mb-5">Total Training Steps</p>
                    <div className="grid grid-cols-2 gap-3 w-full text-left">
                      {[
                        { label: 'Pass Rate',    value: metrics ? `${(metrics.pass_rate_pct ?? metrics.pass_rate * 100).toFixed(1)}%` : '--', color: 'text-emerald-400' },
                        { label: 'Daily Breach', value: metrics ? `${(metrics.daily_breach_pct ?? metrics.daily_breach * 100).toFixed(1)}%` : '--', color: 'text-amber-400' },
                        { label: 'Avg PnL',      value: metrics ? `${(metrics.avg_pnl_pct ?? 0).toFixed(2)}%` : '--', color: (metrics?.avg_pnl_pct ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400' },
                        { label: 'Sharpe',       value: metrics ? metrics.sharpe.toFixed(2) : '--', color: 'text-purple-400' },
                      ].map(m => (
                        <div key={m.label} className="glass-panel p-3">
                          <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">{m.label}</p>
                          <p className={`text-sm font-black ${m.color}`}>{m.value}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
                <div>
                  <h3 className="text-base font-bold text-white mb-5">Market Regime Distribution</h3>
                  <div className="h-[280px]"><RegimeChart /></div>
                </div>
              </div>
            )}
          </div>

        </div>

        {/* ── RIGHT COLUMN (Forced to 33% width) ───────────────────────────── */}
        <div style={{ flex: '1 1 0%', minWidth: 0 }} className="flex flex-col gap-6 w-full">

          {/* Organism canvas */}
          <div
            id="organism-container"
            className="w-full flex-grow min-h-[600px] border border-white/10 rounded-xl glass-panel flex flex-col
                       items-center justify-center bg-[radial-gradient(ellipse_at_center,rgba(34,211,238,0.04)_0%,transparent_70%)] relative overflow-hidden"
          >
            <div className="absolute inset-0 w-full h-full">
              <OrganismCanvas />
            </div>
            
            {/* Optional overlay text if you want to keep the label, but usually the 3D scene speaks for itself */}
            <div className="absolute bottom-4 left-0 right-0 text-center pointer-events-none z-10">
              <p className="text-[10px] font-bold tracking-widest uppercase text-cyan-500/40">
                WEBGL ORGANISM
              </p>
            </div>
          </div>

          {/* Live organism signal strip */}
          <div className="glass-panel p-4 grid grid-cols-2 gap-3">
            {[
              {
                label: 'Volatility',
                value: (primary?.volatility ?? 1).toFixed(3),
                color: 'text-amber-400',
              },
              {
                label: 'Action',
                value: primary?.lastAction ?? 'FLAT',
                color: primary?.lastAction === 'LONG'  ? 'text-emerald-400'
                     : primary?.lastAction === 'SHORT' ? 'text-red-400'
                     : 'text-slate-400',
              },
              {
                label: 'Open P&L',
                value: fmtSigned(unrealizedPnl),
                color: pnlColor(unrealizedPnl),
              },
              {
                label: 'Drawdown',
                value: `${drawdown.toFixed(3)}%`,
                color: drawdown > 5 ? 'text-red-400' : drawdown > 2 ? 'text-amber-400' : 'text-emerald-400',
              },
            ].map(s => (
              <div key={s.label} className="bg-white/[0.03] border border-white/5 rounded-xl p-3">
                <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">{s.label}</p>
                <p className={`text-sm font-black font-mono ${s.color}`}>{s.value}</p>
              </div>
            ))}
          </div>

        </div>

      </div>
    </div>
  );
}