"use client";

import { Cpu } from "lucide-react";

export default function AgentsPage() {
  return (
    <div className="space-y-6 max-w-6xl mx-auto animate-in fade-in duration-500">
      <header>
        <h1 className="text-3xl font-black text-white mb-1">Active Agents</h1>
        <p className="text-slate-500 text-sm">Monitor and manage deployed reinforcement learning agents.</p>
      </header>

      <div className="glass-panel p-12 flex flex-col items-center justify-center text-center border-dashed border-white/10 border-2">
        <Cpu className="w-12 h-12 text-cyan-400 mb-4 opacity-50" />
        <h3 className="text-xl font-bold text-white mb-2">No Active Agents Found</h3>
        <p className="text-slate-500 text-sm max-w-md">
          Once you deploy a trained PPO model to your cTrader account, it will appear here.
        </p>
      </div>
    </div>
  );
}
