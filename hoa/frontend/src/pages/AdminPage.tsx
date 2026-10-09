/**
 * Admin page — wraps all admin sub-sections.
 * Permission-gated at component level (adminOnly guard in App.tsx).
 * Individual sections further gated by specific permissions.
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { LogOut, LayoutDashboard, Ticket, BookOpen, BarChart2, Shield, Users, Settings, ChevronRight } from 'lucide-react';
import { useAuthStore, hasPerm } from '../store/authStore';
import PersonaSwitcher from '../components/PersonaSwitcher';

const NAV_ITEMS = [
  { label: 'Dashboard',    icon: LayoutDashboard, perm: null              },
  { label: 'Tickets',      icon: Ticket,          perm: 'tickets:read'    },
  { label: 'Knowledge',    icon: BookOpen,         perm: 'knowledge:read'  },
  { label: 'Analytics',    icon: BarChart2,        perm: 'analytics:read'  },
  { label: 'Audit',        icon: Shield,           perm: 'audit:read'      },
  { label: 'Users',        icon: Users,            perm: 'users:manage'    },
  { label: 'System',       icon: Settings,         perm: 'system:manage'   },
] as const;

export default function AdminPage() {
  const { me, claims, logout } = useAuthStore();
  const navigate = useNavigate();
  const [active, setActive] = useState('Dashboard');

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  const visibleItems = NAV_ITEMS.filter(item =>
    item.perm === null || hasPerm(claims, item.perm)
  );

  return (
    <div className="min-h-screen bg-gray-950 flex">
      {/* Sidebar */}
      <aside className="w-56 flex-shrink-0 border-r border-white/5 bg-gray-900/50 backdrop-blur-sm flex flex-col">
        {/* Brand */}
        <div className="px-5 py-5 border-b border-white/5">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center flex-shrink-0">
              <LayoutDashboard size={14} className="text-white" />
            </div>
            <span className="text-white font-semibold text-sm">HOA Admin</span>
          </div>
          <div className="mt-2 px-0.5">
            <span className={`inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full font-medium
              ${claims?.app_role === 'admin'
                ? 'bg-violet-500/15 text-violet-300 border border-violet-500/25'
                : 'bg-blue-500/15 text-blue-300 border border-blue-500/25'
              }`}>
              <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
              {claims?.app_role}
            </span>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 py-3 space-y-0.5 px-2">
          {visibleItems.map(({ label, icon: Icon }) => (
            <button
              key={label}
              onClick={() => setActive(label)}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium
                transition-all duration-150 group
                ${active === label
                  ? 'bg-indigo-600/20 text-indigo-300'
                  : 'text-gray-500 hover:text-gray-200 hover:bg-white/5'
                }`}
            >
              <Icon size={15} className="flex-shrink-0" />
              {label}
              {active === label && (
                <ChevronRight size={12} className="ml-auto text-indigo-400" />
              )}
            </button>
          ))}
        </nav>

        {/* User footer */}
        <div className="px-3 py-3 border-t border-white/5 space-y-2">
          <PersonaSwitcher />
          <div className="flex items-center gap-2 px-2">
            <div className="w-7 h-7 rounded-full bg-indigo-600 flex items-center justify-center text-xs font-bold text-white flex-shrink-0">
              {me?.name?.[0] ?? '?'}
            </div>
            <div className="min-w-0">
              <p className="text-white text-xs font-medium truncate">{me?.name ?? '…'}</p>
              <p className="text-gray-500 text-xs truncate">{me?.email ?? ''}</p>
            </div>
            <button onClick={handleLogout} title="Sign out" className="ml-auto p-1 text-gray-600 hover:text-gray-300">
              <LogOut size={13} />
            </button>
          </div>
        </div>
      </aside>

      {/* Content area */}
      <main className="flex-1 p-8 overflow-auto">
        <div className="max-w-5xl mx-auto">
          <h1 className="text-2xl font-bold text-white mb-2">{active}</h1>
          <p className="text-gray-500 text-sm mb-8">Admin · {claims?.app_role}</p>

          <div className="rounded-2xl border border-white/5 bg-white/3 backdrop-blur-sm p-12 text-center">
            <p className="text-gray-500 text-sm">{active} panel coming in the next task iteration.</p>
          </div>
        </div>
      </main>
    </div>
  );
}
