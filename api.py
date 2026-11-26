from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mcp_server.auditor import (
    AuditReport,
    RuleBreach,
    build_gro_draft,
    build_sla_reminders,
    detect_duplicate_bill_items,
    load_case,
    load_rules,
    mask_pii,
)
from mcp_server.server import mcp

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="ClaimBack MCP API", version="1.0.0")

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


class AuditRequest(BaseModel):
    case_id: str = "CB-204"
    coverage_months: Optional[int] = None
    cashless_hours: Optional[float] = None
    discharge_hours: Optional[float] = None
    reimbursement_days: Optional[int] = None
    pmc_or_crc_attached: Optional[bool] = None
    clauses_cited: Optional[bool] = None
    extra_bill_desc: Optional[str] = None
    extra_bill_amount: Optional[int] = None


class ApprovalRequest(AuditRequest):
    user_approved: bool = False


def evaluate_audit(req: AuditRequest) -> dict:
    rules_data = load_rules()
    rules_by_id = {r["rule_id"]: r for r in rules_data["rules"]}
    case = load_case(req.case_id)

    history = case["drive_policy_history"]
    renewals = history["continuous_renewals"]
    active_years = sum(1 for r in renewals if r.get("status") == "Active")
    default_months = (active_years * 12) + history.get("ported_or_migrated_months", 0)

    coverage_months = req.coverage_months if req.coverage_months is not None else default_months
    original_si = history.get("initial_sum_insured_inr", 0)
    claim = case["rejection_email"]

    cashless_hrs = (
        req.cashless_hours
        if req.cashless_hours is not None
        else claim.get("cashless_request_hours_taken", 0)
    )
    discharge_hrs = (
        req.discharge_hours
        if req.discharge_hours is not None
        else claim.get("discharge_approval_hours_taken", 0)
    )
    reimb_days = (
        req.reimbursement_days
        if req.reimbursement_days is not None
        else claim.get("reimbursement_days_since_submission", 0)
    )
    pmc_attached = (
        req.pmc_or_crc_attached
        if req.pmc_or_crc_attached is not None
        else claim.get("pmc_or_crc_approval_attached", True)
    )
    clauses_cited = (
        req.clauses_cited
        if req.clauses_cited is not None
        else claim.get("specific_policy_clauses_cited", True)
    )

    all_rules_eval = []
    breaches = []

    # 1. Cashless 1-Hr
    r1 = rules_by_id["IRDAI_CASHLESS_1HR"]
    if cashless_hrs > 1:
        b = RuleBreach(
            rule_id=r1["rule_id"],
            rule_name=r1["name"],
            status="VIOLATED",
            citation=r1["citation"],
            finding=f"Initial cashless decision took {cashless_hrs} hrs (IRDAI limit: 1 hr).",
        )
        breaches.append(b)
        all_rules_eval.append(b.model_dump())
    else:
        all_rules_eval.append(
            {
                "rule_id": r1["rule_id"],
                "rule_name": r1["name"],
                "status": "COMPLIANT",
                "citation": r1["citation"],
                "finding": f"Initial cashless decision completed in {cashless_hrs} hr(s) — within 1-hr IRDAI mandate.",
            }
        )

    # 2. Discharge 3-Hr
    r2 = rules_by_id["IRDAI_DISCHARGE_3HR"]
    if discharge_hrs > 3:
        b = RuleBreach(
            rule_id=r2["rule_id"],
            rule_name=r2["name"],
            status="VIOLATED",
            citation=r2["citation"],
            finding=(
                f"Final discharge authorization took {discharge_hrs} hrs (IRDAI limit: 3 hrs). "
                "Extra hospital charges caused by delay must be borne by the insurer from shareholders' funds."
            ),
        )
        breaches.append(b)
        all_rules_eval.append(b.model_dump())
    else:
        all_rules_eval.append(
            {
                "rule_id": r2["rule_id"],
                "rule_name": r2["name"],
                "status": "COMPLIANT",
                "citation": r2["citation"],
                "finding": f"Final discharge authorization completed in {discharge_hrs} hr(s) — within 3-hr IRDAI mandate.",
            }
        )

    # 3. Reimbursement 15-Day
    r3 = rules_by_id["IRDAI_REIMBURSEMENT_15D"]
    if reimb_days > 15:
        b = RuleBreach(
            rule_id=r3["rule_id"],
            rule_name=r3["name"],
            status="VIOLATED",
            citation=r3["citation"],
            finding=(
                f"Non-cashless claim pending {reimb_days} days from submission (IRDAI limit: 15 days). "
                "Insurer must pay bank rate + 2% interest suo motu from claim intimation."
            ),
        )
        breaches.append(b)
        all_rules_eval.append(b.model_dump())
    else:
        all_rules_eval.append(
            {
                "rule_id": r3["rule_id"],
                "rule_name": r3["name"],
                "status": "COMPLIANT",
                "citation": r3["citation"],
                "finding": f"Claim timeline ({reimb_days} days) is within the 15-day non-cashless settlement window.",
            }
        )

    # 4. Moratorium 60-Month
    r4 = rules_by_id["IRDAI_MORATORIUM_60M"]
    denial_text = claim.get("denial_reason", "").lower()
    is_non_disclosure = any(
        kw in denial_text
        for kw in ["pre-existing", "undisclosed", "non-disclosure", "misrepresentation", "ped"]
    )
    within_original_si = claim["claimed_amount_inr"] <= original_si if original_si else True

    if (
        coverage_months >= 60
        and is_non_disclosure
        and within_original_si
        and not claim.get("fraud_proven", False)
        and not claim.get("is_permanent_exclusion", False)
    ):
        b = RuleBreach(
            rule_id=r4["rule_id"],
            rule_name=r4["name"],
            status="VIOLATED",
            citation=r4["citation"],
            finding=(
                f"{coverage_months} continuous months verified via Drive MCP within the original ₹{original_si:,} sum insured. "
                "Non-disclosure/misrepresentation contestability is barred after 60 months except for established fraud."
            ),
        )
        breaches.append(b)
        all_rules_eval.append(b.model_dump())
    else:
        all_rules_eval.append(
            {
                "rule_id": r4["rule_id"],
                "rule_name": r4["name"],
                "status": "COMPLIANT" if coverage_months < 60 else "NOT_TRIGGERED",
                "citation": r4["citation"],
                "finding": (
                    f"Coverage duration is {coverage_months} months (below 60-month moratorium threshold; "
                    "non-disclosure clause review still applies)."
                    if coverage_months < 60
                    else "Moratorium rule satisfied."
                ),
            }
        )

    # 5. PMC / CRC & Clause Citation
    r5 = rules_by_id["IRDAI_PMC_CRC_REPUDIATION"]
    claim_action = claim.get("claim_action", "").lower()
    missing_pmc = claim_action == "repudiated" and not pmc_attached
    missing_clauses = (
        claim_action in {"repudiated", "rejected", "partially_disallowed"} and not clauses_cited
    )

    if missing_pmc or missing_clauses:
        details = []
        if missing_pmc:
            details.append(
                "Repudiation lacks mandatory approval from the PMC or its three-member CRC sub-group"
            )
        if missing_clauses:
            details.append("Written communication fails to cite specific policy terms and conditions")
        b = RuleBreach(
            rule_id=r5["rule_id"],
            rule_name=r5["name"],
            status="VIOLATED",
            citation=r5["citation"],
            finding="; ".join(details) + ".",
        )
        breaches.append(b)
        all_rules_eval.append(b.model_dump())
    else:
        all_rules_eval.append(
            {
                "rule_id": r5["rule_id"],
                "rule_name": r5["name"],
                "status": "COMPLIANT",
                "citation": r5["citation"],
                "finding": "PMC/CRC repudiation sign-off and specific policy term citations are present.",
            }
        )

    bill_items = list(case.get("hospital_bill_items", []))
    if req.extra_bill_desc and req.extra_bill_amount and bill_items:
        bill_items.append(
            {
                "date": bill_items[0]["date"],
                "description": req.extra_bill_desc.strip(),
                "amount_inr": req.extra_bill_amount,
            }
        )

    duplicates = detect_duplicate_bill_items(bill_items)
    total_dupe_inr = sum(d.amount_inr for d in duplicates)
    amount_lakhs = claim["claimed_amount_inr"] / 100000

    voice_briefs = {
        "EN": (
            f"Stay calm. We verified {coverage_months} continuous months of coverage in your Drive history for your "
            f"₹{amount_lakhs:.2f} Lakh claim. We found {len(breaches)} IRDAI 2024 violations and ₹{total_dupe_inr:,} "
            f"in duplicate hospital bill charges. Nothing has been sent yet. Review the draft and tap Approve."
        ),
        "HI": (
            f"घबराएं नहीं। हमने आपकी Google Drive से {coverage_months} महीनों की लगातार पॉलिसी हिस्ट्री जांची है। "
            f"₹{amount_lakhs:.2f} लाख के क्लेम में {len(breaches)} IRDAI 2024 नियमों का उल्लंघन तथा ₹{total_dupe_inr:,} "
            f"के डुप्लीकेट बिल चार्ज मिले हैं। आपकी अनुमति के बिना कोई ईमेल नहीं भेजा जाएगा।"
        ),
        "KN": (
            f"ಗಾಬರಿಯಾಗಬೇಡಿ. ನಿಮ್ಮ Google Drive ನಿಂದ {coverage_months} ತಿಂಗಳ ನಿರಂತರ ಪಾಲಿಸಿ ದಾಖಲೆಗಳನ್ನು ಪರಿಶೀಲಿಸಲಾಗಿದೆ. "
            f"₹{amount_lakhs:.2f} ಲಕ್ಷದ ಕ್ಲೈಮ್‌ನಲ್ಲಿ {len(breaches)} IRDAI 2024 ನಿಯಮ ಉಲ್ಲಂಘನೆಗಳು ಹಾಗೂ ₹{total_dupe_inr:,} "
            f"ನಕಲಿ ಆಸ್ಪತ್ರೆ ಬಿಲ್ ಶುಲ್ಕಗಳು ಪತ್ತೆಯಾಗಿವೆ. ನಿಮ್ಮ ಅನುಮೋದನೆ ಇಲ್ಲದೆ ಯಾವುದೇ ಇಮೇಲ್ ಕಳುಹಿಸಲಾಗುವುದಿಲ್ಲ."
        ),
    }

    report = AuditReport(
        case_id=case["case_id"],
        policyholder_name=case["policyholder"]["name"],
        claimed_amount_inr=claim["claimed_amount_inr"],
        continuous_coverage_months=coverage_months,
        breaches=breaches,
        duplicate_charges=duplicates,
        total_duplicate_overcharge_inr=total_dupe_inr,
        hitl_gate_status="LOCKED — Awaiting Explicit 1-Click Human Approval",
        voice_briefs=voice_briefs,
    )

    return {
        "report": report.model_dump(),
        "all_rules": all_rules_eval,
        "inputs_used": {
            "coverage_months": coverage_months,
            "cashless_hours": cashless_hrs,
            "discharge_hours": discharge_hrs,
            "reimbursement_days": reimb_days,
            "pmc_or_crc_attached": pmc_attached,
            "clauses_cited": clauses_cited,
        },
    }


@app.get("/")
def serve_home():
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="frontend/index.html not found")
    return FileResponse(str(index_path))


@app.get("/api/case/{case_id}")
def get_case_context(case_id: str = "CB-204"):
    case = load_case(case_id)
    ph = case["policyholder"]
    raw_snippet = (
        f"Patient: {ph['name']} | Policy: {ph['policy_number']} | "
        f"Insurer: {ph['insurer']} | Denial Reason: {case['rejection_email'].get('denial_reason', '')}"
    )
    masked_snippet = mask_pii(raw_snippet, ph["name"], ph["policy_number"])

    tools = [
        {
            "name": "drive_policy_fetcher",
            "scope": "drive.readonly",
            "desc": "Fetches multi-year continuous renewal history from Google Drive",
        },
        {
            "name": "irdai_rule_auditor",
            "scope": "local.deterministic",
            "desc": "Audits claim & bill against IRDAI 2024 rules + RapidFuzz",
        },
        {
            "name": "gmail_draft_escalator",
            "scope": "gmail.compose (Draft-Only)",
            "desc": "Creates editable GRO appeal draft — zero auto-send",
        },
        {
            "name": "calendar_sla_tracker",
            "scope": "calendar.events",
            "desc": "Schedules 3-hr discharge, 14-day GRO & 30-day Ombudsman SLAs",
        },
    ]

    return {
        "case": case,
        "pii_preview": {"raw": raw_snippet, "masked": masked_snippet},
        "mcp_server_name": mcp.name,
        "mcp_tools": tools,
    }


@app.post("/api/audit")
def run_audit_endpoint(req: AuditRequest):
    return evaluate_audit(req)


@app.post("/api/approve")
def approve_hitl_endpoint(req: ApprovalRequest):
    if not req.user_approved:
        return build_gro_draft(req.case_id, user_approved=False)

    is_default = all(
        getattr(req, field) is None
        for field in [
            "coverage_months",
            "cashless_hours",
            "discharge_hours",
            "reimbursement_days",
            "pmc_or_crc_attached",
            "clauses_cited",
            "extra_bill_desc",
            "extra_bill_amount",
        ]
    )
    if is_default:
        draft = build_gro_draft(req.case_id, user_approved=True)
    else:
        eval_data = evaluate_audit(req)
        rep = eval_data["report"]
        case = load_case(req.case_id)
        ph = case["policyholder"]
        breach_lines = "\n".join(
            f"- {b['rule_name']} ({b['citation']}): {b['finding']}" for b in rep["breaches"]
        ) or "- No statutory IRDAI timeline/moratorium breach triggered under current simulation parameters."
        dupe_lines = "\n".join(
            f"- {d['item_1']} / {d['item_2']} on {d['date']}: ₹{d['amount_inr']:,} (match {d['similarity_score']}%)"
            for d in rep["duplicate_charges"]
        ) or "- No duplicate hospital line items flagged."
        body = (
            f"To: Grievance Redressal Officer ({ph['insurer']})\n"
            f"Subject: Grievance Appeal — Policy {ph['policy_number']} | Case #{rep['case_id']}\n\n"
            f"Dear Grievance Redressal Officer,\n\n"
            f"I formally contest the decision on my health insurance claim of ₹{rep['claimed_amount_inr']:,} "
            f"under Policy No. {ph['policy_number']} ({rep['continuous_coverage_months']} months continuous coverage):\n\n"
            f"{breach_lines}\n\n"
            f"Flagged Duplicate Hospital Bill Charges (₹{rep['total_duplicate_overcharge_inr']:,} total):\n"
            f"{dupe_lines}\n\n"
            f"Please provide a reasoned written resolution referencing specific policy terms within 14 days.\n\n"
            f"Regards,\n{ph['name']}\n[Prepared via ClaimBack MCP — Draft Only, Approved by Policyholder]"
        )
        draft = {
            "status": "GMAIL_DRAFT_SAVED",
            "scope": "gmail.compose (Draft-Only — Zero Auto-Send)",
            "to": ph["gro_email"],
            "subject": f"Grievance Appeal — Policy {ph['policy_number']} | Case #{rep['case_id']}",
            "draft_body": body,
        }

    slas = build_sla_reminders(req.case_id)
    return {"draft": draft, "slas": slas}
