import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { LogOut, LayoutDashboard, Ticket, BookOpen, BarChart2, Shield, Users, Settings, ChevronRight } from 'lucide-react';
import { useAuthStore, hasPerm } from '../store/authStore';
import PersonaSwitcher from '../components/PersonaSwitcher';

import DashboardView from '../components/admin/DashboardView';
import TicketsConsoleView from '../components/admin/TicketsConsoleView';
import KnowledgeManagementView from '../components/admin/KnowledgeManagementView';
import AnalyticsView from '../components/admin/AnalyticsView';
import AuditVerificationView from '../components/admin/AuditVerificationView';
import UserManagementView from '../components/admin/UserManagementView';
import SystemSettingsView from '../components/admin/SystemSettingsView';
import EvalDashboardView from '../components/admin/EvalDashboardView';

const NAV_ITEMS = [
  { label: 'Dashboard', icon: LayoutDashboard, perm: null },
  { label: 'Tickets', icon: Ticket, perm: 'tickets:read' },
  { label: 'Knowledge', icon: BookOpen, perm: 'knowledge:read' },
  { label: 'Analytics', icon: BarChart2, perm: 'analytics:read' },
  { label: 'Eval', icon: BarChart2, perm: null },
  { label: 'Audit', icon: Shield, perm: 'audit:read' },
  { label: 'Users', icon: Users, perm: 'users:manage' },
  { label: 'System', icon: Settings, perm: 'system:manage' },
] as const;


export default function AdminPage() {
  const { me, claims, logout } = useAuthStore();
  const navigate = useNavigate();
  const [active, setActive] = useState('Dashboard');

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  const visibleItems = NAV_ITEMS.filter((item) => item.perm === null || hasPerm(claims, item.perm));

  return (
    <div className="min-h-screen bg-gray-950 flex font-sans text-gray-100">
      {/* Sidebar Navigation */}
      <aside className="w-60 flex-shrink-0 border-r border-white/10 bg-gray-900/60 backdrop-blur-md flex flex-col">
        {/* Brand Header */}
        <div className="px-5 py-5 border-b border-white/10">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-indigo-500 via-violet-600 to-pink-500 flex items-center justify-center flex-shrink-0 shadow-lg shadow-indigo-500/20">
              <LayoutDashboard size={16} className="text-white" />
            </div>
            <div>
              <span className="text-white font-bold text-sm tracking-tight block leading-tight">HOA Admin</span>
              <span className="text-[10px] text-gray-400 leading-tight">Console & Governance</span>
            </div>
          </div>
          <div className="mt-3">
            <span
              className={`inline-flex items-center gap-1.5 text-[11px] px-2.5 py-0.5 rounded-full font-semibold uppercase ${
                claims?.app_role === 'admin'
                  ? 'bg-violet-500/15 text-violet-300 border border-violet-500/30'
                  : 'bg-blue-500/15 text-blue-300 border border-blue-500/30'
              }`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
              {claims?.app_role}
            </span>
          </div>
        </div>

        {/* Navigation Items */}
        <nav className="flex-1 py-4 space-y-1 px-3">
          {visibleItems.map(({ label, icon: Icon }) => (
            <button
              key={label}
              onClick={() => setActive(label)}
              className={`w-full flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all duration-150 group ${
                active === label
                  ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
                  : 'text-gray-400 hover:text-white hover:bg-white/5'
              }`}
            >
              <Icon size={16} className={active === label ? 'text-white' : 'text-gray-400 group-hover:text-white'} />
              <span>{label}</span>
              {active === label && <ChevronRight size={13} className="ml-auto text-indigo-200" />}
            </button>
          ))}
        </nav>

        {/* User Footer */}
        <div className="p-3 border-t border-white/10 space-y-2.5">
          <PersonaSwitcher />
          <div className="flex items-center gap-2.5 px-2">
            <div className="w-7 h-7 rounded-full bg-gradient-to-tr from-indigo-500 to-violet-600 flex items-center justify-center text-xs font-bold text-white flex-shrink-0">
              {me?.name?.[0] ?? '?'}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-white text-xs font-semibold truncate leading-tight">{me?.name ?? '...'}</p>
              <p className="text-gray-400 text-[10px] truncate leading-tight">{me?.email ?? ''}</p>
            </div>
            <button onClick={handleLogout} title="Sign out" className="p-1.5 text-gray-400 hover:text-white rounded-lg hover:bg-white/5">
              <LogOut size={14} />
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content Workspace */}
      <main className="flex-1 overflow-y-auto p-6 md:p-8">
        {active === 'Dashboard' && <DashboardView />}
        {active === 'Tickets' && <TicketsConsoleView />}
        {active === 'Knowledge' && <KnowledgeManagementView />}
        {active === 'Analytics' && <AnalyticsView />}
        {active === 'Eval' && <EvalDashboardView />}
        {active === 'Audit' && <AuditVerificationView />}
        {active === 'Users' && <UserManagementView />}
        {active === 'System' && <SystemSettingsView />}
      </main>
    </div>
  );
}
