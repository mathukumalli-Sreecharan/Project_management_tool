import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ClipboardList, FolderGit2, Sparkles, FileText, CheckCircle2, Copy, History, Clock, Loader2 } from "lucide-react";
import { getWorkflowSessions, getWorkflowSession } from "./api";
import "./ProjectGeneration.css";

export default function ProjectGeneration({
  lead,
  requirementsData,
  requirementsHandoff = null,
  projectTranscript = "",
  requirementHistory = [],
  isGenerating = false,
  isLoadingRequirements = false,
  error = "",
  onBack,
  onOpenAnalysis,
  onGenerateFromContext,
  hideHeader = false,
  initialWorkflowFilter = "all",
  selectedWorkflowSessionVersion = null
}) {
  const [copyState, setCopyState] = useState("idle");
  const [showHistoryPanel, setShowHistoryPanel] = useState(false);
  const [selectedHistoryId, setSelectedHistoryId] = useState(null);
  const [workflowFilter, setWorkflowFilter] = useState(initialWorkflowFilter);
  const [workflowContext, setWorkflowContext] = useState(null);
  const [workflowContextStatus, setWorkflowContextStatus] = useState("");
  const [isLoadingWorkflowContext, setIsLoadingWorkflowContext] = useState(false);
  const [showChangesPanel, setShowChangesPanel] = useState(false);
  const [changeText, setChangeText] = useState("");

  const renderSection = (label, items, emptyText = "Not provided") => {
    const list = Array.isArray(items) ? items.filter(Boolean) : [];
    return (
      <div className="requirement-section">
        <div className="section-label">{label}</div>
        {list.length > 0 ? (
          Array.isArray(items) ? (
            <ul>
              {list.map((item, idx) => (
                <li key={`${label}-${idx}`}>{item}</li>
              ))}
            </ul>
          ) : (
            <p>{list}</p>
          )
        ) : (
          <p className="section-empty">{emptyText}</p>
        )}
      </div>
    );
  };

  const asList = (value) => {
    if (Array.isArray(value)) {
      return value.map((item) => String(item).trim()).filter(Boolean);
    }
    if (typeof value === "string" && value.trim()) {
      return [value.trim()];
    }
    return [];
  };

  const deriveContextValue = (requirement, kind) => {
    const explicitKeys = kind === "input"
      ? ["inputs", "input", "source_inputs", "source_input", "inbound_data"]
      : ["outputs", "output", "deliverables", "result", "expected_output"];

    for (const key of explicitKeys) {
      const matches = asList(requirement?.[key]);
      if (matches.length > 0) return matches;
    }
    return [];
  };

  const renderDetailBlock = (label, value, emptyText = "Not provided") => {
    const list = asList(value);
    return (
      <div className="td-req-section">
        <div className="td-req-section-label">{label}</div>
        {list.length > 0 ? (
          <div className="td-req-section-value">
            {list.length > 1 ? (
              <ul className="criteria-list">
                {list.map((item, idx) => <li key={`${label}-${idx}`}>{item}</li>)}
              </ul>
            ) : (
              <span>{list[0]}</span>
            )}
          </div>
        ) : (
          <div className="td-req-section-value">{emptyText}</div>
        )}
      </div>
    );
  };

  useEffect(() => {
    if (initialWorkflowFilter !== "all") {
      setWorkflowFilter(initialWorkflowFilter);
    }
  }, [initialWorkflowFilter]);

  const selectedHistoryEvent = useMemo(
    () => requirementHistory.find((event) => event.id === selectedHistoryId) || null,
    [requirementHistory, selectedHistoryId]
  );

  const activeRequirementsData = selectedHistoryEvent?.requirements || requirementsData;

  const displayedWorkflows = useMemo(() => {
    const sourceWorkflows = Array.isArray(activeRequirementsData?.workflows)
      ? activeRequirementsData.workflows
      : Array.isArray(activeRequirementsData?.projects)
        ? activeRequirementsData.projects.map((project) => ({
            workflow_id: project?.workflow_id || project?.project_id,
            workflow_name: project?.workflow_name || project?.project_name,
            workflow_summary: project?.workflow_summary || project?.project_summary,
            actors: project?.actors || [],
            epics: project?.epics,
            requirements: project?.requirements,
            system_constraints: project?.system_constraints || []
          }))
        : Array.isArray(activeRequirementsData?.requirements)
          ? [
              {
                workflow_id: activeRequirementsData?.workflow_id || activeRequirementsData?.project_id || lead?.id || "WF-1",
                workflow_name: activeRequirementsData?.workflow_name || activeRequirementsData?.project_name || lead?.project_name || lead?.company || "Generated Workflow",
                workflow_summary: activeRequirementsData?.workflow_summary || activeRequirementsData?.project_summary || "",
                actors: activeRequirementsData?.actors || [],
                requirements: activeRequirementsData.requirements,
                system_constraints: activeRequirementsData?.system_constraints || []
              }
            ]
          : Array.isArray(activeRequirementsData)
            ? [
                {
                  workflow_id: lead?.id || "WF-1",
                  workflow_name: lead?.project_name || lead?.company || "Generated Workflow",
                  workflow_summary: "",
                  actors: [],
                  requirements: activeRequirementsData,
                  system_constraints: []
                }
              ]
            : [];

    if (sourceWorkflows.length <= 1) return sourceWorkflows;

    const combined = {
      ...sourceWorkflows[0],
      _uiKey: "combined-workflow-0",
      _displayWorkflowId: "WF-1",
      workflow_id: "WF-1",
      workflow_name: sourceWorkflows[0]?.workflow_name || "Combined Workflow",
      workflow_summary: sourceWorkflows[0]?.workflow_summary || "Combined workflow synthesized from stored workflow sessions.",
      actors: [],
      epics: [],
      system_constraints: []
    };

    const seenActors = new Set();
    const seenConstraints = new Set();
    let epicCounter = 1;
    let reqCounter = 1;

    sourceWorkflows.forEach((workflow) => {
      (workflow?.actors || []).forEach((actor) => {
        const key = `${actor?.name || ""}::${actor?.type || ""}`;
        if (key !== "::" && !seenActors.has(key)) {
          seenActors.add(key);
          combined.actors.push(actor);
        }
      });
      (workflow?.system_constraints || []).forEach((constraint) => {
        if (constraint && !seenConstraints.has(constraint)) {
          seenConstraints.add(constraint);
          combined.system_constraints.push(constraint);
        }
      });
      const workflowEpics = Array.isArray(workflow?.epics) && workflow.epics.length > 0
        ? workflow.epics
        : (Array.isArray(workflow?.requirements)
          ? [
              {
                epic_id: `${workflow?.workflow_id || "WF-1"}-EPIC-1`,
                title: workflow?.workflow_name || workflow?.workflow_summary || "Workflow Epic",
                user_story: workflow?.workflow_summary || "",
                requirements: workflow.requirements
              }
            ]
          : []);

      workflowEpics.forEach((epic) => {
        const combinedEpic = {
          ...epic,
          epic_id: `EPIC-${epicCounter++}`,
          requirements: []
        };
        (epic?.requirements || []).forEach((req) => {
          combinedEpic.requirements.push({
            ...req,
            req_id: `REQ-${reqCounter++}`,
            description: req?.requirement_description || req?.description || req?.story_text || req?.title || "",
            requirement_description: req?.requirement_description || req?.description || req?.story_text || req?.title || "",
            inputs: asList(req?.inputs),
            outputs: asList(req?.outputs),
          });
        });
        combined.epics.push(combinedEpic);
      });
    });

    return [combined];
  }, [activeRequirementsData, lead?.company, lead?.id, lead?.project_name]);

  const baseRequirementCount = useMemo(() => {
    if (Array.isArray(activeRequirementsData?.workflows)) {
      return displayedWorkflows.reduce(
        (total, workflow) =>
          total +
          (workflow?.epics || []).reduce(
            (epicTotal, epic) => epicTotal + (epic?.requirements?.length || 0),
            0
          ),
        0
      );
    }
    if (Array.isArray(activeRequirementsData?.projects)) {
      return activeRequirementsData.projects.reduce(
        (total, project) =>
          total +
          (project?.epics || []).reduce(
            (epicTotal, epic) => epicTotal + (epic?.requirements?.length || 0),
            0
          ),
        0
      );
    }
    if (Array.isArray(activeRequirementsData?.requirements)) {
      return activeRequirementsData.requirements.length;
    }
    if (Array.isArray(activeRequirementsData)) {
      return activeRequirementsData.length;
    }
    return 0;
  }, [activeRequirementsData, displayedWorkflows]);

  const approvedWorkflowVersion = workflowContext?.version ?? null;
  const generatedWorkflowVersion = requirementsHandoff?.requirements_state?.workflow_session_version ?? null;
  const workflowSourceVersion = selectedWorkflowSessionVersion ?? generatedWorkflowVersion ?? approvedWorkflowVersion ?? null;
  const currentProjectTranscript = (projectTranscript || "").trim();
  const generatedProjectTranscript = (requirementsHandoff?.requirements_state?.transcript_context || "").trim();
  const generatedWorkflowVersionKey = generatedWorkflowVersion == null ? "" : String(generatedWorkflowVersion);
  const workflowSourceVersionKey = workflowSourceVersion == null ? "" : String(workflowSourceVersion);
  const transcriptChanged = Boolean(
    currentProjectTranscript &&
    (!generatedProjectTranscript || currentProjectTranscript !== generatedProjectTranscript)
  );
  const isRequirementsStale = Boolean(
    workflowSourceVersionKey &&
    baseRequirementCount > 0 &&
    (!generatedWorkflowVersionKey || generatedWorkflowVersionKey !== workflowSourceVersionKey)
  ) || transcriptChanged;
  const displayedRequirements = activeRequirementsData;
  const displayedTranscript = selectedHistoryEvent?.transcript || "";
  const isDraftingRequirements = Boolean(isGenerating);

  useEffect(() => {
    if (!selectedHistoryId) return;

    const stillExists = requirementHistory.some((event) => event.id === selectedHistoryId);
    if (!stillExists) {
      setSelectedHistoryId(null);
    }
  }, [requirementHistory, requirementsData, selectedHistoryId]);

  useEffect(() => {
    setSelectedHistoryId(null);
  }, [requirementsHandoff?.updated_at, requirementsHandoff?.stored_at]);

  useEffect(() => {
    setSelectedHistoryId(null);
  }, [workflowContext?.version, lead?.id]);

  const visibleWorkflows = useMemo(() => {
    if (!displayedWorkflows.length) return [];
    if (workflowFilter === "all") return displayedWorkflows;
    const filtered = displayedWorkflows.filter(
      (workflow) =>
        workflow.workflow_id === workflowFilter ||
        workflow._displayWorkflowId === workflowFilter
    );
    return filtered.length > 0 ? filtered : displayedWorkflows;
  }, [displayedWorkflows, workflowFilter]);

  const requirementCount = useMemo(
    () =>
      displayedWorkflows.reduce(
        (total, workflow) =>
          total +
          (workflow?.epics || []).reduce(
            (epicTotal, epic) => epicTotal + (epic?.requirements?.length || 0),
            0
          ),
        0
      ),
    [displayedWorkflows]
  );

  const epicCount = useMemo(
    () => displayedWorkflows.reduce((total, workflow) => total + (workflow?.epics?.length || 0), 0),
    [displayedWorkflows]
  );

  const hasGeneratedRequirements = requirementCount > 0;

  const loadWorkflowContext = async () => {
    const projectId = lead?.id;
    if (!projectId || isLoadingWorkflowContext) return;

    setIsLoadingWorkflowContext(true);
    setWorkflowContextStatus("");
    try {
      const sessionsRes = await getWorkflowSessions(projectId);
      const sessions = sessionsRes?.sessions || [];
      if (!sessions.length) {
        setWorkflowContextStatus("No saved workflow sessions found for this project.");
        setWorkflowContext(null);
        return;
      }

      let approvedSession = null;
      const requestedVersion = selectedWorkflowSessionVersion != null
        ? String(selectedWorkflowSessionVersion)
        : "";

      if (requestedVersion) {
        approvedSession = sessions.find((session) => session.version.toString() === requestedVersion);
      }

      // Fallback to latest approved if no specific filter match
      if (!approvedSession) {
        approvedSession = sessions.find((session) => session.client_approved);
      }

      if (!approvedSession) {
        setWorkflowContextStatus("No approved workflow session found. Approve & lock a workflow first.");
        setWorkflowContext(null);
        return;
      }



      const sessionRes = await getWorkflowSession(projectId, approvedSession.version);
      const toBeFlow = sessionRes?.session?.to_be || "";
      if (!toBeFlow || !toBeFlow.trim()) {
        setWorkflowContextStatus(`Approved session v${approvedSession.version} has no TO-BE flow.`);
        setWorkflowContext(null);
        return;
      }

      setWorkflowContext({
        version: approvedSession.version,
        sessionTitle: approvedSession.session_title || `Session ${approvedSession.version}`,
        to_be: toBeFlow.trim(),
      });
      setWorkflowContextStatus(
        requestedVersion
          ? `Using workflow session v${approvedSession.version} as the requirement source.`
          : `Using approved workflow session v${approvedSession.version} as the requirement source.`
      );
    } catch (err) {
      setWorkflowContextStatus("Unable to load workflow context. Please try again.");
      setWorkflowContext(null);
    } finally {
      setIsLoadingWorkflowContext(false);
    }
  };

  useEffect(() => {
    setWorkflowContext(null);
    setWorkflowContextStatus("");
    if (lead?.id) {
      loadWorkflowContext();
    }
  }, [lead?.id, requirementsHandoff?.workflow_session?.version, initialWorkflowFilter, selectedWorkflowSessionVersion]);

  useEffect(() => {
    if (isRequirementsStale) {
      setSelectedHistoryId(null);
    }
  }, [approvedWorkflowVersion, generatedWorkflowVersion, currentProjectTranscript, isRequirementsStale]);

  const handleGenerate = () => {
    if (!onGenerateFromContext || !lead?.id) return;
    onGenerateFromContext({ confirmProjectStart: true });
  };

  const handleRegenerateWithChanges = () => {
    if (!onGenerateFromContext || !lead?.id || !changeText.trim()) return;
    onGenerateFromContext({
      confirmProjectStart: true,
      changeRequest: changeText.trim()
    });
  };

  const handleCopyAllRequirements = async () => {
    if (!displayedRequirements || !navigator?.clipboard) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(displayedRequirements, null, 2));
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 2000);
    } catch (error) {
      setCopyState("error");
      window.setTimeout(() => setCopyState("idle"), 2000);
    }
  };

  const shellClass = hideHeader ? "project-shell-internal" : "project-shell";

  return (
    <div className={shellClass} style={hideHeader ? { padding: 0, minHeight: 'auto' } : {}}>
      {!hideHeader && (
        <div className="project-header">
          <button className="project-back-btn" onClick={onBack}>
            <ArrowLeft size={16} /> Lead Forge
          </button>
          <div className="project-header-copy">
            <div className="project-badge"><FolderGit2 size={14} /> Project Generation</div>
            <h1>{lead?.project_name || lead?.company || "Project Generation"}</h1>
            <p>Requirements are generated from the approved Workflow Identification output and displayed here as read-only project output.</p>
          </div>
          <button className="project-open-analysis" onClick={onOpenAnalysis}>
            Open Analysis Pipeline
          </button>
        </div>
      )}

      <div className="project-grid">
        <section className="project-panel project-transcript-panel">
          <div className="project-panel-title">
            <ClipboardList size={18} />
            <div>
              <h2>Requirement Source</h2>
              <span>Requirement input is locked to Workflow Identification. This page only shows generated output.</span>
            </div>
          </div>

          <div className="project-actions" style={{ marginTop: "12px" }}>
            <button
              type="button"
              className="project-secondary-btn"
              onClick={loadWorkflowContext}
              disabled={isLoadingWorkflowContext || !lead?.id}
            >
              <FolderGit2 size={16} />
              {isLoadingWorkflowContext ? "Loading Workflow Context..." : "Refresh Workflow Context"}
            </button>
            {!hasGeneratedRequirements && (
              <button
                type="button"
                className="project-generate-btn"
                onClick={handleGenerate}
                disabled={!workflowContext || isGenerating}
              >
                {isGenerating ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}
                Generate Requirements
              </button>
            )}
          </div>

          <div className="project-input-hint">
            The transcript and workflow architecture come from the approved Workflow Identification step. If they need to change, go back there first.
          </div>

          <div className="project-upload-box" style={{ cursor: "default" }}>
            <div className="project-upload-copy">
              {workflowContext
                ? `Approved workflow source: ${workflowContext.sessionTitle} (v${workflowContext.version})`
                : "No approved workflow has been attached yet."}
            </div>
            <div className="project-upload-file">
              <FileText size={16} />
              {isDraftingRequirements
                ? "Drafting requirements from the selected workflow session..."
                : (workflowContextStatus || (isRequirementsStale ? "Workflow changed. Regenerating requirements..." : "Waiting for workflow context..."))}
            </div>
            {isDraftingRequirements && (
              <div className="project-draft-preview">
                <div className="project-draft-topline">
                  <Loader2 size={16} className="spin" />
                  <span>Drafting requirement scope</span>
                </div>
                <div className="project-draft-steps">
                  <span className="draft-pill active">Reading transcript</span>
                  <span className="draft-pill active">Mapping inputs</span>
                  <span className="draft-pill active">Writing stories</span>
                  <span className="draft-pill">Checking coverage</span>
                </div>
                <div className="project-draft-progress">
                  <div className="project-draft-progress-bar"></div>
                </div>
                <p className="project-draft-note">
                  The system is still working, even if the page looks still. We’re turning the workflow into user stories, descriptions, and acceptance signals now.
                </p>
              </div>
            )}
          </div>

          {error && <div className="project-alert error">{error}</div>}
          {!error && requirementCount > 0 && (
            <div className="project-alert success">
              <CheckCircle2 size={16} /> Requirement output is ready.
            </div>
          )}
        </section>

        <section className="project-panel project-requirements-panel">
          <div className="project-panel-header">
            <div className="project-panel-title">
              <Sparkles size={18} />
              <div>
                <h2>Generated Requirements</h2>
                <span>
                  {requirementCount > 0
                    ? `${requirementCount} requirement blocks ready across ${displayedWorkflows.length} workflow${displayedWorkflows.length === 1 ? "" : "s"}`
                    : isRequirementsStale
                      ? "Requirements were generated, but they are tied to a previous workflow version."
                      : "No requirements generated yet"}
                </span>
              </div>
            </div>
            <div className="project-panel-actions">
              <button
                type="button"
                className={`project-secondary-btn ${showChangesPanel ? "active" : ""}`}
                onClick={() => setShowChangesPanel((value) => !value)}
                disabled={!hasGeneratedRequirements}
              >
                <Sparkles size={15} />
                Changes
              </button>
              <button
                type="button"
                className={`project-secondary-btn ${showHistoryPanel ? "active" : ""}`}
                onClick={() => setShowHistoryPanel((value) => !value)}
                disabled={requirementHistory.length === 0}
              >
                <History size={15} />
                History
              </button>
              <button
                type="button"
                className="project-secondary-btn"
                onClick={handleCopyAllRequirements}
                disabled={!hasGeneratedRequirements}
              >
                <Copy size={15} />
                {copyState === "copied" ? "Copied" : copyState === "error" ? "Copy Failed" : "Copy All"}
              </button>
            </div>
          </div>

          {showHistoryPanel && (
            <section className="requirements-history-panel">
              <div className="project-panel-title compact">
                <History size={18} />
                <div>
                  <h2>Requirements History</h2>
                  <span>Click any saved version to open it in the requirements view.</span>
                </div>
              </div>

              <div className="requirements-history-list">
                <button
                  type="button"
                  className={`history-item ${selectedHistoryId === null ? "active" : ""}`}
                  onClick={() => setSelectedHistoryId(null)}
                >
                  <div className="history-item-top">
                    <span className="history-item-title">Latest Working Version</span>
                  </div>
                  <div className="history-item-meta">
                    <Clock size={12} />
                    {displayedTranscript ? "Current in-memory requirements" : "Use the latest saved output"}
                  </div>
                </button>

                {requirementHistory.map((event, index) => (
                  <button
                    type="button"
                    key={event.id || `${event.event_type}-${index}`}
                    className={`history-item ${selectedHistoryId === event.id ? "active" : ""}`}
                    onClick={() => setSelectedHistoryId(event.id)}
                  >
                    <div className="history-item-top">
                      <span className="history-item-title">
                        {(event.event_type || "history").replaceAll("_", " ")}
                      </span>
                      <span className="history-item-badge">Version {requirementHistory.length - index}</span>
                    </div>
                    <div className="history-item-meta">
                      <Clock size={12} />
                      {event.at ? new Date(event.at).toLocaleString() : "Saved version"}
                    </div>
                  </button>
                ))}
              </div>
            </section>
          )}

          {showChangesPanel && hasGeneratedRequirements && (
            <section className="changes-panel">
              <div className="project-panel-title compact">
                <Sparkles size={18} />
                <div>
                  <h2>Changes Prompt</h2>
                  <span>Describe what should change, then regenerate requirements from the stored workflow context.</span>
                </div>
              </div>

              <textarea
                className="project-change-input"
                placeholder="Example: keep the same workflow, but add audit logging, role-based approvals, and stronger edge-case handling for partial submissions."
                value={changeText}
                onChange={(event) => setChangeText(event.target.value)}
              />

              <div className="project-actions">
                <button
                  type="button"
                  className="project-generate-btn"
                  onClick={handleRegenerateWithChanges}
                  disabled={isGenerating || !changeText.trim()}
                >
                  {isGenerating ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}
                  Re-generate
                </button>
              </div>
            </section>
          )}

          {requirementCount > 0 && (
            <div className="requirements-toolbar">
              <div className="requirements-overview">
                <div className="requirements-stat">
                  <strong>{displayedWorkflows.length}</strong>
                  <span>Workflows</span>
                </div>
                <div className="requirements-stat">
                  <strong>{epicCount}</strong>
                  <span>Epics</span>
                </div>
                <div className="requirements-stat">
                  <strong>{requirementCount}</strong>
                  <span>Requirements</span>
                </div>
              </div>

              {displayedWorkflows.length > 1 && (
                <div className="workflow-filter-wrapper">
                  <select
                    className="workflow-filter-select"
                    value={workflowFilter}
                    onChange={(e) => setWorkflowFilter(e.target.value)}
                  >
                    <option value="all">All Workflows</option>
                    {displayedWorkflows.map(wf => (
                      <option key={wf._uiKey} value={wf.workflow_id}>{wf.workflow_name}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          )}

          {isLoadingRequirements && (
            <div className="requirements-skeleton-loader">
              <div className="skeleton-toolbar">
                <div className="skeleton-item long shimmer"></div>
                <div className="skeleton-item short shimmer"></div>
              </div>
              {[1, 2, 3].map(i => (
                <div key={i} className="skeleton-workflow-card">
                  <div className="skeleton-header">
                    <div className="skeleton-id shimmer"></div>
                    <div className="skeleton-title shimmer"></div>
                  </div>
                  <div className="skeleton-body">
                    <div className="skeleton-line shimmer"></div>
                    <div className="skeleton-line shimmer"></div>
                    <div className="skeleton-line short shimmer"></div>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className={`requirements-list ${isLoadingRequirements ? 'loading-blur' : ''}`}>
            {displayedWorkflows.length === 0 ? (
              <div className="requirements-empty">
                {workflowContext
                  ? (isRequirementsStale
                    ? "A newer workflow was approved. Regenerating requirements from the latest transcript..."
                    : "Requirements are being generated from the approved workflow context, or no output has been saved yet.")
                  : "Approve a workflow in Workflow Identification first. Requirement output will appear here automatically."}
              </div>
            ) : (
              <>
                {visibleWorkflows
                  .map((workflow, workflowIdx) => (
                    <section key={workflow._uiKey || `workflow-${workflowIdx}`} className="workflow-card anim-slide-up">
                      <header className="workflow-header">
                        <div>
                          <div className="requirement-id">{workflow._displayWorkflowId || workflow.workflow_id || `WF-${workflowIdx + 1}`}</div>
                          <h3>{workflow.workflow_name || `Workflow ${workflowIdx + 1}`}</h3>
                        </div>
                        <div className="workflow-meta">
                          <span>{workflow.epics?.length || 0} epics</span>
                          <span>
                            {(workflow.epics || []).reduce((total, epic) => total + (epic?.requirements?.length || 0), 0)} requirements
                          </span>
                        </div>
                      </header>
                      {(workflow.epics || []).map((epic, epicIdx) => (
                        <section key={`${workflow._uiKey || workflowIdx}-${epic.epic_id || epicIdx}-${epicIdx}`} className="epic-card">
                          <div className="epic-header">
                            <div className="requirement-id">{epic.epic_id || `EPIC-${epicIdx + 1}`}</div>
                            <h4>{epic.title || `Epic ${epicIdx + 1}`}</h4>
                          </div>
                          {(epic.requirements || []).map((item, idx) => (
                            <article key={`${workflow._uiKey || workflowIdx}-${epic.epic_id || epicIdx}-${item.req_id || idx}-${idx}`} className="requirement-card">
                              <div className="requirement-topline">
                                <div className="requirement-id">{item.req_id || `REQ-${idx + 1}`}</div>
                              </div>
                              <h5>{item.requirement_title || item.short_title || item.title || item.story_text || `Requirement ${idx + 1}`}</h5>
                              <p className="requirement-copy">
                                {item.requirement_description || item.description || item.story_text || "No requirement description was provided for this item."}
                              </p>
                              <p className="requirement-story">
                                {item.user_story || "No user story was provided for this item."}
                              </p>

                              <div className="td-req-sections">
                                {renderDetailBlock("Inputs", item.inputs || deriveContextValue(item, "input"), "No input evidence captured from the transcript yet.")}
                                {renderDetailBlock("Outputs", item.outputs || deriveContextValue(item, "output"), "No output evidence captured from the transcript yet.")}
                              </div>

                              <div className="requirement-grid">
                                {renderSection("Acceptance Criteria", item.acceptance_criteria, "No acceptance criteria provided.")}
                              </div>
                            </article>
                          ))}
                        </section>
                      ))}
                    </section>
                  ))}
              </>
            )}
          </div>
          {isLoadingRequirements && (
            <div className="fetching-indicator">
              <div className="pulse-fetching"></div>
              <span>Fetching from database...</span>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

