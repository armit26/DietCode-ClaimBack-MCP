from fastmcp import FastMCP

from mcp_server.auditor import (
    build_gro_draft,
    build_sla_reminders,
    load_case,
    run_irdai_audit,
)

mcp = FastMCP("ClaimBack MCP")


@mcp.tool()
def drive_policy_fetcher(case_id: str = "CB-204") -> dict:
    """Fetch policy metadata and multi-year continuous renewal history via read-only Google Drive MCP scope."""
    case = load_case(case_id)
    history = case["drive_policy_history"]
    return {
        "case_id": case["case_id"],
        "insurer": case["policyholder"]["insurer"],
        "policy_number": case["policyholder"]["policy_number"],
        "source": history["source"],
        "initial_inception_date": history["initial_inception_date"],
        "initial_sum_insured_inr": history["initial_sum_insured_inr"],
        "total_continuous_years": len(history["continuous_renewals"]),
        "renewals": history["continuous_renewals"],
    }


@mcp.tool()
def irdai_rule_auditor(case_id: str = "CB-204") -> dict:
    """Audit a health insurance claim and hospital bill against deterministic IRDAI 2024 rules and RapidFuzz duplicate detection."""
    report = run_irdai_audit(case_id)
    return report.model_dump()


@mcp.tool()
def gmail_draft_escalator(case_id: str = "CB-204", user_approved: bool = False) -> dict:
    """Save an editable GRO grievance draft in Gmail. Enforces strict HITL gate (zero autonomous sending)."""
    return build_gro_draft(case_id=case_id, user_approved=user_approved)


@mcp.tool()
def calendar_sla_tracker(case_id: str = "CB-204") -> dict:
    """Schedule 3-hour discharge, 14-day grievance resolution, and 30-day Ombudsman eligibility clocks via Calendar MCP."""
    return build_sla_reminders(case_id=case_id)


if __name__ == "__main__":
    mcp.run()