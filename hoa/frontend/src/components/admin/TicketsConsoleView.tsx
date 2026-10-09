import { useEffect, useState } from 'react';
import { UserCheck, CheckCircle2, ShieldAlert } from 'lucide-react';
import { useAuthStore } from '../../store/authStore';

export default function TicketsConsoleView() {
  const { authFetch } = useAuthStore();
  const [tickets, setTickets] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedTicket, setSelectedTicket] = useState<any>(null);
  const [ticketEvents, setTicketEvents] = useState<any[]>([]);

  const [teamFilter, setTeamFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [resolutionNote, setResolutionNote] = useState('');
  const [reassignTeam, setReassignTeam] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);

  const loadTickets = async () => {
    try {
      setLoading(true);
      let url = '/console/tickets?limit=100';
      if (teamFilter) url += `&team=${encodeURIComponent(teamFilter)}`;
      if (statusFilter) url += `&status=${encodeURIComponent(statusFilter)}`;

      const res = await authFetch(url);
      if (res.ok) {
        const data = await res.json();
        setTickets(data.tickets || []);
      }
    } catch (err) {
      console.error('Failed to load tickets', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTickets();
  }, [teamFilter, statusFilter]);

  const openTicketDetail = async (ticket: any) => {
    setSelectedTicket(ticket);
    setActionError(null);
    try {
      const res = await authFetch(`/console/tickets/${ticket.id}`);
      if (res.ok) {
        const data = await res.json();
        setTicketEvents(data.events || []);
      }
    } catch (err) {
      console.error('Failed to load ticket events', err);
    }
  };

  const handleAction = async (action: 'claim' | 'reassign' | 'resolve') => {
    setActionError(null);
    try {
      const body: any = { action };
      if (action === 'reassign') body.new_team = reassignTeam;
      if (action === 'resolve') body.resolution_note = resolutionNote;

      const res = await authFetch(`/console/tickets/${selectedTicket.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Action failed');
      }

      await loadTickets();
      setSelectedTicket(null);
      setResolutionNote('');
    } catch (err: any) {
      setActionError(err.message);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight">Routing & Tickets Console</h2>
          <p className="text-xs text-gray-400 mt-1">Manage, claim, and resolve operational tickets with Separation of Duties</p>
        </div>

        <div className="flex items-center gap-3">
          <select
            value={teamFilter}
            onChange={(e) => setTeamFilter(e.target.value)}
            className="bg-gray-900 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none"
          >
            <option value="">All Teams</option>
            <option value="Billing Operations">Billing Operations</option>
            <option value="Billing Supervisor">Billing Supervisor</option>
            <option value="Insurance/TPA">Insurance/TPA</option>
            <option value="Laboratory">Laboratory</option>
            <option value="IT">IT</option>
            <option value="Department Operations Head">Department Operations Head</option>
          </select>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-gray-900 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none"
          >
            <option value="">All Statuses</option>
            <option value="open">Open</option>
            <option value="in_progress">In Progress</option>
            <option value="resolved">Resolved</option>
          </select>
        </div>
      </div>

      {/* Tickets List Table */}
      <div className="bg-gray-900 border border-white/10 rounded-xl overflow-hidden shadow-sm">
        <table className="w-full text-left text-xs text-gray-300">
          <thead className="bg-gray-950 text-gray-400 font-semibold border-b border-white/10 uppercase tracking-wider text-[11px]">
            <tr>
              <th className="py-3 px-4">Urgency</th>
              <th className="py-3 px-4">Team</th>
              <th className="py-3 px-4">Reason</th>
              <th className="py-3 px-4">Status</th>
              <th className="py-3 px-4">Summary</th>
              <th className="py-3 px-4 text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {tickets.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-8 text-center text-gray-500">
                  {loading ? 'Loading tickets...' : 'No tickets found matching filters.'}
                </td>
              </tr>
            ) : (
              tickets.map((t) => (
                <tr key={t.id} className="hover:bg-white/5 transition-colors">
                  <td className="py-3 px-4">
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${
                        t.urgency === 'urgent'
                          ? 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                          : t.urgency === 'high'
                          ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30'
                          : 'bg-blue-500/15 text-blue-400 border border-blue-500/30'
                      }`}
                    >
                      {t.urgency}
                    </span>
                  </td>
                  <td className="py-3 px-4 font-medium text-white">{t.team}</td>
                  <td className="py-3 px-4 text-gray-400">{t.reason}</td>
                  <td className="py-3 px-4">
                    <span
                      className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-medium capitalize ${
                        t.status === 'open'
                          ? 'bg-amber-500/10 text-amber-400'
                          : t.status === 'in_progress'
                          ? 'bg-indigo-500/10 text-indigo-400'
                          : 'bg-emerald-500/10 text-emerald-400'
                      }`}
                    >
                      {t.status.replace('_', ' ')}
                    </span>
                  </td>
                  <td className="py-3 px-4 max-w-xs truncate text-gray-300">{t.summary}</td>
                  <td className="py-3 px-4 text-right">
                    <button
                      onClick={() => openTicketDetail(t)}
                      className="px-3 py-1 rounded bg-indigo-600/20 hover:bg-indigo-600/40 text-indigo-300 font-medium text-xs transition-all"
                    >
                      View
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Ticket Action Modal */}
      {selectedTicket && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-gray-900 border border-white/10 rounded-2xl max-w-xl w-full p-6 space-y-5 shadow-2xl">
            <div className="flex justify-between items-start">
              <div>
                <span className="text-xs text-indigo-400 font-semibold uppercase">{selectedTicket.team}</span>
                <h3 className="text-lg font-bold text-white mt-0.5">{selectedTicket.summary}</h3>
                <p className="text-xs text-gray-400 mt-1">Ticket ID: {selectedTicket.id}</p>
              </div>
              <button onClick={() => setSelectedTicket(null)} className="text-gray-400 hover:text-white">✕</button>
            </div>

            {actionError && (
              <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-xs text-rose-300 flex items-center gap-2">
                <ShieldAlert size={16} />
                <span>{actionError}</span>
              </div>
            )}

            {/* Events Timeline */}
            {ticketEvents.length > 0 && (
              <div className="space-y-1.5 pt-2 border-t border-white/10">
                <p className="text-xs font-semibold text-gray-400">Event History:</p>
                <div className="max-h-32 overflow-y-auto space-y-1">
                  {ticketEvents.map((ev: any) => (
                    <div key={ev.id} className="text-[11px] text-gray-400 flex justify-between bg-gray-950 p-1.5 rounded">
                      <span className="font-semibold text-indigo-300">{ev.event_type}</span>
                      <span>{ev.created_at?.slice(0, 19)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Ticket Actions */}
            <div className="space-y-3 pt-2">
              {selectedTicket.status === 'open' && (
                <button
                  onClick={() => handleAction('claim')}
                  className="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs flex items-center justify-center gap-2 shadow"
                >
                  <UserCheck size={15} />
                  Claim Ticket
                </button>
              )}

              {selectedTicket.status !== 'resolved' && (
                <div className="space-y-3 pt-2 border-t border-white/10">
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={reassignTeam}
                      onChange={(e) => setReassignTeam(e.target.value)}
                      placeholder="New Team Name"
                      className="flex-1 bg-gray-950 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-white"
                    />
                    <button
                      onClick={() => handleAction('reassign')}
                      disabled={!reassignTeam.trim()}
                      className="px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-white font-semibold text-xs disabled:opacity-50"
                    >
                      Reassign
                    </button>
                  </div>

                  <textarea
                    value={resolutionNote}
                    onChange={(e) => setResolutionNote(e.target.value)}
                    placeholder="Enter resolution notes..."
                    rows={2}
                    className="w-full bg-gray-950 border border-white/10 rounded-xl p-3 text-xs text-white focus:outline-none focus:border-indigo-500"
                  />
                  <button
                    onClick={() => handleAction('resolve')}
                    disabled={!resolutionNote.trim()}
                    className="w-full py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white font-semibold text-xs flex items-center justify-center gap-2 shadow"
                  >
                    <CheckCircle2 size={15} />
                    Resolve Ticket
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
