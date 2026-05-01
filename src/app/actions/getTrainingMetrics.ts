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

  // Sort files chronologically so we can merge all training runs
  const sortedFiles = metricsFiles
    .map(name => ({ name, time: fs.statSync(path.join(logsDir, name)).mtime.getTime() }))
    .sort((a, b) => a.time - b.time); // Oldest to newest

  const metrics = [];
  const seenSteps = new Set();
  
  for (const fileObj of sortedFiles) {
    const filePath = path.join(logsDir, fileObj.name);
    const fileContent = fs.readFileSync(filePath, 'utf-8');
    const lines = fileContent.trim().split('\n');
    
    for (const line of lines) {
      if (!line) continue;
      try {
        const parsed = JSON.parse(line);
        // Only add if we haven't seen this exact step (handles overlaps during resume)
        if (parsed.step !== undefined && !seenSteps.has(parsed.step)) {
          seenSteps.add(parsed.step);
          metrics.push(parsed);
        }
      } catch {
        console.error("Failed to parse log line:", line);
      }
    }
  }

  // Ensure they are strictly sorted by step
  metrics.sort((a, b) => a.step - b.step);

  return metrics;
}
