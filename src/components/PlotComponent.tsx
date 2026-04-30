"use client";
import React from 'react';
import dynamic from 'next/dynamic';

const PlotComponent = dynamic(async () => {
    // We import plotly.js-dist-min to avoid the window.fetch TypeError
    // caused by standard plotly.js whatwg-fetch polyfills
    // @ts-expect-error No types for dist-min
    const Plotly = await import('plotly.js-dist-min');
    
    // We can safely load the factory without an ignore ignore because types exist
    const createPlotlyComponent = (await import('react-plotly.js/factory')).default;
    return createPlotlyComponent(Plotly);
}, { ssr: false });

export default PlotComponent;
