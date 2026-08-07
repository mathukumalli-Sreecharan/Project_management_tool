import React, { useState, useEffect, useMemo } from 'react';
import {
    Layout, Sparkles, Workflow, CheckCircle2,
    Clock, FileText, AlertTriangle, ChevronRight,
    ShieldCheck, Database, Layers, Loader2
} from 'lucide-react';
import { getWorkflowSession, getLatestDocArtifact, getProjectContext, runUISynthesis, refineUISynthesis } from './api';
import './ui_-design.css';

const UIDesignAgent = ({ activeProject, workflowId, workflowName, onComplete }) => {
    const [session, setSession] = useState(null);
    const [docArtifact, setDocArtifact] = useState(null);
    const [leadId, setLeadId] = useState('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [isSynthesizing, setIsSynthesizing] = useState(false);
    const [isRefining, setIsRefining] = useState(false);
    const [synthesisResult, setSynthesisResult] = useState(null);
    const [uiFeedback, setUiFeedback] = useState('');

    const projectId = useMemo(() => activeProject?.id || activeProject?.project_id, [activeProject]);
    const isWorkflowApproved = !!session?.client_approved;
    const hasHld = !!docArtifact?.hld_content;
    const hasLld = !!docArtifact?.lld_content;

    useEffect(() => {
        let isMounted = true;
        const fetchData = async () => {
            if (!projectId || !workflowId) {
                if (isMounted) setLoading(false);
                return;
            }
            if (isMounted) setLoading(true);
            try {
                let resolvedLeadId = projectId;
                try {
                    const projectContext = await getProjectContext(projectId);
                    resolvedLeadId = projectContext?.project?.lead_id || projectId;
                    if (isMounted) setLeadId(resolvedLeadId);
                } catch {
                    if (isMounted) setLeadId(projectId);
                }

                const sessRes = await getWorkflowSession(projectId, workflowId);
                if (isMounted && sessRes?.status === 'success') {
                    setSession(sessRes.session);
                }
                const docRes = await getLatestDocArtifact(resolvedLeadId, workflowId);
                if (isMounted && docRes?.status === 'ok') setDocArtifact(docRes.artifact);
            } catch (err) {
                if (isMounted) setError('Context sync failed.');
            } finally {
                if (isMounted) setLoading(false);
            }
        };
        fetchData();
        return () => { isMounted = false; };
    }, [projectId, workflowId]);

    const handleInitializeSynthesis = async () => {
        setIsSynthesizing(true);
        setError(null);
        try {
            const res = await runUISynthesis(projectId, workflowId, session?.version);
            if (res.status === 'success') setSynthesisResult(res);
            else throw new Error(res.error || res.message || 'Synthesis failed.');
        } catch (err) {
            setError(err.message || 'Synthesis failed.');
        } finally {
            setIsSynthesizing(false);
        }
    };

    const handleRefineUI = async () => {
        if (!uiFeedback.trim()) return;
        setIsRefining(true);
        setError(null);
        try {
            const res = await refineUISynthesis(projectId, workflowId, session?.version, uiFeedback);
            if (res.status === 'success') {
                setSynthesisResult(res);
                setUiFeedback('');
            } else throw new Error(res.error || res.message || 'Refinement failed.');
        } catch (err) {
            setError(err.message || 'Refinement failed.');
        } finally {
            setIsRefining(false);
        }
    };

    const renderPreview = () => {
        if (!synthesisResult?.code) return null;
        const code = synthesisResult.code;
        const isFullHtml = code.trim().toLowerCase().startsWith('<!doctype') || code.trim().toLowerCase().startsWith('<html');

        const htmlContent = isFullHtml ? code : `
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8" />
                <script src="https://unpkg.com/react@18/umd/react.development.js"></script>
                <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
                <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
                <script src="https://cdn.tailwindcss.com"></script>
                <style>
                    body { margin: 0; background: #0f172a; color: white; font-family: sans-serif; }
                    #root { min-height: 100vh; }
                </style>
            </head>
            <body>
                <div id="root"></div>
                <script type="text/babel">
                    try {
                        const { useState, useEffect, useMemo, useCallback } = React;
                        Object.assign(window, { useState, useEffect, useMemo, useCallback });
                        const rawCode = ${JSON.stringify(code)};
                        const cleanedCode = rawCode.replace(/import\\s+.*?from\\s+['"].*?['"];?/g, '');
                        const { code: transformed } = Babel.transform(cleanedCode, { presets: ['react'] });
                        const script = document.createElement('script');
                        script.text = transformed;
                        document.body.appendChild(script);
                        setTimeout(() => {
                            const component = window.App || (typeof App !== "undefined" ? App : null);
                            if (component) ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(component));
                        }, 100);
                    } catch (e) { console.error(e); }
                </script>
            </body>
            </html>
        `;

        return (
            <div className="ui-preview-section anim-fade-in">
                <div className="preview-header-row">
                    <div className="preview-header"><Sparkles size={18} className="text-blue-400" /><span>Live Design Preview</span></div>
                    <div className="preview-badge">v{session?.version || 1} Stable</div>
                </div>
                <div className="preview-frame-container">
                    <iframe srcDoc={htmlContent} title="UI Preview" className="ui-preview-iframe" />
                </div>
                
                <div className="ui-refinement-panel glass-panel">
                    <div className="refinement-header"><Sparkles size={16} /><span>Design Iteration & Approval</span></div>
                    <textarea 
                        className="refinement-input" 
                        placeholder="Refine design (e.g. 'Make it more compact', 'Change theme to neon')..." 
                        value={uiFeedback} 
                        onChange={(e) => setUiFeedback(e.target.value)} 
                    />
                    <div className="refinement-actions">
                        {/* ITERATE ACTION */}
                        <button className="btn-refine" disabled={isRefining || !uiFeedback.trim()} onClick={handleRefineUI}>
                            {isRefining ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}
                            {isRefining ? 'Refining...' : 'Refine Design'}
                        </button>

                        {/* FINAL APPROVE ACTION (Moved beside Refine) */}
                        <button className="btn-approve-inline" onClick={() => onComplete && onComplete()}>
                            <div className="btn-shine"></div>
                            <CheckCircle2 size={16} />
                            <span>Approve & Sync</span>
                        </button>
                    </div>
                </div>

                <div className="preview-footer-note">
                    <ShieldCheck size={14} /><span>Architectural sync pending final approval.</span>
                </div>
            </div>
        );
    };

    if (loading) return <div className="ui-design-loading"><Clock className="spin-slow" size={24} /><span>Synchronizing...</span></div>;

    return (
        <div className="ui-design-container anim-fade-in">
            <div className="ui-design-header">
                <div className="header-main-info">
                    <div className="header-icon-box"><Layout size={24} /></div>
                    <div className="header-text">
                        <h2>UI Design Agent</h2>
                        <p>Synthesis for <strong>{workflowName || 'Current Workflow'}</strong></p>
                    </div>
                </div>
            </div>

            <div className="ui-design-context-row">
                <div className="doc-context-card workflow-card">
                    <div className="doc-context-card-header">
                        <div className="doc-context-icon workflow"><Workflow size={20} /></div>
                        <div className="doc-context-body">
                            <span className="doc-context-label">Ingested Workflow</span>
                            <span className="doc-context-value">{session?.session_title || `Workflow Session`}</span>
                        </div>
                    </div>
                    <div className={`doc-context-status ${isWorkflowApproved ? 'active' : 'inactive'}`}>
                        {isWorkflowApproved ? <><CheckCircle2 size={13} /> Approved</> : <><Clock size={13} /> Pending</>}
                    </div>
                </div>
                <div className="doc-context-card requirements-card">
                    <div className="doc-context-card-header">
                        <div className="doc-context-icon architecture"><Layers size={20} /></div>
                        <div className="doc-context-body">
                            <span className="doc-context-label">Design Blueprint</span>
                            <span className="doc-context-value">{hasHld && hasLld ? 'Full Package Sync' : 'Awaiting Artifacts'}</span>
                        </div>
                    </div>
                    <div className={`doc-context-status ${hasHld && hasLld ? 'active' : 'inactive'}`}>
                        {hasHld && hasLld ? <><CheckCircle2 size={13} /> Ready</> : <><Clock size={13} /> Incomplete</>}
                    </div>
                </div>
            </div>

            {error && <div className="ui-design-error anim-shake"><AlertTriangle size={16} /><span>{error}</span></div>}

            {synthesisResult ? renderPreview() : (
                <div className="ui-synthesis-placeholder glass-panel">
                    <Sparkles size={40} className={`sparkle-icon ${isSynthesizing ? 'spin-glow' : ''}`} />
                    <h3>UI Synthesis Engine</h3>
                    <p>Transforming blueprints into React components.</p>
                    <button className="btn-primary-glow" disabled={!isWorkflowApproved || !hasHld || !hasLld || isSynthesizing} onClick={handleInitializeSynthesis}>
                        {isSynthesizing ? <><Loader2 size={18} className="spin" /> Synthesizing...</> : <><Sparkles size={18} /> Initialize Synthesis</>}
                    </button>
                </div>
            )}
        </div>
    );
};

export default UIDesignAgent;
