import re
from typing import Any, Dict, List


STRICT_CAPABILITIES = [
    {
        "capability_id": "CAP-1",
        "name": "Input Normalization",
        "description": "Ability to accept, classify, clean, and normalize incoming inputs into a consistent machine-usable structure.",
    },
    {
        "capability_id": "CAP-2",
        "name": "Context Interpretation",
        "description": "Ability to infer business intent, disambiguate meaning, and apply context-aware interpretation of normalized inputs.",
    },
    {
        "capability_id": "CAP-3",
        "name": "Structured Data Extraction",
        "description": "Ability to extract relevant business data from unstructured and semi-structured inputs into a structured representation.",
    },
    {
        "capability_id": "CAP-4",
        "name": "Computation and Validation",
        "description": "Ability to compute derived values and validate completeness, consistency, and business-rule compliance.",
    },
    {
        "capability_id": "CAP-5",
        "name": "Structured Output Generation",
        "description": "Ability to generate structured outputs for downstream consumption.",
    },
]


REQUIRED_EPIC_BLUEPRINTS = [
    ("EPIC-1", "Input Processing", ["Input Normalization", "Context Interpretation"]),
    ("EPIC-2", "Data Extraction & Validation", ["Structured Data Extraction", "Computation and Validation"]),
    ("EPIC-3", "Output Generation", ["Structured Output Generation", "Computation and Validation"]),
]


EPIC_CLASSIFICATION_RULES = {
    "Input Processing": [
        "input", "ingest", "intake", "capture", "receive", "collect", "upload",
        "submission", "parse", "classify", "normalize", "pre-process",
    ],
    "Data Extraction & Validation": [
        "extract", "extraction", "map", "mapping", "transform", "interpret",
        "validate", "validation", "reconcile", "check", "calculation",
        "document", "entity", "attribute",
        "compute", "derive", "matching",
    ],
    "Output Generation": [
        "output", "report", "proposal", "export", "publish", "deliver", "generate",
        "downstream", "api", "erp", "sync", "handoff", "send", "post", "update",
    ],
}


def _standardize_text_terms(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return text
    replacements = [
        (r"\bclients\b", "external systems"),
        (r"\bclient\b", "external system"),
        (r"\bdrawings\b", "visual input"),
        (r"\bdrawing\b", "visual input"),
        (r"\bproposals\b", "structured output"),
        (r"\bproposal\b", "structured output"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _normalize_text_list(value) -> List[str]:
    if isinstance(value, list):
        return [
            _standardize_text_terms(str(item)).strip()
            for item in value
            if str(item).strip()
        ]
    if isinstance(value, str) and value.strip():
        return [_standardize_text_terms(value).strip()]
    return []


def _capability_reference(capability: Dict[str, Any]) -> str:
    capability_id = (capability.get("capability_id") or "").strip()
    capability_name = _standardize_text_terms(capability.get("name") or "").strip()
    return f"{capability_id}: {capability_name}".strip(": ")


def _capability_reference_lookup(capabilities: List[Dict[str, Any]]) -> Dict[str, str]:
    lookup = {}
    for capability in capabilities:
        reference = _capability_reference(capability)
        capability_id = (capability.get("capability_id") or "").strip()
        capability_name = _standardize_text_terms(capability.get("name") or "").strip()
        if reference:
            lookup[reference.lower()] = reference
        if capability_id:
            lookup[capability_id.lower()] = reference
        if capability_name:
            lookup[capability_name.lower()] = reference
    return lookup


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").strip().lower()).strip()


def _find_capability_id_by_name(capabilities: List[Dict[str, Any]], capability_name: str) -> str:
    target = _slugify(capability_name)
    for capability in capabilities:
        if _slugify(capability.get("name") or "") == target:
            return (capability.get("capability_id") or "").strip()
    return ""


def _ensure_capabilities(capabilities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Strict capability lock: output must always use exactly these five capabilities.
    return [dict(capability) for capability in STRICT_CAPABILITIES]


def _canonical_dependency_references(
    dependencies: List[str],
    allowed_capability_ids: List[str],
    capabilities: List[Dict[str, Any]],
) -> List[str]:
    capability_by_id = {
        (cap.get("capability_id") or "").strip(): cap
        for cap in capabilities
        if (cap.get("capability_id") or "").strip()
    }
    scoped_references = [
        _capability_reference(capability_by_id[capability_id])
        for capability_id in allowed_capability_ids
        if capability_id in capability_by_id
    ]
    scoped_lookup = {item.lower(): item for item in scoped_references}

    normalized = []
    seen = set()
    for dependency in dependencies or []:
        raw_dependency = _standardize_text_terms(dependency).strip()
        if not raw_dependency:
            continue
        reference = scoped_lookup.get(raw_dependency.lower())
        if not reference:
            for key, value in scoped_lookup.items():
                if raw_dependency.lower() in key or key in raw_dependency.lower():
                    reference = value
                    break
        if not reference and scoped_references:
            reference = scoped_references[min(len(normalized), len(scoped_references) - 1)]
        if reference and reference not in seen:
            seen.add(reference)
            normalized.append(reference)

    if not normalized:
        normalized = scoped_references[:2] or [
            _capability_reference(capability)
            for capability in capabilities[:2]
        ]
    return normalized


def _requirement_signature(requirement: Dict[str, Any]) -> str:
    seed = " ".join(
        [
            _standardize_text_terms(requirement.get("title") or "").lower(),
            _standardize_text_terms(requirement.get("description") or "").lower(),
            " ".join(_normalize_text_list(requirement.get("inputs"))).lower(),
            " ".join(_normalize_text_list(requirement.get("outputs"))).lower(),
        ]
    )
    tokens = re.findall(r"[a-z0-9]+", seed)
    stopwords = {
        "the", "system", "shall", "for", "with", "and", "from", "into", "that",
        "workflow", "process", "stage", "data", "user",
    }
    return " ".join(token for token in tokens if token not in stopwords)


def _epic_text(epic: Dict[str, Any]) -> str:
    requirement_text = " ".join(
        f"{requirement.get('title', '')} {requirement.get('description', '')}"
        for requirement in (epic.get("requirements") or [])
    )
    return " ".join(
        [
            epic.get("title", ""),
            epic.get("user_story", ""),
            requirement_text,
        ]
    ).strip()


def _canonical_epic_title(title: str) -> str:
    normalized_title = _standardize_text_terms(title or "").strip()
    title_key = _slugify(normalized_title)
    if not title_key:
        return ""
    for canonical_title, keywords in EPIC_CLASSIFICATION_RULES.items():
        if title_key == _slugify(canonical_title):
            return canonical_title
        if any(keyword in title_key for keyword in keywords):
            return canonical_title
    return normalized_title


def _classify_requirement_epic(requirement: Dict[str, Any]) -> str:
    requirement_text = _slugify(
        f"{requirement.get('title', '')} {requirement.get('description', '')} "
        f"{' '.join(requirement.get('acceptance_criteria', []) or [])}"
    )
    for canonical_title, keywords in EPIC_CLASSIFICATION_RULES.items():
        if any(keyword in requirement_text for keyword in keywords):
            return canonical_title
    return ""


def _default_capability_ids_for_epic(epic_title: str, capabilities: List[Dict[str, Any]]) -> List[str]:
    for _epic_id, canonical_title, capability_names in REQUIRED_EPIC_BLUEPRINTS:
        if epic_title == canonical_title:
            capability_ids = [
                _find_capability_id_by_name(capabilities, capability_name)
                for capability_name in capability_names
            ]
            return [capability_id for capability_id in capability_ids if capability_id]

    fallback_names = ["Computation and Validation", "Structured Output Generation"]
    capability_ids = [
        _find_capability_id_by_name(capabilities, capability_name)
        for capability_name in fallback_names
    ]
    return [capability_id for capability_id in capability_ids if capability_id]


def _detected_business_signals(transcript: str, workflow: Dict[str, Any]) -> Dict[str, bool]:
    text = " ".join(
        [
            transcript or "",
            workflow.get("workflow_name", ""),
            workflow.get("workflow_summary", ""),
            " ".join(epic.get("title", "") for epic in workflow.get("epics", []) or []),
            " ".join(
                req.get("title", "")
                for epic in (workflow.get("epics", []) or [])
                for req in (epic.get("requirements", []) or [])
            ),
        ]
    ).lower()
    return {
        "product_name_normalization": bool(
            re.search(r"\b(product|sku|item).*(name|naming|alias|mapping|normalize)\b", text)
            or re.search(r"\bsame product\b.*\bdifferent\b.*\bname", text)
            or re.search(r"\bproduct\b.*\balias", text)
        ),
        "customer_identification": bool(
            re.search(r"\bcustomer\b.*\b(identify|identification|mapping)\b", text)
            or re.search(r"\bemail domain\b|\bsender\b", text)
        ),
        "missing_data_auto_response": bool(
            re.search(r"\bmissing\b.*\b(data|field|value)\b", text)
            or re.search(r"\b(auto|automated)\b.*\b(response|reply|follow[- ]?up)\b", text)
        ),
        "approval_before_erp": bool(
            re.search(r"\b(approval|approve|approved|review)\b", text) and re.search(r"\berp\b", text)
        ),
        "format_conversion": bool(
            re.search(r"\b(pdf|email|xml|csv|text)\b", text)
            and re.search(r"\b(convert|transform|mapping|structured|normalize)\b", text)
        ),
        "quotation_management": bool(
            re.search(r"\bquote|quotation|pricing\b", text)
        ),
        "high_volume_quotes": bool(
            re.search(r"\b\d{3,}\b.*\b(quote|quotation|day)\b", text)
            or re.search(r"\bhigh volume\b", text)
        ),
    }


def _inject_signal_driven_requirements(workflow: Dict[str, Any], transcript: str) -> Dict[str, Any]:
    signals = _detected_business_signals(transcript, workflow)
    if not any(signals.values()):
        return workflow

    cleaned = {**workflow}
    epics = list(cleaned.get("epics", []) or [])
    capabilities = cleaned.get("capabilities", []) or []

    epic_by_title = {_canonical_epic_title(epic.get("title") or ""): epic for epic in epics}
    for epic in epics:
        epic.setdefault("requirements", [])

    def _get_or_create_epic(title: str) -> Dict[str, Any]:
        canonical = _canonical_epic_title(title) or title
        if canonical in epic_by_title:
            return epic_by_title[canonical]
        new_epic = {
            "epic_id": "",
            "title": title,
            "user_story": _epic_user_story(title),
            "mapped_capabilities": _default_capability_ids_for_epic(title, capabilities),
            "requirements": [],
        }
        epics.append(new_epic)
        epic_by_title[canonical] = new_epic
        return new_epic

    def _append_requirement(epic_title: str, title: str, description: str):
        epic = _get_or_create_epic(epic_title)
        candidate = _normalize_requirement(
            {
                "req_id": "",
                "title": title,
                "description": description,
                "user_story": _requirement_user_story(title, epic.get("title") or epic_title),
                "acceptance_criteria": [],
                "edge_cases": [],
                "dependencies": [],
                "priority": "high",
            },
            epic.get("title") or epic_title,
            epic.get("mapped_capabilities") or _default_capability_ids_for_epic(epic_title, capabilities),
            capabilities,
        )
        signature = _requirement_signature(candidate)
        existing = {_requirement_signature(req) for req in (epic.get("requirements") or [])}
        if signature not in existing:
            epic["requirements"].append(candidate)

    if signals["product_name_normalization"]:
        _append_requirement(
            "Data Extraction & Validation",
            "Product Name Normalization",
            "The system shall map customer-specific product names to the internal product catalog using deterministic matching and fallback resolution rules.",
        )
    if signals["customer_identification"]:
        _append_requirement(
            "Input Processing",
            "Customer Identification",
            "The system shall identify customers from email domain, sender metadata, and contextual attributes before downstream processing.",
        )
    if signals["missing_data_auto_response"]:
        _append_requirement(
            "Data Extraction & Validation",
            "Missing Data Handling",
            "The system shall detect missing required fields and trigger an automated response requesting exact missing data elements.",
        )
    if signals["approval_before_erp"]:
        _append_requirement(
            "Output Generation",
            "Approval Interface Before ERP Submission",
            "The system shall provide a review-and-approval step before publishing any transaction payload to ERP.",
        )
    if signals["format_conversion"]:
        _append_requirement(
            "Data Extraction & Validation",
            "Multi Format Data Transformation",
            "The system shall transform PDF, email, XML, and text inputs into a structured canonical format for validation and output generation.",
        )
    if signals["quotation_management"]:
        _append_requirement(
            "Quotation Management",
            "Quote Capture Across Channels",
            "The system shall capture and structure quotation requests received via email, phone notes, and other unstructured channels.",
        )
        _append_requirement(
            "Quotation Management",
            "Quote To Order Conversion",
            "The system shall convert approved quotations into structured orders while preserving price context and traceability.",
        )
        if signals["high_volume_quotes"]:
            _append_requirement(
                "Quotation Management",
                "High Volume Quote Processing",
                "The system shall support high-volume quote intake with prioritization, deduplication, and queue-based processing.",
            )

    cleaned["epics"] = epics
    return cleaned


def _fallback_requirements_for_epic(epic_title: str, workflow_name: str) -> List[Dict[str, Any]]:
    workflow_label = _standardize_text_terms(workflow_name or "the workflow").strip().lower()
    templates = {
        "Input Processing": [
            {
                "title": "Capture Incoming Inputs",
                "description": f"The system shall capture all required source inputs needed to start {workflow_label}.",
                "user_story": _strict_user_story("capture incoming workflow inputs", "the process starts with complete source information"),
                "inputs": ["Client inputs, source records, and supporting attachments."],
                "outputs": ["Captured source data ready for normalization."],
            },
            {
                "title": "Normalize And Validate Intake Data",
                "description": f"The system shall normalize incoming data and validate required fields before {workflow_label} continues.",
                "user_story": _strict_user_story("normalize and validate intake data", "downstream processing starts from trusted inputs"),
                "inputs": ["Captured source data and validation rules."],
                "outputs": ["Normalized and validated intake payload."],
            },
            {
                "title": "Route Inputs By Business Context",
                "description": "The system shall route normalized inputs to the correct business path based on interpreted customer and product context.",
                "user_story": _strict_user_story("route inputs by business context", "the workflow follows the correct processing path"),
                "inputs": ["Normalized intake data and business context signals."],
                "outputs": ["Routed workflow path or target processing lane."],
            },
        ],
        "Data Extraction & Validation": [
            {
                "title": "Extract Structured Business Data",
                "description": f"The system shall extract business entities and attributes from incoming inputs required by {workflow_label}.",
                "user_story": _strict_user_story("extract structured business data", "the workflow can operate on trusted fields instead of raw input"),
                "inputs": ["Normalized input data and extraction rules."],
                "outputs": ["Structured business fields and extracted entities."],
            },
            {
                "title": "Compute Derived Business Values",
                "description": "The system shall compute required derived values and consistency checks from extracted structured data.",
                "user_story": _strict_user_story("compute derived business values", "downstream processing uses validated and complete metrics"),
                "inputs": ["Structured business data and validation inputs."],
                "outputs": ["Computed values and consistency checks."],
            },
            {
                "title": "Validate Computation Results",
                "description": "The system shall validate computed outputs against business rules and data completeness constraints before final output generation.",
                "user_story": _strict_user_story("validate computed results", "invalid or conflicting values are corrected before output generation"),
                "inputs": ["Computed results and business rules."],
                "outputs": ["Validation status and corrected results."],
            },
        ],
        "Output Generation": [
            {
                "title": "Generate Structured Output",
                "description": f"The system shall generate structured output artifacts required by {workflow_label} for downstream consumption.",
                "user_story": _strict_user_story("generate structured output", "downstream systems and users receive consistent outputs"),
                "inputs": ["Validated structured data and output schema."],
                "outputs": ["Structured output artifact ready for handoff."],
            },
            {
                "title": "Prepare Output For Handoff",
                "description": "The system shall format generated output to the target schema required by downstream systems or APIs.",
                "user_story": _strict_user_story("prepare output for handoff", "downstream systems can consume output without manual rework"),
                "inputs": ["Structured output artifact and destination schema."],
                "outputs": ["Handoff-ready payload or integration package."],
            },
            {
                "title": "Track Output Delivery",
                "description": "The system shall track output delivery status and surface failures for remediation.",
                "user_story": _strict_user_story("track output delivery", "delivery failures are visible and recoverable"),
                "inputs": ["Output delivery events and transfer status."],
                "outputs": ["Delivery status, confirmations, or remediation signals."],
            },
        ],
    }
    if epic_title not in templates:
        business_label = _standardize_text_terms(epic_title or "business function").strip().lower()
        templates[epic_title] = [
            {
                "title": f"{epic_title} Intake Control",
                "description": f"The system shall capture and validate inputs required for {business_label} within {workflow_label}.",
                "user_story": _strict_user_story(f"capture {business_label} inputs", f"{business_label} starts with complete and valid data"),
                "inputs": ["Upstream source data and triggering business context."],
                "outputs": ["Validated intake payload for the business function."],
            },
            {
                "title": f"{epic_title} Decision Automation",
                "description": f"The system shall apply business rules and decision logic required to execute {business_label} accurately.",
                "user_story": _strict_user_story(f"automate {business_label} decisions", f"{business_label} is executed consistently"),
                "inputs": ["Validated business inputs and decision rules."],
                "outputs": ["Decision outcome or processed business result."],
            },
            {
                "title": f"{epic_title} Output And Handoff",
                "description": f"The system shall generate structured outputs for {business_label} and route them to the correct downstream destination.",
                "user_story": _strict_user_story(f"generate and hand off {business_label} outputs", f"downstream teams receive complete and actionable outcomes"),
                "inputs": ["Processed business data and destination requirements."],
                "outputs": ["Structured output and downstream handoff package."],
            },
        ]
    seeded = []
    for index, template in enumerate(templates.get(epic_title, []), start=1):
        seeded.append(
            {
                "req_id": f"TEMP-{index}",
                "title": template["title"],
                "description": template["description"],
                "user_story": template["user_story"],
                "acceptance_criteria": [
                    f"Given valid source data, when {template['title'].lower()} runs, then the system produces a traceable result for the next workflow stage.",
                    "Given missing or invalid input, when processing runs, then the system blocks continuation and returns a clear remediation message.",
                ],
                "edge_cases": [
                    f"The system shall detect incomplete information required for {template['title'].lower()}.",
                    f"The system shall prevent silent failure if {template['title'].lower()} cannot complete successfully.",
                ],
                "dependencies": [],
                "priority": "high",
            }
        )
    return seeded


def _normalize_requirement(
    requirement: Dict[str, Any],
    epic_title: str,
    mapped_capabilities: List[str],
    capabilities: List[Dict[str, Any]],
) -> Dict[str, Any]:
    title = _standardize_text_terms(requirement.get("title") or "").strip() or f"{epic_title} Requirement"
    description = _standardize_text_terms(requirement.get("description") or "").strip()
    description = re.sub(
        r"\bexecute\b.+?\bworkflow-specific rules\b\.?",
        "",
        description,
        flags=re.IGNORECASE,
    ).strip()
    if description.lower() in {"the system shall", "the system shall."}:
        description = ""
    if description and not description.lower().startswith("the system shall"):
        description = f"The system shall {description[0].lower()}{description[1:]}" if len(description) > 1 else "The system shall support the workflow."
    if not description:
        description = f"The system shall perform {title.lower()} with clear, testable business behavior."

    user_story = _standardize_text_terms(requirement.get("user_story") or "").strip()
    if not re.match(r"^As a [^,]+, I want .+ so that .+$", user_story):
        user_story = _requirement_user_story(title, epic_title)

    acceptance_criteria = [
        _standardize_text_terms(item)
        for item in (requirement.get("acceptance_criteria") or [])
        if (item or "").strip()
    ] or _default_acceptance_criteria(title, epic_title)
    inputs = _normalize_text_list(requirement.get("inputs")) or [
        f"Upstream workflow data needed for {title.lower()}."
    ]
    outputs = _normalize_text_list(requirement.get("outputs")) or [
        f"Downstream artifact or status produced by {title.lower()}."
    ]
    edge_cases = [
        _standardize_text_terms(item)
        for item in (requirement.get("edge_cases") or [])
        if (item or "").strip()
    ] or _default_edge_cases(title, epic_title)
    dependencies = _canonical_dependency_references(
        requirement.get("dependencies") or [],
        mapped_capabilities,
        capabilities,
    )
    if len(dependencies) > 2:
        dependencies = dependencies[:2]

    return {
        "req_id": requirement.get("req_id", ""),
        "title": title,
        "description": description,
        "user_story": user_story,
        "inputs": inputs,
        "outputs": outputs,
        "acceptance_criteria": acceptance_criteria,
        "edge_cases": edge_cases,
        "dependencies": dependencies,
        "priority": (requirement.get("priority") or "high").strip().lower(),
    }


def _normalize_epic(
    epic: Dict[str, Any],
    capabilities: List[Dict[str, Any]],
    workflow_name: str,
    epic_id: str,
) -> Dict[str, Any]:
    title = _canonical_epic_title(epic.get("title") or "") or f"Business Function {epic_id.split('-')[-1]}"
    mapped_capabilities = [
        capability_id
        for capability_id in (epic.get("mapped_capabilities") or [])
        if capability_id and any(capability.get("capability_id") == capability_id for capability in capabilities)
    ]
    if not mapped_capabilities:
        mapped_capabilities = _default_capability_ids_for_epic(title, capabilities)

    normalized_requirements = []
    seen_signatures = set()
    for requirement in epic.get("requirements", []) or []:
        normalized_requirement = _normalize_requirement(requirement, title, mapped_capabilities, capabilities)
        signature = _requirement_signature(normalized_requirement)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        normalized_requirements.append(normalized_requirement)

    fallback_candidates = _fallback_requirements_for_epic(title, workflow_name)
    while len(normalized_requirements) < 1:
        added = False
        for candidate in fallback_candidates:
            normalized_candidate = _normalize_requirement(candidate, title, mapped_capabilities, capabilities)
            signature = _requirement_signature(normalized_candidate)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            normalized_requirements.append(normalized_candidate)
            added = True
            if len(normalized_requirements) >= 1:
                break
        if not added:
            break

    user_story = _standardize_text_terms(epic.get("user_story") or "").strip()
    if not re.match(r"^As a [^,]+, I want .+ so that .+$", user_story):
        user_story = _epic_user_story(title)

    return {
        "epic_id": epic_id,
        "title": title,
        "user_story": user_story,
        "mapped_capabilities": mapped_capabilities,
        "requirements": normalized_requirements,
    }


def _merge_epics_by_title(epics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged = {}
    order = []
    for epic in epics:
        title = _canonical_epic_title(epic.get("title") or "")
        if not title:
            title = epic.get("title") or "Business Function"
        if title not in merged:
            merged[title] = {**epic, "title": title, "requirements": list(epic.get("requirements") or [])}
            order.append(title)
            continue
        existing = merged[title]
        existing["requirements"] = list(existing.get("requirements") or []) + list(epic.get("requirements") or [])
        existing_caps = list(existing.get("mapped_capabilities") or [])
        for capability_id in epic.get("mapped_capabilities") or []:
            if capability_id not in existing_caps:
                existing_caps.append(capability_id)
        existing["mapped_capabilities"] = existing_caps
        if not existing.get("user_story") and epic.get("user_story"):
            existing["user_story"] = epic.get("user_story")
    return [merged[title] for title in order]


def _required_epic_stub(title: str) -> Dict[str, Any]:
    return {
        "title": title,
        "user_story": "",
        "mapped_capabilities": [],
        "requirements": [],
    }


def _ensure_epic_structure(workflow: Dict[str, Any], capabilities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    source_epics = _merge_epics_by_title(workflow.get("epics", []) or [])
    indexed_epics = []

    required_titles = [title for _epic_id, title, _capability_names in REQUIRED_EPIC_BLUEPRINTS]
    seen_required_titles = {title: False for title in required_titles}

    for epic in source_epics:
        canonical_title = _canonical_epic_title(epic.get("title") or "")
        if canonical_title in seen_required_titles:
            seen_required_titles[canonical_title] = True
        indexed_epics.append(epic)

    for title, present in seen_required_titles.items():
        if not present:
            seeded_requirements = []
            for epic in source_epics:
                for requirement in epic.get("requirements", []) or []:
                    if _classify_requirement_epic(requirement) == title:
                        seeded_requirements.append(requirement)
            indexed_epics.append(
                {
                    **_required_epic_stub(title),
                    "requirements": seeded_requirements,
                }
            )

    required_epics = []
    additional_epics = []
    for epic in indexed_epics:
        title = _canonical_epic_title(epic.get("title") or "")
        if title in required_titles:
            required_epics.append(epic)
        else:
            additional_epics.append(epic)

    normalized_epics = []
    epic_counter = 1
    for title in required_titles:
        matching_epics = [epic for epic in required_epics if _canonical_epic_title(epic.get("title") or "") == title]
        merged_epic = _merge_epics_by_title(matching_epics or [_required_epic_stub(title)])[0]
        normalized_epics.append(
            _normalize_epic(
                merged_epic,
                capabilities=capabilities,
                workflow_name=workflow.get("workflow_name") or "",
                epic_id=f"EPIC-{epic_counter}",
            )
        )
        epic_counter += 1

    for epic in additional_epics:
        normalized_epics.append(
            _normalize_epic(
                epic,
                capabilities=capabilities,
                workflow_name=workflow.get("workflow_name") or "",
                epic_id=f"EPIC-{epic_counter}",
            )
        )
        epic_counter += 1

    return normalized_epics


def _merge_requirement_group(requirements: List[Dict[str, Any]]) -> Dict[str, Any]:
    primary = {**requirements[0]}
    merged_acceptance = []
    merged_edge_cases = []
    merged_dependencies = []
    merged_inputs = []
    merged_outputs = []
    seen_acceptance = set()
    seen_edge_cases = set()
    seen_dependencies = set()
    seen_inputs = set()
    seen_outputs = set()

    for requirement in requirements:
        for input_item in requirement.get("inputs", []) or []:
            key = input_item.strip().lower()
            if key and key not in seen_inputs:
                seen_inputs.add(key)
                merged_inputs.append(input_item)
        for output_item in requirement.get("outputs", []) or []:
            key = output_item.strip().lower()
            if key and key not in seen_outputs:
                seen_outputs.add(key)
                merged_outputs.append(output_item)
        for criterion in requirement.get("acceptance_criteria", []) or []:
            key = criterion.strip().lower()
            if key and key not in seen_acceptance:
                seen_acceptance.add(key)
                merged_acceptance.append(criterion)
        for edge_case in requirement.get("edge_cases", []) or []:
            key = edge_case.strip().lower()
            if key and key not in seen_edge_cases:
                seen_edge_cases.add(key)
                merged_edge_cases.append(edge_case)
        for dependency in requirement.get("dependencies", []) or []:
            key = dependency.strip().lower()
            if key and key not in seen_dependencies:
                seen_dependencies.add(key)
                merged_dependencies.append(dependency)

    primary["inputs"] = merged_inputs
    primary["outputs"] = merged_outputs
    primary["acceptance_criteria"] = merged_acceptance
    primary["edge_cases"] = merged_edge_cases
    primary["dependencies"] = merged_dependencies
    return primary


def workflow_signature_tokens(workflow: Dict[str, Any]) -> set:
    stopwords = {
        "the", "and", "for", "with", "from", "into", "to", "of", "in", "on", "a", "an",
        "system", "workflow", "management", "automation", "automated", "process",
        "document", "documents", "construction",
    }
    seed = " ".join(
        [
            workflow.get("workflow_name", ""),
            workflow.get("workflow_summary", ""),
            " ".join(epic.get("title", "") for epic in workflow.get("epics", [])),
            " ".join(
                req.get("title", "")
                for epic in workflow.get("epics", [])
                for req in epic.get("requirements", [])
            ),
        ]
    ).lower()
    words = re.findall(r"[a-zA-Z0-9\-]+", seed)
    return {w for w in words if len(w) > 2 and w not in stopwords}


def merge_workflow_pair(primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, Any]:
    merged = {**primary}
    existing_epic_titles = {(epic.get("title") or "").strip().lower() for epic in merged.get("epics", [])}
    merged_epics = list(merged.get("epics", []))

    for epic in secondary.get("epics", []):
        title_key = (epic.get("title") or "").strip().lower()
        if title_key and title_key in existing_epic_titles:
            continue
        merged_epics.append(epic)
        if title_key:
            existing_epic_titles.add(title_key)

    merged["epics"] = merged_epics

    merged["intent"] = {
        "goals": list(
            dict.fromkeys(
                (primary.get("intent", {}) or {}).get("goals", [])
                + (secondary.get("intent", {}) or {}).get("goals", [])
            )
        )
    }

    capability_lookup = {}
    for capability in (primary.get("capabilities", []) + secondary.get("capabilities", [])):
        capability_id = (capability.get("capability_id") or "").strip()
        if not capability_id or capability_id in capability_lookup:
            continue
        capability_lookup[capability_id] = capability
    merged["capabilities"] = list(capability_lookup.values())

    actor_lookup = {}
    for actor in (primary.get("actors", []) + secondary.get("actors", [])):
        key = ((actor.get("name") or "").strip().lower(), (actor.get("type") or "").strip().lower())
        if not key[0]:
            continue
        actor_lookup[key] = actor
    merged["actors"] = list(actor_lookup.values())

    validation_lookup = {}
    for item in (primary.get("validation_summary", []) + secondary.get("validation_summary", [])):
        key = (item.get("check") or "").strip().lower()
        if not key or key in validation_lookup:
            continue
        validation_lookup[key] = item
    merged["validation_summary"] = list(validation_lookup.values())

    constraints = []
    seen_constraints = set()
    for item in (primary.get("system_constraints", []) + secondary.get("system_constraints", [])):
        key = (item or "").strip().lower()
        if not key or key in seen_constraints:
            continue
        seen_constraints.add(key)
        constraints.append(item)
    merged["system_constraints"] = constraints

    return merged


def dedupe_and_merge_similar_workflows(workflows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(workflows) <= 1:
        return workflows

    merged = []
    consumed = set()

    for i, workflow in enumerate(workflows):
        if i in consumed:
            continue
        base = workflow
        base_tokens = workflow_signature_tokens(base)
        for j in range(i + 1, len(workflows)):
            if j in consumed:
                continue
            other = workflows[j]
            other_tokens = workflow_signature_tokens(other)
            if not base_tokens or not other_tokens:
                continue
            overlap = len(base_tokens & other_tokens)
            union = len(base_tokens | other_tokens)
            similarity = (overlap / union) if union else 0
            if similarity >= 0.45:
                base = merge_workflow_pair(base, other)
                consumed.add(j)
                base_tokens = workflow_signature_tokens(base)
        merged.append(base)

    return merged


def transcript_indicates_multiple_initiatives(transcript: str) -> bool:
    text = (transcript or "").lower()
    markers = [
        "separate initiative",
        "another initiative",
        "another track",
        "parallel track",
        "parallel initiative",
        "independent workflow",
        "workflow 1",
        "workflow 2",
        "track 1",
        "track 2",
    ]
    return any(marker in text for marker in markers)


def _workflow_priority_score(workflow: Dict[str, Any]) -> tuple:
    epics = workflow.get("epics", []) or []
    requirements = sum(len(epic.get("requirements", []) or []) for epic in epics)
    return (requirements, len(epics))


def _consolidated_workflow_name(primary: Dict[str, Any], all_workflows: List[Dict[str, Any]]) -> str:
    names = [
        _standardize_text_terms(workflow.get("workflow_name") or "").strip()
        for workflow in all_workflows
        if (workflow.get("workflow_name") or "").strip()
    ]
    unique_names = list(dict.fromkeys(name for name in names if name))
    if len(unique_names) <= 1:
        return unique_names[0] if unique_names else _standardize_text_terms(primary.get("workflow_name") or "Unified Workflow")

    primary_name = _standardize_text_terms(primary.get("workflow_name") or "").strip()
    if primary_name:
        if primary_name.lower().startswith("end-to-end "):
            return primary_name
        return f"End-to-End {primary_name}"
    return f"End-to-End {unique_names[0]}"


def _consolidated_workflow_summary(primary: Dict[str, Any], all_workflows: List[Dict[str, Any]]) -> str:
    summaries = [
        _standardize_text_terms(workflow.get("workflow_summary") or "").strip()
        for workflow in all_workflows
        if (workflow.get("workflow_summary") or "").strip()
    ]
    unique_summaries = list(dict.fromkeys(summary for summary in summaries if summary))
    if len(unique_summaries) <= 1:
        return unique_summaries[0] if unique_summaries else _standardize_text_terms(primary.get("workflow_summary") or "")
    return "Unifies all detected business problems into one end-to-end workflow so that input handling, data validation, integrations, and business functions stay covered in a single structured architecture."


def collapse_to_single_workflow_if_needed(workflows: List[Dict[str, Any]], transcript: str) -> List[Dict[str, Any]]:
    if len(workflows) <= 1:
        return workflows

    ordered = sorted(workflows, key=_workflow_priority_score, reverse=True)
    primary = ordered[0]
    for other in ordered[1:]:
        primary = merge_workflow_pair(primary, other)
    primary["workflow_name"] = _consolidated_workflow_name(primary, ordered)
    primary["workflow_summary"] = _consolidated_workflow_summary(primary, ordered)
    return [primary]


def transcript_has_explicit_sla_or_accuracy_targets(transcript: str) -> bool:
    text = re.sub(r"\[\d{2}:\d{2}:\d{2}\]\s*", "", (transcript or "").lower())
    # Require explicit quality/SLA intent, not just dimensions/quantities.
    patterns = [
        r"\b\d{1,3}\s*%\b",
        r"\b\d+(?:\.\d+)?\s*(?:second|seconds|sec|sekund|sekunder|minute|minutes|min)\b",
        r"\baccuracy\b",
        r"\bprecision\b",
        r"\bsla\b",
        r"\bservice level\b",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def strip_ungrounded_numeric_targets(workflow: Dict[str, Any], transcript: str) -> Dict[str, Any]:
    if transcript_has_explicit_sla_or_accuracy_targets(transcript):
        return workflow

    cleaned_workflow = {**workflow}
    cleaned_epics = []
    for epic in workflow.get("epics", []):
        new_epic = {**epic}
        new_requirements = []
        for requirement in epic.get("requirements", []):
            new_req = {**requirement}
            cleaned_acceptance = []
            for criterion in (requirement.get("acceptance_criteria") or []):
                c = (criterion or "").strip()
                if not c:
                    continue
                if re.search(r"\b\d{1,3}\s*%\b", c.lower()):
                    continue
                if re.search(r"\b\d+(?:\.\d+)?\s*(?:second|seconds|sec|s|minute|minutes|min)\b", c.lower()):
                    continue
                cleaned_acceptance.append(c)
            if not cleaned_acceptance:
                cleaned_acceptance = ["Given valid project inputs, when processing completes, then output is reviewable and traceable."]
            new_req["acceptance_criteria"] = cleaned_acceptance
            new_requirements.append(new_req)
        new_epic["requirements"] = new_requirements
        cleaned_epics.append(new_epic)
    cleaned_workflow["epics"] = cleaned_epics
    return cleaned_workflow


def normalize_validation_summary(workflow: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = {**workflow}
    summary = []
    for item in workflow.get("validation_summary", []):
        normalized_item = {**item}
        check = (normalized_item.get("check") or "").lower()
        notes = (normalized_item.get("notes") or "").lower()
        if "generic document system" in check and any(
            phrase in notes for phrase in ["not generic", "specific", "tailored", "domain-specific"]
        ):
            normalized_item["status"] = "pass"
        summary.append(normalized_item)
    cleaned["validation_summary"] = summary
    return cleaned


def _strict_user_story(action: str, outcome: str) -> str:
    normalized_action = (action or "complete the workflow").strip().rstrip(".")
    normalized_outcome = (outcome or "the workflow produces a reliable result").strip().rstrip(".")
    return f"As a user, I want {normalized_action} so that {normalized_outcome}"


def _requirement_user_story(requirement_title: str, epic_title: str) -> str:
    req = _standardize_text_terms(requirement_title or "process the requirement").strip().lower()
    epic_key = _slugify(epic_title or "")
    if "input" in epic_key:
        outcome = "incoming requests are captured in a consistent format for downstream processing"
    elif "extraction" in epic_key or "validation" in epic_key or "computation" in epic_key:
        outcome = "processed data is trustworthy, complete, and ready for business decisions"
    elif "output" in epic_key:
        outcome = "downstream systems receive structured and usable outputs"
    elif "quote" in epic_key or "quotation" in epic_key:
        outcome = "quotation workflows remain accurate and conversion-ready"
    else:
        outcome = "the workflow step executes with clear and testable behavior"
    return _strict_user_story(req, outcome)


def _default_acceptance_criteria(requirement_title: str, epic_title: str) -> List[str]:
    req = _standardize_text_terms(requirement_title or "this requirement").strip().lower()
    epic_key = _slugify(epic_title or "")
    if "input" in epic_key:
        return [
            f"Given incoming business input, when {req} runs, then the system standardizes the data into a canonical structure.",
            "Given malformed or incomplete source input, when intake runs, then the system flags issues with actionable remediation feedback.",
        ]
    if "extraction" in epic_key or "validation" in epic_key or "computation" in epic_key:
        return [
            f"Given normalized input, when {req} runs, then extracted fields and computed values are stored with traceable evidence.",
            "Given conflicting or missing values, when validation runs, then the system blocks progression until issues are resolved.",
        ]
    if "output" in epic_key:
        return [
            f"Given validated data, when {req} runs, then the system produces schema-compliant structured output.",
            "Given delivery or schema failure, when output generation runs, then the system records the failure and initiates recovery handling.",
        ]
    return [
        f"Given valid workflow context, when {req} runs, then the system produces a traceable and reviewable result.",
        "Given rule violations, when processing runs, then the system surfaces a deterministic validation outcome.",
    ]


def _default_edge_cases(requirement_title: str, epic_title: str) -> List[str]:
    req = _standardize_text_terms(requirement_title or "this requirement").strip().lower()
    epic_key = _slugify(epic_title or "")
    if "input" in epic_key:
        return [
            f"The system shall return a clear intake error when required source fields for {req} are missing.",
            f"The system shall prevent partial ingestion when {req} encounters incompatible input formats.",
        ]
    if "extraction" in epic_key or "validation" in epic_key or "computation" in epic_key:
        return [
            f"The system shall flag ambiguous data mappings encountered during {req}.",
            f"The system shall stop downstream progression when {req} detects inconsistent computed values.",
        ]
    if "output" in epic_key:
        return [
            f"The system shall quarantine output artifacts when {req} fails schema validation.",
            f"The system shall retry or queue handoff when {req} encounters transient downstream failures.",
        ]
    return [
        f"The system shall return a clear validation message when required input for {req} is missing.",
        f"The system shall prevent incomplete output when {req} encounters invalid or ambiguous data.",
    ]


def _epic_user_story(title: str) -> str:
    normalized_title = _canonical_epic_title(title or "") or _standardize_text_terms(title or "workflow stage")
    title_key = _slugify(normalized_title)

    if "input" in title_key:
        return _strict_user_story(
            "standardize incoming input data",
            "downstream processing starts with complete and consistent information",
        )
    if "extraction" in title_key or "validation" in title_key or "computation" in title_key:
        return _strict_user_story(
            "extract and validate business data",
            "the workflow operates on trusted and computation-ready information",
        )
    if "output" in title_key:
        return _strict_user_story(
            "generate structured outputs",
            "downstream systems and users receive reliable and consumable results",
        )
    if "quotation" in title_key or "quote" in title_key:
        return _strict_user_story(
            "manage quotation requests",
            "quotation handling remains accurate, traceable, and conversion-ready",
        )

    return _strict_user_story(
        f"complete {normalized_title.lower()}",
        "the workflow advances with clear and measurable business outcomes",
    )


def ensure_workflow_architecture(workflow: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = {**workflow}

    intent = cleaned.get("intent") or {}
    goals = [goal for goal in intent.get("goals", []) if (goal or "").strip()]
    if not goals:
        goals = [
            "Merge all detected business problems into one end-to-end workflow.",
            "Preserve full scope while improving consistency, traceability, and execution quality.",
            "Deliver structured outputs and downstream updates without losing business context.",
        ]
    cleaned["intent"] = {"goals": goals}

    cleaned["capabilities"] = _ensure_capabilities(cleaned.get("capabilities") or [])
    cleaned["epics"] = _ensure_epic_structure(cleaned, cleaned["capabilities"])

    actors = cleaned.get("actors") or []
    if not actors:
        actors = [
            {"name": "User", "type": "user"},
            {"name": "System", "type": "system"},
        ]
    cleaned["actors"] = actors
    return cleaned


def align_workflow_consistency(workflow: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = {**workflow}
    capabilities = [
        {
            **capability,
            "name": _standardize_text_terms(capability.get("name") or ""),
            "description": _standardize_text_terms(capability.get("description") or ""),
        }
        for capability in (cleaned.get("capabilities") or [])
    ]
    capability_by_id = {
        (capability.get("capability_id") or "").strip(): capability
        for capability in capabilities
        if (capability.get("capability_id") or "").strip()
    }
    cleaned["capabilities"] = capabilities

    normalized_epics = []
    for epic in cleaned.get("epics", []):
        epic_copy = {**epic}
        mapped_capabilities = [
            capability_id
            for capability_id in (epic_copy.get("mapped_capabilities") or [])
            if capability_id in capability_by_id
        ]
        if not mapped_capabilities:
            mapped_capabilities = _default_capability_ids_for_epic(
                _canonical_epic_title(epic_copy.get("title") or "") or epic_copy.get("title") or "",
                capabilities,
            )
        epic_copy["mapped_capabilities"] = mapped_capabilities
        epic_copy["title"] = _canonical_epic_title(epic_copy.get("title") or "") or _standardize_text_terms(epic_copy.get("title") or "")
        epic_copy["user_story"] = _epic_user_story(epic_copy.get("title") or "workflow stage")

        normalized_requirements = []
        for requirement in epic_copy.get("requirements", []):
            normalized_requirements.append(
                _normalize_requirement(
                    requirement,
                    epic_copy.get("title") or "Business Function",
                    mapped_capabilities,
                    capabilities,
                )
            )

        epic_copy["requirements"] = normalized_requirements
        normalized_epics.append(epic_copy)

    cleaned["epics"] = normalized_epics
    cleaned["workflow_name"] = _standardize_text_terms(cleaned.get("workflow_name") or "")
    cleaned["workflow_summary"] = _standardize_text_terms(cleaned.get("workflow_summary") or "")
    return cleaned


def align_final_system_structure(workflow: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = {**workflow}
    capabilities = _ensure_capabilities(cleaned.get("capabilities") or [])
    cleaned["capabilities"] = capabilities
    cleaned["epics"] = _ensure_epic_structure(cleaned, capabilities)
    cleaned["workflow_name"] = _standardize_text_terms(cleaned.get("workflow_name") or "")
    cleaned["workflow_summary"] = _standardize_text_terms(cleaned.get("workflow_summary") or "")
    return cleaned


def post_process_generated_workflows(workflows: List[Dict[str, Any]], transcript: str) -> List[Dict[str, Any]]:
    merged = dedupe_and_merge_similar_workflows(workflows)
    merged = collapse_to_single_workflow_if_needed(merged, transcript)
    processed = []
    for workflow in merged:
        workflow = ensure_workflow_architecture(workflow)
        workflow = _inject_signal_driven_requirements(workflow, transcript)
        workflow = strip_ungrounded_numeric_targets(workflow, transcript)
        workflow = align_workflow_consistency(workflow)
        workflow = align_final_system_structure(workflow)
        processed.append(workflow)
    return processed
