import { Activity, ShieldCheck, Zap } from 'lucide-react';

export default function AgentsPage() {
  return (
    <div className="space-y-6 max-w-6xl mx-auto animate-in fade-in duration-500">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-black text-white mb-1">Active Agents</h1>
          <p className="text-slate-500 text-sm">Monitor and manage your deployed reinforcement learning organisms.</p>
        </div>
        <button className="bg-emerald-500 hover:bg-emerald-400 text-black font-bold py-2 px-4 rounded-lg transition-colors text-sm flex items-center gap-2">
          <Zap className="w-4 h-4" /> Deploy New Agent
        </button>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Agent Card 1 */}
        <div className="glass-panel p-6 border border-emerald-500/20 relative overflow-hidden group">
          <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
            <Activity className="w-16 h-16 text-emerald-400" />
          </div>
          <div className="flex justify-between items-start mb-6">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <h3 className="text-xl font-bold text-white">SAWA-Alpha-v1.4</h3>
                <span className="bg-emerald-500/10 text-emerald-400 text-[10px] font-bold px-2 py-0.5 rounded-full uppercase border border-emerald-500/20">Active</span>
              </div>
              <p className="text-sm text-slate-400">Mean Reversion / Trend Following</p>
            </div>
          </div>
          
          <div className="grid grid-cols-2 gap-4 mb-6">
            <div className="bg-black/20 rounded-lg p-3 border border-white/5">
              <p className="text-xs text-slate-500 mb-1">Total Return</p>
              <p className="text-lg font-bold text-emerald-400">+24.5%</p>
            </div>
            <div className="bg-black/20 rounded-lg p-3 border border-white/5">
              <p className="text-xs text-slate-500 mb-1">Sharpe Ratio</p>
              <p className="text-lg font-bold text-white">2.1</p>
            </div>
            <div className="bg-black/20 rounded-lg p-3 border border-white/5">
              <p className="text-xs text-slate-500 mb-1">Max Drawdown</p>
              <p className="text-lg font-bold text-rose-400">-4.2%</p>
            </div>
            <div className="bg-black/20 rounded-lg p-3 border border-white/5">
              <p className="text-xs text-slate-500 mb-1">Trades</p>
              <p className="text-lg font-bold text-white">1,432</p>
            </div>
          </div>

          <div className="flex justify-end gap-3">
            <button className="px-4 py-2 bg-white/5 hover:bg-white/10 text-white rounded-lg text-sm transition-colors border border-white/10">Configure</button>
            <button className="px-4 py-2 bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 rounded-lg text-sm transition-colors border border-rose-500/20">Halt Trading</button>
          </div>
        </div>

        {/* Agent Card 2 */}
        <div className="glass-panel p-6 opacity-60 border border-white/5 relative overflow-hidden group">
          <div className="absolute top-0 right-0 p-4 opacity-10 transition-opacity">
            <ShieldCheck className="w-16 h-16 text-slate-400" />
          </div>
          <div className="flex justify-between items-start mb-6">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <h3 className="text-xl font-bold text-white">SAWA-Beta-v0.9</h3>
                <span className="bg-slate-500/10 text-slate-400 text-[10px] font-bold px-2 py-0.5 rounded-full uppercase border border-slate-500/20">Standby</span>
              </div>
              <p className="text-sm text-slate-400">High Frequency Arbitrage</p>
            </div>
          </div>
          
          <div className="grid grid-cols-2 gap-4 mb-6">
            <div className="bg-black/20 rounded-lg p-3 border border-white/5">
              <p className="text-xs text-slate-500 mb-1">Backtest Return</p>
              <p className="text-lg font-bold text-white">+18.2%</p>
            </div>
            <div className="bg-black/20 rounded-lg p-3 border border-white/5">
              <p className="text-xs text-slate-500 mb-1">Sharpe Ratio</p>
              <p className="text-lg font-bold text-white">1.8</p>
            </div>
            <div className="bg-black/20 rounded-lg p-3 border border-white/5">
              <p className="text-xs text-slate-500 mb-1">Max Drawdown</p>
              <p className="text-lg font-bold text-white">-6.1%</p>
            </div>
            <div className="bg-black/20 rounded-lg p-3 border border-white/5">
              <p className="text-xs text-slate-500 mb-1">Status</p>
              <p className="text-lg font-bold text-amber-400">Validating</p>
            </div>
          </div>

          <div className="flex justify-end gap-3">
             <button className="px-4 py-2 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 rounded-lg text-sm transition-colors border border-emerald-500/20">Resume Trading</button>
          </div>
        </div>
      </div>
    </div>
  );
}