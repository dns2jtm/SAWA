"use client";

import { Briefcase } from "lucide-react";

export default function PortfolioPage() {
  return (
    <div className="space-y-6 max-w-6xl mx-auto animate-in fade-in duration-500">
      <header>
        <h1 className="text-3xl font-black text-white mb-1">Portfolio</h1>
        <p className="text-slate-500 text-sm">Aggregate metrics across all prop-firm accounts.</p>
      </header>

      <div className="glass-panel p-12 flex flex-col items-center justify-center text-center border-dashed border-white/10 border-2">
        <Briefcase className="w-12 h-12 text-emerald-400 mb-4 opacity-50" />
        <h3 className="text-xl font-bold text-white mb-2">No Connected Accounts</h3>
        <p className="text-slate-500 text-sm max-w-md">
          Connect your cTrader or MetaApi accounts in the settings tab to view aggregate equity curves.
        </p>
      </div>
    </div>
  );
}
