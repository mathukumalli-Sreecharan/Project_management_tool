import React, { useState, useEffect } from 'react';
import { ShieldCheck, Loader2, CheckCircle2, ChevronDown, ChevronRight, FileText, Activity, RefreshCcw, XCircle, AlertTriangle } from 'lucide-react';
import { getTestCases, failTestCase } from './api';
import './QAAgent.css';

function QAAgent({ activeProject, workflowId, workflowName }) {
  const [testCases, setTestCases] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [expandedCaseId, setExpandedCaseId] = useState(null);
  const [error, setError] = useState(null);
  const [failingTestCase, setFailingTestCase] = useState(null);
  const [bugReportText, setBugReportText] = useState("");
  const [isSubmittingBug, setIsSubmittingBug] = useState(false);

  const projectId = activeProject?.id || activeProject?.project_id;

  // Load existing test cases on mount
  useEffect(() => {
    if (!projectId || !workflowId) return;
    loadTests();
  }, [projectId, workflowId]);

  const loadTests = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await getTestCases(projectId, workflowId);
      if (res?.test_cases) {
        // Group by task and deduplicate test cases by ID AND Title
        const seenCaseIds = new Set();
        const seenTitlesByTask = {}; // { taskId: Set of titles }

        const grouped = res.test_cases.reduce((acc, tc) => {
          if (seenCaseIds.has(tc.id)) return acc;
          seenCaseIds.add(tc.id);

          const tId = tc.task_id || tc.requirement_id || 'unassigned';
          
          // Secondary check: Title within the same task
          if (!seenTitlesByTask[tId]) seenTitlesByTask[tId] = new Set();
          if (seenTitlesByTask[tId].has(tc.title)) return acc;
          seenTitlesByTask[tId].add(tc.title);

          if (!acc[tId]) {
            acc[tId] = {
              taskId: tc.task_id || 'Unknown',
              taskTitle: tc.task_title || 'Unassigned Task',
              cases: []
            };
          }
          acc[tId].cases.push(tc);
          return acc;
        }, {});
        
        setTestCases(Object.values(grouped));
      }
    } catch (err) {
      console.error("Failed to load test cases:", err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleFailSubmit = async () => {
    if (!bugReportText.trim() || !failingTestCase) return;
    setIsSubmittingBug(true);
    try {
      await failTestCase(failingTestCase.task_id, {
        test_case_id: failingTestCase.id,
        test_case_title: failingTestCase.title,
        bug_report: bugReportText,
        project_id: projectId,
        workflow_id: workflowId
      });
      setFailingTestCase(null);
      setBugReportText("");
      loadTests();
    } catch (err) {
      console.error(err);
      setError("Failed to submit bug report: " + err.message);
    } finally {
      setIsSubmittingBug(false);
    }
  };

  const toggleExpand = (id) => {
    setExpandedCaseId(expandedCaseId === id ? null : id);
  };

  const typeColorMap = {
    'Unit': '#60a5fa',
    'Integration': '#a78bfa',
    'E2E': '#fbbf24',
    'Database': '#f43f5e',
    'Security': '#10b981'
  };

  return (
    <div className="agent-panel-content anim-fade-in">
      <div className="agent-panel-header">
        <div className="agent-panel-icon doc-icon"> <ShieldCheck size={24} /> </div>
        <div style={{ flex: 1 }}>
          <h2>QA Agent</h2>
          <p>Workflow: <strong>{workflowName || 'Processing...'}</strong></p>
        </div>
        <button
          className="agent-action-btn"
          onClick={loadTests}
          disabled={isLoading}
          style={{ padding: '8px 16px', display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(255,255,255,0.1)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer' }}
        >
          <RefreshCcw size={16} className={isLoading ? "spin" : ""} />
          Refresh Status
        </button>
      </div>

      {error && (
        <div className="agent-error-banner" style={{ marginTop: 20 }}>
          <Activity size={18} />
          <span>{error}</span>
        </div>
      )}

      {isLoading ? (
        <div className="task-empty-state" style={{ marginTop: 40 }}>
          <Loader2 size={48} className="spin" style={{ opacity: 0.5, marginBottom: 20 }} />
          <h3>Loading Test Suites</h3>
        </div>
      ) : testCases.length === 0 ? (
        <div className="task-empty-state" style={{ marginTop: 40 }}>
          <ShieldCheck size={48} style={{ opacity: 0.5, marginBottom: 20 }} />
          <h3>No Test Cases Generated Yet</h3>
          <p>Move tasks to the "Review" column on the Kanban board and click Refresh Status to pull Context-Aware Test Suites.</p>
        </div>
      ) : (
        <div className="qa-test-list">
          {testCases.map((group) => (
            <div key={group.taskId} style={{ marginBottom: '32px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px', paddingBottom: '8px', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                <h3 style={{ margin: 0, color: '#f8fafc', fontSize: '16px', fontWeight: 600 }}>{group.taskId}: {group.taskTitle}</h3>
                <span style={{ fontSize: '11px', background: 'rgba(96, 165, 250, 0.1)', color: '#60a5fa', padding: '4px 8px', borderRadius: '2px', fontWeight: 700, letterSpacing: '0.5px', textTransform: 'uppercase' }}>
                  {group.cases.length} Tests
                </span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {group.cases.map((tc) => (
                  <div key={tc.id} className="qa-test-card glass-panel">
                    <div
                      className="qa-test-header"
                      onClick={() => toggleExpand(tc.id)}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        {expandedCaseId === tc.id ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                        <h4>{tc.title}</h4>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        <span
                          className="qa-type-badge"
                          style={{
                            backgroundColor: `${typeColorMap[tc.type] || '#60a5fa'}20`,
                            color: typeColorMap[tc.type] || '#60a5fa'
                          }}>
                          {tc.type}
                        </span>
                      </div>
                    </div>

                    {expandedCaseId === tc.id && (
                      <div className="qa-test-details anim-fade-in">
                        <p className="qa-test-desc">{tc.description}</p>

                        <div className="qa-test-grid">
                          <div>
                            <div className="qa-box-title">
                              <FileText size={14} /> Steps to Execute
                            </div>
                            <div className="qa-box-content">
                              {tc.test_steps}
                            </div>
                          </div>
                          <div>
                            <div className="qa-box-title">
                              <CheckCircle2 size={14} color="#34d399" /> Expected Result
                            </div>
                            <div className="qa-box-content success">
                              {tc.expected_result}
                            </div>
                          </div>
                        </div>
                        <div style={{ marginTop: '16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
                          {failingTestCase?.id !== tc.id ? (
                            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setFailingTestCase({ ...tc, task_id: group.taskId });
                                  setBugReportText("");
                                }}
                                style={{ background: 'rgba(239, 68, 68, 0.1)', color: '#f87171', border: '1px solid rgba(239, 68, 68, 0.2)', padding: '6px 12px', borderRadius: 4, display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}
                              >
                                <XCircle size={14} /> Report Bug
                              </button>
                            </div>
                          ) : (
                            <div className="bug-report-inline anim-fade-in" style={{ background: 'rgba(239, 68, 68, 0.05)', padding: 16, borderRadius: 4, border: '1px solid rgba(239, 68, 68, 0.2)' }}>
                              <h4 style={{ margin: '0 0 12px 0', color: '#f87171', fontSize: '14px', display: 'flex', alignItems: 'center', gap: 8 }}>
                                <AlertTriangle size={14} /> Provide Bug Details
                              </h4>
                              <textarea
                                value={bugReportText}
                                autoFocus
                                onChange={(e) => setBugReportText(e.target.value)}
                                placeholder="What went wrong? Describe the issue here..."
                                style={{ width: '100%', height: '100px', background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 4, padding: 10, color: '#fff', fontSize: '13px', marginBottom: 12, resize: 'vertical' }}
                              />
                              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                                <button
                                  onClick={() => setFailingTestCase(null)}
                                  style={{ background: 'transparent', border: '1px solid rgba(255,255,255,0.1)', color: '#94a3b8', padding: '6px 12px', borderRadius: 4, cursor: 'pointer', fontSize: '12px' }}
                                >
                                  Cancel
                                </button>
                                <button
                                  onClick={handleFailSubmit}
                                  disabled={isSubmittingBug || !bugReportText.trim()}
                                  style={{ background: '#ef4444', border: 'none', color: '#fff', padding: '6px 16px', borderRadius: 4, cursor: 'pointer', fontSize: '12px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6, opacity: (!bugReportText.trim() || isSubmittingBug) ? 0.5 : 1 }}
                                >
                                  {isSubmittingBug ? <Loader2 size={14} className="spin" /> : <CheckCircle2 size={14} />}
                                  Confirm & Fail Task
                                </button>
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

    </div>
  );
}

export default QAAgent;
