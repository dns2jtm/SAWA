"use client";
import React from 'react';
import type { Data, Layout } from 'plotly.js';

// Dynamically import Plotly to avoid SSR "window is not defined" errors
import Plot from '@/components/PlotComponent';

type Metric = { 
  step: number; 
  pass_rate: number; 
  avg_pnl_pct: number;
  total_breach: number;
  daily_breach: number;
  sharpe: number;
  avg_days: number;
};

// Helper for Simple Moving Average to smooth highly volatile lines
const calculateSMA = (data: number[], windowSize: number): number[] => {
  const result: number[] = [];
  for (let i = 0; i < data.length; i++) {
    const start = Math.max(0, i - windowSize + 1);
    const subset = data.slice(start, i + 1);
    const sum = subset.reduce((a, b) => a + b, 0);
    result.push(sum / subset.length);
  }
  return result;
};

export default function MetricsChart({ history, metricType = 'primary' }: { history: Metric[], metricType?: 'primary' | 'secondary' }) {
  if (!history || history.length === 0) {
    return (
      <div className="flex items-center justify-center w-full h-full text-slate-500 font-mono text-sm border border-white/5 rounded-lg bg-black/10">
        [ Waiting for Live WebSocket Data ]
      </div>
    );
  }

  const steps = history.map(m => m.step);

  let plotData: Data[] = [];
  let plotLayout: Partial<Layout> = {
    autosize: true,
    margin: { l: 50, r: 50, t: 10, b: 30 },
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: '#8b9bb4', family: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace' },
    showlegend: true,
    legend: {
      orientation: 'h',
      y: 1.1,
      x: 0,
      font: { size: 11 }
    }
  };

  if (metricType === 'primary') {
    const passRates = history.map(m => (m.pass_rate || 0) * 100);
    const avgPnl = history.map(m => (m.avg_pnl_pct || 0) * 100);

    plotData = [
      {
        x: steps,
        y: avgPnl,
        type: 'scatter',
        mode: 'lines',
        name: 'Avg PnL (%)',
        line: { color: '#00e1ff', width: 2 },
        yaxis: 'y2',
      },
      {
        x: steps,
        y: passRates,
        type: 'scatter',
        mode: 'lines',
        name: 'Pass Rate (%)',
        line: { color: '#00ff88', width: 2.5 },
        fill: 'tozeroy',
        fillcolor: 'rgba(0, 255, 136, 0.05)',
        yaxis: 'y',
      }
    ];

    plotLayout = {
      ...plotLayout,
      xaxis: {
        showgrid: true,
        gridcolor: 'rgba(255, 255, 255, 0.03)',
        zeroline: false,
        tickfont: { size: 10 }
      },
      yaxis: {
        title: { text: 'Pass Rate (%)', font: { size: 11, color: '#00ff88' } },
        showgrid: true,
        gridcolor: 'rgba(255, 255, 255, 0.03)',
        zeroline: false,
        range: [0, 100],
        tickfont: { size: 10 }
      },
      yaxis2: {
        title: { text: 'Avg PnL (%)', font: { size: 11, color: '#00e1ff' } },
        overlaying: 'y',
        side: 'right',
        showgrid: false,
        zeroline: true,
        zerolinecolor: 'rgba(255, 255, 255, 0.1)',
        tickfont: { size: 10 }
      },
    };
  } else {
    // Secondary Chart (Breaches - Smoothed)
    const rawTotalBreach = history.map(m => (m.total_breach || 0) * 100);
    const rawDailyBreach = history.map(m => (m.daily_breach || 0) * 100);
    
    // Apply a 5-step moving average to smooth out the chaotic volatility
    const smoothTotalBreach = calculateSMA(rawTotalBreach, 5);
    const smoothDailyBreach = calculateSMA(rawDailyBreach, 5);

    plotData = [
      {
        x: steps,
        y: smoothTotalBreach,
        type: 'scatter',
        mode: 'lines',
        name: 'Total Breach (%) - Smoothed',
        line: { color: 'rgba(255, 68, 68, 0.7)', width: 1.5 },
        yaxis: 'y',
      },
      {
        x: steps,
        y: smoothDailyBreach,
        type: 'scatter',
        mode: 'lines',
        name: 'Daily Breach (%) - Smoothed',
        line: { color: 'rgba(255, 170, 0, 0.7)', width: 1.5 },
        yaxis: 'y',
      }
    ];

    plotLayout = {
      ...plotLayout,
      margin: { l: 50, r: 50, t: 10, b: 30 },
      xaxis: {
        showgrid: true,
        gridcolor: 'rgba(255, 255, 255, 0.03)',
        zeroline: false,
        tickfont: { size: 10 }
      },
      yaxis: {
        title: { text: 'Breach Rate (%)', font: { size: 11, color: '#ff4444' } },
        showgrid: true,
        gridcolor: 'rgba(255, 255, 255, 0.03)',
        zeroline: true,
        zerolinecolor: 'rgba(255, 255, 255, 0.1)',
        tickfont: { size: 10 }
      }
    };
  }

  return (
    <Plot
      data={plotData}
      layout={plotLayout}
      useResizeHandler={true}
      style={{ width: '100%', height: '100%' }}
      config={{ displayModeBar: false, responsive: true }}
    />
  );
}
