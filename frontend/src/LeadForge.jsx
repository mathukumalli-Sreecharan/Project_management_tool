import React, { useState, useEffect } from 'react';
import {
  ShieldCheck, Globe, Briefcase, Zap, Sparkles, Users, Plus, Trash2, X,
  Loader2, CheckCircle2, ArrowRight, Database, Activity, ExternalLink,
  UploadCloud, FileText, ChevronRight, Building2, Layers, Edit3, MessageSquare,
  FolderGit2
} from 'lucide-react';
import {
  getCompanies, registerLead, deleteLead, deleteCompany, updateCompany,
  analyzeDocuments, confirmDocuments, getLeads, getLead, lookupCompany
} from './api';
import './LeadForge.css';

const isProjectLead = (lead) => {
  const status = (lead?.status || "").toLowerCase();
  const stage = (lead?.project_stage || "").toLowerCase();
  return status === "accepted" || status === "launched" || stage === "requirements";
};

export default function LeadForge({ onSelectLead, onRefresh, user }) {
  const [view, setView] = useState("grid");           // grid | leads | upload | form
  const [companies, setCompanies] = useState([]);
  const [activeCompany, setActiveCompany] = useState(null);   // company clicked into
  const [activeLead, setActiveLead] = useState(null);         // lead detail panel
  const [isLoading, setIsLoading] = useState(true);
  const [isSyncing, setIsSyncing] = useState(false);
  const [saveMessage, setSaveMessage] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [uploadFiles, setUploadFiles] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState(null);
  const [analysisResults, setAnalysisResults] = useState(null);
  const [editLead, setEditLead] = useState(null);
  const [editCompany, setEditCompany] = useState(null);
  const [createAsProject, setCreateAsProject] = useState(false);

  const [form, setForm] = useState({
    project_name: "", company: "", domain: "", poc: "",
    ceo: "", industry: "", company_size: "Mid-Market", lead_info: ""
  });

  useEffect(() => { fetchCompanies(); }, []);

  useEffect(() => {
    if (activeLead) setEditLead({ ...activeLead });
    else setEditLead(null);
  }, [activeLead]);

  useEffect(() => {
    if (activeCompany) setEditCompany({ ...activeCompany });
    else setEditCompany(null);
  }, [activeCompany]);

  const hasLeadChanges = activeLead && editLead
    ? JSON.stringify({ ...activeLead, leads: undefined }) !== JSON.stringify({ ...editLead, leads: undefined })
    : false;

  const hasCompanyChanges = activeCompany && editCompany
    ? JSON.stringify({ ...activeCompany, leads: undefined }) !== JSON.stringify({ ...editCompany, leads: undefined })
    : false;

  const fetchCompanies = async () => {
    setIsLoading(true);
    try {
      const data = await getCompanies();
      if (data?.companies) setCompanies(data.companies);
    } catch (err) {
      console.error("Fetch companies failed:", err);
    } finally {
      setIsLoading(false);
    }
  };

  const openProjectForm = () => {
    setCreateAsProject(true);
    setView("form");
  };

  const openLeadDetail = async (lead) => {
    if (!lead?.id) return;
    setActiveLead(lead);
    try {
      const res = await getLead(lead.id);
      if (res?.lead) {
        setActiveLead(res.lead);
        return res.lead;
      }
    } catch (err) {
      console.error("Load lead detail failed:", err);
    }
    return lead;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSyncing(true);
    try {
      const shouldOpenProject = createAsProject;
      const payload = {
        ...form,
        status: shouldOpenProject ? "accepted" : (form.status || "new"),
        project_stage: shouldOpenProject ? "requirements" : (form.project_stage || "lead_pipeline")
      };
      const res = await registerLead(payload);
      const savedLead = res?.lead || res?.data?.lead || { ...payload, id: res?.lead_id || payload.id };
      setForm({ project_name: "", company: "", domain: "", poc: "", ceo: "", industry: "", company_size: "Mid-Market", lead_info: "" });
      setCreateAsProject(false);
      setView("grid");
      await fetchCompanies();
      if (onRefresh) await onRefresh();
      if (shouldOpenProject && onSelectLead) {
        onSelectLead(savedLead);
      }
    } catch (err) {
      console.error("Lead creation failed:", err);
    } finally {
      setIsSyncing(false);
    }
  };

  const handleSaveLead = async () => {
    setIsSyncing(true);
    try {
      await registerLead(editLead);
      setActiveLead(editLead);
      setSaveMessage("Changes Saved!");
      setTimeout(() => setSaveMessage(null), 3000);
      await fetchCompanies();
    } catch (err) {
      console.error("Save lead failed:", err);
    } finally {
      setIsSyncing(false);
    }
  };

  const handleSaveCompany = async () => {
    setIsSyncing(true);
    try {
      await updateCompany(activeCompany.id, editCompany);
      setActiveCompany({ ...activeCompany, ...editCompany });
      setSaveMessage("Company Updated!");
      setTimeout(() => setSaveMessage(null), 3000);
      await fetchCompanies();
    } catch (err) {
      console.error("Save company failed:", err);
    } finally {
      setIsSyncing(false);
    }
  };

  const handleToggleStatus = async (lead, e) => {
    e?.stopPropagation();
    const convertingToProject = !isProjectLead(lead);
    const newStatus = convertingToProject ? "accepted" : "new";
    const nextStage = convertingToProject ? "requirements" : "lead_pipeline";
    setIsSyncing(true);
    
    // Optimistic Update: Update the main companies list instantly
    setCompanies(prev => prev.map(c => ({
      ...c,
      leads: (c.leads || []).map(l => l.id === lead.id ? { ...l, status: newStatus } : l)
    })));

    try {
      await registerLead({ ...lead, status: newStatus, project_stage: nextStage });
      if (activeCompany) {
        const updatedLeads = activeCompany.leads.map(l =>
          l.id === lead.id ? { ...l, status: newStatus, project_stage: nextStage } : l
        );
        setActiveCompany({ ...activeCompany, leads: updatedLeads });
      }
      if (activeLead?.id === lead.id) setActiveLead({ ...lead, status: newStatus, project_stage: nextStage });
      await fetchCompanies();
    } catch (err) {
      console.error("Toggle status failed:", err);
      await fetchCompanies();
    } finally { setIsSyncing(false); }
  };

  const handleDeleteLead = async (lid, e) => {
    e?.stopPropagation();
    if (!window.confirm("Are you sure you want to delete this lead? All associated history will be purged.")) return;
    
    // Optimistic Update: Remove from local state instantly
    setCompanies(prev => prev.map(c => ({
      ...c,
      leads: (c.leads || []).filter(l => l.id !== lid)
    })));
    if (activeCompany) {
      setActiveCompany({ ...activeCompany, leads: (activeCompany.leads || []).filter(l => l.id !== lid) });
    }

    try {
      await deleteLead(lid);
      if (activeLead?.id === lid) setActiveLead(null);
      await fetchCompanies();
      if (onRefresh) onRefresh();
    } catch (err) { 
      console.error(err);
      await fetchCompanies(); // Revert if failed
    }
  };

  const handleLookup = async (domain) => {
    if (!domain || domain.length < 4) return;
    try {
      const res = await lookupCompany(domain);
      if (res.status === "found") {
        const co = res.company;
        setForm(prev => ({
          ...prev,
          company: co.name || prev.company,
          ceo: co.ceo || prev.ceo,
          poc: co.poc || prev.poc,
          industry: co.industry || prev.industry,
          company_size: co.company_size || prev.company_size,
        }));
        setSaveMessage(`Metadata Synced: ${co.name}`);
        setTimeout(() => setSaveMessage(null), 3000);
      }
    } catch (err) { console.error("Lookup failed:", err); }
  };

  const handleDeleteCompany = async (cid, e) => {
    e?.stopPropagation();
    if (!window.confirm("Delete this company and ALL its leads? This cannot be undone.")) return;
    
    // Optimistic Update
    const originalCompanies = [...companies];
    setCompanies(prev => prev.filter(c => c.id !== cid));

    try {
      await deleteCompany(cid);
      if (activeCompany?.id === cid) { setActiveCompany(null); setView("grid"); }
      await fetchCompanies();
    } catch (err) { 
      console.error(err);
      setCompanies(originalCompanies); // Revert on failure
    }
  };

  // Upload handlers
  const handleDrag = (e) => {
    e.preventDefault(); e.stopPropagation();
    setDragActive(e.type === "dragenter" || e.type === "dragover");
  };
  const handleDrop = (e) => {
    e.preventDefault(); e.stopPropagation(); setDragActive(false);
    if (e.dataTransfer.files?.[0]) setUploadFiles([...uploadFiles, ...Array.from(e.dataTransfer.files)]);
  };
  const executeAnalysis = async () => {
    if (!uploadFiles.length) return;
    setIsUploading(true); setUploadStatus(null);
    try {
      const res = await analyzeDocuments(uploadFiles);
      const normalizedAnalysis = (res?.analysis || []).map((item) => ({
        ...item,
        fallback_ingested: Boolean(item?.fallback_ingested),
      }));
      setAnalysisResults(normalizedAnalysis);
      setUploadStatus("Analysis complete. Pending review.");
    } catch { setUploadStatus("Error calling AI prediction agent."); }
    setIsUploading(false);
  };
  const handleConfirm = async () => {
    setIsUploading(true);
    try {
      const alreadyIngested = Array.isArray(analysisResults) && analysisResults.some((item) => item?.fallback_ingested);
      if (!alreadyIngested) {
        await confirmDocuments(analysisResults);
      }
      setUploadStatus("Success! Files ingested to selected silos.");
      setUploadFiles([]); setAnalysisResults(null);
    } catch { setUploadStatus("Error ingesting confirmed files."); }
    setIsUploading(false);
  };

  // All leads flat list for routing panel (excluding converted projects)
  const allLeads = companies.flatMap(c => (c.leads || []).filter(l => !isProjectLead(l)).map(l => ({ ...l, _companyName: c.name })));

  const visibleLeads = activeCompany ? (activeCompany.leads || []).filter(l => !isProjectLead(l)) : [];

  return (
    <div className="lead-forge-overlay">
      <div className="forge-container glass-panel-premium">

        {/* Sidebar Nav */}
        <div className="forge-sidebar">
          <div className="forge-logo">
            <div className="logo-icon-wrapper">
              <Sparkles className="pulse-slow" size={24} color="#3b82f6" />
            </div>
            <div className="logo-text">
              <span className="brand-name">LEAD FORGE</span>
              <span className="brand-tagline">INTELLIGENCE TERMINAL</span>
            </div>
          </div>

          <div className="forge-steps-nav">
            <div className={`step-item ${view === 'grid' || view === 'leads' ? 'active' : ''}`}
              onClick={() => { setView('grid'); setActiveCompany(null); setActiveLead(null); }}>
              <div className="step-num"><Building2 size={16} /></div>
              <div className="step-label">COMPANIES</div>
            </div>
            <div className={`step-item ${view === 'upload' ? 'active' : ''}`}
              onClick={() => { setView('upload'); setActiveLead(null); }}>
              <div className="step-num"><UploadCloud size={16} /></div>
              <div className="step-label">GLOBAL INTAKE</div>
            </div>
            <div className={`step-item ${view === 'form' ? 'active' : ''}`}
              onClick={() => setView('form')}>
              <div className="step-num"><Zap size={16} /></div>
              <div className="step-label">NEW LEAD</div>
            </div>
          </div>

          {/* Mini lead list in sidebar when inside a company */}
          {view === 'leads' && activeCompany && (
            <div style={{ marginTop: '20px', padding: '0 12px' }}>
              <div style={{ fontSize: '0.65rem', color: '#4b5563', letterSpacing: '1.5px', fontWeight: 700, textTransform: 'uppercase', marginBottom: '8px' }}>
                {activeCompany.name}
              </div>
              {visibleLeads.map(l => (
                <div key={l.id}
                  className={`step-item ${activeLead?.id === l.id ? 'active' : ''}`}
                  style={{ padding: '8px 10px', fontSize: '0.78rem' }}
                  onClick={() => openLeadDetail(l)}>
                  <Layers size={13} />
                  <span style={{ marginLeft: 8 }}>{l.project_name || 'Unnamed Lead'}</span>
                </div>
              ))}
              <div className="step-item" style={{ padding: '8px 10px', fontSize: '0.78rem', marginTop: 6 }}
                onClick={() => setView('form')}>
                <Plus size={13} /><span style={{ marginLeft: 8 }}>Add Lead</span>
              </div>
            </div>
          )}

          <div className="forge-usage-tip">
            <Activity size={14} color="#fbbf24" />
            <p>{companies.length} companies · {allLeads.length} leads</p>
          </div>
        </div>

        {/* Main Content */}
        <div className="forge-main custom-scroll">

          {/* ═══ COMPANY GRID ═══ */}
          {view === 'grid' && (
            <div className="anim-fade-in" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
              <div className="forge-header-block">
                <div className="title-area">
                  <h1 className="cyber-title">Company Registry <span className="title-decoration"></span></h1>
                  <p className="cyber-subtitle">{companies.length} active companies · {allLeads.length} total leads</p>
                </div>
                <div className="action-area">
                  <button className="btn-premium btn-new" onClick={() => setView("form")}>
                    <Plus size={16} /> NEW LEAD
                  </button>
                  <button className="btn-premium btn-new" onClick={openProjectForm} style={{ borderColor: 'rgba(251, 191, 36, 0.35)', color: '#fbbf24' }}>
                    <FolderGit2 size={16} /> NEW PROJECT
                  </button>
                </div>
              </div>

              <div className="forge-grid-container custom-scroll">
                {isLoading ? (
                  <div className="empty-state">
                    <Loader2 size={48} className="spin" color="#3b82f6" />
                    <h3 className="mt-20">Scanning Company Network...</h3>
                  </div>
                ) : companies.length === 0 ? (
                  <div className="empty-state">
                    <Building2 size={64} className="empty-icon" />
                    <h3>No companies yet</h3>
                    <p>Create your first lead and a company card will appear automatically.</p>
                    <div className="action-area mt-20">
                      <button className="btn-premium btn-new" onClick={() => setView("form")}>
                        CREATE FIRST LEAD
                      </button>
                      <button className="btn-premium btn-new" onClick={openProjectForm} style={{ borderColor: 'rgba(251, 191, 36, 0.35)', color: '#fbbf24' }}>
                        CREATE FIRST PROJECT
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="forge-grid">
                    {companies.map(co => (
                      <div key={co.id}
                        className="forge-card-premium"
                        onClick={() => { setActiveCompany(co); setActiveLead(null); setView('leads'); }}>
                        <div className="card-glare"></div>
                        <div className="card-header">
                          <div className="company-info">
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <Building2 size={16} color="#60a5fa" />
                              <h3>{co.name}</h3>
                            </div>
                            <span className="domain-tag">{co.domain}</span>
                          </div>
                        </div>
                        <div className="card-body">
                          <div className="info-row"><Globe size={14} className="icon" /><span>{co.industry || "—"}</span></div>
                          <div className="info-row"><Users size={14} className="icon" /><span>{co.poc || "No contact"}</span></div>
                          <div className="info-row">
                            <Layers size={14} className="icon" />
                            <span style={{ color: '#60a5fa', fontWeight: 600 }}>
                              {(co.leads || []).filter(l => !isProjectLead(l)).length} lead{((co.leads || []).filter(l => !isProjectLead(l)).length) !== 1 ? 's' : ''}
                            </span>
                          </div>
                        </div>
                        <div className="card-footer">
                          <button className="btn-card delete" onClick={(e) => handleDeleteCompany(co.id, e)}>
                            <Trash2 size={14} />
                          </button>
                          <div className="spacer"></div>
                          <button className="btn-card primary" onClick={(e) => { e.stopPropagation(); setActiveCompany(co); setActiveLead(null); setView('leads'); }}>
                            VIEW LEADS <ChevronRight size={14} />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ═══ LEADS INSIDE A COMPANY ═══ */}
          {view === 'leads' && activeCompany && (
            <div className="anim-fade-in" style={{ height: '100%', display: 'flex', flexDirection: 'column', position: 'relative' }}>
              {/* Company Header */}
              <div className="forge-header-block">
                <div className="title-area" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <button style={{ background: 'none', border: 'none', color: '#4b5563', cursor: 'pointer', padding: 0 }}
                    onClick={() => { setView('grid'); setActiveCompany(null); setActiveLead(null); }}>
                    <Building2 size={18} />
                  </button>
                  <ChevronRight size={14} color="#4b5563" />
                  <div>
                    <h1 className="cyber-title" style={{ fontSize: '1.4rem' }}>
                      {editCompany?.name || activeCompany.name}
                    </h1>
                    <p className="cyber-subtitle">{activeCompany.domain} · {visibleLeads.length} leads</p>
                  </div>
                </div>
                <div className="action-area">
                  {hasCompanyChanges && (
                    <button className="btn-cyber-success anim-fade-in"
                      style={{ height: 40, padding: '0 18px', borderRadius: 10, margin: 0 }}
                      onClick={handleSaveCompany} disabled={isSyncing}>
                      {isSyncing ? <Loader2 size={15} className="spin" /> : <>SAVE <CheckCircle2 size={14} /></>}
                    </button>
                  )}
                  <button className="btn-premium btn-new" onClick={() => setView("form")}>
                    <Plus size={16} /> ADD LEAD
                  </button>
                  <button className="btn-premium btn-new" onClick={openProjectForm} style={{ borderColor: 'rgba(251, 191, 36, 0.35)', color: '#fbbf24' }}>
                    <FolderGit2 size={16} /> ADD PROJECT
                  </button>
                </div>
              </div>

              {/* Company meta strip */}
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 24, padding: '0 4px' }}>
                {[
                  { label: 'Industry', field: 'industry', icon: <Briefcase size={13} /> },
                  { label: 'CEO', field: 'ceo', icon: <Users size={13} /> },
                  { label: 'POC', field: 'poc', icon: <Users size={13} /> },
                  { label: 'Scale', field: 'company_size', icon: <Activity size={13} /> },
                ].map(({ label, field, icon }) => (
                  <div key={field} className="meta-tile-premium">
                    <span className="meta-label">{icon} {label.toUpperCase()}</span>
                    <input
                      className="meta-input"
                      value={editCompany?.[field] || ''}
                      onChange={e => setEditCompany({ ...editCompany, [field]: e.target.value })}
                      onKeyDown={e => e.key === 'Enter' && handleSaveCompany()}
                    />
                  </div>
                ))}
              </div>

              {/* Leads grid */}
              <div className="forge-grid-container custom-scroll" style={{ flex: 1 }}>
                {visibleLeads.length === 0 ? (
                  <div className="empty-state">
                    <Layers size={48} className="empty-icon" />
                    <h3>No leads yet</h3>
                    <p>Add the first lead for {activeCompany.name}.</p>
                    <button className="btn-premium btn-new mt-20" onClick={() => setView("form")}>ADD LEAD</button>
                  </div>
                ) : (
                  <div className="forge-grid">
                    {visibleLeads.map(l => (
                      <div key={l.id}
                        className={`forge-card-premium ${activeLead?.id === l.id ? 'selected' : ''}`}
                        onClick={() => openLeadDetail(l)}>
                        <div className="card-glare"></div>
                        <div className="card-header">
                          <div className="company-info">
                            <h3>{l.lead_name || l.project_name || 'Untitled Lead'}</h3>
                            <span className="lead-poc-tag">{l.poc || 'No contact'}</span>
                          </div>
                        </div>
                        <div className="card-body">
                          <div className="info-row" style={{ marginTop: 8 }}>
                            <FileText size={14} className="icon" />
                            <span style={{ color: '#9ca3af', fontSize: '0.82rem', lineHeight: '1.5', height: '3.0em', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                              {l.lead_info || 'No project brief provided yet.'}
                            </span>
                          </div>
                        </div>
                        <div className="card-footer">
                          <button className="btn-card delete" onClick={(e) => handleDeleteLead(l.id, e)}><Trash2 size={14} /></button>
                          <div className="spacer"></div>
                          <button
                            className="btn-card launch"
                            style={{
                              background: isProjectLead(l) ? 'var(--warning)' : 'rgba(255,255,255,0.05)',
                              color: isProjectLead(l) ? '#000' : '#fff',
                              border: isProjectLead(l) ? 'none' : '1px solid var(--forge-border)'
                            }}
                            onClick={(e) => handleToggleStatus(l, e)}
                          >
                            {isProjectLead(l) ? "PROJECT" : "LAUNCH"}
                          </button>
                          <button className="btn-card primary" onClick={(e) => { e.stopPropagation(); openLeadDetail(l).then((detail) => onSelectLead(detail || l)); }}>CHAT</button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Lead Detail Panel */}
              {activeLead && (
                <div className="profile-detail-overlay anim-fade-in custom-scroll">
                  <div className="detail-header">
                    <div className="detail-title">
                      <input
                        className="edit-title-input"
                        value={editLead?.project_name || ''}
                        onChange={e => setEditLead({ ...editLead, project_name: e.target.value })}
                        onKeyDown={e => e.key === 'Enter' && handleSaveLead()}
                        placeholder={editLead?.lead_name || "Lead / Project Name..."}
                      />
                      <span className="detail-id">Lead ID: {activeLead.id}</span>
                    </div>
                    {saveMessage && (
                      <div className="save-toast anim-fade-in" style={{ position: 'absolute', top: 40, right: 100, background: 'rgba(16,185,129,0.1)', border: '1px solid rgba(16,185,129,0.4)', color: '#6ee7b7', padding: '6px 14px', borderRadius: 8, fontSize: '0.8rem', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 8, zIndex: 10 }}>
                        <CheckCircle2 size={14} /> {saveMessage}
                      </div>
                    )}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      {hasLeadChanges && (
                        <button className="btn-cyber-success anim-fade-in"
                          style={{ height: 44, padding: '0 20px', borderRadius: 12, margin: 0 }}
                          onClick={handleSaveLead} disabled={isSyncing}>
                          {isSyncing ? <Loader2 size={16} className="spin" /> : <>SAVE <CheckCircle2 size={16} /></>}
                        </button>
                      )}
                      <button
                        className="btn-card launch"
                        style={{
                          height: 44, padding: '0 20px', borderRadius: 12,
                          background: isProjectLead(editLead) ? 'var(--warning)' : 'rgba(255,255,255,0.05)',
                          color: isProjectLead(editLead) ? '#000' : '#fff',
                          border: isProjectLead(editLead) ? 'none' : '1px solid var(--forge-border)'
                        }}
                        onClick={(e) => handleToggleStatus(editLead, e)}
                      >
                        {isProjectLead(editLead) ? "PROJECT" : "LAUNCH"}
                      </button>
                      <button className="btn-card primary" style={{ height: 44, padding: '0 16px', borderRadius: 12 }}
                        onClick={() => { openLeadDetail(activeLead).then((detail) => onSelectLead(detail || activeLead)); }}>
                        CHAT <MessageSquare size={16} />
                      </button>
                      <button className="close-detail" onClick={() => setActiveLead(null)}><X size={20} /></button>
                    </div>
                  </div>

                  <div className="detail-content">
                    <div className="detail-grid">
                      <div className="detail-section">
                        <label><Users size={12} /> CONTACT & HIERARCHY</label>
                        <div className="detail-item-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '15px', marginTop: '10px' }}>
                          <div className="detail-item">
                            <strong>POC:</strong>
                            <input value={editLead?.poc || ''} onChange={e => setEditLead({ ...editLead, poc: e.target.value })} onKeyDown={e => e.key === 'Enter' && handleSaveLead()} />
                          </div>
                          <div className="detail-item">
                            <strong>CEO:</strong>
                            <input value={editLead?.ceo || ''} onChange={e => setEditLead({ ...editLead, ceo: e.target.value })} onKeyDown={e => e.key === 'Enter' && handleSaveLead()} />
                          </div>
                        </div>
                      </div>
                    </div>
                    <div className="detail-grid" style={{ marginTop: 20 }}>
                      <div className="detail-section">
                        <label><ShieldCheck size={12} /> FIRMOGRAPHICS</label>
                        <div className="detail-item-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '15px', marginTop: '10px' }}>
                          <div className="detail-item">
                            <strong>Industry:</strong>
                            <input value={editLead?.industry || ''} onChange={e => setEditLead({ ...editLead, industry: e.target.value })} onKeyDown={e => e.key === 'Enter' && handleSaveLead()} />
                          </div>
                          <div className="detail-item">
                            <strong>Scale:</strong>
                            <select
                              style={{ background: 'none', border: 'none', color: '#fff', fontSize: '0.85rem', width: '100%', outline: 'none' }}
                              value={editLead?.company_size || 'Mid-Market'}
                              onChange={e => setEditLead({ ...editLead, company_size: e.target.value })}
                            >
                              <option>Startup</option><option>Mid-Market</option><option>Enterprise</option><option>Fortune 500</option>
                            </select>
                          </div>
                        </div>
                      </div>
                    </div>
                    <div className="detail-section" style={{ marginTop: 24 }}>
                      <label><FileText size={12} /> PROJECT BRIEF</label>
                      <textarea
                        className="edit-intelligence-area custom-scroll"
                        value={editLead?.lead_info || ''}
                        placeholder="Key requirements, context, goals..."
                        onChange={e => setEditLead({ ...editLead, lead_info: e.target.value })}
                      />
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ═══ GLOBAL INTAKE (UPLOAD) ═══ */}
          {view === 'upload' && (
            <div className="anim-fade-in" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
              <div className="forge-header-block" style={{ marginTop: '20px' }}>
                <div className="title-area">
                  <h1 className="cyber-title">Global Intake Zone <span className="title-decoration"></span></h1>
                  <p className="cyber-subtitle">Agentic Multi-Thread Parsing & Autonomous Routing Sandbox.</p>
                </div>
              </div>
              <div className={`dropzone-area ${dragActive ? 'drag-active' : ''}`}
                onDragEnter={handleDrag} onDragLeave={handleDrag} onDragOver={handleDrag} onDrop={handleDrop}
                style={{ border: dragActive ? '2px dashed #fbbf24' : '2px dashed #4b5563', padding: '60px', textAlign: 'center', borderRadius: '12px', marginTop: '40px', background: 'rgba(59,130,246,0.05)', transition: 'all 0.3s' }}>
                <UploadCloud size={64} color="#fbbf24" style={{ margin: '0 auto 20px auto' }} />
                <h2 style={{ color: '#fff', fontSize: '1.2rem', marginBottom: '10px' }}>Drag & Drop Intelligence Artifacts</h2>
                <p style={{ color: '#9ca3af', marginBottom: '20px' }}>PDFs, DOCX, EML (with attachments), Text files</p>
                <input type="file" multiple id="fileUpload" style={{ display: 'none' }}
                  onChange={(e) => setUploadFiles([...uploadFiles, ...Array.from(e.target.files)])} />
                <label htmlFor="fileUpload" className="btn-secondary" style={{ cursor: 'pointer' }}>BROWSE FILES</label>
              </div>

              {uploadFiles.length > 0 && (
                <div className="upload-queue anim-fade-in" style={{ marginTop: '30px', background: 'rgba(15,23,42,0.6)', padding: '25px', borderRadius: '16px', border: '1px solid rgba(59,130,246,0.1)', backdropFilter: 'blur(10px)' }}>
                  <h3 style={{ color: '#fff', marginBottom: '20px', fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '8px' }}><Activity size={16} color="#3b82f6" /> DATA QUEUE</h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    {uploadFiles.map((f, i) => (
                      <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', background: 'rgba(0,0,0,0.3)', borderRadius: '8px', color: '#e5e7eb', fontSize: '0.9rem', borderLeft: '3px solid #3b82f6' }}>
                        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}><FileText size={16} color="#60a5fa" /><span>{f.name}</span></div>
                        <span style={{ color: '#6b7280', fontSize: '0.8rem' }}>{(f.size / 1024 / 1024).toFixed(2)} MB</span>
                      </div>
                    ))}
                  </div>
                  <div style={{ marginTop: '25px', display: 'flex', justifyContent: 'flex-end', gap: '15px' }}>
                    <button className="btn-secondary" style={{ padding: '0 20px', borderRadius: '8px' }} onClick={() => setUploadFiles([])} disabled={isUploading || !!analysisResults}>CLEAR</button>
                    <button className="btn-finish-premium" style={{ display: 'flex', alignItems: 'center', padding: '0 24px', height: '44px', borderRadius: '8px', gap: '8px', fontWeight: 600 }} onClick={executeAnalysis} disabled={isUploading || !!analysisResults}>
                      {isUploading ? <Loader2 size={18} className="spin" /> : 'ENGAGE AI ROUTER'} {!isUploading && <Sparkles size={18} />}
                    </button>
                  </div>
                </div>
              )}

              {analysisResults && (
                <div className="analysis-review-panel anim-fade-in" style={{ marginTop: '30px', padding: '30px', background: 'rgba(20,20,30,0.7)', backdropFilter: 'blur(12px)', borderRadius: '16px', border: '1px solid rgba(251,191,36,0.4)', boxShadow: '0 10px 40px rgba(0,0,0,0.5)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '25px', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '15px' }}>
                    <div style={{ background: 'rgba(251,191,36,0.1)', padding: '8px', borderRadius: '8px', display: 'flex' }}><ShieldCheck size={24} color="#fbbf24" /></div>
                    <div>
                      <h3 style={{ color: '#fff', fontSize: '1.2rem', margin: 0 }}>Intelligence Verification</h3>
                      <p style={{ color: '#9ca3af', fontSize: '0.85rem', margin: '4px 0 0 0' }}>Review and override the AI's autonomous silo targeting.</p>
                    </div>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                    {analysisResults.map((item, idx) => (
                      <div key={idx} style={{ padding: '20px', background: 'rgba(255,255,255,0.03)', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.05)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '20px' }}>
                          <FileText size={18} color="#9ca3af" />
                          <h4 style={{ color: '#e5e7eb', margin: 0, fontWeight: 500 }}>{item.filename}</h4>
                        </div>
                        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                          {allLeads.map(lead => {
                            const isSelected = item.predicted_leads.includes(lead.id);
                            return (
                              <div key={lead.id}
                                onClick={() => {
                                  const n = [...analysisResults];
                                  n[idx].predicted_leads = isSelected
                                    ? n[idx].predicted_leads.filter(id => id !== lead.id)
                                    : [...n[idx].predicted_leads, lead.id];
                                  setAnalysisResults(n);
                                }}
                                style={{ padding: '8px 16px', borderRadius: '24px', fontSize: '0.85rem', cursor: 'pointer', transition: 'all 0.2s', background: isSelected ? 'rgba(59,130,246,0.2)' : 'rgba(0,0,0,0.2)', border: isSelected ? '1px solid rgba(96,165,250,0.5)' : '1px solid rgba(255,255,255,0.1)', color: isSelected ? '#93c5fd' : '#9ca3af', display: 'flex', alignItems: 'center', gap: 6 }}>
                                {isSelected && <CheckCircle2 size={14} />}
                                {lead.project_name || lead._companyName}
                              </div>
                            );
                          })}
                          <div onClick={() => {
                            const n = analysisResults.filter((_, i) => i !== idx);
                            setAnalysisResults(n.length ? n : null);
                          }} style={{ padding: '8px 16px', borderRadius: '24px', fontSize: '0.85rem', cursor: 'pointer', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', color: '#f87171', display: 'flex', alignItems: 'center', gap: 6 }}>
                            <Trash2 size={14} /> Discard
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '15px', marginTop: '30px', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '20px' }}>
                    <button className="btn-secondary" style={{ padding: '0 24px', height: '44px', borderRadius: '8px' }} onClick={() => setAnalysisResults(null)} disabled={isUploading}>ABORT</button>
                    <button style={{ background: 'linear-gradient(135deg,#10b981,#059669)', color: '#fff', border: 'none', padding: '0 24px', height: '44px', borderRadius: '8px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }} onClick={handleConfirm} disabled={isUploading}>
                      {isUploading ? <Loader2 size={18} className="spin" /> : 'AUTHORIZE INGESTION'} {!isUploading && <CheckCircle2 size={18} />}
                    </button>
                  </div>
                </div>
              )}

              {uploadStatus && !analysisResults && (
                <div className="anim-fade-in" style={{ marginTop: '20px', padding: '15px', background: uploadStatus.includes('Error') ? 'rgba(239,68,68,0.1)' : 'rgba(16,185,129,0.1)', border: uploadStatus.includes('Error') ? '1px solid rgba(239,68,68,0.3)' : '1px solid rgba(16,185,129,0.3)', color: uploadStatus.includes('Error') ? '#fca5a5' : '#6ee7b7', borderRadius: '8px', fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <Activity size={18} /> {uploadStatus}
                </div>
              )}
            </div>
          )}

          {/* ═══ NEW LEAD FORM ═══ */}
          {view === 'form' && (
            <form onSubmit={handleSubmit} className="forge-form-wrapper anim-fade-in">
              <div className="forge-header-block" style={{ marginTop: '20px' }}>
                <div className="title-area">
                  <h1 className="cyber-title">New Lead <span className="title-decoration"></span></h1>
                  <p className="cyber-subtitle">Company details will auto-match or create a new company card.</p>
                </div>
              </div>

              <div className="forge-form-grid" style={{ marginTop: '40px' }}>
                {/* --- Section 1: Company Intelligence --- */}
                <div style={{ gridColumn: '1 / -1', marginBottom: '10px' }}>
                  <h3 style={{ fontSize: '0.75rem', color: '#60a5fa', letterSpacing: '2px', fontWeight: 800 }}>COMPANY INTELLIGENCE</h3>
                  <div style={{ height: '1px', background: 'linear-gradient(90deg, #3b82f6, transparent)', marginTop: '8px' }}></div>
                </div>

                <div className="input-field">
                  <label><Building2 size={14} /> COMPANY NAME</label>
                  <input placeholder="e.g. Acme Inc" value={form.company} required
                    onChange={e => setForm({ ...form, company: e.target.value })} />
                </div>
                <div className="input-field">
                  <label><Globe size={14} /> COMPANY DOMAIN</label>
                  <input placeholder="e.g. acme.com" value={form.domain} required
                    onChange={e => setForm({ ...form, domain: e.target.value })}
                    onBlur={e => handleLookup(e.target.value)}
                  />
                </div>
                <div className="input-field">
                  <label><Users size={14} /> COMPANY CEO</label>
                  <input placeholder="e.g. Elon Musk" value={form.ceo || ''}
                    onChange={e => setForm({ ...form, ceo: e.target.value })} />
                </div>
                <div className="input-field">
                  <label><ShieldCheck size={14} /> INDUSTRY</label>
                  <input placeholder="e.g. Manufacturing" value={form.industry}
                    onChange={e => setForm({ ...form, industry: e.target.value })} />
                </div>
                <div className="input-field full">
                  <label><Users size={14} /> COMPANY SIZE</label>
                  <select value={form.company_size} onChange={e => setForm({ ...form, company_size: e.target.value })}>
                    <option>Startup</option><option>Mid-Market</option>
                    <option>Enterprise</option><option>Fortune 500</option>
                  </select>
                </div>

                {/* --- Section 2: Lead Context --- */}
                <div style={{ gridColumn: '1 / -1', marginTop: '30px', marginBottom: '10px' }}>
                  <h3 style={{ fontSize: '0.75rem', color: '#fbbf24', letterSpacing: '2px', fontWeight: 800 }}>LEAD CONTEXT</h3>
                  <div style={{ height: '1px', background: 'linear-gradient(90deg, #fbbf24, transparent)', marginTop: '8px' }}></div>
                </div>

                <div className="input-field">
                  <label><Plus size={14} /> LEAD / PROJECT NAME</label>
                  <input placeholder="e.g. CRM Automation Project" value={form.project_name} required
                    onChange={e => setForm({ ...form, project_name: e.target.value })} />
                </div>
                <div className="input-field">
                  <label><Users size={14} /> PERSON OF CONTACT</label>
                  <input placeholder="e.g. John Doe, CTO" value={form.poc}
                    onChange={e => setForm({ ...form, poc: e.target.value })} />
                </div>

                <div className="input-field full" style={{ marginTop: 10 }}>
                  <label><FileText size={14} /> PROJECT BRIEF / REQUIREMENTS</label>
                  <textarea placeholder="Key context, goals, requirements..." value={form.lead_info}
                    onChange={e => setForm({ ...form, lead_info: e.target.value })}
                    className="custom-scroll"
                    style={{ width: '100%', background: 'rgba(15,23,42,0.4)', border: '1px solid rgba(59,130,246,0.2)', borderRadius: 8, padding: '12px 16px', color: '#eff6ff', fontSize: '0.95rem', minHeight: 120, resize: 'none', outline: 'none' }} />
                </div>

                <div className="input-field full" style={{ marginTop: 10 }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <input
                      type="checkbox"
                      checked={createAsProject}
                      onChange={(e) => setCreateAsProject(e.target.checked)}
                      style={{ accentColor: '#fbbf24' }}
                    />
                    CREATE AS PROJECT
                  </label>
                  <p style={{ margin: '8px 0 0', color: '#9ca3af', fontSize: '0.82rem', lineHeight: 1.5 }}>
                    Skip the lead-only path and start directly in the project workflow with accepted status and requirements stage.
                  </p>
                </div>
              </div>

              <div className="forge-form-footer" style={{ marginTop: '40px' }}>
                <button type="button" className="btn-secondary" onClick={() => setView(activeCompany ? 'leads' : 'grid')}>CANCEL</button>
                <div className="spacer"></div>
                <button type="submit" className="btn-finish-premium" disabled={isSyncing}>
                  {isSyncing ? <Loader2 size={18} className="spin" /> : (createAsProject ? 'CREATE PROJECT' : 'CREATE LEAD')} <Zap size={18} />
                </button>
              </div>
            </form>
          )}

        </div>
      </div>
    </div>
  );
}
