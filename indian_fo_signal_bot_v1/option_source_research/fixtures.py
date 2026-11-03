"""Authored D2 examples; values are not provider facts, rights or quotes."""
from option_intelligence.evidence import digest
from option_intelligence.identity import validate_contract
from .mapping import GROUPS, REQUIREMENTS, SCHEMA, mapping_unit, requirement_for

DECISION = "2026-11-03T10:00:00+05:30"


def synthetic_fixture(provider="upstox"):
    token = "NSE_FO|999999" if provider == "upstox" else "999999"
    underlying = "NSE_INDEX|Nifty 50" if provider == "upstox" else "99926000"
    master = dict(provider=provider, identifier=token, symbol="AUTHORED_D2_OPTION_CE",
        underlying="NIFTY", underlying_identifier=underlying, exchange="NFO",
        segment="NSE_FO_INDEX", instrument_type="OPTIDX", option_type="CE",
        expiry="2026-11-05", strike="25000", lot_size=50, tick_size=".05",
        multiplier=1, price_unit="INR", quantity_unit="UNDERLYING_UNITS",
        valid_from="2026-11-03", valid_to="2026-11-03", contract_status="ACTIVE",
        source="AUTHORED_D2_NOT_VENDOR", source_revision="AUTHORED_MASTER_D2_V1",
        master_id="AUTHORED_D2_MASTER", master_sha256="1"*64,
        source_observed_at="2026-11-03T09:00:00+05:30",
        received_at="2026-11-03T09:00:01+05:30", available_at="2026-11-03T09:00:02+05:30")
    identity = validate_contract(master, decision_at=DECISION).contract
    quote = dict(quote_id="AUTHORED_D2_QUOTE", contract_id=identity.contract_id,
        provider=provider, source_revision=master["source_revision"], source_id="AUTHORED_D2_BOOK",
        observed_at="2026-11-03T09:59:59+05:30", received_at="2026-11-03T09:59:59.500000+05:30",
        available_at=DECISION, bid_at="2026-11-03T09:59:59+05:30", ask_at="2026-11-03T09:59:59+05:30",
        bid="101.50", ask="102.00", bid_size=50, ask_size=50,
        price_unit="INR", quantity_unit="UNDERLYING_UNITS")
    source = dict(master=master, quote=quote,
        policy=dict(source_id="AUTHORED_D2_BOOK", evidence_reference="AUTHORED_NOT_REAL_CLOCK_PROOF",
            available_at="2026-11-03T09:00:00+05:30", documented_cadence_seconds="1",
            timestamp_resolution_seconds=".001", max_age_seconds="3", max_leg_skew_seconds="1"),
        session=dict(session_date="2026-11-03",open_at="2026-11-03T09:15:00+05:30",
            close_at="2026-11-03T15:30:00+05:30",phase="NORMAL",
            source_reference="AUTHORED_RESEARCH_WINDOW_NOT_EXCHANGE_PHASE_AUTHORITY",
            available_at="2026-11-03T09:00:00+05:30"),
        assumptions=dict(version="AUTHORED_D2_COSTS",source_reference="ZERO_FEES_SYNTHETIC_ONLY",
            effective_from="2026-11-03",effective_to="2026-11-03",
            available_at="2026-11-03T09:00:00+05:30",entry_impact="0",exit_impact="0",
            round_trip_fees_inr="0",risk_budget_inr="2000",capital_budget_inr="10000",
            premium_loss_fraction=".35"),
        size_at="2026-11-03T09:59:59+05:30",book_time_meaning="EXCHANGE_BOOK_SNAPSHOT",
        membership=None,context=None,context_max_age_seconds=None,depth=None)
    source["source_sha256"] = digest(source)
    evidence = [dict(requirement=name,evidence_id="AUTHORED_"+name,
        documentation_state="DOCUMENTED",observed_state="VERIFIED",provider=provider,
        scope="SYNTHETIC_OFFLINE_MAPPING",reference="AUTHORED_NOT_OFFICIAL_"+name,
        available_at="2026-11-03T09:00:00+05:30",effective_from="2026-11-03T00:00:00+05:30",
        effective_until="2026-11-04T00:00:00+05:30",
        limitations=["Authored synthetic assumption only; no vendor data, trust or rights"])
        for name in REQUIREMENTS]
    mappings = [dict(source_path=source_group+"."+name,target_path=group+"."+name,
        presence="OBSERVED",unit=mapping_unit(group,name),
        evidence_ids=["AUTHORED_"+requirement_for(group,name)])
        for group,(source_group,names) in GROUPS.items() for name in names]
    return dict(schema_version=SCHEMA,fixture_id="AUTHORED_D2_"+provider,
        provenance="SYNTHETIC_FIXTURE",read_only=True,decision_at=DECISION,intended_lots=1,
        evidence=evidence,source=source,mapping=mappings,
        source_qualified=False,prospective_ready=False,forward_entry_allowed=False,
        actionable=False,execution_allowed=False,historical_replay_allowed=False)


def refresh_source_digest(fixture):
    """Test-only recapture of authored content; never publisher authentication."""
    source = fixture["source"]
    source["source_sha256"] = digest({key:value for key,value in source.items() if key != "source_sha256"})
    return fixture


def example_vectors():
    """Five independently authored outcomes; all remain unqualified."""
    positive = synthetic_fixture()
    missing = synthetic_fixture()
    missing["source"]["master"].pop("tick_size")
    next(row for row in missing["mapping"] if row["target_path"] == "contract.tick_size")["presence"] = "ABSENT"
    refresh_source_digest(missing)
    invalid = synthetic_fixture()
    invalid["source"]["quote"]["bid"] = "103"
    refresh_source_digest(invalid)
    stale = synthetic_fixture()
    for field in ("observed_at", "bid_at", "ask_at"):
        stale["source"]["quote"][field] = "2026-11-03T09:59:56+05:30"
    stale["source"]["size_at"] = "2026-11-03T09:59:56+05:30"
    refresh_source_digest(stale)
    contradictory = synthetic_fixture()
    next(row for row in contradictory["evidence"] if row["requirement"] == "BOOK_SOURCE_CLOCKS")["documentation_state"] = "CONTRADICTORY"
    return (
        ("positive_synthetic_only", positive, "VERIFIED", "SYNTHETIC_MAPPING_ONLY"),
        ("missing_tick", missing, "UNAVAILABLE", "MANDATORY_FIELD_ABSENT"),
        ("invalid_crossed_book", invalid, "INVALID", "NONPOSITIVE_OR_CROSSED_BOOK"),
        ("stale_book_and_sizes", stale, "STALE", "LIQUIDITY_SOURCE_CLOCK_STALE"),
        ("contradictory_book_documentation", contradictory, "NOT_ESTABLISHED", "DOCUMENTATION_CONTRADICTORY"),
    )
