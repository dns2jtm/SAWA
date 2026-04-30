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

          if (data.equity && data.equity > 0) {
            const now = new Date().toISOString();
            const newPoint = { timestamp: data.timestamp || now, equity: data.equity };
            newHistory = [...state.equityHistory, newPoint];
            // Keep last 1000 points to prevent memory bloat
            if (newHistory.length > 1000) {
              newHistory = newHistory.slice(newHistory.length - 1000);
            }
          }

          return { metrics: newMetrics, equityHistory: newHistory };
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
