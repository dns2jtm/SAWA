import React from 'react';
import { ArrowLeft } from 'lucide-react';
import Link from 'next/link';

export default function DocsPage() {
  return (
    <div className="max-w-4xl mx-auto py-8 animate-in fade-in duration-500 text-slate-300">
      <Link href="/dashboard" className="flex items-center gap-2 text-blue-400 hover:text-blue-300 mb-8 transition-colors w-fit">
        <ArrowLeft className="w-4 h-4" /> Back to Dashboard
      </Link>
      
      <h1 className="text-4xl font-black text-white mb-2 tracking-tight">Metrics Documentation</h1>
      <p className="text-slate-500 mb-12">In-depth explanations of the RL training pipeline metrics and dashboard components.</p>

      <div className="space-y-12">
        <section id="latest-step" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-white mb-3">Latest Step</h2>
          <p className="leading-relaxed">
            The total number of simulated environment steps processed so far across all parallel workers.
            In PPO, a "step" represents one single action taken by the agent in one environment (i.e. one 1-hour bar of market data).
          </p>
        </section>

        <section id="pass-rate" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-emerald-400 mb-3">Pass Rate</h2>
          <p className="leading-relaxed">
            The percentage of trading episodes where the agent successfully hit the FTMO profit target (usually 10%) 
            without ever violating the daily or total drawdown rules.
          </p>
        </section>

        <section id="avg-pnl" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-white mb-3">Average PnL (%)</h2>
          <p className="leading-relaxed">
            The average simulated profit or loss percentage across the last sample window (e.g. 200 episodes).
            This is a pure return metric.
          </p>
        </section>

        <section id="sharpe-ratio" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-white mb-3">Sharpe Ratio</h2>
          <p className="leading-relaxed">
            A risk-adjusted return metric. It takes the mean return and divides it by the standard deviation of returns. 
            A higher Sharpe ratio indicates a smoother, more consistent upward equity curve with less volatility.
          </p>
        </section>

        <section id="total-breach" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-rose-400 mb-3">Total Breach</h2>
          <p className="leading-relaxed">
            The percentage of episodes where the agent lost enough money to violate the maximum total drawdown rule.
          </p>
        </section>
        
        <section id="daily-breach" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-orange-400 mb-3">Daily Breach</h2>
          <p className="leading-relaxed">
            The percentage of episodes where the agent violated the maximum daily drawdown rule within a single 24-hour period.
          </p>
        </section>
        
        <section id="std" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-rose-400 mb-3">Train / Std Dev</h2>
          <p className="leading-relaxed">
            The standard deviation of the action distribution. High initial exploration (`std`) reduces as the agent learns.
          </p>
        </section>

        <section id="equity-chart" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-white mb-3">EquityChart</h2>
          <p className="leading-relaxed">
            Renders the portfolio equity curve over time, showing performance across episodes.
          </p>
        </section>

        <section id="metrics-chart" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-white mb-3">MetricsChart</h2>
          <p className="leading-relaxed">
            Displays FTMO training metrics including pass rates, average PnL, daily and total breach percentages.
          </p>
        </section>

        <section id="regime-chart" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-white mb-3">RegimeChart</h2>
          <p className="leading-relaxed">
            Shows market regime classification (e.g., bull, bear) across the training period.
          </p>
        </section>

        <section id="agents-page" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-white mb-3">Agents Page</h2>
          <p className="leading-relaxed">
            Lists all active trading agents and their current training or evaluation status.
          </p>
        </section>

        <section id="portfolio-page" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-white mb-3">Portfolio Page</h2>
          <p className="leading-relaxed">
            Summarizes portfolio allocation and performance statistics for selected assets.
          </p>
        </section>

        <section id="strategy-page" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-white mb-3">Strategy Page</h2>
          <p className="leading-relaxed">
            Details backtested strategies, their parameters, and performance comparisons.
          </p>
        </section>

        <section id="settings-page" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-white mb-3">Settings Page</h2>
          <p className="leading-relaxed">
            Provides dashboard configuration options, environment variables, and feature toggles.
          </p>
        </section>

        <section id="kl-divergence" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-white mb-3">KL Divergence</h2>
          <p className="leading-relaxed">
            Measures how much the current policy distribution diverges from the previous policy, indicating the extent of policy updates each training step.
          </p>
        </section>

        <section id="entropy-loss" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-white mb-3">Entropy Loss</h2>
          <p className="leading-relaxed">
            Quantifies the randomness of the policy’s action selection; higher entropy encourages exploration, and decreasing entropy signals convergence toward deterministic actions.
          </p>
        </section>

        <section id="value-loss" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-white mb-3">Value Loss</h2>
          <p className="leading-relaxed">
            The loss between predicted value estimates and actual discounted returns; lower value loss indicates more accurate state-value predictions.
          </p>
        </section>

        <section id="final-pnl-pct" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-emerald-400 mb-3">Final PnL (%)</h2>
          <p className="leading-relaxed">
            The percentage change in account equity at the end of an episode, calculated as (final equity – initial equity) / initial equity * 100.
          </p>
        </section>

        <section id="total-episodes" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-white mb-3">Total Episodes</h2>
          <p className="leading-relaxed">
            The total number of completed training episodes in the current run, where each episode resets environment state.
          </p>
        </section>

        <section id="active-episode-fraction" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-white mb-3">Active Episode Fraction</h2>
          <p className="leading-relaxed">
            The ratio of episodes in which the agent has taken at least one action versus total episodes, indicating exploration engagement.
          </p>
        </section>

        <section id="avg-trades" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-white mb-3">Average Trades</h2>
          <p className="leading-relaxed">
            The mean number of trades executed per episode, reflecting trading activity level.
          </p>
        </section>

        <section id="trading-days" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-white mb-3">Trading Days</h2>
          <p className="leading-relaxed">
            The average number of days each episode spans, based on market calendar days, indicating episode duration.
          </p>
        </section>
      </div>
    </div>
  );
}