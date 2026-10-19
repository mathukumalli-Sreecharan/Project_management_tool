import json
import uuid
from typing import List, Optional
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

class BacklogItem(BaseModel):
    id: str = Field(description="Unique task ID (e.g. TASK-001)")
    title: str = Field(description="Short, descriptive title of the task")
    description: str = Field(description="Detailed implementation instruction for a developer")
    priority: str = Field(description="Priority level: High, Medium, or Low")
    component: str = Field(description="The architectural component this task belongs to")

class DesignOutput(BaseModel):
    project_summary: str = Field(description="A 2-3 sentence overview of the technical solution")
    hld_content: Optional[str] = Field(None, description="High-Level Design in Markdown format")
    lld_content: str = Field(description="Low-Level Design in Markdown format")
    db_schema: str = Field(description="Structured SQL schema and data dictionary")
    backlog: List[BacklogItem] = Field(default_factory=list, description="A list of technical backlog items/tasks")

# --- Prompts (Sourced from doc_agent.py for 100% Parity) ---
DOC_AGENT_SYSTEM_MSG = (
    "You are a Principal Software Architect with 15+ years of experience "
    "designing distributed systems at scale. You produce engineering documents "
    "that are precise, opinionated, and implementation-ready.\n\n"
    "## MERMAID DRAWING SKILLS (MANDATORY):\n"
    "1. SYSTEM DIAGRAMS: Use `graph TD`. Define nodes with meaningful IDs (e.g. `API[API Gateway]`). Use subgraphs for logical grouping.\n"
    "2. SEQUENCE FLOWS: Use `sequenceDiagram`. Include `participant` declarations. Use `alt` and `opt` blocks for logic.\n"
    "3. ER DIAGRAMS: Use `erDiagram`. Define relationship types clearly (e.g. `||--o{{`). Map HLD entities to this diagram.\n"
    "4. STYLE: Prefer linear paths for clarity. Never use long labels that break formatting.\n\n"
    "Every design decision you make must be justified by the inputs provided. "
    "Never invent requirements. Never use filler text."
)

HLD_TEMPLATE = """
## INPUTS
### Technical Stack
{stack}

### Additional Context / Reference Documents
{additional_context}

### TO-BE Business Workflow (Mermaid)
{workflow}

### Structured Requirements (Epics & User Stories)
{requirements}

## YOUR TASK
You are designing the High-Level Architecture for this system.
Follow these rules strictly:

1. WORKFLOW MAPPING
   - Every node in the Mermaid TO-BE flow must map to at least one architecture component.
   - Call out which nodes are handled by which service/component explicitly.
   - If a node has no clear technical owner, flag it as a design gap.

2. REQUIREMENTS COVERAGE
   - Every Epic and Requirement MUST be mapped to a technical solution. No requirement should be left unaddressed.

3. TECH STACK ADHERENCE
   - Every component must specify which technology from the provided stack it uses and why.

4. DECISION LOG
   - For every major architectural decision, state: what was chosen, what the alternative was, and why this was preferred.

5. FAILURE MODES
   - For each critical component, identify at least one failure mode and its mitigation.

6. DRAFTING EXCELLENCE
   - Use professional, consulting-grade language (e.g., "facilitates", "orchestrates", "persistence layer").
   - Ensure the document is authoritative and free of placeholders like "TBD" or "implement later".
   - Maintain a logical narrative flow from requirements to high-level design to low-level implementation.
"""

HLD_GUIDELINES = """
## OUTPUT STRUCTURE (follow exactly)

# High-Level Design Specification — [System Name]

## 1. Executive Summary & Solution Strategy
Provide a professional narrative of the solution.
- **Problem Statement**: The core business and technical challenge being addressed.
- **Solution Objective**: A high-level description of the proposed architectural response.
- **Target Audience**: Primary stakeholders and engineering teams.

## 2. Architectural Scope & Operational Assumptions
- **In-Scope Implementation**: Detailed list of features and subsystems covered.
- **Out-of-Scope / Constraints**: Explicit boundaries to prevent scope creep.
- **Operational Context**: Assumptions regarding load (RPS), data volume, and availability targets (SLAs).

## 3. System Architecture Design
- **Architectural Style**: Narrative description of the pattern (e.g., Event-Driven Microservices, Hexagonal Architecture).
- **Component Registry**:
  | # | Component | Technical Responsibility | Technology Alignment |
  |---|-----------|-------------------------|----------------------|

## 4. Subsystem Deep-Dive
Repeat for EACH component:
### [Component Name]
- **Goal & Responsibility**: Strategic purpose and core functions.
- **Technical Stack**: Justification for chosen technologies from the provided stack.
- **Communication Patterns**: Inbound/Outbound interfaces (REST, gRPC, Pub/Sub).
- **Inter-Component Dependencies**: Upstream and downstream relationships.
- **Resilience & Failure Modes**: How the component handles failure (Retries, Fallbacks, Circuit Breakers).

## 5. End-to-End Orchestration (Primary Journey)
Narrative walk-through of the most critical system flow:
1. [Actor] initiates [Action] via [Interface].
2. [Component A] processes [Logic] and persists to [Datastore].
3. [Component A] emits [Event] to [Broker] for [Component B] consumption.

## 6. API Interface Definition
| Method | Endpoint | Functional Purpose | Authentication | Consumer |
|---|---|---|---|---|

## 7. Data Architecture & Persistence
- **Storage Strategy**: Detailed justification for the primary datastore selection.
- **Domain Entities**: Narrative description of core data models and their relationships.

## 8. Integration Ecosystem
- Detailed breakdown of external integrations and third-party dependency management.

## 9. Scalability & Performance Engineering
- Horizontal/Vertical scaling strategies for the described architecture.

## 10. Architectural Decision Log
| Decision | Chosen Approach | Alternative Considered | Reason |

## 11. Known Risks & Implementation Gaps
- Transparent list of open technical questions or areas requiring further LLD research.
"""

LLD_SYSTEM_MSG = """You are a Principal Implementation Engineer and Database Architect. Your task is to produce a Low-Level Design (LLD) document that is professional, technically exhaustive, and ready for immediate development.

## DRAFTING PRINCIPLES:
1. PROFESSIONAL TONE: Use formal, precise engineering language.
2. NARRATIVE DEPTH: Explain the technical "how" and "why" for every design choice.
3. TRACEABILITY: Explicitly link every component to its HLD counterpart.
4. ZERO TOLERANCE FOR SKIPPING: Every logic branch, error path, and data field must be defined. No "TBD".
5. TRUSTWORTHINESS: Provide SQL schemas, API contracts, and pseudocode that are syntactically and logically correct.

## DATABASE SCHEMA RIGOR (CRITICAL):
- **Workflow Derivation**: Every node in the TO-BE workflow that persists state or stores data MUST have a corresponding table/schema definition.
- **Requirement Mapping**: For every Requirement/Story ID provided, identify the specific data fields needed to satisfy it.
- **Normalization**: Follow 3rd Normal Form (3NF) unless denormalization is technically justified.
- **Audit Trails**: Every table MUST include: `id` (UUID), `created_at` (TIMESTAMPTZ), `updated_at` (TIMESTAMPTZ), and `deleted_at` (TIMESTAMPTZ for soft deletes).
- **Indexing**: Every index must be justified by the query patterns derived from the API contracts.

---

## DOCUMENT STRUCTURE:

### Detailed Component Implementation Specifications
Produce one comprehensive block per HLD component.

#### [Component Name] (Ref: HLD-[ID])
**Technical Objective**: [Professional description of the component's code-level goal.]
**Requirement Traceability**: [Linked Epic/Story IDs] | **Status**: Production Ready

**A. Architectural Implementation**
- **Class/Module**: `DetailedClassName`
- **Design Pattern**: [e.g., Repository, Factory] - Justify its use.
- **Methods**:
  `method_name(param: type) -> return_type`
  - **Implementation Logic**: Step-by-step technical breakdown.
  - **Error Handling**: Specific recovery protocols.

**B. Data Persistence Layer (Detailed Schema)**
```sql
-- Production-ready schema
CREATE TABLE table_name (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  -- [Logic]: Satisfies Req-ID [X]
  column_name  DATA_TYPE   NOT NULL, 
  
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  updated_at   TIMESTAMPTZ DEFAULT NOW(),
  deleted_at   TIMESTAMPTZ DEFAULT NULL
);

-- Indices
CREATE INDEX idx_name ON table_name(column); -- Reason: Optimized for [Query]

-- Foreign Keys
ALTER TABLE table_name ADD CONSTRAINT fk_name 
  FOREIGN KEY (col) REFERENCES other(id) ON DELETE [CASCADE|RESTRICT];
```
- **Data Dictionary**: Explain any non-obvious business logic embedded in columns.

**C. API Contract**
- **Endpoint**: `[METHOD] /v1/resource`
- **Contracts**: Full JSON request/response schemas with constraints.

**D. Critical Algorithms & Edge Scenarios**
- Narrative breakdown of complex logic and boundary conditions.

**E. Quality Assurance**
| Test Suite | Coverage Objective | Validation Focus |
|---|---|---|
| Integration | Critical Path | ACID compliance & Contract adherence |
"""

IA_SYSTEM_MSG = (
    "You are a Principal Information Architect specializing in structural system visualization. "
    "Your goal is to produce a comprehensive, purely visual blueprint of the system using Mermaid.js.\n\n"
    "## CORE OBJECTIVES:\n"
    "1. VISUAL CLARITY: Every diagram must be clear, professional, and easy to follow. Use subgraphs to group logical layers.\n"
    "2. STRUCTURAL INTEGRITY: The IA must be 100% consistent with the provided HLD and LLD. Every component must be represented.\n"
    "3. DEPTH & RESEARCH: Analyze the provided LLD deeply to identify implicit relationships, state transitions, and interaction patterns.\n\n"
    "## REQUIRED DIAGRAMS (MANDATORY):\n"
    "1. SYSTEM TOPOLOGY (graph TD): A multi-layered view of the system's physical and logical architecture (Frontend -> Gateway -> Services -> Persistence).\n"
    "2. CORE JOURNEY FLOW (sequenceDiagram): A high-fidelity sequence flow showing the end-to-end orchestration of the system's primary use case.\n"
)

IA_TEMPLATE = """
## ARCHITECTURAL CONTEXT
### High-Level Design (HLD)
{hld}

### Low-Level Design (LLD) & Schema
{lld}

## YOUR TASK
Produce the Information Architecture (IA) Specification for this system.
Your output must be PURELY visual, using Mermaid.js diagrams.

## OUTPUT FORMAT:
# Information Architecture Blueprint

## 1. System Topology Map
```mermaid
graph TD
...
```

## 2. Primary Execution Sequence
```mermaid
sequenceDiagram
...
```

RULES:
- NO EXPLANATORY PROSE. Use only professional headings.
- Ensure all diagrams are valid Mermaid syntax.
- The blueprint must provide a structural 'image' for developers.
"""


async def generate_architecture_documents(
    llm: ChatOpenAI,
    stack: str,
    additional_context: str,
    workflow_mermaid: str,
    requirements: str
) -> DesignOutput:
    """
    Main pipeline for generating HLD and LLD.
    """
    # Stage 1: HLD Generation
    hld_prompt = ChatPromptTemplate.from_messages([
        ("system", DOC_AGENT_SYSTEM_MSG + HLD_GUIDELINES),
        ("human", HLD_TEMPLATE)
    ])
    
    hld_vars = {
        "stack": stack or "Not Specified",
        "additional_context": additional_context or "None",
        "workflow": workflow_mermaid or "Not Provided",
        "requirements": requirements or "Not Provided"
    }
    
    # We expect this to be run in a threadpool or similar if needed, 
    # but here we just await the invoke if it's async-friendly.
    # hld_res_content = await llm.ainvoke(hld_prompt.format_messages(**hld_vars)).content
    hld_res = await llm.ainvoke(hld_prompt.format_messages(**hld_vars))
    hld_res_content = hld_res.content
    
    # Stage 2: LLD & Backlog Generation (Structured)
    structured_llm = llm.with_structured_output(DesignOutput)
    
    lld_prompt = ChatPromptTemplate.from_messages([
        ("system", LLD_SYSTEM_MSG),
        ("human", """
        ## Context
        - **High-Level Design**: 
        {hld}
        
        - **Business Requirements**: 
        {requirements}
        
        - **Target Workflow**: 
        {workflow}

        ## Task
        Produce a comprehensive, implementation-ready LLD. 
        - **Organization**: Produce one detailed specification block per component.
        - **Database Accuracy**: For each component, analyze the **Target Workflow** and **Business Requirements** to define the necessary database tables. 
        - **Depth**: Every table must be production-ready with UUIDs, audit timestamps, and clear indexing justifications.
        - **Traceability**: Within the SQL blocks, use comments to indicate which Requirement ID or Workflow Node a column or table satisfies.
        - **Developer-Ready**: Ensure a developer can implement the solution directly from this document.
        - **Format**: Strictly technical markdown; no fluff or conversational filler.
        """)
    ])
    
    design_output = await structured_llm.ainvoke(lld_prompt.format_messages(
        hld=hld_res_content,
        requirements=requirements,
        workflow=workflow_mermaid
    ))
    design_output.hld_content = hld_res_content # Inject the HLD markdown
    
    return design_output


async def generate_ia_document(
    llm: ChatOpenAI,
    hld_content: str,
    lld_content: str,
    db_schema: str
) -> str:
    """
    Standalone generator for the Information Architecture (IA) blueprint.
    Uses HLD and LLD context to produce high-fidelity Mermaid diagrams.
    """
    ia_prompt = ChatPromptTemplate.from_messages([
        ("system", IA_SYSTEM_MSG),
        ("human", IA_TEMPLATE)
    ])
    
    ia_res = await llm.ainvoke(ia_prompt.format_messages(
        hld=hld_content,
        lld=lld_content + "\n\n" + db_schema
    ))
    
    return ia_res.content


# --- Refinement Logic ---

DOC_REFINE_SYSTEM_MSG = (
    "You are a Principal Software Architect specializing in iterative design refinement. "
    "Your goal is to surgically update existing architectural documents (HLD and LLD) based on user feedback.\n\n"
    "## REFINEMENT PRIORITIES:\n"
    "1. FEEDBACK SUPREMACY: If the user requests a change (e.g., 'use XYZ instead of PQR' or 'add a detailed overview'), this is your TOP PRIORITY. You must incorporate these changes precisely while maintaining technical logic.\n"
    "2. CONTEXT PRESERVATION: Only modify sections that are impacted by the feedback. Keep all other professional narrative, diagrams, and technical details intact.\n"
    "3. STRUCTURAL FLEXIBILITY: If the user asks for a new section or a specific type of detail in a section (e.g., 'detailed project overview in LLD'), you must create and populate that section with professional, implementation-ready content.\n"
    "4. TECH STACK SWAPS: When a technology is swapped, update all justifications, component registries, and LLD implementation details (SQL types, API protocols) to reflect the new technology's standards.\n"
    "5. CROSS-DOCUMENT SYNC: Ensure the HLD and LLD stay perfectly synchronized. A change in the architectural overview must be reflected in the database schemas and technical tasks.\n"
)

REFINE_TEMPLATE = """
## CURRENT STATE
### High-Level Design (HLD)
{current_hld}

### Low-Level Design (LLD)
{current_lld}

## USER FEEDBACK / CHANGE REQUEST
{feedback}

## ORIGINAL PROJECT CONTEXT
### Business Workflow
{workflow}

### Approved Requirements
{requirements}

## YOUR TASK
Analyze the feedback and perform a surgical update of the architectural design.
- Update the HLD Markdown to incorporate the feedback.
- Update the LLD Markdown, SQL schemas, and technical tasks to remain consistent with the new HLD.
- Output the result as a complete, updated DesignOutput object.
"""

async def refine_architecture_documents(
    llm: ChatOpenAI,
    current_hld: str,
    current_lld: str,
    feedback: str,
    workflow_mermaid: str,
    requirements: str
) -> DesignOutput:
    """
    Iterative refinement pipeline for architecture docs.
    """
    structured_llm = llm.with_structured_output(DesignOutput)
    
    refine_prompt = ChatPromptTemplate.from_messages([
        ("system", DOC_REFINE_SYSTEM_MSG + LLD_SYSTEM_MSG), # Combine core LLD rigor with refinement rules
        ("human", REFINE_TEMPLATE)
    ])
    
    design_output = await structured_llm.ainvoke(refine_prompt.format_messages(
        current_hld=current_hld,
        current_lld=current_lld,
        feedback=feedback,
        workflow=workflow_mermaid,
        requirements=requirements
    ))
    
    # The structured output should populate hld_content, lld_content, etc.
    return design_output
