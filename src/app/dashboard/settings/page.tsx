import { Settings, Save, Database, Key, Shield } from 'lucide-react';

export default function SettingsPage() {
  return (
    <div className="space-y-6 max-w-4xl mx-auto animate-in fade-in duration-500">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-black text-white mb-1">Configuration</h1>
          <p className="text-slate-500 text-sm">System settings, API keys, and database preferences.</p>
        </div>
      </header>

      <div className="glass-panel p-8 rounded-2xl space-y-8">
        {/* Environment Settings */}
        <section>
          <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2"><Database className="w-5 h-5 text-cyan-400"/> Database & Connectors</h3>
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-center border-b border-white/5 pb-4">
              <label className="text-sm font-medium text-slate-300">Backend URL</label>
              <div className="md:col-span-3">
                <input 
                  type="text" 
                  defaultValue="http://localhost:8000"
                  className="w-full bg-black/20 border border-white/10 rounded-lg px-4 py-2 text-white text-sm font-mono focus:outline-none focus:border-cyan-500/50" 
                />
              </div>
            </div>
             <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-center border-b border-white/5 pb-4">
              <label className="text-sm font-medium text-slate-300">LSEG Feed Host</label>
              <div className="md:col-span-3">
                <input 
                  type="text" 
                  defaultValue="wss://streaming.ws.reuters.com"
                  className="w-full bg-black/20 border border-white/10 rounded-lg px-4 py-2 text-white text-sm font-mono focus:outline-none focus:border-cyan-500/50" 
                />
              </div>
            </div>
             <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-center">
              <label className="text-sm font-medium text-slate-300">Data Root Dir</label>
              <div className="md:col-span-3">
                <input 
                  type="text" 
                  defaultValue="./data/raw"
                  className="w-full bg-black/20 border border-white/10 rounded-lg px-4 py-2 text-white text-sm font-mono focus:outline-none focus:border-cyan-500/50" 
                />
              </div>
            </div>
          </div>
        </section>

        {/* API Keys */}
        <section>
          <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2"><Key className="w-5 h-5 text-cyan-400"/> API Authentication</h3>
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-center border-b border-white/5 pb-4">
              <label className="text-sm font-medium text-slate-300">Dukascopy Key</label>
              <div className="md:col-span-3">
                <input 
                  type="password" 
                  defaultValue="************************"
                  className="w-full bg-black/20 border border-white/10 rounded-lg px-4 py-2 text-white text-sm font-mono focus:outline-none focus:border-cyan-500/50" 
                />
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-center border-b border-white/5 pb-4">
              <label className="text-sm font-medium text-slate-300">Supabase URL</label>
              <div className="md:col-span-3">
                <input 
                  type="password" 
                  defaultValue="************************"
                  className="w-full bg-black/20 border border-white/10 rounded-lg px-4 py-2 text-white text-sm font-mono focus:outline-none focus:border-cyan-500/50" 
                />
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-center">
              <label className="text-sm font-medium text-slate-300">Prop Firm Ticker Base</label>
              <div className="md:col-span-3">
                <input 
                  type="text" 
                  defaultValue="EURUSD,GBPUSD,XAUUSD"
                  className="w-full bg-black/20 border border-white/10 rounded-lg px-4 py-2 text-white text-sm font-mono focus:outline-none focus:border-cyan-500/50" 
                />
              </div>
            </div>
          </div>
        </section>

        {/* Risk Management */}
        <section>
          <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2"><Shield className="w-5 h-5 text-cyan-400"/> Risk Parameters</h3>
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-center border-b border-white/5 pb-4">
              <label className="text-sm font-medium text-slate-300">Max Daily Drawdown</label>
              <div className="md:col-span-3">
                <input 
                  type="number" 
                  defaultValue="4.5"
                  step="0.1"
                  className="w-full bg-black/20 border border-white/10 rounded-lg px-4 py-2 text-white text-sm font-mono focus:outline-none focus:border-cyan-500/50" 
                />
              </div>
            </div>
             <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-center">
              <label className="text-sm font-medium text-slate-300">Emergency Kill-switch</label>
              <div className="md:col-span-3">
                <button className="bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 border border-rose-500/20 font-bold py-2 px-4 rounded-lg transition-colors text-sm">
                  Deactivate All Agents
                </button>
                <p className="text-xs text-slate-500 mt-2">Instantly closes all open positions at market prices and halts agent execution loops.</p>
              </div>
            </div>
          </div>
        </section>

        <div className="flex justify-end pt-4 border-t border-white/5 mt-8">
          <button className="bg-emerald-500 hover:bg-emerald-400 text-black font-bold py-2 px-6 rounded-lg transition-colors text-sm flex items-center gap-2">
            <Save className="w-4 h-4" /> Save Configuration
          </button>
        </div>
      </div>
    </div>
  );
}