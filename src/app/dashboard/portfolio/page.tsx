import { Briefcase, TrendingUp, Wallet, ArrowUpRight, ArrowDownRight } from 'lucide-react';

export default function PortfolioPage() {
  return (
    <div className="space-y-6 max-w-6xl mx-auto animate-in fade-in duration-500">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-black text-white mb-1">Portfolio Balance</h1>
          <p className="text-slate-500 text-sm">Asset allocation and real-time PnL tracking.</p>
        </div>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="glass-panel p-6 border border-cyan-500/20 bg-cyan-950/10 rounded-2xl flex flex-col justify-center">
            <p className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-2"><Wallet className="w-4 h-4"/> Available Margin</p>
            <p className="text-4xl font-black text-white">£42,150.00</p>
            <p className="text-sm text-slate-500 mt-2">78% of Total Account Value</p>
        </div>
        <div className="glass-panel p-6 rounded-2xl flex flex-col justify-center">
            <p className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-2"><Briefcase className="w-4 h-4"/> Position Value</p>
            <p className="text-4xl font-black text-white">£11,850.00</p>
            <p className="text-sm text-slate-500 mt-2">22% of Total Account Value</p>
        </div>
        <div className="glass-panel p-6 border border-emerald-500/20 bg-emerald-950/10 rounded-2xl flex flex-col justify-center">
            <p className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-2"><TrendingUp className="w-4 h-4"/> Unrealized PnL</p>
            <div className="flex items-center gap-3">
              <p className="text-4xl font-black text-emerald-400">+£1,240.50</p>
              <ArrowUpRight className="w-8 h-8 text-emerald-400 opacity-50" />
            </div>
            <p className="text-sm text-slate-500 mt-2">+2.3% today</p>
        </div>
      </div>

      <div className="glass-panel p-6 rounded-2xl">
        <h3 className="text-lg font-bold text-white mb-6">Open Positions</h3>
        
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left text-slate-300">
            <thead className="text-xs text-slate-500 uppercase bg-black/20 border-b border-white/5">
              <tr>
                <th scope="col" className="px-6 py-4 rounded-tl-lg">Asset</th>
                <th scope="col" className="px-6 py-4">Side</th>
                <th scope="col" className="px-6 py-4">Size</th>
                <th scope="col" className="px-6 py-4">Entry Px</th>
                <th scope="col" className="px-6 py-4">Mark Px</th>
                <th scope="col" className="px-6 py-4 rounded-tr-lg">Unrealized PnL</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-white/5 hover:bg-white/[0.02] transition-colors">
                <td className="px-6 py-4 font-bold text-white">XAUUSD</td>
                <td className="px-6 py-4"><span className="text-emerald-400 bg-emerald-400/10 px-2 py-1 rounded text-xs font-bold border border-emerald-400/20">LONG</span></td>
                <td className="px-6 py-4 font-mono">2.5</td>
                <td className="px-6 py-4 font-mono">2345.10</td>
                <td className="px-6 py-4 font-mono">2352.40</td>
                <td className="px-6 py-4 font-mono text-emerald-400 flex items-center gap-1">+£1,825.00 <ArrowUpRight className="w-3 h-3"/></td>
              </tr>
              <tr className="border-b border-white/5 hover:bg-white/[0.02] transition-colors">
                <td className="px-6 py-4 font-bold text-white">EURUSD</td>
                <td className="px-6 py-4"><span className="text-rose-400 bg-rose-400/10 px-2 py-1 rounded text-xs font-bold border border-rose-400/20">SHORT</span></td>
                <td className="px-6 py-4 font-mono">10.0</td>
                <td className="px-6 py-4 font-mono">1.0845</td>
                <td className="px-6 py-4 font-mono">1.0862</td>
                <td className="px-6 py-4 font-mono text-rose-400 flex items-center gap-1">-£584.50 <ArrowDownRight className="w-3 h-3"/></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}