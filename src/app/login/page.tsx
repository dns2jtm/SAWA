"use client";
import { useState } from 'react';
import Link from 'next/link';
import { login } from '@/app/actions/auth';

export default function Login() {
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleLogin = async (formData: FormData) => {
    setLoading(true);
    setError('');

    const result = await login(formData);

    if (result?.error) {
      setError(result.error);
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-[#242424] flex flex-col items-center justify-center p-6 text-[#f0f4f8] bg-[radial-gradient(circle_at_50%_0%,rgba(0,255,136,0.05)_0%,transparent_50%)] relative">
      <Link href="/" className="absolute top-8 left-8 text-slate-400 font-medium hover:text-white transition-colors">
        ← Back to Home
      </Link>
      
      <div className="w-full max-w-md bg-[#141923]/60 border border-white/5 p-10 rounded-2xl backdrop-blur-md shadow-[0_20px_80px_rgba(0,0,0,0.6)]">
        <div className="text-3xl font-black tracking-tight text-center bg-gradient-to-r from-cyan-400 to-emerald-400 bg-clip-text text-transparent mb-2">SAWA</div>
        <p className="text-center text-slate-400 text-sm mb-8">Systematic Algorithmic Wealth Architecture</p>
        
        {error && <div className="bg-red-500/10 border border-red-500/20 text-red-400 px-4 py-3 rounded-lg text-sm mb-6 text-center">{error}</div>}
        
        <form action={handleLogin} className="space-y-5">
          <div className="space-y-2">
            <label htmlFor="email" className="block text-sm font-medium text-slate-300">Email Address</label>
            <input 
              id="email"
              name="email"
              type="email" 
              className="w-full bg-black/20 border border-white/10 rounded-lg px-4 py-3 text-white placeholder:text-slate-600 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/50 transition-all font-mono" 
              placeholder="admin@sawa.ai"
              required
            />
          </div>
          
          <div className="space-y-2">
            <label htmlFor="password" className="block text-sm font-medium text-slate-300">Password</label>
            <input 
              id="password"
              name="password"
              type="password" 
              className="w-full bg-black/20 border border-white/10 rounded-lg px-4 py-3 text-white placeholder:text-slate-600 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/50 transition-all font-mono" 
              placeholder="••••••••"
              required
            />
          </div>
          
          <button type="submit" className="w-full bg-gradient-to-r from-cyan-400 to-emerald-400 text-black font-bold py-3 rounded-lg hover:translate-y-[-2px] hover:shadow-[0_10px_25px_rgba(0,255,136,0.2)] transition-all disabled:opacity-70 disabled:hover:translate-y-0" disabled={loading}>
            {loading ? 'Authenticating...' : 'Sign In to Dashboard'}
          </button>
        </form>
      </div>
    </main>
  );
}
