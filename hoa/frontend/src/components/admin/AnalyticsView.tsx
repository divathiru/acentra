import { useEffect, useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { useAuthStore } from '../../store/authStore';

const COLORS = ['#6366f1', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#06b6d4'];

export default function AnalyticsView() {
  const { authFetch } = useAuthStore();
  const [summary, setSummary] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      try {
        const res = await authFetch('/analytics/summary');
        if (res.ok) setSummary(await res.json());
      } catch (err) {
        console.error('Failed to load analytics summary', err);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  if (loading) {
    return <div className="p-8 text-center text-gray-400 text-sm">Loading analytics summary...</div>;
  }

  const outcomeData = Object.entries(summary?.outcome_breakdown || {}).map(([name, value]) => ({
    name,
    count: value,
  }));

  const confidenceData = Object.entries(summary?.confidence_band_breakdown || {}).map(([name, value]) => ({
    name,
    count: value,
  }));

  const stageData = Object.entries(summary?.stage_latency_averages || {}).map(([name, value]) => ({
    name: name.replace('_ms', ''),
    ms: value,
  }));

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-white tracking-tight">System Performance & Analytics</h2>
        <p className="text-xs text-gray-400 mt-1">Aggregated interaction telemetry, confidence distribution, stage latencies</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Outcome Breakdown */}
        <div className="p-5 rounded-xl bg-gray-900 border border-white/10 space-y-4">
          <h3 className="text-sm font-semibold text-white">Interactions by Decision Outcome</h3>
          <div className="h-60 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={outcomeData}>
                <XAxis dataKey="name" stroke="#6b7280" fontSize={11} />
                <YAxis stroke="#6b7280" fontSize={11} />
                <Tooltip contentStyle={{ backgroundColor: '#111827', borderColor: '#374151', color: '#fff' }} />
                <Bar dataKey="count" fill="#6366f1" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Confidence Band Distribution */}
        <div className="p-5 rounded-xl bg-gray-900 border border-white/10 space-y-4">
          <h3 className="text-sm font-semibold text-white">Confidence Band Distribution</h3>
          <div className="h-60 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={confidenceData}>
                <XAxis dataKey="name" stroke="#6b7280" fontSize={11} />
                <YAxis stroke="#6b7280" fontSize={11} />
                <Tooltip contentStyle={{ backgroundColor: '#111827', borderColor: '#374151', color: '#fff' }} />
                <Bar dataKey="count" fill="#10b981" radius={[4, 4, 0, 0]}>
                  {confidenceData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Stage Latencies */}
        <div className="p-5 rounded-xl bg-gray-900 border border-white/10 space-y-4 lg:col-span-2">
          <h3 className="text-sm font-semibold text-white">Average Latency per Pipeline Stage (ms)</h3>
          <div className="h-60 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stageData}>
                <XAxis dataKey="name" stroke="#6b7280" fontSize={11} />
                <YAxis stroke="#6b7280" fontSize={11} />
                <Tooltip contentStyle={{ backgroundColor: '#111827', borderColor: '#374151', color: '#fff' }} />
                <Bar dataKey="ms" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}
