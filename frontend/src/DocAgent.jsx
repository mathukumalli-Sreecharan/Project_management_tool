import { useState, useRef, useEffect } from 'react';
import {
  FileText, Sparkles, Workflow, Database,
  CheckCircle2, Clock, Loader2, UploadCloud, AlertTriangle,
  Eye, Download, FileImage, Bot
} from 'lucide-react';

import { getWorkflowSessions, getWorkflowSession, getLatestRequirements, getProjectContext, runDocAgent, getLatestDocArtifact, extractFileText, refineDocAgent, runIAGeneration } from './api';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './DocAgent.css';

const API_BASE = import.meta.env.VITE_API_BASE || '';

// ═══════════════════════════════════════════
// MERMAID DIAGRAM RENDERER (Shared Context)
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
            flowchart: { nodeSpacing: 30, rankSpacing: 55, padding: 18, htmlLabels: true, curve: 'basis', useMaxWidth: true },
            themeVariables: {
              fontSize: '13px', primaryColor: '#3b82f6', primaryTextColor: '#f1f5f9', primaryBorderColor: '#60a5fa',
              lineColor: '#475569', secondaryColor: '#1e293b', tertiaryColor: '#0f172a', edgeLabelBackground: '#0f172a',
              mainBkg: '#1e293b', nodeBorder: '#3b82f6', clusterBkg: 'rgba(59, 130, 246, 0.04)', clusterBorder: 'rgba(96, 165, 250, 0.25)',
            },
            themeCSS: `
              .node rect, .node circle, .node polygon, .node path { stroke-width: 2px !important; fill: #1e293b !important; rx: 8px !important; ry: 8px !important; }
              .node .label { font-weight: 600 !important; font-size: 12px !important; color: #f1f5f9 !important; font-family: 'Inter', sans-serif !important; }
              .edgePath .path { stroke: #475569 !important; stroke-width: 1.5px !important; }
              .marker { fill: #475569 !important; stroke: #475569 !important; }
              .edgeLabel { background-color: #0f172a !important; color: #94a3b8 !important; font-size: 10px !important; font-weight: 500 !important; padding: 3px 6px !important; border-radius: 4px !important; }
              .cluster rect { fill: rgba(15, 23, 42, 0.6) !important; stroke: rgba(96, 165, 250, 0.2) !important; stroke-width: 1.5px !important; rx: 12px !important; ry: 12px !important; }
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

  if (renderError) return <div className="mermaid-error"><AlertTriangle size={16} /> Syntax Error</div>;

  return (
    <div className="mermaid-container" ref={containerRef}>
      <div className="mermaid-loading"><Loader2 size={16} className="spin" /></div>
    </div>
  );
}


// ═══════════════════════════════════════════
// PREMIUM DESIGN VIEWER (Markdown + Mermaid)
// ═══════════════════════════════════════════
function RichDesignViewer({ content }) {
  if (!content) return null;

  return (
    <div className="rich-design-viewer">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ node, ...props }) => <h1 className="design-h1" {...props} />,
          h2: ({ node, ...props }) => <h2 className="design-h2" {...props} />,
          h3: ({ node, ...props }) => <h3 className="design-h3" {...props} />,
          table: ({ node, ...props }) => (
            <div className="design-table-wrapper">
              <table className="design-table" {...props} />
            </div>
          ),
          code: ({ node, inline, className, children, ...props }) => {
            const match = /language-(\w+)/.exec(className || '');
            const lang = match ? match[1] : '';

            if (!inline && lang === 'mermaid') {
              return <MermaidDiagram code={String(children).replace(/\n$/, '')} />;
            }

            if (inline) {
              return (
                <code className="design-code-inline" {...props}>
                  {children}
                </code>
              );
            }

            // Only show the "fancy box" if it's actual code (json, sql, etc.)
            // If it's just 'text' or empty, keep it minimal
            const isActualCode = lang && lang !== 'text';

            return isActualCode ? (
              <div className="design-code-block-container">
                <div className="code-block-header">{lang}</div>
                <pre className="design-code-block">
                  <code className={className} {...props}>
                    {children}
                  </code>
                </pre>
              </div>
            ) : (
              <pre className="design-code-minimal">
                <code {...props}>{children}</code>
              </pre>
            );
          },
          blockquote: ({ node, ...props }) => {
            const text = String(props.children[1]?.props?.children || '');
            if (text.includes('⚠️ GAP') || text.includes('⚠️ UNSPECIFIED')) {
              return <div className="design-alert gap" {...props} />;
            }
            return <blockquote className="design-blockquote" {...props} />;
          }
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

// ═══════════════════════════════════════════
// DOC AGENT PANEL
// ═══════════════════════════════════════════
export default function DocAgent({
  activeProject,
  requirementsData = null,
  workflowId = null,
  workflowName = '',
  onComplete
}) {
  const [docInput, setDocInput] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);
  const [techStack, setTechStack] = useState('');
  const [activeTab, setActiveTab] = useState('HLD');
  const [showJson, setShowJson] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState([]); // [{name, text}]
  const [showRefinePrompt, setShowRefinePrompt] = useState(false);
  const [refineFeedback, setRefineFeedback] = useState('');
  const [isRefining, setIsRefining] = useState(false);
  const [isGeneratingIA, setIsGeneratingIA] = useState(false);
  const [leadId, setLeadId] = useState('');



  // Context state
  const [workflowContext, setWorkflowContext] = useState(null);
  const [workflowRequirements, setWorkflowRequirements] = useState(null);
  const [isLoadingContext, setIsLoadingContext] = useState(true);

  const fileInputRef = useRef(null);

  // ── Load workflow context on mount ──
  useEffect(() => {
    const loadWorkflowContext = async () => {
      const projId = activeProject?.id || activeProject?.project_id;
      if (!projId) { setIsLoadingContext(false); return; }

      try {
        try {
          const projectContext = await getProjectContext(projId);
          setLeadId(projectContext?.project?.lead_id || projId);
        } catch {
          setLeadId(projId);
        }

        const sessRes = await getWorkflowSessions(projId);
        const sessions = sessRes?.sessions || [];

        // Match specific version
        let target = null;
        if (workflowId) {
          // 1. Try matching by version string (e.g. "1")
          target = sessions.find(s => s.version.toString() === workflowId && s.client_approved);
          if (!target) {
            target = sessions.find(s => s.version.toString() === workflowId);
          }

          // 2. Try encoded match (e.g. "proj_v1_to_be")
          if (!target && workflowId.includes('_v')) {
            const match = workflowId.match(/_v(\d+)/);
            if (match) {
              const version = parseInt(match[1]);
              target = sessions.find(s => s.version === version && s.client_approved);
              if (!target) {
                target = sessions.find(s => s.version === version);
              }
            }
          }
        }

        // Fallback to latest approved session if no specific track match
        if (!target) {
          target = sessions.find(s => s.client_approved);
        }


        if (target) {
          const detail = await getWorkflowSession(projId, target.version);
          const session = detail?.session;

          // CRITICAL: Parse mermaid code if it's wrapped in markdown
          let rawToBe = session?.to_be || '';
          let cleanedToBe = rawToBe;
          if (rawToBe.includes('```mermaid')) {
            const match = rawToBe.match(/```mermaid([\s\S]*?)```/);
            if (match) cleanedToBe = match[1].trim();
          }

          // 2. Fetch specific JSON requirements for this workflow
          try {
            const reqRes = await getLatestRequirements(projId, { workflow_id: workflowId });
            const requirements = reqRes?.requirements || reqRes?.requirements_state?.current_requirements;
            setWorkflowRequirements(requirements || null);
          } catch (err) {
            console.error('Failed to load specific requirements:', err);
          }

          setWorkflowContext({
            version: target.version,
            title: target.session_title || `Session ${target.version}`,
            hasAsIs: Boolean(session?.as_is),
            hasToBe: Boolean(session?.to_be),
            contentToBe: cleanedToBe
          });
        }
      } catch (err) {
        console.error('Failed to load workflow context:', err);
      } finally {
        setIsLoadingContext(false);
      }
    };

    loadWorkflowContext();
  }, [activeProject, workflowId]);

  // ── Load latest generated design artifact on mount/switch ──
  useEffect(() => {
    const loadLatestArtifact = async () => {
      const projId = activeProject?.id || activeProject?.project_id;
      const docLeadId = leadId || projId;
      if (!docLeadId || !workflowId) return;

      try {
        const res = await getLatestDocArtifact(docLeadId, workflowId);
        if (res.status === 'ok' && res.artifact) {
          setResults({
            status: 'success',
            message: `Version ${res.artifact.version} loaded from history`,
            design: {
              project_summary: res.artifact.project_summary || 'Summary not available',
              hld_content: res.artifact.hld_content,
              lld_content: res.artifact.lld_content,
              ia_content: res.artifact.ia_content || '', // Frontend-only field for now
              db_schema: res.artifact.db_schema,
              backlog: res.artifact.backlog
            }
          });
        }
      } catch (err) {
        console.error('Failed to load latest artifact:', err);
      }
    };
    loadLatestArtifact();
  }, [activeProject, workflowId, leadId]);

  // ── Derive status for context cards ──
  const workflowStatus = workflowContext ? 'active' : 'inactive';
  const workflowStatusLabel = workflowContext
    ? `Approved v${workflowContext.version}`
    : 'Not Ingested';

  const requirementsStatus = requirementsData ? 'active' : 'inactive';
  const requirementsStats = (() => {
    const data = workflowRequirements;
    if (!data) return null;


    let epics = 0;
    let reqs = 0;

    if (Array.isArray(data.workflows)) {
      data.workflows.forEach(wf => {
        if (Array.isArray(wf.epics)) {
          epics += wf.epics.length;
          wf.epics.forEach(ep => {
            if (Array.isArray(ep.requirements)) {
              reqs += ep.requirements.length;
            }
          });
        }
      });
    } else if (Array.isArray(data.requirements)) {
      reqs = data.requirements.length;
      // If it's a flat list, we might not have epics or they might be embedded
    }

    return { epics, reqs };
  })();

  // ── Download workflow as PNG handler ──
  const handleDownloadWorkflowImage = () => {
    const container = document.getElementById('doc-hidden-mermaid-render');
    const svg = container?.querySelector('svg');

    if (!svg) {
      alert("Preparing workflow image... Please try again in a second.");
      return;
    }

    const downloadSvgFallback = (svgData) => {
      const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(svgBlob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${workflowContext.title}_ToBe_Workflow.svg`;
      a.click();
      URL.revokeObjectURL(url);
    };

    try {
      const serializer = new XMLSerializer();
      let svgData = serializer.serializeToString(svg);
      if (!svgData.includes('xmlns="http://www.w3.org/2000/svg"')) {
        svgData = svgData.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"');
      }

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
          a.download = `${workflowContext.title}_ToBe_Workflow.png`;
          a.click();
        } catch (e) {
          console.error("PNG export error:", e);
          downloadSvgFallback(svgData);
        }
      };

      img.onerror = () => downloadSvgFallback(svgData);
      const base64 = btoa(unescape(encodeURIComponent(svgData)));
      img.src = 'data:image/svg+xml;base64,' + base64;
    } catch (err) {
      console.error("Export failed:", err);
    }
  };


  // ── File upload handler ──
  const handleFileUpload = async (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;

    setIsGenerating(true);
    setError(null);

    const newUploadedFiles = [];

    for (const file of files) {
      const fileName = file.name;
      const isPlainText = fileName.toLowerCase().endsWith('.txt') || fileName.toLowerCase().endsWith('.md');

      try {
        let text = '';
        if (isPlainText) {
          text = await new Promise((resolve) => {
            const reader = new FileReader();
            reader.onload = (ev) => resolve(ev.target.result);
            reader.readAsText(file);
          });
        } else {
          const res = await extractFileText(file);
          if (res.status === 'ok') {
            text = res.text;
          } else {
            throw new Error(res.error || 'Extraction failed');
          }
        }
        newUploadedFiles.push({ name: fileName, text });
      } catch (err) {
        console.error(`Error uploading ${fileName}:`, err);
        setError(`Failed to process ${fileName}`);
      }
    }

    setUploadedFiles(prev => [...prev, ...newUploadedFiles]);
    setIsGenerating(false);
    e.target.value = '';
  };

  const removeFile = (index) => {
    setUploadedFiles(prev => prev.filter((_, i) => i !== index));
  };

  // ── Generate handler ──
  const handleGenerate = async () => {
    setIsGenerating(true);
    setError(null);
    setResults(null);

    // Aggregate all context
    const aggregatedContext = [
      docInput.trim(),
      ...uploadedFiles.map(f => `--- SOURCE: ${f.name} ---\n${f.text}`)
    ].filter(Boolean).join('\n\n');

    if (!aggregatedContext && !techStack) {
      setError("Please provide at least some technical context or upload a document.");
      setIsGenerating(false);
      return;
    }

    try {
      const res = await runDocAgent(
        leadId || activeProject?.id || activeProject?.project_id,
        workflowId || 'default',
        techStack,
        aggregatedContext
      );

      if (res.status === 'ok') {
        setResults({
          status: 'success',
          message: 'Documents generated successfully!',
          design: res.design
        });
      } else {
        throw new Error(res.error || 'Failed to generate documents');
      }
    } catch (err) {
      console.error('Doc generation error:', err);
      setError(err.message || 'Document generation failed. Please check your backend is running.');
    } finally {
      setIsGenerating(false);
    }
  };

  // ── Refine handler ──
  const handleRefine = async () => {
    if (!refineFeedback.trim()) return;
    setIsRefining(true);
    setError(null);

    try {
      const res = await refineDocAgent(
        leadId || activeProject?.id || activeProject?.project_id,
        workflowId || 'default',
        refineFeedback
      );

      if (res.status === 'ok') {
        setResults({
          status: 'success',
          message: `Refinement v${res.version} completed successfully!`,
          design: res.design
        });
        setRefineFeedback('');
        setShowRefinePrompt(false);
      } else {
        throw new Error(res.error || 'Refinement failed');
      }
    } catch (err) {
      console.error('Refinement error:', err);
      setError(err.message || 'Failed to refine the design.');
    } finally {
      setIsRefining(false);
    }
  };

  // ── IA Generate handler ──
  const handleGenerateIA = async () => {
    setIsGeneratingIA(true);
    setError(null);

    try {
      const res = await runIAGeneration(
        leadId || activeProject?.id || activeProject?.project_id,
        workflowId || 'default'
      );

      if (res.status === 'ok') {
        setResults(prev => ({
          ...prev,
          design: {
            ...prev.design,
            ia_content: res.ia_content
          }
        }));
      } else {
        throw new Error(res.error || 'IA generation failed');
      }
    } catch (err) {
      console.error('IA generation error:', err);
      setError(err.message || 'Failed to generate IA blueprint.');
    } finally {
      setIsGeneratingIA(false);
    }
  };

  // ── Download PDF handler ──

  const handleDownloadPdf = (type = 'full') => {
    if (!activeProject || !results) return;
    const projId = leadId || activeProject.id || activeProject.project_id;
    const wfParam = workflowId ? `&workflow_id=${encodeURIComponent(workflowId)}` : '';
    const url = `${API_BASE}/api/agents/doc-download-pdf?lead_id=${encodeURIComponent(projId)}${wfParam}&doc_type=${encodeURIComponent(type)}`;
    window.open(url, '_blank');
  };

  return (
    <div className="doc-agent-shell">

      {/* ── CONTEXT CARDS ── */}
      <div className="doc-agent-context-row">
        {/* Workflow Card */}
        <div className="doc-context-card workflow-card">
          <div className="doc-context-card-header">
            <div className="doc-context-icon workflow">
              <Workflow size={20} />
            </div>
            <div className="doc-context-body">
              <span className="doc-context-label">Ingested Workflow</span>
              <div className="doc-context-value-row">
                <span className="doc-context-value">
                  {isLoadingContext
                    ? 'Loading...'
                    : workflowContext
                      ? workflowContext.title
                      : 'No workflow ingested'}
                </span>
                {workflowContext?.hasToBe && (
                  <button
                    className="doc-icon-btn"
                    title="Download Workflow Image (PNG)"
                    onClick={handleDownloadWorkflowImage}
                  >
                    <FileImage size={14} />
                  </button>
                )}
              </div>
            </div>
          </div>
          <div className={`doc-context-status ${workflowStatus}`}>
            {workflowStatus === 'active'
              ? <><CheckCircle2 size={13} /> {workflowStatusLabel}</>
              : <><Clock size={13} /> {workflowStatusLabel}</>
            }
          </div>

          {workflowContext && (
            <p className="doc-context-meta">
              AS-IS {workflowContext.hasAsIs ? '✓' : '—'} &nbsp;|&nbsp; TO-BE {workflowContext.hasToBe ? '✓' : '—'}
            </p>
          )}
        </div>

        {/* Requirements Card */}
        <div className="doc-context-card requirements-card">
          <div className="doc-context-card-header">
            <div className="doc-context-icon requirements">
              <Database size={20} />
            </div>
            <div className="doc-context-body">
              <span className="doc-context-label">Project Requirements</span>
              <span className="doc-context-value">
                {requirementsStats
                  ? (requirementsStats.epics > 0
                    ? `${requirementsStats.epics} Epics, ${requirementsStats.reqs} Req`
                    : `${requirementsStats.reqs} Requirements`)
                  : 'No requirements for this flow'}
              </span>
            </div>
            <button
              className={`doc-icon-btn ${showJson ? 'active' : ''}`}
              onClick={() => setShowJson(!showJson)}
              title="View Raw JSON"
            >
              <Eye size={14} />
            </button>
          </div>
          <div className={`doc-context-status ${requirementsStats?.reqs > 0 ? 'active' : 'inactive'}`}>
            {requirementsStats?.reqs > 0
              ? <><CheckCircle2 size={13} /> Requirements Ready</>
              : <><Clock size={13} /> No Requirements Found</>
            }
          </div>
          {workflowRequirements && (
            <p className="doc-context-meta">
              {Array.isArray(workflowRequirements.workflows)
                ? `${workflowRequirements.workflows.length} workflow${workflowRequirements.workflows.length !== 1 ? 's' : ''} mapped`
                : 'Single workflow scope'}
            </p>
          )}

          {showJson && (
            <div className="doc-json-preview anim-slide-down">
              <pre>
                {JSON.stringify(workflowRequirements, null, 2)}
              </pre>
            </div>
          )}

        </div>
      </div>

      {/* ── DOC INPUT SECTION (Workflow Agent style) ── */}
      <div className="doc-input-section">
        <div className="doc-input-section-header">
          <h3><FileText size={16} /> Document Input</h3>
          <div className="doc-input-actions">
            <input
              type="file"
              ref={fileInputRef}
              hidden
              multiple
              accept=".txt,.md,.doc,.docx,.pdf,.json,.csv"
              onChange={handleFileUpload}
            />
            <button
              className="doc-btn-upload-file"
              onClick={() => fileInputRef.current?.click()}
            >
              <UploadCloud size={14} /> Upload Files
            </button>
          </div>
        </div>

        <textarea
          className="doc-textarea custom-scroll"
          style={{ minHeight: '120px' }}
          placeholder="Provide additional technical context, architecture standards, or specific instructions here..."
          value={docInput}
          onChange={(e) => setDocInput(e.target.value)}
          rows={5}
        />

        {uploadedFiles.length > 0 && (
          <div className="doc-attachments-list">
            {uploadedFiles.map((file, idx) => (
              <div key={idx} className="doc-attachment-item anim-fade-in">
                <div className="attachment-info">
                  <FileText size={14} />
                  <span className="attachment-name" title={file.name}>{file.name}</span>
                </div>
                <div className="attachment-actions">
                  <span className="attachment-size">{Math.round(file.text.length / 1024)} KB</span>
                  <button className="attachment-remove" onClick={() => removeFile(idx)} title="Remove file">×</button>
                </div>
              </div>
            ))}
          </div>
        )}

        {error && (
          <div className="doc-error anim-fade-in">
            <AlertTriangle size={14} />
            <span>{error}</span>
          </div>
        )}

        {results && results.status === 'success' && !results.message.includes('Refinement') && (
          <div className="doc-success anim-fade-in">
            <CheckCircle2 size={14} />
            <span>{results.message}</span>
          </div>
        )}

        <div className="doc-actions-bar">
          <span className="doc-char-count">{docInput.length.toLocaleString()} characters</span>
          <button
            className="doc-btn-generate"
            onClick={handleGenerate}
            disabled={!docInput.trim() || isGenerating}
          >
            {isGenerating ? (
              <>
                <Loader2 size={16} className="spin" />
                Generating Documents…
              </>
            ) : (
              <>
                <Sparkles size={16} />
                Generate Documents
              </>
            )}
          </button>
        </div>
      </div>

      {/* ── RESULTS DISPLAY ── */}
      {results?.design && (
        <div className="doc-results-section anim-fade-in">
          <div className="doc-results-header">
            <h3><CheckCircle2 size={16} /> Generation Results</h3>
            <div className="doc-results-actions" style={{ gap: '12px' }}>
              <button className="doc-icon-btn hld-btn" title="Download HLD PDF" onClick={() => handleDownloadPdf('hld')}>
                <Download size={14} /> <span>HLD PDF</span>
              </button>
              <button className="doc-icon-btn lld-btn" title="Download LLD PDF" onClick={() => handleDownloadPdf('lld')}>
                <Download size={14} /> <span>LLD PDF</span>
              </button>
            </div>
          </div>

          <div className="doc-results-summary">
            {results.message.includes('Refinement') && (
              <div className="doc-refine-success-banner anim-slide-down">
                <Sparkles size={14} />
                <span>{results.message}</span>
              </div>
            )}
            <p>{results.design.project_summary}</p>
          </div>

          <div className="doc-results-tabs">
            <div className="doc-tabs-header">
              <div className="doc-tabs-main">
                {['HLD', 'LLD', 'IA'].map(tab => (
                  <button
                    key={tab}
                    className={activeTab === tab ? 'active' : ''}
                    onClick={() => setActiveTab(tab)}
                  >
                    {tab}
                  </button>
                ))}
                <button
                  className={`doc-refine-trigger-btn ${showRefinePrompt ? 'active' : ''}`}
                  title="Refine Design with AI Feedback"
                  onClick={() => setShowRefinePrompt(!showRefinePrompt)}
                >
                  <img src="/assets/bot-icon.png" alt="AI Refine" className="doc-refine-bot-img" />
                </button>
              </div>
            </div>

            {showRefinePrompt && (
              <div className="doc-refine-prompt-panel anim-slide-down">
                <div className="refine-prompt-header">
                  <Bot size={14} />
                  <span>AI Design Refinement</span>
                </div>
                <textarea
                  className="refine-textarea"
                  placeholder="What would you like to change? (e.g. 'Add a Redis cache', 'Split the API into microservices', 'Update the DB schema for GDPR')..."
                  value={refineFeedback}
                  onChange={(e) => setRefineFeedback(e.target.value)}
                  disabled={isRefining}
                />
                <div className="refine-prompt-actions">
                  <button
                    className="refine-btn-cancel"
                    onClick={() => setShowRefinePrompt(false)}
                    disabled={isRefining}
                  >
                    Cancel
                  </button>
                  <button
                    className="refine-btn-submit"
                    onClick={handleRefine}
                    disabled={!refineFeedback.trim() || isRefining}
                  >
                    {isRefining ? (
                      <><Loader2 size={14} className="spin" /> Refining... </>
                    ) : (
                      <><Sparkles size={14} /> Refine Design</>
                    )}
                  </button>
                </div>
              </div>
            )}

            <div className="doc-tab-content custom-scroll">
              <div className="doc-markdown-render">
                {activeTab === 'HLD' && (
                  <RichDesignViewer content={results.design.hld_content} />
                )}
                {activeTab === 'LLD' && (
                  <RichDesignViewer content={results.design.lld_content} />
                )}
                {activeTab === 'IA' && (
                  results.design.ia_content ? (
                    <RichDesignViewer content={results.design.ia_content} />
                  ) : (
                    <div className="doc-ia-placeholder anim-fade-in">
                      <div className="ia-placeholder-icon">
                        <Sparkles size={32} />
                      </div>
                      <h4>Information Architecture Blueprint</h4>
                      <p>Generate a structural visual blueprint based on your HLD and LLD context.</p>
                      <button 
                        className="ia-generate-btn" 
                        onClick={handleGenerateIA}
                        disabled={isGeneratingIA}
                      >
                        {isGeneratingIA ? (
                          <><Loader2 size={16} className="spin" /> Synthesizing IA... </>
                        ) : (
                          <><Sparkles size={16} /> Generate IA Blueprint </>
                        )}
                      </button>
                    </div>
                  )
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── HIDDEN RENDERER FOR IMAGE EXPORT ── */}
      <div
        id="doc-hidden-mermaid-render"
        style={{ position: 'absolute', top: -9999, left: -9999, width: 2000 }}
      >
        {workflowContext?.contentToBe && (
          <MermaidDiagram code={workflowContext.contentToBe} />
        )}
      </div>
    </div>
  );
}
