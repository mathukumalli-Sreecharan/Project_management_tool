from typing import Optional
import re
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


# We retrieve shared AI components from core.py
from core import get_model


def sanitize_mermaid(code: str) -> str:
    """
    Fix common Mermaid syntax issues that cause rendering failures.
    Applied as a post-processing step after LLM generation.
    Preserves markdown fencing (```mermaid ... ```) if present.
    """
    if not code or not code.strip():
        return code

    # 1. Extract mermaid code from markdown fences if wrapped
    #    Preserve any text before/after the fence (e.g. "### 🚀 TO-BE MAP")
    had_fences = False
    prefix_text = ""
    suffix_text = ""
    md_match = re.search(r'```mermaid\s*\n?(.*?)```', code, re.DOTALL)
    if md_match:
        had_fences = True
        prefix_text = code[:md_match.start()].strip()
        suffix_text = code[md_match.end():].strip()
        inner = md_match.group(1).strip()
    else:
        inner = code.strip()

    lines = inner.split('\n')
    fixed_lines = []

    for line in lines:
        stripped = line.strip()
        
        # 2. Fix subgraph labels with spaces — quote them
        sg_match = re.match(r'^(\s*)subgraph\s+(.+)$', line)
        if sg_match:
            indent = sg_match.group(1)
            label = sg_match.group(2).strip()
            if label.startswith('"') or '[' in label:
                fixed_lines.append(line)
            elif ' ' in label:
                safe_id = re.sub(r'[^a-zA-Z0-9_]', '_', label)
                fixed_lines.append(f'{indent}subgraph {safe_id}["{label}"]')
            else:
                fixed_lines.append(line)
            continue

        # 3. Fix node labels with colons — wrap in quotes if not already
        node_match = re.match(r'^(\s*)(\w+)\[([^"\]]*:[^"\]]*)](.*)$', line)
        if node_match:
            indent = node_match.group(1)
            node_id = node_match.group(2)
            label = node_match.group(3)
            rest = node_match.group(4)
            fixed_lines.append(f'{indent}{node_id}["{label}"]{rest}')
            continue

        # 4. Fix decision nodes with single braces
        dec_match = re.match(r'^(\s*)(\w+)\{([^{}]+)}(.*)$', line)
        if dec_match and not stripped.startswith('subgraph'):
            indent = dec_match.group(1)
            node_id = dec_match.group(2)
            label = dec_match.group(3)
            rest = dec_match.group(4)
            fixed_lines.append(f'{indent}{node_id}{{"{label}"}}{rest}')
            continue

        # 5. Fix edge labels with special chars — ensure quoted
        edge_match = re.match(r'^(.+-->\|)([^"]*:[^"|]*)\|(.+)$', line)
        if edge_match:
            prefix = edge_match.group(1)
            label = edge_match.group(2)
            suffix = edge_match.group(3)
            fixed_lines.append(f'{prefix}"{label}"|{suffix}')
            continue

        fixed_lines.append(line)

    result = '\n'.join(fixed_lines)

    # 6. Ensure it starts with graph TD/LR
    if not re.match(r'^\s*(graph|flowchart)\s+(TD|LR|TB|BT|RL)', result):
        result = 'graph TD\n' + result

    # 7. Re-wrap in markdown fences if the input had them
    if had_fences:
        parts = []
        if prefix_text:
            parts.append(prefix_text)
        parts.append(f'```mermaid\n{result}\n```')
        if suffix_text:
            parts.append(suffix_text)
        return '\n'.join(parts)

    return result


WORKFLOW_AS_IS_PROMPT = ChatPromptTemplate.from_template("""
You are a senior business process analyst. Your only job is to produce a Mermaid AS-IS flowchart that is 100% grounded in the transcript — nothing invented, nothing assumed.

TRANSCRIPT:
{input_text}

═══════════════════════════════════════════
STEP 0 — VALIDITY CHECK + NOISE FILTERING
═══════════════════════════════════════════
Before extraction, strip the following from consideration entirely:
- Greetings, introductions, and small talk ("nice to meet you", company intros, who's on the call)
- Personal background ("I've been in this industry for 20 years")
- Meeting logistics ("can you hear me?", "let me share my screen")
- Pleasantries and closings ("thanks for joining", "let's reconnect next week")

These are NEVER process nodes. If the only content in the transcript is the above, output: INVALID_CONTEXT
Otherwise, proceed to Step 1 using ONLY the business/process/requirements content.

═══════════════════════════════════════════════════════
STEP 1 — TRANSCRIPT EXTRACTION (INTERNAL REASONING ONLY)
═══════════════════════════════════════════════════════
First, perform a STRATEGIC CONTEXT ANALYSIS:
- What is the core business goal discussed?
- What is the main friction or bottleneck preventing this goal today?

Then, extract ONLY what is explicitly stated or clearly implied:

A) ACTORS — Real names, teams, systems mentioned.
B) TRIGGER — What event starts the process?
C) STEPS — Every discrete action, in the order mentioned.
D) DECISIONS — Branch points actually discussed.
E) PAIN POINTS — Exact frustrations, delays, errors mentioned. Quote the transcript where possible.
F) TOOLS/SYSTEMS — Any software, spreadsheet, platform mentioned by name.
G) END STATE — What does the current process produce?

⚠ HALLUCINATION GUARD: If something was NOT mentioned in the transcript, do NOT include it.
If a step is implied but not explicit, mark it with a "?" in your internal extraction and use it only if it is essential to connect the flow.

⚠ INTRODUCTION GUARD: Company introductions and participant names are context only.
They are NOT actors in the process unless they perform a specific business action.
Do NOT create nodes for "X introduces Y" or "X explains their company".

═══════════════════════════════════════════════════
STEP 2 — BUILD THE AS-IS MERMAID FLOWCHART
═══════════════════════════════════════════════════
Rules:
1. TRANSCRIPT-ONLY: Every node must trace to something in Step 1. No invented steps.
2. PAIN POINTS INLINE: Embed pain points as edge labels using ⚠, not as separate nodes.
   Example: M2 -->|"⚠ Manual: no audit trail"| M3
3. REAL NAMES: Use actual names, systems, and timeframes from the transcript.
4. ONE CONTINUOUS PATH: ST → ... → EN. No orphaned nodes. No parallel branches unless the transcript explicitly describes one.
5. SUBGRAPHS: Group by natural phases that emerge from the transcript. Do not force phases that don't exist.
6. SYNTAX:
   - Node IDs: short alphanumeric only (M1, D1, S1). No spaces.
   - Labels: max 40 characters. No <br/> tags.
   - Subgraph titles: quoted strings, closed with `end`.
   - Cross-subgraph edges: written AFTER the last `end`.
   - Every declared node must appear in at least one edge.

NODE SHAPES:
  Manual step:   M1[Action description]
  Decision:      D1{{Condition?}}
  System/Tool:   S1([System Name])
  Actor:         AC1((Person or Team))
  Start/End:     ST([Start]) / EN([End])

═══════════════════════
OUTPUT FORMAT (STRICT)
═══════════════════════
 Do NOT output Step 1 extraction.
 Do NOT output prose, explanation, or headings outside the code block.
 Output ONLY:

###  AS-IS PROCESS MAP
```mermaid
graph TD
[your flowchart]
```
""")

WORKFLOW_TO_BE_PROMPT = ChatPromptTemplate.from_template("""
You are a senior process architect. Your job is to design a TO-BE automated solution that directly optimizes the AS-IS process and solves the specific manual bottlenecks discussed in the transcript. Every automation node must replace a named pain point from the current scenario.

TRANSCRIPT:
{input_text}

AS-IS WORKFLOW (Current State):
{as_is_context}

═══════════════════════════════════════════
STEP 0 — VALIDITY CHECK + NOISE FILTERING
═══════════════════════════════════════════
Before extraction, strip the following from consideration entirely:
- Greetings, introductions, and small talk ("nice to meet you", company intros, who's on the call)
- Personal background ("I've been in this industry for 20 years")
- Meeting logistics ("can you hear me?", "let me share my screen")
- Pleasantries and closings ("thanks for joining", "let's reconnect next week")

These are NEVER process nodes. If the only content in the transcript is the above, output: INVALID_CONTEXT
Otherwise, proceed to Step 1 using ONLY the business/process/requirements content.

═══════════════════════════════════════════════════════
STEP 1 — TRANSCRIPT EXTRACTION (INTERNAL REASONING ONLY)
═══════════════════════════════════════════════════════
First, perform a STRATEGIC CONTEXT ANALYSIS:
- How does the proposed solution transform the current business goal?
- What is the "North Star" or primary objective of this automation?

Then, extract from the transcript:

A) PAIN POINTS → AUTOMATION TARGET mapping:
   For each pain point found, define what replaces it.
   Example: "Maria manually copies invoice data" → AI: OCR + auto-field extraction

B) DESIRED CAPABILITIES — What did the client say they WANT? Quote directly.
C) SYSTEMS TO INTEGRATE — What tools/platforms were mentioned as targets?
D) HUMAN TOUCHPOINTS TO KEEP — Where did the client say humans should stay involved?
E) OUTCOMES DESIRED — What end state did the client describe?

⚠ HALLUCINATION GUARD:
- Do NOT introduce AI capabilities that were not discussed or implied.
- Do NOT add integrations with systems not mentioned.
- If the client did not mention a capability, do not include it.

⚠ INTRODUCTION GUARD: Company introductions and participant names are context only.
They are NOT actors in the process unless they perform a specific business action.
Do NOT create nodes for "X introduces Y" or "X explains their company".

══════════════════════════════════════════════════════════
STEP 2 — BUILD THE TO-BE FLOWCHART (FROM YOUR EXTRACTION)
══════════════════════════════════════════════════════════
- DETAILED: Every automated step = its own node.
- TRACEABILITY: Every AI/Auto node must replace an AS-IS pain point from the provided context.
- HUMAN REVIEW GATES: Include H1(Human: Review) nodes where human oversight is required.

Subgraphs: Group nodes by natural phases (e.g. Ingestion, AI Processing, Integration). The subgraphs must be dynamic and relevant to the specific workflow, not a static list.

NODE SHAPES:
  Automated steps:   A1[Auto: Action]
  AI steps:          AI1[AI: Capability]
  Human touchpoints: H1(Human: Review)
  Decisions:         D1{{Condition?}}
  Systems:           S1([System Name])
  Start/End:         ST([Start]) / EN([End])


SYNTAX RULES:
  - Node IDs: short (A1, AI1, H1). No spaces.
  - Labels: max 35 chars. No <br/> tags.
  - Subgraph titles: Quoted, close with `end`.
  - CONNECTIVITY IS MANDATORY: Every subgraph must have at least one incoming edge FROM another subgraph and one outgoing edge TO the next subgraph. No orphaned nodes.
  - DECLARE NODES SEPARATELY from edges. Define nodes first, then write edges.
  - Cross-subgraph edges must be written OUTSIDE all subgraph blocks, after the last `end`.
  - ANCHOR NODES: ST([Start]) must be inside the first subgraph. EN([End]) must be inside the last subgraph.
  - NO UNUSED NODES: Every declared node MUST appear in at least one edge. If no edge exists, do not declare it.
  - ACTOR LINKAGE: Actor nodes ((Name)) must connect directly to the action they perform.
  - Trace one continuous path from ST to EN to verify every node is reachable.
  - Language: ALWAYS English.

FLOW STRUCTURE (MANDATORY):
The workflow MUST follow a strict linear progression:
ST([Start]) -> Node 1 -> Node 2 -> Node 3 -> ... -> EN([End])
Even when using subgraphs, ensure every node is part of a single continuous path from ST to EN. Avoid parallel branches unless absolutely necessary for a decision.


OUTPUT FORMAT — STRICT (FOLLOW EXACTLY):
⛔ DO NOT output the extraction (Step 1). It is internal reasoning only.
⛔ DO NOT output any explanation, summary, bullet points, or prose before or after the Mermaid block.
⛔ DO NOT output section labels like "Explanation:", "Ingestion:", "AI Processing:", etc.
✅ Output ONLY this exact structure, nothing else:

### 🚀 TO-BE OPTIMIZED MAP
```mermaid
graph TD
[flowchart code]
```
""")

async def run_workflow_agent(input_text: str, get_model_fn, feedback: str = "") -> dict:
    model = get_model_fn()
    augmented_input = (input_text or "").strip()
    feedback_text = (feedback or "").strip()
    if feedback_text:
        augmented_input = (
            f"{augmented_input}\n\n"
            "USER FEEDBACK / CORRECTIONS:\n"
            f"{feedback_text}"
        ).strip()

    # Phase 1: Generate AS-IS Workflow (Sequential Step 1)
    as_is_chain = WORKFLOW_AS_IS_PROMPT | model | StrOutputParser()
    as_is_raw = await as_is_chain.ainvoke({"input_text": augmented_input})
    as_is_final = sanitize_mermaid(as_is_raw)

    # Phase 2: Generate TO-BE Workflow (Sequential Step 2)
    # Uses AS-IS context to ensure optimized flow alignment and traceability
    to_be_chain = WORKFLOW_TO_BE_PROMPT | model | StrOutputParser()
    to_be_raw = await to_be_chain.ainvoke({
        "input_text": augmented_input,
        "as_is_context": as_is_final
    })
    to_be_final = sanitize_mermaid(to_be_raw)

    return {
        "as_is": as_is_final,
        "to_be": to_be_final
    }

async def run_workflow_refine(current_flow: str, feedback: str, get_model_fn) -> str:
    model = get_model_fn()
    refine_prompt = ChatPromptTemplate.from_template("""
You are a senior process analyst refining an existing Mermaid flowchart based on specific feedback.

CURRENT FLOW:
{current_flow}

USER FEEDBACK:
{feedback}

RULES:
1. Only change what the feedback directly asks for.
2. Do not restructure, reformat, or "improve" anything not mentioned in the feedback.
3. Fix any Mermaid syntax errors introduced by your changes.
4. Maintain ST → ... → EN linear progression.
5. Output ONLY the updated Mermaid block. No prose.
""")
    chain = refine_prompt | model | StrOutputParser()
    result = await chain.ainvoke({"current_flow": current_flow, "feedback": feedback})
    return sanitize_mermaid(result)