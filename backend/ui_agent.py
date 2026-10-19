import os
import asyncio
import json
import re
import mysql.connector
import traceback
import uuid
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient

# Add local imports for model access
try:
    from .core import get_model
    from langchain_core.messages import SystemMessage, HumanMessage
except ImportError:
    get_model = None

# Load environment from parent directory where .env is located
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv()

def _get_env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default

# --- DB CONFIG ---
DB_HOST = _get_env("db_host", "DB_HOST", "MYSQLHOST", "MYSQL_HOST", default="127.0.0.1")
DB_USER = _get_env("db_username", "DB_USER", "MYSQLUSER", "MYSQL_USER", default="root")
DB_PASSWORD = _get_env("db_password", "DB_PASSWORD", "MYSQLPASSWORD", "MYSQL_PASSWORD")
DB_NAME = _get_env("db_name", "DB_NAME", "MYSQLDATABASE", "MYSQL_DATABASE", default="Project Management")
DB_PORT = int(_get_env("db_port", "DB_PORT", "MYSQLPORT", "MYSQL_PORT", default="3306"))

def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        port=DB_PORT
    )


def _resolve_doc_lead_id(project_ref: str) -> str:
    """Resolve a project reference to the lead_id used by doc artifacts."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT lead_id FROM projects WHERE id=%s LIMIT 1", (project_ref,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row and row.get("lead_id"):
            return row["lead_id"]
    except Exception:
        pass
    return project_ref


def _log_ui_trace(message: str, **details):
    payload = {"message": message, **details}
    print(f"[UI_AGENT] {payload}")

def sanitize_extracted_code(code: str) -> str:
    """
    Cleans up extracted React code, removing trailing metadata, JSON junk,
    and unescaping common JSON/Unicode escape sequences.
    """
    if not code:
        return ""
    
    # 1. Clip everything after the mandatory end marker
    end_marker = "window.App = App;"
    if end_marker in code:
        # Take the part before the marker and include the marker itself
        code = code.split(end_marker)[0] + end_marker
    
    # 2. Unescape common JSON sequences if they appear to be escaped
    if '\\n' in code or '\\"' in code or '\\u' in code:
        try:
            # We use a trick: wrap in a JSON string and parse it to let Python's json engine handle escapes
            # But we must be careful not to double-escape. 
            # If it's just raw code with stray escapes, we do manual replacement.
            code = code.replace('\\n', '\n')
            code = code.replace('\\"', '"')
            code = code.replace('\\\\', '\\')
            code = code.replace('\\/', '/')
            
            # Handle Unicode escapes like \u0027 using regex
            code = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), code)
        except Exception as e:
            print(f"⚠️ Sanitization unescape warning: {e}")

    # 3. Remove trailing markdown backticks if they were captured
    code = code.split("```")[0].strip()
    
    # 4. Final cleaning of leading/trailing whitespace or stray quotes from JSON wrapping
    code = code.strip().strip('"').strip("'").strip()
    
    return code

# Validate API Key early
STITCH_API_KEY = os.getenv("STITCH_API_KEY") or os.getenv("GOOGLE_API_KEY")

servers = {
    "stitch": {
        "url": "https://stitch.googleapis.com/mcp",
        "transport": "streamable_http",
        "headers": {
            "X-Goog-Api-Key": STITCH_API_KEY
        }
    }
}

async def generate_ui_synthesis(project_id, workflow_id, session_version, check_only=False):
    """
    Orchestrates the UI synthesis flow with robust code extraction and unified output.
    """
    if not STITCH_API_KEY:
        return {"status": "error", "message": "Missing STITCH_API_KEY or GOOGLE_API_KEY in environment."}

    _log_ui_trace(
        "start",
        mode="check" if check_only else "synthesize",
        project_id=project_id,
        workflow_id=workflow_id,
        session_version=session_version,
        stitch_configured=bool(STITCH_API_KEY),
    )
    
    try:
        # 0. PERSISTENCE CHECK: Does this session already have a generated UI?
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            # Cast for consistency
            p_str = str(project_id)
            w_str = str(workflow_id)
            v_int = int(session_version) if session_version else 1
            
            check_query = "SELECT ui_code, stitch_project_id FROM ui_artifacts WHERE project_id = %s AND workflow_id = %s AND session_version = %s"
            cursor.execute(check_query, (p_str, w_str, v_int))
            existing = cursor.fetchone()
            if existing:
                _log_ui_trace("cached_artifact_found", project_id=p_str, workflow_id=w_str, session_version=v_int)
                return {
                    "status": "success",
                    "message": "UI Artifact retrieved from persistent storage.",
                    "code": existing['ui_code'],
                    "stitch_project": existing['stitch_project_id'],
                    "workflow_version": v_int
                }
            
            # IF CHECK ONLY: Return not_found instead of proceeding to synthesis
            if check_only:
                _log_ui_trace("cache_miss_check_only", project_id=p_str, workflow_id=w_str, session_version=v_int)
                return {
                    "status": "not_found",
                    "message": "No existing UI design found for this session."
                }

            _log_ui_trace("cache_miss_proceed", project_id=p_str, workflow_id=w_str, session_version=v_int)
        except Exception as db_e:
            _log_ui_trace("persistence_check_warning", error=str(db_e), project_id=p_str, workflow_id=w_str)
        finally:
            cursor.close()
            conn.close()

        # 1. FETCH CONTEXT FROM DATABASE
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            lead_ref = _resolve_doc_lead_id(p_str)
            _log_ui_trace("resolved_lead", project_id=p_str, resolved_lead_id=lead_ref, workflow_id=w_str)
            
            # 1a. FETCH WORKFLOW NODES (The Visual Map)
            # Alignment: project_id, version, and client_approved
            cursor.execute(
                """SELECT nodes, id FROM workflows 
                   WHERE project_id=%s AND version=%s AND client_approved=1 
                   LIMIT 1""",
                (project_id, session_version)
            )
            wf_row = cursor.fetchone()
            if not wf_row:
                _log_ui_trace("workflow_missing", project_id=p_str, workflow_id=w_str, session_version=v_int)
            workflow_data = wf_row['nodes'] if wf_row else "No approved TO-BE workflow found."
            
            # 1b. FETCH ARCHITECTURAL DOCS (HLD/LLD)
            # Alignment: lead_id (project), workflow_id (type/instance), and version
            cursor.execute(
                """SELECT hld_content, lld_content, db_schema, project_summary 
                FROM doc_agent_artifacts 
                WHERE lead_id=%s AND workflow_id=%s AND version=%s 
                LIMIT 1""",
                (lead_ref, workflow_id, session_version)
            )
            doc_row = cursor.fetchone()
            
            if not doc_row:
                _log_ui_trace("doc_artifact_fallback_lookup", resolved_lead_id=lead_ref, workflow_id=w_str)
                cursor.execute(
                    "SELECT hld_content, lld_content, db_schema, project_summary FROM doc_agent_artifacts WHERE lead_id=%s AND workflow_id=%s ORDER BY version DESC LIMIT 1",
                    (lead_ref, workflow_id)
                )
                doc_row = cursor.fetchone()
        finally:
            if conn:
                conn.close()
        
        if not doc_row:
            _log_ui_trace("doc_artifact_missing", resolved_lead_id=lead_ref, workflow_id=w_str, session_version=v_int)
            return {"status": "error", "message": "Missing architectural artifacts (HLD/LLD). Please generate them first."}

        hld = doc_row.get('hld_content', '')
        lld = doc_row.get('lld_content', '')
        summary = doc_row.get('project_summary', '')

        # 2. CONNECT TO MCP
        client = MultiServerMCPClient(servers)
        tools = await client.get_tools()
        
        # 3. DISCOVER OR CREATE UNIQUE PROJECT (FOLDER)
        # We use a unique title to ensure separation as requested by the user
        target_project_title = f"PRJ_{project_id}_WF_{workflow_id}_SESS_{session_version}"
        stitch_project_id = None
        
        list_tool = next((t for t in tools if "list_projects" in t.name), None)
        if list_tool:
            _log_ui_trace("stitch_search", target_project_title=target_project_title)
            projects_resp = await list_tool.ainvoke({})
            
            # Handle list/dict responses (modern MCP style)
            if isinstance(projects_resp, list):
                for p in projects_resp:
                    if p.get('title') == target_project_title:
                        # Extract ID from 'projects/ID' or just use 'name'
                        name = p.get('name', '')
                        stitch_project_id = name.split('/')[-1] if '/' in name else name
                        break
            
            # Fallback to robust string parsing for older/different MCP adapters
            if not stitch_project_id:
                resp_str = str(projects_resp)
                # Robust search for project ID associated with our specific title
                match = re.search(fr"projects/([^/\s\":'\",\)]+).*?{re.escape(target_project_title)}", resp_str, re.IGNORECASE | re.DOTALL)
                if not match:
                    match = re.search(fr"{re.escape(target_project_title)}.*?projects/([^/\s\":'\",\)]+)", resp_str, re.IGNORECASE | re.DOTALL)
                
                if match:
                    stitch_project_id = match.group(1)

            if stitch_project_id:
                _log_ui_trace("stitch_project_found", stitch_project_id=stitch_project_id)

        if not stitch_project_id:
            create_tool = next((t for t in tools if "create_project" in t.name), None)
            if create_tool:
                _log_ui_trace("stitch_create", target_project_title=target_project_title)
                create_resp = await create_tool.ainvoke({"title": target_project_title})
                # Extract ID from creation response
                ids = re.findall(r"projects/([^/\s\"':,]+)", str(create_resp))
                if ids: 
                    stitch_project_id = ids[0]
                    _log_ui_trace("stitch_project_created", stitch_project_id=stitch_project_id)

        if not stitch_project_id:
            return {"status": "error", "message": "Stitch project connection failed or could not be created."}

        # 4. EXECUTE SYNTHESIS
        synthesis_tool = next((t for t in tools if "generate_screen_from_text" in t.name), None)
        if not synthesis_tool:
            # Fallback for different tool names
            synthesis_tool = next((t for t in tools if "generate" in t.name and "screen" in t.name), None)
            
        if not synthesis_tool:
            return {"status": "error", "message": "Stitch synthesis tool not found in MCP server. Available tools: " + ", ".join([t.name for t in tools])}

        # Optimized truncation: 15,000 chars is the "sweet spot"
        hld_truncated = hld[:15000] if hld else ''
        lld_truncated = lld[:15000] if lld else ''
        workflow_truncated = workflow_data[:10000] if workflow_data else ''
        
        prompt = f"""
        [SYSTEM OVERRIDE: RAW CODE OUTPUT ONLY]
        [NO MARKDOWN][NO PROSE][NO SUMMARY][NO REPORTS]
        
        TASK: Return the pure React/HTML code for a high-fidelity industrial dashboard.
        
        SPECIFICATION:
        1. STRUCTURE: Modular React components orchestrated by 'App'.
        2. STYLE: Tailwind CSS, Industrial Dark Mode (#0F172A).
        3. DATA: Use realistic business data from the Context below.
        4. MARKER: End with 'window.App = App;'
        
        CONTEXT:
        - Summary: {summary}
        - Workflow: {workflow_truncated}
        - LLD: {lld_truncated}
        
        FINAL INSTRUCTION: Do NOT provide any text or markdown. Start immediately with <!DOCTYPE html>.
        """
        
        _log_ui_trace("stitch_dispatch", stitch_project_id=stitch_project_id)
        result = None
        try:
            result = await synthesis_tool.ainvoke({
                "projectId": stitch_project_id,
                "prompt": prompt
            })
        except Exception as e:
            # Handle Python 3.11+ ExceptionGroup (TaskGroup errors)
            if hasattr(e, 'exceptions'):
                root_error = e.exceptions[0] if e.exceptions else e
                print(f"❌ Synthesis TaskGroup failed: {type(root_error).__name__}: {root_error}")
                traceback.print_exc()
                return {"status": "error", "message": f"Stitch Synthesis Task failed: {type(root_error).__name__}: {str(root_error)}"}
            print(f"❌ Synthesis direct error: {e}")
            return {"status": "error", "message": f"Stitch Synthesis Dispatch failed: {str(e)}"}

        # 5. SIMPLE EXTRACTION: Get the HTML from Stitch's downloadUrl
        raw_content = ""
        try:
            if hasattr(result, "content") and isinstance(result.content, list):
                parts = []
                for item in result.content:
                    if hasattr(item, "text"):
                        parts.append(item.text)
                    elif isinstance(item, dict) and "text" in item:
                        parts.append(item["text"])
                    else:
                        parts.append(str(item))
                raw_content = "\n".join(parts)
            elif hasattr(result, "text"):
                raw_content = result.text
            else:
                raw_content = str(result)
        except Exception as e:
            print(f"⚠️ Raw extraction warning: {e}")
            raw_content = str(result)
            
        # PERSIST RAW OUTPUT for debugging
        try:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            artifacts_dir = os.path.join(project_root, "artifacts")
            os.makedirs(artifacts_dir, exist_ok=True)
            output_path = os.path.join(artifacts_dir, "stitch_raw_output.txt")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(raw_content)
        except: pass

        # 6. FIND THE downloadUrl & screenId
        download_url = None
        stitch_screen_id = None
        
        # Try JSON parse first
        try:
            # Stitch might return a string representation of a list/dict, or actual JSON
            data = None
            try:
                data = json.loads(raw_content)
            except:
                # If it's a string representation of a Python list (common in some MCP adapters)
                import ast
                data = ast.literal_eval(raw_content)
            
            # Recursive search for screens in the JSON tree
            def find_screen_id(obj):
                if isinstance(obj, dict):
                    # Check for 'text' field which might contain stringified JSON (Stitch quirk)
                    if "text" in obj and isinstance(obj["text"], str) and obj["text"].startswith("{"):
                        try:
                            res = find_screen_id(json.loads(obj["text"]))
                            if res: return res
                        except: pass
                        
                    if "htmlCode" in obj and "downloadUrl" in obj["htmlCode"]:
                        # This is the gold mine: actual HTML code
                        d_url = obj["htmlCode"]["downloadUrl"]
                        s_name = obj.get("name", "")
                        s_id = s_name.split("/")[-1] if "/screens/" in s_name else None
                        return d_url, s_id
                        
                    for k, v in obj.items():
                        res = find_screen_id(v)
                        if res: return res
                elif isinstance(obj, list):
                    for item in obj:
                        res = find_screen_id(item)
                        if res: return res
                return None

            search_res = find_screen_id(data)
            if search_res:
                download_url, stitch_screen_id = search_res
                _log_ui_trace("stitch_screen_found", stitch_screen_id=stitch_screen_id)
        except Exception as e:
            _log_ui_trace("json_parse_skipped", error=str(e))
            pass
        
        # Regex fallback (specifically targeting htmlCode block)
        if not download_url:
            _log_ui_trace("regex_fallback_start")
            # Look for the downloadUrl that is immediately preceded by "htmlCode"
            # This avoids picking up the PNG "screenshot" URL which usually comes first
            html_url_match = re.search(r'"htmlCode"\s*:\s*\{[^}]*"downloadUrl"\s*:\s*"([^"]+)"', raw_content)
            id_match = re.search(r'"name"\s*:\s*"[^"]+/screens/([^"]+)"', raw_content)
            
            if html_url_match:
                download_url = html_url_match.group(1)
                if id_match:
                    stitch_screen_id = id_match.group(1)
                _log_ui_trace("stitch_screen_regex_recovery", stitch_screen_id=stitch_screen_id)
            else:
                # Last resort: find any URL that looks like a code download
                any_code_url = re.search(r'"downloadUrl"\s*:\s*"(https://contribution\.usercontent\.google\.com/[^"]+)"', raw_content)
                if any_code_url:
                    download_url = any_code_url.group(1)
                    _log_ui_trace("last_resort_url_recovery")
        
        if not download_url:
            _log_ui_trace("missing_download_url", raw_preview=raw_content[:300] if raw_content else "Empty response")
            return {
                "status": "error", 
                "message": "Stitch did not return a downloadUrl for htmlCode.",
                "raw_preview": raw_content[:300] if raw_content else "Empty response"
            }

        # 7. DOWNLOAD THE HTML — This is the actual UI that Stitch renders
        _log_ui_trace("downloading_html", download_url=download_url[:80])
        generated_code = ""
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            resp = await http_client.get(download_url, follow_redirects=True)
            if resp.status_code == 200:
                if resp.content.startswith(b'\x89PNG'):
                    _log_ui_trace("stitch_returned_png")
                    return {"status": "error", "message": "Stitch returned a PNG mockup instead of HTML code."}
                generated_code = resp.text
                _log_ui_trace("html_downloaded", length=len(generated_code))
            else:
                _log_ui_trace("download_failed", status_code=resp.status_code)
                return {"status": "error", "message": f"Failed to download code from Stitch (HTTP {resp.status_code})"}

        if not generated_code or len(generated_code) < 50:
            _log_ui_trace("downloaded_code_too_small", length=len(generated_code or ""))
            return {"status": "error", "message": "Downloaded HTML from Stitch was empty."}
        
        # 8. PERSIST TO DATABASE (No debugger, no sanitizer — raw Stitch HTML)
        try:
            p_str = str(project_id)
            w_str = str(workflow_id)
            v_int = int(session_version) if session_version else 1
            
            _log_ui_trace("saving_html", project_id=p_str, workflow_id=w_str, session_version=v_int, size=len(generated_code))
            conn = get_db_connection()
            cursor = conn.cursor()
            artifact_id = str(uuid.uuid4())
            
            save_query = """
                INSERT INTO ui_artifacts (id, project_id, workflow_id, session_version, ui_code, stitch_project_id, stitch_screen_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    ui_code = VALUES(ui_code), 
                    stitch_project_id = VALUES(stitch_project_id),
                    stitch_screen_id = VALUES(stitch_screen_id),
                    created_at = CURRENT_TIMESTAMP
            """
            cursor.execute(save_query, (artifact_id, p_str, w_str, v_int, generated_code, stitch_project_id, stitch_screen_id))
            conn.commit()
            _log_ui_trace("save_success", session_version=v_int)
            cursor.close()
            conn.close()
        except Exception as save_e:
            _log_ui_trace("save_failed", error=str(save_e))
            traceback.print_exc()

        return {
            "status": "success",
            "message": "UI Synthesis completed and persisted.",
            "code": generated_code,
            "stitch_project": stitch_project_id,
            "workflow_version": session_version
        }
    except Exception as e:
        _log_ui_trace("synthesis_error", error=str(e), project_id=project_id, workflow_id=workflow_id, session_version=session_version)
        traceback.print_exc()
        return {"status": "error", "message": f"Synthesis Error: {str(e)}"}

async def generate_ui_refinement(project_id, workflow_id, session_version, feedback):
    """
    Refines an existing UI synthesis based on user feedback.
    """
    if not STITCH_API_KEY:
        return {"status": "error", "message": "Missing API Key."}

    print(f"🔄 TRACER: Refining UI for PID:[{project_id}], WFID:[{workflow_id}], VER:[{session_version}]")
    
    try:
        p_str = str(project_id)
        w_str = str(workflow_id)
        v_int = int(session_version) if session_version else 1

        # 1. FETCH CURRENT ARTIFACT & CONTEXT
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        lead_ref = _resolve_doc_lead_id(p_str)
        
        # Get latest UI code and Stitch project ID for the exact workflow version first.
        cursor.execute(
            """SELECT ui_code, stitch_project_id, stitch_screen_id 
               FROM ui_artifacts 
               WHERE project_id=%s AND workflow_id=%s AND session_version=%s 
               ORDER BY created_at DESC LIMIT 1""",
            (p_str, w_str, v_int)
        )
        current_ui = cursor.fetchone()

        # Fall back to the most recent saved UI for this project/workflow if the version changed.
        if not current_ui:
            cursor.execute(
                """SELECT ui_code, stitch_project_id, stitch_screen_id, session_version
                   FROM ui_artifacts 
                   WHERE project_id=%s AND workflow_id=%s 
                   ORDER BY session_version DESC, created_at DESC LIMIT 1""",
                (p_str, w_str)
            )
            current_ui = cursor.fetchone()
        
        # Get HLD/LLD context
        cursor.execute(
            "SELECT hld_content, lld_content, project_summary FROM doc_agent_artifacts WHERE lead_id=%s AND workflow_id=%s AND version=%s",
            (lead_ref, w_str, v_int)
        )
        doc_row = cursor.fetchone()
        if not doc_row:
            cursor.execute(
                """SELECT hld_content, lld_content, project_summary, version
                   FROM doc_agent_artifacts
                   WHERE lead_id=%s AND workflow_id=%s
                   ORDER BY version DESC LIMIT 1""",
                (lead_ref, w_str)
            )
            doc_row = cursor.fetchone()
        cursor.close(); conn.close()

        if not current_ui:
            return {"status": "error", "message": "No existing UI found to refine."}

        stitch_project_id = current_ui['stitch_project_id']
        stitch_screen_id = current_ui.get('stitch_screen_id')
        current_code = current_ui['ui_code']
        summary = doc_row.get('project_summary', '') if doc_row else ""
        hld = doc_row.get('hld_content', '') if doc_row else ""
        doc_version = doc_row.get('version', v_int) if doc_row else v_int
        current_version = current_ui.get('session_version', v_int)

        # 2. CONNECT TO MCP
        client = MultiServerMCPClient(servers)
        tools = await client.get_tools()
        
        # 3. DISCOVER EDIT TOOL
        # Use 'edit_screens' for surgical refinement if we have a screen ID
        edit_tool = None
        if stitch_screen_id:
            edit_tool = next((t for t in tools if "edit_screens" in t.name), None)
            if edit_tool:
                print(f"🚀 Dispatching SURGICAL EDIT to Stitch Screen: {stitch_screen_id}")
            else:
                print("⚠️ 'edit_screens' tool not found. Falling back to synthesis.")
        
        if not edit_tool:
            # Fallback to synthesis tool (Re-generation)
            print("🔄 Falling back to 'generate_screen_from_text' (Full Re-synthesis)")
            edit_tool = next((t for t in tools if "generate_screen_from_text" in t.name), None) or \
                        next((t for t in tools if "generate" in t.name and "screen" in t.name), None)

        if not edit_tool:
            return {"status": "error", "message": "Stitch refinement tool not found."}

        # 4. EXECUTE REFINEMENT (Surgical Edit)
        # We explicitly tell Stitch to EDIT the existing component
        refine_prompt = f"""
        TASK: SURGICALLY EDIT the existing React component based on the user feedback.
        
        USER FEEDBACK: "{feedback}"
        
        INSTRUCTIONS:
        1. DO NOT START FROM SCRATCH. SURGICALLY EDIT the existing component.
        2. MIRROR ISOLATION: The target UI is a STANDALONE application. Do NOT use terms or design patterns from the 'Agentic Pipeline' (this management tool).
        3. Identify specific sections mentioned in the feedback and update only those.
        4. Maintain all existing sub-component logic and the main orchestrator (window.App = App).
        5. Preserve the industrial dark mode aesthetics and responsive grid layout.
        
        EXISTING CODE FOR REFERENCE:
        {current_code[:20000]}
        """
        
        print(f"🚀 Dispatching SURGICAL EDIT to Stitch Screen: {stitch_screen_id} in Project: {stitch_project_id}")
        
        # Prepare tool arguments
        tool_args = {
            "projectId": stitch_project_id,
            "prompt": refine_prompt
        }
        
        # If using edit_screens, specify the screenId
        if "edit_screens" in edit_tool.name and stitch_screen_id:
            tool_args["selectedScreenIds"] = [stitch_screen_id]

        result = await edit_tool.ainvoke(tool_args)

        # 5. DOWNLOAD & PROCESS (Re-using discovery logic)
        raw_content = str(result)
        download_url = None
        
        # Capture the updated screen's downloadUrl
        html_block = re.search(r'"htmlCode"\s*:\s*\{[^}]*"downloadUrl"\s*:\s*"([^"]+)"[^}]*"mimeType"\s*:\s*"text/html"', raw_content)
        if not html_block:
             html_block = re.search(r'"htmlCode"\s*:\s*\{[^}]*"mimeType"\s*:\s*"text/html"[^}]*"downloadUrl"\s*:\s*"([^"]+)"', raw_content)
        
        if html_block:
            download_url = html_block.group(1)
        
        if not download_url:
            return {"status": "error", "message": "Refinement failed to produce a valid download URL."}

        import httpx
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            resp = await http_client.get(download_url, follow_redirects=True)
            if resp.status_code == 200:
                refined_code = resp.text
            else:
                return {"status": "error", "message": "Failed to download refined code."}

        # 6. UPDATE DATABASE
        conn = get_db_connection()
        cursor = conn.cursor()
        update_query = "UPDATE ui_artifacts SET ui_code = %s, created_at = CURRENT_TIMESTAMP WHERE project_id = %s AND workflow_id = %s AND session_version = %s"
        cursor.execute(update_query, (refined_code, p_str, w_str, current_version))
        conn.commit(); cursor.close(); conn.close()

        return {
            "status": "success",
            "message": "UI Refinement completed.",
            "code": refined_code,
            "stitch_project": stitch_project_id,
            "workflow_version": current_version,
            "doc_version": doc_version
        }

    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": f"Refinement Error: {str(e)}"}
