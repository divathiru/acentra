import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  LogOut,
  Send,
  ThumbsUp,
  ThumbsDown,
  Sparkles,
  Shield,
  AlertTriangle,
  FileText,
  Clock,
  ChevronDown,
  ChevronUp,
  RotateCcw,
  CheckCircle2,
  Building2,
} from 'lucide-react';
import { useAuthStore } from '../store/authStore';
import PersonaSwitcher from '../components/PersonaSwitcher';

interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  timestamp: string;
  confidence_band?: 'HIGH' | 'MEDIUM' | 'LOW';
  confidence_score?: number;
  mode?: 'llm' | 'template';
  citations?: string[];
  stage_ms?: Record<string, number>;
  total_ms?: number;
  workflow_action?: {
    state: string;
    prompt_fields?: string[];
    missing_fields?: string[];
    route_team?: string;
    form?: string;
    system?: string;
  };
  feedback?: 'positive' | 'negative';
  interaction_id?: string;
}

const SAMPLE_QUERIES = [
  { label: 'MRI Pre-Authorization', text: 'I need to check pre-authorization requirements for an MRI scan.' },
  { label: 'Discharge Billing Clearance', text: 'Patient is ready for discharge, check total billing clearance.' },
  { label: 'Specimen Rejection', text: 'Lab rejected blood specimen due to hemolysis, what is the protocol?' },
  { label: 'Prior Auth Policy', text: 'What is the prior authorization policy for out-of-network insurers?' },
];

export default function ChatPage() {
  const { me, claims, logout, authFetch } = useAuthStore();
  const navigate = useNavigate();

  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'init-1',
      sender: 'assistant',
      text: `Hello ${me?.name ?? 'there'}! I am your Healthcare Operations Assistant. How can I help you today?`,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    },
  ]);

  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [workflowSlots, setWorkflowSlots] = useState<Record<string, string>>({});
  const [conversationId, setConversationId] = useState<string>(() => `conv_${Date.now()}`);
  const [expandedLatencies, setExpandedLatencies] = useState<Record<string, boolean>>({});

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  const handleSend = async (queryText?: string, extraSlots?: Record<string, string>) => {
    const textToSend = queryText ?? input;
    if (!textToSend.trim() && !extraSlots) return;

    const userMsgId = `usr_${Date.now()}`;
    const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    if (textToSend.trim()) {
      setMessages((prev) => [
        ...prev,
        {
          id: userMsgId,
          sender: 'user',
          text: textToSend,
          timestamp,
        },
      ]);
    }

    setInput('');
    setLoading(true);

    const mergedSlots = { ...workflowSlots, ...(extraSlots ?? {}) };

    try {
      const res = await authFetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: textToSend || 'Continuing workflow',
          conversation_id: conversationId,
          workflow_slots: mergedSlots,
        }),
      });

      if (!res.ok) {
        throw new Error(`Chat request failed with status ${res.status}`);
      }

      const data = await res.json();
      const assistantMsgId = `ast_${Date.now()}`;

      setMessages((prev) => [
        ...prev,
        {
          id: assistantMsgId,
          sender: 'assistant',
          text: data.answer || data.text || 'Process completed.',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          confidence_band: data.confidence_band || data.band,
          confidence_score: data.confidence_score || data.confidence,
          mode: data.mode,
          citations: data.citations || [],
          stage_ms: data.stage_ms_json || data.stage_ms,
          total_ms: data.latency_ms,
          workflow_action: data.workflow_action || data.workflow || (data.prompt_fields ? { state: data.status || 'COLLECT', prompt_fields: data.prompt_fields } : undefined),
          interaction_id: data.interaction_id,
        },
      ]);

      if (data.updated_slots) {
        setWorkflowSlots((prev) => ({ ...prev, ...data.updated_slots }));
      }
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        {
          id: `err_${Date.now()}`,
          sender: 'assistant',
          text: `An error occurred: ${err.message || 'Failed to connect to assistant backend.'}`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          confidence_band: 'LOW',
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleFeedback = async (messageId: string, rating: 'positive' | 'negative', interactionId?: string) => {
    setMessages((prev) =>
      prev.map((msg) => (msg.id === messageId ? { ...msg, feedback: rating } : msg))
    );

    try {
      await authFetch('/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          rating,
          interaction_id: interactionId,
        }),
      });
    } catch (err) {
      console.error('Failed to submit feedback:', err);
    }
  };

  const resetConversation = () => {
    setMessages([
      {
        id: `init-${Date.now()}`,
        sender: 'assistant',
        text: 'Session reset. How else can I assist you?',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      },
    ]);
    setWorkflowSlots({});
    setConversationId(`conv_${Date.now()}`);
  };

  return (
    <div className="min-h-screen bg-gray-950 flex flex-col font-sans text-gray-100">
      {/* Top Navigation Header */}
      <header className="flex items-center justify-between px-6 py-3.5 border-b border-white/10 bg-gray-900/80 backdrop-blur-md sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 via-violet-600 to-pink-500 flex items-center justify-center shadow-lg shadow-indigo-500/20">
            <Building2 size={18} className="text-white" />
          </div>
          <div>
            <h1 className="text-white font-bold text-base tracking-tight leading-none">Acentra HOA</h1>
            <p className="text-xs text-indigo-400 font-medium mt-0.5">Healthcare Operations Assistant</p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <PersonaSwitcher />

          <button
            onClick={resetConversation}
            title="Reset Conversation"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-gray-400 hover:text-white bg-white/5 hover:bg-white/10 border border-white/5 transition-all"
          >
            <RotateCcw size={13} />
            <span>New Session</span>
          </button>

          <div className="h-4 w-px bg-white/10" />

          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-indigo-500 to-violet-600 flex items-center justify-center text-xs font-bold text-white shadow-sm">
              {me?.name?.[0] ?? '?'}
            </div>
            <div className="hidden sm:block text-left">
              <p className="text-xs font-semibold text-white leading-tight">{me?.name ?? 'User'}</p>
              <p className="text-[10px] text-gray-400 leading-tight">{claims?.active_dept_role ?? claims?.app_role}</p>
            </div>
          </div>

          <button
            onClick={handleLogout}
            title="Sign out"
            className="p-2 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
          >
            <LogOut size={16} />
          </button>
        </div>
      </header>

      {/* Main Chat Area */}
      <main className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6 max-w-4xl w-full mx-auto">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex gap-3.5 ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            {msg.sender === 'assistant' && (
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-600 to-violet-600 flex items-center justify-center text-white flex-shrink-0 mt-1 shadow-md shadow-indigo-600/20">
                <Sparkles size={16} />
              </div>
            )}

            <div className={`max-w-2xl space-y-3 ${msg.sender === 'user' ? 'items-end' : 'items-start'}`}>
              <div
                className={`p-4 rounded-2xl text-sm leading-relaxed shadow-sm ${
                  msg.sender === 'user'
                    ? 'bg-gradient-to-r from-indigo-600 to-violet-600 text-white rounded-br-none'
                    : 'bg-gray-900/90 border border-white/10 text-gray-200 rounded-bl-none backdrop-blur-sm'
                }`}
              >
                <div className="whitespace-pre-wrap">{msg.text}</div>

                {/* Interactive Workflow Slot Form */}
                {msg.workflow_action?.prompt_fields && msg.workflow_action.prompt_fields.length > 0 && (
                  <SlotFillingForm
                    fields={msg.workflow_action.prompt_fields}
                    onSubmit={(slots) => handleSend('Submitting requested parameters', slots)}
                    disabled={loading}
                  />
                )}

                {/* Form / System guidance note */}
                {(msg.workflow_action?.form || msg.workflow_action?.system) && (
                  <div className="mt-3 p-3 rounded-xl bg-indigo-950/60 border border-indigo-500/20 text-xs text-indigo-300 space-y-1">
                    {msg.workflow_action.form && <div><strong>Form Required:</strong> {msg.workflow_action.form}</div>}
                    {msg.workflow_action.system && <div><strong>Target System:</strong> {msg.workflow_action.system}</div>}
                  </div>
                )}
              </div>

              {/* Assistant Message Metadata Bar */}
              {msg.sender === 'assistant' && (
                <div className="flex items-center flex-wrap gap-2 text-xs text-gray-400 px-1">
                  {/* Confidence Band */}
                  {msg.confidence_band && (
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold border ${
                        msg.confidence_band === 'HIGH'
                          ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                          : msg.confidence_band === 'MEDIUM'
                          ? 'bg-amber-500/15 text-amber-400 border-amber-500/30'
                          : 'bg-rose-500/15 text-rose-400 border-rose-500/30'
                      }`}
                    >
                      {msg.confidence_band === 'HIGH' ? (
                        <CheckCircle2 size={11} />
                      ) : (
                        <AlertTriangle size={11} />
                      )}
                      Confidence: {msg.confidence_band}
                    </span>
                  )}

                  {/* Mode Badge */}
                  {msg.mode && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-gray-800 text-gray-300 border border-white/10">
                      {msg.mode === 'llm' ? <Sparkles size={10} className="text-violet-400" /> : <Shield size={10} className="text-cyan-400" />}
                      {msg.mode.toUpperCase()}
                    </span>
                  )}

                  {/* Citations */}
                  {msg.citations && msg.citations.length > 0 && (
                    <span className="inline-flex items-center gap-1 text-[11px] text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded-full border border-indigo-500/20">
                      <FileText size={10} />
                      {msg.citations.join(', ')}
                    </span>
                  )}

                  {/* Latency Dropdown Toggle */}
                  {msg.total_ms !== undefined && (
                    <button
                      onClick={() =>
                        setExpandedLatencies((prev) => ({
                          ...prev,
                          [msg.id]: !prev[msg.id],
                        }))
                      }
                      className="inline-flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-200 transition-colors"
                    >
                      <Clock size={10} />
                      {msg.total_ms} ms
                      {expandedLatencies[msg.id] ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
                    </button>
                  )}

                  {/* Feedback Buttons */}
                  <div className="ml-auto flex items-center gap-1">
                    <button
                      onClick={() => handleFeedback(msg.id, 'positive', msg.interaction_id)}
                      className={`p-1 rounded hover:bg-white/10 transition-colors ${
                        msg.feedback === 'positive' ? 'text-emerald-400' : 'text-gray-500'
                      }`}
                      title="Helpful"
                    >
                      <ThumbsUp size={13} />
                    </button>
                    <button
                      onClick={() => handleFeedback(msg.id, 'negative', msg.interaction_id)}
                      className={`p-1 rounded hover:bg-white/10 transition-colors ${
                        msg.feedback === 'negative' ? 'text-rose-400' : 'text-gray-500'
                      }`}
                      title="Not helpful"
                    >
                      <ThumbsDown size={13} />
                    </button>
                  </div>

                  {/* Expanded Stage Latency Breakdown */}
                  {expandedLatencies[msg.id] && msg.stage_ms && (
                    <div className="w-full mt-2 p-2.5 rounded-xl bg-gray-900 border border-white/5 text-[11px] grid grid-cols-2 sm:grid-cols-4 gap-2 text-gray-300">
                      {Object.entries(msg.stage_ms).map(([stage, ms]) => (
                        <div key={stage} className="flex justify-between border-b border-white/5 pb-1">
                          <span className="capitalize text-gray-500">{stage}:</span>
                          <span className="font-mono text-indigo-300">{ms} ms</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            {msg.sender === 'user' && (
              <div className="w-8 h-8 rounded-lg bg-gray-800 border border-white/10 flex items-center justify-center text-xs font-bold text-gray-300 flex-shrink-0 mt-1">
                {me?.name?.[0] ?? 'U'}
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="flex gap-3.5 items-center">
            <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center text-white animate-pulse">
              <Sparkles size={16} />
            </div>
            <div className="p-4 rounded-2xl bg-gray-900 border border-white/10 text-xs text-gray-400 flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-indigo-500 animate-ping" />
              Processing operational query through safety guard, knowledge graph, and decision engine...
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </main>

      {/* Quick Sample Queries */}
      <div className="max-w-4xl w-full mx-auto px-4 pb-2">
        <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-none">
          <span className="text-[11px] text-gray-500 font-medium whitespace-nowrap">Suggested:</span>
          {SAMPLE_QUERIES.map((sq) => (
            <button
              key={sq.label}
              onClick={() => handleSend(sq.text)}
              disabled={loading}
              className="px-3 py-1 rounded-full text-xs bg-gray-900 hover:bg-gray-800 text-gray-300 hover:text-white border border-white/10 whitespace-nowrap transition-all"
            >
              {sq.label}
            </button>
          ))}
        </div>
      </div>

      {/* Bottom Input Area */}
      <footer className="border-t border-white/10 bg-gray-900/90 backdrop-blur-md p-4 sticky bottom-0 z-40">
        <div className="max-w-4xl mx-auto flex gap-3 items-center">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
            placeholder="Ask a question about operational policies, workflows, or authorization..."
            disabled={loading}
            className="flex-1 bg-gray-950 border border-white/10 focus:border-indigo-500 rounded-xl px-4 py-3 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 transition-all"
          />
          <button
            onClick={() => handleSend()}
            disabled={loading || !input.trim()}
            className="px-5 py-3 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium text-sm flex items-center gap-2 shadow-lg shadow-indigo-600/20 transition-all"
          >
            <span>Send</span>
            <Send size={15} />
          </button>
        </div>
      </footer>
    </div>
  );
}

// Subcomponent: Slot Filling Form inside message bubble
function SlotFillingForm({
  fields,
  onSubmit,
  disabled,
}: {
  fields: string[];
  onSubmit: (slots: Record<string, string>) => void;
  disabled: boolean;
}) {
  const [formValues, setFormValues] = useState<Record<string, string>>({});

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit(formValues);
  };

  return (
    <form onSubmit={handleSubmit} className="mt-4 pt-3 border-t border-white/10 space-y-3">
      <p className="text-xs font-semibold text-indigo-300">Required Parameters:</p>
      {fields.map((field) => (
        <div key={field} className="space-y-1">
          <label className="text-[11px] font-medium text-gray-400 capitalize">{field.replace('_', ' ')}</label>
          <input
            type={field.includes('date') ? 'date' : 'text'}
            value={formValues[field] || ''}
            onChange={(e) => setFormValues({ ...formValues, [field]: e.target.value })}
            placeholder={`Enter ${field.replace('_', ' ')}`}
            required
            className="w-full bg-gray-950 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
          />
        </div>
      ))}
      <button
        type="submit"
        disabled={disabled}
        className="w-full mt-2 py-2 px-3 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs shadow transition-all"
      >
        Submit Parameters
      </button>
    </form>
  );
}
