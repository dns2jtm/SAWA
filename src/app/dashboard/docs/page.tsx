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
      <p className="text-slate-500 mb-12">In-depth explanations of the RL training pipeline metrics.</p>

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
            The percentage of episodes where the agent lost enough money to violate the maximum total drawdown rule 
            (e.g., losing 10% of the initial balance).
          </p>
        </section>
        
        <section id="daily-breach" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-orange-400 mb-3">Daily Breach</h2>
          <p className="leading-relaxed">
            The percentage of episodes where the agent violated the maximum daily drawdown rule 
            (e.g., losing 5% of the starting daily equity within a single 24-hour period).
          </p>
        </section>
        
        <section id="std" className="scroll-mt-24">
          <h2 className="text-2xl font-bold text-rose-400 mb-3">Train / Std Dev</h2>
          <p className="leading-relaxed">
            The standard deviation of the continuous action distribution. When an RL agent first starts learning, it explores 
            the environment randomly, which is represented by a high `std`. As it discovers profitable strategies, it becomes 
            more confident and deterministic, and the `std` should mathematically collapse towards 0.
          </p>
        </section>
        
        {/* Additional sections can be built out here */}
        <section className="p-6 bg-blue-500/10 border border-blue-500/20 rounded-xl mt-8">
          <h3 className="text-blue-400 font-bold mb-2">More metrics coming soon</h3>
          <p className="text-sm text-blue-400/80">Additional deep learning statistics (KL divergence, Entropy Loss, etc.) will be documented here shortly.</p>
        </section>
      </div>
    </div>
  );
}
