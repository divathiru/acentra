import { useEffect, useState } from 'react';
import { Power, Sliders } from 'lucide-react';
import { useAuthStore } from '../../store/authStore';

export default function SystemSettingsView() {
  const { authFetch } = useAuthStore();
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  const loadSettings = async () => {
    try {
      setLoading(true);
      const res = await authFetch('/admin/settings');
      if (res.ok) {
        const data = await res.json();
        setSettings(data.settings || {});
      }
    } catch (err) {
      console.error('Failed to load settings', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSettings();
  }, []);

  const updateSetting = async (key: string, value: string) => {
    try {
      const res = await authFetch('/admin/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, value }),
      });

      if (res.ok) {
        setMessage(`Setting '${key}' updated to '${value}'`);
        setSettings((prev) => ({ ...prev, [key]: value }));
      }
    } catch (err) {
      console.error('Failed to update setting', err);
    }
  };

  if (loading) {
    return <div className="p-8 text-center text-gray-400 text-sm">Loading system configuration...</div>;
  }

  const llmEnabled = settings.llm_enabled === 'true';

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-white tracking-tight">System Controls & Settings</h2>
        <p className="text-xs text-gray-400 mt-1">Admin emergency kill switches, confidence thresholds, and model configurations</p>
      </div>

      {message && (
        <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-300 flex items-center justify-between">
          <span>{message}</span>
          <button onClick={() => setMessage(null)} className="text-emerald-400">✕</button>
        </div>
      )}

      {/* Emergency Kill Switch Card */}
      <div className={`p-5 rounded-xl border flex items-center justify-between transition-all ${
        llmEnabled ? 'bg-gray-900 border-white/10' : 'bg-amber-950/40 border-amber-500/30'
      }`}>
        <div className="flex items-center gap-4">
          <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${
            llmEnabled ? 'bg-indigo-600/20 text-indigo-400' : 'bg-amber-500/20 text-amber-400 animate-pulse'
          }`}>
            <Power size={24} />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white">LLM Generation Provider Kill Switch</h3>
            <p className="text-xs text-gray-400">
              {llmEnabled
                ? 'LLM responses active via Mistral AI gateway.'
                : 'LLM IS DISABLED! System is running in 100% deterministic template fallback mode.'}
            </p>
          </div>
        </div>

        <button
          onClick={() => updateSetting('llm_enabled', llmEnabled ? 'false' : 'true')}
          className={`px-4 py-2 rounded-xl font-bold text-xs shadow transition-all ${
            llmEnabled
              ? 'bg-rose-600 hover:bg-rose-500 text-white'
              : 'bg-emerald-600 hover:bg-emerald-500 text-white'
          }`}
        >
          {llmEnabled ? 'ENABLE KILL SWITCH (Disable LLM)' : 'RESTORE LLM GENERATION'}
        </button>
      </div>

      {/* Config Form */}
      <div className="p-5 rounded-xl bg-gray-900 border border-white/10 space-y-4">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <Sliders size={16} className="text-indigo-400" />
          Threshold & Model Settings
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-gray-400 block mb-1">Primary LLM Model Tier</label>
            <select
              value={settings.llm_model || 'mistral-small-latest'}
              onChange={(e) => updateSetting('llm_model', e.target.value)}
              className="w-full bg-gray-950 border border-white/10 rounded-lg px-3 py-2 text-xs text-white"
            >
              <option value="mistral-small-latest">mistral-small-latest</option>
              <option value="mistral-medium-latest">mistral-medium-latest</option>
              <option value="mistral-large-latest">mistral-large-latest</option>
            </select>
          </div>

          <div>
            <label className="text-xs text-gray-400 block mb-1">High Confidence Threshold</label>
            <input
              type="text"
              value={settings.high_confidence_threshold || '0.75'}
              onChange={(e) => updateSetting('high_confidence_threshold', e.target.value)}
              className="w-full bg-gray-950 border border-white/10 rounded-lg px-3 py-2 text-xs text-white font-mono"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
