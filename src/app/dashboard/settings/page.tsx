"use client";

import { Settings } from "lucide-react";

export default function SettingsPage() {
  return (
    <div className="space-y-6 max-w-6xl mx-auto animate-in fade-in duration-500">
      <header>
        <h1 className="text-3xl font-black text-white mb-1">Settings</h1>
        <p className="text-slate-500 text-sm">Configure broker connections, Telegram alerts, and risk thresholds.</p>
      </header>

      <div className="glass-panel p-12 flex flex-col items-center justify-center text-center border-dashed border-white/10 border-2">
        <Settings className="w-12 h-12 text-slate-400 mb-4 opacity-50" />
        <h3 className="text-xl font-bold text-white mb-2">Configuration Missing</h3>
        <p className="text-slate-500 text-sm max-w-md">
          Please edit the .env file in the repository root to configure cTrader, MetaApi, and RunPod credentials.
        </p>
      </div>
    </div>
  );
}
