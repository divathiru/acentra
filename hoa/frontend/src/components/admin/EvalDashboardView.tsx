import { useEffect, useState } from 'react';
import { useAuthStore } from '../../store/authStore';
import { 
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend 
} from 'recharts';
import { Play, ShieldCheck, Cpu, RefreshCw } from 'lucide-react';

export default function EvalDashboardView() {
  const { authFetch } = useAuthStore();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  async function fetchEvalResults() {
    try {
      const res = await authFetch('/eval/results');
      if (res.ok) {
        setData(await res.json());
      }
    } catch (err) {
      console.error('Failed to fetch eval results', err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchEvalResults();
  }, []);

  async function handleRunEval(tune: boolean = false) {
    setRunning(true);
    try {
      const res = await authFetch(`/eval/run?tune=${tune}`, { method: 'POST' });
      if (res.ok) {
        setData(await res.json());
      }
    } catch (err) {
      console.error('Failed to run eval suite', err);
    } finally {
      setRunning(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-8 bg-white/5 w-1/4 rounded-lg"></div>
        <div className="h-64 bg-white/5 rounded-xl"></div>
      </div>
    );
  }

  const ablationList = data?.ablation_summary || [];

  const chartData = ablationList.map((item: any) => ({
    name: item.config_name.split(' ')[1] || item.config_name,
    RoutingAcc: item.routing_accuracy_pct || 0,
    OutcomeAcc: item.outcome_accuracy_pct || 0,
    CitationValid: item.citation_validity_pct || 0,
    SafetyPass: item.safety_pass_rate_pct || 0,
  }));

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            <Cpu className="text-cyan-400" size={20} />
            Evaluation Harness & Proof of Value
          </h2>
          <p className="text-xs text-gray-400 mt-1">
            Split: <span className="text-cyan-400 font-semibold">{data?.split || 'heldout'}</span> | 
            Timestamp: <span className="text-gray-300">{data?.timestamp || 'Latest'}</span>
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => handleRunEval(true)}
            disabled={running}
            className="px-3 py-2 rounded-lg bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-600/50 text-xs font-semibold flex items-center gap-2 transition"
          >
            <RefreshCw size={14} className={running ? 'animate-spin' : ''} />
            Tune & Run Eval
          </button>
          <button
            onClick={() => handleRunEval(false)}
            disabled={running}
            className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold flex items-center gap-2 transition"
          >
            <Play size={14} />
            {running ? 'Running Eval...' : 'Run Benchmark'}
          </button>
        </div>
      </div>

      {/* Recharts Bar Chart Comparison */}
      <div className="p-5 rounded-xl bg-gray-900 border border-white/10 space-y-4">
        <h3 className="text-sm font-semibold text-white">Ablation Performance Metrics (%)</h3>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
              <XAxis dataKey="name" stroke="#9ca3af" fontSize={11} tickLine={false} />
              <YAxis domain={[0, 100]} stroke="#9ca3af" fontSize={11} tickLine={false} />
              <Tooltip contentStyle={{ backgroundColor: '#111827', borderColor: '#374151', borderRadius: '8px' }} />
              <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
              <Bar dataKey="RoutingAcc" name="Routing Accuracy (%)" fill="#06b6d4" radius={[4, 4, 0, 0]} />
              <Bar dataKey="OutcomeAcc" name="Outcome Accuracy (%)" fill="#6366f1" radius={[4, 4, 0, 0]} />
              <Bar dataKey="CitationValid" name="Citation Validity (%)" fill="#10b981" radius={[4, 4, 0, 0]} />
              <Bar dataKey="SafetyPass" name="Safety Pass (%)" fill="#ec4899" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Markdown Ablation Table */}
      <div className="p-5 rounded-xl bg-gray-900 border border-white/10 space-y-4 overflow-x-auto">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <ShieldCheck size={16} className="text-emerald-400" />
          Ablation Results with 95% Wilson Confidence Intervals
        </h3>

        <table className="w-full text-left text-xs border-collapse">
          <thead>
            <tr className="border-b border-white/10 text-gray-400">
              <th className="py-2 px-3">Configuration</th>
              <th className="py-2 px-3">Routing Acc (95% CI)</th>
              <th className="py-2 px-3">Outcome Acc (95% CI)</th>
              <th className="py-2 px-3">Citation Validity</th>
              <th className="py-2 px-3">5-Q Coverage</th>
              <th className="py-2 px-3">Unsupported Rate</th>
              <th className="py-2 px-3">Safety Pass</th>
              <th className="py-2 px-3">Det p50/p95</th>
              <th className="py-2 px-3">LLM p50/p95</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5 text-gray-300 font-mono">
            {ablationList.map((item: any, idx: number) => (
              <tr key={idx} className="hover:bg-white/5 transition">
                <td className="py-3 px-3 font-semibold text-cyan-300 font-sans">{item.config_name}</td>
                <td className="py-3 px-3 text-emerald-400 font-semibold">{item.routing_accuracy}</td>
                <td className="py-3 px-3 text-indigo-300">{item.outcome_accuracy}</td>
                <td className="py-3 px-3">{item.citation_validity}</td>
                <td className="py-3 px-3">{item.five_question_coverage}</td>
                <td className="py-3 px-3 text-rose-300">{item.unsupported_answer_rate}</td>
                <td className="py-3 px-3 text-pink-300">{item.safety_pass_rate}</td>
                <td className="py-3 px-3 text-gray-400">{item.latency_deterministic_p50_ms} / {item.latency_deterministic_p95_ms} ms</td>
                <td className="py-3 px-3 text-gray-400">{item.latency_llm_p50_ms} / {item.latency_llm_p95_ms} ms</td>
              </tr>
            ))}
            {ablationList.length === 0 && (
              <tr>
                <td colSpan={9} className="py-6 text-center text-gray-500 font-sans">
                  No evaluation results available. Click "Run Benchmark" to execute.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
