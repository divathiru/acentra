import { useEffect, useState } from 'react';
import { ShieldCheck, ShieldAlert, RefreshCw } from 'lucide-react';
import { useAuthStore } from '../../store/authStore';

export default function AuditVerificationView() {
  const { authFetch } = useAuthStore();
  const [logRows, setLogRows] = useState<any[]>([]);
  const [verification, setVerification] = useState<any>(null);
  const [verifying, setVerifying] = useState(false);

  const loadAuditLog = async () => {
    try {
      const res = await authFetch('/audit/log');
      if (res.ok) {
        const data = await res.json();
        setLogRows(data.rows || []);
      }
    } catch (err) {
      console.error('Failed to load audit log', err);
    }
  };

  useEffect(() => {
    loadAuditLog();
  }, []);

  const runVerification = async () => {
    try {
      setVerifying(true);
      const res = await authFetch('/audit/verify');
      if (res.ok) {
        const data = await res.json();
        setVerification(data);
      }
    } catch (err) {
      console.error('Audit verification failed', err);
    } finally {
      setVerifying(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight">Audit Trail & Chain Verification</h2>
          <p className="text-xs text-gray-400 mt-1">Append-only HMAC SHA-256 tamper-evident cryptographic chain log</p>
        </div>

        <button
          onClick={runVerification}
          disabled={verifying}
          className="flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white font-semibold text-xs shadow transition-all"
        >
          <RefreshCw size={14} className={verifying ? 'animate-spin' : ''} />
          <span>Verify Audit Chain Integrity</span>
        </button>
      </div>

      {/* Verification Result Banner */}
      {verification && (
        <div
          className={`p-4 rounded-xl border flex items-center justify-between ${
            verification.ok
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
              : 'bg-rose-500/10 border-rose-500/30 text-rose-300'
          }`}
        >
          <div className="flex items-center gap-3">
            {verification.ok ? <ShieldCheck size={24} className="text-emerald-400" /> : <ShieldAlert size={24} className="text-rose-400" />}
            <div>
              <h3 className="font-bold text-sm">{verification.ok ? 'HMAC Chain Integrity PASSED' : 'HMAC Chain Integrity BROKEN!'}</h3>
              <p className="text-xs opacity-80">
                Verified {verification.rows} entries. {verification.ok ? 'All cryptographic links are valid and unaltered.' : `First broken link at entry ID ${verification.first_bad_id}`}
              </p>
            </div>
          </div>
          <span className="font-mono text-xs font-bold px-3 py-1 rounded-full bg-white/10">
            {verification.ok ? 'OK' : 'TAMPER DETECTED'}
          </span>
        </div>
      )}

      {/* Audit Table */}
      <div className="bg-gray-900 border border-white/10 rounded-xl overflow-hidden shadow-sm">
        <table className="w-full text-left text-xs text-gray-300">
          <thead className="bg-gray-950 text-gray-400 font-semibold border-b border-white/10 uppercase tracking-wider text-[11px]">
            <tr>
              <th className="py-3 px-4">ID</th>
              <th className="py-3 px-4">Event Type</th>
              <th className="py-3 px-4">Payload Summary</th>
              <th className="py-3 px-4">Prev Hash</th>
              <th className="py-3 px-4">HMAC Hash</th>
              <th className="py-3 px-4 text-right">Timestamp</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5 font-mono text-[11px]">
            {logRows.map((r) => (
              <tr key={r.id} className="hover:bg-white/5 transition-colors">
                <td className="py-3 px-4 text-indigo-400 font-bold">{r.id}</td>
                <td className="py-3 px-4 font-sans font-medium text-white">{r.payload?.event_type || 'audit'}</td>
                <td className="py-3 px-4 font-sans max-w-xs truncate text-gray-400">
                  {JSON.stringify(r.payload)}
                </td>
                <td className="py-3 px-4 text-gray-500">{r.payload?.prev_hash ? r.payload.prev_hash.slice(0, 8) + '...' : 'GENESIS'}</td>
                <td className="py-3 px-4 text-emerald-400">{r.hash?.slice(0, 10)}...</td>
                <td className="py-3 px-4 text-right font-sans text-gray-400">{r.created_at?.slice(0, 19)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
