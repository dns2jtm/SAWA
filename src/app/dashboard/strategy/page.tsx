"use client";

import { FlaskConical } from "lucide-react";

export default function StrategyLabPage() {
  return (
    <div className="space-y-6 max-w-6xl mx-auto animate-in fade-in duration-500">
      <header>
        <h1 className="text-3xl font-black text-white mb-1">Strategy Lab</h1>
        <p className="text-slate-500 text-sm">Review backtest results, curriculum progress, and feature importance.</p>
      </header>

      <div className="glass-panel p-12 flex flex-col items-center justify-center text-center border-dashed border-white/10 border-2">
        <FlaskConical className="w-12 h-12 text-purple-400 mb-4 opacity-50" />
        <h3 className="text-xl font-bold text-white mb-2">Awaiting Walk-Forward Test</h3>
        <p className="text-slate-500 text-sm max-w-md">
          Run python scripts/backtest.py --report to generate JSON reports that will automatically populate this view.
        </p>
      </div>
    </div>
  );
}
