import os
import uuid
import json
import asyncio
import importlib.util
import sys
import threading
import os
import mysql.connector
from mysql.connector import Error, pooling
import io
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, Form, Request, BackgroundTasks
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
import uvicorn
import uuid
from pypdf import PdfReader
from pydantic import BaseModel, Field
from dotenv import load_dotenv

import zipfile
import email
from email import policy
import re
from operator import itemgetter
import xml.etree.ElementTree as ET
import importlib.util
try:
    import docx
except ImportError as e:
    print(f"⚠️ Warning: Failed to load 'docx' module due to system restrictions: {e}")
    docx = None


from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate

# --- DIRECTORIES / ENV ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# --- CORE UTILS ---
from core import get_model
from pipeline import run_workflow_agent, run_workflow_refine
from doc_architect_agent import generate_architecture_documents, DesignOutput


try:
    from pdf_generator import generate_design_pdf, generate_hld_pdf, generate_lld_pdf
    PDF_GENERATOR_IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    # Keep the API bootable even when optional PDF dependencies are missing.
    if exc.name != "fpdf":
        raise
    generate_design_pdf = None
    generate_hld_pdf = None
    generate_lld_pdf = None
    PDF_GENERATOR_IMPORT_ERROR = (
        "PDF export is unavailable because the 'fpdf' package is not installed. "
        "Install project dependencies with `pip install -r req.txt`."
    )

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

def _get_env(*names: str, default: Optional[str] = None) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def _env_truthy(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


_raw_db_host = _get_env("db_host", "DB_HOST", "MYSQLHOST", "MYSQL_HOST", default="127.0.0.1") or ""
DB_HOST = "127.0.0.1" if _raw_db_host.lower() in {"", "localhost"} else _raw_db_host

# --- DIRECTORIES ---
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_USER = _get_env("db_username", "DB_USER", "MYSQLUSER", "MYSQL_USER", default="root")
DB_PASSWORD = _get_env("db_password", "DB_PASSWORD", "MYSQLPASSWORD", "MYSQL_PASSWORD")
DB_NAME = _get_env("db_name", "DB_NAME", "MYSQLDATABASE", "MYSQL_DATABASE", default="LeadFlowDB")
DB_PORT = int(_get_env("db_port", "DB_PORT", "MYSQLPORT", "MYSQL_PORT", default="3306"))
DB_CONNECT_TIMEOUT = int(os.getenv("db_connect_timeout", 5))
DB_READ_TIMEOUT = int(os.getenv("db_read_timeout", 5))
DB_WRITE_TIMEOUT = int(os.getenv("db_write_timeout", 5))
DB_USE_POOL = os.getenv("db_use_pool", "false").strip().lower() in {"1", "true", "yes"}
LEADS_DB_BYPASS = os.getenv("LEADS_DB_BYPASS", "false").strip().lower() in {"1", "true", "yes"}
REQ_FAST_MODE = _env_truthy(os.getenv("REQ_FAST_MODE"), True)

app = FastAPI(title="LeadFlow Vision AI - Strategic RAG Core")

default_cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://project-management-tool-ashy-zeta.vercel.app",
]
extra_cors_origins = [
    origin.strip()
    for origin in (os.getenv("CORS_ORIGINS", "") or "").split(",")
    if origin.strip()
]
cors_origins = sorted(set(default_cors_origins + extra_cors_origins))
cors_origin_regex = os.getenv(
    "CORS_ORIGIN_REGEX",
    r"^https://.*\.vercel\.app$|^http://localhost:\d+$|^http://127\.0\.0\.1:\d+$"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"message": "API is running"}


@app.head("/")
def root_head():
    return Response(status_code=200)


@app.get("/test-db")
def test_db():
    try:
        conn = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
        )
        cursor = conn.cursor()
        cursor.execute("SHOW TABLES;")
        tables = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return {"tables": tables}
    except Exception as e:
        return {"error": str(e)}

CLEANING_PROMPT = """
You are a Document Preprocessor.

Input:
Raw document text (PDF / Email / Transcript)

Task:
- Remove noise (headers, timestamps, signatures)
- Normalize text
- Fix broken sentences
- Keep only meaningful conversational/business content

Return clean text only.
"""

DISTILLATION_PROMPT = """
You are a Forensic Intelligence Analyst.

Input:
Raw lead-intake document text from emails, transcripts, proposals, PDFs, or notes.

Task:
Extract the following:

1. PRIMARY ENTITY
- The client company, organization, or prospect name

2. KEY STAKEHOLDERS
- Only client-side people
- Exclude internal team members such as Marcus, Bharat, and Christofer

3. PROJECT SCOPE
- Business problems, operational pain points, requested solutions, technical asks, or project goals discussed

4. INDUSTRY / FIELD
- The business domain, sector, or operating field of the client

5. INTERACTION CONTEXT
- Classify the document as one of:
  - email
  - transcript
  - proposal
  - document
  - unknown

Rules:
- Ignore internal team members, vendor-side discussion, signatures, disclaimers, and unrelated document noise
- Do not invent missing details
- If the client entity is unclear, return: ENTITY: UNKNOWN
- Keep the output factual and concise
- Do not add explanations outside the structured summary

Output Format:
PRIMARY ENTITY: ...
KEY STAKEHOLDERS: ...
PROJECT SCOPE: ...
INDUSTRY / FIELD: ...
INTERACTION CONTEXT: ...
"""

CONTEXT_SPLIT_PROMPT = """
You are a Conversation Segmentation Expert.

Input:
A cleaned transcript containing one or more client discussions.

Task:
- Detect whether the transcript contains multiple independent discussion contexts
- Split the transcript into separate contexts when appropriate

Segmentation Goal:
- Each context should represent one distinct lead, project, business problem, or solution discussion
- If the transcript is about only one discussion, return a single context

Split when you detect:
- a clear change in speaker intent
- a shift to a different business problem
- a move to a new project, initiative, workflow, or client need
- a separate solution track or implementation track
- a different stakeholder discussion with a different objective

Do not split for:
- minor wording changes
- follow-up clarifications within the same discussion
- detailed continuation of the same project/problem
- repeated references to the same lead or business topic

Rules:
- Each context must be internally coherent
- Preserve the original wording as much as possible
- Do not summarize
- Do not rewrite into a different style
- Do not drop meaningful business content
- Make each segment large enough to retain usable context
- If uncertain, prefer fewer segments over unnecessary fragmentation

Return STRICT JSON only in this format:
[
  {
    "context_id": "CTX-1",
    "text": "..."
  }
]
"""

LEAD_MATCH_PROMPT = """
You are the ViljeTech Senior Auditor.

Input:
- Context summary
- Existing leads database

Rules:
- Require at least 2-3 strong matches:
  - company name
  - stakeholder
  - project context

- If ambiguous -> return empty
- Confidence must be >95%

Return:

{
  "matched_lead_ids": [],
  "confidence_score": 0-100
}
"""

LEAD_DECISION_PROMPT = """
You are a Lead Routing Decision Engine.

Input:
Matching result

Task:

IF match exists:
-> route to existing lead

IF no match:
-> mark as NEW LEAD

Return:

{
  "action": "existing | new",
  "lead_id": "...",
  "message": "..."
}
"""

STORAGE_PROMPT = """
You are a Context Storage Engine.

Input:
- Context text
- Lead ID

Task:
- Append new context to lead
- Maintain chronological history
- Do NOT overwrite previous data

Return:

{
  "status": "stored",
  "lead_id": "...",
  "context_added": true
}
"""

NEW_LEAD_PROMPT = """
You are a Lead Initialization Assistant.

Input:
Extracted summary

Task:
Pre-fill:

- Company Name
- Stakeholders
- Industry
- Problem Summary

IMPORTANT:
- DO NOT auto-create
- Ask user confirmation

Return:

{
  "suggested_lead": {...},
  "message": "No matching lead found. Do you want to create a new lead?"
}
"""

REQ_TRIGGER_PROMPT = """
You are a Workflow Trigger Engine.

Task:

ONLY trigger requirement generation IF:
- lead is accepted
- user confirms project start

IMPORTANT:
- Do NOT use previous lead context
- Treat requirement input as fresh

Return:
{
  "next_step": "requirement_generation"
}
"""

TEMP_AUTH_EMAIL = "admin@vilje.ai"
TEMP_AUTH_PASSWORD = "Admin@123"
TEMP_AUTH_USER = {
    "id": "temp-admin",
    "name": "VILJE Admin",
    "email": TEMP_AUTH_EMAIL,
    "role": "admin",
    "auth_provider": "credentials",
}


class AuthCredentials(BaseModel):
    email: str
    password: str


class SignupPayload(BaseModel):
    email: str
    name: str
    password: str


class GoogleAuthPayload(BaseModel):
    email: Optional[str] = None
    name: Optional[str] = None
    credential: Optional[str] = None


# --- DOCUMENT AGENT MODELS (Moved to doc_architect_agent.py) ---

class DocGenerateRequest(BaseModel):
    lead_id: str
    workflow_id: str
    tech_stack: Optional[str] = ""
    additional_context: Optional[str] = ""

class DocRefineRequest(BaseModel):
    lead_id: str
    workflow_id: str
    feedback: str

class IAGenerateRequest(BaseModel):
    lead_id: str
    workflow_id: str

class QAGenerateRequest(BaseModel):
    project_id: str
    workflow_id: str

# InfraGenerateRequest placeholder — new Deployment agent coming soon.




@app.post("/api/agents/doc-refine")
async def refine_architecture(payload: DocRefineRequest):
    """Iteratively refines the HLD and LLD based on user feedback."""
    try:
        lid = payload.lead_id
        workflow_id = payload.workflow_id
        
        db = get_db(); c = db.cursor(dictionary=True)
        
        # 1. Get the latest design artifact for context
        c.execute(
            "SELECT * FROM doc_agent_artifacts WHERE lead_id=%s AND workflow_id=%s ORDER BY version DESC LIMIT 1",
            (lid, workflow_id)
        )
        current_artifact = c.fetchone()
        if not current_artifact:
            return JSONResponse(status_code=404, content={"error": "No existing design found to refine."})
            
        # 2. Get requirements and workflow context
        db = get_db(); c = db.cursor(dictionary=True)
        c.execute("SELECT id FROM projects WHERE lead_id=%s LIMIT 1", (lid,))
        p = c.fetchone()
        project_id = p['id'] if p else None

        # Fetch Requirements (Priority to session-specific)
        if workflow_id:
            req_state = await run_blocking_call(get_requirement_state_db, lid, workflow_id)
            if not req_state:
                req_state = await run_blocking_call(_load_normalized_requirements_state_db, project_id) if project_id else None
        else:
            normalized_state = await run_blocking_call(_load_normalized_requirements_state_db, project_id) if project_id else None
            req_state = normalized_state or await run_blocking_call(get_requirement_state_db, lid, workflow_id)
            
        requirements = req_state.get("current_requirements") if req_state else ""
        
        # Fetch Workflow Context (Try specific session first)
        flow_row = None
        try:
            version_int = int(str(workflow_id).replace("Session ", ""))
            c.execute("SELECT nodes FROM workflows WHERE project_id=%s AND type='to_be' AND version=%s", (lid, version_int))
            flow_row = c.fetchone()
        except: pass

        if not flow_row:
            c.execute("SELECT nodes FROM workflows WHERE project_id=%s AND type='to_be' ORDER BY version DESC LIMIT 1", (lid,))
            flow_row = c.fetchone()
            
        workflow_mermaid = flow_row['nodes'] if flow_row else ""
        c.close(); db.close()

        # 3. Trigger Refinement
        from doc_architect_agent import refine_architecture_documents as run_refinement
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model="gpt-4o", temperature=0)
        
        design_output = await run_refinement(
            llm,
            current_artifact['hld_content'],
            current_artifact['lld_content'],
            payload.feedback,
            workflow_mermaid,
            str(requirements)
        )

        # 4. Save New Version
        db = get_db(); c = db.cursor()
        new_id = str(uuid.uuid4())
        new_version = current_artifact['version'] + 1
        
        c.execute(
            """INSERT INTO doc_agent_artifacts (id, lead_id, workflow_id, version, project_summary, hld_content, lld_content, db_schema, backlog)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                new_id, lid, workflow_id, new_version,
                design_output.project_summary,
                design_output.hld_content,
                design_output.lld_content,
                design_output.db_schema,
                json.dumps([b.dict() for b in design_output.backlog])
            )
        )
        db.commit(); c.close(); db.close()

        return {
            "status": "ok",
            "artifact_id": new_id,
            "version": new_version,
            "design": design_output.dict()
        }

    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": f"Refinement failed: {str(e)}"})

class UISynthesisRequest(BaseModel):
    project_id: str
    workflow_id: str
    session_version: int
    check_only: bool = False


def _resolve_lead_id_for_ref(cursor, ref_id: str) -> Optional[str]:
    """Resolve a project/reference id to the lead_id used by doc artifacts."""
    if not ref_id:
        return None

    cursor.execute("SELECT lead_id FROM projects WHERE id=%s LIMIT 1", (ref_id,))
    row = cursor.fetchone()
    if row and row.get("lead_id"):
        return row["lead_id"]
    return ref_id


@app.get("/api/debug/ui-context")
async def debug_ui_context(project_id: str, workflow_id: str, session_version: int):
    """Return non-sensitive diagnostics for UI synthesis lookups."""
    try:
        db = get_db()
        c = db.cursor(dictionary=True)

        resolved_lead_id = _resolve_lead_id_for_ref(c, project_id)
        c.execute(
            "SELECT id, version FROM doc_agent_artifacts WHERE lead_id=%s AND workflow_id=%s ORDER BY version DESC LIMIT 1",
            (resolved_lead_id, workflow_id),
        )
        doc_row = c.fetchone()

        c.execute(
            "SELECT id, version, client_approved FROM workflows WHERE project_id=%s AND version=%s LIMIT 1",
            (project_id, session_version),
        )
        workflow_row = c.fetchone()

        c.close()
        db.close()

        return {
            "status": "ok",
            "project_id": project_id,
            "workflow_id": workflow_id,
            "session_version": session_version,
            "resolved_lead_id": resolved_lead_id,
            "stitch_configured": bool(STITCH_API_KEY),
            "google_api_configured": bool(os.getenv("GOOGLE_API_KEY")),
            "doc_artifact_exists": bool(doc_row),
            "doc_artifact_version": doc_row.get("version") if doc_row else None,
            "workflow_exists": bool(workflow_row),
            "workflow_version": workflow_row.get("version") if workflow_row else None,
            "workflow_approved": bool(workflow_row and workflow_row.get("client_approved")),
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})

@app.post("/api/agents/ui-synthesis")
async def run_ui_synthesis(payload: UISynthesisRequest):
    """Triggers the UI Design Agent to generate components in Stitch."""
    try:
        print(
            "[UI_SYNTHESIS] request",
            {
                "project_id": payload.project_id,
                "workflow_id": payload.workflow_id,
                "session_version": payload.session_version,
                "check_only": payload.check_only,
            },
        )
        from ui_agent import generate_ui_synthesis
        result = await generate_ui_synthesis(
            payload.project_id,
            payload.workflow_id,
            payload.session_version,
            check_only=payload.check_only
        )
        if result.get("status") == "error":
            print("[UI_SYNTHESIS] failed", result)
            return JSONResponse(status_code=400, content=result)
        print("[UI_SYNTHESIS] success", {"status": result.get("status"), "workflow_version": result.get("workflow_version")})
        return result
    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": f"Synthesis failed: {str(e)}"})

@app.post("/api/agents/ui-refine")
async def refine_ui_synthesis(payload: dict):
    """Refines an existing UI synthesis in Stitch based on feedback."""
    try:
        from ui_agent import generate_ui_refinement
        result = await generate_ui_refinement(
            payload.get("project_id"),
            payload.get("workflow_id"),
            payload.get("session_version"),
            payload.get("feedback")
        )
        if result.get("status") == "error":
            return JSONResponse(status_code=400, content=result)
        return result
    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": f"Refinement failed: {str(e)}"})

@app.post("/api/agents/qa-generate")
async def trigger_qa_agent(payload: QAGenerateRequest):
    """Triggers the QA Agent to generate test suites for tasks in 'review' state."""
    try:
        project_id = payload.project_id
        workflow_id = payload.workflow_id
        
        db = get_db(); c = db.cursor(dictionary=True)
        
        # 1. Fetch tasks in review
        c.execute("SELECT * FROM tasks WHERE project_id=%s AND workflow_id=%s AND status='review'", (project_id, workflow_id))
        review_tasks = c.fetchall()
        
        if not review_tasks:
            c.close(); db.close()
            return {"status": "skipped", "message": "No tasks are currently in the Review stage.", "test_cases": []}
            
        # 2. Fetch HLD and LLD
        c.execute("SELECT lead_id FROM projects WHERE id=%s LIMIT 1", (project_id,))
        p = c.fetchone()
        lead_id = p['lead_id'] if p else None
        
        hld_content = ""
        lld_content = ""
        if lead_id:
            c.execute(
                "SELECT hld_content, lld_content FROM doc_agent_artifacts WHERE lead_id=%s AND workflow_id=%s ORDER BY version DESC LIMIT 1",
                (lead_id, workflow_id)
            )
            doc_row = c.fetchone()
            if doc_row:
                hld_content = doc_row['hld_content'] or ""
                lld_content = doc_row['lld_content'] or ""
                
        # 3. Call QA Agent
        from qa_agent import generate_test_cases
        qa_output = await generate_test_cases(review_tasks, hld_content, lld_content)
        
        # 4. Save Test Cases to DB
        saved_cases = []
        for tc in qa_output.test_cases:
            tc_id = str(uuid.uuid4())
            c.execute(
                """INSERT INTO test_cases (id, requirement_id, workflow_id, title, description, type, test_steps, expected_result)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (tc_id, tc.requirement_id, workflow_id, tc.title, tc.description, tc.type, tc.test_steps, tc.expected_result)
            )
            tc_dict = tc.dict()
            tc_dict['id'] = tc_id
            saved_cases.append(tc_dict)
            
        db.commit()
        c.close(); db.close()
        
        return {
            "status": "success",
            "message": f"Successfully generated {len(saved_cases)} test cases.",
            "test_cases": saved_cases
        }
    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": f"QA Suite generation failed: {str(e)}"})

# /api/agents/infra-generate placeholder.
# New Deployment agent endpoint will be defined here.

@app.get("/api/test-cases/{project_id}")
async def get_test_cases(project_id: str, workflow_id: Optional[str] = None):
    """Return all persisted test cases for a project/workflow."""
    try:
        db = get_db(); c = db.cursor(dictionary=True)
        if workflow_id:
            print(f"[DEBUG] Fetching test cases for Proj: {project_id}, WF: {workflow_id}")
            c.execute(
                """SELECT t.*, 
                          (SELECT id FROM tasks 
                           WHERE requirement_id = t.requirement_id 
                           AND project_id = t.project_id 
                           AND workflow_id = t.workflow_id 
                           LIMIT 1) as task_id,
                          (SELECT title FROM tasks 
                           WHERE requirement_id = t.requirement_id 
                           AND project_id = t.project_id 
                           AND workflow_id = t.workflow_id 
                           LIMIT 1) as task_title
                   FROM test_cases t 
                   WHERE t.workflow_id=%s AND t.project_id=%s
                   ORDER BY t.created_at ASC""",
                (workflow_id, project_id)
            )
        else:
            c.execute(
                """SELECT t.*, 
                          (SELECT id FROM tasks 
                           WHERE requirement_id = t.requirement_id 
                           AND project_id = t.project_id 
                           LIMIT 1) as task_id,
                          (SELECT title FROM tasks 
                           WHERE requirement_id = t.requirement_id 
                           AND project_id = t.project_id 
                           LIMIT 1) as task_title
                   FROM test_cases t 
                   WHERE t.project_id=%s 
                   ORDER BY t.created_at ASC""",
                (project_id,)
            )
        rows = c.fetchall()
        c.close(); db.close()
        return {"test_cases": rows}
    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": f"Failed to fetch test cases: {str(e)}"})


# ─────────────────────────────────────────────────────────
#  TASK & SPRINT ENGINE — DB PERSISTENCE ENDPOINTS
# ─────────────────────────────────────────────────────────

@app.get("/api/tasks/{project_id}")
async def get_tasks(project_id: str, workflow_id: Optional[str] = None):
    """Return all persisted tasks for a project, optionally filtered by workflow_id."""
    try:
        db = get_db(); c = db.cursor(dictionary=True)
        if workflow_id:
            c.execute(
                "SELECT * FROM tasks WHERE project_id=%s AND workflow_id=%s ORDER BY sprint_label ASC, created_at ASC",
                (project_id, workflow_id)
            )
        else:
            c.execute(
                "SELECT * FROM tasks WHERE project_id=%s ORDER BY sprint_label ASC, created_at ASC",
                (project_id,)
            )
        rows = c.fetchall()
        c.close(); db.close()
        # Decode any bytes fields
        for row in rows:
            for k, v in list(row.items()):
                if isinstance(v, (bytes, bytearray)):
                    row[k] = v.decode("utf-8", errors="ignore")
            if "hours" not in row:
                raw_hours = row.get("effort_estimate_hours")
                try:
                    row["hours"] = int(raw_hours) if raw_hours is not None else 0
                except (TypeError, ValueError):
                    row["hours"] = 0
        return {"tasks": rows}
    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})


class TaskSyncPayload(BaseModel):
    project_id: str
    workflow_id: Optional[str] = None
    tasks: list


@app.post("/api/tasks/sync")
async def sync_tasks(payload: TaskSyncPayload):
    """Bulk-upsert AI-derived sprint tasks into the tasks table (idempotent).
    Only inserts rows that do not yet exist — preserves existing status/assignee overrides."""
    try:
        db = get_db(); c = db.cursor()
        inserted = 0
        for t in payload.tasks:
            task_id = t.get("id", "")
            if not task_id:
                continue
            c.execute(
                """INSERT INTO tasks
                   (id, project_id, workflow_id, requirement_id, title, description,
                    status, assignee_id, effort_estimate_hours, priority,
                    sprint_label, story, user_story, ai_generated, last_updated_via, created_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,'sync',NOW(),NOW())
                   ON DUPLICATE KEY UPDATE
                     title=VALUES(title),
                     description=VALUES(description),
                     effort_estimate_hours=VALUES(effort_estimate_hours),
                     priority=VALUES(priority),
                     sprint_label=VALUES(sprint_label),
                     story=VALUES(story),
                     user_story=VALUES(user_story),
                     assignee_id=VALUES(assignee_id),
                     updated_at=NOW()""",
                (
                    task_id,
                    payload.project_id,
                    payload.workflow_id or "",
                    t.get("sourceReq", ""),
                    (t.get("title", ""))[:255],
                    t.get("description", ""),
                    t.get("status", "todo"),
                    t.get("assignee", {}).get("id", "") if isinstance(t.get("assignee"), dict) else str(t.get("assignee", "")),
                    int(t.get("hours", 4)),
                    t.get("priority", "medium"),
                    t.get("sprint", "Sprint 1"),
                    t.get("story", ""),
                    t.get("userStory", ""),
                )
            )
            inserted += 1
        db.commit(); c.close(); db.close()
        return {"status": "ok", "synced": inserted}
    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})


class TaskStatusUpdate(BaseModel):
    status: str
    project_id: str
    workflow_id: Optional[str] = None
    updated_via: Optional[str] = "drag"


@app.patch("/api/tasks/{task_id}/status")
async def update_task_status(task_id: str, payload: TaskStatusUpdate, background_tasks: BackgroundTasks):
    """Persist a single task's status change (called on kanban drag-drop)."""
    allowed = {"todo", "inprog", "review", "done"}
    if payload.status not in allowed:
        return JSONResponse(status_code=400, content={"error": f"Invalid status '{payload.status}'. Must be one of {sorted(allowed)}"})
    try:
        db = get_db(); c = db.cursor(dictionary=True)
        
        # Grab task info using composite key
        c.execute(
            "SELECT requirement_id, workflow_id FROM tasks WHERE id=%s AND project_id=%s AND workflow_id=%s", 
            (task_id, payload.project_id, payload.workflow_id or "")
        )
        tr = c.fetchone()
        
        c.execute(
            "UPDATE tasks SET status=%s, last_updated_via=%s, updated_at=NOW() WHERE id=%s AND project_id=%s AND workflow_id=%s",
            (payload.status, payload.updated_via or "drag", task_id, payload.project_id, payload.workflow_id or "")
        )
        affected = c.rowcount
        
        if affected > 0 and tr:
            if payload.status == 'review':
                # Trigger QA Generation in background using composite keys
                background_tasks.add_task(auto_generate_qa_for_task, task_id, payload.project_id, payload.workflow_id or "")
            else:
                # Delete test cases if moved OUT of review
                c.execute("DELETE FROM test_cases WHERE requirement_id=%s AND workflow_id=%s", (tr['requirement_id'], tr['workflow_id']))
                
        db.commit(); c.close(); db.close()
        
        if affected == 0:
            return JSONResponse(status_code=404, content={"error": f"Task '{task_id}' not found."})
        return {"status": "ok", "task_id": task_id, "new_status": payload.status}
    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

class TaskFailPayload(BaseModel):
    test_case_id: str
    test_case_title: str
    bug_report: str
    project_id: str
    workflow_id: Optional[str] = None

@app.post("/api/tasks/{task_id}/fail-test")
async def fail_task_test(task_id: str, payload: TaskFailPayload):
    """Logs a bug report and moves a task from review back to inprog."""
    try:
        db = get_db(); c = db.cursor(dictionary=True)
        # Filter by composite key to ensure correct task identification
        c.execute(
            "SELECT requirement_id, workflow_id, description FROM tasks WHERE id=%s AND project_id=%s AND workflow_id=%s", 
            (task_id, payload.project_id, payload.workflow_id or "")
        )
        task = c.fetchone()
        
        if not task:
            c.close(); db.close()
            return JSONResponse(status_code=404, content={"error": f"Task '{task_id}' not found."})
            
        new_desc = task['description'] or ""
        bug_entry = f"\n\n--- BUG REPORT: {payload.test_case_title} ---\n{payload.bug_report}\n"
        new_desc += bug_entry
        
        c.execute(
            "UPDATE tasks SET status='inprog', description=%s, last_updated_via='qa_fail', updated_at=NOW() WHERE id=%s AND project_id=%s AND workflow_id=%s",
            (new_desc, task_id, payload.project_id, payload.workflow_id or "")
        )
        
        c.execute("DELETE FROM test_cases WHERE requirement_id=%s AND project_id=%s AND workflow_id=%s", (task['requirement_id'], payload.project_id, task['workflow_id']))
        
        db.commit(); c.close(); db.close()
        return {"status": "ok", "task_id": task_id}
    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})


async def auto_generate_qa_for_task(task_id: str, project_id: str, workflow_id: str):
    """Triggered in background when a task moves to 'review'."""
    try:
        db = get_db(); c = db.cursor(dictionary=True)
        
        # 1. Fetch the triggering task
        c.execute(
            "SELECT * FROM tasks WHERE id=%s AND project_id=%s AND workflow_id=%s", 
            (task_id, project_id, workflow_id)
        )
        task = c.fetchone()
        if not task or task['status'] != 'review':
            print(f"[DEBUG] QA trigger ignored: Task {task_id} not in review status.")
            c.close(); db.close(); return
            
        req_id = task['requirement_id']
        
        # 2. DEBOUNCE: Avoid double-fire within 60 seconds for this requirement/workflow
        c.execute(
            """SELECT COUNT(*) as count FROM test_cases 
               WHERE requirement_id=%s AND project_id=%s AND workflow_id=%s 
               AND created_at > NOW() - INTERVAL 1 MINUTE""",
            (req_id, project_id, workflow_id)
        )
        if c.fetchone()['count'] > 0:
            print(f"[DEBUG] QA Suite generated recently for {req_id}. Skipping burst.")
            c.close(); db.close(); return

        print(f"[DEBUG] Generating QA suite for {req_id} in WF: {workflow_id}")
        
        # 3. Clean up old tests for this specific (Req, Proj, WF)
        c.execute("DELETE FROM test_cases WHERE requirement_id=%s AND project_id=%s AND workflow_id=%s", (req_id, project_id, workflow_id))
        
        # 4. Fetch architectural context
        c.execute(
            "SELECT hld_content, lld_content FROM doc_agent_artifacts WHERE lead_id=%s AND workflow_id=%s ORDER BY version DESC LIMIT 1",
            (project_id, workflow_id)
        )
        doc_row = c.fetchone()
        hld = doc_row['hld_content'] if doc_row else ""
        lld = doc_row['lld_content'] if doc_row else ""

        # 5. Fetch ALL tasks for this requirement in this workflow that are in review
        c.execute(
            "SELECT * FROM tasks WHERE requirement_id=%s AND project_id=%s AND workflow_id=%s AND status='review'",
            (req_id, project_id, workflow_id)
        )
        review_tasks = c.fetchall()
        if not review_tasks:
            print(f"[WARNING] No tasks found for {req_id} during generation. Skipping.")
            c.close(); db.close(); return

        # 6. Generate (AI call)
        from qa_agent import generate_test_cases
        qa_suite = await generate_test_cases(review_tasks, hld, lld)
        
        # 7. Persist
        if qa_suite and qa_suite.test_cases:
            for tc in qa_suite.test_cases:
                c.execute(
                    """INSERT INTO test_cases (id, project_id, requirement_id, workflow_id, title, description, type, test_steps, expected_result, status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')""",
                    (str(uuid.uuid4())[:8], project_id, req_id, workflow_id, tc.title, tc.description, tc.type, tc.test_steps, tc.expected_result)
                )
            db.commit()
            print(f"[SUCCESS] Generated {len(qa_suite.test_cases)} tests for {req_id}")
        
        c.close(); db.close()
    except Exception as e:
        print(f"[CRITICAL ERROR] QA background task failed: {str(e)}")
        import traceback; traceback.print_exc()

# --- MODELS & TOOLS (Lazy Loaded) ---
_model = None
_embeddings = None

def get_embeddings():
    global _embeddings
    if _embeddings is None:
        _embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    return _embeddings

splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=300)

# --- AGENTIC MODULES ---
_req_generation_module = None

def get_req_generation_module():
    global _req_generation_module
    if _req_generation_module is None:
        module_path = os.path.join(BASE_DIR, "Req-generation.py")
        if BASE_DIR not in sys.path:
            sys.path.insert(0, BASE_DIR)
        spec = importlib.util.spec_from_file_location("req_generation_module", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _req_generation_module = module
    return _req_generation_module

# --- DB MANAGEMENT ---
db_config = {
    "host": DB_HOST,
    "user": DB_USER,
    "password": DB_PASSWORD,
    "database": DB_NAME,
    "port": DB_PORT,
    "connection_timeout": DB_CONNECT_TIMEOUT,
    "read_timeout": DB_READ_TIMEOUT,
    "write_timeout": DB_WRITE_TIMEOUT,
}

# Ensure database exists (using a temporary connection)
if DB_HOST and DB_USER and DB_NAME and DB_PASSWORD is not None:
    try:
        temp_conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT,
            connection_timeout=DB_CONNECT_TIMEOUT,
        )
        temp_cursor = temp_conn.cursor()
        temp_cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}`")
        temp_conn.commit()
        temp_cursor.close()
        temp_conn.close()
    except Error as e:
        print(f"Database bootstrap warning: {e}")
else:
    print("Database bootstrap skipped: database env vars are not fully configured yet.")

db_pool = None
if DB_USE_POOL:
    try:
        db_pool = pooling.MySQLConnectionPool(
            pool_name="leadflow_pool",
            pool_size=10,
            pool_reset_session=True,
            **db_config
        )
        print("Database connection pool initialized.")
    except Error as e:
        print(f"Error creating connection pool. Falling back to direct connections: {e}")
        db_pool = None
else:
    print("DB pool disabled (db_use_pool=false). Using direct connections.")

_project_requirement_locks = {}
_project_requirement_locks_mutex = threading.Lock()


def _get_project_requirement_lock(project_id: str) -> asyncio.Lock:
    lock = _project_requirement_locks.get(project_id)
    if lock is None:
        with _project_requirement_locks_mutex:
            lock = _project_requirement_locks.get(project_id)
            if lock is None:
                lock = asyncio.Lock()
                _project_requirement_locks[project_id] = lock
    return lock

def get_db():
    if db_pool:
        conn = None
        try:
            conn = db_pool.get_connection()
            # Proactively fail stale pool connections fast.
            conn.ping(reconnect=True, attempts=1, delay=0)
            return conn
        except Error:
            try:
                conn.close()
            except Exception:
                pass
            # Fall through to direct connection when pool is unhealthy/exhausted.
            pass
    return mysql.connector.connect(**db_config)


async def run_blocking_call(func, *args, timeout: int = 5):
    """Run blocking DB/file operations without freezing FastAPI event loop."""
    return await asyncio.wait_for(run_in_threadpool(func, *args), timeout=timeout)

def init_db():
    try:
        conn = get_db(); c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS leads (id VARCHAR(255) PRIMARY KEY, company_id VARCHAR(255), project_name TEXT, company TEXT, domain TEXT, industry TEXT, poc TEXT, company_size TEXT, lead_info LONGTEXT, vector_index LONGBLOB, at VARCHAR(255))")
        c.execute("CREATE TABLE IF NOT EXISTS users (id CHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL, email VARCHAR(255) NOT NULL UNIQUE, password TEXT, provider VARCHAR(50), role ENUM('PM', 'Dev', 'QA', 'Design', 'Client', 'Admin') NOT NULL DEFAULT 'Client', status ENUM('Active', 'Inactive', 'Suspended') DEFAULT 'Active', base_capacity INT DEFAULT 100, timezone VARCHAR(100), last_active_at DATETIME, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")
        # RAG/Requirement tables
        c.execute("CREATE TABLE IF NOT EXISTS requirement_state (lead_id VARCHAR(255), workflow_id VARCHAR(255) DEFAULT 'default', transcript_context LONGTEXT, current_requirements LONGTEXT, current_scope_review LONGTEXT, updated_at VARCHAR(255), PRIMARY KEY (lead_id, workflow_id))")
        c.execute("CREATE TABLE IF NOT EXISTS requirement_events (id INTEGER PRIMARY KEY AUTO_INCREMENT, lead_id VARCHAR(255), workflow_id VARCHAR(255) DEFAULT 'default', event_type VARCHAR(255), transcript LONGTEXT, input_payload LONGTEXT, requirements LONGTEXT, scope_review LONGTEXT, at VARCHAR(255))")
        
        # Specialized artifacts for Doc Agent persistence
        c.execute("""CREATE TABLE IF NOT EXISTS doc_agent_artifacts (
            id VARCHAR(255) PRIMARY KEY,
            lead_id VARCHAR(255) NOT NULL,
            workflow_id VARCHAR(255) NOT NULL,
            version INT DEFAULT 1,
            project_summary TEXT,
            hld_content LONGTEXT,
            lld_content LONGTEXT,
            db_schema LONGTEXT,
            backlog LONGTEXT,
            ia_content LONGTEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_doc_agent_lead_flow (lead_id, workflow_id)
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS sprint_task_artifacts (
            id VARCHAR(255) PRIMARY KEY,
            project_id VARCHAR(255) NOT NULL,
            workflow_id VARCHAR(255) NOT NULL,
            workflow_name TEXT,
            session_version INT DEFAULT 1,
            session_title TEXT,
            generated_tasks LONGTEXT,
            task_comments LONGTEXT,
            task_logs LONGTEXT,
            board_state LONGTEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_sprint_tasks_project_workflow (project_id, workflow_id)
        )""")
        
        # Migration: Add project_summary if it's an older table version
        try:
            c.execute("ALTER TABLE doc_agent_artifacts ADD COLUMN project_summary TEXT AFTER version")
        except:
            pass # Column already exists

        # Migration: Add ia_content for IA blueprints on older deployments
        try:
            c.execute("ALTER TABLE doc_agent_artifacts ADD COLUMN ia_content LONGTEXT AFTER backlog")
        except:
            pass # Column already exists



        # Main project/auth tables
        c.execute("""CREATE TABLE IF NOT EXISTS auth_accounts (
            id CHAR(36) PRIMARY KEY, user_id CHAR(36), provider VARCHAR(50), provider_user_id VARCHAR(255),
            access_token TEXT, refresh_token TEXT, expires_at DATETIME, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_auth_accounts_user (user_id), INDEX idx_auth_accounts_provider_user (provider, provider_user_id)
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS projects (
            id CHAR(36) PRIMARY KEY, name VARCHAR(255), lead_id CHAR(36), current_stage VARCHAR(50),
            health_status VARCHAR(50), progress_percentage INT DEFAULT 0, created_by CHAR(36),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_projects_lead (lead_id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS lead_sources (
            id CHAR(36) PRIMARY KEY, lead_id CHAR(36), source_type VARCHAR(50), file_url TEXT, content LONGTEXT,
            title VARCHAR(255), email_subject VARCHAR(255), email_from VARCHAR(255), email_to VARCHAR(255),
            email_date DATETIME, email_thread_id VARCHAR(255), uploaded_by CHAR(36),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, INDEX idx_lead_sources_lead (lead_id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS lead_embeddings (
            id CHAR(36) PRIMARY KEY, lead_id CHAR(36), source_id CHAR(36), chunk_text LONGTEXT,
            embedding LONGTEXT, chunk_index INT, metadata LONGTEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_lead_embeddings_lead (lead_id), INDEX idx_lead_embeddings_source (source_id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS chat_threads (
            id CHAR(36) PRIMARY KEY, lead_id CHAR(36), user_id CHAR(36), title VARCHAR(255),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, INDEX idx_chat_threads_lead (lead_id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
            id CHAR(36) PRIMARY KEY, thread_id CHAR(36), sender_type VARCHAR(50), user_id CHAR(36),
            message LONGTEXT, retrieved_chunks LONGTEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_chat_messages_thread (thread_id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS workflows (
            id CHAR(36) PRIMARY KEY, project_id CHAR(36), type VARCHAR(20), nodes LONGTEXT,
            client_approved TINYINT(1) DEFAULT 0, version INT DEFAULT 1, generated_by_agent TINYINT(1) DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_workflows_project (project_id, version)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS requirements (
            id VARCHAR(50) PRIMARY KEY, project_id CHAR(36), story_text LONGTEXT, status VARCHAR(50),
            source_context LONGTEXT, created_by CHAR(36), ai_generated TINYINT(1) DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_requirements_project (project_id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS acceptance_criteria (
            id CHAR(36) PRIMARY KEY, requirement_id VARCHAR(50), criteria_text LONGTEXT,
            is_mandatory TINYINT(1) DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_acceptance_requirement (requirement_id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS test_cases (
            id VARCHAR(50), 
            project_id CHAR(36),
            requirement_id VARCHAR(50), 
            workflow_id VARCHAR(255), 
            title VARCHAR(255), 
            description LONGTEXT,
            type VARCHAR(50), 
            status VARCHAR(50), 
            test_steps LONGTEXT, 
            expected_result LONGTEXT,
            ai_generated TINYINT(1) DEFAULT 1, 
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (project_id, workflow_id, id),
            INDEX idx_test_cases_requirement (requirement_id),
            INDEX idx_test_cases_project (project_id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS deployment_artifacts (
            id VARCHAR(255) PRIMARY KEY,
            lead_id VARCHAR(255) NOT NULL,
            workflow_id VARCHAR(255) NOT NULL,
            dockerfile LONGTEXT,
            docker_compose LONGTEXT,
            env_template TEXT,
            deploy_script LONGTEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_deploy_lead (lead_id),
            INDEX idx_deploy_workflow (workflow_id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS ui_artifacts (
            id VARCHAR(255) PRIMARY KEY,
            project_id VARCHAR(255) NOT NULL,
            workflow_id VARCHAR(255) NOT NULL,
            session_version INT DEFAULT 1,
            ui_code LONGTEXT,
            stitch_project_id VARCHAR(255),
            stitch_screen_id VARCHAR(255),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_ui_artifacts_project_workflow (project_id, workflow_id, session_version)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id VARCHAR(50), 
            project_id CHAR(36), 
            requirement_id VARCHAR(50), 
            title VARCHAR(255),
            description LONGTEXT, 
            status VARCHAR(50), 
            assignee_id CHAR(36), 
            effort_estimate_hours INT,
            priority VARCHAR(50), 
            ai_generated TINYINT(1) DEFAULT 1, 
            last_updated_via VARCHAR(255),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, 
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            design_doc_id CHAR(36), 
            workflow_id VARCHAR(255),
            PRIMARY KEY (id, project_id, workflow_id),
            INDEX idx_tasks_project (project_id), 
            INDEX idx_tasks_requirement (requirement_id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS design_documents (
            id CHAR(36) PRIMARY KEY, project_id CHAR(36), doc_type VARCHAR(50), title VARCHAR(255),
            content LONGTEXT, tech_stack LONGTEXT, version INT DEFAULT 1, generated_by_agent TINYINT(1) DEFAULT 1,
            created_by CHAR(36), created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, INDEX idx_design_documents_project (project_id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS project_resources (
            id CHAR(36) PRIMARY KEY, project_id CHAR(36), user_id CHAR(36), allocation_percentage INT DEFAULT 0,
            role_in_project VARCHAR(100), assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_project_resources_project (project_id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS agent_logs (
            id CHAR(36) PRIMARY KEY, project_id CHAR(36), lead_id CHAR(36), agent_type VARCHAR(100),
            action_taken VARCHAR(255), status VARCHAR(50), payload LONGTEXT, error_message TEXT,
            triggered_by CHAR(36), created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_agent_logs_project (project_id), INDEX idx_agent_logs_lead (lead_id)
        )""")

        # Auto-Migration for columns
        migrations = [
            ("leads", "poc", "TEXT"),
            ("leads", "industry", "TEXT"),
            ("leads", "company_size", "TEXT"),
            ("leads", "lead_info", "LONGTEXT"),
            ("leads", "status", "TEXT"),
            ("leads", "project_stage", "TEXT"),
            ("leads", "project_scope", "LONGTEXT"),
            ("leads", "scope_source", "TEXT"),
            ("leads", "scope_updated_at", "TEXT"),
            ("leads", "ceo", "TEXT"),
            ("leads", "vector_index", "LONGBLOB"),
            ("leads", "at", "VARCHAR(255)"),
            ("leads", "company_id", "VARCHAR(255)"),
            ("ui_artifacts", "stitch_project_id", "VARCHAR(255)"),
            ("ui_artifacts", "stitch_screen_id", "VARCHAR(255)"),
            ("ui_artifacts", "updated_at", "DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            ("companies", "ceo", "TEXT"),
            ("requirement_state", "workflow_id", "VARCHAR(255) DEFAULT 'default' AFTER lead_id"),
            ("requirement_events", "workflow_id", "VARCHAR(255) DEFAULT 'default' AFTER lead_id"),
            ("leads", "lead_name", "VARCHAR(255)"),
            ("leads", "contact_person", "VARCHAR(255)"),
            ("leads", "company_name", "VARCHAR(255)"),

            ("leads", "company_domain", "VARCHAR(255)"),
            ("leads", "company_field", "VARCHAR(255)"),
            ("leads", "company_brief", "TEXT"),
            ("leads", "lead_stage", "VARCHAR(50)"),
            ("leads", "created_by", "CHAR(36)"),
            ("leads", "created_at", "DATETIME"),
            ("leads", "updated_at", "DATETIME"),
            ("leads", "converted_to_project", "TINYINT(1)"),
            ("test_cases", "workflow_id", "VARCHAR(255) AFTER requirement_id"),
            ("requirements", "workflow_id", "VARCHAR(255) AFTER project_id"),
            # Task & Sprint Engine — new columns for DB persistence
            ("test_cases", "project_id", "CHAR(36) AFTER id"),
            ("tasks", "workflow_id",  "VARCHAR(255) DEFAULT '' AFTER project_id"),
            ("tasks", "sprint_label", "VARCHAR(100) DEFAULT 'Sprint 1' AFTER priority"),
            ("tasks", "story",        "TEXT AFTER sprint_label"),
            ("tasks", "user_story",   "LONGTEXT AFTER story"),
        ]
        for table, col, type_str in migrations:
            try: c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {type_str}")
            except: pass
            
        # Composite primary key for requirement_state
        try:
            c.execute("ALTER TABLE requirement_state DROP PRIMARY KEY")
            c.execute("ALTER TABLE requirement_state ADD PRIMARY KEY (lead_id, workflow_id)")
        except:
            pass

        # Composite primary key for tasks (project_id, workflow_id, id)
        try:
            c.execute("SHOW KEYS FROM tasks WHERE Key_name = 'PRIMARY'")
            pk_info = c.fetchall()
            # If the current PK is just 'id' (one column), upgrade it
            if len(pk_info) == 1:
                print("Migrating: Upgrading tasks table to composite primary key (project_id, workflow_id, id)...")
                c.execute("ALTER TABLE tasks DROP PRIMARY KEY")
                c.execute("ALTER TABLE tasks ADD PRIMARY KEY (project_id, workflow_id, id)")
        except Exception as e:
            print(f"Tasks Migration error: {e}")

        # Cleanup orphans: Remove test cases with missing project_id or workflow_id
        try:
            c.execute("DELETE FROM test_cases WHERE project_id IS NULL OR project_id = '' OR project_id = 'null'")
        except:
            pass

        c.execute("UPDATE history SET thread_id = 'default' WHERE thread_id IS NULL")
        c.execute("UPDATE leads SET status = 'new' WHERE status IS NULL OR status = ''")
        c.execute("UPDATE leads SET project_stage = 'lead_pipeline' WHERE project_stage IS NULL OR project_stage = ''")

        conn.commit()
        c.close()
        conn.close()
    except Error as e:
        print(f"DB Init Error: {e}")

init_db()

def load_sources(lead_id=None):
    db = get_db()
    c = db.cursor(dictionary=True)
    try:
        if lead_id:
            c.execute(
                """SELECT id, lead_id, COALESCE(title, file_url, source_type, '') AS name,
                          1 AS pages, 1 AS chunks, created_at AS at
                   FROM lead_sources
                   WHERE lead_id=%s
                   ORDER BY created_at DESC""",
                (lead_id,),
            )
        else:
            c.execute(
                """SELECT id, lead_id, COALESCE(title, file_url, source_type, '') AS name,
                          1 AS pages, 1 AS chunks, created_at AS at
                   FROM lead_sources
                   ORDER BY created_at DESC"""
            )
        return c.fetchall()
    finally:
        c.close()
        db.close()


def _strip_binary_fields(row):
    if not row:
        return row
    cleaned = dict(row)
    for key, value in list(cleaned.items()):
        if isinstance(value, (bytes, bytearray)):
            cleaned[key] = None
    return cleaned


def save_source_db(s):
    db = get_db()
    c = db.cursor()
    c.execute(
        """INSERT INTO lead_sources
           (id, lead_id, source_type, file_url, content, title, uploaded_by, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
           ON DUPLICATE KEY UPDATE
             source_type=VALUES(source_type),
             file_url=VALUES(file_url),
             content=VALUES(content),
             title=VALUES(title),
             uploaded_by=VALUES(uploaded_by)""",
        (
            s["id"],
            s["lead_id"],
            s.get("source_type") or "upload",
            s.get("file_url") or s.get("name"),
            s.get("content"),
            s.get("title") or s.get("name"),
            s.get("uploaded_by"),
            s.get("created_at") or s.get("at") or datetime.now(),
        ),
    )
    db.commit()
    c.close()
    db.close()

def load_lead_summaries(company_id=None):
    db = get_db()
    c = db.cursor(dictionary=True)
    query = """
        SELECT l.id, l.company_id, l.project_name, l.poc, l.at, l.status,
               l.project_stage,
               COALESCE(l.company_name, l.project_name, l.lead_name) as company,
               COALESCE(l.company_domain, '') as domain,
               COALESCE(l.company_field, l.industry, '') as industry,
               COALESCE(l.ceo, '') as ceo,
               l.company_size,
               l.lead_name, l.contact_person, l.company_name, l.company_domain,
               l.company_field, l.company_brief, l.lead_stage, l.created_by,
               l.created_at, l.updated_at, l.converted_to_project
        FROM leads l
    """
    try:
        if company_id:
            c.execute(query + " WHERE l.company_id=%s ORDER BY l.at DESC", (company_id,))
        else:
            c.execute(query + " ORDER BY l.at DESC")
        return [_strip_binary_fields(row) for row in c.fetchall()]
    finally:
        c.close()
        db.close()

def load_leads(company_id=None):
    return load_lead_summaries(company_id)

def get_lead_db(lid):
    db = get_db(); c = db.cursor(dictionary=True)
    c.execute("SELECT * FROM leads WHERE id=%s", (lid,))
    row = c.fetchone(); c.close(); db.close()
    if not row: return None
    row["company"] = row.get("company") or row.get("company_name") or row.get("project_name") or ""
    row["domain"] = row.get("domain") or row.get("company_domain") or ""
    row["industry"] = row.get("industry") or row.get("company_field") or ""
    row["poc"] = row.get("poc") or row.get("contact_person") or ""
    row["project_name"] = row.get("project_name") or row.get("lead_name") or row.get("company_name") or ""
    row["lead_stage"] = row.get("lead_stage") or row.get("project_stage")
    # Filter out binary data for safety and performance
    if "vector_index" in row: del row["vector_index"]
    for k, v in row.items():
        if isinstance(v, bytes): row[k] = v.decode('utf-8', errors='ignore')
    return row

def get_lead_summary_db(lid):
    db = get_db(); c = db.cursor(dictionary=True)
    c.execute(
        """SELECT l.id, l.company_id, l.project_name, l.poc, l.at, l.status,
                  l.project_stage,
                  COALESCE(l.company_name, l.project_name, l.lead_name) as company,
                  COALESCE(l.company_domain, '') as domain,
                  COALESCE(l.company_field, l.industry, '') as industry,
                  COALESCE(l.ceo, '') as ceo,
                  l.company_size,
                  l.lead_name, l.contact_person, l.company_name, l.company_domain,
                  l.company_field, l.company_brief, l.lead_stage, l.created_by,
                  l.created_at, l.updated_at, l.converted_to_project
           FROM leads l
           WHERE l.id=%s""",
        (lid,),
    )
    row = c.fetchone(); c.close(); db.close()
    if not row: return None
    return _strip_binary_fields(row)

def find_company_by_domain(domain):
    if not domain: return None
    db = get_db(); c = db.cursor(dictionary=True)
    clean_domain = domain.lower().strip().lstrip("www.").split("/")[0]
    c.execute(
        """SELECT company_id AS id, company_name AS name, company_domain AS domain,
                  company_field AS industry, ceo, contact_person AS poc, company_size,
                  company_brief AS notes, created_at AS at
           FROM leads
           WHERE LOWER(TRIM(LEADING 'www.' FROM company_domain)) = %s
           ORDER BY updated_at DESC, created_at DESC
           LIMIT 1""",
        (clean_domain,),
    )
    row = c.fetchone(); c.close(); db.close()
    return row

def save_company_db(data):
    conn = get_db(); c = conn.cursor()
    company_id = data.get('id', str(uuid.uuid4())[:8])

    c.execute(
        """INSERT INTO leads (
               id, company_id, project_name, lead_name, contact_person, company_name, company_domain,
               company_field, company_brief, company_size, ceo, lead_stage, status, created_at, updated_at, at
           )
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON DUPLICATE KEY UPDATE
             company_id=VALUES(company_id),
             company_name=VALUES(company_name),
             company_domain=VALUES(company_domain),
             company_field=VALUES(company_field),
             company_brief=VALUES(company_brief),
             company_size=COALESCE(NULLIF(VALUES(company_size), ''), company_size),
             ceo=COALESCE(NULLIF(VALUES(ceo), ''), ceo),
             contact_person=COALESCE(NULLIF(VALUES(contact_person), ''), contact_person),

             updated_at=VALUES(updated_at)""",
        (
            company_id,
            company_id,
            data.get('name', ''),
            data.get('name', ''),
            data.get('poc', ''),
            data.get('name', ''),
            (data.get('domain') or '').strip().lower(),
            data.get('industry', ''),
            data.get('notes', ''),
            data.get('company_size', 'Mid-Market'),
            data.get('ceo', ''),
            'company_directory',
            'company_directory',
            data.get('created_at') or datetime.now(),
            datetime.now(),
            data.get('at', datetime.now().isoformat()),
        ),
    )
    conn.commit(); c.close(); conn.close()
    return company_id

def save_lead_db(data):
    conn = get_db(); c = conn.cursor()
    lead_id = data.get('id', str(uuid.uuid4())[:12])
    company_id = data.get('company_id')
    existing_status = None
    existing_stage = None
    if data.get("id"):
        c.execute("SELECT status, project_stage FROM leads WHERE id=%s", (lead_id,))
        existing_row = c.fetchone()
        if existing_row:
            existing_status = existing_row[0]
            existing_stage = existing_row[1]

    status_value = data.get('status', existing_status if existing_status else 'new')
    stage_value = data.get('project_stage', existing_stage if existing_stage else 'lead_pipeline')
    now_value = data.get('created_at') or data.get('at') or datetime.now()
    company_name = data.get('company_name') or data.get('company') or ''
    company_domain = data.get('company_domain') or data.get('domain') or ''
    company_field = data.get('company_field') or data.get('industry') or ''
    company_brief = data.get('company_brief') or data.get('lead_info') or ''
    lead_name = data.get('lead_name') or data.get('project_name') or (f"Discovery: {company_name}" if company_name else lead_id)


    c.execute('''INSERT INTO leads (
                    id, company_id, project_name, poc, lead_info, status, project_stage, at,
                    lead_name, contact_person, company_name, company_domain, company_field, company_brief,
                    lead_stage, created_by, created_at, updated_at, converted_to_project
                 )
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                 ON DUPLICATE KEY UPDATE company_id=VALUES(company_id), project_name=VALUES(project_name), 
                 poc=VALUES(poc), lead_info=VALUES(lead_info), status=VALUES(status), project_stage=VALUES(project_stage),
                 lead_name=VALUES(lead_name), contact_person=VALUES(contact_person), company_name=VALUES(company_name),
                 company_domain=VALUES(company_domain), company_field=VALUES(company_field), company_brief=VALUES(company_brief),
                 lead_stage=VALUES(lead_stage), created_by=VALUES(created_by), updated_at=VALUES(updated_at),
                 converted_to_project=VALUES(converted_to_project)''',
              (lead_id, company_id, data.get('project_name',''), data.get('poc',''),
               data.get('lead_info',''), status_value, stage_value, data.get('at', datetime.now().isoformat()),
               lead_name, data.get('contact_person') or data.get('poc',''), company_name, company_domain,
               company_field, company_brief, data.get('lead_stage') or stage_value,
               data.get('created_by'), now_value, datetime.now(), int(bool(data.get('converted_to_project', False)))))
    conn.commit(); c.close(); conn.close()
    return lead_id

def save_project_scope_db(lead_id, project_scope, source_name=None):
    db = get_db(); c = db.cursor()
    c.execute("UPDATE leads SET project_scope=%s, scope_source=%s, scope_updated_at=%s WHERE id=%s",
              (json.dumps(project_scope) if project_scope else None, source_name, datetime.now().isoformat(), lead_id))
    db.commit(); c.close(); db.close()


def _decode_json_blob(raw_value, default=None):
    if raw_value in (None, ""):
        return default
    try:
        return json.loads(raw_value)
    except (TypeError, json.JSONDecodeError):
        return raw_value


def _upsert_project_record(cursor, project_id: str, lead_id: Optional[str] = None, stage: str = "workflow", name: str = ""):
    project_name = name or project_id
    progress = 25 if stage == "workflow" else 50 if stage == "requirements" else 0
    cursor.execute(
        """INSERT INTO projects
           (id, name, lead_id, current_stage, health_status, progress_percentage, created_by, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
           ON DUPLICATE KEY UPDATE
             name=VALUES(name),
             lead_id=COALESCE(VALUES(lead_id), lead_id),
             current_stage=VALUES(current_stage),
             progress_percentage=GREATEST(progress_percentage, VALUES(progress_percentage)),
             updated_at=NOW()""",
        (project_id, project_name[:255], lead_id, stage, "active", progress, None),
    )


def _write_design_document(cursor, project_id: str, doc_type: str, title: str, content, version: int = 1):
    cursor.execute(
        """INSERT INTO design_documents
           (id, project_id, doc_type, title, content, tech_stack, version, generated_by_agent, created_by, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
           ON DUPLICATE KEY UPDATE
             title=VALUES(title),
             content=VALUES(content),
             tech_stack=VALUES(tech_stack),
             version=VALUES(version),
             updated_at=NOW()""",
        (
            f"{project_id}_{doc_type}",
            project_id,
            doc_type[:50],
            title[:255],
            json.dumps(content) if not isinstance(content, str) else content,
            None,
            version,
            1,
            None,
        ),
    )


def _log_agent_entry(cursor, project_id: Optional[str], lead_id: Optional[str], agent_type: str, action_taken: str, payload=None, status: str = "success"):
    cursor.execute(
        """INSERT INTO agent_logs
           (id, project_id, lead_id, agent_type, action_taken, status, payload, error_message, triggered_by, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())""",
        (
            str(uuid.uuid4()),
            project_id,
            lead_id,
            agent_type[:100],
            action_taken[:255],
            status[:50],
            json.dumps(payload) if payload is not None else None,
            None,
            None,
        ),
    )


def _normalize_criteria_list(value):
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        items = []
        for entry in value:
            if isinstance(entry, str) and entry.strip():
                items.append(entry.strip())
            elif isinstance(entry, dict):
                text = entry.get("criteria_text") or entry.get("text") or entry.get("title")
                if text:
                    items.append(str(text).strip())
        return items
    return [str(value).strip()]


def _iter_requirement_entries(payload):
    if not payload:
        return []

    if isinstance(payload, list):
        return [{"workflow_id": None, "workflow_name": None, "epic_id": None, "epic_title": None, "requirement": item} for item in payload if isinstance(item, dict)]

    workflows = []
    if isinstance(payload, dict):
        if isinstance(payload.get("workflows"), list):
            workflows = payload["workflows"]
        elif isinstance(payload.get("requirements"), list):
            workflows = [{"workflow_id": payload.get("workflow_id"), "workflow_name": payload.get("workflow_name"), "requirements": payload.get("requirements")}]

    entries = []
    for workflow in workflows:
        workflow_id = workflow.get("workflow_id")
        workflow_name = workflow.get("workflow_name")
        epics = workflow.get("epics")
        if isinstance(epics, list) and epics:
            for epic in epics:
                for requirement in epic.get("requirements", []) or []:
                    if isinstance(requirement, dict):
                        entries.append({
                            "workflow_id": workflow_id,
                            "workflow_name": workflow_name,
                            "epic_id": epic.get("epic_id"),
                            "epic_title": epic.get("title"),
                            "requirement": requirement,
                        })
        else:
            for requirement in workflow.get("requirements", []) or []:
                if isinstance(requirement, dict):
                    entries.append({
                        "workflow_id": workflow_id,
                        "workflow_name": workflow_name,
                        "epic_id": None,
                        "epic_title": None,
                        "requirement": requirement,
                    })
    return entries


def _sync_requirements_to_relational(cursor, project_id: str, requirements_payload, scope_review_payload=None, workflow_session_version: Optional[int] = None):
    current_wf_id = str(workflow_session_version) if workflow_session_version else "default"
    
    # Only delete existing records for the SPECIFIC workflow/session being synced
    cursor.execute("SELECT id FROM requirements WHERE project_id=%s AND workflow_id=%s", (project_id, current_wf_id))
    existing_ids = [row[0] for row in cursor.fetchall()]
    for rid in existing_ids:
        cursor.execute("DELETE FROM acceptance_criteria WHERE requirement_id=%s", (rid,))
        cursor.execute("DELETE FROM test_cases WHERE requirement_id=%s", (rid,))
    cursor.execute("DELETE FROM requirements WHERE project_id=%s AND workflow_id=%s", (project_id, current_wf_id))

    entries = _iter_requirement_entries(requirements_payload)
    for index, entry in enumerate(entries, start=1):
        requirement = entry["requirement"]
        local_id = (
            requirement.get("requirement_id")
            or requirement.get("id")
            or f"REQ_{index}"
        )
        # Unique requirement_id across projects and sessions to prevent PK collisions
        unique_id = f"{project_id}_{current_wf_id}_{local_id}"[:50]

        story_text = (
            requirement.get("story_text")
            or requirement.get("user_story")
            or requirement.get("title")
            or requirement.get("description")
            or json.dumps(requirement)
        )
        source_context = {
            "workflow_id": entry["workflow_id"],
            "workflow_name": entry["workflow_name"],
            "epic_id": entry["epic_id"],
            "epic_title": entry["epic_title"],
            "workflow_session_version": workflow_session_version,
            "scope_review": scope_review_payload,
            "payload": requirement,
        }
        cursor.execute(
            """INSERT INTO requirements
               (id, project_id, workflow_id, story_text, status, source_context, created_by, ai_generated, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())""",
            (
                unique_id,
                project_id,
                current_wf_id,
                story_text,
                (requirement.get("status") or "draft")[:50],
                json.dumps(source_context),
                None,
                1,
            ),
        )

        requirement_id = unique_id # Use the unique one for children

        acceptance_items = _normalize_criteria_list(requirement.get("acceptance_criteria"))
        for criterion in acceptance_items:
            cursor.execute(
                """INSERT INTO acceptance_criteria
                   (id, requirement_id, criteria_text, is_mandatory, created_at)
                   VALUES (%s, %s, %s, %s, NOW())""",
                (str(uuid.uuid4()), requirement_id, criterion, 1),
            )

        for tc_index, test_case in enumerate(requirement.get("test_cases") or [], start=1):
            if not isinstance(test_case, dict):
                continue
            cursor.execute(
                """INSERT INTO test_cases
                   (id, requirement_id, title, description, type, status, test_steps, expected_result, ai_generated, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())""",
                (
                    (test_case.get("id") or f"{requirement_id}_TC_{tc_index}")[:50],
                    requirement_id,
                    test_case.get("title") or f"Test Case {tc_index}",
                    test_case.get("description") or "",
                    (test_case.get("type") or "functional")[:50],
                    (test_case.get("status") or "draft")[:50],
                    json.dumps(test_case.get("test_steps")) if test_case.get("test_steps") is not None else None,
                    test_case.get("expected_result") or "",
                    1,
                ),
            )


def _load_normalized_requirements_state_db(project_id: str, workflow_id: Optional[str] = None):
    db = get_db()
    c = db.cursor(dictionary=True)
    try:
        if workflow_id:
            # Strip "Session " if present to match DB format
            clean_wf_id = str(workflow_id).replace("Session ", "")
            c.execute(
                """SELECT id, story_text, status, source_context, updated_at
                   FROM requirements
                   WHERE project_id=%s AND workflow_id=%s
                   ORDER BY created_at ASC, id ASC""",
                (project_id, clean_wf_id),
            )
        else:
            c.execute(
                """SELECT id, story_text, status, source_context, updated_at
                   FROM requirements
                   WHERE project_id=%s
                   ORDER BY created_at ASC, id ASC""",
                (project_id,),
            )
        requirement_rows = c.fetchall()
        if not requirement_rows:
            return None

        # Fetch children only for the selected requirements
        req_ids = [r['id'] for r in requirement_rows]
        format_strings = ','.join(['%s'] * len(req_ids))
        
        c.execute(
            f"""SELECT requirement_id, criteria_text
               FROM acceptance_criteria
               WHERE requirement_id IN ({format_strings})
               ORDER BY created_at ASC""",
            tuple(req_ids),
        )
        criteria_rows = c.fetchall()

        c.execute(
            f"""SELECT id, requirement_id, title, description, type, status, test_steps, expected_result
               FROM test_cases
               WHERE requirement_id IN ({format_strings})
               ORDER BY created_at ASC, id ASC""",
            tuple(req_ids),
        )
        test_case_rows = c.fetchall()
    finally:
        c.close()
        db.close()

    criteria_by_requirement = {}
    for row in criteria_rows:
        criteria_by_requirement.setdefault(row["requirement_id"], []).append(row["criteria_text"])

    test_cases_by_requirement = {}
    for row in test_case_rows:
        steps = _decode_json_blob(row.get("test_steps"))
        test_cases_by_requirement.setdefault(row["requirement_id"], []).append(
            {
                "id": row["id"].split("_", 1)[-1] if "_" in row["id"] else row["id"],
                "title": row.get("title") or "",
                "description": row.get("description") or "",
                "type": row.get("type") or "",
                "status": row.get("status") or "",
                "test_steps": steps,
                "expected_result": row.get("expected_result") or "",
            }
        )

    workflows_by_id = {}
    latest_updated_at = None
    transcript_context = ""
    scope_review = None

    for row in requirement_rows:
        source_context = _decode_json_blob(row.get("source_context")) or {}
        workflow_session_version = source_context.get("workflow_session_version")
        workflow_id = workflow_session_version or source_context.get("workflow_id") or "WF-1"
        workflow_name = source_context.get("workflow_name") or f"Workflow {workflow_id}"
        epic_id = source_context.get("epic_id")
        epic_title = source_context.get("epic_title")

        workflow_entry = workflows_by_id.setdefault(
            workflow_id,
            {
                "workflow_id": workflow_id,
                "workflow_name": workflow_name,
                "workflow_summary": "",
                "epics": [],
            },
        )
        if epic_id:
            epic_entry = next((epic for epic in workflow_entry["epics"] if epic.get("epic_id") == epic_id), None)
            if not epic_entry:
                epic_entry = {"epic_id": epic_id, "title": epic_title or epic_id, "requirements": []}
                workflow_entry["epics"].append(epic_entry)
            requirement_list = epic_entry["requirements"]
        else:
            requirement_list = workflow_entry.setdefault("requirements", [])

        requirement_payload = {
            "requirement_id": row["id"],
            "title": row.get("story_text") or row["id"],
            "story_text": row.get("story_text") or "",
            "status": row.get("status") or "draft",
            "acceptance_criteria": criteria_by_requirement.get(row["id"], []),
            "test_cases": test_cases_by_requirement.get(row["id"], []),
        }
        requirement_list.append(requirement_payload)

        if not transcript_context:
            transcript_context = source_context.get("transcript") or source_context.get("transcript_context") or ""
        if scope_review is None and source_context.get("scope_review") is not None:
            scope_review = source_context.get("scope_review")
        row_updated_at = row.get("updated_at")
        if latest_updated_at is None or (row_updated_at and row_updated_at > latest_updated_at):
            latest_updated_at = row_updated_at

    requirements_payload = _collapse_requirement_workflows_payload({"workflows": list(workflows_by_id.values())}, transcript=transcript_context)
    return {
        "project_id": project_id,
        "workflow_session_version": workflow_id,
        "transcript_context": transcript_context,
        "current_requirements": requirements_payload,
        "current_scope_review": scope_review,
        "updated_at": latest_updated_at.isoformat() if hasattr(latest_updated_at, "isoformat") else latest_updated_at,
    }


def _load_normalized_requirement_events_db(project_id: str, lead_id: Optional[str] = None):
    db = get_db()
    c = db.cursor(dictionary=True)
    try:
        if lead_id:
            c.execute(
                """SELECT id, action_taken, payload, created_at
                   FROM agent_logs
                   WHERE project_id=%s OR lead_id=%s
                   ORDER BY created_at DESC""",
                (project_id, lead_id),
            )
        else:
            c.execute(
                """SELECT id, action_taken, payload, created_at
                   FROM agent_logs
                   WHERE project_id=%s
                   ORDER BY created_at DESC""",
                (project_id,),
            )
        rows = c.fetchall()
    finally:
        c.close()
        db.close()

    events = []
    seen_keys = set()
    for row in rows:
        payload = _decode_json_blob(row.get("payload")) or {}
        if not isinstance(payload, dict):
            continue
        if not {"requirements", "scope_review", "input_payload", "transcript"} & set(payload.keys()):
            continue
        payload_signature = json.dumps(
            {
                "event_type": row.get("action_taken") or "agent_log",
                "workflow_session_version": payload.get("workflow_session_version"),
                "transcript": payload.get("transcript") or "",
                "input_payload": payload.get("input_payload"),
                "requirements": payload.get("requirements"),
                "scope_review": payload.get("scope_review"),
            },
            sort_keys=True,
            default=str,
        )
        if payload_signature in seen_keys:
            continue
        seen_keys.add(payload_signature)
        events.append(
            {
                "id": row["id"],
                "project_id": project_id,
                "lead_id": lead_id,
                "event_type": row.get("action_taken") or "agent_log",
                "transcript": payload.get("transcript") or "",
                "input_payload": payload.get("input_payload"),
                "requirements": payload.get("requirements"),
                "scope_review": payload.get("scope_review"),
                "workflow_session_version": payload.get("workflow_session_version"),
                "at": row.get("created_at").isoformat() if hasattr(row.get("created_at"), "isoformat") else row.get("created_at"),
            }
        )
    return events


def _load_requirement_state_from_events_db(project_id: str, workflow_id: Optional[str] = None):
    requested = _normalize_workflow_snapshot_id(workflow_id)
    if not requested:
        return None

    events = _load_normalized_requirement_events_db(project_id)
    for event in events:
        event_version = _normalize_workflow_snapshot_id(
            event.get("workflow_session_version")
            or (event.get("input_payload") or {}).get("workflow_session_version")
        )
        if not event_version or event_version != requested:
            continue

        requirements = event.get("requirements")
        scope_review = event.get("scope_review")
        if not requirements:
            continue

        return {
            "workflow_id": requested,
            "workflow_session_version": requested,
            "transcript_context": event.get("transcript") or "",
            "current_requirements": requirements,
            "current_scope_review": scope_review,
            "updated_at": event.get("at") or "",
        }

    return None


def _get_project_id_for_lead_db(lead_id: str):
    db = get_db()
    c = db.cursor()
    try:
        c.execute(
            """SELECT id
               FROM projects
               WHERE lead_id=%s
               ORDER BY updated_at DESC
               LIMIT 1""",
            (lead_id,),
        )
        row = c.fetchone()
        return row[0] if row and row[0] else None
    finally:
        c.close()
        db.close()


def save_project_context_db(data):
    conn = get_db()
    c = conn.cursor()
    project_id = (data.get("project_id") or f"proj_{uuid.uuid4().hex[:12]}").strip()
    lead_id = (data.get("lead_id") or "").strip() or None
    source_files = data.get("source_files") or []
    raw_context = (data.get("raw_context") or "").strip()
    processed_context = (data.get("processed_context") or raw_context).strip()
    workflow_analysis = data.get("workflow_analysis")
    structured_workflow = data.get("structured_workflow")
    project_scope = data.get("project_scope")

    _upsert_project_record(c, project_id, lead_id=lead_id, stage="workflow", name=data.get("project_name") or project_id)
    _write_design_document(
        c,
        project_id,
        "project_context",
        f"Project Context {project_id}",
        {
            "source_files": source_files,
            "raw_context": raw_context,
            "processed_context": processed_context,
            "workflow_analysis": workflow_analysis,
            "structured_workflow": structured_workflow,
            "project_scope": project_scope,
        },
    )
    _log_agent_entry(c, project_id, lead_id, "workflow_agent", "save_project_context", {"source_files": source_files})
    conn.commit()
    c.close()
    conn.close()
    return project_id


def get_project_context_db(project_id):
    db = get_db()
    c = db.cursor(dictionary=True)
    try:
        c.execute("SELECT * FROM projects WHERE id=%s", (project_id,))
        project = c.fetchone()
        if not project:
            return None
        c.execute(
            """SELECT content, created_at, updated_at
               FROM design_documents
               WHERE project_id=%s AND doc_type=%s
               ORDER BY updated_at DESC
               LIMIT 1""",
            (project_id, "project_context"),
        )
        doc = c.fetchone()
    finally:
        c.close()
        db.close()

    payload = _decode_json_blob((doc or {}).get("content")) or {}
    created_at = (doc or {}).get("created_at") or project.get("created_at")
    updated_at = (doc or {}).get("updated_at") or project.get("updated_at")
    return {
        "project_id": project["id"],
        "lead_id": project.get("lead_id"),
        "source_files": payload.get("source_files") or [],
        "raw_context": payload.get("raw_context") or "",
        "processed_context": payload.get("processed_context") or payload.get("raw_context") or "",
        "workflow_analysis": payload.get("workflow_analysis"),
        "structured_workflow": payload.get("structured_workflow"),
        "project_scope": payload.get("project_scope"),
        "requirements_handoff": get_requirements_handoff_db(project["id"]),
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
    }


def get_workflow_session_detail_db(project_id, version):
    db = get_db(); c = db.cursor(dictionary=True)
    try:
        c.execute("""
            SELECT id, type, nodes, client_approved, version, created_at, updated_at
            FROM workflows 
            WHERE project_id = %s AND version = %s
        """, (project_id, version))
        rows = c.fetchall()
        
        # Format similar to get_latest_approved_workflow_artifact_db
        as_is = next((r['nodes'] for r in rows if r['type'] == 'as_is'), "")
        to_be = next((r['nodes'] for r in rows if r['type'] == 'to_be'), "")
        
        # Fetch raw transcript from design_documents if available
        c.execute("""
            SELECT content FROM design_documents 
            WHERE project_id = %s AND doc_type = 'workflow_context'
        """, (project_id,))
        doc = c.fetchone()
        doc_payload = _decode_json_blob((doc or {}).get("content")) if doc else {}
        
        return {
            "version": version,
            "as_is": as_is,
            "to_be": to_be,
            "raw_transcript": (doc_payload or {}).get("raw_transcript") or "",
            "session_title": (doc_payload or {}).get("session_title") or f"Session {version}"
        }
    finally: c.close(); db.close()



def get_latest_approved_workflow_artifact_db(project_id):
    db = get_db()
    c = db.cursor(dictionary=True)
    c.execute(
        """SELECT w.version, w.nodes
           FROM workflows w
           WHERE w.project_id=%s AND w.type='to_be' AND w.client_approved=TRUE
           ORDER BY w.version DESC
           LIMIT 1""",
        (project_id,),
    )
    row = c.fetchone()
    doc = None
    if row:
        c.execute(
            """SELECT content
               FROM design_documents
               WHERE project_id=%s AND doc_type=%s
               ORDER BY updated_at DESC
               LIMIT 1""",
            (project_id, f"workflow_session_v{row.get('version')}"),
        )
        doc = c.fetchone()
    c.close()
    db.close()
    if not row:
        return None
    doc_payload = _decode_json_blob((doc or {}).get("content")) if doc else {}
    return {
        "version": row.get("version"),
        "session_title": (doc_payload or {}).get("session_title") or "",
        "to_be": row.get("nodes") or "",
        "raw_transcript": (doc_payload or {}).get("raw_transcript") or "",
    }


def _load_workflow_session_artifact_db(project_id: str, version: int):
    db = get_db()
    c = db.cursor(dictionary=True)
    try:
        c.execute(
            """SELECT id, type, nodes, client_approved, version, created_at, updated_at
               FROM workflows
               WHERE project_id=%s AND version=%s
               ORDER BY type ASC""",
            (project_id, version),
        )
        rows = c.fetchall()
        if not rows:
            return None

        c.execute(
            """SELECT content, created_at, updated_at
               FROM design_documents
               WHERE project_id=%s AND doc_type=%s
               ORDER BY updated_at DESC
               LIMIT 1""",
            (project_id, f"workflow_session_v{version}"),
        )
        doc = c.fetchone()
    finally:
        c.close()
        db.close()

    doc_payload = _decode_json_blob((doc or {}).get("content")) if doc else {}
    session = {
        "project_id": project_id,
        "version": version,
        "session_title": (doc_payload or {}).get("session_title") or f"Session {version}",
        "raw_transcript": (doc_payload or {}).get("raw_transcript") or "",
        "as_is": "",
        "to_be": "",
        "client_approved": False,
    }

    for row in rows:
        if row.get("type") == "as_is":
            session["as_is"] = row.get("nodes") or ""
        elif row.get("type") == "to_be":
            session["to_be"] = row.get("nodes") or ""
        session["client_approved"] = session["client_approved"] or bool(row.get("client_approved"))

    if doc and doc.get("created_at"):
        session["created_at"] = doc["created_at"].isoformat() if hasattr(doc["created_at"], "isoformat") else doc["created_at"]
    if doc and doc.get("updated_at"):
        session["updated_at"] = doc["updated_at"].isoformat() if hasattr(doc["updated_at"], "isoformat") else doc["updated_at"]
    return session


def _save_requirements_handoff_bundle_db(cursor, project_id: str, lead_id: Optional[str], workflow_session: Optional[dict], requirements_state: Optional[dict]):
    payload = {
        "project_id": project_id,
        "lead_id": lead_id,
        "workflow_session": workflow_session or {},
        "requirements_state": requirements_state or {},
        "stored_at": datetime.now().isoformat(),
    }
    cursor.execute(
        """INSERT INTO design_documents
           (id, project_id, doc_type, title, content, tech_stack, version, generated_by_agent, created_by, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
           ON DUPLICATE KEY UPDATE
             title=VALUES(title),
             content=VALUES(content),
             version=VALUES(version),
             updated_at=NOW()""",
        (
            f"{project_id}_requirements_handoff",
            project_id,
            "requirements_handoff",
            f"Requirements Handoff {project_id}",
            json.dumps(payload),
            None,
            (workflow_session or {}).get("version") or 1,
            1,
            None,
        ),
    )


def upsert_sprint_task_artifact_db(
    project_id: str,
    workflow_id: str,
    workflow_name: Optional[str],
    session_version: int,
    session_title: Optional[str],
    generated_tasks,
    task_comments,
    task_logs,
    board_state,
):
    db = get_db()
    c = db.cursor()
    try:
        artifact_id = f"{project_id}_{workflow_id}_v{session_version}"
        c.execute(
            """INSERT INTO sprint_task_artifacts
               (id, project_id, workflow_id, workflow_name, session_version, session_title, generated_tasks, task_comments, task_logs, board_state, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
               ON DUPLICATE KEY UPDATE
                 workflow_name=VALUES(workflow_name),
                 session_title=VALUES(session_title),
                 generated_tasks=VALUES(generated_tasks),
                 task_comments=VALUES(task_comments),
                 task_logs=VALUES(task_logs),
                 board_state=VALUES(board_state),
                 updated_at=NOW()""",
            (
                artifact_id,
                project_id,
                workflow_id,
                workflow_name,
                session_version,
                session_title,
                json.dumps(generated_tasks, default=str),
                json.dumps(task_comments, default=str),
                json.dumps(task_logs, default=str),
                json.dumps(board_state, default=str),
            ),
        )
        db.commit()
        return artifact_id
    finally:
        c.close()
        db.close()


def get_sprint_task_artifact_db(project_id: str, workflow_id: str, session_version: int):
    db = get_db()
    c = db.cursor(dictionary=True)
    try:
        c.execute(
            """SELECT id, project_id, workflow_id, workflow_name, session_version, session_title,
                      generated_tasks, task_comments, task_logs, board_state, created_at, updated_at
               FROM sprint_task_artifacts
               WHERE project_id=%s AND workflow_id=%s AND session_version=%s
               ORDER BY updated_at DESC
               LIMIT 1""",
            (project_id, workflow_id, session_version),
        )
        row = c.fetchone()
        if not row:
            return None
        return {
            "id": row.get("id"),
            "project_id": row.get("project_id"),
            "workflow_id": row.get("workflow_id"),
            "workflow_name": row.get("workflow_name"),
            "session_version": row.get("session_version"),
            "session_title": row.get("session_title"),
            "generated_tasks": _decode_json_blob(row.get("generated_tasks")) or [],
            "task_comments": _decode_json_blob(row.get("task_comments")) or {},
            "task_logs": _decode_json_blob(row.get("task_logs")) or {},
            "board_state": _decode_json_blob(row.get("board_state")) or {},
            "created_at": row["created_at"].isoformat() if hasattr(row.get("created_at"), "isoformat") else row.get("created_at"),
            "updated_at": row["updated_at"].isoformat() if hasattr(row.get("updated_at"), "isoformat") else row.get("updated_at"),
        }
    finally:
        c.close()
        db.close()


def get_requirements_handoff_db(project_id: str):
    db = get_db()
    c = db.cursor(dictionary=True)
    try:
        c.execute(
            """SELECT content, created_at, updated_at
               FROM design_documents
               WHERE project_id=%s AND doc_type=%s
               ORDER BY updated_at DESC
               LIMIT 1""",
            (project_id, "requirements_handoff"),
        )
        row = c.fetchone()
    finally:
        c.close()
        db.close()

    if not row:
        return None
    payload = _decode_json_blob(row.get("content")) or {}
    return {
        "project_id": project_id,
        "workflow_session": payload.get("workflow_session") or {},
        "requirements_state": payload.get("requirements_state") or {},
        "stored_at": payload.get("stored_at") or (
            row["created_at"].isoformat() if hasattr(row.get("created_at"), "isoformat") else row.get("created_at")
        ),
        "updated_at": row["updated_at"].isoformat() if hasattr(row.get("updated_at"), "isoformat") else row.get("updated_at"),
    }


def get_project_artifacts_db(project_id: str, doc_type: Optional[str] = None):
    db = get_db()
    c = db.cursor(dictionary=True)
    try:
        if doc_type:
            c.execute(
                """SELECT id, project_id, doc_type, title, version, created_at, updated_at
                   FROM design_documents
                   WHERE project_id=%s AND doc_type=%s
                   ORDER BY updated_at DESC""",
                (project_id, doc_type),
            )
        else:
            c.execute(
                """SELECT id, project_id, doc_type, title, version, created_at, updated_at
                   FROM design_documents
                   WHERE project_id=%s
                   ORDER BY updated_at DESC""",
                (project_id,),
            )
        rows = c.fetchall()
        for row in rows:
            if row.get("created_at"):
                row["created_at"] = row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"]
            if row.get("updated_at"):
                row["updated_at"] = row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else row["updated_at"]
        return rows
    finally:
        c.close()
        db.close()


def save_requirements_handoff_db(project_id: str, lead_id: Optional[str], workflow_session: Optional[dict], requirements_state: Optional[dict]):
    db = get_db()
    c = db.cursor()
    try:
        _save_requirements_handoff_bundle_db(c, project_id, lead_id, workflow_session, requirements_state)
        db.commit()
    finally:
        c.close()
        db.close()

def load_companies():
    all_leads = load_lead_summaries()
    companies = {}

    for lead in all_leads:
        company_id = lead.get("company_id") or lead.get("id")
        company_name = lead.get("company_name") or lead.get("company") or lead.get("project_name") or "Unknown Company"
        company_entry = companies.setdefault(
            company_id,
            {
                "id": company_id,
                "name": company_name,
                "domain": lead.get("company_domain") or lead.get("domain") or "",
                "industry": lead.get("company_field") or lead.get("industry") or "",
                "ceo": lead.get("ceo") or "",
                "poc": lead.get("contact_person") or lead.get("poc") or "",
                "company_size": lead.get("company_size") or "",
                "notes": lead.get("company_brief") or "",
                "at": lead.get("created_at") or lead.get("at"),
                "leads": [],
            },
        )
        # Coalesce metadata: If the current entry has empty fields, try to fill them from this lead
        if not company_entry.get("ceo") and lead.get("ceo"):
            company_entry["ceo"] = lead.get("ceo")
        if not company_entry.get("industry") and (lead.get("company_field") or lead.get("industry")):
            company_entry["industry"] = lead.get("company_field") or lead.get("industry")
        if not company_entry.get("company_size") and lead.get("company_size"):
            company_entry["company_size"] = lead.get("company_size")
        if not company_entry.get("poc") and (lead.get("contact_person") or lead.get("poc")):
            company_entry["poc"] = lead.get("contact_person") or lead.get("poc")
        if not company_entry.get("notes") and lead.get("company_brief"):
            company_entry["notes"] = lead.get("company_brief")

        if lead.get("status") != 'company_directory':
            company_entry["leads"].append(lead)


    return list(companies.values())

def delete_company_db(cid):
    db = get_db(); c = db.cursor(); c.execute("SELECT id FROM leads WHERE company_id=%s", (cid,))
    lead_ids = [r[0] for r in c.fetchall()]
    for lid in lead_ids:
        c.execute("DELETE FROM chat_messages WHERE thread_id=%s", (_chat_thread_storage_id(lid, 'default'),))
        c.execute("DELETE FROM chat_threads WHERE lead_id=%s", (lid,))
        c.execute("DELETE FROM lead_sources WHERE lead_id=%s", (lid,))
        c.execute("DELETE FROM lead_embeddings WHERE lead_id=%s", (lid,))
        c.execute("DELETE FROM workflows WHERE project_id IN (SELECT id FROM projects WHERE lead_id=%s)", (lid,))
        c.execute("DELETE FROM requirements WHERE project_id IN (SELECT id FROM projects WHERE lead_id=%s)", (lid,))
        c.execute("DELETE FROM design_documents WHERE project_id IN (SELECT id FROM projects WHERE lead_id=%s)", (lid,))
        c.execute("DELETE FROM projects WHERE lead_id=%s", (lid,))
        c.execute("DELETE FROM agent_logs WHERE lead_id=%s", (lid,))
        c.execute("DELETE FROM leads WHERE id=%s", (lid,))
    db.commit(); c.close(); db.close()


def append_context_to_lead(lead_id: str, context_text: str, source_name: str = "Intake Context") -> dict:
    text = (context_text or "").strip()
    if not lead_id or not text:
        return {"status": "skipped", "lead_id": lead_id, "context_added": False}

    existing_lead = get_lead_db(lead_id)
    if not existing_lead:
        return {"status": "missing", "lead_id": lead_id, "context_added": False}

    existing_info = (existing_lead.get("lead_info") or "").strip()
    timestamp = datetime.now().isoformat()
    entry = f"[{timestamp}] {source_name}\n{text}".strip()

    if entry in existing_info or text in existing_info:
        return {"status": "stored", "lead_id": lead_id, "context_added": False}

    updated_info = f"{existing_info}\n\n{entry}".strip() if existing_info else entry

    db = get_db()
    c = db.cursor()
    c.execute("UPDATE leads SET lead_info=%s WHERE id=%s", (updated_info, lead_id))
    db.commit()
    c.close()
    db.close()

    return {"status": "stored", "lead_id": lead_id, "context_added": True}


def build_project_scope_snapshot(requirements, scope_review, transcript_context="", source_name=None):
    workflows = (requirements or {}).get("workflows", [])
    scope_workflows = (scope_review or {}).get("workflows", [])
    scope_counts = {
        "MUST_HAVE": 0,
        "SHOULD_HAVE": 0,
        "FUTURE_SCOPE": 0,
        "OUT_OF_SCOPE": 0,
    }

    scope_index = {}
    for workflow in scope_workflows:
        workflow_id = workflow.get("workflow_id")
        scope_index[workflow_id] = workflow.get("requirements", [])
        for item in workflow.get("requirements", []):
            scope = (item.get("scope") or "").strip().upper()
            if scope in scope_counts:
                scope_counts[scope] += 1

    summarized_workflows = []
    for workflow in workflows:
        workflow_id = workflow.get("workflow_id")
        epics = workflow.get("epics", [])
        requirement_total = sum(len(epic.get("requirements", [])) for epic in epics)
        scoped_items = scope_index.get(workflow_id, [])
        must_have_titles = [
            item.get("title")
            for item in scoped_items
            if (item.get("scope") or "").strip().upper() == "MUST_HAVE" and item.get("title")
        ]
        summarized_workflows.append(
            {
                "workflow_id": workflow_id,
                "workflow_name": workflow.get("workflow_name"),
                "workflow_summary": workflow.get("workflow_summary"),
                "requirement_count": requirement_total,
                "must_have_titles": must_have_titles,
            }
        )

    return {
        "summary": {
            "workflow_count": len(workflows),
            "requirement_count": sum(item["requirement_count"] for item in summarized_workflows),
            "scope_breakdown": scope_counts,
        },
        "workflows": summarized_workflows,
        "source_name": source_name,
        "transcript_excerpt": (transcript_context or "")[:1500],
        "stored_at": datetime.now().isoformat(),
    }




def mark_lead_accepted(lid):
    db = get_db()
    c = db.cursor()
    c.execute("UPDATE leads SET status=%s, project_stage=%s WHERE id=%s", ("accepted", "requirements", lid))
    db.commit()
    c.close()
    db.close()
    return get_lead_db(lid)


def can_trigger_requirement_generation(
    lead: dict,
    project_start_confirmed: bool,
    allow_unaccepted_workflow: bool = False,
):
    if not lead:
        return False, "Lead not found"
    status = (lead.get("status") or "").strip().lower()
    stage = (lead.get("project_stage") or "").strip().lower()
    # Backward compatibility: older UI used "launched" to denote accepted leads.
    is_accepted = status in {"accepted", "launched"} or stage == "requirements"
    if not is_accepted and not allow_unaccepted_workflow:
        return False, "Lead must be accepted before requirement generation."
    if not project_start_confirmed:
        return False, "Project start confirmation is required to trigger requirement generation."
    return True, None


def _chat_thread_storage_id(lead_id: str, thread_id: Optional[str]) -> str:
    tid = (thread_id or "default").strip() or "default"
    if tid == "default":
        return f"default:{lead_id}"
    return tid

def delete_lead_db(lid):
    db = get_db(); c = db.cursor()
    try:
        # Full purge of all associated data
        c.execute("DELETE FROM chat_messages WHERE thread_id=%s", (_chat_thread_storage_id(lid, 'default'),))
        c.execute("DELETE FROM chat_threads WHERE lead_id=%s", (lid,))
        c.execute("DELETE FROM lead_sources WHERE lead_id=%s", (lid,))
        c.execute("DELETE FROM lead_embeddings WHERE lead_id=%s", (lid,))
        c.execute("DELETE FROM workflows WHERE project_id IN (SELECT id FROM projects WHERE lead_id=%s)", (lid,))
        c.execute("DELETE FROM requirements WHERE project_id IN (SELECT id FROM projects WHERE lead_id=%s)", (lid,))
        c.execute("DELETE FROM design_documents WHERE project_id IN (SELECT id FROM projects WHERE lead_id=%s)", (lid,))
        c.execute("DELETE FROM projects WHERE lead_id=%s", (lid,))
        c.execute("DELETE FROM agent_logs WHERE lead_id=%s", (lid,))
        c.execute("DELETE FROM leads WHERE id=%s", (lid,))
        db.commit()
    finally: c.close(); db.close()

def save_history_db(h):
    db = get_db(); c = db.cursor()
    c.execute(
        """INSERT INTO chat_messages (id, thread_id, sender_type, user_id, message, retrieved_chunks, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (
            str(uuid.uuid4()),
            _chat_thread_storage_id(h.get("lead_id"), h.get("thread_id", "default")),
            h.get("role", "assistant"),
            h.get("user_id"),
            h.get("text", ""),
            json.dumps(h.get("sources", [])),
            datetime.now(),
        ),
    )
    db.commit(); c.close(); db.close()

def save_thread_db(t):
    db = get_db(); c = db.cursor()
    c.execute(
        """REPLACE INTO chat_threads (id, lead_id, user_id, title, created_at)
           VALUES (%s,%s,%s,%s,%s)""",
        (_chat_thread_storage_id(t['lead_id'], t['id']), t['lead_id'], t.get('user_id'), t['title'], t.get('at', datetime.now())),
    )
    db.commit(); c.close(); db.close()


def get_requirement_state_db(lid, workflow_id=None):
    db = get_db()
    c = db.cursor(dictionary=True)
    
    row = None
    # 1. Try specific workflow_id when the caller asked for one.
    if workflow_id:
        c.execute("SELECT * FROM requirement_state WHERE lead_id=%s AND workflow_id=%s", (lid, workflow_id))
        row = c.fetchone()

        # If "Session X" is passed but stored as "X" (or vice versa), try the alternate key.
        if not row:
            alt_id = None
            if "Session " in str(workflow_id):
                alt_id = str(workflow_id).replace("Session ", "")
            else:
                alt_id = f"Session {workflow_id}"

            if alt_id:
                c.execute("SELECT * FROM requirement_state WHERE lead_id=%s AND workflow_id=%s", (lid, alt_id))
                row = c.fetchone()
    else:
        # When no workflow is requested, "latest" should mean the most recent snapshot
        c.execute("SELECT * FROM requirement_state WHERE lead_id=%s ORDER BY updated_at DESC LIMIT 1", (lid,))
        row = c.fetchone()

    if row:
        # Normalize the DB row into the standard state dictionary format
        return {
            "lead_id": row.get("lead_id"),
            "workflow_id": row.get("workflow_id"),
            "workflow_session_version": row.get("workflow_id"),
            "transcript_context": row.get("transcript_context") or "",
            "current_requirements": _decode_json_blob(row.get("current_requirements")),
            "current_scope_review": _decode_json_blob(row.get("current_scope_review")),
            "updated_at": row.get("updated_at").isoformat() if hasattr(row.get("updated_at"), "isoformat") else row.get("updated_at"),
        }
    
    return None



def get_project_requirement_state_db(project_id):
    return _load_normalized_requirements_state_db(project_id)


def _normalize_workflow_snapshot_id(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith("session "):
        return text[8:].strip()
    return text


def _handoff_matches_workflow_id(handoff: Optional[dict], workflow_id: Optional[str]) -> bool:
    if not handoff or not workflow_id:
        return False

    requested = _normalize_workflow_snapshot_id(workflow_id)
    if not requested:
        return False

    requirements_state = handoff.get("requirements_state") or {}
    workflow_session = handoff.get("workflow_session") or {}
    stored_version = requirements_state.get("workflow_session_version") or workflow_session.get("version")
    if stored_version is None:
        return False

    stored_key = _normalize_workflow_snapshot_id(stored_version)
    return requested == stored_key


def _split_sentences(text: str) -> List[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]


def _extract_grounded_detail_items(transcript: str, title: str, kind: str) -> List[str]:
    source_text = (transcript or "").strip()
    if not source_text:
        return []

    title_tokens = {
        token
        for token in re.findall(r"[A-Za-z0-9]+", (title or "").lower())
        if len(token) > 3
    }
    if kind == "input":
        keywords = {
            "input", "inputs", "ingest", "capture", "collect", "receive", "upload", "import",
            "source", "submission", "intake", "submitted", "provided", "from"
        }
    else:
        keywords = {
            "output", "outputs", "generate", "publish", "handoff", "deliver", "report",
            "result", "export", "return", "produce", "ready", "response"
        }

    scored = []
    for sentence in _split_sentences(source_text):
        lowered = sentence.lower()
        score = 0
        if any(keyword in lowered for keyword in keywords):
            score += 2
        score += sum(1 for token in title_tokens if token in lowered)
        if score > 0:
            scored.append((score, sentence))

    scored.sort(key=lambda item: (-item[0], item[1]))
    grounded = []
    seen = set()
    for _, sentence in scored:
        normalized = sentence.strip()
        if normalized and normalized not in seen:
            grounded.append(normalized)
            seen.add(normalized)
        if len(grounded) >= 3:
            break
    return grounded


def _normalize_requirement_entry(requirement: dict, workflow_name: str = "", epic_title: str = "", transcript: str = "") -> dict:
    normalized = dict(requirement or {})
    title = (normalized.get("title") or normalized.get("short_title") or normalized.get("req_id") or "Requirement").strip()
    description = (
        normalized.get("description")
        or normalized.get("requirement_description")
        or normalized.get("story_text")
        or normalized.get("summary")
        or ""
    ).strip()
    if not description:
        description = f"The system shall support {title.lower()} as part of {workflow_name or 'the workflow'}."
    elif not description.lower().startswith("the system shall"):
        description = f"The system shall {description[0].lower()}{description[1:]}" if len(description) > 1 else description

    inputs = normalized.get("inputs") or normalized.get("input") or normalized.get("source_inputs") or normalized.get("functional_details") or []
    outputs = normalized.get("outputs") or normalized.get("output") or normalized.get("deliverables") or normalized.get("expected_output") or []
    if isinstance(inputs, str):
        inputs = [inputs]
    if isinstance(outputs, str):
        outputs = [outputs]
    inputs = [str(item).strip() for item in inputs if str(item).strip()]
    outputs = [str(item).strip() for item in outputs if str(item).strip()]
    if not inputs:
        inputs = _extract_grounded_detail_items(transcript, title, "input")
    if not outputs:
        outputs = _extract_grounded_detail_items(transcript, title, "output")

    user_story = (normalized.get("user_story") or "").strip()
    if not user_story:
        actor = "user"
        context_bits = [bit for bit in [workflow_name.strip(), epic_title.strip()] if bit]
        context = " / ".join(context_bits) if context_bits else "the workflow"
        benefit = description[0].lower() + description[1:] if len(description) > 1 else description
        user_story = f"As a {actor} working in {context}, I want {title.lower()} so that {benefit}."

    normalized["title"] = title
    normalized["description"] = description
    normalized["requirement_description"] = description
    normalized["inputs"] = inputs
    normalized["outputs"] = outputs
    normalized["user_story"] = user_story
    if not normalized.get("functional_details") and (inputs or outputs):
        functional_details = []
        if inputs:
            functional_details.append(f"Input: {inputs[0]}")
        if outputs:
            functional_details.append(f"Output: {outputs[0]}")
        normalized["functional_details"] = functional_details
    return normalized


def _collapse_requirement_workflows_payload(requirements_payload, transcript: str = ""):
    workflows = []
    if isinstance(requirements_payload, dict):
        workflows = requirements_payload.get("workflows") or []
    elif isinstance(requirements_payload, list):
        workflows = requirements_payload

    workflows = [workflow for workflow in workflows if isinstance(workflow, dict)]
    if not workflows:
        return {"workflows": []}
    if len(workflows) == 1:
        single = dict(workflows[0])
        normalized_epics = []
        for epic_index, epic in enumerate(single.get("epics") or [], start=1):
            epic_payload = dict(epic or {})
            epic_payload["epic_id"] = epic_payload.get("epic_id") or f"EPIC-{epic_index}"
            epic_payload["title"] = epic_payload.get("title") or f"Epic {epic_index}"
            epic_payload["requirements"] = [
                _normalize_requirement_entry(
                    requirement,
                    single.get("workflow_name") or "",
                    epic_payload["title"],
                    transcript=transcript,
                )
                for requirement in epic_payload.get("requirements") or []
            ]
            normalized_epics.append(epic_payload)
        single["epics"] = normalized_epics
        return {"workflows": [single]}

    combined = dict(workflows[0])
    combined["workflow_id"] = "WF-1"
    combined["workflow_name"] = combined.get("workflow_name") or "Combined Workflow"
    combined["workflow_summary"] = combined.get("workflow_summary") or "Combined workflow synthesized from stored workflow sessions."
    combined["epics"] = []

    seen_requirements = 0
    for workflow in workflows:
        for epic in workflow.get("epics") or []:
            combined_epic = {
                **epic,
                "epic_id": f"EPIC-{len(combined['epics']) + 1}",
                "requirements": [],
            }
            for requirement in epic.get("requirements") or []:
                seen_requirements += 1
                combined_requirement = _normalize_requirement_entry(
                    requirement,
                    combined.get("workflow_name") or "",
                    epic.get("title") or "",
                    transcript=transcript,
                )
                combined_requirement["req_id"] = f"REQ-{seen_requirements}"
                combined_epic["requirements"].append(combined_requirement)
            combined["epics"].append(combined_epic)

    return {"workflows": [combined]}


def _build_scope_review_from_requirements_payload(requirements_payload):
    collapsed = _collapse_requirement_workflows_payload(requirements_payload)
    workflows = collapsed.get("workflows") or []
    review_workflows = []
    for workflow in workflows:
        review_workflows.append(
            {
                "workflow_id": workflow.get("workflow_id") or "WF-1",
                "requirements": [
                    {
                        "req_id": requirement.get("req_id") or "",
                        "title": requirement.get("title") or "",
                        "scope": "MUST_HAVE",
                        "priority": requirement.get("priority") or "high",
                        "action": "keep",
                        "reason": "Fast mode preserved the generated requirement as part of the approved workflow scope.",
                    }
                    for epic in workflow.get("epics") or []
                    for requirement in epic.get("requirements") or []
                ],
            }
        )
    return {"workflows": review_workflows}


def save_project_requirement_state_db(project_id, lead_id, transcript_context, requirements, scope_review, workflow_session_version: Optional[int] = None):
    db = get_db()
    c = db.cursor()
    _upsert_project_record(c, project_id, lead_id=lead_id, stage="requirements", name=project_id)
    _sync_requirements_to_relational(c, project_id, requirements, scope_review, workflow_session_version=workflow_session_version)
    _write_design_document(
        c,
        project_id,
        "requirements_context",
        f"Requirements Context {project_id}",
        {
            "transcript_context": transcript_context,
            "scope_review": scope_review,
            "workflow_session_version": workflow_session_version,
        },
    )
    db.commit()
    c.close()
    db.close()


def save_project_requirement_event_db(project_id, lead_id, event_type, transcript, input_payload, requirements, scope_review, workflow_session_version: Optional[int] = None):
    db = get_db()
    c = db.cursor()
    _log_agent_entry(
        c,
        project_id,
        lead_id,
        "requirements_agent",
        event_type,
        {
            "transcript": transcript,
            "input_payload": input_payload,
            "requirements": requirements,
            "scope_review": scope_review,
            "workflow_session_version": workflow_session_version,
        },
    )
    db.commit()
    c.close()
    db.close()


def load_project_requirement_events_db(project_id):
    return _load_normalized_requirement_events_db(project_id)


# Project-based state lookup (legacy or project-specific)
def get_requirement_state_by_project_db(lid):
    project_id = _get_project_id_for_lead_db(lid)
    return _load_normalized_requirements_state_db(project_id) if project_id else None


def save_requirement_state_db(lead_id, transcript_context, requirements, scope_review, workflow_id="default"):
    workflow_key = str(workflow_id or "default").strip() or "default"
    db = get_db()
    c = db.cursor()
    # Path A: Session-based storage (Head)
    c.execute(
        """REPLACE INTO requirement_state
           (lead_id, workflow_id, transcript_context, current_requirements, current_scope_review, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (
            lead_id,
            workflow_key,
            transcript_context,
            json.dumps(requirements),
            json.dumps(scope_review),
            datetime.now().isoformat(),
        ),
    )
    
    # Path B: Project-based storage (Incoming)
    project_id = _get_project_id_for_lead_db(lead_id) or lead_id
    save_project_requirement_state_db(project_id, lead_id, transcript_context, requirements, scope_review, workflow_session_version=workflow_key)
    
    db.commit()
    c.close()
    db.close()


def save_requirement_event_db(lead_id, event_type, transcript, input_payload, requirements, scope_review, workflow_id="default"):
    workflow_key = str(workflow_id or "default").strip() or "default"
    db = get_db()
    c = db.cursor()
    # Path A: Session-based events (Head)
    c.execute(
        """INSERT INTO requirement_events 
           (lead_id, workflow_id, event_type, transcript, input_payload, requirements, scope_review, at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            lead_id,
            workflow_key,
            event_type,
            transcript,
            json.dumps(input_payload),
            json.dumps(requirements),
            json.dumps(scope_review),
            datetime.now().isoformat(),
        ),
    )
    
    # Path B: Project-based events (Incoming)
    project_id = _get_project_id_for_lead_db(lead_id) or lead_id
    save_project_requirement_event_db(project_id, lead_id, event_type, transcript, input_payload, requirements, scope_review, workflow_session_version=workflow_key)
    
    db.commit()
    c.close()
    db.close()


def load_requirement_events_db(lid):
    project_id = _get_project_id_for_lead_db(lid)
    return _load_normalized_requirement_events_db(project_id, lid) if project_id else []


def merge_requirement_context(existing_context: str, new_context: str) -> str:
    existing = (existing_context or "").strip()
    new = (new_context or "").strip()
    if not existing:
        return new
    if not new:
        return existing
    if new in existing:
        return existing
    return f"{existing}\n\n{new}".strip()


def merge_generation_inputs(base_input: str, change_request: str = "") -> str:
    base_text = (base_input or "").strip()
    change_text = (change_request or "").strip()
    if not change_text:
        return base_text
    if not base_text:
        return change_text
    return (
        f"{base_text}\n\n"
        "CHANGE REQUEST / SCOPE UPDATES:\n"
        f"{change_text}"
    ).strip()


async def generate_requirements_from_project_context(project_id: str, payload: dict, expected_lead_id: Optional[str] = None):
    lock = _get_project_requirement_lock(project_id)
    async with lock:
        return await _generate_requirements_from_project_context_locked(project_id, payload, expected_lead_id)


async def _generate_requirements_from_project_context_locked(project_id: str, payload: dict, expected_lead_id: Optional[str] = None):
    project_context = await run_in_threadpool(get_project_context_db, project_id)
    if not project_context:
        return JSONResponse(status_code=404, content={"error": "Project context not found"})

    stored_lead_id = (project_context.get("lead_id") or "").strip() or None
    linked_lead_id = (expected_lead_id or stored_lead_id or "").strip() or None
    if expected_lead_id and stored_lead_id and expected_lead_id != stored_lead_id:
        return JSONResponse(status_code=400, content={"error": "project_id does not belong to the requested lead"})

    lead = None
    if linked_lead_id:
        lead = await run_in_threadpool(get_lead_db, linked_lead_id)
        if not lead:
            return JSONResponse(status_code=404, content={"error": "Linked lead not found"})

    requested_workflow_id = payload.get("workflow_id")
    if requested_workflow_id:
        try:
            workflow_artifact = await run_in_threadpool(get_workflow_session_detail_db, project_id, int(requested_workflow_id))
        except (ValueError, TypeError):
            workflow_artifact = await run_in_threadpool(get_latest_approved_workflow_artifact_db, project_id)
    else:
        workflow_artifact = await run_in_threadpool(get_latest_approved_workflow_artifact_db, project_id)



    project_start_confirmed = bool(payload.get("confirm_project_start"))
    if lead:
        can_trigger, trigger_error = can_trigger_requirement_generation(
            lead,
            project_start_confirmed,
            allow_unaccepted_workflow=bool(workflow_artifact),
        )
        if not can_trigger:
            return JSONResponse(status_code=400, content={"error": trigger_error})
    elif not project_start_confirmed:
        return JSONResponse(
            status_code=400,
            content={"error": "Project start confirmation is required to trigger requirement generation."},
        )

    forbidden_fields = []
    if (payload.get("transcript") or "").strip():
        forbidden_fields.append("transcript")
    if payload.get("structured_workflow") not in (None, "", {}):
        forbidden_fields.append("structured_workflow")
    if forbidden_fields:
        return JSONResponse(
            status_code=400,
            content={
                "error": (
                    "Step 2 no longer accepts raw input. "
                    f"Remove {', '.join(forbidden_fields)} and reuse the stored Step 1 context via project_id."
                )
            },
        )

    change_request = (payload.get("change_request") or "").strip()
    explicit_removal_requested = bool(re.search(r"\b(remove|delete|drop|exclude|eliminate)\b", change_request, flags=re.IGNORECASE))
    project_transcript_context = (project_context.get("processed_context") or project_context.get("raw_context") or "").strip()
    workflow_transcript_context = (workflow_artifact or {}).get("raw_transcript", "").strip()
    base_transcript_context = project_transcript_context or workflow_transcript_context
    structured_workflow = (workflow_artifact or {}).get("to_be") or project_context.get("structured_workflow")

    transcript_context = merge_generation_inputs(base_transcript_context, change_request)
    if not transcript_context and not structured_workflow:
        return JSONResponse(status_code=400, content={"error": "No reusable Step 1 context is stored for this project"})

    existing_handoff = await run_in_threadpool(get_requirements_handoff_db, project_id)
    existing_state = (existing_handoff or {}).get("requirements_state") or {}
    existing_workflow_version = str(existing_state.get("workflow_session_version") or "")
    existing_transcript_context = (existing_state.get("transcript_context") or "").strip()
    existing_updated_at = (existing_handoff or {}).get("stored_at") or ""
    same_generation_input = (
        existing_workflow_version == str((workflow_artifact or {}).get("version") or "")
        and existing_transcript_context
        and existing_transcript_context == transcript_context
    )
    if same_generation_input and existing_updated_at:
        return {
            "status": "ok",
            "project_id": project_id,
            "lead": lead,
            "source_files": project_context.get("source_files") or [],
            "transcript": transcript_context,
            "requirements": existing_state.get("current_requirements"),
            "workflow_validation": None,
            "scope_review": existing_state.get("current_scope_review"),
            "project_scope": existing_state.get("project_scope"),
            "duplicate": True,
        }

    try:
        req_module = get_req_generation_module()
        generated_requirements = await run_in_threadpool(
            lambda: req_module.generate_requirements(
                transcript_context, structured_workflow=structured_workflow
            )
        )
        workflow_validation = None
        workflow_session_version = (workflow_artifact or {}).get("version")

        if REQ_FAST_MODE:
            scope_review = _build_scope_review_from_requirements_payload(generated_requirements)
            requirements = _collapse_requirement_workflows_payload(generated_requirements, transcript=transcript_context)
        else:
            workflow_validation = await run_in_threadpool(
                req_module.validate_workflow_vs_requirements,
                structured_workflow,
                generated_requirements,
            )
            scope_review = await run_in_threadpool(
                req_module.scope_control_requirements, transcript_context, generated_requirements
            )
            requirements = await run_in_threadpool(
                req_module.apply_scope_control, generated_requirements, scope_review
            )
        if existing_state and not explicit_removal_requested:
            merged_requirements = await run_in_threadpool(
                req_module.merge_requirement_payloads,
                existing_state.get("current_requirements"),
                requirements,
            )
            merged_scope_review = await run_in_threadpool(
                req_module.merge_scope_review_payloads,
                existing_state.get("current_scope_review"),
                scope_review,
            )
            if merged_requirements:
                requirements = merged_requirements
            if merged_scope_review:
                scope_review = merged_scope_review
        requirements = await run_in_threadpool(req_module.collapse_requirement_workflows, requirements)
        source_files = project_context.get("source_files") or []
        source_name = source_files[0] if len(source_files) == 1 else (f"{len(source_files)} files" if source_files else "project_context")
        project_scope = build_project_scope_snapshot(requirements, scope_review, transcript_context, source_name=source_name)

        await run_in_threadpool(
            save_project_requirement_state_db,
            project_id,
            linked_lead_id,
            transcript_context,
            requirements,
            scope_review,
            workflow_session_version,
        )
        await run_in_threadpool(
            save_project_requirement_event_db,
            project_id,
            linked_lead_id,
            "generate_from_project_context",
            transcript_context,
            {
                "project_id": project_id,
                "confirm_project_start": project_start_confirmed,
                "source_files": source_files,
                "change_request": change_request,
                "workflow_session_version": workflow_session_version,
                "next_step": "requirement_generation",
            },
            requirements,
            scope_review,
            workflow_session_version,
        )
        await run_in_threadpool(
            save_requirements_handoff_db,
            project_id,
            linked_lead_id,
            {
                "version": (workflow_artifact or {}).get("version"),
                "session_title": (workflow_artifact or {}).get("session_title") or "",
                "to_be": structured_workflow or (workflow_artifact or {}).get("to_be") or "",
                "raw_transcript": (workflow_artifact or {}).get("raw_transcript") or "",
                "client_approved": bool(workflow_artifact),
            },
            {
                "transcript_context": transcript_context,
                "current_requirements": requirements,
                "current_scope_review": scope_review,
                "project_scope": project_scope,
                "source_files": source_files,
                "workflow_session_version": (workflow_artifact or {}).get("version"),
            },
        )
        await run_in_threadpool(
            save_project_context_db,
            {
                "project_id": project_id,
                "lead_id": linked_lead_id,
                "source_files": source_files,
                "raw_context": project_context.get("raw_context") or base_transcript_context,
                "processed_context": project_context.get("processed_context") or base_transcript_context,
                "workflow_analysis": project_context.get("workflow_analysis"),
                "structured_workflow": structured_workflow,
                "project_scope": project_scope,
            },
        )

        if linked_lead_id:
            workflow_state_key = str(workflow_session_version or "default").strip() or "default"
            await run_in_threadpool(save_requirement_state_db, linked_lead_id, transcript_context, requirements, scope_review, workflow_state_key)
            await run_in_threadpool(save_project_scope_db, linked_lead_id, project_scope, source_name)

        return {
            "status": "ok",
            "project_id": project_id,
            "lead": lead,
            "source_files": source_files,
            "transcript": transcript_context,
            "requirements": requirements,
            "workflow_validation": workflow_validation,
            "scope_review": scope_review,
            "project_scope": project_scope,
        }
    except Exception as e:
        print(f"Project requirement generation error: {e}")
        return JSONResponse(status_code=500, content={"error": "Requirement generation failed"})


async def iterate_requirements_from_project_context(project_id: str, feedback: str, payload: dict):
    project_context = await run_in_threadpool(get_project_context_db, project_id)
    if not project_context:
        return JSONResponse(status_code=404, content={"error": "Project context not found"})

    linked_lead_id = (project_context.get("lead_id") or "").strip() or None
    explicit_removal_requested = bool(re.search(r"\b(remove|delete|drop|exclude|eliminate)\b", feedback or "", flags=re.IGNORECASE))
    state = await run_blocking_call(get_project_requirement_state_db, project_id, timeout=10)
    if not state or not state.get("current_requirements"):
        return JSONResponse(status_code=400, content={"error": "No requirements found to iterate on. Generate them first."})

    existing_requirements = state["current_requirements"]
    if isinstance(existing_requirements, str):
        existing_requirements = json.loads(existing_requirements)

    try:
        req_module = get_req_generation_module()
        refined_requirements = await run_in_threadpool(
            lambda: req_module.refine_requirements(existing_requirements, feedback)
        )
        if not explicit_removal_requested:
            merged_requirements = await run_in_threadpool(
                req_module.merge_requirement_payloads,
                existing_requirements,
                refined_requirements,
            )
            if merged_requirements:
                refined_requirements = merged_requirements
        refined_requirements = await run_in_threadpool(req_module.collapse_requirement_workflows, refined_requirements)
        workflow_session_version = str(state.get("workflow_session_version") or (project_context.get("requirements_handoff") or {}).get("workflow_session", {}).get("version") or "default")
        
        # Similar saving logic as generation
        source_files = project_context.get("source_files") or []
        source_name = source_files[0] if len(source_files) == 1 else (f"{len(source_files)} files" if source_files else "project_context")
        
        # Build new snapshot
        project_scope = build_project_scope_snapshot(refined_requirements, state.get("current_scope_review"), state.get("transcript_context"), source_name=source_name)

        await run_in_threadpool(
            save_project_requirement_state_db,
            project_id,
            linked_lead_id,
            state.get("transcript_context"),
            refined_requirements,
            state.get("current_scope_review"),
            workflow_session_version,
        )
        
        await run_in_threadpool(
            save_project_requirement_event_db,
            project_id,
            linked_lead_id,
            "iteration_feedback",
            feedback,
            payload,
            refined_requirements,
            state.get("current_scope_review"),
            workflow_session_version,
        )

        return {
            "status": "ok",
            "project_id": project_id,
            "requirements": refined_requirements,
            "project_scope": project_scope,
        }
    except Exception as e:
        print(f"Project requirement iteration error: {e}")
        return JSONResponse(status_code=500, content={"error": "Requirement iteration failed"})


def load_threads(lid):
    db = get_db()
    c = db.cursor(dictionary=True)
    try:
        c.execute(
            """SELECT id, lead_id, title, created_at AS at
               FROM chat_threads
               WHERE lead_id=%s
               ORDER BY created_at DESC""",
            (lid,),
        )
        threads = c.fetchall()
        for thread in threads:
            if thread["id"] == f"default:{lid}":
                thread["id"] = "default"

        c.execute(
            """SELECT count(*) AS cnt
               FROM chat_messages
               WHERE thread_id=%s""",
            (_chat_thread_storage_id(lid, "default"),),
        )
        res = c.fetchone()
        has_history = res['cnt'] if res else 0

        if has_history > 0 and not any(t['id'] == 'default' for t in threads):
            threads.append({'id': 'default', 'lead_id': lid, 'title': 'Primary Briefing', 'at': '2020-01-01'})
        return threads
    finally:
        c.close()
        db.close()

def load_history(lid, tid=None):
    db = get_db()
    c = db.cursor(dictionary=True)
    try:
        if (tid and tid != 'default'):
            c.execute(
                """SELECT id, thread_id, sender_type AS role, message AS text,
                          retrieved_chunks AS sources, created_at AS at
                   FROM chat_messages
                   WHERE thread_id=%s
                   ORDER BY created_at ASC""",
                (_chat_thread_storage_id(lid, tid),),
            )
        else:
            c.execute("""
                SELECT id, thread_id, sender_type AS role, message AS text,
                       retrieved_chunks AS sources, created_at AS at
                FROM chat_messages
                WHERE thread_id=%s
                ORDER BY created_at ASC
            """, (_chat_thread_storage_id(lid, 'default'),))
        rows = c.fetchall()
    finally:
        c.close()
        db.close()
    
    res = []
    for r in rows:
        d = dict(r)
        if d.get("thread_id") == f"default:{lid}":
            d["thread_id"] = "default"
        d['sources'] = json.loads(d['sources']) if d['sources'] else []
        res.append(d)
    return res

# --- RAG UTILS ---
def get_vectorstore(lead_id):
    try:
        db = get_db(); c = db.cursor(dictionary=True); c.execute("SELECT vector_index FROM leads WHERE id=%s", (lead_id,))
        row = c.fetchone(); c.close(); db.close()
        if row and row['vector_index']: return FAISS.deserialize_from_bytes(row['vector_index'], get_embeddings(), allow_dangerous_deserialization=True)
    except Exception as e: print(f"FAISS Load Error: {e}")
    return None

def ingest_to_faiss(text, metadata, lead_id):
    chunks = splitter.split_text(text)
    fresh = FAISS.from_texts(chunks, get_embeddings(), metadatas=[metadata]*len(chunks))
    store = get_vectorstore(lead_id)
    if store: store.merge_from(fresh)
    else: store = fresh
    try:
        db_bytes = store.serialize_to_bytes()
        db = get_db(); c = db.cursor(); c.execute("UPDATE leads SET vector_index=%s WHERE id=%s", (db_bytes, lead_id))
        db.commit(); c.close(); db.close()
    except Exception as e: print(f"Vector Sync Error: {e}")
    return store

def search_vault(query, lead_id, k=8):
    store = get_vectorstore(lead_id); return store.similarity_search(query, k=k) if store else []

# --- AGENTIC DOCUMENT ROUTING ---
def route_document_decision(text: str) -> dict:
    leads = load_leads()
    if not leads:
        lead_init = initialize_new_lead_suggestion("ENTITY: UNKNOWN")
        return {
            "action": "new",
            "lead_id": "",
            "message": lead_init.get("message") or "No existing leads available. Marking as NEW LEAD.",
            "suggested_lead": lead_init.get("suggested_lead", {}),
        }
    
    lead_summaries = [{"id": l["id"], "company": l["company"], "project_name": l["project_name"], "poc": l.get("poc", ""), "industry": l.get("industry", ""), "lead_info": l.get("lead_info", "")} for l in leads]
    
    try:
        excerpt = text[:250000] # Holistic scan
        # Pass 1: Identifiers Extraction
        distill_msg = [SystemMessage(content=DISTILLATION_PROMPT), HumanMessage(content=f"Document Text:\n{excerpt}")]
        summary = get_model().invoke(distill_msg).content
        
        audit_msg = [
            SystemMessage(
                content=(
                    f"{LEAD_MATCH_PROMPT.strip()}\n\n"
                    f"CONTEXT SUMMARY:\n{summary}\n\n"
                    f"EXISTING LEADS DATABASE:\n{json.dumps(lead_summaries, indent=2)}"
                )
            ),
            HumanMessage(content="Final Strategic Audit Decision:")
        ]
        response = get_model().invoke(audit_msg).content
        
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            match_data = json.loads(match.group(0))
        else:
            match_data = json.loads(response)

        decision_msg = [
            SystemMessage(content=LEAD_DECISION_PROMPT),
            HumanMessage(content=f"Matching result:\n{json.dumps(match_data, indent=2)}")
        ]
        decision_response = get_model().invoke(decision_msg).content
        decision_match = re.search(r'\{.*\}', decision_response, re.DOTALL)
        if decision_match:
            decision = json.loads(decision_match.group(0))
        else:
            decision = json.loads(decision_response)

        confidence = match_data.get("confidence_score", 0)
        matched_ids = match_data.get("matched_lead_ids", [])
        if confidence < 95 or not matched_ids:
            lead_init = initialize_new_lead_suggestion(summary)
            return {
                "action": "new",
                "lead_id": "",
                "message": lead_init.get("message") or decision.get("message") or "No reliable lead match found. Marking as NEW LEAD.",
                "suggested_lead": lead_init.get("suggested_lead", {}),
            }

        selected_id = decision.get("lead_id") or matched_ids[0]
        if selected_id not in matched_ids:
            selected_id = matched_ids[0]

        return {
            "action": "existing",
            "lead_id": selected_id,
            "message": decision.get("message") or "Matched to an existing lead.",
            "suggested_lead": {},
        }
    except Exception as e:
        print(f"High-Accuracy Routing error: {e}")
        lead_init = initialize_new_lead_suggestion("ENTITY: UNKNOWN")
        return {
            "action": "new",
            "lead_id": "",
            "message": lead_init.get("message") or "Lead routing failed. Marking as NEW LEAD.",
            "suggested_lead": lead_init.get("suggested_lead", {}),
        }


def route_document_to_lead(text: str) -> list:
    decision = route_document_decision(text)
    if decision.get("action") == "existing" and decision.get("lead_id"):
        return [decision["lead_id"]]
    return []


def clean_intake_text(raw_text: str, model=None) -> str:
    text = (raw_text or "").strip()
    if not text:
        return ""

    cleaner_model = model or ChatOpenAI(model="gpt-4o-mini", temperature=0)
    cleaning_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", CLEANING_PROMPT),
            ("human", "{raw_text}"),
        ]
    )
    cleaning_chain = cleaning_prompt | cleaner_model
    cleaned = cleaning_chain.invoke({"raw_text": text})
    cleaned_text = getattr(cleaned, "content", cleaned)
    return (cleaned_text or text).strip()


def split_intake_contexts(cleaned_text: str, model=None) -> list:
    text = (cleaned_text or "").strip()
    if not text:
        return []
    if len(text) < 800:
        return [{"context_id": "CTX-1", "text": text}]

    splitter_model = model or ChatOpenAI(model="gpt-4o-mini", temperature=0)
    split_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", CONTEXT_SPLIT_PROMPT),
            ("human", "{cleaned_text}"),
        ]
    )
    split_chain = split_prompt | splitter_model

    try:
        response = split_chain.invoke({"cleaned_text": text})
        raw_content = getattr(response, "content", response)
        match = re.search(r"\[\s*\{.*\}\s*\]", raw_content, re.DOTALL)
        payload = match.group(0) if match else raw_content
        contexts = json.loads(payload)
        normalized = []
        for idx, item in enumerate(contexts, start=1):
            context_text = (item.get("text") or "").strip()
            if context_text:
                normalized.append({
                    "context_id": item.get("context_id") or f"CTX-{idx}",
                    "text": context_text,
                })
        return normalized or [{"context_id": "CTX-1", "text": text}]
    except Exception as e:
        print(f"Context split error: {e}")
        return [{"context_id": "CTX-1", "text": text}]

def initialize_new_lead_suggestion(summary: str) -> dict:
    summary_text = (summary or "").strip()
    if not summary_text:
        return {
            "suggested_lead": {},
            "message": "No matching lead found. Do you want to create a new lead?",
        }

    try:
        init_msg = [
            SystemMessage(content=NEW_LEAD_PROMPT),
            HumanMessage(content=f"Extracted summary:\n{summary_text}")
        ]
        response = get_model().invoke(init_msg).content
        match = re.search(r'\{.*\}', response, re.DOTALL)
        payload = json.loads(match.group(0)) if match else json.loads(response)
        return {
            "suggested_lead": payload.get("suggested_lead", {}),
            "message": payload.get("message") or "No matching lead found. Do you want to create a new lead?",
        }
    except Exception as e:
        print(f"New lead initialization error: {e}")
        return {
            "suggested_lead": {},
            "message": "No matching lead found. Do you want to create a new lead?",
        }


# --- MODELS ---
class AgentRequest(BaseModel):
    lead_id: str
    query: Optional[str] = None
    thread_id: Optional[str] = "default"


class WorkflowAnalyzeRequest(BaseModel):
    transcript: str
    lead_id: Optional[str] = None
    project_id: Optional[str] = None
    source_files: Optional[List[str]] = None
    feedback: Optional[str] = ""

def extract_requirement_text(filename: str, content: bytes) -> str:
    text, _ = extract_text_from_content(filename, content)
    return text


async def extract_requirement_texts_from_uploads(upload_files: List[UploadFile]) -> tuple[str, List[str]]:
    combined_parts = []
    filenames = []
    for upload in upload_files or []:
        if not upload:
            continue
        content = await upload.read()
        extracted = (await run_in_threadpool(extract_requirement_text, upload.filename, content)).strip()
        if not extracted:
            continue
        fname = upload.filename or "uploaded_file"
        filenames.append(fname)
        combined_parts.append(f"--- [FILE: {fname}] ---\n{extracted}")
    return ("\n\n".join(combined_parts).strip(), filenames)


@app.post("/api/utils/extract-text")
async def api_extract_text(file: UploadFile = File(...)):
    """Utility endpoint to extract plain text from PDF, DOCX, or TXT files."""
    try:
        content = await file.read()
        extracted_text, _ = await run_in_threadpool(extract_text_from_content, file.filename, content)
        return {"status": "ok", "text": extracted_text}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Extraction failed: {str(e)}"})


def extract_mermaid_blocks(text: str) -> list:
    if not text:
        return []
    blocks = re.findall(r"```mermaid\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    return [block.strip() for block in blocks if block and block.strip()]


def strip_mermaid_blocks(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"```mermaid\s*.*?```", "\n", text, flags=re.IGNORECASE | re.DOTALL)
    return cleaned.strip()


def looks_like_mermaid(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    markers = (
        "graph ",
        "flowchart ",
        "sequencediagram",
        "statediagram",
        "classdiagram",
        "erdiagram",
        "journey",
        "gantt",
        "mindmap",
        "timeline",
        "quadrantchart",
        "gitgraph",
        "pie ",
    )
    lowered = value.lower()
    return any(lowered.startswith(marker) for marker in markers)


def parse_mermaid_workflow(raw_text: str, req_module):
    if not raw_text:
        return None
    blocks = extract_mermaid_blocks(raw_text)
    mermaid_code = blocks[0] if blocks else ((raw_text or "").strip() if looks_like_mermaid(raw_text) else "")
    if not mermaid_code:
        return None
    parsed = req_module.understand_mermaid_workflow(mermaid_code)
    if isinstance(parsed, dict):
        return parsed.get("workflow") or parsed
    return None


def normalize_structured_workflow_input(raw_value, req_module):
    if raw_value is None:
        return None
    if isinstance(raw_value, (dict, list)):
        return raw_value
    if not isinstance(raw_value, str):
        return raw_value

    text = raw_value.strip()
    if not text:
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        mermaid_workflow = parse_mermaid_workflow(text, req_module)
        if mermaid_workflow:
            return mermaid_workflow
        return raw_value


def serialize_structured_workflow_context(workflow):
    if not workflow:
        return ""
    if isinstance(workflow, str):
        return workflow.strip()
    try:
        return json.dumps(workflow, indent=2)
    except Exception:
        return str(workflow).strip()


def auto_workflow_from_markdown(filename: str, transcript: str, req_module):
    name = (filename or "").lower()
    if not name.endswith(".md"):
        return None, transcript

    workflow = parse_mermaid_workflow(transcript, req_module)
    cleaned_transcript = strip_mermaid_blocks(transcript)
    if cleaned_transcript:
        return workflow, cleaned_transcript
    return workflow, transcript


def extract_text_from_content(filename, content):
    filename_lower = filename.lower()
    text = ""
    pages_count = 1
    
    if filename_lower.endswith(".pdf"):
        try:
            pdf = PdfReader(io.BytesIO(content))
            pages_count = len(pdf.pages)
            text = "\n".join([p.extract_text() for p in pdf.pages if p.extract_text()])
        except:
            pass
    elif filename_lower.endswith(".docx"):
        try:
            doc = docx.Document(io.BytesIO(content))
            text = "\n".join([para.text for para in doc.paragraphs if para.text])
            pages_count = max(1, len(doc.paragraphs) // 30 + 1)
        except:
            pass
    elif filename_lower.endswith(".eml"):
        try:
            msg = email.message_from_bytes(content, policy=policy.default)
            parts_text = []
            subject = msg.get("Subject", "No Subject")
            from_addr = msg.get("From", "Unknown")
            to_addr = msg.get("To", "Unknown")
            date_str = msg.get("Date", "Unknown")
            parts_text.append(f"--- EMAIL BEGIN ---\nSubject: {subject}\nFrom: {from_addr}\nTo: {to_addr}\nDate: {date_str}\n\n[EMAIL BODY]")

            has_plain_text = False
            for part in msg.walk():
                if part.is_multipart() or "attachment" in str(part.get("Content-Disposition")) or part.get_filename():
                    continue
                if part.get_content_type() == "text/plain":
                    has_plain_text = True
                    break

            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                att_filename = part.get_filename()

                if "attachment" in content_disposition or att_filename:
                    att_filename = att_filename or "unknown_attachment"
                    att_content = part.get_payload(decode=True)
                    if att_content:
                        parts_text.append(f"\n\n--- [ATTACHMENT START: {att_filename}] ---")
                        att_text, att_pages = extract_text_from_content(att_filename, att_content)
                        formatted_att_lines = []
                        for line in att_text.split('\n'):
                            if line.strip():
                                formatted_att_lines.append(f"[Attachment: {att_filename}] {line}")
                            else:
                                formatted_att_lines.append("")
                        parts_text.append("\n".join(formatted_att_lines))
                        parts_text.append(f"--- [ATTACHMENT END: {att_filename}] ---\n")
                        pages_count += att_pages
                else:
                    if part.is_multipart():
                        continue
                    if content_type == "text/plain":
                        try:
                            body = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors="ignore")
                            parts_text.append(body)
                        except:
                            pass
                    elif content_type == "text/html" and not has_plain_text:
                        try:
                            body = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors="ignore")
                            clean_txt = re.sub(r'<style.*?>.*?</style>', '', body, flags=re.DOTALL | re.IGNORECASE)
                            clean_txt = re.sub(r'<[^>]+>', ' ', clean_txt)
                            parts_text.append(clean_txt)
                        except:
                            pass
            parts_text.append("--- EMAIL END ---")
            text = "\n".join(parts_text)
        except Exception:
            text = content.decode("utf-8", errors="ignore")
    else:
        text = content.decode("utf-8", errors="ignore")

    return text.strip(), pages_count

# --- DOCUMENT AGENT PROMPTS (Moved to doc_architect_agent.py) ---

# --- ENDPOINTS ---
@app.post("/api/auth/login")
async def auth_login(payload: AuthCredentials):
    if payload.email.strip().lower() != TEMP_AUTH_EMAIL or payload.password != TEMP_AUTH_PASSWORD:
        return JSONResponse(
            status_code=401,
            content={
                "error": f"Invalid credentials. Use {TEMP_AUTH_EMAIL} / {TEMP_AUTH_PASSWORD}."
            },
        )

    return {
        "ok": True,
        "user": TEMP_AUTH_USER,
        "message": "Temporary credential login enabled.",
    }


@app.post("/api/auth/signup")
async def auth_signup(payload: SignupPayload):
    return {
        "ok": True,
        "user": {
            **TEMP_AUTH_USER,
            "name": payload.name.strip() or TEMP_AUTH_USER["name"],
            "email": payload.email.strip().lower() or TEMP_AUTH_USER["email"],
            "auth_provider": "signup-mock",
        },
        "message": "Signup is temporarily mocked for local development.",
    }


@app.post("/api/auth/google")
async def auth_google(payload: GoogleAuthPayload):
    return {
        "ok": True,
        "user": {
            **TEMP_AUTH_USER,
            "name": (payload.name or TEMP_AUTH_USER["name"]).strip(),
            "email": (payload.email or TEMP_AUTH_USER["email"]).strip().lower(),
            "auth_provider": "google-mock",
        },
        "message": "Google auth is temporarily mocked for local development.",
    }


# ---- COMPANIES ----
@app.get("/api/companies")
async def get_companies():
    try:
        companies = await run_blocking_call(load_companies, timeout=10)
        return {"companies": companies}
    except asyncio.TimeoutError:
        return {"companies": [], "warning": "Database request timed out while loading companies."}
    except Error as e:
        return {"companies": [], "warning": f"Database unavailable while loading companies: {str(e)}"}

@app.post("/api/companies")
async def add_company(company: dict):
    try:
        cid = await run_blocking_call(save_company_db, company, timeout=10)
        return {"status": "ok", "company_id": cid}
    except asyncio.TimeoutError:
        return JSONResponse(status_code=503, content={"error": "Database request timed out while saving company."})
    except Error as e:
        return JSONResponse(status_code=503, content={"error": f"Database unavailable while saving company: {str(e)}"})
@app.delete("/api/companies/{cid}")
async def del_company(cid: str):
    try:
        await run_blocking_call(delete_company_db, cid, timeout=10)
        return {"status": "ok"}
    except asyncio.TimeoutError:
        return JSONResponse(status_code=503, content={"error": "Database request timed out while deleting company."})
    except Error as e:
        return JSONResponse(status_code=503, content={"error": f"Database unavailable while deleting company: {str(e)}"})

@app.get("/api/companies/lookup/{domain}")
async def lookup_company(domain: str):
    company = await run_blocking_call(find_company_by_domain, domain, timeout=10)
    if company:
        return {"status": "found", "company": company}
    return {"status": "not_found"}

@app.put("/api/companies/{cid}")
async def update_company(cid: str, company: dict):
    try:
        company['id'] = cid
        await run_blocking_call(save_company_db, company, timeout=10)
        return {"status": "ok"}
    except asyncio.TimeoutError:
        return JSONResponse(status_code=503, content={"error": "Database request timed out while updating company."})
    except Error as e:
        return JSONResponse(status_code=503, content={"error": f"Database unavailable while updating company: {str(e)}"})

# ---- LEADS ----
@app.get("/api/leads")
async def get_leads(company_id: Optional[str] = None):
    if LEADS_DB_BYPASS:
        return {"leads": []}
    try:
        leads = await run_blocking_call(load_leads, company_id, timeout=5)
        # Filter out master company records so they don't appear as leads in the UI
        filtered_leads = [l for l in leads if l.get('status') != 'company_directory']
        return {"leads": filtered_leads}
    except asyncio.TimeoutError:
        return {"leads": [], "warning": "Database request timed out while loading leads."}
    except Error as e:
        return {"leads": [], "warning": f"Database unavailable while loading leads: {str(e)}"}

@app.get("/api/leads/{lid}")
async def get_lead_detail(lid: str):
    try:
        lead = await run_blocking_call(get_lead_db, lid, timeout=10)
        if not lead:
            return JSONResponse(status_code=404, content={"error": "Lead not found"})
        return {"status": "ok", "lead": lead}
    except asyncio.TimeoutError:
        return JSONResponse(status_code=503, content={"error": "Database request timed out while loading lead detail."})
    except Error as e:
        return JSONResponse(status_code=503, content={"error": f"Database unavailable while loading lead detail: {str(e)}"})

@app.post("/api/leads")
async def add_lead(lead: dict):
    """Normalized lead creation: upsert company data, then attach lead-specific project data."""
    domain = lead.get('domain', '').strip().lower()
    
    # Step 1: Normalize and synchronize parent company master-record
    existing_company = await run_blocking_call(find_company_by_domain, domain, timeout=10)
    company_id = existing_company['id'] if existing_company else str(uuid.uuid4())[:12]
    
    await run_blocking_call(save_company_db, {
        'id': company_id, 
        'name': lead.get('company'), 
        'domain': domain, 
        'industry': lead.get('industry', ''), 
        'ceo': lead.get('ceo', ''),
        'poc': lead.get('poc', ''),
        'company_size': lead.get('company_size') or 'Mid-Market'
    }, timeout=10)

    # Step 2: Save the lead as a project-level child
    lead['company_id'] = company_id
    lead_id = await run_blocking_call(save_lead_db, lead, timeout=10)
    return {"status": "ok", "lead_id": lead_id, "company_id": company_id}


@app.post("/api/leads/{lid}/accept")
async def accept_lead(lid: str):
    lead = await run_blocking_call(get_lead_db, lid, timeout=10)
    if not lead:
        return JSONResponse(status_code=404, content={"error": "Lead not found"})
    updated = await run_blocking_call(mark_lead_accepted, lid, timeout=10)
    return {"status": "ok", "lead": updated}


@app.post("/api/leads/{lid}/requirements")
async def generate_lead_requirements(lid: str, payload: dict):
    project_id = (payload.get("project_id") or "").strip()
    if not project_id:
        return JSONResponse(
            status_code=400,
            content={
                "error": "project_id is required. Step 2 now reuses the stored Step 1 context instead of accepting raw transcript input."
            },
        )
    return await generate_requirements_from_project_context(project_id, payload, expected_lead_id=lid)


@app.post("/api/leads/{lid}/requirements/upload")
async def generate_lead_requirements_from_upload(
    lid: str,


):
    return JSONResponse(
        status_code=410,
        content={
            "error": (
                "Step 2 file uploads have been removed. Upload files in Step 1, store the reusable context, "
                "and call requirement generation with project_id only."
            )
        },
    )


@app.post("/api/leads/{lid}/requirements/refine")
async def refine_lead_requirements(lid: str, payload: dict):
    return JSONResponse(
        status_code=409,
        content={
            "error": (
                "Requirement changes now belong to Step 1. Update the stored project context there, "
                "then regenerate downstream outputs with project_id."
            )
        },

    )


@app.post("/api/leads/{lid}/requirements/refine/upload")
async def refine_lead_requirements_from_upload(
    lid: str,
):
    return JSONResponse(
        status_code=410,
        content={
            "error": (
                "Downstream upload-based requirement changes are no longer supported. "
                "Go back to Step 1, update the project context, and regenerate with project_id."
            )
        },
    )


@app.post("/api/leads/{lid}/requirements/manual-update")
async def manual_update_lead_requirements(lid: str, payload: dict):
    return JSONResponse(
        status_code=409,
        content={
            "error": (
                "Manual requirement edits are disabled in downstream steps. "
                "Return to Step 1, revise the stored context, and regenerate with project_id."
            )
        },
    )


@app.get("/api/leads/{lid}/requirements/latest")
async def get_latest_lead_requirements(lid: str, workflow_id: Optional[str] = None):
    try:
        lead = await run_blocking_call(get_lead_db, lid, timeout=10)
        if not lead:
            return JSONResponse(status_code=404, content={"error": "Lead not found"})

        lead_project_id = await run_blocking_call(_get_project_id_for_lead_db, lid, timeout=10)
        project_context = await run_blocking_call(get_project_context_db, lead_project_id, timeout=10) if lead_project_id else None
        requirements_handoff = (project_context or {}).get("requirements_handoff") if project_context else None

        state = None
        if workflow_id and requirements_handoff and _handoff_matches_workflow_id(requirements_handoff, workflow_id):
            state = requirements_handoff.get("requirements_state") or None

        if not state:
            if requirements_handoff and not workflow_id:
                state = requirements_handoff.get("requirements_state") or None
            if not state:
                state = await run_blocking_call(get_requirement_state_db, lid, workflow_id, timeout=10)
            if not state and workflow_id and lead_project_id:
                state = await run_blocking_call(_load_requirement_state_from_events_db, lead_project_id, workflow_id, timeout=10)
            if not state and lead_project_id:
                state = await run_blocking_call(_load_normalized_requirements_state_db, lead_project_id, workflow_id, timeout=10)

    except asyncio.TimeoutError:
        return JSONResponse(status_code=503, content={"error": "Database request timed out while loading latest requirements."})
    except Error as e:
        return JSONResponse(status_code=503, content={"error": f"Database unavailable while loading latest requirements: {str(e)}"})

    if not lead:
        return JSONResponse(status_code=404, content={"error": "Lead not found"})

    project_scope = None
    if lead and lead.get("project_scope"):
        try:
            project_scope = json.loads(lead["project_scope"])
        except json.JSONDecodeError:
            project_scope = None
    handoff = await run_blocking_call(get_requirements_handoff_db, lead_project_id, timeout=10) if lead_project_id else None
    
    # Critical: If we found a specific session state, ensure the handoff metadata matches it
    # so the frontend doesn't flag it as stale.
    if state and workflow_id:
        if not handoff: handoff = {"requirements_state": state}
        else: handoff["requirements_state"] = state

    return {
        "status": "ok",
        "lead": lead,
        "project": await run_blocking_call(get_project_context_db, lead_project_id, timeout=10) if lead_project_id else None,
        "requirements_state": state,
        "requirements_handoff": handoff,
        "project_scope": project_scope,
    }



@app.post("/api/agents/doc-generate")
async def generate_technical_documents(payload: DocGenerateRequest):
    lid = payload.lead_id
    workflow_id = payload.workflow_id
    
    try:
        # 1. Fetch Requirements (Robust)
        db = get_db(); c = db.cursor(dictionary=True)
        c.execute("SELECT id FROM projects WHERE lead_id=%s LIMIT 1", (lid,))
        p = c.fetchone()
        project_id = p['id'] if p else None
        c.close(); db.close()

        normalized_state = None
        if project_id:
            from app import _load_normalized_requirements_state_db
            normalized_state = await run_blocking_call(_load_normalized_requirements_state_db, project_id)
            
        from app import get_requirement_state_db
        req_state = normalized_state or await run_blocking_call(get_requirement_state_db, lid, workflow_id)
        requirements = req_state.get("current_requirements") if req_state else ""
        
        # 2. TO-BE Workflow (Mermaid) Lookup (Robust)
        db = get_db(); c = db.cursor(dictionary=True)
        flow_row = None
        # Try specific version first
        try:
            version_int = int(str(workflow_id).replace("Session ", ""))
            c.execute("SELECT nodes FROM workflows WHERE project_id=%s AND type='to_be' AND version=%s", (lid, version_int))
            flow_row = c.fetchone()
        except: pass

        if not flow_row:
            # Try latest approved
            c.execute("SELECT nodes FROM workflows WHERE project_id=%s AND type='to_be' AND client_approved=1 ORDER BY version DESC LIMIT 1", (lid,))
            flow_row = c.fetchone()
            
        if not flow_row:
            # Try any latest
            c.execute("SELECT nodes FROM workflows WHERE project_id=%s AND type='to_be' ORDER BY version DESC LIMIT 1", (lid,))
            flow_row = c.fetchone()

        workflow_mermaid = flow_row['nodes'] if flow_row else "Not specified"
        c.close(); db.close()

        if not requirements or not workflow_mermaid:
            print(f"Doc Generation Blocked: Req found? {bool(requirements)}, Flow found? {bool(workflow_mermaid)}")

        # 3. Trigger Generation Pipeline
        from doc_architect_agent import generate_architecture_documents as run_doc_generation
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model="gpt-4o", temperature=0)
        
        design_output = await run_doc_generation(
            llm,
            payload.tech_stack or "Not Specified",
            payload.additional_context or "None",
            workflow_mermaid,
            requirements
        )

        # 4. Save to doc_agent_artifacts (Versioned)
        db = get_db(); c = db.cursor()
        new_id = str(uuid.uuid4())
        # Determine current version
        c.execute("SELECT MAX(version) FROM doc_agent_artifacts WHERE lead_id=%s AND workflow_id=%s", (lid, workflow_id))
        max_v = c.fetchone()[0] or 0
        new_version = max_v + 1
        
        c.execute(
            """INSERT INTO doc_agent_artifacts (id, lead_id, workflow_id, version, project_summary, hld_content, lld_content, db_schema, backlog)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                new_id, lid, workflow_id, new_version,
                design_output.project_summary,
                design_output.hld_content,
                design_output.lld_content,
                design_output.db_schema,
                json.dumps([b.dict() for b in design_output.backlog])
            )
        )
        db.commit(); c.close(); db.close()

        return {
            "status": "ok",
            "artifact_id": new_id,
            "version": new_version,
            "design": design_output.dict()
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": f"Document generation failed: {str(e)}"})


@app.get("/api/doc-artifacts/{lead_id}/{workflow_id}/latest")
async def get_latest_doc_artifact(lead_id: str, workflow_id: str):
    """Retrieves the most recent architectural design for a specific lead and workflow."""
    try:
        db = get_db(); c = db.cursor(dictionary=True)
        resolved_lead_id = _resolve_lead_id_for_ref(c, lead_id)
        # Using lead_id and workflow_id as suggested by user for specialized doc_agent_artifacts table
        c.execute(
            """SELECT * FROM doc_agent_artifacts 
               WHERE lead_id=%s AND workflow_id=%s 
               ORDER BY version DESC LIMIT 1""",
            (resolved_lead_id, workflow_id)
        )
        row = c.fetchone()
        c.close(); db.close()
        
        if not row:
            return JSONResponse(status_code=404, content={"status": "none", "message": "No design found for this workflow"})
            
        return {
            "status": "ok",
            "artifact": {
                "id": row['id'],
                "version": row['version'],
                "project_summary": row.get('project_summary', ''),
                "hld_content": row['hld_content'],
                "lld_content": row['lld_content'],
                "ia_content": row.get('ia_content', ''),
                "db_schema": row['db_schema'],
                "backlog": json.loads(row['backlog']) if row['backlog'] else [],
                "created_at": row['created_at'].isoformat() if row['created_at'] else None
            }
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/agents/ia-generate")
async def generate_ia_blueprint(payload: IAGenerateRequest):
    """Generates the Information Architecture (IA) purely visual blueprint."""
    lid = payload.lead_id
    workflow_id = payload.workflow_id
    
    try:
        # 1. Fetch Latest Architectural Context (HLD/LLD/Schema)
        db = get_db(); c = db.cursor(dictionary=True)
        resolved_lead_id = _resolve_lead_id_for_ref(c, lid)
        c.execute(
            "SELECT id, hld_content, lld_content, db_schema FROM doc_agent_artifacts WHERE lead_id=%s AND workflow_id=%s ORDER BY version DESC LIMIT 1",
            (resolved_lead_id, workflow_id)
        )
        artifact = c.fetchone()
        
        if not artifact:
            c.close(); db.close()
            return JSONResponse(status_code=404, content={"error": "No architectural documents found. Please generate HLD/LLD first."})
            
        # 2. Trigger IA Generation
        from doc_architect_agent import generate_ia_document
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model="gpt-4o", temperature=0)
        
        ia_blueprint = await generate_ia_document(
            llm,
            artifact['hld_content'],
            artifact['lld_content'],
            artifact['db_schema']
        )
        
        # 3. Persist to DB (Update the latest session artifact)
        c.execute(
            "UPDATE doc_agent_artifacts SET ia_content = %s WHERE id = %s",
            (ia_blueprint, artifact['id'])
        )
        db.commit()
        c.close(); db.close()
        
        return {
            "status": "ok",
            "ia_content": ia_blueprint,
            "artifact_id": artifact['id']
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": f"IA generation failed: {str(e)}"})



@app.get("/api/agents/doc-download-pdf")
async def download_design_pdf(
    lead_id: str,
    artifact_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    doc_type: str = "full",
):
    try:
        if PDF_GENERATOR_IMPORT_ERROR:
            return JSONResponse(status_code=503, content={"error": PDF_GENERATOR_IMPORT_ERROR})

        db = get_db(); c = db.cursor(dictionary=True)
        resolved_lead_id = _resolve_lead_id_for_ref(c, lead_id)
        row = None
        if artifact_id:
            c.execute("SELECT data FROM project_artifacts WHERE id=%s", (artifact_id,))
            row = c.fetchone()
            if not row:
                c.execute(
                    """SELECT hld_content, lld_content, db_schema, backlog, version
                       FROM doc_agent_artifacts
                       WHERE id=%s""",
                    (artifact_id,),
                )
                doc_row = c.fetchone()
                if doc_row:
                    row = {
                        "data": json.dumps(
                            {
                                "hld_content": doc_row.get("hld_content") or "",
                                "lld_content": doc_row.get("lld_content") or "",
                                "db_schema": doc_row.get("db_schema") or "",
                                "backlog": _decode_json_blob(doc_row.get("backlog")) or [],
                                "version": doc_row.get("version"),
                            }
                        )
                    }
        else:
            if workflow_id:
                c.execute(
                    """SELECT hld_content, lld_content, db_schema, backlog, version
                       FROM doc_agent_artifacts
                       WHERE lead_id=%s AND workflow_id=%s
                       ORDER BY version DESC
                       LIMIT 1""",
                    (resolved_lead_id, workflow_id),
                )
                doc_row = c.fetchone()
                if doc_row:
                    row = {
                        "data": json.dumps(
                            {
                                "hld_content": doc_row.get("hld_content") or "",
                                "lld_content": doc_row.get("lld_content") or "",
                                "db_schema": doc_row.get("db_schema") or "",
                                "backlog": _decode_json_blob(doc_row.get("backlog")) or [],
                                "version": doc_row.get("version"),
                            }
                        )
                    }

            if not row:
                c.execute(
                    "SELECT data FROM project_artifacts WHERE lead_id=%s AND agent_id='doc_agent' ORDER BY at DESC LIMIT 1",
                    (resolved_lead_id,),
                )
                row = c.fetchone()

        c.close(); db.close()
        
        if not row:
            return JSONResponse(status_code=404, content={"error": "Design document not found."})
            
        # Determine data source
        if 'hld_content' in row and row['hld_content'] is not None:
            # Data from doc_agent_artifacts
            data = {
                'project_summary': row.get('project_summary', ''),
                'hld_content': row.get('hld_content', ''),
                'lld_content': row.get('lld_content', ''),
                'db_schema': row.get('db_schema', ''),
                'backlog': json.loads(row['backlog']) if isinstance(row.get('backlog'), str) else row.get('backlog', [])
            }
        else:
            # Data from generic project_artifacts
            data = json.loads(row['data']) if 'data' in row else {}
        
        # Get Lead Name for the PDF title
        lead_info = get_lead_db(resolved_lead_id)
        base_name = lead_info.get('project_name', 'System Architecture Design') if lead_info else 'System Architecture Design'
        session_label = f"Session {workflow_id}" if workflow_id else "Latest"
        project_name = f"{base_name} - {session_label}"
        
        # Generate PDF based on type
        if doc_type == "hld":
            from pdf_generator import generate_hld_pdf
            pdf_bytes = generate_hld_pdf(
                project_name=project_name,
                summary=data.get('project_summary', '') or data.get('db_schema', '')[:300],
                hld=data.get('hld_content', '')
            )
            filename = f"HLD_{lead_id[:8]}_{workflow_id or 'latest'}.pdf"
        elif doc_type == "lld":
            from pdf_generator import generate_lld_pdf
            pdf_bytes = generate_lld_pdf(
                project_name=project_name,
                summary=data.get('project_summary', '') or data.get('db_schema', '')[:300],
                lld=data.get('lld_content', '')
            )
            filename = f"LLD_{lead_id[:8]}_{workflow_id or 'latest'}.pdf"
        else:
            from pdf_generator import generate_design_pdf
            pdf_bytes = generate_design_pdf(
                project_name=project_name,
                summary=data.get('project_summary', '') or data.get('db_schema', '')[:300],
                hld=data.get('hld_content', ''),
                lld=data.get('lld_content', '')
            )
            filename = f"Design_{lead_id[:8]}_{workflow_id or 'latest'}.pdf"
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except Exception as e:
        print(f"PDF Export Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# New Project Endpoints from Main

@app.get("/api/projects/{project_id}/context")
async def get_project_context(project_id: str):
    project_context = await run_in_threadpool(get_project_context_db, project_id)
    if not project_context:
        return JSONResponse(status_code=404, content={"error": "Project context not found"})
    return {"status": "ok", "project": project_context}


@app.post("/api/projects/{project_id}/requirements")
async def generate_project_requirements(project_id: str, payload: dict):
    request_id = (payload.get("request_id") or "").strip()
    if request_id:
        print(f"Requirement generation request received: project_id={project_id}, request_id={request_id}")
    else:
        print(f"Requirement generation request received: project_id={project_id}")
    return await generate_requirements_from_project_context(project_id, payload)



@app.post("/api/projects/{project_id}/iteration")
async def iterate_project_requirements(project_id: str, payload: dict):
    feedback = payload.get("feedback", "")
    if not feedback:
        return JSONResponse(status_code=400, content={"error": "feedback is required"})
    return await iterate_requirements_from_project_context(project_id, feedback, payload)


@app.get("/api/projects/{project_id}/artifacts")
async def get_project_artifacts(project_id: str, type: Optional[str] = None):
    artifacts = await run_in_threadpool(get_project_artifacts_db, project_id, type)
    return {"status": "ok", "artifacts": artifacts}

@app.get("/api/projects/{project_id}/requirements/latest")
async def get_latest_project_requirements(project_id: str):
    try:
        project_context = await run_blocking_call(get_project_context_db, project_id, timeout=10)
        if not project_context:
            return JSONResponse(status_code=404, content={"error": "Project context not found"})
        requirements_handoff = project_context.get("requirements_handoff") or {}
        state = requirements_handoff.get("requirements_state") or None
        if not state:
            state = await run_blocking_call(get_project_requirement_state_db, project_id, timeout=10)
        if not state:
            state = await run_blocking_call(_load_normalized_requirements_state_db, project_id, timeout=10)
    except asyncio.TimeoutError:
        return JSONResponse(status_code=503, content={"error": "Database request timed out while loading latest project requirements."})
    except Error as e:
        return JSONResponse(status_code=503, content={"error": f"Database unavailable while loading latest project requirements: {str(e)}"})

    lead = None
    linked_lead_id = (project_context.get("lead_id") or "").strip()
    if linked_lead_id:
        lead = await run_blocking_call(get_lead_db, linked_lead_id, timeout=10)

    return {
        "status": "ok",
        "project_id": project_id,
        "lead": lead,
        "project": project_context,
        "requirements_state": state,
        "requirements_handoff": project_context.get("requirements_handoff"),
        "project_scope": project_context.get("project_scope"),
    }


@app.get("/api/leads/{lid}/requirements/history")
async def get_lead_requirement_history(lid: str):
    try:
        lead = await run_blocking_call(get_lead_db, lid, timeout=10)
        if not lead:
            return JSONResponse(status_code=404, content={"error": "Lead not found"})
        lead_project_id = await run_blocking_call(_get_project_id_for_lead_db, lid, timeout=10)
        normalized_events = (
            await run_blocking_call(_load_normalized_requirement_events_db, lead_project_id, lid, timeout=10)
            if lead_project_id else None
        )
        events = normalized_events or await run_blocking_call(load_requirement_events_db, lid, timeout=10)
    except asyncio.TimeoutError:
        return JSONResponse(status_code=503, content={"error": "Database request timed out while loading requirement history."})
    except Error as e:
        return JSONResponse(status_code=503, content={"error": f"Database unavailable while loading requirement history: {str(e)}"})

    return {
        "status": "ok",
        "lead": lead,
        "events": events,
    }


@app.get("/api/projects/{project_id}/requirements/history")
async def get_project_requirement_history(project_id: str):
    try:
        project_context = await run_blocking_call(get_project_context_db, project_id, timeout=10)
        if not project_context:
            return JSONResponse(status_code=404, content={"error": "Project context not found"})
        normalized_events = await run_blocking_call(
            _load_normalized_requirement_events_db,
            project_id,
            (project_context.get("lead_id") or "").strip() or None,
            timeout=10,
        )
        events = normalized_events or await run_blocking_call(load_project_requirement_events_db, project_id, timeout=10)
    except asyncio.TimeoutError:
        return JSONResponse(status_code=503, content={"error": "Database request timed out while loading project requirement history."})
    except Error as e:
        return JSONResponse(status_code=503, content={"error": f"Database unavailable while loading project requirement history: {str(e)}"})

    lead = None
    linked_lead_id = (project_context.get("lead_id") or "").strip()
    if linked_lead_id:
        lead = await run_blocking_call(get_lead_db, linked_lead_id, timeout=10)

    return {
        "status": "ok",
        "project_id": project_id,
        "lead": lead,
        "events": events,
    }

@app.delete("/api/leads/{lid}")
async def del_lead(lid: str):
    try:
        await run_blocking_call(delete_lead_db, lid, timeout=10)
        return {"status": "ok"}
    except asyncio.TimeoutError:
        return JSONResponse(status_code=503, content={"error": "Database request timed out while deleting lead."})
    except Error as e:
        return JSONResponse(status_code=503, content={"error": f"Database unavailable while deleting lead: {str(e)}"})

@app.post("/api/leads/launch/{lid}")
async def launch_lead(lid: str):
    db = get_db(); c = db.cursor()
    try:
        c.execute("UPDATE leads SET status='active', project_stage='requirement_gathering' WHERE id=%s", (lid,))
        db.commit()
        return {"status": "ok"}
    finally: c.close(); db.close()

@app.get("/api/sources")
async def get_sources(lead_id: Optional[str] = None):
    try:
        sources = await run_blocking_call(load_sources, lead_id, timeout=10)
        return {"sources": sources}
    except asyncio.TimeoutError:
        return JSONResponse(status_code=503, content={"error": "Database request timed out while loading sources."})
    except Error as e:
        return JSONResponse(status_code=503, content={"error": f"Database unavailable while loading sources: {str(e)}"})

@app.delete("/api/sources/{sid}")
async def del_source(sid: str):
    db = get_db()
    c = db.cursor()
    c.execute("DELETE FROM lead_sources WHERE id=%s", (sid,))
    db.commit()
    c.close()
    db.close()
    return {"status": "ok"}

@app.get("/api/history/{lid}")
async def get_history(lid: str, tid: str = None):
    try:
        history = await run_blocking_call(load_history, lid, tid, timeout=10)
        return {"history": history}
    except asyncio.TimeoutError:
        return JSONResponse(status_code=503, content={"error": "Database request timed out while loading chat history."})
    except Error as e:
        return JSONResponse(status_code=503, content={"error": f"Database unavailable while loading chat history: {str(e)}"})

@app.get("/api/threads/{lid}")
async def get_threads(lid: str):
    try:
        threads = await run_blocking_call(load_threads, lid, timeout=10)
        return {"threads": threads}
    except asyncio.TimeoutError:
        return JSONResponse(status_code=503, content={"error": "Database request timed out while loading threads."})
    except Error as e:
        return JSONResponse(status_code=503, content={"error": f"Database unavailable while loading threads: {str(e)}"})


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "leadflow-api"}

@app.post("/api/threads")
async def add_thread(thread: dict):
    save_thread_db(thread)
    return {"status": "ok"}

@app.post("/api/upload")
async def upload_docs(request: Request):
    try:
        data = await request.json()
        text = clean_intake_text(data.get("content", ""))
        name = data.get("title", "Neural Entry")
        lead_id = data.get("lead_id", "auto")
        if text:
            contexts = split_intake_contexts(text)
            all_routed_ids = []
            processed = 0
            for context in contexts:
                context_text = context.get("text", "").strip()
                if not context_text:
                    continue
                target_lead_ids = route_document_to_lead(context_text) if lead_id == "auto" else [lead_id]
                all_routed_ids.extend(target_lead_ids)
                context_name = name if len(contexts) == 1 else f"{name} ({context.get('context_id', 'CTX')})"
                for t_id in target_lead_ids:
                    sid = str(uuid.uuid4())[:8]
                    meta = {"id": sid, "name": context_name, "at": datetime.now().isoformat()}
                    ingest_to_faiss(context_text, meta, t_id)
                    save_source_db({**meta, "lead_id": t_id, "pages": 1, "chunks": 1})
                    append_context_to_lead(t_id, context_text, context_name)
                processed += 1
            return {
                "status": "ok",
                "processed": processed,
                "routed_to": list(set(all_routed_ids)),
                "contexts": contexts,
            }
    except:
        form = await request.form()
        files = form.getlist("files")
        lead_id = form.get("lead_id", "auto")
        processed = 0
        all_routed_ids = []
        for f in files:
            content = await f.read()
            name = f.filename
            text, pages_count = extract_text_from_content(name, content)
            text = clean_intake_text(text)
                
            if text:
                contexts = split_intake_contexts(text)
                for context in contexts:
                    context_text = context.get("text", "").strip()
                    if not context_text:
                        continue
                    target_lead_ids = route_document_to_lead(context_text) if lead_id == "auto" else [lead_id]
                    all_routed_ids.extend(target_lead_ids)
                    context_name = name if len(contexts) == 1 else f"{name} ({context.get('context_id', 'CTX')})"
                    for t_id in target_lead_ids:
                        sid = str(uuid.uuid4())[:8]
                        meta = {"id": sid, "name": context_name, "at": datetime.now().isoformat()}
                        ingest_to_faiss(context_text, meta, t_id)
                        save_source_db({**meta, "lead_id": t_id, "pages": pages_count, "chunks": 1})
                        append_context_to_lead(t_id, context_text, context_name)
                    processed += 1
        return {"status": "ok", "processed": processed, "routed_to": list(set(all_routed_ids))}
    return {"status": "error"}

@app.post("/api/analyze-upload")
async def analyze_upload(request: Request):
    try:
        form = await request.form()
        files = form.getlist("files")
        results = []
        for f in files:
            content = await f.read()
            name = f.filename
            text, pages_count = extract_text_from_content(name, content)
            text = clean_intake_text(text)
                
            if text:
                contexts = split_intake_contexts(text)
                context_results = []
                aggregated_predictions = []
                for context in contexts:
                    context_text = context.get("text", "").strip()
                    if not context_text:
                        continue
                    decision = route_document_decision(context_text)
                    predictions = [decision["lead_id"]] if decision.get("action") == "existing" and decision.get("lead_id") else []
                    aggregated_predictions.extend(predictions)
                    context_results.append({
                        "context_id": context.get("context_id", "CTX-1"),
                        "text": context_text,
                        "predicted_leads": predictions,
                        "routing_decision": decision,
                    })
                results.append({
                    "filename": name,
                    "text": text,
                    "predicted_leads": list(set(aggregated_predictions)),
                    "pages": pages_count,
                    "contexts": context_results,
                })
        return {"status": "ok", "analysis": results}
    except Exception as e: return {"error": str(e)}

@app.post("/api/confirm-upload")
async def confirm_upload(request: Request):
    data = await request.json()
    processed = 0
    for item in data.get("items", []):
        text = clean_intake_text(item.get("text", ""))
        name = item.get("filename", "")
        pages_count = item.get("pages", 1)

        contexts = item.get("contexts") or []
        if contexts:
            for context in contexts:
                context_text = clean_intake_text(context.get("text", ""))
                target_ids = context.get("predicted_leads", [])
                if not context_text or not target_ids:
                    continue
                context_name = name if len(contexts) == 1 else f"{name} ({context.get('context_id', 'CTX')})"
                for t_id in target_ids:
                    sid = str(uuid.uuid4())[:8]
                    meta = {"id": sid, "name": context_name, "at": datetime.now().isoformat()}
                    ingest_to_faiss(context_text, meta, t_id)
                    save_source_db({**meta, "lead_id": t_id, "pages": pages_count, "chunks": 1})
                    append_context_to_lead(t_id, context_text, context_name)
                processed += 1
        else:
            target_ids = item.get("predicted_leads", [])
            if text and target_ids:
                for t_id in target_ids:
                    sid = str(uuid.uuid4())[:8]
                    meta = {"id": sid, "name": name, "at": datetime.now().isoformat()}
                    ingest_to_faiss(text, meta, t_id)
                    save_source_db({**meta, "lead_id": t_id, "pages": pages_count, "chunks": 1})
                    append_context_to_lead(t_id, text, name)
                processed += 1
    return {"status": "ok", "processed": processed}

@app.post("/api/history/add")
async def add_history(data: dict):
    save_history_db(data)
    return {"status": "ok"}

@app.get("/api/artifacts/{lead_id}")
async def get_artifacts(lead_id: str):
    db = get_db(); c = db.cursor(dictionary=True)
    try:
        c.execute(
            """SELECT action_taken, payload, created_at
               FROM agent_logs
               WHERE lead_id=%s AND action_taken LIKE 'artifact:%'
               ORDER BY created_at DESC""",
            (lead_id,),
        )
        rows = c.fetchall()
        for r in rows:
            r['agent_id'] = (r.get('action_taken') or '').split(':', 1)[1] if ':' in (r.get('action_taken') or '') else r.get('action_taken')
            try: r['data'] = json.loads(r['payload']) if r.get('payload') else None
            except: pass
            r['at'] = r.get('created_at')
        return {"status": "success", "artifacts": rows}
    finally: c.close(); db.close()

@app.post("/api/artifacts/save")
async def save_artifact(request: Request):
    data = await request.json()
    lead_id = data.get("lead_id"); agent_id = data.get("agent_id"); content = data.get("content")
    if not lead_id or not agent_id: return {"error": "Lead ID and Agent ID required"}
    db = get_db(); c = db.cursor()
    try:
        aid = f"{lead_id}_{agent_id}"
        _log_agent_entry(c, _get_project_id_for_lead_db(lead_id), lead_id, "artifact_store", f"artifact:{agent_id}", content)
        db.commit(); return {"status": "success", "artifact_id": aid}
    finally: c.close(); db.close()

class WorkflowRefineRequest(BaseModel):
    current_flow: str
    feedback: str
    lead_id: Optional[str] = None

@app.post("/api/agents/workflow-analyze")
async def run_workflow_analyze(request: WorkflowAnalyzeRequest):
    if not request.transcript.strip(): return {"error": "Transcript text is required."}
    try:
        processed_context = clean_intake_text(request.transcript)
        analysis_input = processed_context or request.transcript.strip()
        results = await run_workflow_agent(analysis_input, get_model, request.feedback or "")
        
        # Validation Gate Check
        as_is_text = results.get("as_is", "")
        to_be_text = results.get("to_be", "")
        if "INVALID_CONTEXT" in as_is_text or "INVALID_CONTEXT" in to_be_text:
            return {"error": "Invalid Input: The text provided does not appear to be a valid meeting transcript, project discussion, or set of requirements. Please provide actual context rather than raw code or conversational filler."}

        project_id = await run_in_threadpool(
            save_project_context_db,
            {
                "project_id": request.project_id,
                "lead_id": request.lead_id,
                "source_files": request.source_files or [],
                "raw_context": request.transcript.strip(),
                "processed_context": analysis_input,
                "workflow_analysis": results,
            },
        )

        return {
            "status": "success",
            "project_id": project_id,
            "processed_context": analysis_input,
            "analysis": results,
        }
    except Exception as e: return {"error": str(e)}


@app.post("/api/agents/workflow-analyze/upload")
async def run_workflow_analyze_upload(
    files: List[UploadFile] = File(...),
    lead_id: str = Form(None),
    project_id: str = Form(None),
):
    source_files = list(files or [])
    if not source_files:
        return JSONResponse(status_code=400, content={"error": "At least one upload file is required"})

    transcript, source_filenames = await extract_requirement_texts_from_uploads(source_files)
    if not transcript:
        return JSONResponse(status_code=400, content={"error": "No readable text found in uploaded files"})

    try:
        processed_context = clean_intake_text(transcript)
        analysis_input = processed_context or transcript
        results = await run_workflow_agent(analysis_input, get_model)

        as_is_text = results.get("as_is", "")
        to_be_text = results.get("to_be", "")
        if "INVALID_CONTEXT" in as_is_text or "INVALID_CONTEXT" in to_be_text:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "Invalid Input: The uploaded files do not contain a usable workflow discussion or transcript."
                },
            )

        saved_project_id = await run_in_threadpool(
            save_project_context_db,
            {
                "project_id": project_id,
                "lead_id": lead_id,
                "source_files": source_filenames,
                "raw_context": transcript,
                "processed_context": analysis_input,
                "workflow_analysis": results,
            },
        )

        return {
            "status": "success",
            "project_id": saved_project_id,
            "source_files": source_filenames,
            "processed_context": analysis_input,
            "analysis": results,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/agents/workflow-refine")
async def run_workflow_refine_endpoint(request: WorkflowRefineRequest):
    if not request.current_flow.strip() or not request.feedback.strip():
        return {"error": "Current flow and feedback are required."}
    try:
        revised = await run_workflow_refine(request.current_flow, request.feedback, get_model)
        return {"status": "success", "revised_flow": revised}
    except Exception as e: return {"error": str(e)}

# ═══════════════════════════════════════════════════════
# WORKFLOW ARTIFACTS — Session-based CRUD
# ═══════════════════════════════════════════════════════

@app.get("/api/workflow-artifacts/{project_id}")
async def get_workflow_sessions(project_id: str):
    """Get all workflow sessions for a project."""
    db = get_db(); c = db.cursor(dictionary=True)
    try:
        c.execute("""
            SELECT version,
                   MAX(client_approved) as client_approved,
                   MIN(created_at) as created_at,
                   MAX(updated_at) as updated_at
            FROM workflows 
            WHERE project_id = %s 
            GROUP BY version
            ORDER BY version DESC
        """, (project_id,))
        sessions = c.fetchall()
        for s in sessions:
            c.execute(
                """SELECT content
                   FROM design_documents
                   WHERE project_id=%s AND doc_type=%s
                   ORDER BY updated_at DESC
                   LIMIT 1""",
                (project_id, f"workflow_session_v{s['version']}"),
            )
            doc = c.fetchone()
            doc_payload = _decode_json_blob((doc or {}).get("content")) if doc else {}
            s["session_title"] = (doc_payload or {}).get("session_title") or f"Session {s['version']}"
            s['client_approved'] = bool(s['client_approved'])
            s['created_at'] = s['created_at'].isoformat() if s['created_at'] else None
            s['updated_at'] = s['updated_at'].isoformat() if s['updated_at'] else None
        return {"status": "success", "sessions": sessions}
    finally: c.close(); db.close()

@app.get("/api/workflow-artifacts/{project_id}/{version}")
async def get_workflow_session_detail(project_id: str, version: int):
    """Get full AS-IS + TO-BE for a specific session version."""
    db = get_db(); c = db.cursor(dictionary=True)
    try:
        c.execute("""
            SELECT id, type, nodes, client_approved, version, created_at, updated_at
            FROM workflows 
            WHERE project_id = %s AND version = %s
        """, (project_id, version))
        rows = c.fetchall()
        result = {"version": version, "session_title": "", "as_is": "", "to_be": "", "client_approved": False, "raw_transcript": ""}
        c.execute(
            """SELECT content
               FROM design_documents
               WHERE project_id=%s AND doc_type=%s
               ORDER BY updated_at DESC
               LIMIT 1""",
            (project_id, f"workflow_session_v{version}"),
        )
        doc = c.fetchone()
        doc_payload = _decode_json_blob((doc or {}).get("content")) if doc else {}
        for r in rows:
            r['client_approved'] = bool(r['client_approved'])
            r['created_at'] = r['created_at'].isoformat() if r['created_at'] else None
            r['updated_at'] = r['updated_at'].isoformat() if r['updated_at'] else None
            result['session_title'] = (doc_payload or {}).get('session_title') or f"Session {version}"
            result['raw_transcript'] = (doc_payload or {}).get('raw_transcript', '') or ''
            result['client_approved'] = r['client_approved']
            if r['type'] == 'as_is': result['as_is'] = r['nodes'] or ''
            elif r['type'] == 'to_be': result['to_be'] = r['nodes'] or ''
        return {"status": "success", "session": result}
    finally: c.close(); db.close()

@app.post("/api/workflow-artifacts/save")
async def save_workflow_session(request: Request):
    """Save or update a workflow session (both AS-IS and TO-BE)."""
    data = await request.json()
    project_id = data.get("project_id")
    version = data.get("version", 1)
    session_title = data.get("session_title", f"Session {version}")
    as_is = data.get("as_is", "")
    to_be = data.get("to_be", "")
    approved = data.get("client_approved", False)
    transcript = data.get("raw_transcript", "")
    if not project_id: return {"error": "project_id is required"}
    
    db = get_db(); c = db.cursor()
    try:
        as_is_id = f"{project_id}_v{version}_as_is"
        to_be_id = f"{project_id}_v{version}_to_be"

        c.execute(
            """INSERT INTO workflows (id, project_id, type, nodes, client_approved, version, generated_by_agent, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
               ON DUPLICATE KEY UPDATE nodes=VALUES(nodes), client_approved=VALUES(client_approved), updated_at=NOW()""",
            (as_is_id, project_id, "as_is", as_is, int(bool(approved)), version, 1),
        )
        c.execute(
            """INSERT INTO workflows (id, project_id, type, nodes, client_approved, version, generated_by_agent, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
               ON DUPLICATE KEY UPDATE nodes=VALUES(nodes), client_approved=VALUES(client_approved), updated_at=NOW()""",
            (to_be_id, project_id, "to_be", to_be, int(bool(approved)), version, 1),
        )
        _upsert_project_record(c, project_id, stage="workflow", name=session_title)
        _write_design_document(
            c,
            project_id,
            f"workflow_session_v{version}",
            session_title,
            {"version": version, "session_title": session_title, "raw_transcript": transcript},
            version=version,
        )
        
        db.commit()
        return {"status": "success", "version": version}
    except Exception as e:
        return {"error": str(e)}
    finally: c.close(); db.close()

@app.post("/api/workflow-artifacts/approve")
async def approve_workflow_session(request: Request):
    """Approve a specific workflow session version."""
    data = await request.json()
    project_id = data.get("project_id")
    version = data.get("version", 1)
    if not project_id: return {"error": "project_id is required"}
    
    db = get_db(); c = db.cursor()
    try:
        c.execute("UPDATE workflows SET client_approved = TRUE WHERE project_id = %s AND version = %s", (project_id, version))
        workflow_session = _load_workflow_session_artifact_db(project_id, version)
        existing_handoff = get_requirements_handoff_db(project_id)
        requirements_state = (existing_handoff or {}).get("requirements_state") or _load_normalized_requirements_state_db(project_id) or {}
        if isinstance(requirements_state, dict):
            requirements_state = dict(requirements_state)
            requirements_state.setdefault("workflow_session_version", (existing_handoff or {}).get("requirements_state", {}).get("workflow_session_version"))
        if workflow_session or requirements_state:
            _save_requirements_handoff_bundle_db(
                c,
                project_id,
                None,
                workflow_session or {"version": version, "client_approved": True},
                requirements_state,
            )
        db.commit()
        return {"status": "success"}
    finally: c.close(); db.close()

@app.delete("/api/workflow-artifacts/{project_id}/{version}")
async def delete_workflow_session(project_id: str, version: int):
    """Delete a workflow session version."""
    db = get_db(); c = db.cursor()
    try:
        c.execute("DELETE FROM workflows WHERE project_id = %s AND version = %s", (project_id, version))
        c.execute("DELETE FROM design_documents WHERE project_id = %s AND doc_type = %s", (project_id, f"workflow_session_v{version}"))
        db.commit()
        return {"status": "success"}
    except Exception as e:
        return {"error": str(e)}
    finally: c.close(); db.close()


@app.post("/api/sprint-task-artifacts/save")
async def save_sprint_task_artifact(request: Request):
    data = await request.json()
    project_id = data.get("project_id")
    workflow_id = data.get("workflow_id")
    if not project_id or not workflow_id:
        return {"error": "project_id and workflow_id are required"}

    artifact_id = await run_in_threadpool(
        upsert_sprint_task_artifact_db,
        project_id,
        str(workflow_id),
        data.get("workflow_name"),
        int(data.get("session_version") or 1),
        data.get("session_title"),
        data.get("generated_tasks") or [],
        data.get("task_comments") or {},
        data.get("task_logs") or {},
        data.get("board_state") or {},
    )
    return {"status": "success", "artifact_id": artifact_id}


@app.get("/api/sprint-task-artifacts/{project_id}/{workflow_id}/{session_version}")
async def get_sprint_task_artifact(project_id: str, workflow_id: str, session_version: int):
    artifact = await run_in_threadpool(get_sprint_task_artifact_db, project_id, workflow_id, session_version)
    if not artifact:
        return {"status": "not_found", "artifact": None}
    return {"status": "success", "artifact": artifact}


@app.post("/api/chat")
async def chat(request: Request):
    data = await request.json()
    query = data.get("query", "").strip()
    lead_id = data.get("lead_id")
    if not lead_id: return {"error": "Lead ID required"}
    thread_id = data.get("thread_id", "default")
    
    save_history_db({"lead_id": lead_id, "role": "user", "text": query, "thread_id": thread_id})

    lead_row = get_lead_db(lead_id)
    active_lead_info = json.dumps(lead_row, indent=2, default=str) if lead_row else "Unknown Lead"

    context_docs = search_vault(query, lead_id, k=10)
    
    def format_context_with_tags(docs):
        formatted = []
        for d in docs:
            name = d.metadata.get("name", "unknown")
            name_lower = name.lower()
            if any(x in name_lower for x in ["transcript", "call", "meeting"]): source_type = "transcript"
            elif any(x in name_lower for x in ["email", "thread", "message", ".eml"]): source_type = "email"
            else: source_type = "pdf / doc"
            formatted.append(f"[{source_type.upper()} — {name}]\n{d.page_content}\n")
        return "\n---\n".join(formatted) if formatted else "No relevant context retrieved for this query."
        
    context_text = format_context_with_tags(context_docs)
    lead_sources = load_sources(lead_id)
    source_names = [s['name'] for s in lead_sources]
    source_inventory = ", ".join(source_names) if source_names else "None"

    system_prompt = f"""You are the ViljeTech AI Lead Expert — a sales intelligence operative analyzing a specific lead for the ViljeTech team (Marcus, Bharat, Christofer Ohlsson).

CURRENT LEAD: {active_lead_info}
DOCUMENT INVENTORY: {source_inventory}

SOURCE REASONING RULES:
- TRANSCRIPT chunks → identify spoken intent, objections, pain points, action items, and sentiment.
- EMAIL chunks → extract commitments, deadlines, follow-up requests, and relationship tone.
- PDF / DOC chunks → extract project scope, technical requirements, constraints, and decisions.

OPERATIONAL RULES:
1. Answer ONLY using the Document Inventory and RAG Context below. Never invent facts.
2. For inventory/count questions, use the Document Inventory list only.
3. For content questions, reason according to the source type rules above.
4. If sources conflict, present both perspectives and flag the discrepancy explicitly.
5. If the answer isn't in the library, say: "This information isn't in the document library."
6. If uncertain, state it and suggest what additional documents would help.
7. When quoting or referencing, always cite the source name and type (e.g. "Per the March 12 transcript...").

RESPONSE FORMAT:
- Lead with the direct answer, then supporting detail.
- Use bullet points for lists, short paragraphs for analysis.
- For multi-source answers, group insights by source type.

RAG CONTEXT:
{context_text}"""
    
    history_objs = load_history(lead_id, thread_id)
    messages = [SystemMessage(content=system_prompt)]
    for h in history_objs[:-1]:
        if h['role'] == 'user': messages.append(HumanMessage(content=h['text']))
        else: messages.append(AIMessage(content=h['text']))
            
    messages.append(HumanMessage(content=query))
    response = get_model().invoke(messages)
    
    answer = response.content
    sources = list(set([d.metadata.get('name', 'Unknown') for d in context_docs]))
    save_history_db({"lead_id": lead_id, "role": "assistant", "text": answer, "sources": sources, "thread_id": thread_id})
    
    return {"answer": answer, "sources": sources}

# (Requirements agent logic temporarily removed as per client request)

@app.delete("/api/threads/{tid}")
async def delete_thread(tid: str, lead_id: Optional[str] = None):
    db = get_db(); c = db.cursor()
    try:
        if tid == "default" or tid == "null":
            # Purge the unassigned/default history
            if lead_id:
                c.execute("DELETE FROM chat_messages WHERE thread_id=%s", (_chat_thread_storage_id(lead_id, 'default'),))
            else:
                c.execute("DELETE FROM chat_messages WHERE thread_id LIKE 'default:%'")
        else:
            # Purge a specific active thread
            c.execute("DELETE FROM chat_messages WHERE thread_id=%s", (tid,))
            c.execute("DELETE FROM chat_threads WHERE id=%s", (tid,))
        
        db.commit()
        return {"status": "Thread and history purged"}
    except Error as e:
        print(f"Purge error: {e}")
        return {"error": str(e)}
    finally:
        c.close(); db.close()


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("API_PORT", "8000")))
    uvicorn.run(app, host=host, port=port)
