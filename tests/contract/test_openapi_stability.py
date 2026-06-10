"""API contract stability tests (Phase 6 §5.2).

Pins the minimum API surface orchestrators depend on. Uses the real
`/openapi.json` schema so structural breakage (missing paths, removed
components, downgraded response codes, missing scopes) fails CI while
additive changes pass.
"""

from fastapi import routing

from apps.api.main import create_app

# (method, path) pairs required for external orchestrators. Keep sorted.
EXPECTED_ROUTES: set[tuple[str, str]] = {
    ("GET", "/health"),
    ("POST", "/api/v1/charters"),
    ("GET", "/api/v1/charters"),
    ("GET", "/api/v1/cycles"),
    ("POST", "/api/v1/cycles"),
    ("GET", "/api/v1/jobs"),
    ("POST", "/api/v1/jobs/{job_id}/cancel"),
    ("GET", "/api/v1/events/stream"),
    ("GET", "/api/v1/skills"),
    ("POST", "/api/v1/skills/discover"),
    ("GET", "/api/v1/patterns"),
    ("POST", "/api/v1/patterns/consolidate"),
    ("POST", "/api/v1/patterns/decay"),
    ("POST", "/api/v1/patterns/retrieve-preview"),
    ("POST", "/api/v1/patterns/{pattern_id}/retrieve-preview"),
    ("POST", "/api/v1/patterns/{pattern_id}/approve"),
    ("POST", "/api/v1/patterns/{pattern_id}/reject"),
    ("PATCH", "/api/v1/patterns/{pattern_id}/trust-tier"),
    ("GET", "/api/v1/patterns/{pattern_id}"),
    ("GET", "/api/v1/patterns/{pattern_id}/observations"),
}

EXPECTED_COMPONENTS: set[str] = {
    "PatternSummary",
    "PatternDetail",
    "PatternList",
    "PatternApprovalRead",
    "ConsolidateRequest",
    "DecayRequest",
    "JobAcceptedResponse",
}


def _openapi_schema() -> dict:
    app = create_app()
    return app.openapi()


def test_openapi_schema_exposes_required_paths() -> None:
    schema = _openapi_schema()
    paths = schema.get("paths", {})
    missing: list[tuple[str, str]] = []
    for method, path in EXPECTED_ROUTES:
        if path not in paths:
            missing.append((method, path))
            continue
        if method.lower() not in paths[path]:
            missing.append((method, path))
    assert not missing, f"missing required routes: {sorted(missing)}"


def test_openapi_schema_defines_pattern_components() -> None:
    schema = _openapi_schema()
    components = set((schema.get("components", {}).get("schemas") or {}).keys())
    missing = EXPECTED_COMPONENTS - components
    assert not missing, f"missing required component schemas: {sorted(missing)}"


def test_consolidate_and_decay_return_202_accepted() -> None:
    schema = _openapi_schema()
    paths = schema.get("paths", {})
    consolidate = paths["/api/v1/patterns/consolidate"]["post"]["responses"]
    decay = paths["/api/v1/patterns/decay"]["post"]["responses"]
    assert "202" in consolidate, "consolidate must advertise 202 Accepted"
    assert "202" in decay, "decay must advertise 202 Accepted"


def test_pattern_mutations_require_write_scope() -> None:
    """Every mutating pattern endpoint must depend on the patterns.write scope."""
    app = create_app()
    mutating_paths = {
        ("POST", "/api/v1/patterns/consolidate"),
        ("POST", "/api/v1/patterns/decay"),
        ("POST", "/api/v1/patterns/{pattern_id}/approve"),
        ("POST", "/api/v1/patterns/{pattern_id}/reject"),
        ("PATCH", "/api/v1/patterns/{pattern_id}/trust-tier"),
    }
    seen: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, routing.APIRoute):
            continue
        for method in route.methods or set():
            if (method, route.path) not in mutating_paths:
                continue
            seen.add((method, route.path))
            assert _route_uses_scope(route, "patterns.write"), (
                f"{method} {route.path} does not require patterns.write scope"
            )
    assert seen == mutating_paths, f"did not cover all mutating paths: {mutating_paths - seen}"


def _route_uses_scope(route: routing.APIRoute, scope: str) -> bool:
    """Walk the dependant tree for a require_scope(scope) closure."""
    stack = [route.dependant]
    while stack:
        dep = stack.pop()
        call = getattr(dep, "call", None)
        if call is not None:
            cells = getattr(call, "__closure__", None) or ()
            for cell in cells:
                try:
                    value = cell.cell_contents
                except ValueError:
                    continue
                if value == scope:
                    return True
        stack.extend(dep.dependencies)
    return False
