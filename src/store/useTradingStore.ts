import { create } from 'zustand';

export type Position = {
  id: string;
  type: 'BUY' | 'SHORT';
  openTime: string;
  volume: number;
  symbol: string;
  profit: number;
  pips: number;
};

export type DailySummary = {
  date: string;
  trades: number;
  lots: number;
  result: number;
};

type AccountStats = {
  balance?: number;
  currency?: string;
  net_pnl?: number;
  net_pnl_pct?: number;
  daily_summary?: DailySummary[];
};

type AccountType = {
  accountStats: AccountStats;
  positions: Position[];
  balance: number;
  isSimulated: boolean;
  isLive: boolean;
  volatility: number;
  lastAction: string;
};

interface TradingStoreState {
  accounts: Record<string, AccountType>;
  equity: number;
  equityHistory: { equity: number; timestamp: string }[];
  drawdown: number;
}

export const useTradingStore = create<TradingStoreState>((set) => {
  // Start simulation loop for client-side demo
  if (typeof window !== 'undefined') {
    setInterval(() => {
      set((state) => {
        const lastEq = state.equity;
        const trend = Math.random() > 0.4 ? 1 : -1; // Slight upward bias
        const diff = (Math.random() * 25) * trend; // random small gain or loss
        const newEq = lastEq + diff;
        
        const newVol = Math.max(0.2, state.accounts['531260945'].volatility + (Math.random() * 0.2 - 0.1));
        const newDrawdown = Math.max(0, state.drawdown + (newEq < lastEq ? 0.05 : -0.05));
        
        return {
          equity: newEq,
          drawdown: newDrawdown,
          equityHistory: [
            ...state.equityHistory.slice(-50), // keep last 50 points
            { equity: newEq, timestamp: new Date().toISOString() }
          ],
          accounts: {
            ...state.accounts,
            '531260945': {
              ...state.accounts['531260945'],
              volatility: newVol,
              lastAction: trend > 0 ? (Math.random() > 0.5 ? 'LONG' : 'FLAT') : (Math.random() > 0.5 ? 'SHORT' : 'FLAT'),
              accountStats: {
                ...state.accounts['531260945'].accountStats,
                net_pnl: newEq - 70000,
                net_pnl_pct: ((newEq - 70000) / 70000) * 100
              }
            }
          }
        };
      });
    }, 2000); // update every 2 seconds
  }

  return {
  accounts: {
    '531260945': {
      accountStats: {
        balance: 70000,
        currency: 'GBP',
        net_pnl: 0,
        net_pnl_pct: 0,
        daily_summary: [
          { date: '2026-04-13', trades: 5, lots: 2.5, result: 150.5 }
        ]
      },
      positions: [
        {
          id: 'POS-1',
          type: 'BUY',
          openTime: '2026-04-13T10:00:00.000Z',
          volume: 1.0,
          symbol: 'EURGBP',
          profit: 25.5,
          pips: 5.2
        }
      ],
      balance: 70000,
      isSimulated: true,
      isLive: false,
      volatility: 1.0,
      lastAction: 'LONG',
    }
  },
  equity: 70025.5,
  equityHistory: [
    { equity: 70000, timestamp: '2026-04-12T10:00:00.000Z' },
    { equity: 70025.5, timestamp: '2026-04-13T11:00:00.000Z' }
  ],
  drawdown: 0.5,
  };
});
