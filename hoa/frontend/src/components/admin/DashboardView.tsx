import { useEffect, useState } from 'react';
import { useAuthStore } from '../../store/authStore';
import { 
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, 
  LineChart, Line, PieChart, Pie, Cell, CartesianGrid 
} from 'recharts';
import { Activity, ShieldCheck, CheckCircle, Clock, Inbox } from 'lucide-react';

const COLORS = ['#6366f1', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#06b6d4'];

export default function DashboardView() {
  const { authFetch } = useAuthStore();
  const [summary, setSummary] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      try {
        const [sumRes, healthRes] = await Promise.all([
          authFetch('/analytics/summary'),
          fetch('/readyz'),
        ]);

        if (sumRes.ok) setSummary(await sumRes.json());
        if (healthRes.ok) setHealth(await healthRes.json());
      } catch (err) {
        console.error('Failed to load dashboard data', err);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  if (loading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-8 bg-white/5 w-1/4 rounded-lg"></div>
        <div className="grid grid-cols-2 lg:grid-cols-6 gap-4">
          {[...Array(6)].map((_, i) => <div key={i} className="h-24 bg-white/5 rounded-xl"></div>)}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="h-64 bg-white/5 rounded-xl"></div>
          <div className="h-64 bg-white/5 rounded-xl"></div>
        </div>
      </div>
    );
  }

  // Formatting Data for Charts
  const avgConfidence = summary?.total_interactions > 0
    ? ((summary.confidence_band_breakdown?.HIGH || 0) / summary.total_interactions) * 100
    : 0;

  const queriesPerDay = Object.entries(summary?.queries_per_day || {}).map(([date, count]) => ({
    date: new Date(date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
    Queries: count,
  }));

  const outcomeData = Object.entries(summary?.outcome_breakdown || {}).map(([name, count]) => ({
    name, value: count
  }));

  const deptData = Object.entries(summary?.queries_by_dept_role || {}).map(([name, count]) => ({
    name, count
  }));

  const topWorkflows = Object.entries(summary?.top_workflows || {})
    .sort(([, a], [, b]) => (b as number) - (a as number))
    .slice(0, 5);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-white tracking-tight">Overview</h2>
        <p className="text-xs text-gray-400 mt-1">Real-time system telemetry and operational metrics</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-6 gap-4">
        <KpiCard title="Queries" value={summary?.total_interactions ?? 0} icon={Activity} color="text-indigo-400" bg="bg-indigo-600/20" />
        <KpiCard title="Deflection" value={`${summary?.deflection_rate ?? 0}%`} icon={ShieldCheck} color="text-emerald-400" bg="bg-emerald-600/20" />
        <KpiCard title="High Conf." value={`${Math.round(avgConfidence)}%`} icon={CheckCircle} color="text-violet-400" bg="bg-violet-600/20" />
        <KpiCard title="Citation Val." value={`${summary?.citation_validity_rate ?? 0}%`} icon={CheckCircle} color="text-blue-400" bg="bg-blue-600/20" />
        <KpiCard title="p95 Latency" value={`${summary?.p95_latency_llm ?? 0}ms`} icon={Clock} color="text-pink-400" bg="bg-pink-600/20" />
        <KpiCard title="Open Tickets" value={summary?.open_tickets ?? 0} icon={Inbox} color="text-amber-400" bg="bg-amber-600/20" />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Line Chart: Queries/Day */}
        <div className="p-5 rounded-xl bg-gray-900 border border-white/10 lg:col-span-2 space-y-4">
          <h3 className="text-sm font-semibold text-white">Queries / Day</h3>
          <div className="h-60">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={queriesPerDay}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
                <XAxis dataKey="date" stroke="#9ca3af" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke="#9ca3af" fontSize={11} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={{ backgroundColor: '#111827', borderColor: '#374151', borderRadius: '8px' }} />
                <Line type="monotone" dataKey="Queries" stroke="#06b6d4" strokeWidth={2} dot={false} activeDot={{ r: 6 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Donut Chart: Outcome Mix */}
        <div className="p-5 rounded-xl bg-gray-900 border border-white/10 space-y-4">
          <h3 className="text-sm font-semibold text-white">Outcome Mix</h3>
          <div className="h-60">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={outcomeData} cx="50%" cy="50%" innerRadius={60} outerRadius={80} paddingAngle={5} dataKey="value">
                  {outcomeData.map((_, index) => <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />)}
                </Pie>
                <Tooltip contentStyle={{ backgroundColor: '#111827', borderColor: '#374151', borderRadius: '8px' }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Bar Chart: Department */}
        <div className="p-5 rounded-xl bg-gray-900 border border-white/10 space-y-4">
          <h3 className="text-sm font-semibold text-white">Queries by Department</h3>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={deptData} layout="vertical" margin={{ left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" horizontal={false} />
                <XAxis type="number" stroke="#9ca3af" fontSize={11} hide />
                <YAxis dataKey="name" type="category" stroke="#9ca3af" fontSize={11} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={{ backgroundColor: '#111827', borderColor: '#374151', borderRadius: '8px' }} />
                <Bar dataKey="count" fill="#6366f1" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Top Workflows */}
        <div className="p-5 rounded-xl bg-gray-900 border border-white/10 space-y-4">
          <h3 className="text-sm font-semibold text-white">Top Workflows</h3>
          <div className="space-y-3">
            {topWorkflows.map(([w, c]) => (
              <div key={String(w)} className="flex items-center justify-between p-2 rounded-lg bg-white/5 border border-white/5">
                <span className="text-xs text-gray-300 truncate font-medium">{String(w)}</span>
                <span className="text-xs font-bold text-indigo-400">{String(c)}</span>
              </div>
            ))}
            {topWorkflows.length === 0 && <div className="text-xs text-gray-500 py-4 text-center">No workflow data</div>}
          </div>
        </div>

        {/* System Health */}
        <div className="p-5 rounded-xl bg-gray-900 border border-white/10 space-y-4">
          <h3 className="text-sm font-semibold text-white flex items-center gap-2">
            <Activity size={16} className="text-emerald-400" />
            System Health
          </h3>
          <div className="space-y-3">
            <HealthRow label="Database" status={health?.checks?.db === 'ok' ? 'Online' : 'Error'} isOk={health?.checks?.db === 'ok'} />
            <HealthRow label="Graph Active" status={health?.checks?.active_graph === 'ok' ? 'Yes' : 'No'} isOk={health?.checks?.active_graph === 'ok'} />
            <HealthRow label="LLM Mode Shares" status="" isOk={true} />
            <div className="pl-4 text-[11px] space-y-1">
              {Object.entries(summary?.mode_breakdown || {}).map(([mode, count]) => (
                <div key={mode} className="flex justify-between text-gray-400">
                  <span className="uppercase">{mode}</span>
                  <span className="text-white font-medium">{String(count)} calls</span>
                </div>
              ))}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}

function KpiCard({ title, value, icon: Icon, color, bg }: any) {
  return (
    <div className="p-4 rounded-xl bg-gray-900 border border-white/10 flex flex-col gap-3 relative overflow-hidden">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium text-gray-400 uppercase tracking-wider">{title}</span>
        <div className={`w-7 h-7 rounded-lg ${bg} ${color} flex items-center justify-center`}>
          <Icon size={14} />
        </div>
      </div>
      <p className="text-2xl font-bold text-white tracking-tight">{value}</p>
    </div>
  );
}

function HealthRow({ label, status, isOk }: any) {
  return (
    <div className="flex items-center justify-between p-2 rounded-lg bg-white/5 border border-white/5">
      <span className="text-xs font-medium text-gray-300">{label}</span>
      <div className="flex items-center gap-1.5">
        {status && <span className={`text-[10px] font-bold uppercase ${isOk ? 'text-emerald-400' : 'text-rose-400'}`}>{status}</span>}
        {status && <div className={`w-1.5 h-1.5 rounded-full ${isOk ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'}`} />}
      </div>
    </div>
  );
}
