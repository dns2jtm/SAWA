"use client";
import React from 'react';
import dynamic from 'next/dynamic';
import type { Data, Layout } from 'plotly.js';

// Dynamically import Plotly to avoid SSR "window is not defined" errors
const Plot = dynamic(() => import('react-plotly.js'), { ssr: false });

export type EquityPoint = {
  timestamp: string;
  equity: number;
};

export default function EquityChart({ history }: { history: EquityPoint[] }) {
  if (!history || history.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500">
        [ Waiting for Live WebSocket Data ]
      </div>
    );
  }

  const times = history.map(h => h.timestamp);
  const equities = history.map(h => h.equity);

  const plotData: Data[] = [
    {
      x: times,
      y: equities,
      type: 'scatter',
      mode: 'lines',
      name: 'Equity',
      line: { color: '#00e1ff', width: 3, shape: 'spline' },
      fill: 'tozeroy',
      fillcolor: 'rgba(0, 225, 255, 0.1)',
    }
  ];

  const plotLayout: Partial<Layout> = {
    autosize: true,
    margin: { l: 60, r: 20, t: 10, b: 40 },
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: '#8a9fc2' },
    xaxis: {
      showgrid: true,
      gridcolor: 'rgba(255, 255, 255, 0.05)',
      zeroline: false,
    },
    yaxis: {
      title: { text: 'Equity (GBP)' },
      showgrid: true,
      gridcolor: 'rgba(255, 255, 255, 0.05)',
      zeroline: true,
      zerolinecolor: 'rgba(255, 255, 255, 0.1)',
      tickprefix: '£',
    },
    hovermode: 'x unified',
  };

  return (
    <div className="w-full h-full min-h-[300px]">
      <Plot
        data={plotData}
        layout={plotLayout}
        useResizeHandler={true}
        style={{ width: '100%', height: '100%' }}
        config={{ displayModeBar: false, responsive: true }}
      />
    </div>
  );
}
