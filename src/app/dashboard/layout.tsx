"use client";
import { usePathname } from 'next/navigation';
import Link from 'next/link';
import { Activity, Cpu, Briefcase, FlaskConical, Settings, LogOut } from 'lucide-react';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex h-screen bg-[#0a0e17] text-[#f0f4f8] overflow-hidden">
      <aside className="w-[260px] flex flex-col p-6 bg-[#141923]/60 border-r border-white/5">
        <div className="text-2xl font-black tracking-tight bg-gradient-to-r from-cyan-400 to-emerald-400 bg-clip-text text-transparent mb-10">SAWA</div>
        <nav className="flex flex-col gap-2 h-full">
          {[
            { href: '/dashboard', label: 'Overview', icon: <Activity className="w-4 h-4" /> },
            { href: '/dashboard/agents', label: 'Active Agents', icon: <Cpu className="w-4 h-4" /> },
            { href: '/dashboard/portfolio', label: 'Portfolio', icon: <Briefcase className="w-4 h-4" /> },
            { href: '/dashboard/strategy', label: 'Strategy Lab', icon: <FlaskConical className="w-4 h-4" /> },
            { href: '/dashboard/settings', label: 'Settings', icon: <Settings className="w-4 h-4" /> },
          ].map(link => (
            <Link 
              key={link.label}
              href={link.href} 
              className={`flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
                pathname === link.href ? 'bg-emerald-500/10 text-emerald-400' : 'text-slate-400 hover:bg-emerald-500/10 hover:text-emerald-400'
              }`}
            >
              {link.icon}
              {link.label}
            </Link>
          ))}
          
          <button 
            onClick={() => {
              try { localStorage.removeItem('sawa_auth_token'); } catch {}
              window.location.href = '/login';
            }}
            className="mt-auto flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium text-slate-400 hover:bg-emerald-500/10 hover:text-emerald-400 transition-colors text-left"
          >
            <LogOut className="w-4 h-4" />
            Logout
          </button>
        </nav>
      </aside>
      
      <main className="flex-1 p-8 overflow-y-auto bg-[radial-gradient(circle_at_50%_0%,rgba(0,225,255,0.05)_0%,transparent_50%)]">
        {children}
      </main>
    </div>
  );
}
