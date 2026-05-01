import { FlaskConical, Beaker, GitCommitHorizontal, Play, ArrowUpRight } from 'lucide-react';

export default function StrategyPage() {
  return (
    <div className="space-y-6 max-w-6xl mx-auto animate-in fade-in duration-500">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-black text-white mb-1">Strategy Lab</h1>
          <p className="text-slate-500 text-sm">Develop, backtest, and optimize reinforcement learning models.</p>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <div className="glass-panel p-6 rounded-2xl flex flex-col justify-center min-h-[300px] border-dashed border-2 border-white/10 bg-black/20 items-center text-center">
             <FlaskConical className="w-12 h-12 text-slate-600 mb-4" />
             <h3 className="text-xl font-bold text-white mb-2">No Active Experiments</h3>
             <p className="text-slate-500 text-sm max-w-sm mb-6">Start a new backtest or walk-forward validation run to see training curves and hyperparameter performance metrics here.</p>
             <button className="bg-white text-black font-bold py-2 px-6 rounded-lg transition-colors text-sm hover:opacity-90">
               New Experiment
             </button>
          </div>

          <div className="glass-panel p-6 rounded-2xl">
            <h3 className="text-lg font-bold text-white mb-4">Recent Runs</h3>
            <div className="space-y-3">
               {[1,2,3].map((run, i) => (
                 <div key={i} className="flex items-center justify-between p-4 rounded-xl bg-white/[0.02] border border-white/5 hover:bg-white/[0.05] transition-colors cursor-pointer">
                   <div className="flex items-center gap-4">
                     <div className={`p-2 rounded-full ${i === 0 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-slate-500/10 text-slate-400'}`}>
                       <Beaker className="w-5 h-5" />
                     </div>
                     <div>
                       <h4 className="font-bold text-white text-sm">PPO Walk-Forward Tuning (Run #{142-i})</h4>
                       <p className="text-xs text-slate-500 mt-1 flex items-center gap-2">
                         <GitCommitHorizontal className="w-3 h-3" /> Commit e81272{i} • April {28-i}, 2026
                       </p>
                     </div>
                   </div>
                   <div className="text-right">
                     <p className={`text-sm font-bold ${i === 0 ? 'text-emerald-400' : 'text-slate-300'}`}>{i===0 ? 'Completed' : 'Aborted'}</p>
                     <p className="text-xs text-slate-500 mt-1">{i===0 ? 'Sharpe: 2.14' : '--'}</p>
                   </div>
                 </div>
               ))}
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <div className="glass-panel p-6 rounded-2xl">
            <h3 className="text-lg font-bold text-white mb-4">Pipeline Status</h3>
            <div className="space-y-4">
              <div>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-slate-400">Data Synchronization</span>
                  <span className="text-emerald-400">Healthy</span>
                </div>
                <div className="h-1.5 w-full bg-black/40 rounded-full overflow-hidden">
                  <div className="h-full bg-emerald-500 w-full animate-pulse opacity-50"></div>
                </div>
              </div>
              
              <div>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-slate-400">Feature Engineering cache</span>
                  <span className="text-white">Up to date</span>
                </div>
                <div className="h-1.5 w-full bg-black/40 rounded-full overflow-hidden">
                  <div className="h-full bg-cyan-500 w-full"></div>
                </div>
              </div>

               <div>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-slate-400">LSEG API Connection</span>
                  <span className="text-emerald-400">Connected</span>
                </div>
              </div>
            </div>
          </div>

          <div className="glass-panel p-6 rounded-2xl bg-gradient-to-br from-cyan-900/20 to-emerald-900/20 border border-cyan-500/20">
            <h3 className="text-sm font-bold text-white mb-2 uppercase tracking-wider">Quick Actions</h3>
            <div className="space-y-2 mt-4">
              <button className="w-full flex items-center justify-between px-4 py-3 rounded-lg bg-black/40 border border-white/5 hover:border-cyan-500/30 hover:bg-black/60 transition-all text-sm text-slate-300">
                <span>Retrain Active Model</span>
                <Play className="w-4 h-4 text-cyan-400" />
              </button>
              <button className="w-full flex items-center justify-between px-4 py-3 rounded-lg bg-black/40 border border-white/5 hover:border-cyan-500/30 hover:bg-black/60 transition-all text-sm text-slate-300">
                <span>Update Dataset (Dukascopy)</span>
                <ArrowUpRight className="w-4 h-4 text-cyan-400" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}