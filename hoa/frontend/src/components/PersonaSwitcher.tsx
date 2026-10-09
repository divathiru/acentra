/**
 * PersonaSwitcher — shows a badge + dropdown for employees with multiple dept roles.
 * Only renders if the user has >1 dept role.
 */

import { useState } from 'react';
import { ChevronDown, RefreshCw } from 'lucide-react';
import { useAuthStore } from '../store/authStore';

export default function PersonaSwitcher() {
  const { me, claims, switchPersona } = useAuthStore();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Only show for users with multiple dept roles
  if (!me || me.dept_roles.length <= 1) return null;

  const activeDept = claims?.active_dept_role ?? me.dept_roles[0];

  const handleSwitch = async (role: string) => {
    if (role === activeDept) { setOpen(false); return; }
    setLoading(true);
    setError(null);
    try {
      await switchPersona(role);
      setOpen(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to switch');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        disabled={loading}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-indigo-600/20 border border-indigo-500/40 
                   text-indigo-200 text-sm font-medium hover:bg-indigo-600/30 transition-all duration-200
                   disabled:opacity-50 disabled:cursor-not-allowed"
        aria-label="Switch active role"
      >
        {loading ? (
          <RefreshCw size={14} className="animate-spin" />
        ) : (
          <span className="w-2 h-2 rounded-full bg-indigo-400 animate-pulse" />
        )}
        <span className="max-w-[140px] truncate">{activeDept}</span>
        <ChevronDown
          size={14}
          className={`transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div className="absolute right-0 mt-2 min-w-[180px] z-50 rounded-xl border border-white/10 
                        bg-gray-900/95 backdrop-blur-sm shadow-xl shadow-black/40 overflow-hidden">
          <div className="px-3 py-2 text-xs text-gray-500 font-semibold uppercase tracking-wider border-b border-white/5">
            Switch Role
          </div>
          {me.dept_roles.map((role) => (
            <button
              key={role}
              onClick={() => handleSwitch(role)}
              className={`w-full text-left px-4 py-2.5 text-sm transition-colors duration-150
                ${role === activeDept
                  ? 'bg-indigo-600/20 text-indigo-300 font-medium'
                  : 'text-gray-300 hover:bg-white/5 hover:text-white'
                }`}
            >
              <span className="flex items-center gap-2">
                {role === activeDept && (
                  <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 flex-shrink-0" />
                )}
                <span className={role === activeDept ? '' : 'pl-3.5'}>{role}</span>
              </span>
            </button>
          ))}
        </div>
      )}

      {error && (
        <p className="absolute top-full mt-1 right-0 text-xs text-red-400 whitespace-nowrap">
          {error}
        </p>
      )}
    </div>
  );
}
