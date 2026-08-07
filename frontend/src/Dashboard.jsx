import React, { useState, useEffect } from 'react';
import {
  LayoutDashboard, Users, FolderKanban, TrendingUp,
  Building2, Layers, Activity, ChevronRight, Sparkles, Zap,
  ArrowUpRight, Clock, Plus, Rocket, Brain, FolderKanban as FolderIcon, Trash2
} from 'lucide-react';
import { getCompanies, deleteLead } from './api';
import LeadForge from './LeadForge';
import './Dashboard.css';

const isProjectLead = (lead) => {
  const status = (lead?.status || "").toLowerCase();
  const stage = (lead?.project_stage || "").toLowerCase();
  return status === "accepted" || status === "launched" || stage === "requirements";
};

/* ═══════════════════════════════════
   DASHBOARD HOME VIEW
   ═══════════════════════════════════ */
const DashboardHome = ({ stats, companies, onNavigate, onSelectLead }) => {
  const activeLeads = companies.flatMap(c =>
    (c.leads || []).filter(l => !isProjectLead(l)).map(l => ({ ...l, _companyName: c.name }))
  ).slice(0, 6);

  return (
    <div className="dash-home custom-scroll">
      {/* Ambient Aurora */}
      <div className="dash-home-aurora">
        <div className="aurora-orb orb-1"></div>
        <div className="aurora-orb orb-2"></div>
        <div className="aurora-orb orb-3"></div>
      </div>

      {/* Hero */}
      <div className="dash-hero">
        <div className="dash-hero-badge">
          <Sparkles size={14} /> COMMAND CENTER
        </div>
        <h1 className="dash-hero-title">
          Welcome to <span className="gradient-text">Vilje</span>
        </h1>
        <p className="dash-hero-subtitle">
          Orchestrate your automation pipelines, technical workflows, and project intelligence from a single terminal.
        </p>
      </div>

      {/* Stats Grid */}
      <div className="dash-stats-grid">
        <div className="dash-stat-card" onClick={() => onNavigate('leads')}>
          <div className="stat-card-icon blue">
            <Building2 size={22} />
          </div>
          <div className="stat-card-info">
            <span className="stat-card-value">{stats.companies}</span>
            <span className="stat-card-label">Companies</span>
          </div>
          <div className="stat-card-trend"><ArrowUpRight size={16} /></div>
        </div>

        <div className="dash-stat-card" onClick={() => onNavigate('leads')}>
          <div className="stat-card-icon indigo">
            <Users size={22} />
          </div>
          <div className="stat-card-info">
            <span className="stat-card-value">{stats.leads}</span>
            <span className="stat-card-label">Active Leads</span>
          </div>
          <div className="stat-card-trend"><ArrowUpRight size={16} /></div>
        </div>

        <div className="dash-stat-card" onClick={() => onNavigate('projects')}>
          <div className="stat-card-icon amber">
            <FolderKanban size={22} />
          </div>
          <div className="stat-card-info">
            <span className="stat-card-value">{stats.projects || 0}</span>
            <span className="stat-card-label">Projects</span>
          </div>
          <div className="stat-card-trend"><ArrowUpRight size={16} /></div>
        </div>
      </div>

      {/* Quick Actions */}
      <div className="dash-section">
        <h2 className="dash-section-title">Quick Actions</h2>
        <div className="dash-actions-grid">
          <div className="dash-action-card" onClick={() => onNavigate('leads')}>
            <div className="action-card-icon">
              <Plus size={24} />
            </div>
            <div className="action-card-text">
              <h3>Project Inbound</h3>
              <p>Initialize a new project context silo</p>
            </div>
            <ChevronRight size={18} className="action-card-arrow" />
          </div>

          <div className="dash-action-card" onClick={() => onNavigate('leads')}>
            <div className="action-card-icon brain">
              <Brain size={24} />
            </div>
            <div className="action-card-text">
              <h3>Agentic Audit</h3>
              <p>Trigger RAG analysis on inbound data</p>
            </div>
            <ChevronRight size={18} className="action-card-arrow" />
          </div>

          <div className="dash-action-card" onClick={() => onNavigate('projects')}>
            <div className="action-card-icon amber-action">
              <FolderKanban size={24} />
            </div>
            <div className="action-card-text">
              <h3>Projects</h3>
              <p>View and manage your projects</p>
            </div>
            <ChevronRight size={18} className="action-card-arrow" />
          </div>
        </div>
      </div>

      {/* Active Leads */}
      {activeLeads.length > 0 && (
        <div className="dash-section">
          <div className="dash-section-header">
            <h2 className="dash-section-title">Active Leads</h2>
            <button className="dash-see-all" onClick={() => onNavigate('leads')}>
              View All <ChevronRight size={14} />
            </button>
          </div>
          <div className="dash-recent-list">
            {activeLeads.map(lead => (
              <div key={lead.id} className="dash-recent-item" onClick={() => onSelectLead(lead)}>
                <div className="recent-item-avatar">
                  <span style={{ fontWeight: 'bold', color: '#60a5fa' }}>LA</span>
                </div>
                <div className="recent-item-info">
                  <span className="recent-item-name">{lead.lead_name || lead.project_name || 'Unnamed Lead'}</span>
                  <span className="recent-item-meta">
                    {lead._companyName} · {lead.poc || 'No POC'}
                  </span>
                </div>
                <div className="recent-item-industry" style={{ display: 'flex', gap: '8px' }}>
                  <span className="meta-tag"><Activity size={12} /> Pending Analysis</span>
                </div>
                <ChevronRight size={16} className="recent-item-arrow" />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

/* ═══════════════════════════════════
   PROJECTS PIPELINE VIEW
   ═══════════════════════════════════ */
const ProjectsPipeline = ({ companies, onSelectLead, onOpenPipeline, onDeleteProject, user }) => {
  const [activeCompany, setActiveCompany] = useState(null);

  // Filter companies that have at least one converted/accepted project
  const companiesWithProjects = companies.map(c => ({
    ...c,
    launchedLeads: (c.leads || []).filter(isProjectLead)
  })).filter(c => c.launchedLeads.length > 0);

  // Total projects count
  const totalProjects = companiesWithProjects.reduce((acc, c) => acc + c.launchedLeads.length, 0);

  if (activeCompany) {
    const projects = activeCompany.launchedLeads;

    return (
      <div className="dash-home custom-scroll">
        <div className="dash-hero">
          <div className="dash-hero-badge" style={{ borderColor: 'rgba(251, 191, 36, 0.3)', color: '#fbbf24', background: 'rgba(251, 191, 36, 0.08)' }}>
            <button onClick={() => setActiveCompany(null)} className="back-link">
              <ChevronRight size={14} style={{ transform: 'rotate(180deg)' }} /> BACK TO COMPANIES
            </button>
          </div>
          <h1 className="dash-hero-title">
            {activeCompany.name} <span className="gradient-text">Project Pipeline</span>
          </h1>
          <p className="dash-hero-subtitle">
            Managing {projects.length} active intelligence silo{projects.length !== 1 ? 's' : ''} for this entity.
          </p>
        </div>

        <div className="dash-section">
          <div className="projects-grid">
            {projects.map(p => (
              <div key={p.id} className="project-card" onClick={() => onOpenPipeline(p)}>
                <div className="project-card-glare"></div>

                <div className="project-card-header">
                  <div className="project-status-dot"></div>
                  <span className="project-company">{activeCompany.name}</span>
                </div>

                <div className="project-card-body">
                  <h3 className="project-title">{p.lead_name || p.project_name || 'Untitled Project'}</h3>
                  <div className="project-meta">
                    <span className="meta-tag"><Users size={12} /> {p.poc || 'No POC'}</span>
                    <span className="meta-tag"><Activity size={12} /> Priority</span>
                  </div>
                </div>

                <div className="project-card-footer">
                  <div className="project-stats" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <button
                      className="delete-project-btn"
                      onClick={(e) => { e.stopPropagation(); onDeleteProject(p.id); }}
                      title="Delete Project"
                    >
                      <Trash2 size={14} />
                    </button>
                    <span>Launched</span>
                  </div>
                  <button className="project-action-btn glass-btn" onClick={(e) => { e.stopPropagation(); onOpenPipeline(p); }}>
                    VIEW PIPELINE <ArrowUpRight size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // Calculate flattened items: 
  // If a company has > 1 project, show the company card (folder).
  // If a company has exactly 1 project, show that project card directly.
  const flattenedProjects = companiesWithProjects.reduce((acc, co) => {
    if (co.launchedLeads.length > 1) {
      acc.push({ type: 'company', data: co });
    } else if (co.launchedLeads.length === 1) {
      acc.push({ type: 'project', data: co.launchedLeads[0], companyName: co.name });
    }
    return acc;
  }, []);

  return (
    <div className="dash-home custom-scroll">
      <div className="dash-hero">
        <div className="dash-hero-badge" style={{ borderColor: 'rgba(251, 191, 36, 0.3)', color: '#fbbf24', background: 'rgba(251, 191, 36, 0.08)' }}>
          <FolderKanban size={14} /> ACTIVE PIPELINE
        </div>
        <h1 className="dash-hero-title">
          Project Intelligence <span className="gradient-text">Hub</span>
        </h1>
        <p className="dash-hero-subtitle">
          Orchestrating {totalProjects} successfully launched intelligence silos across {companiesWithProjects.length} entities.
        </p>
      </div>

      <div className="dash-section">
        {flattenedProjects.length === 0 ? (
          <div className="dash-placeholder anim-fade-in" style={{ height: '300px' }}>
            <div className="placeholder-content">
              <div className="placeholder-icon-ring">
                <Rocket size={48} color="#4b5563" />
              </div>
              <h3 style={{ margin: 0, fontSize: '1.2rem' }}>No Active Projects</h3>
              <p style={{ margin: 0, color: '#6b7280' }}>Launch leads from the Company Registry to see them here.</p>
            </div>
          </div>
        ) : (
          <div className="projects-grid">
            {flattenedProjects.map(item => {
              if (item.type === 'company') {
                const co = item.data;
                return (
                  <div key={`co-${co.id}`} className="project-card company-group-card" onClick={() => setActiveCompany(co)}>
                    <div className="project-card-glare"></div>
                    <div className="project-card-header">
                      <div className="project-status-dot active"></div>
                      <span className="project-company">{co.domain}</span>
                    </div>
                    <div className="project-card-body">
                      <h3 className="project-title">{co.name}</h3>
                      <div className="project-meta">
                        <span className="meta-tag"><Layers size={12} /> {co.launchedLeads.length} Projects</span>
                        <span className="meta-tag"><Building2 size={12} /> Cluster Hub</span>
                      </div>
                    </div>
                    <div className="project-card-footer">
                      <div className="project-stats">
                        <span className="pulse-dot" style={{ background: '#fbbf24' }}></span>
                        <span>Multi-Project Hub</span>
                      </div>
                      <button className="project-action-btn glass-btn">
                        OPEN CLUSTER <ChevronRight size={14} />
                      </button>
                    </div>
                  </div>
                );
              } else {
                const p = item.data;
                return (
                  <div key={`p-${p.id}`} className="project-card" onClick={() => onOpenPipeline(p)}>
                    <div className="project-card-glare"></div>
                    <div className="project-card-header">
                      <div className="project-status-dot active"></div>
                      <span className="project-company">{item.companyName}</span>
                    </div>
                    <div className="project-card-body">
                      <h3 className="project-title">{p.lead_name || p.project_name || 'Untitled Project'}</h3>
                      <div className="project-meta">
                        <span className="meta-tag"><Users size={12} /> {p.poc || 'No POC'}</span>
                        <span className="meta-tag"><Activity size={12} /> Active Silo</span>
                      </div>
                    </div>
                    <div className="project-card-footer">
                      <div className="project-stats">
                        <button className="delete-project-btn" onClick={(e) => { e.stopPropagation(); onDeleteProject(p.id); }}>
                          <Trash2 size={14} />
                        </button>
                        <span>Launched</span>
                      </div>
                      <button className="project-action-btn glass-btn">
                        VIEW PIPELINE <ArrowUpRight size={14} />
                      </button>
                    </div>
                  </div>
                );
              }
            })}
          </div>
        )}
      </div>
    </div>
  );
};

/* ═══════════════════════════════════
   MAIN DASHBOARD COMPONENT
   ═══════════════════════════════════ */
export default function Dashboard({ onSelectLead, onOpenPipeline, leads, onRefresh, activeSection, setActiveSection, user }) {
  const [companies, setCompanies] = useState([]);
  const [stats, setStats] = useState({ companies: 0, leads: 0, launched: 0 });

  useEffect(() => { fetchStats(); }, []);

  const fetchStats = async () => {
    try {
      const data = await getCompanies();
      if (data?.companies) {
        const allLeads = data.companies.flatMap(c => c.leads || []);
        const activeLeads = allLeads.filter(l => !isProjectLead(l));
        const activeProjects = allLeads.filter(isProjectLead);
        setCompanies(data.companies);
        setStats({
          companies: data.companies.length,
          leads: activeLeads.length,
          projects: activeProjects.length
        });
      }
    } catch (err) {
      console.error('Stats fetch failed:', err);
    }
  };

  const handleDeleteProject = async (leadId) => {
    if (!window.confirm("Are you sure you want to permanently delete this project silo?")) return;
    try {
      await deleteLead(leadId);
      if (onRefresh) await onRefresh();
      await fetchStats();
    } catch (e) {
      console.error("Failed to delete project:", e);
    }
  };

  const navItems = [
    { id: 'home', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'leads', label: 'Leads', icon: Users },
    { id: 'projects', label: 'Projects', icon: FolderKanban },
  ];

  return (
    <div className="dashboard-layout">
      {/* ── Sidebar ── */}
      <aside className={`dash-sidebar ${activeSection !== 'home' ? 'collapsed' : ''}`}>
        <div className="dash-sidebar-inner">
          {/* Logo */}
          <div className="dash-sidebar-header">
            <div className="dash-logo" onClick={() => setActiveSection('home')}>
              <div className="dash-logo-icon">
                <Sparkles size={20} />
              </div>
              <div className="dash-logo-text">
                <span className="dash-brand">LEAD CONTROL</span>
                <span className="dash-tagline">COMMAND CENTER</span>
              </div>
            </div>
          </div>

          {/* Navigation */}
          <nav className="dash-nav">
            <div className="dash-nav-section-label">MAIN MENU</div>
            {navItems.map(item => (
              <button
                key={item.id}
                className={`dash-nav-item ${activeSection === item.id ? 'active' : ''}`}
                onClick={() => setActiveSection(item.id)}
                data-tooltip={item.label}
              >
                <div className="dash-nav-icon-box">
                  <item.icon size={18} />
                </div>
                <span className="dash-nav-label">{item.label}</span>
                {activeSection === item.id && <div className="dash-nav-active-dot"></div>}
              </button>
            ))}
          </nav>

          {/* Footer Stats */}
          <div className="dash-sidebar-bottom">
            <div className="dash-quick-stat">
              <Activity size={14} className="dash-stat-pulse" />
              <span>{stats.companies} companies · {stats.leads} leads</span>
            </div>
          </div>
        </div>
      </aside>

      {/* ── Content ── */}
      <main className="dash-main">
        {activeSection === 'home' && (
          <DashboardHome
            stats={stats}
            companies={companies}
            onNavigate={setActiveSection}
            onSelectLead={onSelectLead}
          />
        )}

        {activeSection === 'leads' && (
          <div className="dash-leadforge-wrapper">
            <LeadForge
              onSelectLead={onSelectLead}
              leads={leads}
              onRefresh={() => { onRefresh(); fetchStats(); }}
              user={user}
            />
          </div>
        )}

        {activeSection === 'projects' && (
          <ProjectsPipeline
            companies={companies}
            onSelectLead={onSelectLead}
            onOpenPipeline={onOpenPipeline}
            onDeleteProject={handleDeleteProject}
            user={user}
          />
        )}
      </main>
    </div>
  );
}
