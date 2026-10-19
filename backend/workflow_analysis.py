import re
from typing import Any, Dict, List


def extract_client_intent_transcript(transcript: str) -> str:
    """
    Keep client-side lines and remove known internal/vendor speaker lines
    so requirement generation stays grounded in client intent.
    """
    text = (transcript or "").strip()
    if not text:
        return ""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    speaker_line_pattern = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]\s*([^:]+):\s*(.*)$")
    internal_speakers = {
        "marcus nordstrom",
        "marcus nordström",
        "bharat",
        "christofer",
        "christofer ohlsson",
        "christopher",
        "christopher ohlsson",
    }

    filtered_lines = []
    for line in lines:
        match = speaker_line_pattern.match(line)
        if not match:
            filtered_lines.append(line)
            continue
        speaker = (match.group(1) or "").strip().lower()
        content = (match.group(2) or "").strip()
        if not content:
            continue
        if speaker in internal_speakers:
            continue
        filtered_lines.append(line)

    # Remove provider capability-demo snippets that often appear in intro chatter
    # and can derail scope extraction.
    capability_demo_terms = [
        "retail",
        "store",
        "butik",
        "camera",
        "kamera",
        "age",
        "gender",
        "ansiktsigenk",
        "facial",
        "body recognition",
        "customer demographic",
    ]
    client_scope_terms = [
        "anbud",
        "offert",
        "ritning",
        "drawing",
        "k-handling",
        "konstrukt",
        "bluebeam",
        "wikels",
        "next",
        "betong",
        "armering",
        "fundament",
        "pdf",
        "förfrågningsunderlag",
        "quantity",
        "pricing",
    ]
    refined_lines = []
    for line in filtered_lines:
        lower = line.lower()
        has_demo_term = any(term in lower for term in capability_demo_terms)
        has_scope_term = any(term in lower for term in client_scope_terms)
        if has_demo_term and not has_scope_term:
            continue
        refined_lines.append(line)

    # If filtering became too aggressive, fall back.
    candidate = "\n".join(refined_lines).strip()
    if not candidate or len(candidate) < max(160, int(len(text) * 0.2)):
        return text
    return candidate


def anchor_transcript_to_client_problem_scope(transcript: str) -> str:
    """
    Trim early intro/capability chatter and anchor the transcript to the first
    concrete client problem/process segment.
    """
    text = (transcript or "").strip()
    if not text:
        return text

    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return text

    scope_markers = [
        "anbudsprocess",
        "anbud",
        "offert",
        "förfrågningsunderlag",
        "foerfragningsunderlag",
        "k-handling",
        "konstruktionsrit",
        "bluebeam",
        "wikels",
        "next",
        "mängd",
        "mangd",
        "betong",
        "armering",
        "fundament",
    ]

    first_scope_idx = None
    for idx, line in enumerate(lines):
        lower = line.lower()
        if any(marker in lower for marker in scope_markers):
            first_scope_idx = idx
            break

    if first_scope_idx is None:
        return text

    # Keep a tiny amount of lead-in context, but remove most pre-scope chatter.
    start = max(0, first_scope_idx - 3)
    anchored = "\n".join(lines[start:]).strip()
    if len(anchored) < max(160, int(len(text) * 0.2)):
        return text
    return anchored


def flatten_workflow_text(workflow: Dict[str, Any]) -> str:
    if not workflow:
        return ""
    parts = [
        workflow.get("workflow_name", ""),
        workflow.get("workflow_summary", ""),
    ]
    for epic in workflow.get("epics", []):
        parts.extend([epic.get("title", ""), epic.get("user_story", "")])
        for req in epic.get("requirements", []):
            parts.extend(
                [
                    req.get("title", ""),
                    req.get("description", ""),
                    req.get("user_story", ""),
                    " ".join(req.get("functional_details", []) or []),
                    " ".join(req.get("acceptance_criteria", []) or []),
                    " ".join(req.get("edge_cases", []) or []),
                    " ".join(req.get("dependencies", []) or []),
                ]
            )
    return " ".join(p for p in parts if p).lower()


def detect_alignment_issues(transcript: str, workflow: Dict[str, Any]) -> List[str]:
    text = (transcript or "").lower()
    text_no_timestamps = re.sub(r"\[\d{2}:\d{2}:\d{2}\]\s*", "", text)
    req_text = flatten_workflow_text(workflow)
    issues = []

    if not workflow or not workflow.get("epics"):
        issues.append("No usable requirements were generated.")
        return issues

    mentions_doc_processing = any(
        phrase in text for phrase in ["document processing", "document classification"]
    )
    generated_forbidden = any(
        phrase in req_text for phrase in ["document processing", "document classification"]
    )
    if generated_forbidden and not mentions_doc_processing:
        issues.append(
            "Forbidden concept found: document processing/classification appears without explicit transcript demand."
        )

    # Input-format enforcement: if multiple formats are present in transcript, require multi-format handling in output.
    format_terms = {
        "pdf": ["pdf"],
        "email": ["email", "mail", "email text"],
        "xml": ["xml"],
        "excel": ["excel", "xlsx", "xls", "spreadsheet"],
    }
    mentioned_formats = [
        fmt
        for fmt, terms in format_terms.items()
        if any(term in text for term in terms)
    ]
    if len(mentioned_formats) >= 2:
        has_multiformat_signal = any(
            token in req_text
            for token in [
                "multi-format",
                "multiple format",
                "multi format",
                "ingestion",
                "intake",
            ]
        )
        if not has_multiformat_signal:
            issues.append(
                "Transcript contains multiple input formats but requirements do not clearly include multi-format ingestion."
            )

    # Terminology mapping enforcement.
    mapping_triggers = [
        "same product different names",
        "different names",
        "terminology mismatch",
        "same item different name",
        "same product with different name",
    ]
    if any(trigger in text for trigger in mapping_triggers):
        has_mapping_signal = any(
            token in req_text
            for token in ["normalization", "mapping", "canonical", "standardize", "taxonomy"]
        )
        if not has_mapping_signal:
            issues.append(
                "Transcript indicates terminology mismatch but requirements are missing a normalization/mapping capability."
            )

    # Core constraints checks for self-correction loop.
    constraint_checks = [
        (["missing data", "incomplete data"], ["missing", "incomplete", "fallback"]),
        (["validation", "validate"], ["validation", "validate"]),
        (["approval", "approve"], ["approval", "approve"]),
        (["erp"], ["erp", "integration"]),
    ]
    for triggers, required_tokens in constraint_checks:
        if any(t in text for t in triggers) and not any(token in req_text for token in required_tokens):
            issues.append(
                f"Constraint missing from requirements for transcript signal: {', '.join(triggers)}."
            )

    # Off-domain drift checks: reject requirement content that appears only as side examples, not client scope.
    drift_terms = [
        "retail",
        "camera",
        "customer demographics",
        "age detection",
        "gender detection",
        "facial recognition",
        "body recognition",
        "marketing strategy",
    ]
    drift_hits = [term for term in drift_terms if term in req_text and term not in text]
    if drift_hits:
        issues.append(
            "Requirements include off-scope domain terms not supported by transcript intent: "
            + ", ".join(sorted(set(drift_hits)))
            + "."
        )

    # Metric hallucination check: avoid invented SLA/accuracy percentages unless grounded in transcript.
    req_metric_hits = re.findall(
        r"\b\d{1,3}\s*%|\b\d+(?:\.\d+)?\s*(?:second|seconds|sec|s)\b",
        req_text,
    )
    transcript_has_metrics = bool(
        re.search(
            r"\b\d{1,3}\s*%|\b\d+(?:\.\d+)?\s*(?:second|seconds|sec|s|sekund|sekunder)\b",
            text_no_timestamps,
        )
    )
    if req_metric_hits and not transcript_has_metrics:
        issues.append(
            "Requirements contain invented accuracy/SLA metrics not grounded in transcript evidence."
        )
    return issues
