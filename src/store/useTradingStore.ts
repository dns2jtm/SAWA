import { create } from 'zustand';

export type EquityPoint = {
  timestamp: string;
  equity: number;
};

export type OrganismMetrics = {
  equity: number;
  drawdown: number;
  volatility: number;
  last_action: string;
};

interface TradingStoreState {
  isConnected: boolean;
  metrics: OrganismMetrics;
  equityHistory: EquityPoint[];
  chartRevision: number;
  connect: () => void;
  disconnect: () => void;
}

let ws: WebSocket | null = null;
let reconnectTimeout: NodeJS.Timeout | null = null;

export const useTradingStore = create<TradingStoreState>((set, get) => ({
  isConnected: false,
  metrics: {
    equity: 0,
    drawdown: 0.0,
    volatility: 0.0,
    last_action: 'WAITING'
  },
  equityHistory: [],
  chartRevision: 0,

  connect: () => {
    if (typeof window === 'undefined') return;
    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return;

    ws = new WebSocket('ws://localhost:8001/ws/organism');

    ws.onopen = () => {
      set({ isConnected: true });
      console.log('Connected to live metrics stream (Zustand)');
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        set((state) => {
          const newMetrics = { ...state.metrics, ...data };
          let newHistory = state.equityHistory;

          let newRevision = state.chartRevision;

          if (data.equity && data.equity > 0) {
            const now = new Date().toISOString();
            const newPoint = { timestamp: data.timestamp || now, equity: data.equity };
            
            // If timestamp matches the last point, update it instead of adding a duplicate
            // This prevents Plotly from drawing vertical glitch lines for identical timestamps
            if (state.equityHistory.length > 0 && state.equityHistory[state.equityHistory.length - 1].timestamp === newPoint.timestamp) {
              newHistory = [...state.equityHistory];
              newHistory[newHistory.length - 1] = newPoint;
              newRevision += 1;
            } else {
              newHistory = [...state.equityHistory, newPoint];
              newRevision += 1;
              // Keep last 1000 points to prevent memory bloat
              if (newHistory.length > 1000) {
                newHistory = newHistory.slice(newHistory.length - 1000);
              }
            }
          }

          return { metrics: newMetrics, equityHistory: newHistory, chartRevision: newRevision };
        });
      } catch (e) {
        console.error('Error parsing metrics data', e);
      }
    };

    ws.onclose = () => {
      set({ isConnected: false });
      ws = null;
      console.log('Disconnected from live metrics stream. Reconnecting in 3s...');
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      reconnectTimeout = setTimeout(() => get().connect(), 3000);
    };

    ws.onerror = (err) => {
      console.error('WebSocket error:', err);
      if (ws) ws.close();
    };
  },

  disconnect: () => {
    if (reconnectTimeout) clearTimeout(reconnectTimeout);
    if (ws) {
      ws.close();
      ws = null;
    }
    set({ isConnected: false });
  }
}));
