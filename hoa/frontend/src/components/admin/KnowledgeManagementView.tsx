import { useEffect, useState } from 'react';
import { Plus, Search, Link2, AlertCircle, Trash2, CheckCircle2, ShieldAlert } from 'lucide-react';
import { useAuthStore } from '../../store/authStore';

export default function KnowledgeManagementView() {
  const { authFetch } = useAuthStore();
  const [activeTab, setActiveTab] = useState<'articles' | 'gaps' | 'suggestions'>('articles');

  // Articles state
  const [articles, setArticles] = useState<any[]>([]);
  const [search, setSearch] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [owner, setOwner] = useState('Department Operations Head');

  // Gaps & Draft state
  const [gaps, setGaps] = useState<any[]>([]);
  const [selectedGap, setSelectedGap] = useState<any | null>(null);
  const [draftTitle, setDraftTitle] = useState('');
  const [draftBody, setDraftBody] = useState('');

  // Link Suggestions state
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [generating, setGenerating] = useState(false);

  // Impact modal
  const [impactModalNode, setImpactModalNode] = useState<any | null>(null);
  const [impactData, setImpactData] = useState<any | null>(null);

  const [message, setMessage] = useState<string | null>(null);

  const loadArticles = async () => {
    try {
      const res = await authFetch(`/admin/knowledge/articles?query=${encodeURIComponent(search)}`);
      if (res.ok) {
        const data = await res.json();
        setArticles(data.articles || []);
      }
    } catch (err) {
      console.error('Failed to load articles', err);
    }
  };

  const loadGaps = async () => {
    try {
      const res = await authFetch('/admin/knowledge/gaps');
      if (res.ok) {
        const data = await res.json();
        setGaps(data.gaps || []);
      }
    } catch (err) {
      console.error('Failed to load gaps', err);
    }
  };

  const loadSuggestions = async () => {
    try {
      const res = await authFetch('/admin/knowledge/link-suggestions');
      if (res.ok) {
        const data = await res.json();
        setSuggestions(data.suggestions || []);
      }
    } catch (err) {
      console.error('Failed to load suggestions', err);
    }
  };

  useEffect(() => {
    if (activeTab === 'articles') loadArticles();
    if (activeTab === 'gaps') loadGaps();
    if (activeTab === 'suggestions') loadSuggestions();
  }, [activeTab, search]);

  const handleCreateArticle = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await authFetch('/admin/knowledge/articles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, body, type: 'policy', owner, roles: ['ALL'] }),
      });
      if (res.ok) {
        setMessage('Article created and published!');
        setShowCreateModal(false);
        setTitle('');
        setBody('');
        loadArticles();
      }
    } catch (err) {
      console.error('Failed to create article', err);
    }
  };

  const handleApproveArticle = async (articleId: string) => {
    try {
      const res = await authFetch(`/admin/knowledge/articles/${articleId}/approve`, {
        method: 'POST',
      });
      if (res.ok) {
        setMessage('Article approved & new graph version published!');
        loadArticles();
      }
    } catch (err) {
      console.error('Approve failed', err);
    }
  };

  const handleRetireArticle = async (articleId: string) => {
    try {
      const res = await authFetch(`/admin/knowledge/articles/${articleId}/retire`, {
        method: 'POST',
      });
      if (res.ok) {
        setMessage('Article retired & embeddings deleted atomically.');
        loadArticles();
      }
    } catch (err) {
      console.error('Retire failed', err);
    }
  };

  const handleCreateDraftFromGap = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedGap) return;
    try {
      const res = await authFetch(`/admin/knowledge/gaps/${selectedGap.id}/draft`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: draftTitle, body: draftBody, owner: selectedGap.team }),
      });
      if (res.ok) {
        setMessage('Draft article created from gap!');
        setSelectedGap(null);
        setDraftTitle('');
        setDraftBody('');
        loadGaps();
        loadArticles();
      }
    } catch (err) {
      console.error('Failed to create draft from gap', err);
    }
  };

  const handleGenerateSuggestions = async () => {
    setGenerating(true);
    try {
      const res = await authFetch('/admin/knowledge/link-suggestions/generate', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setMessage(`Generated ${data.generated_count} link suggestions!`);
        loadSuggestions();
      }
    } catch (err) {
      console.error('Generate suggestions failed', err);
    } finally {
      setGenerating(false);
    }
  };

  const handleApproveSuggestion = async (id: number) => {
    try {
      const res = await authFetch(`/admin/knowledge/link-suggestions/${id}/approve`, { method: 'POST' });
      if (res.ok) {
        setMessage('Suggestion approved!');
        loadSuggestions();
      }
    } catch (err) {
      console.error('Approve suggestion failed', err);
    }
  };

  const handleRejectSuggestion = async (id: number) => {
    try {
      const res = await authFetch(`/admin/knowledge/link-suggestions/${id}/reject`, { method: 'POST' });
      if (res.ok) {
        setMessage('Suggestion rejected.');
        loadSuggestions();
      }
    } catch (err) {
      console.error('Reject suggestion failed', err);
    }
  };

  const handleViewImpact = async (art: any) => {
    setImpactModalNode(art);
    try {
      const res = await authFetch(`/graph/impact/${art.id}`);
      if (res.ok) {
        setImpactData(await res.json());
      }
    } catch (err) {
      console.error('Fetch impact failed', err);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight">Knowledge & Second Brain</h2>
          <p className="text-xs text-gray-400 mt-1">Manage articles, resolve gaps to drafts, review link suggestions</p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs shadow transition-all"
          >
            <Plus size={14} />
            New Article
          </button>
        </div>
      </div>

      {message && (
        <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-300 flex items-center justify-between">
          <span>{message}</span>
          <button onClick={() => setMessage(null)} className="text-emerald-400 font-bold">✕</button>
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-white/10 gap-6 text-xs font-semibold text-gray-400">
        <button
          onClick={() => setActiveTab('articles')}
          className={`pb-3 transition-colors ${activeTab === 'articles' ? 'text-indigo-400 border-b-2 border-indigo-500' : 'hover:text-white'}`}
        >
          Articles & Nodes
        </button>
        <button
          onClick={() => setActiveTab('gaps')}
          className={`pb-3 transition-colors flex items-center gap-1.5 ${activeTab === 'gaps' ? 'text-amber-400 border-b-2 border-amber-500' : 'hover:text-white'}`}
        >
          <AlertCircle size={14} />
          Knowledge Gaps
        </button>
        <button
          onClick={() => setActiveTab('suggestions')}
          className={`pb-3 transition-colors flex items-center gap-1.5 ${activeTab === 'suggestions' ? 'text-violet-400 border-b-2 border-violet-500' : 'hover:text-white'}`}
        >
          <Link2 size={14} />
          Link Suggestions
        </button>
      </div>

      {/* TAB 1: Articles */}
      {activeTab === 'articles' && (
        <div className="space-y-4">
          <div className="relative">
            <Search size={15} className="absolute left-3.5 top-3 text-gray-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search articles by title..."
              className="w-full bg-gray-900 border border-white/10 rounded-xl pl-10 pr-4 py-2 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {articles.map((art) => (
              <div key={art.id} className="p-4 rounded-xl bg-gray-900 border border-white/10 space-y-3">
                <div className="flex justify-between items-start">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${
                    art.status === 'draft' ? 'bg-amber-500/15 text-amber-300 border-amber-500/30' :
                    art.status === 'approved' ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' :
                    'bg-gray-800 text-gray-400 border-gray-700'
                  }`}>
                    {art.status}
                  </span>
                  <span className="text-[10px] text-gray-500">v{art.version}</span>
                </div>

                <h3 className="text-sm font-semibold text-white">{art.title}</h3>
                <p className="text-xs text-gray-400 line-clamp-3">{art.body}</p>

                <div className="pt-3 flex justify-between items-center text-[10px] border-t border-white/5">
                  <span className="text-gray-500">Owner: {art.owner}</span>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleViewImpact(art)}
                      className="px-2 py-1 rounded bg-white/5 hover:bg-white/10 text-gray-300 font-medium"
                    >
                      Impact
                    </button>
                    {art.status === 'draft' && (
                      <button
                        onClick={() => handleApproveArticle(art.id)}
                        className="px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-semibold flex items-center gap-1"
                      >
                        <CheckCircle2 size={11} /> Approve
                      </button>
                    )}
                    {art.status === 'approved' && (
                      <button
                        onClick={() => handleRetireArticle(art.id)}
                        className="px-2 py-1 rounded bg-rose-600/20 hover:bg-rose-600/40 text-rose-300 font-semibold border border-rose-500/30 flex items-center gap-1"
                      >
                        <Trash2 size={11} /> Retire
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* TAB 2: Knowledge Gaps */}
      {activeTab === 'gaps' && (
        <div className="space-y-4">
          <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/20 text-xs text-amber-300 flex items-center gap-3">
            <ShieldAlert size={18} className="text-amber-400 flex-shrink-0" />
            <span>These tickets were flagged as knowledge gaps from insufficient evidence. Click "Create Draft" to resolve a gap into a draft article.</span>
          </div>

          <div className="space-y-3">
            {gaps.map((gap) => (
              <div key={gap.id} className="p-4 rounded-xl bg-gray-900 border border-white/10 flex items-center justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-white">{gap.reason}</span>
                    <span className="text-[10px] px-2 py-0.5 rounded bg-white/5 text-gray-400">{gap.team}</span>
                  </div>
                  <p className="text-xs text-gray-400 mt-1">{gap.summary || 'Unresolved query resulting in ticket route'}</p>
                </div>

                <button
                  onClick={() => { setSelectedGap(gap); setDraftTitle(''); setDraftBody(''); }}
                  className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs shadow"
                >
                  Create Draft Article
                </button>
              </div>
            ))}
            {gaps.length === 0 && <div className="text-xs text-gray-500 text-center py-8">No active knowledge gaps</div>}
          </div>
        </div>
      )}

      {/* TAB 3: Link Suggestions */}
      {activeTab === 'suggestions' && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <p className="text-xs text-gray-400">Review queue of suggested relations found by rapidfuzz between articles, forms, and systems.</p>
            <button
              onClick={handleGenerateSuggestions}
              disabled={generating}
              className="px-3 py-1.5 rounded-xl bg-violet-600 hover:bg-violet-500 text-white font-semibold text-xs shadow"
            >
              {generating ? 'Scanning...' : 'Scan & Generate Suggestions'}
            </button>
          </div>

          <div className="space-y-3">
            {suggestions.map((sug) => (
              <div key={sug.id} className="p-4 rounded-xl bg-gray-900 border border-white/10 flex items-center justify-between gap-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2 text-xs">
                    <span className="font-semibold text-indigo-300">{sug.from_title}</span>
                    <span className="text-gray-500">→ [{sug.type}] →</span>
                    <span className="font-semibold text-emerald-300">{sug.to_title}</span>
                  </div>
                  <p className="text-[10px] text-gray-500 font-mono">{sug.note}</p>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleApproveSuggestion(sug.id)}
                    className="px-2.5 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => handleRejectSuggestion(sug.id)}
                    className="px-2.5 py-1 rounded bg-rose-600/20 hover:bg-rose-600/40 text-rose-300 font-semibold text-xs border border-rose-500/30"
                  >
                    Reject
                  </button>
                </div>
              </div>
            ))}
            {suggestions.length === 0 && <div className="text-xs text-gray-500 text-center py-8">No pending link suggestions</div>}
          </div>
        </div>
      )}

      {/* Modal: Create Article */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <form onSubmit={handleCreateArticle} className="bg-gray-900 border border-white/10 rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl">
            <div className="flex justify-between items-center">
              <h3 className="text-base font-bold text-white">Create Knowledge Article</h3>
              <button type="button" onClick={() => setShowCreateModal(false)} className="text-gray-400 hover:text-white">✕</button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-400">Title</label>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  required
                  className="w-full bg-gray-950 border border-white/10 rounded-lg px-3 py-2 text-xs text-white"
                />
              </div>

              <div>
                <label className="text-xs text-gray-400">Body</label>
                <textarea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  required
                  rows={4}
                  className="w-full bg-gray-950 border border-white/10 rounded-lg p-3 text-xs text-white"
                />
              </div>

              <div>
                <label className="text-xs text-gray-400">Owner Team</label>
                <input
                  type="text"
                  value={owner}
                  onChange={(e) => setOwner(e.target.value)}
                  className="w-full bg-gray-950 border border-white/10 rounded-lg px-3 py-2 text-xs text-white"
                />
              </div>
            </div>

            <button type="submit" className="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs shadow">
              Save & Publish Article
            </button>
          </form>
        </div>
      )}

      {/* Drawer: Draft from Gap */}
      {selectedGap && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <form onSubmit={handleCreateDraftFromGap} className="bg-gray-900 border border-white/10 rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl">
            <div className="flex justify-between items-center">
              <h3 className="text-base font-bold text-white">Resolve Gap to Draft Article</h3>
              <button type="button" onClick={() => setSelectedGap(null)} className="text-gray-400 hover:text-white">✕</button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-400">Article Title</label>
                <input
                  type="text"
                  value={draftTitle}
                  onChange={(e) => setDraftTitle(e.target.value)}
                  required
                  placeholder="e.g. Pediatric Pet Therapy Policy"
                  className="w-full bg-gray-950 border border-white/10 rounded-lg px-3 py-2 text-xs text-white"
                />
              </div>

              <div>
                <label className="text-xs text-gray-400">Resolution Body (Draft content)</label>
                <textarea
                  value={draftBody}
                  onChange={(e) => setDraftBody(e.target.value)}
                  required
                  rows={5}
                  placeholder="Enter the official policy text to resolve this knowledge gap..."
                  className="w-full bg-gray-950 border border-white/10 rounded-lg p-3 text-xs text-white"
                />
              </div>
            </div>

            <button type="submit" className="w-full py-2.5 rounded-xl bg-amber-600 hover:bg-amber-500 text-white font-semibold text-xs shadow">
              Create Draft Node (Status: Draft)
            </button>
          </form>
        </div>
      )}

      {/* Modal: Change Impact */}
      {impactModalNode && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-gray-900 border border-white/10 rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl">
            <div className="flex justify-between items-center">
              <h3 className="text-base font-bold text-white">Change Impact Analysis</h3>
              <button type="button" onClick={() => setImpactModalNode(null)} className="text-gray-400 hover:text-white">✕</button>
            </div>

            <p className="text-xs text-gray-400">
              Workflows and articles affected through backlinks if <span className="text-white font-semibold">{impactModalNode.title}</span> is updated or retired.
            </p>

            <div className="space-y-3 max-h-60 overflow-y-auto pr-1">
              <div>
                <h4 className="text-xs font-semibold text-indigo-300">Affected Workflows ({impactData?.affected_workflows?.length || 0})</h4>
                {impactData?.affected_workflows?.map((w: any) => (
                  <div key={w.id} className="p-2 rounded bg-white/5 text-xs text-gray-300 mt-1">{w.title} (Owner: {w.owner})</div>
                ))}
              </div>

              <div>
                <h4 className="text-xs font-semibold text-emerald-300">Affected Articles ({impactData?.affected_articles?.length || 0})</h4>
                {impactData?.affected_articles?.map((a: any) => (
                  <div key={a.id} className="p-2 rounded bg-white/5 text-xs text-gray-300 mt-1">{a.title}</div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
