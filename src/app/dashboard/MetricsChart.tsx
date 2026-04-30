"use client";
import React from 'react';
import dynamic from 'next/dynamic';
import type { Data, Layout } from 'plotly.js';

// Dynamically import Plotly to avoid SSR "window is not defined" errors
const Plot = dynamic(() => import('react-plotly.js'), { ssr: false });

type Metric = { step: number; pass_rate: number; avg_pnl_pct: number };

export default function MetricsChart({ history }: { history: Metric[] }) {
  if (!history || history.length === 0) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px', color: 'var(--text-muted)' }}>
        [ Waiting for Live WebSocket Data ]
      </div>
    );
  }

  const steps = history.map(m => m.step);
  const passRates = history.map(m => m.pass_rate * 100);
  const avgPnl = history.map(m => m.avg_pnl_pct * 100);

  const plotData: Data[] = [
    {
      x: steps,
      y: passRates,
      type: 'scatter',
      mode: 'lines',
      name: 'Pass Rate (%)',
      line: { color: '#00ff88', width: 2 },
      fill: 'tozeroy',
      fillcolor: 'rgba(0, 255, 136, 0.1)',
    },
    {
      x: steps,
      y: avgPnl,
      type: 'scatter',
      mode: 'lines',
      name: 'Avg PnL (%)',
      line: { color: '#00e1ff', width: 2 },
      yaxis: 'y2',
    }
  ];

  const plotLayout: Partial<Layout> = {
    autosize: true,
    height: 250,
    margin: { l: 40, r: 40, t: 10, b: 30 },
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: '#8b9bb4' },
    xaxis: {
      showgrid: true,
      gridcolor: 'rgba(255, 255, 255, 0.05)',
      zeroline: false,
    },
    yaxis: {
      title: 'Pass Rate (%)',
      showgrid: true,
      gridcolor: 'rgba(255, 255, 255, 0.05)',
      zeroline: false,
      range: [0, 100],
    },
    yaxis2: {
      title: 'Avg PnL (%)',
      overlaying: 'y',
      side: 'right',
      showgrid: false,
      zeroline: true,
      zerolinecolor: 'rgba(255, 255, 255, 0.1)',
    },
    legend: {
      orientation: 'h',
      y: 1.1,
      x: 0,
    }
  };

  return (
    <Plot
      data={plotData}
      layout={plotLayout}
      useResizeHandler={true}
      style={{ width: '100%', height: '100%' }}
      config={{ displayModeBar: false }}
    />
  );
}
