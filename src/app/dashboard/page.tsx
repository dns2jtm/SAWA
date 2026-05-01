"use client";
import { useEffect, useState, useMemo } from 'react';
import { Activity, BarChart, ChevronLeft, ChevronRight, Info, Wifi, WifiOff } from 'lucide-react';
import MetricsChart from './MetricsChart';
import { useTradingStore } from '@/store/useTradingStore';

import { getTrainingMetrics } from '@/app/actions/getTrainingMetrics';

export default function DashboardOverview() {
  const { isConnected, connect } = useTradingStore();
  const [trainingMetrics, setTrainingMetrics] = useState<any[]>([]);
  const [showNerdStats, setShowNerdStats] = useState(true);
  const [activePhase, setActivePhase] = useState(1);

  useEffect(() => {
    connect();
    
    const fetchMetrics = async () => {
      const data = await getTrainingMetrics();
      setTrainingMetrics(data);
    };
    
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 5000);
    return () => clearInterval(interval);
  }, [connect]);

  // Derive max phase from available data
  const maxPhase = useMemo(() => {
    let max = 1;
    for (const m of trainingMetrics) {
      if (m.step > 7000000) max = Math.max(max, 3);
      else if (m.step > 3000000) max = Math.max(max, 2);
    }
    return max;
  }, [trainingMetrics]);

  // Filter metrics by active phase segment
  const phaseMetrics = useMemo(() => {
    return trainingMetrics.filter(m => {
      if (activePhase === 1) return m.step <= 3000000;
      if (activePhase === 2) return m.step > 3000000 && m.step <= 7000000;
      return m.step > 7000000;
    });
  }, [trainingMetrics, activePhase]);

  const latestMetrics = trainingMetrics.length > 0 ? trainingMetrics[trainingMetrics.length - 1] : null;
  const latestPhaseMetrics = phaseMetrics.length > 0 ? phaseMetrics[phaseMetrics.length - 1] : null;

  return (
    <div className="space-y-8 max-w-[1400px] mx-auto animate-in fade-in duration-500 pb-12">
      <header className="flex items-center justify-between pb-4 border-b border-white/5">
        <div>
          <h1 className="text-3xl font-black text-white mb-1 tracking-tight">Training Pipeline</h1>
          <p className="text-slate-500 text-sm">Real-time deep reinforcement learning metrics for the FTMO agent.</p>
        </div>
        <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider border transition-colors ${
          isConnected ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-slate-500/10 text-slate-400 border-slate-500/20'
        }`}>
          {isConnected ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
          {isConnected ? 'API Connected' : 'Connecting...'}
        </div>
      </header>

      <div className="flex flex-col gap-8">
        
        {/* Main Training Progress Block */}
        <div className="glass-panel p-6 min-h-[500px] flex flex-col relative overflow-hidden shadow-2xl">
          
          <div className="flex justify-between items-center mb-6">
            <h3 className="text-xl font-bold text-white flex items-center gap-2">
              <BarChart className="w-6 h-6 text-emerald-400" />
              Training Progress (Phase {activePhase})
            </h3>
            
            <div className="flex items-center gap-4">
              <div className="flex bg-black/40 rounded-lg p-1 border border-white/5">
                <button 
                  disabled={activePhase === 1}
                  onClick={() => setActivePhase(Math.max(1, activePhase - 1))}
                  className="p-1.5 text-slate-500 hover:text-white disabled:opacity-30 transition-colors"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <div className="px-4 py-1.5 rounded-md text-sm font-bold bg-emerald-500/20 text-emerald-400 min-w-[100px] text-center">
                  Phase {activePhase}
                </div>
                <button 
                  disabled={activePhase >= maxPhase}
                  onClick={() => setActivePhase(Math.min(maxPhase, activePhase + 1))}
                  className="p-1.5 text-slate-500 hover:text-white disabled:opacity-30 transition-colors"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
              <a href="/dashboard/docs" className="text-sm text-blue-400 hover:text-blue-300 underline underline-offset-4 opacity-80 hover:opacity-100 transition-opacity">Read Documentation</a>
            </div>
          </div>
          
          <div className="flex-1 w-full flex flex-col justify-center">
            {phaseMetrics.length > 0 ? (
              <div className="flex flex-col h-full space-y-8">
                
                {/* The Charts (Split into Stacked Subplots) */}
                <div className="flex-1 flex flex-col gap-6">
                  {/* Primary PnL & Pass Rate Chart */}
                  <div className="w-full h-[300px] bg-black/20 rounded-xl border border-white/5 pt-2">
                     <MetricsChart history={phaseMetrics} />
                  </div>
                </div>

                {/* Primary FTMO Metrics Row */}
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-4 text-sm pt-2">
                  <div className="flex flex-col items-center bg-black/20 p-4 rounded-xl border border-white/5 group relative">
                    <span className="text-slate-400 font-semibold mb-2 text-xs uppercase tracking-wider flex items-center gap-1.5">
                      Latest Step 
                      <a href="/dashboard/docs#latest-step" className="text-slate-600 hover:text-blue-400 cursor-pointer transition-colors opacity-0 group-hover:opacity-100 absolute top-2 right-2"><Info className="w-3.5 h-3.5" /></a>
                    </span>
                    <span className="font-mono text-white font-black text-2xl">{latestPhaseMetrics?.step?.toLocaleString() ?? '---'}</span>
                  </div>
                  <div className="flex flex-col items-center bg-black/20 p-4 rounded-xl border border-white/5 group relative">
                    <span className="text-slate-400 font-semibold mb-2 text-xs uppercase tracking-wider flex items-center gap-1.5">
                      Pass Rate 
                      <a href="/dashboard/docs#pass-rate" className="text-slate-600 hover:text-blue-400 cursor-pointer transition-colors opacity-0 group-hover:opacity-100 absolute top-2 right-2"><Info className="w-3.5 h-3.5" /></a>
                    </span>
                    <span className="font-mono text-emerald-400 font-black text-2xl">{latestPhaseMetrics?.pass_rate !== undefined ? (latestPhaseMetrics.pass_rate * 100).toFixed(1) : '---'}%</span>
                  </div>
                  <div className="flex flex-col items-center bg-black/20 p-4 rounded-xl border border-white/5 group relative">
                    <span className="text-slate-400 font-semibold mb-2 text-xs uppercase tracking-wider flex items-center gap-1.5">
                      Avg PnL 
                      <a href="/dashboard/docs#avg-pnl" className="text-slate-600 hover:text-blue-400 cursor-pointer transition-colors opacity-0 group-hover:opacity-100 absolute top-2 right-2"><Info className="w-3.5 h-3.5" /></a>
                    </span>
                    <span className={`font-mono font-black text-2xl ${latestPhaseMetrics?.avg_pnl_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {latestPhaseMetrics?.avg_pnl_pct !== undefined ? (latestPhaseMetrics.avg_pnl_pct * 100).toFixed(2) : '---'}%
                    </span>
                  </div>
                  <div className="flex flex-col items-center bg-black/20 p-4 rounded-xl border border-white/5 group relative">
                    <span className="text-slate-400 font-semibold mb-2 text-xs uppercase tracking-wider flex items-center gap-1.5">
                      Sharpe Ratio 
                      <a href="/dashboard/docs#sharpe-ratio" className="text-slate-600 hover:text-blue-400 cursor-pointer transition-colors opacity-0 group-hover:opacity-100 absolute top-2 right-2"><Info className="w-3.5 h-3.5" /></a>
                    </span>
                    <span className="font-mono text-white font-black text-2xl">{latestPhaseMetrics?.sharpe?.toFixed(2) ?? '---'}</span>
                  </div>
                  <div className="flex flex-col items-center bg-black/20 p-4 rounded-xl border border-white/5 group relative">
                    <span className="text-slate-400 font-semibold mb-2 text-xs uppercase tracking-wider flex items-center gap-1.5">
                      Total Breach 
                      <a href="/dashboard/docs#total-breach" className="text-slate-600 hover:text-blue-400 cursor-pointer transition-colors opacity-0 group-hover:opacity-100 absolute top-2 right-2"><Info className="w-3.5 h-3.5" /></a>
                    </span>
                    <span className="font-mono text-rose-400 font-black text-2xl">{latestPhaseMetrics?.total_breach !== undefined ? (latestPhaseMetrics.total_breach * 100).toFixed(1) : '---'}%</span>
                  </div>
                </div>

                {/* Secondary FTMO Metrics Row */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                  <div className="flex flex-col items-center bg-black/20 p-3 rounded-lg border border-white/5 group relative">
                    <span className="text-slate-400 font-semibold mb-1 text-[11px] uppercase tracking-wider flex items-center gap-1.5">
                      Daily Breach 
                      <a href="/dashboard/docs#daily-breach" className="text-slate-600 hover:text-blue-400 cursor-pointer transition-colors opacity-0 group-hover:opacity-100"><Info className="w-3.5 h-3.5" /></a>
                    </span>
                    <span className="font-mono text-orange-400 font-bold text-lg">{latestPhaseMetrics?.daily_breach !== undefined ? (latestPhaseMetrics.daily_breach * 100).toFixed(1) : '---'}%</span>
                  </div>
                  <div className="flex flex-col items-center bg-black/20 p-3 rounded-lg border border-white/5 group relative">
                    <span className="text-slate-400 font-semibold mb-1 text-[11px] uppercase tracking-wider flex items-center gap-1.5">
                      Avg Trades 
                      <a href="/dashboard/docs#avg-trades" className="text-slate-600 hover:text-blue-400 cursor-pointer transition-colors opacity-0 group-hover:opacity-100"><Info className="w-3.5 h-3.5" /></a>
                    </span>
                    <span className="font-mono text-white font-bold text-lg">{latestPhaseMetrics?.avg_trades ?? '---'}</span>
                  </div>
                  <div className="flex flex-col items-center bg-black/20 p-3 rounded-lg border border-white/5 group relative">
                    <span className="text-slate-400 font-semibold mb-1 text-[11px] uppercase tracking-wider flex items-center gap-1.5">
                      Active Episodes 
                      <a href="/dashboard/docs#active-episodes" className="text-slate-600 hover:text-blue-400 cursor-pointer transition-colors opacity-0 group-hover:opacity-100"><Info className="w-3.5 h-3.5" /></a>
                    </span>
                    <span className="font-mono text-white font-bold text-lg">{latestPhaseMetrics?.active_episode_fraction !== undefined ? (latestPhaseMetrics.active_episode_fraction * 100).toFixed(1) : '---'}%</span>
                  </div>
                  <div className="flex flex-col items-center bg-black/20 p-3 rounded-lg border border-white/5 group relative">
                    <span className="text-slate-400 font-semibold mb-1 text-[11px] uppercase tracking-wider flex items-center gap-1.5">
                      Sample Size 
                      <a href="/dashboard/docs#n-episodes" className="text-slate-600 hover:text-blue-400 cursor-pointer transition-colors opacity-0 group-hover:opacity-100"><Info className="w-3.5 h-3.5" /></a>
                    </span>
                    <span className="font-mono text-slate-500 font-bold text-lg">{latestPhaseMetrics?.n_episodes ?? '---'}</span>
                  </div>
                </div>

                {/* Deep Learning Stats Accordion */}
                {latestPhaseMetrics?.nerd_stats && (
                  <div className="border border-white/5 rounded-xl overflow-hidden mt-6 bg-black/20">
                    <button 
                      onClick={() => setShowNerdStats(!showNerdStats)}
                      className="w-full hover:bg-white/5 p-4 flex justify-between items-center text-slate-300 transition-colors"
                    >
                      <span className="font-bold text-sm tracking-wide uppercase flex items-center gap-2">
                        <Activity className="w-4 h-4 text-slate-400" />
                        Deep Learning Stats
                      </span>
                      <span className="text-slate-500 font-mono text-xs">{showNerdStats ? '▼ COLLAPSE' : '▶ EXPAND'}</span>
                    </button>
                    
                    {showNerdStats && (
                      <div className="p-6 border-t border-white/5 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-x-6 gap-y-6 text-xs font-mono bg-black/10">
                        
                        {/* TIME METRICS */}
                        <div className="flex flex-col group relative bg-black/20 p-3 rounded-lg">
                          <span className="text-slate-500 mb-1.5 flex justify-between items-center font-sans font-semibold tracking-wide">
                            Time / FPS 
                            <a href="/dashboard/docs#fps" className="text-slate-600 hover:text-blue-400 cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"><Info className="w-3.5 h-3.5" /></a>
                          </span>
                          <span className="text-white text-sm font-medium">{latestPhaseMetrics?.nerd_stats?.fps ?? '---'}</span>
                        </div>
                        <div className="flex flex-col group relative bg-black/20 p-3 rounded-lg">
                          <span className="text-slate-500 mb-1.5 flex justify-between items-center font-sans font-semibold tracking-wide">
                            Time / Iterations 
                            <a href="/dashboard/docs#iterations" className="text-slate-600 hover:text-blue-400 cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"><Info className="w-3.5 h-3.5" /></a>
                          </span>
                          <span className="text-white text-sm font-medium">{latestPhaseMetrics?.nerd_stats?.iterations ?? '---'}</span>
                        </div>
                        <div className="flex flex-col group relative bg-black/20 p-3 rounded-lg">
                          <span className="text-slate-500 mb-1.5 flex justify-between items-center font-sans font-semibold tracking-wide">
                            Time / Elapsed Sec 
                            <a href="/dashboard/docs#time-elapsed" className="text-slate-600 hover:text-blue-400 cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"><Info className="w-3.5 h-3.5" /></a>
                          </span>
                          <span className="text-white text-sm font-medium">{latestPhaseMetrics?.nerd_stats?.time_elapsed ?? '---'}</span>
                        </div>
                        <div className="flex flex-col group relative bg-black/20 p-3 rounded-lg">
                          <span className="text-slate-500 mb-1.5 flex justify-between items-center font-sans font-semibold tracking-wide">
                            Time / Total Steps 
                            <a href="/dashboard/docs#total-timesteps" className="text-slate-600 hover:text-blue-400 cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"><Info className="w-3.5 h-3.5" /></a>
                          </span>
                          <span className="text-white text-sm font-medium">{latestPhaseMetrics?.nerd_stats?.total_timesteps ?? '---'}</span>
                        </div>

                        {/* ROLLOUT METRICS */}
                        <div className="flex flex-col group relative bg-black/20 p-3 rounded-lg">
                          <span className="text-slate-500 mb-1.5 flex justify-between items-center font-sans font-semibold tracking-wide">
                            Rollout / Ep Len 
                            <a href="/dashboard/docs#ep-len" className="text-slate-600 hover:text-blue-400 cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"><Info className="w-3.5 h-3.5" /></a>
                          </span>
                          <span className="text-white text-sm font-medium">{latestPhaseMetrics?.nerd_stats?.ep_len_mean?.toFixed(1) ?? '---'}</span>
                        </div>
                        <div className="flex flex-col group relative bg-black/20 p-3 rounded-lg">
                          <span className="text-slate-500 mb-1.5 flex justify-between items-center font-sans font-semibold tracking-wide">
                            Rollout / Ep Rew 
                            <a href="/dashboard/docs#ep-rew" className="text-slate-600 hover:text-blue-400 cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"><Info className="w-3.5 h-3.5" /></a>
                          </span>
                          <span className="text-white text-sm font-medium">{latestPhaseMetrics?.nerd_stats?.ep_rew_mean?.toFixed(1) ?? '---'}</span>
                        </div>

                        {/* TRAIN METRICS */}
                        <div className="flex flex-col group relative bg-black/20 p-3 rounded-lg">
                          <span className="text-slate-500 mb-1.5 flex justify-between items-center font-sans font-semibold tracking-wide">
                            Train / Loss 
                            <a href="/dashboard/docs#loss" className="text-slate-600 hover:text-blue-400 cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"><Info className="w-3.5 h-3.5" /></a>
                          </span>
                          <span className="text-white text-sm font-medium">{latestPhaseMetrics?.nerd_stats?.loss?.toExponential(2) ?? '---'}</span>
                        </div>
                        <div className="flex flex-col group relative bg-black/20 p-3 rounded-lg">
                          <span className="text-slate-500 mb-1.5 flex justify-between items-center font-sans font-semibold tracking-wide">
                            Train / Entropy 
                            <a href="/dashboard/docs#entropy" className="text-slate-600 hover:text-blue-400 cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"><Info className="w-3.5 h-3.5" /></a>
                          </span>
                          <span className="text-white text-sm font-medium">{latestPhaseMetrics?.nerd_stats?.entropy_loss?.toFixed(3) ?? '---'}</span>
                        </div>
                        <div className="flex flex-col group relative bg-black/20 p-3 rounded-lg border border-rose-500/20">
                          <span className="text-rose-500/70 mb-1.5 flex justify-between items-center font-sans font-semibold tracking-wide">
                            Train / Std Dev 
                            <a href="/dashboard/docs#std" className="text-rose-600 hover:text-rose-400 cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"><Info className="w-3.5 h-3.5" /></a>
                          </span>
                          <span className="text-rose-400 font-bold text-sm">{latestPhaseMetrics?.nerd_stats?.std?.toFixed(2) ?? '---'}</span>
                        </div>
                        <div className="flex flex-col group relative bg-black/20 p-3 rounded-lg">
                          <span className="text-slate-500 mb-1.5 flex justify-between items-center font-sans font-semibold tracking-wide">
                            Train / Expl Var 
                            <a href="/dashboard/docs#explained-var" className="text-slate-600 hover:text-blue-400 cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"><Info className="w-3.5 h-3.5" /></a>
                          </span>
                          <span className="text-white text-sm font-medium">{latestPhaseMetrics?.nerd_stats?.explained_variance?.toFixed(3) ?? '---'}</span>
                        </div>
                        <div className="flex flex-col group relative bg-black/20 p-3 rounded-lg">
                          <span className="text-slate-500 mb-1.5 flex justify-between items-center font-sans font-semibold tracking-wide">
                            Train / Approx KL 
                            <a href="/dashboard/docs#approx-kl" className="text-slate-600 hover:text-blue-400 cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"><Info className="w-3.5 h-3.5" /></a>
                          </span>
                          <span className="text-white text-sm font-medium">{latestPhaseMetrics?.nerd_stats?.approx_kl?.toExponential(2) ?? '---'}</span>
                        </div>
                        <div className="flex flex-col group relative bg-black/20 p-3 rounded-lg">
                          <span className="text-slate-500 mb-1.5 flex justify-between items-center font-sans font-semibold tracking-wide">
                            Train / LR 
                            <a href="/dashboard/docs#learning-rate" className="text-slate-600 hover:text-blue-400 cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"><Info className="w-3.5 h-3.5" /></a>
                          </span>
                          <span className="text-white text-sm font-medium">{latestPhaseMetrics?.nerd_stats?.learning_rate?.toExponential(2) ?? '---'}</span>
                        </div>
                        <div className="flex flex-col group relative bg-black/20 p-3 rounded-lg">
                          <span className="text-slate-500 mb-1.5 flex justify-between items-center font-sans font-semibold tracking-wide">
                            Train / Policy Loss 
                            <a href="/dashboard/docs#policy-loss" className="text-slate-600 hover:text-blue-400 cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"><Info className="w-3.5 h-3.5" /></a>
                          </span>
                          <span className="text-white text-sm font-medium">{latestPhaseMetrics?.nerd_stats?.policy_gradient_loss?.toExponential(2) ?? '---'}</span>
                        </div>
                        <div className="flex flex-col group relative bg-black/20 p-3 rounded-lg">
                          <span className="text-slate-500 mb-1.5 flex justify-between items-center font-sans font-semibold tracking-wide">
                            Train / Value Loss 
                            <a href="/dashboard/docs#value-loss" className="text-slate-600 hover:text-blue-400 cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"><Info className="w-3.5 h-3.5" /></a>
                          </span>
                          <span className="text-white text-sm font-medium">{latestPhaseMetrics?.nerd_stats?.value_loss?.toExponential(2) ?? '---'}</span>
                        </div>
                        <div className="flex flex-col group relative bg-black/20 p-3 rounded-lg">
                          <span className="text-slate-500 mb-1.5 flex justify-between items-center font-sans font-semibold tracking-wide">
                            Train / Clip Frac 
                            <a href="/dashboard/docs#clip-fraction" className="text-slate-600 hover:text-blue-400 cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"><Info className="w-3.5 h-3.5" /></a>
                          </span>
                          <span className="text-white text-sm font-medium">{latestPhaseMetrics?.nerd_stats?.clip_fraction?.toFixed(3) ?? '---'}</span>
                        </div>
                        <div className="flex flex-col group relative bg-black/20 p-3 rounded-lg">
                          <span className="text-slate-500 mb-1.5 flex justify-between items-center font-sans font-semibold tracking-wide">
                            Train / Updates 
                            <a href="/dashboard/docs#n-updates" className="text-slate-600 hover:text-blue-400 cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"><Info className="w-3.5 h-3.5" /></a>
                          </span>
                          <span className="text-white text-sm font-medium">{latestPhaseMetrics?.nerd_stats?.n_updates ?? '---'}</span>
                        </div>
                      </div>
                    )}
                  </div>
                )}

              </div>
            ) : (
              <div className="flex flex-col items-center justify-center text-center text-slate-500 min-h-[300px]">
                <Activity className="w-8 h-8 mb-4 animate-pulse opacity-50" />
                <p>Waiting for training metrics...</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
