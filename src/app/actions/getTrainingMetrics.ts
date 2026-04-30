'use server';

import fs from 'fs';
import path from 'path';

export async function getTrainingMetrics() {
  const logsDir = path.join(process.cwd(), 'models', 'logs');
  
  if (!fs.existsSync(logsDir)) {
    return [];
  }

  const files = fs.readdirSync(logsDir);
  const metricsFiles = files.filter(f => f.startsWith('ftmo_metrics_') && f.endsWith('.jsonl'));
  
  if (metricsFiles.length === 0) {
    return [];
  }

  // Get the most recently created (or modified) file
  const latestFile = metricsFiles
    .map(name => ({ name, time: fs.statSync(path.join(logsDir, name)).mtime.getTime() }))
    .sort((a, b) => b.time - a.time)[0].name;

  const filePath = path.join(logsDir, latestFile);
  const fileContent = fs.readFileSync(filePath, 'utf-8');
  
  const lines = fileContent.trim().split('\n');
  const metrics = [];
  
  for (const line of lines) {
    if (!line) continue;
    try {
      metrics.push(JSON.parse(line));
    } catch {
      console.error("Failed to parse log line:", line);
    }
  }

  return metrics;
}
