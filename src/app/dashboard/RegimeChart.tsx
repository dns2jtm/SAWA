"use client";
import React, { useEffect, useState } from 'react';

import Plot from '@/components/PlotComponent';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:8000';
const POLL_MS = 5 * 60 * 1000;   // refresh every 5 minutes

interface RegimeData {
  labels: string[];
  values: number[];
  n_bars?: number;
  error?: string;
}

export default function RegimeChart() {
  const [data, setData] = useState<RegimeData>({
    labels: ['Trending', 'Ranging', 'Volatile'],
    values: [33.3, 33.3, 33.4],
  });

  useEffect(() => {
    const fetchRegime = () => {
      fetch(`${BACKEND}/api/regime`)
        .then(r => r.json())
        .then((d: RegimeData) => setData(d))
        .catch(() => {/* keep previous data on error */});
    };
    fetchRegime();
    const id = setInterval(fetchRegime, POLL_MS);
    return () => clearInterval(id);
  }, []);

  return (
    <Plot
      data={[
        {
          x: data.labels,
          y: data.values,
          type: 'bar',
          marker: {
            color: ['#00ff88', '#3498db', '#e74c3c'],
            opacity: 0.8,
            line: { color: 'rgba(255, 255, 255, 0.1)', width: 1 },
          },
        }
      ]}
      layout={{
        autosize: true,
        height: 250,
        margin: { l: 40, r: 20, t: 10, b: 30 },
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: { color: '#8b9bb4' },
        xaxis: { showgrid: false, zeroline: false },
        yaxis: {
          title: { text: 'Distribution (%)' },
          showgrid: true,
          gridcolor: 'rgba(255, 255, 255, 0.05)',
          zeroline: false,
          range: [0, 100],
        },
      }}
      useResizeHandler={true}
      style={{ width: '100%', height: '100%' }}
      config={{ displayModeBar: false }}
    />
  );
}
