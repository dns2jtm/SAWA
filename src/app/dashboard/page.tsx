"use client";
import { useState, useEffect } from 'react';
import { Activity, TrendingUp, ShieldAlert, Zap, Wifi, WifiOff } from 'lucide-react';
import EquityChart from './EquityChart';

export default function DashboardOverview() {
  const [metrics, setMetrics] = useState({
    equity: 0,
    drawdown: 0.0,
    volatility: 0.0,
    last_action: 'WAITING'
  });
  const [isConnected, setIsConnected] = useState(false);
  const [equityHistory, setEquityHistory] = useState<{timestamp: string; equity: number}[]>([]);

  useEffect(() => {
    let ws: WebSocket;
    let reconnectTimeout: NodeJS.Timeout;

    const connect = () => {
      // Connect to the FastAPI WebSocket backend for live organism metrics
      ws = new WebSocket('ws://localhost:8001/ws/organism');

      ws.onopen = () => {
        setIsConnected(true);
        console.log('Connected to live metrics stream');
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setMetrics(prev => ({ ...prev, ...data }));
          
          if (data.equity && data.equity > 0) {
            setEquityHistory(prev => {
              const now = new Date().toISOString();
              const updated = [...prev, { timestamp: data.timestamp || now, equity: data.equity }];
              // Keep last 1000 points to prevent memory bloat
              return updated.length > 1000 ? updated.slice(updated.length - 1000) : updated;
            });
          }
        } catch (e) {
          console.error('Error parsing metrics data', e);
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        console.log('Disconnected from live metrics stream. Reconnecting...');
        // Auto-reconnect after 3 seconds
        reconnectTimeout = setTimeout(connect, 3000);
      };

      ws.onerror = (err) => {
        console.error('WebSocket error:', err);
        ws.close();
      };
    };

    connect();

    return () => {
      clearTimeout(reconnectTimeout);
      if (ws) ws.close();
    };
  }, []);

  const formatCurrency = (val: number) => {
    return new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(val);
  };

  return (
    <div className="space-y-6 max-w-6xl mx-auto animate-in fade-in duration-500">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-black text-white mb-1">Live Overview</h1>
          <p className="text-slate-500 text-sm">Real-time RL agent execution metrics and portfolio status.</p>
        </div>
        <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider border transition-colors ${
          isConnected ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-red-500/10 text-red-400 border-red-500/20'
        }`}>
          {isConnected ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
          {isConnected ? 'Live' : 'Disconnected'}
        </div>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {/* Equity Card */}
        <div className="glass-panel p-6 relative overflow-hidden group">
          <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
            <TrendingUp className="w-12 h-12 text-cyan-400" />
          </div>
          <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-2">Total Equity</p>
          <p className="text-3xl font-black text-white">
            {metrics.equity > 0 ? formatCurrency(metrics.equity) : '---'}
          </p>
        </div>

        {/* Drawdown Card */}
        <div className="glass-panel p-6 relative overflow-hidden group">
          <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
            <ShieldAlert className="w-12 h-12 text-rose-400" />
          </div>
          <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-2">Current Drawdown</p>
          <p className="text-3xl font-black text-white">
            {metrics.drawdown > 0 ? `${(metrics.drawdown).toFixed(2)}%` : '0.00%'}
          </p>
        </div>

        {/* Volatility Card */}
        <div className="glass-panel p-6 relative overflow-hidden group">
          <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
            <Activity className="w-12 h-12 text-emerald-400" />
          </div>
          <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-2">Market Volatility (ATR)</p>
          <p className="text-3xl font-black text-white">
            {metrics.volatility > 0 ? `${metrics.volatility.toFixed(2)}x` : '---'}
          </p>
        </div>

        {/* Last Action Card */}
        <div className="glass-panel p-6 relative overflow-hidden group">
          <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
            <Zap className="w-12 h-12 text-amber-400" />
          </div>
          <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-2">Last Action</p>
          <p className={`text-3xl font-black ${
            metrics.last_action.includes('LONG') || metrics.last_action.includes('BUY') ? 'text-emerald-400' :
            metrics.last_action.includes('SHORT') || metrics.last_action.includes('SELL') ? 'text-rose-400' :
            'text-slate-300'
          }`}>
            {metrics.last_action}
          </p>
        </div>
      </div>

      <div className="glass-panel p-6 min-h-[400px] flex flex-col relative overflow-hidden">
        <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
          <Activity className="w-5 h-5 text-cyan-400" />
          Live Equity Curve
        </h3>
        
        {equityHistory.length > 0 ? (
          <div className="flex-1 w-full">
            <EquityChart history={equityHistory} />
          </div>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-center border-dashed border-white/10 border-2 rounded-xl bg-black/20">
            <Activity className={`w-8 h-8 mb-4 ${isConnected ? 'text-cyan-500 animate-pulse' : 'text-slate-600'}`} />
            <h3 className="text-lg font-bold text-white mb-2">Live Execution Feed</h3>
            <p className="text-slate-500 text-sm max-w-md">
              {isConnected 
                ? 'Streaming real-time organism decisions and portfolio metrics from the backend...' 
                : 'Waiting for WebSocket connection to display live trading activity.'}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}