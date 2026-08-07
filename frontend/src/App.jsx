import { useState, useRef, useEffect, useCallback, memo } from "react";
import {
  Upload,
  Send,
  MessageSquare,
  Layers,
  RefreshCw,
  X,
  FileText,
  PenTool,
  Loader2,
  Trash2,
  CheckCircle2,
  Users,
  ShieldCheck,
  Zap,
  Sparkles,
  Plus,
  ArrowRight,
  ChevronLeft,
  Clock,
  History
} from "lucide-react";
import {
  uploadDocuments,
  queryRAG,
  getSources,
  deleteSource,
  ingestText,
  getChatHistory,
  getLeads,
  deleteLead,
  clearHistory,
  getThreads,
  createThread,
  deleteThread,
  generateProjectRequirements,
  getLatestRequirements,
  getRequirementHistory,
  acceptLead
} from "./api";
import ProjectGeneration from "./ProjectGeneration";
import Dashboard from "./Dashboard";
import AgentPipeline from "./AgentPipeline";
import "./index.css";

// --- Custom Components ---
const isProjectLead = (lead) => {
  const status = (lead?.status || "").toLowerCase();
  const stage = (lead?.project_stage || "").toLowerCase();
  return status === "accepted" || status === "launched" || stage === "requirements";
};

const AuroraBackground = () => (
  <div className="aurora-bg">
    <div className="glow glow-1"></div>
    <div className="glow glow-2"></div>
    <div className="glow glow-3"></div>
  </div>
);

const DEFAULT_APP_USER = {
  id: "guest-user",
  name: "Guest User",
  email: "guest@vilje.ai",
  role: "admin",
  auth_provider: "bypass",
};

const Toast = ({ show, msg, onClose }) => {
  useEffect(() => { if (show) { const t = setTimeout(onClose, 5000); return () => clearTimeout(t); } }, [show, onClose]);
  if (!show) return null;
  return (
    <div className="toast-container glass-panel">
      <Zap size={18} className="pulse-slow" style={{ color: "var(--accent-glow)" }} />
      <div className="toast-content"><p>{msg}</p></div>
      <button onClick={onClose}><X size={14} /></button>
    </div>
  );
};

const Sidebar = ({
  activePanel,
  setPanel,
  sources,
  onRefresh,
  onDelSource,
  activeLead,
  setViewMode,
  threads,
  activeThreadId,
  onSelectThread,
  onNewChat,
  onDelThread,
  listTab,
  setListTab,
  user
}) => (
  <aside className="sidebar glass-panel">
    <div className="sidebar-header">
      <div className="logo" onClick={() => setViewMode('dashboard')} style={{ cursor: 'pointer' }}>
        <div className="logo-icon"><Layers size={18} /></div>
        <div>
          <h1>VILJE <span style={{ color: "var(--accent-glow)" }}>AI</span></h1>
          {activeLead && <div className="active-lead-status">
            <span className="pulse-dot" style={{ background: isProjectLead(activeLead) ? '#10b981' : '#3b82f6' }}></span>
            <span style={{ fontSize: '0.65rem', marginRight: '6px', color: '#64748b' }}>
              {isProjectLead(activeLead) ? 'ACTIVE PROJECT:' : 'INBOUND CONTEXT:'}
            </span>
            {activeLead.project_name || activeLead.company}
          </div>}
        </div>
      </div>
    </div>

    {activeLead && (
      <div className="active-lead-card glass-panel anim-fade-in" onClick={() => setViewMode('dashboard')}>
        <div className="card-glitter"></div>
        <div className="card-top">
          <ShieldCheck size={14} className="card-icon" />
          <span className="card-status">PIPELINE ACTIVE</span>
        </div>
        <div className="card-body">
          <h4 className="card-title">{activeLead.company}</h4>
          <div className="card-action">
            <RefreshCw size={10} />
            <span>TAP TO SWITCH LEAD</span>
          </div>
        </div>
      </div>
    )}
    <nav className="sidebar-nav">
      <button className={`nav-btn ${activePanel === 'chat' ? 'active' : ''}`} onClick={() => setPanel('chat')}>
        <MessageSquare size={16} /> Chat
      </button>
      <button className={`nav-btn ${activePanel === 'manual' ? 'active' : ''}`} onClick={() => setPanel('manual')}>
        <PenTool size={16} /> Neural
      </button>
    </nav>

    <div className="sidebar-list-container">
      <div className="list-tabs">
        <button className={listTab === 'history' ? 'active' : ''} onClick={() => setListTab('history')}>
          Sessions <span>{threads?.length || 0}</span>
        </button>
        <button className={listTab === 'vault' ? 'active' : ''} onClick={() => setListTab('vault')}>
          Library <span>{sources?.length || 0}</span>
        </button>
      </div>

      <div className="list-content custom-scroll">
        {listTab === 'history' ? (
          <div className="sources-section anim-fade-in">
            <div className="sources-header">
              <h3>RECENT SESSIONS</h3>
              <button className="icon-btn-sm" onClick={() => onNewChat()} title="New Chat">
                <Plus size={14} />
              </button>
            </div>
            <div className="sources-list">
              {(!threads || threads.length === 0) ? <p className="empty-src">No sessions</p> :
                threads.map(t => (
                  <div
                    className={`source-item ${activeThreadId === t.id ? 'active' : ''}`}
                    key={t.id}
                    onClick={() => onSelectThread(t.id)}
                  >
                    <div className="source-info">
                      <History size={12} className="tint-accent" />
                      <span className="truncate">{t.title}</span>
                      <button className="del-btn-inline" onClick={(e) => { e.stopPropagation(); onDelThread(t.id); }}>
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </div>
                ))
              }
            </div>
          </div>
        ) : (
          <div className="sources-section anim-fade-in">
            <div className="sources-header">
              <h3>DOCUMENT VAULT</h3>
              <button className="icon-btn-sm" onClick={onRefresh}>
                <RefreshCw size={12} />
              </button>
            </div>
            <div className="sources-list">
              {(!sources || sources.length === 0) ? <p className="empty-src">Vault is empty</p> :
                sources.map(s => (
                  <div className="source-item" key={s.id || s}>
                    <div className="source-info">
                      <FileText size={12} className="tint-muted" />
                      <span className="truncate" title={s.name || s}>{s.name || s}</span>
                      <button className="del-btn-inline" onClick={() => onDelSource(s.id || s)}>
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </div>
                ))
              }
            </div>
          </div>
        )}
      </div>
    </div>
  </aside>
);

const ChatPanel = memo(({ messages, setMessages, activeLead, onToast, thread_id, onNewChat }) => {
  const [input, setInput] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef();
  const scrollRef = useRef();

  useEffect(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, [messages, isThinking]);

  const handleFileChange = async (e) => {
    const selectedFiles = Array.from(e.target.files);
    if (!selectedFiles.length || isUploading) return;
    setIsUploading(true);
    try {
      await uploadDocuments(selectedFiles, activeLead?.id);
      onToast(`Vault Sync Complete for ${activeLead?.project_name || activeLead?.company || 'Knowledge base'}.`);
      if (onNewChat) onNewChat(null, true);
    } catch {
      onToast("Upload failed.");
    } finally {
      setIsUploading(false);
      if (e.target) e.target.value = '';
    }
  };

  const handleSend = async (e) => {
    e.preventDefault();
    if (!input.trim() || isThinking) return;

    let targetTid = thread_id;
    if (!targetTid) {
      const sessionName = input.trim().substring(0, 30);
      const newId = await onNewChat(sessionName);
      targetTid = newId;
    }

    const q = input.trim(); setInput("");
    setMessages(prev => [...prev, { role: "user", text: q }]);
    setIsThinking(true);
    try {
      const resp = await queryRAG(q, messages, activeLead?.id, targetTid);
      setMessages(prev => [...prev, { role: "assistant", text: resp.answer, sources: resp.sources || [] }]);
    } catch {
      setMessages(prev => [...prev, { role: "assistant", text: "Connection error." }]);
    } finally { setIsThinking(false); }
  };

  return (
    <div className="main-content anim-fade-in">
      <div className="panel-top-bar">
        <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
          <h2>Intelligence Analyst</h2>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {activeLead && <div className="panel-tag">TARGET: {activeLead.project_name || activeLead.company}</div>}
        </div>
      </div>
      <div className="chat-container custom-scroll" ref={scrollRef}>
        {messages.length === 0 ? (
          <div className="chat-welcome">
            <Sparkles size={48} className="pulse-slow" style={{ color: "var(--accent-glow)", marginBottom: "1.5rem" }} />
            <h3>Intelligence Pipeline Active</h3>
            <p>Ready to analyze intelligence for <strong>{activeLead?.project_name || activeLead?.company}</strong>. Command entry open below.</p>
          </div>
        ) :
          messages.map((m, i) => (
            <div className={`chat-msg ${m.role}`} key={i}>
              <div className="msg-avatar">{m.role === 'user' ? 'U' : 'AI'}</div>
              <div className="msg-bubble glass-panel">
                <div className="msg-text">{m.text}</div>
                {m.sources?.length > 0 && <div className="msg-sources">Source Intelligence Locked: <span>{m.sources.join(", ")}</span></div>}
              </div>
            </div>
          ))
        }
        {isThinking && (
          <div className="chat-msg assistant">
            <div className="msg-avatar">AI</div>
            <div className="msg-bubble glass-panel">
              <div className="thinking-dots"><span>.</span><span>.</span><span>.</span></div>
            </div>
          </div>
        )}
      </div>

      <form className="chat-input-bar" onSubmit={handleSend}>
        <input type="file" ref={fileInputRef} hidden onChange={handleFileChange} multiple />
        <button
          type="button"
          className="btn-plus"
          onClick={() => fileInputRef.current?.click()}
          disabled={isUploading || isThinking}
        >
          {isUploading ? <Loader2 className="spin" size={18} /> : <Plus size={18} />}
        </button>
        <input placeholder={`Inquire about ${activeLead?.project_name || activeLead?.company}...`} value={input} onChange={e => setInput(e.target.value)} disabled={isThinking} />
        <button className="btn-send" disabled={!input.trim() || isThinking}><Send size={18} /></button>
      </form>
    </div>
  );
});

const UploadPanel = ({ onRefresh, onToast, activeLead }) => {
  const [files, setFiles] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef();

  const handleUpload = async () => {
    if (!files.length || isUploading) return;
    setIsUploading(true);
    try {
      if (activeLead && activeLead.id) {
        await uploadDocuments(files, activeLead.id);
        onToast(`Vault Sync Complete for ${activeLead.project_name || activeLead.company}.`);
      } else {
        await uploadDocuments(files, null);
        onToast(`Global Vault Sync Complete.`);
      }
      setFiles([]); await onRefresh();
    } catch { alert("Failed."); }
    finally { setIsUploading(false); }
  };

  return (
    <div className="main-content anim-fade-in">
      <div className="panel-top-bar">
        <h2>Knowledge Vault</h2>
        {activeLead && <div className="panel-tag">INBOUND: {activeLead.project_name || activeLead.company}</div>}
      </div>
      <div className="upload-container custom-scroll">
        <div className="upload-area glass-panel" onClick={() => files.length === 0 && fileInputRef.current.click()}>
          {files.length === 0 ? (
            <>
              <div className="pulse-slow" style={{ background: 'var(--accent-glow)', width: '64px', height: '64px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '1rem' }}>
                <Upload size={28} color="white" />
              </div>
              <h3>Strategic Ingestion</h3>
              <p>Index documents into your current active project silo.</p>
              <input type="file" multiple hidden ref={fileInputRef} onChange={e => setFiles(Array.from(e.target.files))} />
              <button className="btn-primary" style={{ marginTop: '1.5rem' }}>Select Documents</button>
            </>
          ) : (
            <div className="file-queue-box glass-panel" style={{ width: '100%' }}>
              <div className="queue-header-area">
                <h3>Research Queue ({files.length})</h3>
                <div style={{ display: 'flex', gap: '10px' }}>
                  <button className="btn-danger btn-sm" onClick={(e) => { e.stopPropagation(); setFiles([]); }}>Clear</button>
                  <button className="btn-primary btn-sm" onClick={(e) => { e.stopPropagation(); handleUpload(); }} disabled={isUploading}>
                    {isUploading ? <Loader2 className="spin" size={14} /> : <Zap size={14} />} Ingest
                  </button>
                </div>
              </div>
              <div className="queue-list-area custom-scroll">
                {files.map((f, i) => (
                  <div className="queue-row" key={i}>
                    <FileText size={16} />
                    <span className="queue-file-name">{f.name}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const NeuralEntryPanel = ({ onRefresh, onToast, activeLead }) => {
  const [topic, setTopic] = useState("");
  const [content, setTopicContent] = useState("");
  const [isCommiting, setIsCommiting] = useState(false);

  const handleClear = () => {
    setTopic(""); setTopicContent("");
    onToast("Draft cleared.");
  };

  const handleSubmit = async (e) => {
    e.preventDefault(); if (!topic || !content || isCommiting) return;
    setIsCommiting(true);
    try {
      await ingestText(topic, content, activeLead?.id);
      onToast(`Neural Segment Locked: ${topic}`);
      setTopic(""); setTopicContent("");
      onRefresh();
    } catch { alert("Failed."); }
    finally { setIsCommiting(false); }
  };

  return (
    <div className="main-content anim-fade-in">
      <div className="panel-top-bar">
        <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
          <h2>Neural Segment Entry</h2>
          <div className="panel-tag">MANUAL VECTORIZATION</div>
        </div>
      </div>
      <div className="neural-entry-container custom-scroll">
        <form className="manual-entry-form glass-panel" onSubmit={handleSubmit}>
          <div className="form-header">
            <PenTool size={20} style={{ color: 'var(--accent-glow)' }} />
            <h3>Intelligence Manual Protocol</h3>
          </div>
          <div className="input-group">
            <label>SOURCE NAME / TOPIC</label>
            <div className="input-field">
              <input value={topic} required onChange={e => setTopic(e.target.value)} placeholder="e.g., Marketing Strategy Call Notes" />
            </div>
          </div>
          <div className="input-group">
            <label>INTELLIGENCE CONTENT</label>
            <div className="input-field">
              <textarea value={content} required onChange={e => setTopicContent(e.target.value)} placeholder="Paste raw intelligence data here for vectorization..." style={{ minHeight: '180px' }}></textarea>
            </div>
          </div>
          <div className="form-actions">
            <button type="button" className="btn-secondary" onClick={handleClear} disabled={isCommiting}>
              <RefreshCw size={14} /> CLEAR DRAFT
            </button>
            <button type="submit" className="btn-primary" disabled={isCommiting}>
              {isCommiting ? <Loader2 className="spin" size={16} /> : <Zap size={16} />}
              COMMIT TO VECTOR VAULT
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default function App() {
  const [user, setUser] = useState(() => {
    try {
      const saved = localStorage.getItem("leadflow_user");
      return saved ? JSON.parse(saved) : DEFAULT_APP_USER;
    } catch { return DEFAULT_APP_USER; }
  });

  const [viewMode, setViewMode] = useState("dashboard");
  const [activeDashSection, setActiveDashSection] = useState("home"); // lifted from Dashboard
  const [activePanel, setActivePanel] = useState("chat");
  const [activeLead, setActiveLead] = useState(null);
  const [sources, setSources] = useState([]);
  const [leads, setLeads] = useState(() => {
    try {
      const saved = localStorage.getItem("leadflow_leads_cache");
      return saved ? JSON.parse(saved) : [];
    } catch { return []; }
  });
  const [threads, setThreads] = useState([]);
  const [activeThreadId, setActiveThreadId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [requirementsData, setRequirementsData] = useState(null);
  const [latestProjectTranscript, setLatestProjectTranscript] = useState("");
  const [requirementsHandoff, setRequirementsHandoff] = useState(null);
  const [requirementHistory, setRequirementHistory] = useState([]);
  const [selectedWorkflowSessionVersion, setSelectedWorkflowSessionVersion] = useState(null);
  const [projectError, setProjectError] = useState("");
  const [isGeneratingRequirements, setIsGeneratingRequirements] = useState(false);
  const [isLoadingRequirements, setIsLoadingRequirements] = useState(false);
  const [toast, setToast] = useState({ show: false, msg: "" });
  const [listTab, setListTab] = useState("history");
  const syncInFlightRef = useRef(false);
  const syncBackoffRef = useRef(30000);
  const requirementGenerationLockRef = useRef(false);

  const normalizeLeadSummary = (lead) => {
    if (!lead) return null;
    return {
      id: lead.id || "",
      company_id: lead.company_id || "",
      project_name: lead.project_name || "",
      company: lead.company || lead.company_name || lead.project_name || "",
      domain: lead.domain || lead.company_domain || "",
      industry: lead.industry || lead.company_field || "",
      poc: lead.poc || lead.contact_person || "",
      company_size: lead.company_size || "",
      status: lead.status || "",
      project_stage: lead.project_stage || "",
      updated_at: lead.updated_at || "",
      at: lead.at || "",
    };
  };

  const triggerToast = (m) => setToast({ show: true, msg: m });

  const handleAuthSuccess = (userData) => {
    setUser(userData);
    localStorage.setItem("leadflow_user", JSON.stringify(userData));
    triggerToast(`Authenticated as ${userData.name}`);
  };

  const fetchData = useCallback(async (currentLid, currentTid, showLoader = false) => {
    if (syncInFlightRef.current) return;
    syncInFlightRef.current = true;
    try {
      const lid = currentLid || activeLead?.id;
      const tid = currentTid || activeThreadId;

      let lData = null;
      try {
        lData = await getLeads();
      } catch (leadErr) {
        const cachedLeads = (() => {
          try {
            const saved = localStorage.getItem("leadflow_leads_cache");
            return saved ? JSON.parse(saved) : [];
          } catch {
            return [];
          }
        })();
        if (cachedLeads.length) {
          lData = { leads: cachedLeads };
        } else {
          throw leadErr;
        }
      }

      syncBackoffRef.current = 30000;
      if (lData?.leads) {
        setLeads(lData.leads);
        localStorage.setItem("leadflow_leads_cache", JSON.stringify(lData.leads));
        if (lid) {
          const refreshedLead = lData.leads.find((lead) => lead.id === lid);
          // Only update if something meaningful changed to avoid re-render loops
          if (refreshedLead) {
            const currentSummary = normalizeLeadSummary(activeLead);
            const refreshedSummary = normalizeLeadSummary(refreshedLead);
            if (JSON.stringify(refreshedSummary) !== JSON.stringify(currentSummary)) {
              setActiveLead((prev) => (prev?.id === refreshedLead.id ? { ...prev, ...refreshedLead } : refreshedLead));
            }
          }
        }
      }

      if (lid) {
        const workflowQuery = selectedWorkflowSessionVersion
          ? { workflow_id: String(selectedWorkflowSessionVersion) }
          : requirementsHandoff?.requirements_state?.workflow_session_version
            ? { workflow_id: String(requirementsHandoff.requirements_state.workflow_session_version) }
            : {};
        if (showLoader) setIsLoadingRequirements(true);
        const [sData, tData, hData, rData, rhData] = await Promise.allSettled([
          getSources(lid),
          getThreads(lid),
          tid ? getChatHistory(lid, tid) : Promise.resolve({ history: [] }),
          getLatestRequirements(lid, workflowQuery),
          getRequirementHistory(lid)
        ]);
        setIsLoadingRequirements(false);
        if (sData.status === 'fulfilled') setSources(sData.value?.sources || []);
        if (tData.status === 'fulfilled') setThreads(tData.value?.threads || []);
        if (hData.status === 'fulfilled' && tid) setMessages(hData.value?.history || []);
        if (rData.status === 'fulfilled') {
          const requirementState = rData.value?.requirements_state || null;
          const projectData = rData.value?.project || null;
          setRequirementsData(requirementState?.current_requirements || null);
          setLatestProjectTranscript(projectData?.processed_context || projectData?.raw_context || "");
          setRequirementsHandoff(rData.value?.requirements_handoff || null);
        }
        if (rhData.status === 'fulfilled') setRequirementHistory(rhData.value?.events || []);
      }
    } catch (err) {
      syncBackoffRef.current = Math.min(syncBackoffRef.current * 2, 180000);
      console.warn("Sync fallback activated", err);
    }
    finally {
      syncInFlightRef.current = false;
    }
  }, [activeLead, activeThreadId, selectedWorkflowSessionVersion, requirementsHandoff?.requirements_state?.workflow_session_version]);

  useEffect(() => {
    if (activeLead?.id) {
      fetchData(null, null, true);
    }
  }, [selectedWorkflowSessionVersion]);

  // ── Polling & Sync Logic ──
  // Use a ref to always point to the latest fetchData without triggering the effect loop
  const fetchDataRef = useRef(fetchData);
  useEffect(() => {
    fetchDataRef.current = fetchData;
  }, [fetchData]);

  useEffect(() => {
    let cancelled = false;
    let timer = null;

    const run = async () => {
      if (cancelled) return;
      await fetchDataRef.current();
      if (cancelled) return;
      timer = setTimeout(run, syncBackoffRef.current);
    };

    // First run after a short delay, then follow backoff
    timer = setTimeout(run, 1000);

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []); // Run once on mount

  const handleDelSource = async (id) => { await deleteSource(id); triggerToast("Source removed."); fetchData(null, null, true); };

  const handleSelectLead = (lead) => {
    setActiveLead(lead);
    setSelectedWorkflowSessionVersion(null);
    if (isProjectLead(lead) && (lead?.status || "").toLowerCase() !== 'launched') {
      setViewMode("pipeline");
      triggerToast(`Agent Pipeline Active: ${lead.company}`);
    } else if (lead.status === 'launched') {
      setViewMode("pipeline");
      triggerToast(`Project Pipeline Active: ${lead.company}`);
    } else {
      setViewMode("classic");
      triggerToast(`Pipeline Activated: ${lead.company}`);
    }
    setActivePanel("chat");
    setActiveThreadId(null);
    setRequirementsData(null);
    setLatestProjectTranscript("");
    setRequirementsHandoff(null);
    setRequirementHistory([]);
    setProjectError("");
  };

  const handleAcceptLead = async (lead) => {
    if (!lead?.id) return;
    const proceed = window.confirm(
      "Create this project and move into Requirement Generation? This will start the next workflow step."
    );
    if (!proceed) return;

    let leadForProject = lead;
    try {
      const res = await acceptLead(lead.id);
      if (res?.lead) {
        leadForProject = { ...lead, ...res.lead };
      }
    } catch (err) {
      console.error("Accept lead failed:", err);
    }

    setActiveLead(leadForProject);
    setSelectedWorkflowSessionVersion(null);
    setViewMode("pipeline");
    setRequirementsData(null);
    setLatestProjectTranscript("");
    setRequirementsHandoff(null);
    setRequirementHistory([]);
    setProjectError("");
    setProjectError("");
    await fetchData(null, null, true);
    triggerToast(`Agent Pipeline Active: ${leadForProject.company || lead.company || "Lead"}`);
  };

  const handleOpenPipeline = (lead) => {
    setActiveLead(lead);
    setSelectedWorkflowSessionVersion(null);
    setViewMode("pipeline");
    triggerToast(`Agent Pipeline Active: ${lead.company}`);
  };

  const handleOpenAnalysis = () => {
    setViewMode("classic");
    setActivePanel("chat");
  };

  const runRequirementsGeneration = async (runner) => {
    if (!activeLead?.id || isGeneratingRequirements || requirementGenerationLockRef.current) {
      if (requirementGenerationLockRef.current) {
        console.warn("Requirement generation skipped because a request is already in flight.");
      }
      return false;
    }
    const requestId = globalThis.crypto?.randomUUID
      ? globalThis.crypto.randomUUID()
      : `req-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    requirementGenerationLockRef.current = true;
    setIsGeneratingRequirements(true);
    setProjectError("");
    try {
      console.info("Starting requirement generation", {
        leadId: activeLead.id,
        requestId,
      });
      const res = await runner(requestId);
      if (res?.error) {
        setProjectError(res.error);
        return false;
      }
      await fetchData();
      triggerToast(`Requirements Generated: ${activeLead.company}`);
      return true;
    } catch (err) {
      setProjectError("Requirement generation failed.");
      return false;
    } finally {
      requirementGenerationLockRef.current = false;
      setIsGeneratingRequirements(false);
    }
  };

  const handleGenerateFromContext = async (options = {}) => {
    if (!activeLead?.id) return;
    return await runRequirementsGeneration((requestId) =>
      generateProjectRequirements(activeLead.id, {
        ...options,
        requestId,
        workflow_id: selectedWorkflowSessionVersion ? String(selectedWorkflowSessionVersion) : options.workflow_id
      })
    );
  };

  const handleDelThread = async (tid) => {
    if (!window.confirm("Permanently purge this session history?")) return;
    await deleteThread(tid);
    if (activeThreadId === tid) {
      setActiveThreadId(null);
      setMessages([]);
    }
    triggerToast("Intelligence Session Purged");
    fetchData(null, null, true);
  };

  const handleNewChat = async (customTitle, refreshOnly = false) => {
    if (!activeLead) return;
    if (refreshOnly) {
      fetchData();
      return;
    }
    const title = customTitle || `New Session ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
    const { id } = await createThread(activeLead.id, title);
    setActiveThreadId(id);
    fetchData(null, null, true);
    return id;
  };

  return (
    <div className="app-layout">
      {(viewMode === 'classic' || viewMode === 'project') && <AuroraBackground />}

      {viewMode === 'classic' ? (
        <div className="view-container anim-fade-in" style={{ display: 'flex', flex: 1, height: '100%' }}>
          <Sidebar
            activePanel={activePanel}
            setPanel={setActivePanel}
            sources={sources}
            leads={leads}
            onRefresh={fetchData}
            onDelSource={handleDelSource}
            activeLead={activeLead}
            setViewMode={setViewMode}
            threads={threads}
            activeThreadId={activeThreadId}
            onSelectThread={setActiveThreadId}
            onNewChat={() => handleNewChat()}
            onDelThread={handleDelThread}
            listTab={listTab}
            setListTab={setListTab}
            user={user}
          />

          {activePanel === 'chat' && (
            <ChatPanel
              messages={messages}
              setMessages={setMessages}
              activeLead={activeLead}
              onToast={triggerToast}
              thread_id={activeThreadId}
              onNewChat={handleNewChat}
            />
          )}
          {activePanel === 'manual' && <NeuralEntryPanel onRefresh={fetchData} onToast={triggerToast} activeLead={activeLead} />}
        </div>
      ) : viewMode === 'project' ? (
        <ProjectGeneration
          lead={activeLead}
          requirementsData={requirementsData}
          requirementsHandoff={requirementsHandoff}
          projectTranscript={latestProjectTranscript}
          requirementHistory={requirementHistory}
          isGenerating={isGeneratingRequirements}
          isLoadingRequirements={isLoadingRequirements}
          error={projectError}
          onBack={() => setViewMode("classic")}
          onOpenAnalysis={handleOpenAnalysis}
          onGenerateFromContext={handleGenerateFromContext}
        />
      ) : viewMode === 'pipeline' ? (
        <div className="view-container anim-fade-in" style={{ flex: 1, height: '100%' }}>
          <AgentPipeline
            activeProject={activeLead}
            requirementsData={requirementsData}
            requirementsHandoff={requirementsHandoff}
            projectTranscript={latestProjectTranscript}
            requirementHistory={requirementHistory}
            isGenerating={isGeneratingRequirements}
            isLoadingRequirements={isLoadingRequirements}
            error={projectError}
            onBack={() => setViewMode("dashboard")}
            onGenerateFromContext={handleGenerateFromContext}
            onRefresh={fetchData}
            onWorkflowSessionChange={setSelectedWorkflowSessionVersion}
            selectedWorkflowSessionVersion={selectedWorkflowSessionVersion}
          />
        </div>
      ) : (
        <div className="view-container anim-fade-in" style={{ flex: 1 }}>
          <Dashboard
            onSelectLead={handleSelectLead}
            onOpenPipeline={handleOpenPipeline}
            leads={leads}
            onRefresh={fetchData}
            activeSection={activeDashSection}
            setActiveSection={setActiveDashSection}
            user={user}
          />
        </div>
      )}

      <Toast show={toast.show} msg={toast.msg} onClose={() => setToast({ show: false, msg: "" })} />
    </div>
  );
}
