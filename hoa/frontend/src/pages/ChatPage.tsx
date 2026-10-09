/**
 * Chat page stub — employee home.
 * Will be fleshed out in TASK 4.
 */

import { useNavigate } from 'react-router-dom';
import { LogOut, MessageSquare } from 'lucide-react';
import { useAuthStore } from '../store/authStore';
import PersonaSwitcher from '../components/PersonaSwitcher';

export default function ChatPage() {
  const { me, claims, logout } = useAuthStore();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <div className="min-h-screen bg-gray-950 flex flex-col">
      {/* Top bar */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-white/5 bg-gray-900/50 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center">
            <MessageSquare size={16} className="text-white" />
          </div>
          <span className="text-white font-semibold text-sm">HOA Chat</span>
        </div>

        <div className="flex items-center gap-3">
          <PersonaSwitcher />

          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-full bg-indigo-600 flex items-center justify-center text-xs font-bold text-white">
              {me?.name?.[0] ?? '?'}
            </div>
            <span className="text-gray-300 text-sm hidden sm:block">
              {me?.name ?? claims?.active_dept_role}
            </span>
          </div>

          <button
            onClick={handleLogout}
            title="Sign out"
            className="p-2 rounded-lg text-gray-500 hover:text-gray-200 hover:bg-white/5 transition-colors"
          >
            <LogOut size={16} />
          </button>
        </div>
      </header>

      {/* Chat area placeholder */}
      <main className="flex-1 flex items-center justify-center p-8">
        <div className="text-center">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-indigo-600/10 border border-indigo-500/20 mb-4">
            <MessageSquare size={28} className="text-indigo-400" />
          </div>
          <h2 className="text-xl font-semibold text-white mb-2">Healthcare Operations Chat</h2>
          <p className="text-gray-400 text-sm max-w-sm">
            Ask operational questions, get guided through workflows, or route issues to the right team.
          </p>
          <p className="text-gray-600 text-xs mt-4">Chat interface coming in TASK 4</p>
        </div>
      </main>
    </div>
  );
}
