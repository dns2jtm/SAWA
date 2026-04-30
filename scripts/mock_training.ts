import fs from 'fs';
import path from 'path';

const LOGS_DIR = path.join(process.cwd(), 'models', 'logs');

if (!fs.existsSync(LOGS_DIR)) {
  fs.mkdirSync(LOGS_DIR, { recursive: true });
}

const RUN_ID = new Date().toISOString().replace(/[:.]/g, '-');
const logFile = path.join(LOGS_DIR, `ftmo_metrics_${RUN_ID}.jsonl`);

console.log(`Starting mock RL training...\nLogging to ${logFile}`);

let step = 0;
const totalSteps = 10000000;
const evalFreq = 100000;

function generateMetrics(currentStep: number) {
  // Simulated organic improvement
  const progress = currentStep / totalSteps;
  
  // Base metrics that improve over time
  const pass_rate = Math.min(0.85, 0.05 + progress * 0.8 + (Math.random() * 0.1 - 0.05));
  const daily_breach = Math.max(0.05, 0.4 - progress * 0.35 + (Math.random() * 0.05));
  const total_breach = Math.max(0.05, 0.3 - progress * 0.25 + (Math.random() * 0.05));
  
  // Avg PnL improves from negative to positive target (10%)
  const avg_pnl_pct = -0.05 + progress * 0.2 + (Math.random() * 0.02 - 0.01);
  const avg_trades = 10 + progress * 15 + Math.random() * 5;
  const avg_days = 25 - progress * 10 + Math.random() * 2;
  const active_episode_fraction = 0.95 + Math.random() * 0.05;
  
  // Sharpe improves
  const sharpe = -1.0 + progress * 3.5 + (Math.random() * 0.2 - 0.1);

  return {
    step: currentStep,
    pass_rate: Number(pass_rate.toFixed(3)),
    daily_breach: Number(daily_breach.toFixed(3)),
    total_breach: Number(total_breach.toFixed(3)),
    avg_pnl_pct: Number(avg_pnl_pct.toFixed(4)),
    avg_trades: Number(avg_trades.toFixed(1)),
    avg_days: Number(avg_days.toFixed(1)),
    active_episode_fraction: Number(active_episode_fraction.toFixed(3)),
    sharpe: Number(sharpe.toFixed(3)),
    n_episodes: 200
  };
}

const interval = setInterval(() => {
  step += evalFreq;
  
  const metrics = generateMetrics(step);
  fs.appendFileSync(logFile, JSON.stringify(metrics) + '\n');
  
  console.log(`[Step ${step}] Pass Rate: ${(metrics.pass_rate * 100).toFixed(1)}% | Sharpe: ${metrics.sharpe.toFixed(2)} | PnL: ${(metrics.avg_pnl_pct * 100).toFixed(1)}%`);
  
  if (step >= totalSteps) {
    clearInterval(interval);
    console.log('Mock training completed.');
  }
}, 1000); // 1 mock update per second
