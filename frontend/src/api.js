const API_BASE = import.meta.env.VITE_API_BASE || "";

const DEFAULT_FETCH_TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS || 0);
const DEFAULT_RETRIES = 2;
const RETRY_DELAY_MS = 400;

// Heavy LLM-driven endpoints can legitimately run for several minutes.
// Use a long timeout and disable automatic retries so we don't duplicate work.
const LONG_RUNNING_TIMEOUT_MS = Number(import.meta.env.VITE_LONG_API_TIMEOUT_MS || 300000);
const LONG_RUNNING_RETRIES = 0;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function buildBackendError(method, url, cause, timeoutMs = DEFAULT_FETCH_TIMEOUT_MS) {
  const isTimeout = cause?.name === "AbortError";
  const reason = isTimeout
    ? `Request timed out after ${timeoutMs}ms`
    : (cause?.message || "Network request failed");
  const target = API_BASE || "same-origin /api (Vite proxy)";
  return new Error(
    `Backend unreachable (${method} ${url}). ${reason}. Check API target: ${target}.`
  );
}

async function apiFetch(url, options = {}, retries = DEFAULT_RETRIES) {
  const method = options.method || "GET";
  const timeoutMs = options.timeoutMs ?? DEFAULT_FETCH_TIMEOUT_MS;
  const fetchOptions = { ...options };
  delete fetchOptions.timeoutMs;
  let lastError = null;

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const shouldTimeout = Number.isFinite(timeoutMs) && timeoutMs > 0;
    const controller = shouldTimeout ? new AbortController() : null;
    const timeout = shouldTimeout ? setTimeout(() => controller.abort(), timeoutMs) : null;
    try {
      const res = await fetch(url, controller ? { ...fetchOptions, signal: controller.signal } : fetchOptions);
      if (timeout) clearTimeout(timeout);
      return res;
    } catch (err) {
      if (timeout) clearTimeout(timeout);
      lastError = err;
      const isAbort = err?.name === "AbortError";
      const isLastAttempt = attempt === retries;
      if (isLastAttempt) break;
      // Retry only on transport-level failures (server restarting/offline/network drop).
      if (isAbort || err instanceof TypeError) {
        await sleep(RETRY_DELAY_MS * (attempt + 1));
        continue;
      }
      throw buildBackendError(method, url, err, timeoutMs);
    }
  }

  throw buildBackendError(method, url, lastError, timeoutMs);
}

async function parseResponseBody(res) {
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return res.json().catch(() => ({}));
  }
  const text = await res.text().catch(() => "");
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { message: text };
  }
}

async function apiJson(url, options = {}, retries = DEFAULT_RETRIES) {
  const res = await apiFetch(url, options, retries);
  const body = await parseResponseBody(res);
  if (!res.ok) {
    const message = body?.error || body?.message || body?.detail || `Request failed (${res.status})`;
    const err = new Error(message);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
}

// --- AUTHENTICATION ---
export async function authSignup(data) {
  return apiJson(`${API_BASE}/api/auth/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
}

export async function authLogin(data) {
  return apiJson(`${API_BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
}

export async function authGoogle(data) {
  return apiJson(`${API_BASE}/api/auth/google`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
}

// --- COMPANIES ---
export async function getCompanies() {
  return apiJson(`${API_BASE}/api/companies`);
}

export async function updateCompany(cid, data) {
  return apiJson(`${API_BASE}/api/companies/${cid}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
}

export async function deleteCompany(cid) {
  return apiJson(`${API_BASE}/api/companies/${cid}`, { method: 'DELETE' });
}

export async function lookupCompany(domain) {
  return apiJson(`${API_BASE}/api/companies/lookup/${encodeURIComponent(domain)}`);
}

// --- LEADS ---
export async function getLeads(company_id) {
  const url = company_id ? `${API_BASE}/api/leads?company_id=${encodeURIComponent(company_id)}` : `${API_BASE}/api/leads`;
  return apiJson(url, {}, 0);
}

export async function getLead(id) {
  return apiJson(`${API_BASE}/api/leads/${encodeURIComponent(id)}`);
}

export async function registerLead(lead) {
  return apiJson(`${API_BASE}/api/leads`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(lead)
  });
}

export async function deleteLead(id) {
  return apiJson(`${API_BASE}/api/leads/${id}`, { method: 'DELETE' });
}

export async function acceptLead(id) {
  return apiJson(`${API_BASE}/api/leads/${id}/accept`, {
    method: 'POST'
  });
}

export async function generateProjectRequirements(projectId, options = {}) {
  const requestId = options.requestId || options.request_id || "";
  return apiJson(`${API_BASE}/api/projects/${projectId}/requirements`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      confirm_project_start: options.confirmProjectStart ?? true,
      change_request: options.changeRequest ?? "",
      workflow_id: options.workflow_id || options.workflowId,
      request_id: requestId
    }),

    timeoutMs: LONG_RUNNING_TIMEOUT_MS
  }, LONG_RUNNING_RETRIES);
}



export async function getProjectContext(projectId) {
  return apiJson(`${API_BASE}/api/projects/${projectId}/context`);
}

export async function getLatestProjectRequirements(projectId) {
  return apiJson(`${API_BASE}/api/projects/${projectId}/requirements/latest`);
}

export async function getProjectRequirementHistory(projectId) {
  return apiJson(`${API_BASE}/api/projects/${projectId}/requirements/history`);
}

export async function getLatestRequirements(leadId, params = {}) {
  let url = `${API_BASE}/api/leads/${leadId}/requirements/latest`;
  const query = new URLSearchParams();
  if (params.workflow_id) query.append('workflow_id', params.workflow_id);
  if (query.toString()) url += `?${query.toString()}`;
  return apiJson(url);
}

export async function getRequirementHistory(leadId) {
  return apiJson(`${API_BASE}/api/leads/${leadId}/requirements/history`);
}
export async function getSources(lead_id) {
  return apiJson(`${API_BASE}/api/sources` + (lead_id ? `?lead_id=${encodeURIComponent(lead_id)}` : ''));
}

export async function deleteSource(id) {
  return apiJson(`${API_BASE}/api/sources/${id}`, { method: 'DELETE' });
}

// --- DOCUMENTS ---
export async function uploadDocuments(files, lead_id) {
  const formData = new FormData();
  files.forEach(f => formData.append('files', f));
  formData.append('lead_id', lead_id);
  return apiJson(`${API_BASE}/api/upload`, { method: 'POST', body: formData });
}

export async function ingestText(title, content, lead_id) {
  return apiJson(`${API_BASE}/api/upload`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, content, lead_id })
  });
}

export async function analyzeDocuments(files) {
  const formData = new FormData();
  files.forEach(f => formData.append('files', f));
  try {
    return await apiJson(`${API_BASE}/api/analyze-upload`, { method: 'POST', body: formData });
  } catch (err) {
    // Compatibility fallback for deployments that only expose the intake endpoint.
    // We still return a predictable shape so the UI can continue the review flow.
    if (err?.status !== 404) {
      throw err;
    }

    const fallback = await apiJson(`${API_BASE}/api/upload`, { method: 'POST', body: formData });
    const routedTo = fallback?.routed_to || [];
    const analysis = (files || []).map((file) => ({
      filename: file?.name || 'upload',
      text: '',
      pages: 1,
      predicted_leads: routedTo,
      routing_decision: {
        action: routedTo.length ? 'existing' : 'new',
        lead_id: routedTo[0] || '',
        message: routedTo.length
          ? 'Fallback analysis routed through the intake endpoint.'
          : 'Fallback analysis found no confident lead match.',
      },
      fallback_ingested: true,
    }));

    return { ...fallback, analysis };
  }
}

export async function confirmDocuments(items) {
  return apiJson(`${API_BASE}/api/confirm-upload`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items })
  });
}

// --- CHAT ---
export async function queryRAG(query, history, lead_id, thread_id) {
  return apiJson(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, history, lead_id, thread_id })
  });
}

export async function getChatHistory(lead_id, thread_id) {
  let url = `${API_BASE}/api/history/${lead_id}`;
  if (thread_id) url += `?tid=${encodeURIComponent(thread_id)}`;
  return apiJson(url);
}

export async function getThreads(lead_id) {
  return apiJson(`${API_BASE}/api/threads/${lead_id}`);
}

export async function createThread(lead_id, title) {
  const id = Math.random().toString(36).substring(7);
  const body = await apiJson(`${API_BASE}/api/threads`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, lead_id, title })
  });
  return { id, ...body };
}

export async function clearHistory(lead_id, thread_id) {
  let url = `${API_BASE}/api/history/${lead_id}`;
  if (thread_id) url += `?tid=${encodeURIComponent(thread_id)}`;
  return apiJson(url, { method: 'DELETE' });
}

export async function deleteThread(tid) {
  return apiJson(`${API_BASE}/api/threads/${tid}`, { method: 'DELETE' });
}

// --- AGENTIC PIPELINE ---
export async function runWorkflowAgent(transcript, project_id, source_files = [], feedback = "") {
  const res = await fetch(`${API_BASE}/api/agents/workflow-analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      transcript,
      lead_id: project_id,
      project_id,
      source_files,
      feedback
    })
  });
  return res.json();
}

export async function runWorkflowRefine(current_flow, feedback, lead_id) {
  const res = await fetch(`${API_BASE}/api/agents/workflow-refine`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_flow, feedback, lead_id })
  });
  return res.json();
}

export async function runRequirementsAgent(lead_id) {
  const res = await fetch(`${API_BASE}/api/agents/requirements`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lead_id })
  });
  return res.json();
}

export async function saveArtifact(lead_id, agent_id, content) {
  const res = await fetch(`${API_BASE}/api/artifacts/save`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lead_id, agent_id, content })
  });
  return res.json();
}

export async function getArtifacts(lead_id) {
  const res = await fetch(`${API_BASE}/api/artifacts/${lead_id}`);
  return res.json();
}

// --- WORKFLOW ARTIFACTS (Session-based) ---
export async function getWorkflowSessions(project_id) {
  const res = await fetch(`${API_BASE}/api/workflow-artifacts/${project_id}`);
  return res.json();
}

export async function getWorkflowSession(project_id, version) {
  const res = await fetch(`${API_BASE}/api/workflow-artifacts/${project_id}/${version}`);
  return res.json();
}

export async function saveWorkflowSession(data) {
  const res = await fetch(`${API_BASE}/api/workflow-artifacts/save`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  return res.json();
}

export async function approveWorkflowSession(project_id, version) {
  const res = await fetch(`${API_BASE}/api/workflow-artifacts/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id, version })
  });
  return res.json();
}

export async function deleteWorkflowSession(project_id, version) {
  const res = await fetch(`${API_BASE}/api/workflow-artifacts/${project_id}/${version}`, {
    method: 'DELETE'
  });
  return res.json();
}

export async function saveSprintTaskArtifact(data) {
  const res = await fetch(`${API_BASE}/api/sprint-task-artifacts/save`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  return res.json();
}

export async function getSprintTaskArtifact(project_id, workflow_id, session_version) {
  const res = await fetch(`${API_BASE}/api/sprint-task-artifacts/${encodeURIComponent(project_id)}/${encodeURIComponent(workflow_id)}/${encodeURIComponent(session_version)}`);
  return res.json();
}

export async function runDocAgent(lead_id, workflow_id, tech_stack, additional_context = "") {
  const res = await fetch(`${API_BASE}/api/agents/doc-generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lead_id, workflow_id, tech_stack, additional_context })
  });
  return res.json();
}


export const getLatestDocArtifact = async (lead_id, workflow_id) => {
  const response = await fetch(`${API_BASE}/api/doc-artifacts/${lead_id}/${workflow_id}/latest`);
  return response.json();
};

export async function runIAGeneration(lead_id, workflow_id) {
  const res = await fetch(`${API_BASE}/api/agents/ia-generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lead_id, workflow_id })
  });
  return res.json();
}

export async function extractFileText(file) {
  const formData = new FormData();
  formData.append('file', file);
  return apiJson(`${API_BASE}/api/utils/extract-text`, {
    method: 'POST',
    body: formData
  });
}
export async function refineDocAgent(lead_id, workflow_id, feedback) {
  const res = await fetch(`${API_BASE}/api/agents/doc-refine`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lead_id, workflow_id, feedback })
  });
  return res.json();
}


export async function runUISynthesis(project_id, workflow_id, session_version, check_only = false) {
  return apiJson(`${API_BASE}/api/agents/ui-synthesis`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id, workflow_id, session_version, check_only }),
    timeoutMs: 0
  }, 0);
}

export async function refineUISynthesis(project_id, workflow_id, session_version, feedback) {
  return apiJson(`${API_BASE}/api/agents/ui-refine`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id, workflow_id, session_version, feedback }),
    timeoutMs: 0
  }, 0);
}

export async function runQAAgent(data) {
  return apiJson(`${API_BASE}/api/agents/qa-generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
    timeoutMs: LONG_RUNNING_TIMEOUT_MS
  }, 0);
}

export async function getTestCases(projectId, workflowId) {
  const url = workflowId
    ? `${API_BASE}/api/test-cases/${projectId}?workflow_id=${encodeURIComponent(workflowId)}`
    : `${API_BASE}/api/test-cases/${projectId}`;
  return apiJson(url);
}


export async function runInfraAgent(data) {
  return apiJson(`${API_BASE}/api/agents/infra-generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
    timeoutMs: LONG_RUNNING_TIMEOUT_MS
  }, 0);
}


// --- TASK & SPRINT ENGINE ---

/**
 * Fetch all persisted tasks for a project from the DB.
 * @param {string} projectId
 * @param {string|null} workflowId
 */
export async function getTasks(projectId, workflowId = null) {
  let url = `${API_BASE}/api/tasks/${encodeURIComponent(projectId)}`;
  if (workflowId) url += `?workflow_id=${encodeURIComponent(workflowId)}`;
  return apiJson(url);
}

/**
 * Bulk-upsert AI-derived tasks into the DB (idempotent, safe to call on every mount).
 * The server only updates metadata columns — it never overwrites an existing task's status.
 * @param {string} projectId
 * @param {string|null} workflowId
 * @param {Array} tasks  — the raw task objects from deriveSprintTasks()
 */
export async function syncTasks(projectId, workflowId, tasks) {
  return apiJson(`${API_BASE}/api/tasks/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, workflow_id: workflowId, tasks })
  });
}

/**
 * Persist a single task status change from a kanban drag-drop.
 * @param {string} taskId
 * @param {string} status  — one of: todo | inprog | review | done
 */
export async function updateTaskStatus(taskId, status, projectId, workflowId) {
  return apiJson(`${API_BASE}/api/tasks/${encodeURIComponent(taskId)}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, project_id: projectId, workflow_id: workflowId, updated_via: "drag" })
  });
}

export async function failTestCase(taskId, data) {
  // data should contain: test_case_id, test_case_title, bug_report, project_id, workflow_id
  return apiJson(`${API_BASE}/api/tasks/${encodeURIComponent(taskId)}/fail-test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data)
  });
}
