import { useEffect, useState } from 'react';
import { CheckCircle2 } from 'lucide-react';
import { useAuthStore } from '../../store/authStore';

export default function UserManagementView() {
  const { authFetch } = useAuthStore();
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadUsers() {
      try {
        setLoading(true);
        const res = await authFetch('/users');
        if (res.ok) {
          const data = await res.json();
          setUsers(data.users || []);
        }
      } catch (err) {
        console.error('Failed to load users', err);
      } finally {
        setLoading(false);
      }
    }
    loadUsers();
  }, []);

  if (loading) {
    return <div className="p-8 text-center text-gray-400 text-sm">Loading user directory...</div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-white tracking-tight">User Management & Dual-Hat Roles</h2>
        <p className="text-xs text-gray-400 mt-1">Manage user app roles, department role assignments, and active statuses</p>
      </div>

      <div className="bg-gray-900 border border-white/10 rounded-xl overflow-hidden shadow-sm">
        <table className="w-full text-left text-xs text-gray-300">
          <thead className="bg-gray-950 text-gray-400 font-semibold border-b border-white/10 uppercase tracking-wider text-[11px]">
            <tr>
              <th className="py-3 px-4">User</th>
              <th className="py-3 px-4">Email</th>
              <th className="py-3 px-4">App Role</th>
              <th className="py-3 px-4">Assigned Dept Roles</th>
              <th className="py-3 px-4 text-right">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {users.map((u) => (
              <tr key={u.id} className="hover:bg-white/5 transition-colors">
                <td className="py-3 px-4 font-medium text-white flex items-center gap-2">
                  <div className="w-6 h-6 rounded-full bg-indigo-600 flex items-center justify-center text-[10px] font-bold text-white">
                    {u.name?.[0] ?? 'U'}
                  </div>
                  {u.name}
                </td>
                <td className="py-3 px-4 text-gray-400">{u.email}</td>
                <td className="py-3 px-4">
                  <span
                    className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase ${
                      u.app_role === 'admin'
                        ? 'bg-violet-500/15 text-violet-300 border border-violet-500/25'
                        : u.app_role === 'agent'
                        ? 'bg-blue-500/15 text-blue-300 border border-blue-500/25'
                        : 'bg-gray-800 text-gray-300'
                    }`}
                  >
                    {u.app_role}
                  </span>
                </td>
                <td className="py-3 px-4">
                  <div className="flex flex-wrap gap-1">
                    {(u.dept_roles || []).map((r: string) => (
                      <span key={r} className="px-2 py-0.5 rounded text-[10px] bg-gray-800 text-gray-300">
                        {r}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="py-3 px-4 text-right">
                  <span className="inline-flex items-center gap-1 text-emerald-400 font-medium">
                    <CheckCircle2 size={12} /> Active
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
