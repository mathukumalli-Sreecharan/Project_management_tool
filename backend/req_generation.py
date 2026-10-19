import json
import os
import re
from operator import itemgetter
from typing import Any, Dict, List

from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_openai.embeddings import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field

from .workflow_analysis import (
    anchor_transcript_to_client_problem_scope,
    detect_alignment_issues,
    extract_client_intent_transcript,
)
from .workflow_postprocessing import post_process_generated_workflows

load_dotenv()


def _env_truthy(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


REQ_FAST_MODE = _env_truthy(os.getenv("REQ_FAST_MODE"), True)


class Actor(BaseModel):
    name: str = Field(description="name of the actor")
    type: str = Field(description="actor type: user, system, or external")


class Intent(BaseModel):
    goals: List[str] = Field(default_factory=list, description="business goals for the workflow")


class Capability(BaseModel):
    capability_id: str = Field(description="unique capability id (e.g., CAP-1)")
    name: str = Field(description="short capability name")
    description: str = Field(description="clear capability description")


class Requirement(BaseModel):
    req_id: str = Field(description="unique id for the requirement (e.g., REQ-1)")
    title: str = Field(description="short requirement title")
    description: str = Field(description="clear description of the requirement")
    user_story: str = Field(description="user story in the format: As a <actor>, I want <feature>, so that <benefit>")
    functional_details: List[str] = Field(default_factory=list, description="functional requirement details")
    acceptance_criteria: List[str] = Field(default_factory=list, description="testable acceptance criteria")
    edge_cases: List[str] = Field(default_factory=list, description="edge cases and failure scenarios")
    dependencies: List[str] = Field(default_factory=list, description="dependencies for the requirement")
    priority: str = Field(description="priority: high, medium, or low")


class Epic(BaseModel):
    epic_id: str = Field(description="unique id for the epic (e.g., EPIC-1)")
    title: str = Field(description="epic title representing a complete business workflow")
    user_story: str = Field(description="user story for the epic")
    mapped_capabilities: List[str] = Field(default_factory=list, description="capability ids mapped to this epic")
    requirements: List[Requirement] = Field(description="capability-level requirements grouped under the epic")


class ValidationCheck(BaseModel):
    check: str = Field(description="validation check label")
    status: str = Field(description="pass or fail")
    notes: str = Field(description="short justification for the status")


class WorkflowRequirements(BaseModel):
    workflow_id: str = Field(description="unique id for the workflow (e.g., WF-1)")
    workflow_name: str = Field(description="short workflow name")
    workflow_summary: str = Field(description="high-level summary of the client workflow")
    intent: Intent = Field(default_factory=Intent, description="business goals and intended outcomes")
    capabilities: List[Capability] = Field(default_factory=list, description="generalized reusable system capabilities")
    core_engine_justification: str = Field(default="", description="short explanation of the hardest domain task and why it is the core engine")
    validation_summary: List[ValidationCheck] = Field(default_factory=list, description="pass/fail validation checks proving domain alignment and transcript grounding")
    actors: List[Actor] = Field(default_factory=list, description="actors involved in the system")
    epics: List[Epic] = Field(description="epics representing complete business workflows")
    system_constraints: List[str] = Field(default_factory=list, description="system-wide constraints or limitations for the workflow")


class MultiProjectRequirementsPayload(BaseModel):
    workflows: List[WorkflowRequirements] = Field(description="list of distinct workflows found in the transcript")


class WorkflowCandidate(BaseModel):
    workflow_name: str = Field(description="short workflow name")
    workflow_summary: str = Field(description="summary of the workflow")
    evidence: List[str] = Field(description="signals from transcript supporting the workflow")


class WorkflowDiscoveryPayload(BaseModel):
    workflows: List[WorkflowCandidate] = Field(description="workflow candidates discovered in a transcript chunk")


class SingleWorkflowPayload(BaseModel):
    workflow: WorkflowRequirements = Field(description="fully generated requirements for one workflow")


class GenericWorkflowHeader(BaseModel):
    id: str = Field(default="", description="workflow id")
    name: str = Field(description="workflow name")
    summary: str = Field(description="workflow summary")


class NormalizedWorkflowInputPayload(BaseModel):
    workflow_name: str = Field(description="normalized workflow name")
    workflow_summary: str = Field(description="normalized workflow summary")
    key_steps: List[str] = Field(default_factory=list, description="key workflow steps")
    actors: List[Actor] = Field(default_factory=list, description="actors if present")


class GenericRequirement(BaseModel):
    req_id: str = Field(description="requirement id")
    title: str = Field(description="requirement title")
    description: str = Field(description="requirement description")
    user_story: str = Field(description="user story")
    acceptance_criteria: List[str] = Field(default_factory=list, description="acceptance criteria")
    edge_cases: List[str] = Field(default_factory=list, description="edge cases")
    dependencies: List[str] = Field(default_factory=list, description="dependencies")
    priority: str = Field(default="high", description="priority")


class GenericEpic(BaseModel):
    epic_id: str = Field(description="epic id")
    title: str = Field(description="epic title")
    user_story: str = Field(description="epic user story")
    mapped_capabilities: List[str] = Field(default_factory=list, description="mapped capability ids")
    requirements: List[GenericRequirement] = Field(default_factory=list, description="requirements")


class GenericSingleWorkflowPayload(BaseModel):
    workflow: GenericWorkflowHeader = Field(description="workflow header")
    intent: Intent = Field(default_factory=Intent, description="intent goals")
    actors: List[Actor] = Field(default_factory=list, description="actors involved in the workflow")
    capabilities: List[Capability] = Field(default_factory=list, description="generic capabilities")
    epics: List[GenericEpic] = Field(default_factory=list, description="epics list")


class CapabilityPayload(BaseModel):
    capabilities: List[Capability] = Field(default_factory=list, description="generic capability list")


class ScopedRequirementDecision(BaseModel):
    req_id: str = Field(description="requirement id")
    title: str = Field(description="requirement title")
    scope: str = Field(description="MUST_HAVE | SHOULD_HAVE | FUTURE_SCOPE | OUT_OF_SCOPE")
    priority: str = Field(description="high | medium | low")
    action: str = Field(description="keep | modify | remove")
    reason: str = Field(description="reason for the decision")


class WorkflowScopeReview(BaseModel):
    workflow_id: str = Field(description="workflow id")
    requirements: List[ScopedRequirementDecision] = Field(description="scope review decisions for workflow requirements")


class ScopeControlPayload(BaseModel):
    workflows: List[WorkflowScopeReview] = Field(description="scope control decisions by workflow")


class ContextEnrichmentPayload(BaseModel):
    final_context: str = Field(description="final merged context aligned with transcript intent and workflow")
    workflow_steps: List[Dict[str, Any]] = Field(description="normalized workflow steps")
    business_goals: str = Field(description="summarized business goals extracted from transcript and workflow")


class WorkflowValidationPayload(BaseModel):
    missing_steps: List[str] = Field(description="workflow steps that are missing from generated requirements")
    extra_logic: List[str] = Field(description="logic present in generated requirements but not in source workflow")
    coverage_score: int = Field(description="overall workflow coverage score from 0 to 100")


class MermaidWorkflowPayload(BaseModel):
    workflow: Dict[str, Any] = Field(description="normalized workflow extracted from Mermaid diagram")


class TranscriptLanguagePayload(BaseModel):
    detected_language: str = Field(description="detected language name, e.g., Swedish, English, German")
    translation_applied: bool = Field(description="true if translation to English was applied")
    normalized_english_transcript: str = Field(description="English-normalized transcript preserving business meaning and domain terms")
    domain_keyword_mapping: List[Dict[str, str]] = Field(
        default_factory=list,
        description="key original-language domain keywords mapped to domain concepts in English",
    )


parser = JsonOutputParser(pydantic_object=MultiProjectRequirementsPayload)
workflow_discovery_parser = JsonOutputParser(pydantic_object=WorkflowDiscoveryPayload)
single_workflow_parser = JsonOutputParser(pydantic_object=GenericSingleWorkflowPayload)
input_normalizer_parser = JsonOutputParser(pydantic_object=NormalizedWorkflowInputPayload)
capability_parser = JsonOutputParser(pydantic_object=CapabilityPayload)
scope_control_parser = JsonOutputParser(pydantic_object=ScopeControlPayload)
scope_consolidation_parser = JsonOutputParser(pydantic_object=MultiProjectRequirementsPayload)
context_enrichment_parser = JsonOutputParser(pydantic_object=ContextEnrichmentPayload)
workflow_validation_parser = JsonOutputParser(pydantic_object=WorkflowValidationPayload)
mermaid_understanding_parser = JsonOutputParser(pydantic_object=MermaidWorkflowPayload)
language_normalization_parser = JsonOutputParser(pydantic_object=TranscriptLanguagePayload)


def _as_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


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


def _generate_requirement_story(title: str, description: str, workflow_name: str = "", epic_title: str = "") -> str:
    clean_title = (title or "the requirement").strip()
    clean_workflow = (workflow_name or "the workflow").strip()
    clean_epic = (epic_title or "").strip()
    if clean_epic and clean_epic.lower() not in clean_workflow.lower():
        clean_context = f"{clean_workflow} / {clean_epic}"
    else:
        clean_context = clean_workflow

    benefit_source = (description or clean_title).strip().rstrip(".")
    benefit_source = benefit_source[0].lower() + benefit_source[1:] if len(benefit_source) > 1 else benefit_source
    return (
        f"As a user working in {clean_context}, I want {clean_title.lower()} "
        f"so that {benefit_source}."
    )


def _normalize_requirement_detail_block(requirement: Dict[str, Any], workflow_name: str = "", epic_title: str = "", transcript: str = "") -> Dict[str, Any]:
    req = dict(requirement or {})
    title = (req.get("title") or req.get("short_title") or req.get("req_id") or "Requirement").strip()
    description = (
        req.get("description")
        or req.get("requirement_description")
        or req.get("story_text")
        or req.get("summary")
        or ""
    ).strip()
    if not description:
        description = f"The system shall support {title.lower()} as part of the workflow."
    elif not description.lower().startswith("the system shall"):
        description = f"The system shall {description[0].lower()}{description[1:]}" if len(description) > 1 else description

    inputs = _as_list(req.get("inputs")) or _as_list(req.get("input")) or _as_list(req.get("source_inputs"))
    if not inputs:
        inputs = _as_list(req.get("functional_details"))
    if not inputs:
        inputs = _extract_grounded_detail_items(transcript, title, "input")

    outputs = _as_list(req.get("outputs")) or _as_list(req.get("output")) or _as_list(req.get("deliverables"))
    if not outputs:
        outputs = _as_list(req.get("expected_output"))
    if not outputs:
        outputs = _extract_grounded_detail_items(transcript, title, "output")

    user_story = (req.get("user_story") or "").strip()
    if not user_story:
        user_story = _generate_requirement_story(title, description, workflow_name, epic_title)
    elif not user_story.lower().startswith("as a "):
        user_story = _generate_requirement_story(title, description, workflow_name, epic_title)

    acceptance = [item for item in _as_list(req.get("acceptance_criteria")) if item]
    edge_cases = [item for item in _as_list(req.get("edge_cases")) if item]
    dependencies = [item for item in _as_list(req.get("dependencies")) if item]

    normalized = {
        **req,
        "title": title,
        "description": description,
        "requirement_description": description,
        "inputs": inputs,
        "outputs": outputs,
        "user_story": user_story,
        "acceptance_criteria": acceptance,
        "edge_cases": edge_cases,
        "dependencies": dependencies,
        "priority": (req.get("priority") or "high").strip().lower(),
    }

    if not normalized.get("functional_details") and (inputs or outputs):
        functional_details = []
        if inputs:
            functional_details.append(f"Input: {inputs[0]}")
        if outputs:
            functional_details.append(f"Output: {outputs[0]}")
        normalized["functional_details"] = functional_details

    return normalized


def _normalize_workflow_record(workflow: Dict[str, Any], workflow_index: int, transcript: str = "") -> Dict[str, Any]:
    normalized_workflow = dict(workflow or {})
    workflow_name = (normalized_workflow.get("workflow_name") or normalized_workflow.get("workflow", {}).get("name") or f"Workflow {workflow_index}").strip()
    workflow_summary = (normalized_workflow.get("workflow_summary") or "").strip()
    workflow_id = (normalized_workflow.get("workflow_id") or f"WF-{workflow_index}").strip()

    normalized_epics = []
    epics = normalized_workflow.get("epics") or []
    if not epics and normalized_workflow.get("requirements"):
        epics = [
            {
                "epic_id": f"{workflow_id}-EPIC-1",
                "title": workflow_name,
                "user_story": workflow_summary or workflow_name,
                "requirements": normalized_workflow.get("requirements") or [],
            }
        ]

    for epic_index, epic in enumerate(epics, start=1):
        epic_payload = dict(epic or {})
        epic_id = (epic_payload.get("epic_id") or f"{workflow_id}-EPIC-{epic_index}").strip()
        epic_title = (epic_payload.get("title") or f"Epic {epic_index}").strip()
        epic_story = (epic_payload.get("user_story") or "").strip()
        if not epic_story:
            epic_story = (
                f"As a user working in {workflow_name}, I want {epic_title.lower()} "
                f"so that the workflow remains traceable and implementable."
            )

        normalized_requirements = []
        for req_index, requirement in enumerate(epic_payload.get("requirements") or [], start=1):
            req_payload = _normalize_requirement_detail_block(requirement, workflow_name, epic_title, transcript=transcript)
            req_payload["req_id"] = (req_payload.get("req_id") or f"{epic_id}-REQ-{req_index}").strip()
            req_payload["title"] = (req_payload.get("title") or f"Requirement {req_index}").strip()
            normalized_requirements.append(req_payload)

        normalized_epics.append(
            {
                **epic_payload,
                "epic_id": epic_id,
                "title": epic_title,
                "user_story": epic_story,
                "requirements": normalized_requirements,
            }
        )

    normalized_workflow["workflow_id"] = workflow_id
    normalized_workflow["workflow_name"] = workflow_name
    normalized_workflow["workflow_summary"] = workflow_summary
    normalized_workflow["epics"] = normalized_epics
    normalized_workflow["actors"] = normalized_workflow.get("actors") or []
    normalized_workflow["capabilities"] = normalized_workflow.get("capabilities") or []
    normalized_workflow["system_constraints"] = normalized_workflow.get("system_constraints") or []
    normalized_workflow["validation_summary"] = normalized_workflow.get("validation_summary") or []
    normalized_workflow["core_engine_justification"] = normalized_workflow.get("core_engine_justification") or ""
    normalized_workflow["source_transcript"] = transcript or normalized_workflow.get("source_transcript") or ""
    return normalized_workflow


def collapse_requirement_workflows(requirements_payload, transcript: str = ""):
    workflows = []
    if isinstance(requirements_payload, dict):
        workflows = requirements_payload.get("workflows") or []
    elif isinstance(requirements_payload, list):
        workflows = requirements_payload

    workflows = [workflow for workflow in workflows if isinstance(workflow, dict)]
    if not workflows:
        return {"workflows": []}

    normalized_workflows = [_normalize_workflow_record(workflow, index + 1, transcript=transcript) for index, workflow in enumerate(workflows)]
    if len(normalized_workflows) == 1:
        return {"workflows": normalized_workflows}

    combined_name_parts = [wf.get("workflow_name") for wf in normalized_workflows if wf.get("workflow_name")]
    combined_name = combined_name_parts[0] if len(combined_name_parts) == 1 else "Combined Workflow"
    combined_summary_parts = [wf.get("workflow_summary") for wf in normalized_workflows if wf.get("workflow_summary")]
    combined_summary = "Combined workflow synthesized from approved workflow sessions."
    if combined_summary_parts:
        combined_summary = f"{combined_summary} Source summaries: {' | '.join(dict.fromkeys(combined_summary_parts))}"

    combined = {
        "workflow_id": "WF-1",
        "workflow_name": combined_name,
        "workflow_summary": combined_summary,
        "intent": {"goals": []},
        "capabilities": [],
        "actors": [],
        "epics": [],
        "system_constraints": [],
        "validation_summary": [],
        "core_engine_justification": "Combined and normalized from multiple generated workflow segments.",
        "source_workflows": [wf.get("workflow_id") for wf in normalized_workflows if wf.get("workflow_id")],
    }

    seen_goals = set()
    for workflow in normalized_workflows:
        for goal in (workflow.get("intent") or {}).get("goals") or []:
            if goal and goal not in seen_goals:
                combined["intent"]["goals"].append(goal)
                seen_goals.add(goal)

        for actor in workflow.get("actors") or []:
            actor_key = (actor.get("name"), actor.get("type"))
            if actor_key not in {(item.get("name"), item.get("type")) for item in combined["actors"]}:
                combined["actors"].append(actor)

        for capability in workflow.get("capabilities") or []:
            cap_key = capability.get("capability_id") or capability.get("name")
            if cap_key and cap_key not in {item.get("capability_id") or item.get("name") for item in combined["capabilities"]}:
                combined["capabilities"].append(capability)

        for constraint in workflow.get("system_constraints") or []:
            if constraint and constraint not in combined["system_constraints"]:
                combined["system_constraints"].append(constraint)

        for check in workflow.get("validation_summary") or []:
            if check not in combined["validation_summary"]:
                combined["validation_summary"].append(check)

    epic_counter = 1
    req_counter = 1
    for workflow in normalized_workflows:
        for epic in workflow.get("epics") or []:
            combined_epic = {
                **epic,
                "epic_id": f"EPIC-{epic_counter}",
                "title": epic.get("title") or f"Epic {epic_counter}",
                "requirements": [],
            }
            epic_counter += 1

            for requirement in epic.get("requirements") or []:
                combined_requirement = _normalize_requirement_detail_block(
                    requirement,
                    combined_name,
                    combined_epic["title"],
                    transcript=transcript,
                )
                combined_requirement["req_id"] = f"REQ-{req_counter}"
                req_counter += 1
                combined_epic["requirements"].append(combined_requirement)

            combined["epics"].append(combined_epic)

    return {"workflows": [combined]}

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

TRANSCRIPT_LANGUAGE_NORMALIZATION_PROMPT = """
You are a multilingual transcript normalizer for business requirement generation.

STEP 0: LANGUAGE NORMALIZATION (MANDATORY)

Task:
1) Detect the input language.
2) If the transcript is not English, translate it to clear business English.
3) Preserve domain terms, product names, IDs, units, and business intent exactly.
4) Identify key domain keywords in the original language and map them to domain concepts in English.
5) Keep the same workflow meaning, constraints, and ordering.
6) Do NOT summarize or drop details.

Return STRICT JSON:
{format_instructions}

Transcript:
{transcript}
"""

CONTEXT_ENRICHMENT_PROMPT = """
You are a Context Enrichment Engine.

Inputs:
1. Business transcript
2. Structured workflow (from diagram)

Rules:
- Workflow = system flow (source of truth)
- Transcript = business intent

Task:
- Align both
- Fill missing logic from transcript
- Do NOT contradict diagram

Return:

{
  "final_context": "...",
  "workflow_steps": [...],
  "business_goals": "..."
}
"""

WORKFLOW_VALIDATION_PROMPT = """
Compare workflow vs requirements.

Check:
- Are all steps covered?
- Any missing steps?
- Any extra logic?
- Does each core-engine step have explicit Input -> Output transformation?
- Is the transformation chain implementable end-to-end?
- Are workflows introducing new automation logic (not just modeling existing tools)?

Return:

{
  "missing_steps": [],
  "extra_logic": [],
  "coverage_score": 0-100
}
"""

MERMAID_UNDERSTANDING_PROMPT = """
You are a Workflow Diagram Understanding Agent.

Input:
Mermaid diagram code

Your job is to interpret the diagram and convert it into a structured workflow.

---

STEP-BY-STEP:

1. Identify all nodes
   - Each box = a system step

2. Identify flow connections
   - A --> B = sequence

3. Identify decision points
   - Nodes with { } are conditions
   - Extract branches (Yes/No)

4. Identify start and end points

5. Normalize step names
   - Convert into clear action phrases
   - Example:
     "A[PDF]" -> "Receive PDF"

---

Return STRICT JSON:

{
  "workflow": {
    "start": "step_id",
    "steps": [
      {
        "id": "step_1",
        "name": "Receive PDF",
        "type": "process",
        "next": ["step_2"]
      }
    ],
    "decisions": [
      {
        "id": "decision_1",
        "condition": "Missing information?",
        "branches": {
          "yes": "step_3",
          "no": "step_4"
        }
      }
    ]
  }
}
"""

REFINEMENT_PROMPT = """
You are a Senior Product Analyst refining existing requirements.

You are given:
1. Previously generated requirements
2. User feedback / requested changes

IMPORTANT:
- Do NOT regenerate from scratch
- MODIFY the existing requirements intelligently
- PRESERVE correct parts
- APPLY user feedback precisely
- Maintain structure and consistency

---

INPUTS:

EXISTING REQUIREMENTS:
{existing_requirements}

USER FEEDBACK:
{user_feedback}

---

STEP-BY-STEP INSTRUCTIONS:

1. Understand Feedback
   - Identify what user wants:
     - add new requirement
     - modify existing requirement
     - remove requirement
     - improve clarity

2. Map Feedback to Requirements
   - Find which requirement(s) are affected
   - If new functionality -> create new requirement

3. Apply Changes Carefully
   - Do NOT break structure
   - Do NOT remove valid logic unless explicitly asked
   - Keep requirements atomic

4. Maintain Quality Rules
   - Each requirement must be clear and independent
   - Keep functional_details, acceptance_criteria, edge_cases
   - Ensure testability

5. If feedback is vague:
   - Interpret reasonably
   - Improve clarity

6. Final Validation:
   - No duplicate requirements
   - No missing critical logic
   - Preserve exactly one merged workflow
   - Add new major functionality as epics, not separate workflows

---

Return STRICT JSON using the SAME schema as the generation output with `workflows` as the top-level key.
"""

SCOPE_CONTROL_PROMPT = """
You are a Scope Control and Consolidation Agent.

Your job is NOT just to classify requirements,
but to CLEAN, MERGE, and REDUCE them into correct project scope.

---

INPUTS:

TRANSCRIPT:
{transcript}

GENERATED REQUIREMENTS:
{requirements}

---

STEP-BY-STEP:

1. Identify Core Initiatives (MANDATORY)

- Detect ONLY high-level initiatives from transcript
- Example:
  Order Automation
  Quotation Tool

- DO NOT create sub-workflows

---

2. Remove Redundant Workflows

- If multiple workflows represent parts of the same system:
  -> MERGE them

Example:
Pricing Tool
Quote Generator
History Search

-> Quotation Tool

---

3. Consolidate Requirements

- Combine fragmented requirements into coherent, capability-level requirements

- Ensure each requirement is:
  - capability-level
  - not duplicated
  - not fragmented

---

4. Enforce Workflow Limit

- Maximum workflows allowed: 2-3

If more exist:
-> MERGE them

---

5. Remove Scope Noise

REMOVE:
- duplicate ideas
- repeated modules
- sub-features presented as workflows

---

6. Reassign Requirements

- Group all requirements under correct workflow
- Ensure no overlap

---

7. Fix IDs

- Ensure:
  WF-1, WF-2
  EPIC-1, EPIC-2
  REQ-1, REQ-2

- NO duplicates

---

8. Final Validation

Ensure:

- Only 1 workflow
- All detected functionality is merged into that workflow
- No duplication
- No fragmentation
- Clean structure

---

Return CLEANED JSON:
{format_instructions}
"""

WORKFLOW_DISCOVERY_PROMPT = """
You are identifying all major problem areas and business functions from a transcript chunk.

Rules:
- Detect only real business problems, workflow functions, or major initiative tracks
- Detect items only when they introduce NEW system automation capability or a distinct business function
- Exclude workflows that only describe existing systems/tools with no new automation logic
- Ignore low-level steps
- Keep names short and business-meaningful
- If multiple related problems appear, keep them discoverable so they can be merged later into one end-to-end workflow
- If the chunk has no clear workflow, return an empty list
- Do not invent workflows unsupported by the text

Return STRICT JSON:
{format_instructions}

TRANSCRIPT CHUNK:
{chunk_text}
"""

WORKFLOW_CONSOLIDATION_PROMPT = """
You are consolidating workflow candidates discovered across multiple transcript chunks.

Rules:
- Merge duplicates and near-duplicates
- If multiple workflows or business functions are detected, merge them into one broader end-to-end workflow
- Keep only one final workflow in the output
- Treat secondary workflows as parts of the same end-to-end system
- Treat secondary problems as epics or business functions inside the same final workflow
- Prefer end-to-end business-process names over fragmented feature names
- Preserve only workflows supported by evidence
- Keep only workflows that represent NEW automation capabilities
- Remove workflows that only map existing project-management/tooling behavior without new logic
- Prefer broader workflow names over step names
- Final output must contain exactly 1 workflow
- The single workflow must cover all detected problem areas
- Return the final consolidated workflow list

Return STRICT JSON:
{format_instructions}

DISCOVERED WORKFLOW CANDIDATES:
{discovered_workflows}
"""

INPUT_NORMALIZER_PROMPT = """
You are an input normalizer.

Task:
Convert ANY input (text, transcript, workflow, or JSON) into a structured intermediate format.

Extract:
- workflow_name
- workflow_summary
- key_steps
- actors (if present)

Rules:
- Do NOT assume domain
- Do NOT generate requirements yet
- Just structure the input

Return ONLY JSON:
{format_instructions}

Input:
{raw_input}
"""

INTENT_EXTRACTION_PROMPT = """
You are an intent extraction engine.

Task:
From the workflow, extract business goals.

Rules:
- Goals must be domain-agnostic
- Focus on WHY the workflow exists
- Avoid technical implementation details

Return ONLY JSON:
{format_instructions}

Workflow:
{workflow_input}
"""

CAPABILITY_ABSTRACTION_PROMPT = """
You are a capability abstraction engine.

Task:
Return the strict capability set.

Rules:
- Return EXACTLY these 5 capabilities and no others:
  1. Input Normalization
  2. Context Interpretation
  3. Structured Data Extraction
  4. Computation and Validation
  5. Structured Output Generation
- Keep names exactly as written
- Do not merge, split, rename, or invent capabilities

Return ONLY JSON:
{format_instructions}

Workflow:
{workflow_input}

Intent:
{intent_payload}
"""

REQUIREMENT_GENERATION_PROMPT = """
You are a solution architect.

Transform the input using this strict pipeline:
Detect -> Merge -> Expand -> Structure

INPUT UNDERSTANDING RULES:
- Identify ALL problem areas in the transcript and workflow context
- Do NOT discard any problem
- Do NOT create multiple workflows

WORKFLOW RULES:
- Return EXACTLY ONE workflow
- The workflow must represent the END-TO-END business process
- Secondary problems MUST become epics
- NEVER remove functionality

EPIC CREATION RULES:
- You MUST create epics for:
  1. Input Processing
  2. Data Extraction & Validation
  3. Output Generation
- You MUST add additional business-function epics for major functions detected in the input
  Examples: Quotation Management, Order Processing, Approval Management
- Epics must be business-meaningful and non-duplicative

REQUIREMENT RULES:
1. Each requirement MUST:
   - start with "The system shall..."
   - describe clear, testable system behavior (no template noise)
   - reflect actual input problems and business needs
2. Each requirement MUST map logically to 1-2 capabilities
3. No duplicates allowed
4. Include user story:
   "As a user, I want the system to [action] so that [outcome]"
5. Avoid generic placeholders such as:
   - "execute X using workflow-specific rules"
   - vague implementation-free requirement text
6. Only populate inputs and outputs when they are explicitly supported by the transcript or workflow context
7. If inputs or outputs are not grounded, leave them empty rather than inventing defaults

CAPABILITY RULE (STRICT):
- Use EXACTLY 5 capabilities:
  1. Input Normalization
  2. Context Interpretation
  3. Structured Data Extraction
  4. Computation and Validation
  5. Structured Output Generation
- DO NOT create new capabilities
- DO NOT combine capabilities

COMPLETENESS RULES:
- ALL problems from the input MUST appear in the output
- If anything is missing, rewrite the workflow so coverage is complete
- Keep exactly one workflow and full end-to-end coverage

Return ONLY JSON:
{format_instructions}

Workflow:
{workflow_payload}

Intent:
{intent_payload}

Capabilities:
{capability_payload}

Relevant context:
{context}

Transcript:
{input_text}

Structured workflow:
{structured_workflow}
"""

REQUIREMENT_COMPLETENESS_PROMPT = """
You are a requirement completeness engine.

Task:
Ensure each requirement includes:
- acceptance_criteria
- edge_cases
- dependencies
- priority

Rules:
- Edge cases must include failure scenarios
- Dependencies must reference system components or inputs
- Do NOT remove existing content
- Preserve exactly one workflow
- Preserve all epics needed for full business coverage
- Ensure no problem area from the input has been lost or simplified away
- Preserve strict 5-capability set and clean requirement-to-capability mapping
- Preserve behavioral requirement phrasing and proper user story grammar

If any requirement is incomplete, fix it.

Return ONLY JSON:
{format_instructions}

Workflow payload:
{workflow_payload}
"""

STRICT_VALIDATOR_PROMPT = """
You are a strict validator.

Validate ALL rules:
1. The payload represents exactly one workflow
2. The workflow is end-to-end and not fragmented into multiple workflows
3. Required epics exist:
   - Input Processing
   - Data Extraction & Validation
   - Output Generation
4. Additional major business functions appear as separate epics when present
5. No duplicate requirements
6. No requirement appears in multiple epics
7. Requirement language is behavioral and specific (not repetitive boilerplate)
8. Each requirement includes:
   - description
   - acceptance_criteria
   - edge_cases
   - dependencies
9. User stories are correctly formatted
10. Requirement descriptions start with "The system shall..."
11. Capabilities are exactly:
   - Input Normalization
   - Context Interpretation
   - Structured Data Extraction
   - Computation and Validation
   - Structured Output Generation
12. Each requirement maps clearly to 1-2 capabilities only

If ANY rule fails, rewrite the entire output correctly.

Return ONLY JSON:
{format_instructions}

Workflow payload:
{workflow_payload}
"""

CONSISTENCY_ALIGNMENT_PROMPT = """
You are a strict consistency validator.

Task:
Ensure FULL internal consistency of the system.

VALIDATION RULES:
1. ALL dependencies MUST reference ONLY existing capabilities
   - No new capability names allowed
   - Must match capability_id + name EXACTLY
2. NO hallucinated capabilities allowed
   - If found, replace with the correct existing capability
3. Remove domain-specific terms:
   - Replace drawings with visual input
   - Replace proposals with structured output
4. Each requirement MUST map logically to its capability
5. Fix epic user stories to:
   "As a user, I want the system to [action] so that [outcome]"
6. Ensure naming consistency:
   - Same concept = same name everywhere
   - No synonyms for capabilities
7. Preserve one merged workflow:
   - secondary problems become epics, not separate workflows
   - do not drop any business function

If ANY inconsistency exists, rewrite the entire JSON until fully consistent.

Return ONLY JSON:
{format_instructions}

Workflow payload:
{workflow_payload}
"""

FINAL_SYSTEM_ALIGNMENT_PROMPT = """
You are a final system alignment engine.

Task:
Fix logical consistency and abstraction issues.

RULES:
1. Fix capability mapping:
   - Each requirement must map to the correct capability
   - No incorrect capability usage
   - Capability set must stay exactly:
     Input Normalization, Context Interpretation, Structured Data Extraction, Computation and Validation, Structured Output Generation
2. Fix epic placement:
   - Input Processing -> intake, capture, normalization, submission handling
   - Data Extraction & Validation -> extraction, mapping, computation, validation
   - Output Generation -> output assembly, formatting, publishing, handoff
   - Additional business epics -> business functions such as quotation, order, approval, fulfillment, etc.
3. Fix user stories:
   - MUST follow:
     "As a user, I want the system to [action] so that [outcome]"
4. Remove requirement overlap:
   - Merge or differentiate similar requirements
5. Remove domain-specific naming:
   - Replace client with external system
   - Replace proposal with structured output
6. Ensure internal consistency:
   - No conflicting logic
   - No duplicated responsibilities
7. Preserve the architect structure:
   - one workflow only
   - full problem coverage
   - no loss of business functionality
8. Preserve refinement quality:
   - behavioral requirement wording
   - valid user-story grammar
   - clear requirement-to-capability traceability

If ANY issue exists, rewrite affected sections.

Return ONLY JSON:
{format_instructions}

Workflow payload:
{workflow_payload}
"""

MASTER_REQUIREMENT_PROMPT_V4 = """
You are an AI system that transforms ANY workflow input into a generalized but business-faithful requirement architecture.

Your task is NOT tied to a specific scenario.
You must work for ANY domain.

OBJECTIVE:
1. Detect all business problem areas
2. Merge them into one end-to-end workflow
3. Expand the workflow into architect-level epics and detailed requirements
4. Produce a consistent structured output without losing business meaning

TRANSFORMATION PIPELINE:
1. Detect
2. Merge
3. Expand
4. Structure
5. Completeness
6. Validation
7. Consistency Alignment
8. Final System Alignment

CAPABILITY RULES:
- MUST use exactly these five capabilities:
  1. Input Normalization
  2. Context Interpretation
  3. Structured Data Extraction
  4. Computation and Validation
  5. Structured Output Generation
- MUST NOT add, remove, rename, or combine capabilities

EPIC RULES:
- MUST belong to exactly one workflow
- MUST include:
  1. Input Processing
  2. Data Extraction & Validation
  3. Output Generation
- MUST add additional business-function epics when the input indicates them
- MUST preserve full input coverage

REQUIREMENT RULES:
- MUST describe system behavior
- MUST be testable
- MUST NOT contain vague phrases
- MUST map to 1-2 capabilities only
- MUST reflect actual input problems
- MUST be behavioral, specific, and actionable
- MUST avoid repetitive template phrasing
- MUST only list inputs and outputs that are explicitly grounded in the transcript or structured workflow
- MUST leave inputs/outputs empty if the transcript does not support them

USER STORY FORMAT:
Use exactly:
"As a user, I want [action] so that [outcome]"

GENERALIZATION RULE:
- Output must stay reusable across domains where possible
- Do not erase material business context, business functions, or downstream integrations
- Do not include explanatory text outside JSON
"""

GENERAL_REQUIREMENT_PROMPT = MASTER_REQUIREMENT_PROMPT_V4

SINGLE_WORKFLOW_REQ_PROMPT = """
You are an AI system that generates architected requirements for EXACTLY ONE merged workflow.

Your job is to transform the workflow into a reusable architecture:
Workflow -> Intent -> Actors -> Capabilities -> Epics -> Requirements

IMPORTANT:
- The target workflow is:
  Name: {workflow_name}
  Summary: {workflow_summary}
- Do NOT include other workflows
- Merge all detected problem areas into this one workflow
- Use only the context relevant to this workflow
- Output must preserve actual business functions while remaining reusable where possible
- Epics must include Input Processing, Data Extraction & Validation, and Output Generation
- Add separate business-function epics when the input indicates them
- Requirements must describe concrete, testable system behavior
- Requirements must be behavioral and non-repetitive
- Every epic must map to one or more capabilities
- Use exactly 5 capabilities only:
  Input Normalization, Context Interpretation, Structured Data Extraction, Computation and Validation, Structured Output Generation
- If transcript text and diagram/drawing context both exist, use the structured workflow as the execution backbone and transcript as business context
- Keep IDs when provided, but if missing, generate consistent placeholders
- Never invent inputs or outputs; only include them when they are supported by the transcript or structured workflow
- When evidence is missing, leave input/output arrays empty so the UI can show the gap clearly
- Do NOT output a top-level `workflows` array here

{base_prompt}

{format_instructions}

TARGET WORKFLOW:
Name: {workflow_name}
Summary: {workflow_summary}

WORKFLOW-SPECIFIC CONTEXT:
{context}

FULL TRANSCRIPT:
{input_text}

STRUCTURED WORKFLOW / DRAWING CONTEXT:
{structured_workflow}
"""

workflow_discovery_prompt = ChatPromptTemplate.from_template(
    WORKFLOW_DISCOVERY_PROMPT,
    partial_variables={
        "format_instructions": workflow_discovery_parser.get_format_instructions(),
    },
)

workflow_consolidation_prompt = ChatPromptTemplate.from_template(
    WORKFLOW_CONSOLIDATION_PROMPT,
    partial_variables={
        "format_instructions": workflow_discovery_parser.get_format_instructions(),
    },
)

input_normalizer_prompt = ChatPromptTemplate.from_template(
    INPUT_NORMALIZER_PROMPT,
    partial_variables={
        "format_instructions": input_normalizer_parser.get_format_instructions(),
    },
)

intent_extraction_prompt = ChatPromptTemplate.from_template(
    INTENT_EXTRACTION_PROMPT,
    partial_variables={
        "format_instructions": JsonOutputParser(pydantic_object=Intent).get_format_instructions(),
    },
)

capability_abstraction_prompt = ChatPromptTemplate.from_template(
    CAPABILITY_ABSTRACTION_PROMPT,
    partial_variables={
        "format_instructions": capability_parser.get_format_instructions(),
    },
)

requirement_generation_prompt = ChatPromptTemplate.from_template(
    REQUIREMENT_GENERATION_PROMPT,
    partial_variables={
        "format_instructions": single_workflow_parser.get_format_instructions(),
    },
)

requirement_completeness_prompt = ChatPromptTemplate.from_template(
    REQUIREMENT_COMPLETENESS_PROMPT,
    partial_variables={
        "format_instructions": single_workflow_parser.get_format_instructions(),
    },
)

strict_validator_prompt = ChatPromptTemplate.from_template(
    STRICT_VALIDATOR_PROMPT,
    partial_variables={
        "format_instructions": single_workflow_parser.get_format_instructions(),
    },
)

consistency_alignment_prompt = ChatPromptTemplate.from_template(
    CONSISTENCY_ALIGNMENT_PROMPT,
    partial_variables={
        "format_instructions": single_workflow_parser.get_format_instructions(),
    },
)

final_system_alignment_prompt = ChatPromptTemplate.from_template(
    FINAL_SYSTEM_ALIGNMENT_PROMPT,
    partial_variables={
        "format_instructions": single_workflow_parser.get_format_instructions(),
    },
)

single_workflow_prompt = ChatPromptTemplate.from_template(
    SINGLE_WORKFLOW_REQ_PROMPT,
    partial_variables={
        "base_prompt": GENERAL_REQUIREMENT_PROMPT.strip(),
        "format_instructions": single_workflow_parser.get_format_instructions(),
    },
)

refinement_prompt = ChatPromptTemplate.from_template(
    """{base_prompt}

{format_instructions}

EXISTING REQUIREMENTS:
{existing_requirements}

USER FEEDBACK:
{user_feedback}""",
    partial_variables={
        "base_prompt": REFINEMENT_PROMPT.strip(),
        "format_instructions": parser.get_format_instructions(),
    },
)

scope_control_prompt = ChatPromptTemplate.from_template(
    SCOPE_CONTROL_PROMPT,
    partial_variables={
        "format_instructions": scope_consolidation_parser.get_format_instructions(),
    },
)

context_enrichment_prompt = ChatPromptTemplate.from_template(
    """{base_prompt}

Return STRICT JSON:
{format_instructions}

Business transcript:
{transcript}

Structured workflow:
{structured_workflow}""",
    partial_variables={
        "base_prompt": CONTEXT_ENRICHMENT_PROMPT.strip(),
        "format_instructions": context_enrichment_parser.get_format_instructions(),
    },
)

workflow_validation_prompt = ChatPromptTemplate.from_template(
    """{base_prompt}

Return STRICT JSON:
{format_instructions}

Structured workflow:
{structured_workflow}

Generated requirements:
{generated_requirements}""",
    partial_variables={
        "base_prompt": WORKFLOW_VALIDATION_PROMPT.strip(),
        "format_instructions": workflow_validation_parser.get_format_instructions(),
    },
)

mermaid_understanding_prompt = ChatPromptTemplate.from_template(
    """{base_prompt}

Return STRICT JSON:
{format_instructions}

Mermaid diagram:
{mermaid_code}""",
    partial_variables={
        "base_prompt": MERMAID_UNDERSTANDING_PROMPT.strip(),
        "format_instructions": mermaid_understanding_parser.get_format_instructions(),
    },
)

language_normalization_prompt = ChatPromptTemplate.from_template(
    TRANSCRIPT_LANGUAGE_NORMALIZATION_PROMPT,
    partial_variables={
        "format_instructions": language_normalization_parser.get_format_instructions(),
    },
)


def clean_input_text(raw_text: str, model=None) -> str:
    text = (raw_text or "").strip()
    if not text:
        return ""

    cleaner_model = model or ChatOpenAI(model="gpt-4o", temperature=0)
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


def normalize_transcript_language(raw_text: str, model=None) -> Dict[str, Any]:
    text = (raw_text or "").strip()
    if not text:
        return {
            "detected_language": "unknown",
            "translation_applied": False,
            "normalized_transcript": "",
            "domain_keyword_mapping": [],
        }

    normalizer_model = model or ChatOpenAI(model="gpt-4o", temperature=0)
    chain = language_normalization_prompt | normalizer_model | language_normalization_parser
    try:
        payload = chain.invoke({"transcript": text})
        normalized_text = (payload.get("normalized_english_transcript") or text).strip()
        detected_language = (payload.get("detected_language") or "unknown").strip()
        translation_applied = bool(payload.get("translation_applied"))
        domain_keyword_mapping = payload.get("domain_keyword_mapping") or []
        return {
            "detected_language": detected_language,
            "translation_applied": translation_applied,
            "normalized_transcript": normalized_text or text,
            "domain_keyword_mapping": domain_keyword_mapping,
        }
    except Exception:
        return {
            "detected_language": "unknown",
            "translation_applied": False,
            "normalized_transcript": text,
            "domain_keyword_mapping": [],
        }


def enrich_context_with_workflow(transcript: str, structured_workflow, model=None):
    if not structured_workflow:
        return {
            "final_context": transcript,
            "workflow_steps": [],
            "business_goals": "",
        }

    enrichment_model = model or ChatOpenAI(model="gpt-4o", temperature=0)
    chain = context_enrichment_prompt | enrichment_model | context_enrichment_parser
    workflow_payload = (
        structured_workflow
        if isinstance(structured_workflow, str)
        else json.dumps(structured_workflow, indent=2)
    )
    enriched = chain.invoke(
        {
            "transcript": transcript,
            "structured_workflow": workflow_payload,
        }
    )
    return enriched


def validate_workflow_vs_requirements(structured_workflow, generated_requirements, model=None):
    if not structured_workflow:
        return {
            "missing_steps": [],
            "extra_logic": [],
            "coverage_score": 0,
        }

    validation_model = model or ChatOpenAI(model="gpt-4o", temperature=0)
    chain = workflow_validation_prompt | validation_model | workflow_validation_parser
    workflow_payload = (
        structured_workflow
        if isinstance(structured_workflow, str)
        else json.dumps(structured_workflow, indent=2)
    )
    requirements_payload = (
        generated_requirements
        if isinstance(generated_requirements, str)
        else json.dumps(generated_requirements, indent=2)
    )
    return chain.invoke(
        {
            "structured_workflow": workflow_payload,
            "generated_requirements": requirements_payload,
        }
    )


def understand_mermaid_workflow(mermaid_code: str, model=None):
    code = (mermaid_code or "").strip()
    if not code:
        return {"workflow": {"start": "", "steps": [], "decisions": []}}

    parser_model = model or ChatOpenAI(model="gpt-4o", temperature=0)
    chain = mermaid_understanding_prompt | parser_model | mermaid_understanding_parser
    return chain.invoke({"mermaid_code": code})


def _serialize_structured_workflow(structured_workflow) -> str:
    if not structured_workflow:
        return ""
    if isinstance(structured_workflow, str):
        return structured_workflow.strip()
    try:
        return json.dumps(structured_workflow, indent=2)
    except Exception:
        return str(structured_workflow).strip()


def normalize_workflow_input(raw_input: str, model=None) -> Dict[str, Any]:
    text = (raw_input or "").strip()
    if not text:
        return {
            "workflow_name": "Primary Workflow",
            "workflow_summary": "Main workflow inferred from the provided input.",
            "key_steps": [],
            "actors": [],
        }

    normalizer_model = model or ChatOpenAI(model="gpt-4o", temperature=0)
    chain = input_normalizer_prompt | normalizer_model | input_normalizer_parser
    try:
        payload = chain.invoke({"raw_input": text})
        return {
            "workflow_name": (payload.get("workflow_name") or "Primary Workflow").strip(),
            "workflow_summary": (payload.get("workflow_summary") or "Main workflow inferred from the provided input.").strip(),
            "key_steps": [step.strip() for step in (payload.get("key_steps") or []) if (step or "").strip()],
            "actors": payload.get("actors") or [],
        }
    except Exception:
        return {
            "workflow_name": "Primary Workflow",
            "workflow_summary": "Main workflow inferred from the provided input.",
            "key_steps": [],
            "actors": [],
        }


def extract_workflow_intent(workflow_input: Dict[str, Any], model=None) -> Dict[str, Any]:
    extractor_model = model or ChatOpenAI(model="gpt-4o", temperature=0)
    intent_parser = JsonOutputParser(pydantic_object=Intent)
    chain = intent_extraction_prompt | extractor_model | intent_parser
    try:
        payload = chain.invoke({"workflow_input": json.dumps(workflow_input, indent=2)})
        goals = [goal.strip() for goal in (payload.get("goals") or []) if (goal or "").strip()]
        return {"goals": goals}
    except Exception:
        return {"goals": []}


def extract_capabilities(workflow_input: Dict[str, Any], intent_payload: Dict[str, Any], model=None) -> Dict[str, Any]:
    abstraction_model = model or ChatOpenAI(model="gpt-4o", temperature=0)
    chain = capability_abstraction_prompt | abstraction_model | capability_parser
    try:
        payload = chain.invoke(
            {
                "workflow_input": json.dumps(workflow_input, indent=2),
                "intent_payload": json.dumps({"intent": intent_payload}, indent=2),
            }
        )
        return {"capabilities": payload.get("capabilities") or []}
    except Exception:
        return {"capabilities": []}


def generate_requirements_from_workflow(
    workflow_payload: Dict[str, Any],
    intent_payload: Dict[str, Any],
    capability_payload: Dict[str, Any],
    context: str,
    input_text: str,
    structured_workflow,
    model=None,
) -> Dict[str, Any]:
    generation_model = model or ChatOpenAI(model="gpt-4o", temperature=0)
    chain = requirement_generation_prompt | generation_model | single_workflow_parser
    structured_workflow_payload = (
        structured_workflow
        if isinstance(structured_workflow, str)
        else json.dumps(structured_workflow, indent=2)
    ) if structured_workflow else "None"
    return chain.invoke(
        {
            "workflow_payload": json.dumps(workflow_payload, indent=2),
            "intent_payload": json.dumps({"intent": intent_payload}, indent=2),
            "capability_payload": json.dumps(capability_payload, indent=2),
            "context": context,
            "input_text": input_text,
            "structured_workflow": structured_workflow_payload,
        }
    )


def complete_workflow_requirements(workflow_payload: Dict[str, Any], model=None) -> Dict[str, Any]:
    completion_model = model or ChatOpenAI(model="gpt-4o", temperature=0)
    chain = requirement_completeness_prompt | completion_model | single_workflow_parser
    return chain.invoke({"workflow_payload": json.dumps(workflow_payload, indent=2)})


def validate_workflow_output(workflow_payload: Dict[str, Any], model=None) -> Dict[str, Any]:
    validator_model = model or ChatOpenAI(model="gpt-4o", temperature=0)
    chain = strict_validator_prompt | validator_model | single_workflow_parser
    return chain.invoke({"workflow_payload": json.dumps(workflow_payload, indent=2)})


def consistency_align_workflow_payload(workflow_payload: Dict[str, Any], model=None) -> Dict[str, Any]:
    alignment_model = model or ChatOpenAI(model="gpt-4o", temperature=0)
    chain = consistency_alignment_prompt | alignment_model | single_workflow_parser
    return chain.invoke({"workflow_payload": json.dumps(workflow_payload, indent=2)})


def final_system_align_workflow_payload(workflow_payload: Dict[str, Any], model=None) -> Dict[str, Any]:
    alignment_model = model or ChatOpenAI(model="gpt-4o", temperature=0)
    chain = final_system_alignment_prompt | alignment_model | single_workflow_parser
    return chain.invoke({"workflow_payload": json.dumps(workflow_payload, indent=2)})


def _discover_workflows(chunks: List[str], model):
    discovered = []

    discovery_chain = workflow_discovery_prompt | model | workflow_discovery_parser
    for chunk in chunks:
        result = discovery_chain.invoke({"chunk_text": chunk})
        discovered.extend(result.get("workflows", []))

    if not discovered:
        return []

    consolidation_chain = workflow_consolidation_prompt | model | workflow_discovery_parser
    consolidated = consolidation_chain.invoke(
        {"discovered_workflows": json.dumps({"workflows": discovered}, indent=2)}
    )
    return consolidated.get("workflows", [])


def _extract_client_intent_transcript(transcript: str) -> str:
    return extract_client_intent_transcript(transcript)


def _anchor_transcript_to_client_problem_scope(transcript: str) -> str:
    return anchor_transcript_to_client_problem_scope(transcript)


def _detect_alignment_issues(transcript: str, workflow: Dict[str, Any]) -> List[str]:
    return detect_alignment_issues(transcript, workflow)


def _convert_generic_payload_to_workflow(payload: Dict[str, Any], fallback_candidate: Dict[str, Any]) -> Dict[str, Any]:
    workflow_header = payload.get("workflow", {}) or {}
    intent = payload.get("intent", {}) or {}
    actors = payload.get("actors", []) or []
    capabilities = payload.get("capabilities", []) or []
    epics = payload.get("epics", []) or []

    workflow_name = (workflow_header.get("name") or fallback_candidate.get("workflow_name") or "Primary Workflow").strip()
    workflow_summary = (workflow_header.get("summary") or fallback_candidate.get("workflow_summary") or "").strip()

    normalized_capabilities = []
    for index, capability in enumerate(capabilities, start=1):
        normalized_capabilities.append(
            {
                "capability_id": (capability.get("capability_id") or f"CAP-{index}").strip(),
                "name": (capability.get("name") or f"Capability {index}").strip(),
                "description": (
                    capability.get("description")
                    or f"Ability to support the workflow stage '{capability.get('name') or f'Capability {index}'}'."
                ).strip(),
            }
        )
    capability_refs = {
        item["capability_id"]: f"{item['capability_id']}: {item['name']}"
        for item in normalized_capabilities
        if item.get("capability_id") and item.get("name")
    }

    normalized_epics = []
    for epic_index, epic in enumerate(epics, start=1):
        normalized_requirements = []
        for requirement_index, req in enumerate(epic.get("requirements", []) or [], start=1):
            description = (req.get("description") or "").strip()
            title = (req.get("title") or f"Requirement {requirement_index}").strip()
            acceptance = [item.strip() for item in (req.get("acceptance_criteria") or []) if (item or "").strip()]
            edge_cases = [item.strip() for item in (req.get("edge_cases") or []) if (item or "").strip()]
            dependencies = [item.strip() for item in (req.get("dependencies") or []) if (item or "").strip()]
            inputs = _as_list(req.get("inputs"))
            outputs = _as_list(req.get("outputs"))
            if description and not description.lower().startswith("the system shall"):
                description = f"The system shall {description[0].lower()}{description[1:]}" if len(description) > 1 else "The system shall support the workflow."
            if not acceptance:
                acceptance = []
            if not inputs:
                inputs = []
            if not outputs:
                outputs = []
            if not edge_cases:
                edge_cases = []
            if not dependencies:
                dependencies = []
            normalized_requirements.append(
                {
                    "req_id": (req.get("req_id") or "").strip(),
                    "title": title,
                    "description": description or "",
                    "requirement_description": description or "",
                    "user_story": (req.get("user_story") or "").strip(),
                    "inputs": inputs,
                    "outputs": outputs,
                    "acceptance_criteria": acceptance,
                    "edge_cases": edge_cases,
                    "dependencies": [
                        capability_refs.get(item, item)
                        for item in dependencies
                        if (item or "").strip()
                    ],
                    "priority": (req.get("priority") or "high").strip().lower(),
                }
            )

        normalized_epics.append(
            {
                "epic_id": (epic.get("epic_id") or f"EPIC-{epic_index}").strip(),
                "title": (epic.get("title") or f"Workflow Stage {epic_index}").strip(),
                "user_story": (
                    epic.get("user_story")
                    or f"As a user, I want the system to complete {epic.get('title') or f'workflow stage {epic_index}'}, so that the workflow progresses with reliable outputs."
                ).strip(),
                "mapped_capabilities": epic.get("mapped_capabilities") or [],
                "requirements": normalized_requirements,
            }
        )

    return {
        "workflow_id": (workflow_header.get("id") or "").strip(),
        "workflow_name": workflow_name,
        "workflow_summary": workflow_summary,
        "intent": {"goals": intent.get("goals") or []},
        "capabilities": normalized_capabilities,
        "actors": actors,
        "epics": normalized_epics,
    }


def _generate_single_workflow(
    workflow_candidate,
    transcript: str,
    vectorstore,
    chunk_count: int,
    model,
    structured_workflow=None,
):
    query = f"{workflow_candidate['workflow_name']}. {workflow_candidate['workflow_summary']}"
    context_k = min(max(chunk_count, 4), 12)
    fetch_k = min(max(context_k * 2, 8), 24)
    retriever = vectorstore.as_retriever(
        search_kwargs={"k": context_k},
        search_type="mmr",
        fetch_k=fetch_k,
    )
    docs = retriever.invoke(query)
    context = "\n\n".join(doc.page_content for doc in docs)

    raw_workflow_input = json.dumps(
        {
            "workflow_name": workflow_candidate["workflow_name"],
            "workflow_summary": workflow_candidate["workflow_summary"],
            "retrieved_context": context,
            "transcript": transcript,
            "structured_workflow": structured_workflow or {},
        },
        indent=2,
    )
    normalized_workflow = normalize_workflow_input(raw_workflow_input, model=model)
    workflow_input_payload = {
        "workflow_name": normalized_workflow.get("workflow_name") or workflow_candidate["workflow_name"],
        "workflow_summary": normalized_workflow.get("workflow_summary") or workflow_candidate["workflow_summary"],
        "key_steps": normalized_workflow.get("key_steps") or [],
        "actors": normalized_workflow.get("actors") or [],
    }
    intent_payload = extract_workflow_intent(workflow_input_payload, model=model)
    capability_payload = extract_capabilities(workflow_input_payload, intent_payload, model=model)
    generated_payload = generate_requirements_from_workflow(
        workflow_payload=workflow_input_payload,
        intent_payload=intent_payload,
        capability_payload=capability_payload,
        context=context,
        input_text=transcript,
        structured_workflow=structured_workflow,
        model=model,
    )
    if REQ_FAST_MODE:
        workflow = _convert_generic_payload_to_workflow(generated_payload, workflow_candidate)
    else:
        completed_payload = complete_workflow_requirements(generated_payload, model=model)
        validated_payload = validate_workflow_output(completed_payload, model=model)
        consistency_aligned_payload = consistency_align_workflow_payload(validated_payload, model=model)
        final_aligned_payload = final_system_align_workflow_payload(consistency_aligned_payload, model=model)
        workflow = _convert_generic_payload_to_workflow(final_aligned_payload, workflow_candidate)

    if not workflow.get("actors"):
        workflow["actors"] = normalized_workflow.get("actors") or []
    if not workflow.get("intent", {}).get("goals"):
        workflow["intent"] = {"goals": intent_payload.get("goals") or []}
    if not workflow.get("capabilities"):
        workflow["capabilities"] = capability_payload.get("capabilities") or []

    if REQ_FAST_MODE:
        return workflow

    alignment_issues = _detect_alignment_issues(transcript, workflow)
    if not alignment_issues:
        return workflow

    strict_context = (
        f"{context}\n\n"
        "SELF-CORRECTION REQUIRED:\n"
        "Regenerate requirements with strict alignment. Fix these violations:\n"
        f"{json.dumps(alignment_issues, indent=2)}\n\n"
        "Enforce hard problem lock, forbidden generation rule, input-format enforcement, and terminology mapping enforcement."
    )
    retry = generate_requirements_from_workflow(
        workflow_payload=workflow_input_payload,
        intent_payload=intent_payload,
        capability_payload=capability_payload,
        context=strict_context,
        input_text=transcript,
        structured_workflow=structured_workflow,
        model=model,
    )
    retried_workflow = _convert_generic_payload_to_workflow(
        final_system_align_workflow_payload(
            consistency_align_workflow_payload(
                validate_workflow_output(complete_workflow_requirements(retry, model=model), model=model),
                model=model,
            ),
            model=model,
        ),
        workflow_candidate,
    )
    retry_issues = _detect_alignment_issues(transcript, retried_workflow)
    if not retry_issues:
        return retried_workflow

    final_strict_context = (
        f"{strict_context}\n\n"
        "FINAL REGENERATION MODE:\n"
        "Return only transcript-grounded requirements.\n"
        "Delete any capability, KPI, actor, dependency, or domain term not explicitly supported by transcript evidence.\n"
        f"Remaining violations: {json.dumps(retry_issues, indent=2)}"
    )
    final_retry = generate_requirements_from_workflow(
        workflow_payload=workflow_input_payload,
        intent_payload=intent_payload,
        capability_payload=capability_payload,
        context=final_strict_context,
        input_text=transcript,
        structured_workflow=structured_workflow,
        model=model,
    )
    return _convert_generic_payload_to_workflow(
        final_system_align_workflow_payload(
            consistency_align_workflow_payload(
                validate_workflow_output(complete_workflow_requirements(final_retry, model=model), model=model),
                model=model,
            ),
            model=model,
        ),
        workflow_candidate,
    )


def _normalize_requirement_ids(requirements_payload, transcript: str = ""):
    collapsed = collapse_requirement_workflows(requirements_payload, transcript=transcript)
    workflows = collapsed.get("workflows", []) if isinstance(collapsed, dict) else []
    normalized_workflows = []

    for workflow_index, workflow in enumerate(workflows, start=1):
        normalized_workflow = _normalize_workflow_record(workflow, workflow_index)

        def _normalized_capability_reference(raw_dependency: str) -> str:
            dependency = (raw_dependency or "").strip()
            if not dependency:
                return ""
            lowered = dependency.lower()
            if lowered in capability_ref_map:
                return capability_ref_map[lowered]
            if dependency in capability_id_map:
                mapped_id = capability_id_map[dependency]
                mapped_name = next(
                    (cap.get("name") for cap in normalized_capabilities if cap.get("capability_id") == mapped_id),
                    "",
                )
                return f"{mapped_id}: {mapped_name}" if mapped_name else mapped_id
            return dependency

        normalized_capabilities = []
        capability_id_map = {}
        capability_ref_map = {}
        for capability_index, capability in enumerate(normalized_workflow.get("capabilities", []), start=1):
            new_capability_id = f"CAP-{capability_index}"
            original_capability_id = (capability.get("capability_id") or "").strip()
            capability_name = (capability.get("name") or "").strip()
            if original_capability_id:
                capability_id_map[original_capability_id] = new_capability_id
                if capability_name:
                    capability_ref_map[f"{original_capability_id}: {capability_name}".lower()] = f"{new_capability_id}: {capability_name}"
            normalized_capabilities.append(
                {
                    **capability,
                    "capability_id": new_capability_id,
                }
            )
        normalized_workflow["capabilities"] = normalized_capabilities

        requirement_counter = 1
        normalized_epics = []
        for epic_index, epic in enumerate(normalized_workflow.get("epics", []), start=1):
            normalized_epic = {**epic}
            normalized_epic["epic_id"] = f"EPIC-{epic_index}"
            mapped_capabilities = epic.get("mapped_capabilities") or []
            normalized_epic["mapped_capabilities"] = [
                capability_id_map.get(capability_id, capability_id)
                for capability_id in mapped_capabilities
                if capability_id_map.get(capability_id, capability_id)
            ]

            normalized_requirements = []
            for requirement in epic.get("requirements", []):
                normalized_requirement = _normalize_requirement_detail_block(
                    requirement,
                    normalized_workflow.get("workflow_name", ""),
                    normalized_epic.get("title", ""),
                    transcript=transcript,
                )
                normalized_requirement["req_id"] = f"REQ-{requirement_counter}"
                normalized_requirement["dependencies"] = [
                    _normalized_capability_reference(dependency)
                    for dependency in (normalized_requirement.get("dependencies") or [])
                    if _normalized_capability_reference(dependency)
                ]
                normalized_requirements.append(normalized_requirement)
                requirement_counter += 1

            normalized_epic["requirements"] = normalized_requirements
            normalized_epics.append(normalized_epic)

        normalized_workflow["epics"] = normalized_epics
        normalized_workflow["workflow_id"] = f"WF-{workflow_index}"
        normalized_workflow["workflow_name"] = normalized_workflow.get("workflow_name", "")
        normalized_workflow["workflow_summary"] = normalized_workflow.get("workflow_summary", "")
        normalized_workflow["intent"] = normalized_workflow.get("intent") or {"goals": []}
        normalized_workflows.append(normalized_workflow)

    return {"workflows": normalized_workflows}


def _normalize_scope_review_ids(scope_review, requirements_payload):
    if not scope_review:
        return scope_review

    normalized_workflows = []
    requirement_workflows = requirements_payload.get("workflows", []) if requirements_payload else []

    for workflow_index, workflow_review in enumerate(scope_review.get("workflows", []), start=1):
        normalized_workflow_review = {**workflow_review}
        normalized_workflow_review["workflow_id"] = f"WF-{workflow_index}"

        requirement_lookup = {}
        if workflow_index - 1 < len(requirement_workflows):
            workflow_requirements = requirement_workflows[workflow_index - 1].get("epics", [])
            for epic in workflow_requirements:
                for requirement in epic.get("requirements", []):
                    title_key = (requirement.get("title") or "").strip().lower()
                    if title_key:
                        requirement_lookup[title_key] = requirement.get("req_id")

        normalized_items = []
        for requirement_index, item in enumerate(workflow_review.get("requirements", []), start=1):
            normalized_item = {**item}
            title_key = (item.get("title") or "").strip().lower()
            normalized_item["req_id"] = requirement_lookup.get(title_key, f"REQ-{requirement_index}")
            normalized_items.append(normalized_item)

        normalized_workflow_review["requirements"] = normalized_items
        normalized_workflows.append(normalized_workflow_review)

    return {"workflows": normalized_workflows}


def merge_requirement_payloads(existing_requirements, new_requirements):
    existing_payload = collapse_requirement_workflows(existing_requirements)
    new_payload = collapse_requirement_workflows(new_requirements)

    merged_workflows = (existing_payload.get("workflows") or []) + (new_payload.get("workflows") or [])
    return _normalize_requirement_ids({"workflows": merged_workflows})


def merge_scope_review_payloads(existing_scope_review, new_scope_review):
    if not existing_scope_review:
        return new_scope_review
    if not new_scope_review:
        return existing_scope_review

    merged_workflows = (existing_scope_review.get("workflows") or []) + (new_scope_review.get("workflows") or [])
    return {"workflows": merged_workflows}


def _workflow_signature_tokens(workflow: Dict[str, Any]) -> set:
    from .workflow_postprocessing import workflow_signature_tokens

    return workflow_signature_tokens(workflow)


def _merge_workflow_pair(primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, Any]:
    from .workflow_postprocessing import merge_workflow_pair

    return merge_workflow_pair(primary, secondary)


def _dedupe_and_merge_similar_workflows(workflows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from .workflow_postprocessing import dedupe_and_merge_similar_workflows

    return dedupe_and_merge_similar_workflows(workflows)


def _transcript_indicates_multiple_initiatives(transcript: str) -> bool:
    from .workflow_postprocessing import transcript_indicates_multiple_initiatives

    return transcript_indicates_multiple_initiatives(transcript)


def _collapse_to_single_workflow_if_needed(workflows: List[Dict[str, Any]], transcript: str) -> List[Dict[str, Any]]:
    from .workflow_postprocessing import collapse_to_single_workflow_if_needed

    return collapse_to_single_workflow_if_needed(workflows, transcript)


def _transcript_has_explicit_sla_or_accuracy_targets(transcript: str) -> bool:
    from .workflow_postprocessing import transcript_has_explicit_sla_or_accuracy_targets

    return transcript_has_explicit_sla_or_accuracy_targets(transcript)


def _strip_ungrounded_numeric_targets(workflow: Dict[str, Any], transcript: str) -> Dict[str, Any]:
    from .workflow_postprocessing import strip_ungrounded_numeric_targets

    return strip_ungrounded_numeric_targets(workflow, transcript)


def _normalize_validation_summary(workflow: Dict[str, Any]) -> Dict[str, Any]:
    from .workflow_postprocessing import normalize_validation_summary

    return normalize_validation_summary(workflow)


def _post_process_generated_workflows(workflows: List[Dict[str, Any]], transcript: str) -> List[Dict[str, Any]]:
    return post_process_generated_workflows(workflows, transcript)


def generate_requirements(input_text: str, structured_workflow=None):
    transcript = (input_text or "").strip()
    workflow_context_text = _serialize_structured_workflow(structured_workflow)
    if not transcript and not workflow_context_text:
        raise ValueError("Either a meeting transcript or structured workflow is required")

    if transcript:
        # IMPORTANT: filter/anchor on raw transcript BEFORE normalization and cleaning,
        # because those steps can remove speaker/timestamp structures.
        transcript = _extract_client_intent_transcript(transcript)
        transcript = _anchor_transcript_to_client_problem_scope(transcript)

        normalized = normalize_transcript_language(transcript)
        transcript = normalized.get("normalized_transcript", transcript).strip() or transcript

        cleaned_transcript = clean_input_text(transcript)
        if cleaned_transcript:
            transcript = cleaned_transcript
    else:
        transcript = workflow_context_text

    model = ChatOpenAI(model="gpt-4o", temperature=0)
    if not REQ_FAST_MODE:
        enriched_context = enrich_context_with_workflow(transcript, structured_workflow, model=model)
        transcript = (enriched_context.get("final_context") or transcript or workflow_context_text).strip()
    transcript_for_generation = transcript

    splitter = RecursiveCharacterTextSplitter(chunk_size=1400, chunk_overlap=160)
    chunks = splitter.split_text(transcript_for_generation)
    if not chunks:
        chunks = [transcript_for_generation]

    embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
    vectorstore = FAISS.from_texts(chunks, embeddings)

    workflow_candidates = []
    if not REQ_FAST_MODE and (input_text or "").strip() and not structured_workflow:
        workflow_candidates = _discover_workflows(chunks, model)
    if not workflow_candidates:
        normalized_workflow = normalize_workflow_input(
            workflow_context_text or transcript_for_generation,
            model=model,
        )
        workflow_candidates = [
            {
                "workflow_name": normalized_workflow.get("workflow_name") or "Primary Workflow",
                "workflow_summary": normalized_workflow.get("workflow_summary")
                or (
                    "Main workflow inferred from the provided workflow context."
                    if workflow_context_text and not (input_text or "").strip()
                    else "Main workflow inferred from the transcript."
                ),
                "evidence": [],
            }
        ]

    workflows = []
    for workflow_candidate in workflow_candidates:
        workflow = _generate_single_workflow(
            workflow_candidate=workflow_candidate,
            transcript=transcript_for_generation,
            vectorstore=vectorstore,
            chunk_count=len(chunks),
            model=model,
            structured_workflow=structured_workflow,
        )
        if workflow:
            workflows.append(workflow)

    workflows = _post_process_generated_workflows(workflows, transcript_for_generation)
    workflows = collapse_requirement_workflows({"workflows": workflows}, transcript=transcript_for_generation).get("workflows", [])
    return _normalize_requirement_ids({"workflows": workflows}, transcript=transcript_for_generation)


def refine_requirements(existing_requirements, user_feedback: str):
    if not existing_requirements:
        raise ValueError("Existing requirements are required for refinement")

    feedback = (user_feedback or "").strip()
    if not feedback:
        raise ValueError("User feedback is required for refinement")
    normalized_feedback = normalize_transcript_language(feedback)
    feedback = normalized_feedback.get("normalized_transcript", feedback).strip() or feedback

    if isinstance(existing_requirements, str):
        existing_payload = existing_requirements
    else:
        existing_payload = json.dumps(existing_requirements, indent=2)

    model = ChatOpenAI(model="gpt-4o", temperature=0)

    chain = refinement_prompt | model | parser
    refined = chain.invoke(
        {
            "existing_requirements": existing_payload,
            "user_feedback": feedback,
        }
    )
    workflows = (refined or {}).get("workflows", [])
    workflows = _post_process_generated_workflows(workflows, feedback)
    workflows = collapse_requirement_workflows({"workflows": workflows}, transcript=feedback).get("workflows", [])
    return _normalize_requirement_ids({"workflows": workflows}, transcript=feedback)


def scope_control_requirements(transcript: str, requirements):
    transcript_text = (transcript or "").strip()
    if not transcript_text:
        raise ValueError("Transcript is required for scope control")

    cleaned_transcript = clean_input_text(transcript_text)
    if cleaned_transcript:
        transcript_text = cleaned_transcript
    normalized = normalize_transcript_language(transcript_text)
    transcript_text = normalized.get("normalized_transcript", transcript_text).strip() or transcript_text

    if not requirements:
        raise ValueError("Generated requirements are required for scope control")

    requirements_payload = requirements if isinstance(requirements, str) else json.dumps(requirements, indent=2)
    model = ChatOpenAI(model="gpt-4o", temperature=0)
    chain = scope_control_prompt | model | scope_consolidation_parser
    cleaned_requirements = chain.invoke(
        {
            "transcript": transcript_text,
            "requirements": requirements_payload,
        }
    )
    workflows = (cleaned_requirements or {}).get("workflows", [])
    workflows = _post_process_generated_workflows(workflows, transcript_text)
    workflows = collapse_requirement_workflows({"workflows": workflows}, transcript=transcript_text).get("workflows", [])
    return _normalize_requirement_ids({"workflows": workflows}, transcript=transcript_text)


def apply_scope_control(requirements, scope_review):
    if not requirements or not scope_review:
        return requirements

    if isinstance(scope_review, dict):
        scope_workflows = scope_review.get("workflows", [])
        if scope_workflows and any(workflow.get("epics") for workflow in scope_workflows):
            return _normalize_requirement_ids(scope_review)

    workflows = requirements.get("workflows", [])
    review_map = {
        workflow_review.get("workflow_id"): {
            item.get("req_id"): item
            for item in workflow_review.get("requirements", [])
        }
        for workflow_review in scope_review.get("workflows", [])
    }

    filtered_workflows = []
    for workflow in workflows:
        workflow_id = workflow.get("workflow_id")
        decisions = review_map.get(workflow_id, {})
        new_workflow = {**workflow}
        new_epics = []

        for epic in workflow.get("epics", []):
            new_epic = {**epic}
            new_requirements = []

            for requirement in epic.get("requirements", []):
                decision = decisions.get(requirement.get("req_id"))
                if decision:
                    if decision.get("action") == "remove" or decision.get("scope") == "OUT_OF_SCOPE":
                        continue
                    requirement = {
                        **requirement,
                        "priority": decision.get("priority", requirement.get("priority")),
                        "scope": decision.get("scope"),
                        "scope_action": decision.get("action"),
                        "scope_reason": decision.get("reason"),
                    }
                new_requirements.append(requirement)

            if new_requirements:
                new_epic["requirements"] = new_requirements
                new_epics.append(new_epic)

        if new_epics:
            new_workflow["epics"] = new_epics
            filtered_workflows.append(new_workflow)

    return {"workflows": filtered_workflows}


def append_requirements_history(input_text: str, response, output_file: str = "requirements.json"):
    new_record = {
        "transcript": input_text,
        "analysis": response,
    }

    if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
        with open(output_file, "r", encoding="utf-8") as f:
            try:
                history = json.load(f)
                if not isinstance(history, list):
                    history = [history]
            except json.JSONDecodeError:
                history = []
    else:
        history = []

    history.append(new_record)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=4)


def load_existing_requirements(input_source: str):
    source = (input_source or "").strip()
    if not source:
        raise ValueError("Existing requirements input is required")

    if os.path.exists(source):
        with open(source, "r", encoding="utf-8") as f:
            return json.load(f)

    return json.loads(source)


def main():
    mode = input("Choose mode (generate/refine/scope): ").strip().lower()

    if mode == "refine":
        existing_source = input("Enter existing requirements JSON or file path: ")
        user_feedback = input("Enter user feedback: ")
        existing_requirements = load_existing_requirements(existing_source)
        response = refine_requirements(existing_requirements, user_feedback)
        append_requirements_history(user_feedback, response, output_file="requirements_refined.json")
        print("Refinement completed and appended to requirements_refined.json")
    elif mode == "scope":
        transcript = input("Enter the meeting transcript: ")
        requirements_source = input("Enter generated requirements JSON or file path: ")
        requirements = load_existing_requirements(requirements_source)
        response = scope_control_requirements(transcript, requirements)
        append_requirements_history(transcript, response, output_file="requirements_scope_control.json")
        print("Scope control completed and appended to requirements_scope_control.json")
    else:
        input_text = input("Enter the meeting transcript: ")
        response = generate_requirements(input_text)
        append_requirements_history(input_text, response)
        print("Analysis completed and appended to requirements.json")

    print(json.dumps(response, indent=4))


if __name__ == "__main__":
    main()
