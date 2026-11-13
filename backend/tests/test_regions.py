from services.regions import (
    canonical_region,
    region_display_name,
    region_terms,
    resolve_regions,
)


def test_region_aliases_resolve() -> None:
    assert canonical_region("eg") == "egypt"
    assert canonical_region("KSA") == "saudi arabia"
    assert canonical_region("emirates") == "united arab emirates"
    assert canonical_region("dubai") == "united arab emirates"
    assert canonical_region("doha") == "qatar"
    assert canonical_region("mena") == "middle east"
    assert canonical_region("gcc") == "middle east"
    assert canonical_region(None) is None


def test_region_terms_include_local_cities() -> None:
    terms = region_terms(["egypt", "saudi arabia", "uae", "qatar"])
    lowered = [t.lower() for t in terms]
    for expected in ("egypt", "cairo", "saudi arabia", "riyadh", "uae", "dubai", "qatar", "doha"):
        assert expected in lowered


def test_default_regions_cover_mena() -> None:
    regions = resolve_regions(None)
    assert "egypt" in regions
    assert "saudi arabia" in regions
    assert "united arab emirates" in regions
    assert "qatar" in regions
    assert "kuwait" in regions
    assert "bahrain" in regions
    assert "oman" in regions
    assert "jordan" in regions


def test_region_display_name() -> None:
    assert region_display_name("ae") == "United Arab Emirates"
    assert region_display_name("mena") == "Middle East / MENA"
    assert region_display_name("Qatar") == "Qatar"


def test_orchestrator_selects_mena_spiders_for_remote() -> None:
    from services.orchestrator import JobOrchestrator

    orchestrator = JobOrchestrator.__new__(JobOrchestrator)

    qatar = orchestrator._select_spiders(True, "Qatar", "remote", {}, countries=["qatar"])
    assert "linkedin_qatar" in qatar
    assert "indeed_qa" in qatar
    assert "remoteok" in qatar  # global remote boards still included
    assert "linkedin_eg" not in qatar

    mena = orchestrator._select_spiders(
        True, "Middle East", "remote", {}, countries=["middle east"]
    )
    for name in (
        "linkedin_eg", "linkedin_sa", "linkedin_ae", "linkedin_qatar",
        "linkedin_kuwait", "linkedin_bahrain", "linkedin_oman", "linkedin_jordan",
        "indeed_eg", "indeed_sa", "indeed_ae", "indeed_qa",
        "indeed_kw", "indeed_bh", "indeed_om", "indeed_jo",
    ):
        assert name in mena


def test_linkedin_queries_include_region_and_remote() -> None:
    from services.social.linkedin_posts import build_linkedin_queries

    queries = build_linkedin_queries(["devops"], ["egypt", "saudi arabia", "uae", "qatar"])
    assert queries
    for query in queries:
        assert "remote" in query.lower()
    joined = " ".join(queries).lower()
    for expected in ("egypt", "saudi arabia", "uae", "qatar"):
        assert expected in joined


def test_x_queries_include_region_and_remote() -> None:
    from services.social.x_posts import build_x_queries

    queries = build_x_queries(["devops"], ["egypt", "qatar", "middle east"])
    assert queries
    assert len(queries) <= 6
    for query in queries:
        assert "since:" in query
    joined = " ".join(queries).lower()
    assert any(term in joined for term in ("egypt", "cairo", "qatar", "doha", "#وظائف", "وظائف"))
