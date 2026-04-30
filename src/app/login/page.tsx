"use client";
import { useState } from 'react';
import Link from 'next/link';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    // Simulate network request
    await new Promise(resolve => setTimeout(resolve, 800));

    if (email && password) {
      try {
        localStorage.setItem('sawa_auth_token', 'mock_jwt_token_12345');
      } catch {
        console.warn("Storage access denied in iframe, bypassing");
      }
      try {
        document.cookie = "sawa_auth_token=mock_jwt_token_12345; path=/; max-age=86400; SameSite=Lax";
      } catch {
        console.warn("Cookie access denied in iframe, bypassing");
      }
      
      window.location.href = '/dashboard';
    } else {
      setError('Please enter your credentials.');
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-[#0a0e17] flex flex-col items-center justify-center p-6 text-[#f0f4f8] bg-[radial-gradient(circle_at_50%_0%,rgba(0,255,136,0.05)_0%,transparent_50%)] relative">
      <Link href="/" className="absolute top-8 left-8 text-slate-400 font-medium hover:text-white transition-colors">
        ← Back to Home
      </Link>
      
      <div className="w-full max-w-md bg-[#141923]/60 border border-white/5 p-10 rounded-2xl backdrop-blur-md shadow-[0_20px_80px_rgba(0,0,0,0.6)]">
        <div className="text-3xl font-black tracking-tight text-center bg-gradient-to-r from-cyan-400 to-emerald-400 bg-clip-text text-transparent mb-2">SAWA</div>
        <p className="text-center text-slate-400 text-sm mb-8">Systematic Algorithmic Wealth Architecture</p>
        
        {error && <div className="bg-red-500/10 border border-red-500/20 text-red-400 px-4 py-3 rounded-lg text-sm mb-6 text-center">{error}</div>}
        
        <form onSubmit={handleLogin} className="space-y-5">
          <div className="space-y-2">
            <label htmlFor="email" className="block text-sm font-medium text-slate-300">Email Address</label>
            <input 
              id="email"
              type="email" 
              className="w-full bg-black/20 border border-white/10 rounded-lg px-4 py-3 text-white placeholder:text-slate-600 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/50 transition-all font-mono" 
              placeholder="admin@sawa.ai"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          
          <div className="space-y-2">
            <label htmlFor="password" className="block text-sm font-medium text-slate-300">Password</label>
            <input 
              id="password"
              type="password" 
              className="w-full bg-black/20 border border-white/10 rounded-lg px-4 py-3 text-white placeholder:text-slate-600 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/50 transition-all font-mono" 
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
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
