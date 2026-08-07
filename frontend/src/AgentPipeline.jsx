import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import {
  ArrowLeft, CheckCircle2, Circle, PlayCircle, Loader2,
  Workflow, Layout, Database, Terminal, Settings, FileText,
  RefreshCw, ArrowRight, AlertTriangle, UploadCloud, X,
  ChevronRight, Sparkles, Lock, MessageSquare, ShieldCheck, Download, Trash2, Clock,
  Plus, FileCode, Save, Edit3, CheckCircle, Cloud, ClipboardList
} from 'lucide-react';
import './AgentPipeline.css';
import ProjectGeneration from './ProjectGeneration';
import DocAgent from './DocAgent';
import UIDesignAgent from './ui_design';
import QAAgent from './QAAgent';

import { runWorkflowAgent, runRequirementsAgent, runWorkflowRefine, saveArtifact, getWorkflowSessions, getWorkflowSession, saveWorkflowSession, approveWorkflowSession, deleteWorkflowSession, getTasks, syncTasks, updateTaskStatus as apiUpdateTaskStatus, saveSprintTaskArtifact, getSprintTaskArtifact } from './api';

const AGENTS = [
  {
    id: 'workflow',
    title: "Workflow Agent",
    icon: Workflow,
    description: "Generates AS-IS & TO-BE procedural workflows from meeting transcripts.",
  },
  {
    id: 'requirements',
    title: "Req. Generation & Scope Control",
    icon: Database,
    description: "Extracts developer-ready requirements and scope boundaries.",
  },
  {
    id: 'doc',
    title: "Doc Agent",
    icon: FileText,
    description: "Produces HLD & LLD architectural documents and Jira Sprint Backlog.",
  },
  {
    id: 'ui_design',
    title: "UI Design Agent",
    icon: Layout,
    description: "Formulates visual hierarchy, layouts, and UI/UX specifications.",
  },
  {
    id: 'task_sprint',
    title: "Task & Sprint Engine",
    icon: Settings,
    description: "Builds agile sprint schedules and assigns priority tiers.",
  },
  {
    id: 'qa_agent',
    title: "QA Agent",
    icon: ShieldCheck,
    description: "Generates test cases and executes code review.",
  },
  {
    id: 'deployment_agent',
    title: "Deployment Agent",
    icon: Cloud,
    description: "Executes deployment sequences and infrastructure setup.",
  }
];

const TASK_STATUS_COLUMNS = [
  { id: 'todo', title: 'To Do', tone: '#94a3b8' },
  { id: 'inprog', title: 'In Progress', tone: '#60a5fa' },
  { id: 'review', title: 'Review', tone: '#fbbf24' },
  { id: 'done', title: 'Done', tone: '#10b981' }
];

const TASK_ASSIGNEES = [
  { id: 'BA', name: 'Business Analyst', tone: '#a78bfa' },
  { id: 'BE', name: 'Backend Engineer', tone: '#60a5fa' },
  { id: 'FE', name: 'Frontend Engineer', tone: '#2dd4bf' },
  { id: 'QA', name: 'QA Engineer', tone: '#fbbf24' }
];

const toArray = (value) => {
  if (Array.isArray(value)) return value.filter(Boolean);
  if (typeof value === 'string' && value.trim()) return [value.trim()];
  return [];
};

const normalizePriority = (value) => {
  const priority = String(value || 'medium').toLowerCase();
  if (priority.includes('high')) return 'high';
  if (priority.includes('low')) return 'low';
  return 'medium';
};

const normalizeRequirementWorkflows = (requirementsData, activeProject) => {
  if (!requirementsData) return [];

  if (Array.isArray(requirementsData?.workflows)) return requirementsData.workflows;

  if (Array.isArray(requirementsData?.projects)) {
    return requirementsData.projects.map((project) => ({
      workflow_id: project?.workflow_id || project?.project_id,
      workflow_name: project?.workflow_name || project?.project_name,
      workflow_summary: project?.workflow_summary || project?.project_summary,
      epics: project?.epics,
      requirements: project?.requirements,
      actors: project?.actors || []
    }));
  }

  if (Array.isArray(requirementsData?.requirements)) {
    return [{
      workflow_id: requirementsData?.workflow_id || activeProject?.id || 'WF-1',
      workflow_name: requirementsData?.workflow_name || activeProject?.project_name || activeProject?.company || 'Generated Workflow',
      workflow_summary: requirementsData?.workflow_summary || '',
      requirements: requirementsData.requirements,
      epics: requirementsData?.epics || []
    }];
  }

  if (Array.isArray(requirementsData)) {
    return [{
      workflow_id: activeProject?.id || 'WF-1',
      workflow_name: activeProject?.project_name || activeProject?.company || 'Generated Workflow',
      workflow_summary: '',
      requirements: requirementsData,
      epics: []
    }];
  }

  return [];
};

const pickAssignee = (requirement, index) => {
  const haystack = [
    requirement?.title,
    requirement?.description,
    requirement?.requirement_description,
    ...(toArray(requirement?.functional_details)),
    ...(toArray(requirement?.acceptance_criteria))
  ].join(' ').toLowerCase();

  if (/(test|qa|acceptance|validation|verify|error|edge)/.test(haystack)) return TASK_ASSIGNEES[3];
  if (/(ui|screen|dashboard|form|modal|view|frontend|interface)/.test(haystack)) return TASK_ASSIGNEES[2];
  if (/(api|database|auth|integration|sync|server|backend|data)/.test(haystack)) return TASK_ASSIGNEES[1];
  return TASK_ASSIGNEES[index % TASK_ASSIGNEES.length];
};

const estimateHours = (requirement) => {
  const priority = normalizePriority(requirement?.priority);
  const detailCount = toArray(requirement?.functional_details).length;
  const acceptanceCount = toArray(requirement?.acceptance_criteria).length;
  const edgeCount = toArray(requirement?.edge_cases).length;
  const base = priority === 'high' ? 6 : priority === 'low' ? 3 : 4;
  return Math.min(13, Math.max(3, base + Math.ceil((detailCount + acceptanceCount + edgeCount) / 3)));
};

const deriveSprintTasks = (requirementsData, workflowId, activeProject) => {
  const workflows = normalizeRequirementWorkflows(requirementsData, activeProject);
  const matchingWorkflows = workflowId
    ? workflows.filter((workflow) => String(workflow?.workflow_id || workflow?.id || '') === String(workflowId))
    : workflows;
  const selectedWorkflows = matchingWorkflows.length > 0 ? matchingWorkflows : workflows;
  let taskNumber = 1;
  let sprintHours = 0;
  let sprintNumber = 1;

  return selectedWorkflows.flatMap((workflow) => {
    const epics = Array.isArray(workflow?.epics) && workflow.epics.length > 0
      ? workflow.epics
      : [{
        epic_id: `${workflow?.workflow_id || 'WF'}-EPIC-1`,
        title: workflow?.workflow_name || 'Workflow Epic',
        requirements: workflow?.requirements || []
      }];

    return epics.flatMap((epic) => (
      toArray(epic?.requirements).map((requirement, index) => {
        const hours = estimateHours(requirement);
        if (sprintHours > 0 && sprintHours + hours > 72) {
          sprintNumber += 1;
          sprintHours = 0;
        }
        sprintHours += hours;

        const assignee = pickAssignee(requirement, taskNumber + index);
        const title = requirement?.title || requirement?.requirement_title || requirement?.name || `Requirement ${taskNumber}`;
        const description = requirement?.description || requirement?.requirement_description || requirement?.story_text || requirement?.user_story || '';

        return {
          id: `TSK-${String(taskNumber++).padStart(3, '0')}`,
          sourceReq: requirement?.req_id || requirement?.id || '',
          title: `Build ${title}`,
          story: epic?.title || workflow?.workflow_name || 'Generated Epic',
          userStory: requirement?.user_story || requirement?.story_text || requirement?.description || requirement?.requirement_description || '',
          workflowName: workflow?.workflow_name || activeProject?.project_name || activeProject?.company || 'Workflow',
          description,
          priority: normalizePriority(requirement?.priority),
          assignee,
          hours,
          status: 'todo',
          sprint: `Sprint ${sprintNumber}`,
          acceptanceCriteria: toArray(requirement?.acceptance_criteria),
          functionalDetails: toArray(requirement?.functional_details),
          dependencies: toArray(requirement?.dependencies)
        };
      })
    ));
  });
};

// ═══════════════════════════════════════════
// MARKDOWN RENDERER
// ═══════════════════════════════════════════
function RenderMarkdown({ text }) {
  if (!text) return null;
  const lines = text.split('\n');
  const elements = [];
  let inMermaid = false;
  let mermaidCode = '';
  let mermaidIdx = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (line.trim().startsWith('```mermaid')) {
      inMermaid = true;
      mermaidCode = '';
      continue;
    }
    if (inMermaid && line.trim() === '```') {
      inMermaid = false;
      elements.push(
        <MermaidDiagram key={`mermaid-${mermaidIdx++}`} code={mermaidCode.trim()} />
      );
      continue;
    }
    if (inMermaid) {
      mermaidCode += line + '\n';
      continue;
    }

    if (line.startsWith('### ')) {
      elements.push(<h3 key={i} className="md-h3">{line.replace('### ', '')}</h3>);
    } else if (line.startsWith('## ')) {
      elements.push(<h2 key={i} className="md-h2">{line.replace('## ', '')}</h2>);
    } else if (line.match(/^\d+\.\s/)) {
      elements.push(<div key={i} className="md-list-item numbered">{line}</div>);
    } else if (line.startsWith('- ')) {
      elements.push(<div key={i} className="md-list-item">{line}</div>);
    } else if (line.trim() === '---') {
      elements.push(<hr key={i} className="md-hr" />);
    } else if (line.trim()) {
      elements.push(<p key={i} className="md-p">{line}</p>);
    }
  }
  return <div className="md-content">{elements}</div>;
}

// ═══════════════════════════════════════════
// MERMAID DIAGRAM RENDERER
// ═══════════════════════════════════════════
let mermaidInitialized = false;

function MermaidDiagram({ code }) {
  const containerRef = useRef(null);
  const idRef = useRef(`mmd-${Math.random().toString(36).substring(2, 9)}`);
  const [renderError, setRenderError] = useState(false);

  useEffect(() => {
    if (!code || !containerRef.current) return;
    let cancelled = false;

    const renderDiagram = async () => {
      try {
        const mermaid = (await import('https://cdn.jsdelivr.net/npm/mermaid@10.6.1/dist/mermaid.esm.min.mjs')).default;

        if (!mermaidInitialized) {
          mermaid.initialize({
            startOnLoad: false,
            theme: 'dark',
            securityLevel: 'loose',
            fontFamily: 'Inter, system-ui, sans-serif',
            // Layout engine — controls alignment and spacing
            flowchart: {
              nodeSpacing: 30,
              rankSpacing: 55,
              padding: 18,
              htmlLabels: true,
              curve: 'basis',
              useMaxWidth: true,
            },
            themeVariables: {
              fontSize: '13px',
              primaryColor: '#3b82f6',
              primaryTextColor: '#f1f5f9',
              primaryBorderColor: '#60a5fa',
              lineColor: '#475569',
              secondaryColor: '#1e293b',
              tertiaryColor: '#0f172a',
              edgeLabelBackground: '#0f172a',
              mainBkg: '#1e293b',
              nodeBorder: '#3b82f6',
              clusterBkg: 'rgba(59, 130, 246, 0.04)',
              clusterBorder: 'rgba(96, 165, 250, 0.25)',
            },
            themeCSS: `
              /* Node styling */
              .node rect, .node circle, .node polygon, .node path {
                stroke-width: 2px !important;
                fill: #1e293b !important;
                rx: 8px !important;
                ry: 8px !important;
              }
              .node .label {
                font-weight: 600 !important;
                font-size: 12px !important;
                color: #f1f5f9 !important;
                font-family: 'Inter', sans-serif !important;
              }
              /* Edge styling */
              .edgePath .path {
                stroke: #475569 !important;
                stroke-width: 1.5px !important;
              }
              .marker {
                fill: #475569 !important;
                stroke: #475569 !important;
              }
              .edgeLabel {
                background-color: #0f172a !important;
                color: #94a3b8 !important;
                font-size: 10px !important;
                font-weight: 500 !important;
                padding: 3px 6px !important;
                border-radius: 4px !important;
              }
              /* Subgraph / Cluster styling */
              .cluster rect {
                fill: rgba(15, 23, 42, 0.6) !important;
                stroke: rgba(96, 165, 250, 0.2) !important;
                stroke-width: 1.5px !important;
                rx: 12px !important;
                ry: 12px !important;
              }
              .cluster span {
                color: #60a5fa !important;
                font-weight: 700 !important;
                font-size: 11px !important;
                text-transform: uppercase !important;
                letter-spacing: 1px !important;
              }
            `
          });
          mermaidInitialized = true;
        }

        const uniqueId = idRef.current + '-' + Date.now();
        const { svg } = await mermaid.render(uniqueId, code);
        if (!cancelled && containerRef.current) {
          containerRef.current.innerHTML = svg;
          setRenderError(false);
        }
      } catch (err) {
        console.error('Mermaid render error:', err);
        if (!cancelled) setRenderError(true);
      }
    };

    renderDiagram();
    return () => { cancelled = true; };
  }, [code]);

  if (renderError) {
    return (
      <div className="mermaid-container mermaid-error">
        <div className="mermaid-error-inner">
          <AlertTriangle size={16} />
          <span>Diagram syntax error — showing raw code:</span>
        </div>
        <pre className="mermaid-raw-code">{code}</pre>
      </div>
    );
  }

  return (
    <div className="mermaid-container" ref={containerRef}>
      <div className="mermaid-loading">
        <Loader2 size={20} className="spin" />
        <span>Rendering diagram…</span>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
// WORKFLOW AGENT PANEL
// ═══════════════════════════════════════════
function WorkflowPanel({ activeProject, activeWorkflowId, onComplete, onGenerateFromContext, onProjectRefresh, onFocusRequirements, onWorkflowSessionChange }) {
  const [transcript, setTranscript] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editedAsIs, setEditedAsIs] = useState('');
  const [editedToBe, setEditedToBe] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [refinementInput, setRefinementInput] = useState('');
  const [isRefining, setIsRefining] = useState(false);
  const [isApproved, setIsApproved] = useState(false);
  const [isRefineExpanded, setIsRefineExpanded] = useState(true);
  const [isLoadingArtifact, setIsLoadingArtifact] = useState(true);
  const [resultsTab, setResultsTab] = useState('flowcharts');

  // Session tracking
  const [sessions, setSessions] = useState([]);
  const [activeVersion, setActiveVersion] = useState(null);
  const [isSessionsOpen, setIsSessionsOpen] = useState(false);

  const fileInputRef = useRef(null);

  // Load sessions on mount
  useEffect(() => {
    const loadSessions = async () => {
      const projId = activeProject?.id || activeProject?.project_id;
      if (!projId) { setIsLoadingArtifact(false); return; }
      try {
        const res = await getWorkflowSessions(projId);
        if (res && res.status === 'success' && res.sessions?.length > 0) {
          setSessions(res.sessions);
          const parsedVersion = activeWorkflowId ? parseInt(activeWorkflowId, 10) : NaN;
          const versionToLoad = Number.isFinite(parsedVersion) ? parsedVersion : res.sessions[0].version;
          if (onWorkflowSessionChange) onWorkflowSessionChange(versionToLoad);
          await loadSpecificSession(projId, versionToLoad);
        } else {
          setIsLoadingArtifact(false);
        }
      } catch (err) {
        console.error('Failed to load sessions:', err);
        setIsLoadingArtifact(false);
      }
    };
    loadSessions();
  }, [activeProject, activeWorkflowId]);

  const loadSpecificSession = async (projectId, version) => {
    setIsLoadingArtifact(true);
    try {
      const res = await getWorkflowSession(projectId, version);
      if (res && res.status === 'success') {
        const session = res.session;
        setActiveVersion(session.version);
        if (onWorkflowSessionChange) onWorkflowSessionChange(session.version);
        const asIsData = session.as_is || '';
        const toBeData = session.to_be || '';
        setEditedAsIs(typeof asIsData === 'string' ? asIsData : JSON.stringify(asIsData, null, 2));
        setEditedToBe(typeof toBeData === 'string' ? toBeData : JSON.stringify(toBeData, null, 2));
        setTranscript(session.raw_transcript || '');
        setIsApproved(session.client_approved || false);
        setResults({ as_is: asIsData, to_be: toBeData });
      }
    } catch (err) {
      console.error('Failed to load session details:', err);
    } finally {
      setIsLoadingArtifact(false);
    }
  };

  const handleSessionChange = (e) => {
    const version = parseInt(e.target.value, 10);
    loadSpecificSession(activeProject?.id || activeProject?.project_id, version);
  };

  const handleFileUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      setTranscript(ev.target.result);
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  const handleAnalyze = async () => {
    if (!transcript.trim()) return;
    setIsAnalyzing(true);
    setError(null);
    setResults(null);
    setIsApproved(false);
    try {
      const projectId = activeProject?.id || activeProject?.project_id;
      const res = await runWorkflowAgent(transcript, projectId, [], refinementInput);
      if (res.error) throw new Error(res.error);

      // Morning State Logic: Work directly with the analysis strings
      const asIs = res.as_is || res.analysis?.as_is || '';
      const toBe = res.to_be || res.analysis?.to_be || '';

      const newVersion = sessions.length ? Math.max(...sessions.map(s => s.version)) + 1 : 1;
      const sessionTitle = `Session ${newVersion} - ${new Date().toLocaleDateString()}`;

      const saveRes = await saveWorkflowSession({
        project_id: activeProject?.id || activeProject?.project_id,
        version: newVersion,
        session_title: sessionTitle,
        as_is: asIs,
        to_be: toBe,
        client_approved: false,
        raw_transcript: transcript
      });

      if (saveRes.error) throw new Error(saveRes.error);

      // Reload sessions list
      const sessRes = await getWorkflowSessions(activeProject?.id || activeProject?.project_id);
      if (sessRes && sessRes.status === 'success') {
        setSessions(sessRes.sessions);
      }

      if (onProjectRefresh) {
        await onProjectRefresh();
      }

      setActiveVersion(newVersion);
      if (onWorkflowSessionChange) onWorkflowSessionChange(newVersion);
      setResults({ as_is: asIs, to_be: toBe });
      setEditedAsIs(asIs);
      setEditedToBe(toBe);
    } catch (err) {
      console.error('Workflow analysis error:', err);
      setError(err.message || 'Analysis failed. Please check your backend is running.');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleRefine = async () => {
    if (!refinementInput.trim()) return;
    setIsRefining(true);
    setError(null);
    try {
      const data = await runWorkflowRefine(editedToBe, refinementInput, activeProject?.id);
      if (data.status === 'success') {
        setEditedToBe(data.revised_flow);
        setRefinementInput('');

        // Auto-save draft on successful refine
        if (activeVersion) {
          await saveWorkflowSession({
            project_id: activeProject?.id || activeProject?.project_id,
            version: activeVersion,
            as_is: editedAsIs,
            to_be: data.revised_flow,
            client_approved: false,
            raw_transcript: transcript
          });
        }
      } else {
        setError(data.error || "Refinement failed");
      }
    } catch (err) {
      setError("Network error during refinement. Check backend.");
    } finally {
      setIsRefining(false);
    }
  };

  const handleNewAnalysis = () => {
    setResults(null);
    setTranscript('');
    setEditedAsIs('');
    setEditedToBe('');
    setRefinementInput('');
    setIsApproved(false);
    setActiveVersion(null);
    setIsRefineExpanded(false);
    setError(null);
  };

  const handleApprove = async () => {
    const projId = activeProject?.id || activeProject?.project_id;
    if (!projId || !activeVersion) return;
    setIsSaving(true);
    setError(null);
    try {
      await saveWorkflowSession({
        project_id: projId,
        version: activeVersion,
        as_is: editedAsIs,
        to_be: editedToBe,
        client_approved: true,
        raw_transcript: transcript
      });
      const res = await approveWorkflowSession(projId, activeVersion);
      if (res && res.status === 'success') {
        setIsApproved(true);
        if (onGenerateFromContext) {
          void onGenerateFromContext({ confirmProjectStart: true });
        }
        if (onProjectRefresh) {
          await onProjectRefresh();
        }
        if (onComplete) onComplete();
        if (onFocusRequirements) onFocusRequirements();
        const sessRes = await getWorkflowSessions(projId);
        if (sessRes && sessRes.status === 'success') setSessions(sessRes.sessions);
      } else {
        throw new Error(res?.error || 'Approval failed');
      }
    } catch (err) {
      setError('Approval failed: ' + err.message);
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveDraft = async () => {
    const projId = activeProject?.id || activeProject?.project_id;
    if (!projId || !activeVersion) return;
    setIsSaving(true);
    try {
      const res = await saveWorkflowSession({
        project_id: projId,
        version: activeVersion,
        as_is: editedAsIs,
        to_be: editedToBe,
        client_approved: false,
        raw_transcript: transcript
      });
      if (res && res.error) throw new Error(res.error);
    } catch (err) {
      setError('Save failed: ' + err.message);
    } finally {
      setIsSaving(false);
    }
  };

  const handleDeleteSession = async (projectId, version) => {
    if (!window.confirm("Are you sure you want to delete this session? This action cannot be undone.")) return;
    try {
      const res = await deleteWorkflowSession(projectId, version);
      if (res.status === 'success') {
        const filtered = sessions.filter(s => s.version !== version);
        setSessions(filtered);
        if (activeVersion === version) {
          if (filtered.length > 0) {
            loadSpecificSession(projectId, filtered[0].version);
            if (onWorkflowSessionChange) onWorkflowSessionChange(filtered[0].version);
          } else {
            handleNewAnalysis();
            if (onWorkflowSessionChange) onWorkflowSessionChange(null);
          }
        }
      } else {
        setError("Delete failed: " + (res.error || "Unknown error"));
      }
    } catch (err) {
      console.error("Failed to delete session:", err);
      setError("Network error deleting session.");
    }
  };


  const handleDownloadImage = (type) => {
    const selector = type === 'as_is' ? '.comparison-column.as-is .mermaid-container' : '.comparison-column.to-be .mermaid-container';
    const container = document.querySelector(selector);
    const svg = container?.querySelector('svg');

    if (!svg) {
      alert("Diagram not found. Please ensure the workflow is rendered.");
      return;
    }

    const downloadSvgFallback = (svgData) => {
      const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(svgBlob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `Workflow_${type}_v${activeVersion || 1}.svg`;
      a.click();
      URL.revokeObjectURL(url);
    };

    try {
      // 1. Prepare SVG and sanitize
      const serializer = new XMLSerializer();
      let svgData = serializer.serializeToString(svg);

      // Force namespace
      if (!svgData.includes('xmlns="http://www.w3.org/2000/svg"')) {
        svgData = svgData.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"');
      }

      // 2. Setup Dimensions
      const rect = svg.getBoundingClientRect();
      const scale = 2;
      const width = Math.ceil(rect.width || 1200);
      const height = Math.ceil(rect.height || 800);

      const canvas = document.createElement('canvas');
      canvas.width = width * scale;
      canvas.height = height * scale;

      const ctx = canvas.getContext('2d');
      const img = new Image();

      img.onload = () => {
        try {
          ctx.fillStyle = '#020617'; // Match UI background
          ctx.fillRect(0, 0, canvas.width, canvas.height);
          ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

          const pngUrl = canvas.toDataURL('image/png');
          const a = document.createElement('a');
          a.href = pngUrl;
          a.download = `Workflow_${type}_v${activeVersion || 1}.png`;
          a.click();
        } catch (e) {
          console.error("Canvas toDataURL failed:", e);
          downloadSvgFallback(svgData);
        }
      };

      img.onerror = (e) => {
        console.error("Image load failed:", e);
        downloadSvgFallback(svgData);
      };

      // Use Base64 encoding to sidestep some Blob-based security hurdles
      const base64 = btoa(unescape(encodeURIComponent(svgData)));
      img.src = 'data:image/svg+xml;base64,' + base64;

    } catch (err) {
      console.error("Export process failed:", err);
      alert("PNG Export blocked by browser. Saving as SVG instead.");
      const serializer = new XMLSerializer();
      downloadSvgFallback(serializer.serializeToString(svg));
    }
  };

  // Loading state while checking for saved artifacts
  if (isLoadingArtifact) {
    return (
      <div className="agent-panel-content">
        <div className="agent-panel-header">
          <div className="agent-panel-icon workflow-icon">
            <Workflow size={24} />
          </div>
          <div>
            <h2>Workflow Agent</h2>
            <p>Loading saved workspace…</p>
          </div>
        </div>
        <div className="agent-loading-state">
          <Loader2 size={32} className="spin" />
          <span>Checking for existing analysis…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="agent-panel-content">
      {/* Header */}
      <div className="agent-panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '1rem' }}>
          <div className="agent-panel-icon workflow-icon">
            <Workflow size={24} />
          </div>
          <div>
            <h2>Workflow Agent</h2>
            <p>Paste client transcripts to generate workflows.</p>
          </div>
        </div>

        {sessions.length > 0 && (
          <div className="session-selector-container" style={{ position: 'relative' }}>
            <div className="session-selector-trigger" onClick={() => setIsSessionsOpen(!isSessionsOpen)} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 16px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', cursor: 'pointer', minWidth: '180px' }}>
              <span style={{ fontSize: '12px', color: '#94a3b8' }}>Session {activeVersion}</span>
              <ChevronRight size={14} style={{ transform: isSessionsOpen ? 'rotate(90deg)' : 'none', transition: 'transform 0.2s', marginLeft: 'auto' }} />
            </div>

            {isSessionsOpen && (
              <div className="session-dropdown-menu anim-scale-up" style={{ position: 'absolute', top: 'calc(100% + 8px)', right: 0, width: '240px', background: '#1e293b', border: '1px solid #334155', borderRadius: '12px', boxShadow: '0 10px 25px rgba(0,0,0,0.4)', zIndex: 100, padding: '8px', overflow: 'hidden' }}>
                {sessions.map(s => (
                  <div
                    key={s.version}
                    className={`session-dropdown-item ${activeVersion === s.version ? 'active' : ''}`}
                    onClick={() => { loadSpecificSession(activeProject?.id || activeProject?.project_id, s.version); setIsSessionsOpen(false); }}
                    style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 12px', borderRadius: '8px', cursor: 'pointer', marginBottom: '4px', transition: 'background 0.2s', background: activeVersion === s.version ? 'rgba(59, 130, 246, 0.1)' : 'transparent' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', overflow: 'hidden' }}>
                      {s.client_approved ? <CheckCircle2 size={14} color="#10b981" /> : <RefreshCw size={14} color="#60a5fa" className="spin-slow" />}
                      <span style={{ fontSize: '13px', color: activeVersion === s.version ? '#fff' : '#94a3b8', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden' }}>{s.session_title}</span>
                    </div>

                    {!s.client_approved && (
                      <button
                        className="btn-delete-session"
                        onClick={(e) => { e.stopPropagation(); handleDeleteSession(activeProject?.id || activeProject?.project_id, s.version); }}
                        style={{ background: 'none', border: 'none', color: '#e11d48', padding: '4px', cursor: 'pointer', opacity: 0.6, display: 'flex', borderRadius: '4px' }}
                        title="Delete Session"
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── INPUT SECTION ── */}
      {!results && (
        <div className="workflow-input-section anim-fade-in">
          <div className="input-section-header">
            <h3><FileText size={16} /> Transcript Input</h3>
            <div className="input-actions">
              <input
                type="file"
                ref={fileInputRef}
                hidden
                accept=".txt,.md,.doc,.docx,.pdf"
                onChange={handleFileUpload}
              />
              <button
                className="btn-upload-file"
                onClick={() => fileInputRef.current?.click()}
              >
                <UploadCloud size={14} /> Upload File
              </button>
            </div>
          </div>

          <textarea
            className="transcript-textarea custom-scroll"
            placeholder="Paste the client meeting transcript here…&#10;&#10;"
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
            rows={12}
          />

          <div className="workflow-feedback-inline">
            <div className="workflow-feedback-inline-header">
              <MessageSquare size={14} />
              <span>Workflow feedback / corrections</span>
            </div>
            <textarea
              className="workflow-feedback-input custom-scroll"
              placeholder="Optional: add corrections or extra guidance before analysis. Example: highlight the approval gate, preserve manual review, and keep the flow linear."
              value={refinementInput}
              onChange={(e) => setRefinementInput(e.target.value)}
            />
          </div>

          {error && (
            <div className="agent-error anim-fade-in">
              <AlertTriangle size={14} />
              <span>{error}</span>
            </div>
          )}

          <div className="workflow-actions">
            <span className="char-count">{transcript.length.toLocaleString()} characters</span>
            <button
              className="btn-analyze"
              onClick={handleAnalyze}
              disabled={!transcript.trim() || isAnalyzing}
            >
              {isAnalyzing ? (
                <>
                  <Loader2 size={16} className="spin" />
                  Analyzing Transcript…
                </>
              ) : (
                <>
                  <Sparkles size={16} />
                  Analyze Workflow
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {/* ── RESULTS SECTION ── */}
      {results && (
        <div className="workflow-results anim-fade-in">
          {/* Results Header Bar */}
          <div className="results-comparison-header">
            <div className="comparison-title">
              <Sparkles size={18} color="#60a5fa" />
              <span>Process Comparison</span>
            </div>

            <div className="header-actions">
              <button
                className="btn-new-analysis"
                onClick={handleNewAnalysis}
                title="Start New Meeting Analysis"
              >
                <RefreshCw size={14} /> New Meeting
              </button>
            </div>
          </div>

          {/* Error banner inside results */}
          {error && (
            <div className="agent-error results-error">
              <AlertTriangle size={14} />
              <span>{error}</span>
              <button className="btn-dismiss-error" onClick={() => setError(null)}>
                <X size={12} />
              </button>
            </div>
          )}

          {/* Side-by-Side Comparison */}
          <div className={`workflow-comparison-view ${isApproved ? 'approved-state' : ''}`}>
            {/* AS-IS Column */}
            <div className="comparison-column as-is">
              <div className="column-label">AS-IS Current State</div>
              <div className="workflow-result-card">
                {isEditing ? (
                  <textarea
                    className="edit-markdown-textarea custom-scroll"
                    value={editedAsIs}
                    onChange={(e) => setEditedAsIs(e.target.value)}
                    placeholder="Edit AS-IS markdown…"
                  />
                ) : (
                  <RenderMarkdown text={editedAsIs} />
                )}
              </div>
              {results && !isApproved && (
                <button
                  className="btn-download-image-asis"
                  onClick={() => handleDownloadImage('as_is')}
                  style={{ marginTop: '12px', width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', padding: '8px', background: 'rgba(255, 255, 255, 0.03)', border: '1px solid rgba(255, 255, 255, 0.1)', borderRadius: '6px', color: '#94a3b8', cursor: 'pointer', fontSize: '12px', transition: 'all 0.2s' }}
                  onMouseOver={(e) => { e.currentTarget.style.background = 'rgba(255, 255, 255, 0.08)'; e.currentTarget.style.color = '#fff'; }}
                  onMouseOut={(e) => { e.currentTarget.style.background = 'rgba(255, 255, 255, 0.03)'; e.currentTarget.style.color = '#94a3b8'; }}
                >
                  <Download size={14} /> Download AS-IS Image
                </button>
              )}
            </div>

            {/* TO-BE Column */}
            <div className="comparison-column to-be">
              <div className="column-label">
                TO-BE Optimized State
                {isApproved && <span className="approved-tag">✅ Approved</span>}
              </div>
              <div className="workflow-result-card highlighted-card">
                {isEditing ? (
                  <textarea
                    className="edit-markdown-textarea custom-scroll"
                    value={editedToBe}
                    onChange={(e) => setEditedToBe(e.target.value)}
                    placeholder="Edit TO-BE markdown…"
                  />
                ) : (
                  <RenderMarkdown text={editedToBe} />
                )}
              </div>
            </div>
          </div>

          {/* Action Footer */}
          <div className="results-footer">
            {!isApproved ? (
              <div className="workflow-feedback-panel">
                <div className="refinement-dialog-header">
                  <div className="header-left">
                    <MessageSquare size={14} color="#60a5fa" />
                    <span>Workflow Feedback</span>
                  </div>
                  <button className="btn-close-refine" onClick={() => setIsRefineExpanded((value) => !value)}>
                    <X size={14} />
                  </button>
                </div>
                {!isRefineExpanded ? (
                  <div className="workflow-feedback-collapsed">
                    <p>Leave a note for the workflow agent. We’ll keep it visible while the current flow is being finalized.</p>
                  </div>
                ) : (
                  <>
                    <textarea
                      className="workflow-feedback-input custom-scroll"
                      placeholder="Tell the workflow agent what to refine. Example: add a manual QA gate, include fallback handling, and make the approval path clearer."
                      value={refinementInput}
                      onChange={(e) => setRefinementInput(e.target.value)}
                      autoFocus
                    />
                    <div className="refinement-dialog-footer">
                      <button
                        className="btn-refine-submit"
                        onClick={handleRefine}
                        disabled={isRefining || !refinementInput.trim()}
                      >
                        {isRefining ? <><Loader2 size={14} className="spin" /> Refining…</> : <><RefreshCw size={14} /> Send Feedback</>}
                      </button>
                    </div>
                  </>
                )}
              </div>
            ) : null}

            {!isApproved ? (
              <div className="footer-actions" style={{ display: 'flex', gap: '16px', justifyContent: 'flex-end', width: '100%' }}>
                {isEditing && (
                  <button className="btn-save-draft" onClick={handleSaveDraft} disabled={isSaving}>
                    {isSaving ? <Loader2 size={14} className="spin" /> : <FileText size={14} />} Save Draft
                  </button>
                )}

                <button
                  className="btn-download-image"
                  onClick={() => handleDownloadImage('to_be')}
                  style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 16px', background: 'rgba(59, 130, 246, 0.1)', border: '1px solid rgba(59, 130, 246, 0.2)', borderRadius: '8px', color: '#60a5fa', cursor: 'pointer', fontSize: '14px', fontWeight: '500' }}
                >
                  <Download size={16} /> Image (PNG)
                </button>

                <button className="btn-approve-locked" onClick={handleApprove} disabled={isSaving}>
                  {isSaving ? <><Loader2 size={16} className="spin" /> Saving…</> : <><ShieldCheck size={18} /> Approve &amp; Lock Workflow</>}
                </button>
              </div>
            ) : (
              <div className="approval-badge" style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <CheckCircle2 size={18} color="#10b981" />
                  <span>Workflow approved — proceeding to Requirements Agent.</span>
                </div>
                <div style={{ display: 'flex', gap: '10px' }}>
                  <button
                    className="btn-download-tobe"
                    onClick={() => handleDownloadImage('to_be')}
                    style={{ background: '#059669', opacity: 0.9, border: 'none', color: '#fff', padding: '8px 16px', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: '8px', fontWeight: '500', cursor: 'pointer' }}
                  >
                    <Download size={16} /> Download Image
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════
// REQUIREMENTS AGENT PANEL
// ═══════════════════════════════════════════
function RequirementsPanel({
  activeProject,
  requirementsData,
  projectTranscript = "",
  requirementHistory = [],
  isGenerating = false,
  isLoadingRequirements = false,
  error = "",

  onGenerateFromContext,
  onComplete,
  workflowId,
  selectedWorkflowSessionVersion = null
}) {
  return (
    <div className="agent-panel-content">
      <div className="agent-panel-header">
        <div className="agent-panel-icon requirements-icon">
          <Database size={24} />
        </div>
        <div>
          <h2>Requirement Engineering Agent</h2>
          <p>Transforming approved workflows into structured user stories and technical requirements.</p>
        </div>
      </div>

      <div className="embedded-project-gen">
        <ProjectGeneration
          lead={activeProject}
          requirementsData={requirementsData}
          projectTranscript={projectTranscript}
          requirementHistory={requirementHistory}
          isGenerating={isGenerating}
          isLoadingRequirements={isLoadingRequirements}
          error={error}
          onGenerateFromContext={onGenerateFromContext}
          hideHeader={true}
          onBack={() => { }}
          onOpenAnalysis={() => { }}
          initialWorkflowFilter={workflowId}
          selectedWorkflowSessionVersion={selectedWorkflowSessionVersion}
        />
      </div>
    </div>
  );
}



// ═══════════════════════════════════════════
// TASK & SPRINT ENGINE PANEL
// ═══════════════════════════════════════════
// Reconstruct the rich assignee object from a stored assignee_id string
const ASSIGNEE_MAP = Object.fromEntries(TASK_ASSIGNEES.map((a) => [a.id, a]));

function TaskSprintPanel({
  activeProject,
  requirementsData,
  workflowId,
  workflowName,
  selectedWorkflowSessionVersion = null,
  onComplete
}) {
  const generatedTasks = useMemo(
    () => deriveSprintTasks(requirementsData, workflowId, activeProject),
    [requirementsData, workflowId, activeProject]
  );

  // ── DB-backed state ──
  const [dbStatusMap, setDbStatusMap] = useState({});   // { taskId: status } loaded from DB
  const [dbDescMap, setDbDescMap] = useState({});   // { taskId: description } loaded from DB
  const [dbTasks, setDbTasks] = useState([]); // raw persisted tasks from DB
  const [dbSynced, setDbSynced] = useState(false); // true after first sync completes
  const [isSyncingDb, setIsSyncingDb] = useState(false);

  // ── UI interaction state ──
  const [statusOverrides, setStatusOverrides] = useState({});
  const [draggedTaskId, setDraggedTaskId] = useState(null);
  const [dragOverColumn, setDragOverColumn] = useState(null);
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [taskComments, setTaskComments] = useState({});
  const [taskLogs, setTaskLogs] = useState({});
  const [commentDraft, setCommentDraft] = useState('');
  const [isHydratingBoard, setIsHydratingBoard] = useState(false);
  const boardHydrationRef = useRef(false);

  const projectId = activeProject?.id || activeProject?.project_id || '';

  // ── Step 1: Reset local UI state when project/workflow changes ──
  useEffect(() => {
    // Clear state on workflow switch
    setStatusOverrides({});
    setTaskComments({});
    setTaskLogs({});
    setCommentDraft('');
    setDbStatusMap({});
    setDbDescMap({});
    setDbTasks([]);
    setDbSynced(false);
    setIsSyncingDb(false);
    boardHydrationRef.current = false;
  }, [requirementsData, workflowId]);

  // Our Primary Logic: Load from DB first, then seed missing tasks from derived requirements.
  useEffect(() => {
    if (!projectId || !workflowId) return;
    let cancelled = false;

    const run = async () => {
      setIsSyncingDb(true);
      try {
        const firstPass = await getTasks(projectId, workflowId);
        let persistedTasks = Array.isArray(firstPass?.tasks) ? firstPass.tasks : [];

        if (!persistedTasks.length && generatedTasks.length) {
          await syncTasks(projectId, workflowId, generatedTasks);
          const secondPass = await getTasks(projectId, workflowId);
          persistedTasks = Array.isArray(secondPass?.tasks) ? secondPass.tasks : [];
        }

        if (!cancelled) {
          const sMap = {};
          const dMap = {};
          persistedTasks.forEach((t) => {
            sMap[t.id] = t.status;
            dMap[t.id] = t.description;
          });
          setDbTasks(persistedTasks);
          setDbStatusMap(sMap);
          setDbDescMap(dMap);
          setDbSynced(true);
        }
      } catch (err) {
        console.warn('[TaskSprintPanel] DB sync failed (UI still works):', err);
        if (!cancelled) setDbSynced(true); // don't retry — fall back to local state
      } finally {
        if (!cancelled) setIsSyncingDb(false);
      }
    };
    run();
    return () => { cancelled = true; };
  }, [projectId, workflowId, generatedTasks]);

  // Secondary Logic: Hydrate Session Context (selected task, comments, etc)
  useEffect(() => {
    const sessionVersion = Number(selectedWorkflowSessionVersion) || 1;
    if (!projectId || !workflowId) {
      setIsHydratingBoard(false);
      boardHydrationRef.current = false;
      return;
    }

    let cancelled = false;
    boardHydrationRef.current = true;
    setIsHydratingBoard(true);

    (async () => {
      try {
        const res = await getSprintTaskArtifact(projectId, workflowId, sessionVersion);
        if (cancelled) return;

        if (res?.status === 'success' && res?.artifact) {
          const artifact = res.artifact;
          const boardState = artifact.board_state || {};
          setTaskComments(artifact.task_comments || {});
          setTaskLogs(artifact.task_logs || {});
          
          // Only hydrate the selection if it's NOT the very first time (avoid auto-pop)
          if (boardState.selected_task_id) {
            setSelectedTaskId(boardState.selected_task_id);
          } else {
            setSelectedTaskId(null);
          }
          
          setDragOverColumn(boardState.drag_over_column || null);
        } else {
          setStatusOverrides({});
          setTaskComments({});
          setTaskLogs({});
          setSelectedTaskId(null);
          setDragOverColumn(null);
        }
      } catch {
        if (!cancelled) {
          setStatusOverrides({});
          setTaskComments({});
          setTaskLogs({});
          setSelectedTaskId(null);
          setDragOverColumn(null);
        }
      } finally {
        if (!cancelled) {
          boardHydrationRef.current = false;
          setIsHydratingBoard(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [activeProject?.id, activeProject?.project_id, workflowId, selectedWorkflowSessionVersion]);


  const tasks = useMemo(
    () => {
      const sourceTasks = dbTasks.length > 0 ? dbTasks : generatedTasks;

      return sourceTasks.map((task, index) => {
        let desc = (dbDescMap[task.id] ?? task.description) || '';
        let parsedDesc = desc;
        let bugLogs = [];

        if (desc && desc.includes('--- BUG REPORT:')) {
          const parts = desc.split('\n\n--- BUG REPORT: ');
          parsedDesc = parts[0];
          for (let i = 1; i < parts.length; i++) {
            const lines = parts[i].split('\n');
            const title = lines[0].replace(' ---', '');
            const report = lines.slice(1).join('\n').trim();
            bugLogs.push({
              timestamp: 'From QA',
              message: `DEFECT: ${title}\n${report}`,
              isError: true
            });
          }
        }

        const assignee =
          typeof task.assignee === 'object' && task.assignee
            ? task.assignee
            : ASSIGNEE_MAP[task.assignee_id] || task.assignee || TASK_ASSIGNEES[index % TASK_ASSIGNEES.length];

        return {
          ...task,
          hours: Number(task.hours ?? task.effort_estimate_hours ?? 0),
          assignee,
          status: statusOverrides[task.id] ?? dbStatusMap[task.id] ?? task.status,
          description: parsedDesc,
          bugLogs: bugLogs
        };
      });
    },
    [generatedTasks, dbTasks, statusOverrides, dbStatusMap, dbDescMap]
  );

  // Seed activity logs once tasks are ready


  useEffect(() => {
    if (!tasks.length) {
      setSelectedTaskId(null);
      return;
    }
    setSelectedTaskId((current) => (
      current && tasks.some((task) => task.id === current) ? current : null
    ));
    setTaskLogs((prev) => {
      const seededLogs = { ...prev };
      let hasChanges = false;

      tasks.forEach((task) => {
        const existing = seededLogs[task.id] || [];
        const baseLog = existing.length > 0 ? existing[0] : { timestamp: 'Now', message: `Task created in ${task.sprint} and assigned to ${task.assignee.name}.` };

        const bugs = task.bugLogs || [];
        const currentErrorCount = existing.filter(l => l.isError).length;

        if (existing.length === 0 || bugs.length > currentErrorCount) {
          seededLogs[task.id] = [baseLog, ...bugs];
          hasChanges = true;
        }
      });

      return hasChanges || Object.keys(prev).length === 0 ? seededLogs : prev;
    });
  }, [tasks]);

  const totalHours = tasks.reduce((sum, task) => sum + (Number(task.hours) || 0), 0);
  const sprintCount = new Set(tasks.map((task) => task.sprint)).size || 0;
  const doneCount = tasks.filter((task) => task.status === 'done').length;
  const progressPct = tasks.length ? Math.round((doneCount / tasks.length) * 100) : 0;
  const highPriorityCount = tasks.filter((task) => task.priority === 'high').length;
  const primaryWorkflowName = workflowName || tasks[0]?.workflowName || activeProject?.project_name || activeProject?.company || 'Generated Workflow';
  const selectedTask = selectedTaskId ? tasks.find((task) => task.id === selectedTaskId) : null;

  // ── Status change: optimistic local update + fire-and-forget DB write ──
  const handleUpdateTaskStatus = (taskId, status) => {
    // 1. Optimistic local update (instant UI)
    setStatusOverrides((prev) => ({ ...prev, [taskId]: status }));
    setTaskLogs((prev) => ({
      ...prev,
      [taskId]: [
        ...(prev[taskId] || []),
        { timestamp: 'Now', message: `Moved to ${TASK_STATUS_COLUMNS.find((c) => c.id === status)?.title || status}.` }
      ]
    }));

    // 2. Persist to DB (fire-and-forget — failure silently logged)
    apiUpdateTaskStatus(taskId, status, projectId, workflowId).catch((err) => {
      console.warn(`[TaskSprintPanel] Failed to persist status for ${taskId}:`, err);
    });
  };

  const handleTaskSelect = (taskId) => { setSelectedTaskId(taskId); setCommentDraft(''); };

  const handleAddComment = () => {
    if (!selectedTask || !commentDraft.trim()) return;
    const comment = commentDraft.trim();
    setTaskComments((prev) => ({
      ...prev,
      [selectedTask.id]: [...(prev[selectedTask.id] || []), { author: 'You', timestamp: 'Just now', text: comment }]
    }));
    setTaskLogs((prev) => ({
      ...prev,
      [selectedTask.id]: [...(prev[selectedTask.id] || []), { timestamp: 'Just now', message: `Comment added: ${comment}` }]
    }));
    setCommentDraft('');
  };

  useEffect(() => {
    if (!tasks.length) return;
    const projectId = activeProject?.id || activeProject?.project_id;
    if (!projectId) return;
    if (isHydratingBoard) return; // DON'T SAVE WHILE WE ARE STILL LOADING!

    saveSprintTaskArtifact({
      project_id: projectId,
      workflow_id: workflowId || 'default',
      workflow_name: primaryWorkflowName,
      session_version: Number(selectedWorkflowSessionVersion) || 1,
      session_title: `Sprint Board - ${primaryWorkflowName}`,
      generated_tasks: tasks,
      task_comments: taskComments,
      task_logs: taskLogs,
      board_state: {
        status_overrides: statusOverrides,
        selected_task_id: selectedTaskId,
        drag_over_column: dragOverColumn
      }
    }).catch(() => {});
  }, [
    activeProject,
    dragOverColumn,
    primaryWorkflowName,
    selectedTaskId,
    selectedWorkflowSessionVersion,
    statusOverrides,
    taskComments,
    taskLogs,
    tasks,
    workflowId,
    isHydratingBoard
  ]);

  const handleDragStart = (taskId) => {
    setDraggedTaskId(taskId);
  };

  const handleDragEnd = () => {
    setDraggedTaskId(null);
    setDragOverColumn(null);
  };

  const handleDragOver = (event, columnId) => {
    event.preventDefault();
    if (dragOverColumn !== columnId) setDragOverColumn(columnId);
  };
  const handleDrop = (event, columnId) => {
    event.preventDefault();
    const taskId = draggedTaskId;
    setDraggedTaskId(null);
    setDragOverColumn(null);
    if (!taskId) return;
    handleUpdateTaskStatus(taskId, columnId);
  };

  return (
    <div className="agent-panel-content task-sprint-panel anim-fade-in">
      <div className="agent-panel-header task-sprint-header">
        <div className="agent-panel-icon task-sprint-icon">
          <Settings size={24} />
        </div>
        <div>
          <h2>Task &amp; Sprint Engine</h2>
          <p>Converts generated requirements into an actionable sprint backlog and kanban execution board.</p>
        </div>
        {isSyncingDb && (
          <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#60a5fa', opacity: 0.8 }}>
            <Loader2 size={13} className="spin" /> Syncing board…
          </span>
        )}
      </div>

      {tasks.length === 0 ? (
        <div className="task-empty-state">
          <div className="locked-icon-ring"><ClipboardList size={32} /></div>
          <h3>No requirement tasks yet</h3>
          <p>Generate and approve requirements first. This agent will then create sprint tasks from each requirement, including estimates, owners, priorities, and acceptance context.</p>
        </div>
      ) : (
        <>
          <section className="sprint-engine-hero">
            <div>
              <span className="sprint-kicker">ACTIVE DELIVERY PLAN</span>
              <h3>{primaryWorkflowName}</h3>
              <p>{tasks.length} tasks generated directly from requirements and grouped into {sprintCount} sprint{String(sprintCount) === '1' ? '' : 's'}.</p>
            </div>
            <div className="sprint-progress-card">
              <span>{progressPct}%</span>
              <small>board progress</small>
              <div className="sprint-progress-track">
                <div style={{ width: `${progressPct}%` }} />
              </div>
            </div>
          </section>

          <section className="sprint-stat-grid">
            <div className="sprint-stat-card"><span>Total Tasks</span><strong>{tasks.length}</strong></div>
            <div className="sprint-stat-card"><span>Estimated Hours</span><strong>{totalHours}h</strong></div>
            <div className="sprint-stat-card"><span>High Priority</span><strong>{highPriorityCount}</strong></div>
            <div className="sprint-stat-card"><span>Sprints</span><strong>{sprintCount}</strong></div>
          </section>

          <section className="task-board">
            {TASK_STATUS_COLUMNS.map((column) => {
              const columnTasks = tasks.filter((task) => task.status === column.id);
              return (
                <div className="task-column" key={column.id}>
                  <div className="task-column-header">
                    <span className="task-column-dot" style={{ background: column.tone }} />
                    <span style={{ color: column.tone }}>{column.title}</span>
                    <strong>{columnTasks.length}</strong>
                  </div>
                  <div
                    className={`task-column-body ${dragOverColumn === column.id ? 'drag-over' : ''}`}
                    onDragOver={(event) => handleDragOver(event, column.id)}
                    onDragLeave={() => dragOverColumn === column.id && setDragOverColumn(null)}
                    onDrop={(event) => handleDrop(event, column.id)}
                  >
                    {columnTasks.length === 0 ? (
                      <div className="task-column-empty">No tasks</div>
                    ) : columnTasks.map((task) => (
                      <button
                        type="button"
                        key={task.id}
                        draggable
                        onDragStart={() => handleDragStart(task.id)}
                        onDragEnd={handleDragEnd}
                        onClick={() => handleTaskSelect(task.id)}
                        className={`sprint-task-card priority-${task.priority} ${draggedTaskId === task.id ? 'dragging' : ''}`}
                      >
                        <div className="task-card-topline">
                          <span>{task.id}</span>
                          {task.sourceReq && <span>{task.sourceReq}</span>}
                        </div>
                        <h4>{task.title}</h4>
                        <p>{task.story}</p>
                        <div className="task-card-footer">
                          <span className={`task-priority-badge ${task.priority}`}>{task.priority}</span>
                          <span className="task-hours"><Clock size={12} /> {task.hours}h</span>
                          <span className="task-avatar" style={{ borderColor: task.assignee.tone, color: task.assignee.tone }}>
                            {task.assignee.id}
                          </span>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </section>

          {selectedTask && (
            <div className="task-modal-overlay" onClick={() => setSelectedTaskId(null)}>
              <section className="task-detail-panel" onClick={(e) => e.stopPropagation()}>
                <button className="btn-close-modal" onClick={() => setSelectedTaskId(null)}>
                  <X size={20} />
                </button>
                <div className="task-detail-header">
                  <div>
                    <span className="task-detail-kicker">TASK DETAILS</span>
                    <h3>{selectedTask.title}</h3>
                    <p>{selectedTask.sourceReq ? `Requirement ${selectedTask.sourceReq}` : 'Linked requirement task'}</p>
                  </div>
                  <div className={`task-detail-status status-${selectedTask.status}`}>
                    {TASK_STATUS_COLUMNS.find((column) => column.id === selectedTask.status)?.title || selectedTask.status}
                  </div>
                </div>

                <div className="task-detail-grid">
                  <div className="task-detail-card">
                    <span>Owner</span>
                    <strong>{selectedTask.assignee.name}</strong>
                    <small>{selectedTask.assignee.id}</small>
                  </div>
                  <div className="task-detail-card">
                    <span>Status</span>
                    <strong>{TASK_STATUS_COLUMNS.find((column) => column.id === selectedTask.status)?.title || selectedTask.status}</strong>
                    <small>{selectedTask.sprint}</small>
                  </div>
                  <div className="task-detail-card">
                    <span>Priority</span>
                    <strong className={`priority-label ${selectedTask.priority}`}>{selectedTask.priority}</strong>
                    <small>{selectedTask.hours}h estimate</small>
                  </div>
                  <div className="task-detail-card">
                    <span>Linked User Story</span>
                    <strong>{selectedTask.story}</strong>
                    <small>{selectedTask.workflowName}</small>
                  </div>
                </div>

                {/* Quick-move buttons */}
                <div className="task-status-actions">
                  {TASK_STATUS_COLUMNS.filter((col) => col.id !== selectedTask.status).map((col) => (
                    <button
                      key={col.id}
                      type="button"
                      onClick={() => handleUpdateTaskStatus(selectedTask.id, col.id)}
                      style={{ borderColor: col.tone, color: col.tone }}
                    >
                      Move → {col.title}
                    </button>
                  ))}
                </div>

                <div className="task-detail-sections">
                  <section className="task-detail-section">
                    <h4>Description</h4>
                    <p style={{ whiteSpace: 'pre-wrap' }}>{selectedTask.description || 'No additional task description provided.'}</p>
                  </section>
                  <section className="task-detail-section">
                    <h4>Linked User Story</h4>
                    <p>{selectedTask.userStory || selectedTask.description || 'No linked user story provided.'}</p>
                  </section>
                </div>

                <div className="task-activity-grid">
                  <section className="task-activity-section">
                    <div className="task-activity-section-header">
                      <h4>Comments</h4>
                      <span>{(taskComments[selectedTask.id] || []).length}</span>
                    </div>
                    <div className="task-comment-list">
                      {(taskComments[selectedTask.id] || []).length === 0 ? (
                        <div className="task-activity-empty">No comments yet.</div>
                      ) : (
                        (taskComments[selectedTask.id] || []).map((comment, index) => (
                          <div key={`${selectedTask.id}-comment-${index}`} className="task-comment-item">
                            <div className="task-comment-meta">
                              <strong>{comment.author}</strong>
                              <span>{comment.timestamp}</span>
                            </div>
                            <p>{comment.text}</p>
                          </div>
                        ))
                      )}
                    </div>
                    <div className="task-comment-form">
                      <textarea
                        value={commentDraft}
                        onChange={(e) => setCommentDraft(e.target.value)}
                        placeholder="Add a comment for this task..."
                        rows={3}
                      />
                      <button type="button" className="btn-task-comment" onClick={handleAddComment} disabled={!commentDraft.trim()}>
                        Add Comment
                      </button>
                    </div>
                  </section>

                  <section className="task-activity-section">
                    <div className="task-activity-section-header">
                      <h4>Logs</h4>
                      <span>{(taskLogs[selectedTask.id] || []).length}</span>
                    </div>
                    <div className="task-log-list">
                      {(taskLogs[selectedTask.id] || []).length === 0 ? (
                        <div className="task-activity-empty">No logs yet.</div>
                      ) : (
                        (taskLogs[selectedTask.id] || []).map((log, index) => (
                          <div key={`${selectedTask.id}-log-${index}`} className={`task-log-item ${log.isError ? 'log-error anim-shake' : ''}`}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: log.isError ? '4px' : '0' }}>
                              <span className="task-log-time">{log.timestamp}</span>
                              {log.isError && <AlertTriangle size={14} color="#f87171" />}
                            </div>
                            <p style={{ whiteSpace: log.isError ? 'pre-wrap' : 'normal' }}>{log.message}</p>
                          </div>
                        ))
                      )}
                    </div>
                  </section>
                </div>
              </section>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// LOCKED / COMING SOON PANEL
// ═══════════════════════════════════════════
function LockedPanel({ agent, requiredAgent }) {
  return (
    <div className="agent-panel-content locked-panel anim-fade-in">
      <div className="locked-content glass-panel">
        <div className="locked-icon-ring">
          <Lock size={40} className="pulse-slow" />
        </div>
        <span className="locked-stage-tag">STAGE LOCKED</span>
        <h2>{agent.title}</h2>
        <p>Access to the <strong>{agent.title}</strong> is currently restricted. You must first complete and approve the <strong>{requiredAgent.title}</strong> stage.</p>

        <div className="locked-requirements">
          <div className="locked-req-item done">
            <CheckCircle2 size={14} /> <span>Data Ingestion & Selection</span>
          </div>
          <div className="locked-req-item pending">
            <div className="pending-dot"></div> <span>{requiredAgent.title} Approval</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
// MAIN PIPELINE WORKSPACE
// ═══════════════════════════════════════════
export default function AgentPipeline({
  activeProject,
  requirementsData,
  projectTranscript = "",
  requirementHistory = [],
  isGenerating = false,
  isLoadingRequirements = false,
  error = "",
  onBack,
  onGenerateFromContext,
  onRefresh,
  onWorkflowSessionChange,
  selectedWorkflowSessionVersion = null
}) {
  const [activeAgentId, setActiveAgentId] = useState('workflow');
  const [completedAgents, setCompletedAgents] = useState([]);
  const [dynamicWorkflows, setDynamicWorkflows] = useState([]);
  const [approvedSessionIds, setApprovedSessionIds] = useState([]);
  const [activeWorkflowId, setActiveWorkflowId] = useState(null);
  const [isInitializing, setIsInitializing] = useState(true);
  const [pendingRequirementsFocus, setPendingRequirementsFocus] = useState(false);

  const checkPersistence = useCallback(async () => {
    const projId = activeProject?.id || activeProject?.project_id;
    if (!projId) { setIsInitializing(false); return; }

    try {
      const completed = [];
      // Check Workflow Approval
      const sessRes = await getWorkflowSessions(projId);
      const approved = sessRes?.sessions?.filter(s => s.client_approved).map(s => s.version.toString()) || [];
      setApprovedSessionIds(approved);

      if (sessRes?.sessions?.length > 0) {
        completed.push('workflow');

        // Populate dynamic workflows from sessions
        const wfs = sessRes.sessions.map(s => ({
          id: s.version.toString(),
          name: s.session_title || `Session ${s.version}`,
          approved: s.client_approved
        }));
        setDynamicWorkflows(wfs);

        if (selectedWorkflowSessionVersion != null) {
          setActiveWorkflowId(String(selectedWorkflowSessionVersion));
        } else if (wfs.length > 0 && !activeWorkflowId) {
          setActiveWorkflowId(wfs[0].id);
        }
      } else {
        setDynamicWorkflows([]);
      }

      setCompletedAgents(completed);
    } catch (err) {
      console.error("Pipeline persistence check failed:", err);
    } finally {
      setIsInitializing(false);
    }
  }, [activeProject, requirementsData, selectedWorkflowSessionVersion, activeWorkflowId]);

  useEffect(() => {
    if (selectedWorkflowSessionVersion == null) return;
    setActiveWorkflowId(String(selectedWorkflowSessionVersion));
  }, [selectedWorkflowSessionVersion]);

  useEffect(() => {
    checkPersistence();
  }, [checkPersistence]);

  // Generate the ACTUAL nav items dynamically
  const navItems = useMemo(() => {
    const items = [
      {
        id: 'workflow',
        title: "Workflow Identification",
        icon: Workflow,
        isGlobal: true
      }
    ];

    if (completedAgents.includes('workflow')) {
      // Find the currently active workflow data
      const activeWf = dynamicWorkflows.find(wf => wf.id === activeWorkflowId) || dynamicWorkflows[0];

      if (activeWf) {
        // ADD WORKFLOW HEADER
        items.push({
          id: `header:${activeWf.id}`,
          title: activeWf.name,
          type: 'header',
          isGlobal: false
        });

        // Add agents for THIS active workflow only
        AGENTS.slice(1).forEach(baseAgent => {
          items.push({
            id: `${baseAgent.id}:${activeWf.id}`,
            baseId: baseAgent.id,
            workflowId: activeWf.id,
            title: baseAgent.title,
            fullTitle: `${baseAgent.title} - ${activeWf.name}`,
            icon: baseAgent.icon,
            workflowName: activeWf.name,
            isGlobal: false
          });
        });
      }
    } else {
      // Show locked versions of global types if not even workflow is done?
      // No, let's keep it simple: Show the static ones until workflow is approved.
      AGENTS.slice(1).forEach(a => {
        items.push({
          ...a,
          isGlobal: true,
          isLocked: true
        });
      });
    }
    return items;
  }, [completedAgents, dynamicWorkflows, activeWorkflowId]);




  const activeNavItem = navItems.find(a => a.id === activeAgentId) || navItems[0];
  const hasRequirementTasks = useMemo(
    () => deriveSprintTasks(requirementsData, null, activeProject).length > 0,
    [requirementsData, activeProject]
  );

  useEffect(() => {
    if (!pendingRequirementsFocus) return;
    const reqItem = navItems.find((item) => item.baseId === 'requirements');
    if (!reqItem) return;
    setActiveAgentId(reqItem.id);
    setPendingRequirementsFocus(false);
  }, [navItems, pendingRequirementsFocus]);

  const handleAgentComplete = useCallback((agentId) => {
    setCompletedAgents(prev => {
      if (prev.includes(agentId)) return prev;
      const nextCompleted = [...prev, agentId];

      const nextIndex = navItems.findIndex(a => a.id === agentId) + 1;
      for (let i = nextIndex; i < navItems.length; i += 1) {
        const candidate = navItems[i];
        if (candidate?.type === 'header') continue;

        let candidateLocked = candidate.isLocked;
        if (!candidateLocked && !nextCompleted.includes(candidate.id) && i > 0) {
          let prevIdx = i - 1;
          while (prevIdx >= 0 && navItems[prevIdx].type === 'header') prevIdx--;
          const previousItem = prevIdx >= 0 ? navItems[prevIdx] : null;
          const workflowIsDone = nextCompleted.includes('workflow');

          if (candidate.baseId === 'requirements' || candidate.baseId === 'doc') {
            candidateLocked = !workflowIsDone;
          } else if (candidate.baseId === 'task_sprint') {
            candidateLocked = !hasRequirementTasks;
          } else if (previousItem) {
            candidateLocked = !nextCompleted.includes(previousItem.id);
          }
        }

        if (!candidateLocked) {
          setActiveAgentId(candidate.id);
          break;
        }
      }

      return nextCompleted;
    });
  }, [navItems, hasRequirementTasks]);

  return (
    <div className="pipeline-workspace">
      {/* ── LEFT SIDEBAR ── */}
      <aside className="pipeline-sidebar">
        <div className="pipeline-sidebar-header">
          <button className="btn-sidebar-back" onClick={onBack}>
            <ArrowLeft size={16} />
          </button>
          <div className="sidebar-title-group">
            <span className="sidebar-brand">AGENTIC</span>
            <span className="sidebar-tagline">PIPELINE</span>
          </div>
        </div>

        <div className="pipeline-sidebar-project">
          <div className="project-dot" />
          <span>{activeProject?.project_name || activeProject?.company || 'Project'}</span>
        </div>

        <nav className="pipeline-agent-list">
          {navItems.map((agent, idx) => {
            const Icon = agent.icon;
            const isActive = activeAgentId === agent.id;
            const isCompleted = completedAgents.includes(agent.id);

            if (agent.type === 'header') {
              return (
                <div key={agent.id} className="agent-nav-header">
                  <span>{agent.title} FLOW</span>
                </div>
              );
            }

            // Sequential locking:
            // 1. If agent is explicitly locked by state
            // 2. Default sequential: must finish previous item
            // EXCEPTION: Reqs and Docs for a workflow are unlocked if 'workflow' (global) is done.
            let isLocked = agent.isLocked;
            if (!isLocked && !isCompleted && idx > 0) {
              // Be careful with idx-1 if it's a header
              let prevIdx = idx - 1;
              while (prevIdx >= 0 && navItems[prevIdx].type === 'header') prevIdx--;

              const previousItem = prevIdx >= 0 ? navItems[prevIdx] : null;

              // Track-specific lock: Check if THIS session is approved
              const sessionIsApproved = approvedSessionIds.includes(agent.workflowId);

              if (['requirements', 'doc', 'ui_design', 'task_sprint', 'qa_agent', 'deployment_agent'].includes(agent.baseId)) {
                if (agent.baseId === 'task_sprint') {
                  isLocked = !sessionIsApproved || !hasRequirementTasks;
                } else {
                  isLocked = !sessionIsApproved;
                }
              } else if (previousItem) {
                // Strict sequential for other deeper agents
                isLocked = !completedAgents.includes(previousItem.id);
              }
            }

            return (
              <button
                key={agent.id}
                className={`agent-nav-item ${isActive ? 'active' : ''} ${isCompleted ? 'completed' : ''} ${isLocked ? 'locked' : ''} ${!agent.isGlobal ? 'workflow-sub-item' : ''}`}
                onClick={() => !isLocked && setActiveAgentId(agent.id)}
                disabled={isLocked}
              >
                <div className="agent-nav-indicator">
                  {isCompleted ? (
                    <CheckCircle2 size={18} color="#10b981" />
                  ) : isActive ? (
                    <div className="active-dot-ring">
                      <Circle size={10} fill="#60a5fa" color="#60a5fa" />
                    </div>
                  ) : isLocked ? (
                    <Lock size={14} color="#334155" />
                  ) : (
                    <Circle size={16} color="#334155" />
                  )}
                </div>
                <div className="agent-nav-info">
                  <span className="agent-nav-title">{agent.title}</span>
                </div>
                {isActive && <ChevronRight size={14} className="agent-nav-arrow" />}
              </button>
            );
          })}
        </nav>

        <div className="pipeline-sidebar-footer">
          <Sparkles size={14} color="#fbbf24" />
          <span>{completedAgents.length}/{AGENTS.length} completed</span>
        </div>
      </aside>

      {/* ── RIGHT CONTENT PANEL ── */}
      <main className="pipeline-main custom-scroll">
        {isInitializing ? (
          <div className="agent-panel-content">
            <div className="agent-loading-state">
              <Loader2 size={32} className="spin" />
              <span>Synchronizing Pipeline State...</span>
            </div>
          </div>
        ) : activeNavItem?.id === 'workflow' ? (
          <WorkflowPanel
            activeProject={activeProject}
            activeWorkflowId={activeWorkflowId}
            onComplete={() => {
              handleAgentComplete('workflow');
              checkPersistence();
            }}
            onApprovalChange={() => checkPersistence()}
            onSessionChange={(id) => setActiveWorkflowId(id)}
            onGenerateFromContext={onGenerateFromContext}
            onProjectRefresh={onRefresh}
            onFocusRequirements={() => setPendingRequirementsFocus(true)}
            onWorkflowSessionChange={onWorkflowSessionChange}
          />
        ) : activeNavItem?.baseId === 'requirements' ? (
          <RequirementsPanel
            activeProject={activeProject}
            requirementsData={requirementsData}
            projectTranscript={projectTranscript}
            requirementHistory={requirementHistory}
            isGenerating={isGenerating}
            isLoadingRequirements={isLoadingRequirements}
            error={error}
            onGenerateFromContext={onGenerateFromContext}
            onComplete={() => handleAgentComplete(activeNavItem.id)}
            workflowId={activeNavItem.workflowId}
            selectedWorkflowSessionVersion={selectedWorkflowSessionVersion}
          />
        ) : activeNavItem?.baseId === 'task_sprint' ? (
          <TaskSprintPanel
            activeProject={activeProject}
            requirementsData={requirementsData}
            workflowId={activeNavItem?.workflowId}
            workflowName={dynamicWorkflows?.find(w => w.id === activeNavItem?.workflowId)?.name || ''}
            selectedWorkflowSessionVersion={selectedWorkflowSessionVersion}
            onComplete={() => handleAgentComplete(activeNavItem.id)}
          />
        ) : activeNavItem?.baseId === 'doc' ? (
          <div className="agent-panel-content">
            <div className="agent-panel-header">
              <div className="agent-panel-icon doc-icon"> <FileText size={24} /> </div>
              <div>
                <h2>Design Architect Agent</h2>
                <p>Workflow: <strong>{dynamicWorkflows?.find(w => w.id === activeNavItem?.workflowId)?.name || 'Processing...'}</strong></p>
              </div>
            </div>
            <DocAgent
              activeProject={activeProject}
              requirementsData={requirementsData}
              workflowId={activeNavItem?.workflowId}
              workflowName={dynamicWorkflows?.find(w => w.id === activeNavItem?.workflowId)?.name || ''}
              onComplete={() => handleAgentComplete(activeNavItem.id)}
            />
          </div>
        ) : activeNavItem?.baseId === 'ui_design' ? (
          <div className="agent-panel-content">
            <UIDesignAgent
              activeProject={activeProject}
              workflowId={activeNavItem?.workflowId}
              workflowName={dynamicWorkflows?.find(w => w.id === activeNavItem?.workflowId)?.name || ''}
              onComplete={() => handleAgentComplete(activeNavItem.id)}
            />
          </div>
        ) : activeNavItem?.baseId === 'qa_agent' ? (
          <QAAgent
            activeProject={activeProject}
            workflowId={activeNavItem?.workflowId}
            workflowName={dynamicWorkflows?.find(w => w.id === activeNavItem?.workflowId)?.name || ''}
            onComplete={() => handleAgentComplete(activeNavItem.id)}
          />
        ) : activeNavItem?.baseId === 'deployment_agent' ? (
          <div className="agent-panel-content anim-fade-in">
            <div className="agent-panel-header">
              <div className="agent-panel-icon doc-icon"> <Cloud size={24} /> </div>
              <div>
                <h2>Deployment Agent</h2>
                <p>Workflow: <strong>{dynamicWorkflows?.find(w => w.id === activeNavItem?.workflowId)?.name || 'Processing...'}</strong></p>
              </div>
            </div>
            <div className="task-empty-state" style={{ marginTop: 40 }}>
              <Cloud size={48} style={{ opacity: 0.5, marginBottom: 20 }} />
              <h3>Infrastructure & Deployment</h3>
              <p>Deployment pipeline generation is currently being provisioned.</p>
            </div>
          </div>
        ) : (
          <div className="agent-panel-content locked-panel">
            <div className="locked-content">
              <div className="locked-icon-ring"><Lock size={32} /></div>
              <div className="locked-workflow-tag">{dynamicWorkflows?.find(w => w.id === activeNavItem?.workflowId)?.name || 'Project Flow'}</div>
              <h2>{activeNavItem?.fullTitle || activeNavItem?.title || 'Locked Stage'}</h2>
              <p>The <strong>{activeNavItem?.baseId || 'module'}</strong> for this specific workflow is under orchestration and will be available in the upcoming release.</p>
              <div className="locked-badge">ENGINEERING IN PROGRESS</div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}



