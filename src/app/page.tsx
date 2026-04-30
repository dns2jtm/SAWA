import Link from 'next/link';
import { Layers, Rocket, Shield, Activity } from "lucide-react";

export default function Home() {
  return (
    <main className="min-h-screen bg-[#0a0e17] text-[#f0f4f8] overflow-hidden selection:bg-cyan-500/30 font-sans">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
        
        {/* Navigation */}
        <nav className="flex items-center justify-between py-6 border-b border-white/5">
          <div className="text-2xl font-black tracking-tight bg-gradient-to-r from-cyan-400 to-emerald-400 bg-clip-text text-transparent">
            SAWA
          </div>
          <div className="hidden md:flex gap-8 text-sm font-medium text-slate-300">
            <a href="#features" className="hover:text-cyan-400 transition-colors">Technology</a>
            <a href="#pricing" className="hover:text-cyan-400 transition-colors">Pricing</a>
          </div>
          <Link 
            href="/dashboard" 
            className="bg-gradient-to-r from-cyan-400 to-emerald-400 text-black px-5 py-2.5 rounded-lg text-sm font-bold shadow-[0_0_20px_rgba(0,255,136,0.1)] hover:shadow-[0_0_25px_rgba(0,255,136,0.3)] transition-all hover:-translate-y-0.5"
          >
            Connect Account
          </Link>
        </nav>

        {/* Hero Section */}
        <section className="py-24 md:py-32 flex flex-col items-center text-center relative">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-cyan-500/20 blur-[120px] rounded-full pointer-events-none" />
          
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 text-xs font-bold tracking-widest uppercase mb-8">
            <Rocket className="w-3.5 h-3.5" />
            <span>Algorithm Level 5 Absolute Autonomy</span>
          </div>
          
          <h1 className="text-5xl md:text-7xl font-black tracking-tight mb-8 leading-[1.1]">
            Institutional RL Trading, <br />
            <span className="bg-gradient-to-r from-cyan-400 to-emerald-400 bg-clip-text text-transparent glow-text">
              Now Fully Autonomous.
            </span>
          </h1>
          
          <p className="text-lg md:text-xl text-slate-400 max-w-2xl mb-12 leading-relaxed">
            Deploy our A100-trained Proximal Policy Optimization agent directly to your MT5 prop-firm account. Zero human emotion, 100% mathematical precision.
          </p>
          
          <Link 
            href="/dashboard" 
            className="group relative inline-flex items-center justify-center gap-2 bg-gradient-to-r from-cyan-400 to-emerald-400 text-black px-8 py-4 rounded-xl text-lg font-bold shadow-[0_0_30px_rgba(0,255,136,0.2)] hover:shadow-[0_0_40px_rgba(0,255,136,0.4)] transition-all hover:-translate-y-1"
          >
            Deploy Agent Now
            <Activity className="w-5 h-5 group-hover:animate-pulse" />
          </Link>

          {/* Stats Bar */}
          <div className="flex flex-wrap justify-center gap-8 md:gap-16 mt-20 pt-10 border-t border-white/5">
            {[
              { value: "82.4%", label: "Phase 1 Pass Rate" },
              { value: "2.14", label: "Sharpe Ratio" },
              { value: "0ms", label: "Execution Latency" }
            ].map(stat => (
              <div key={stat.label} className="text-center group">
                <div className="text-4xl font-black text-white mb-2 group-hover:text-cyan-400 transition-colors">{stat.value}</div>
                <div className="text-sm font-medium text-slate-500 uppercase tracking-wider">{stat.label}</div>
              </div>
            ))}
          </div>

          <div className="mt-24 w-full max-w-5xl rounded-2xl border border-white/10 border-t-white/20 bg-[#141923]/60 backdrop-blur-xl p-4 shadow-[0_30px_100px_rgba(0,0,0,0.9)] animate-float">
            <div className="rounded-xl overflow-hidden bg-black/80 relative aspect-[16/9] flex items-center justify-center border border-white/5 shadow-inner">
              <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(0,225,255,0.05)_0%,transparent_70%)]" />
              <div className="text-center z-10">
                <Activity className="w-12 h-12 text-cyan-400 mx-auto mb-4 animate-pulse opacity-70 drop-shadow-[0_0_15px_rgba(0,225,255,0.5)]" />
                <p className="text-slate-400 font-mono text-sm tracking-widest uppercase">Systematic Dashboards Initialize After Login</p>
              </div>
            </div>
          </div>
        </section>

        {/* Features Section */}
        <section id="features" className="py-24 border-t border-white/5">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-black tracking-tight mb-4">Unfair Advantage via Compute</h2>
            <p className="text-slate-400 max-w-2xl mx-auto">Standard indicators fail in modern markets. SAWA relies entirely on massive compute, continuous agent reinforcement, and live regime modeling.</p>
          </div>
          
          <div className="grid md:grid-cols-3 gap-6">
            {[
              {
                icon: <Layers className="w-8 h-8 text-cyan-400" />,
                title: "GMM Regime Detection",
                desc: "Our agent clusters market data in real-time, instantly adjusting risk profiles between trending, ranging, and crisis market regimes."
              },
              {
                icon: <Shield className="w-8 h-8 text-emerald-400" />,
                title: "Tick-Level Drawdown",
                desc: "Trained to respect strict prop-firm equity rules. The AI models intra-bar excursions to guarantee it never breaches daily loss limits."
              },
              {
                icon: <Activity className="w-8 h-8 text-purple-400" />,
                title: "Zero Lookahead",
                desc: "Strictly causal multi-timeframe feature shifting ensures the agent's historical backtests perfectly match live MT5 forward-testing."
              }
            ].map(f => (
              <div key={f.title} className="bg-[#141923]/40 border border-white/5 p-8 rounded-2xl hover:bg-white/[0.02] hover:border-white/10 transition-colors">
                <div className="bg-black/30 w-14 h-14 rounded-xl flex items-center justify-center mb-6 border border-white/5">
                  {f.icon}
                </div>
                <h3 className="text-xl font-bold mb-3">{f.title}</h3>
                <p className="text-slate-400 leading-relaxed text-sm">{f.desc}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Pricing Section */}
        <section id="pricing" className="py-24 border-t border-white/5">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-black tracking-tight mb-4">Prop Firm Scaling Plans</h2>
            <p className="text-slate-400">Fixed costs. No hidden profit splits. Pure programmatic edge.</p>
          </div>
          
          <div className="grid md:grid-cols-2 gap-8 max-w-4xl mx-auto">
            {/* Plan 1 */}
            <div className="bg-[#141923]/40 border border-white/5 p-10 rounded-3xl flex flex-col hover:border-white/10 transition-colors">
              <h3 className="text-2xl font-bold mb-2">Challenge Pass</h3>
              <div className="mb-6 flex items-baseline gap-2">
                <span className="text-5xl font-black">$499</span>
                <span className="text-slate-500">/ account</span>
              </div>
              <ul className="space-y-4 mb-10 flex-1 text-slate-300">
                <li className="flex items-center gap-3"><span className="text-emerald-400">✓</span> Automated Phase 1 & 2</li>
                <li className="flex items-center gap-3"><span className="text-emerald-400">✓</span> $100k - $200k accounts</li>
                <li className="flex items-center gap-3"><span className="text-emerald-400">✓</span> Max 30-day timeline</li>
                <li className="flex items-center gap-3"><span className="text-emerald-400">✓</span> Full refund on failure</li>
              </ul>
              <a href="#" className="w-full text-center bg-white/5 hover:bg-white/10 border border-white/10 text-white py-4 rounded-xl font-bold transition-colors">Select Plan</a>
            </div>
            
            {/* Plan 2 */}
            <div className="bg-gradient-to-b from-[#141923] to-black border border-cyan-500/30 p-10 rounded-3xl flex flex-col relative overflow-hidden shadow-[0_0_50px_rgba(0,225,255,0.1)] hover:shadow-[0_0_80px_rgba(0,225,255,0.2)] transition-shadow">
              <div className="absolute top-0 inset-x-0 h-1 bg-gradient-to-r from-cyan-400 to-emerald-400" />
              <div className="absolute top-6 right-6 bg-cyan-500/10 text-cyan-400 text-xs font-bold px-3 py-1 rounded-full border border-cyan-500/20">Most Popular</div>
              
              <h3 className="text-2xl font-bold mb-2">Funded Master</h3>
              <div className="mb-6 flex items-baseline gap-2">
                <span className="text-5xl font-black text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-emerald-400">$999</span>
                <span className="text-slate-500">/ month</span>
              </div>
              <ul className="space-y-4 mb-10 flex-1 text-slate-300">
                <li className="flex items-center gap-3"><span className="text-cyan-400">⚡</span> Live Funded auto-trading</li>
                <li className="flex items-center gap-3"><span className="text-cyan-400">⚡</span> Dynamic compounding sizing</li>
                <li className="flex items-center gap-3"><span className="text-cyan-400">⚡</span> Dedicated VPS instance</li>
                <li className="flex items-center gap-3"><span className="text-cyan-400">⚡</span> Direct 24/7 Slack support</li>
              </ul>
              <a href="/dashboard" className="w-full text-center bg-gradient-to-r from-cyan-400 to-emerald-400 text-black py-4 rounded-xl font-bold hover:-translate-y-1 transition-transform shadow-[0_10px_20px_rgba(0,255,136,0.2)]">Start Scaling Now</a>
            </div>
          </div>
        </section>

      </div>
    </main>
  );
}
