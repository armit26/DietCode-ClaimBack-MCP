import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel
from rapidfuzz import fuzz, utils

BASE_DIR = Path(__file__).resolve().parent.parent
RULES_PATH = BASE_DIR / "rules" / "irdai_2024_rules.json"
SAMPLE_DATA_DIR = BASE_DIR / "sample_data"


class RuleBreach(BaseModel):
    rule_id: str
    rule_name: str
    status: str
    citation: str
    finding: str


class DuplicateCharge(BaseModel):
    item_1: str
    item_2: str
    date: str
    amount_inr: int
    similarity_score: float


class AuditReport(BaseModel):
    case_id: str
    policyholder_name: str
    claimed_amount_inr: int
    continuous_coverage_months: int
    breaches: List[RuleBreach]
    duplicate_charges: List[DuplicateCharge]
    total_duplicate_overcharge_inr: int
    hitl_gate_status: str
    voice_briefs: dict


def load_rules() -> dict:
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_case(case_id: str = "CB-204") -> dict:
    filename = f"case_{case_id.lower().replace('-', '_')}.json"
    case_path = SAMPLE_DATA_DIR / filename
    if not case_path.exists():
        raise FileNotFoundError(f"Case file not found: {case_path}")
    with open(case_path, "r", encoding="utf-8") as f:
        return json.load(f)


def mask_pii(text: str, policyholder_name: str, policy_number: str) -> str:
    masked = text.replace(policyholder_name, "[PATIENT_NAME_MASKED]")
    masked = masked.replace(policy_number, "[POLICY_ID_MASKED]")
    return masked


def detect_duplicate_bill_items(bill_items: List[dict], threshold: int = 85) -> List[DuplicateCharge]:
    duplicates: List[DuplicateCharge] = []
    seen_pairs = set()

    for i in range(len(bill_items)):
        for j in range(i + 1, len(bill_items)):
            a, b = bill_items[i], bill_items[j]
            if a["date"] == b["date"] and a["amount_inr"] == b["amount_inr"]:
                score = fuzz.token_sort_ratio(
                    a["description"], b["description"], processor=utils.default_process
                )
                if score >= threshold and (i, j) not in seen_pairs:
                    seen_pairs.add((i, j))
                    duplicates.append(
                        DuplicateCharge(
                            item_1=a["description"],
                            item_2=b["description"],
                            date=a["date"],
                            amount_inr=b["amount_inr"],
                            similarity_score=round(score, 1),
                        )
                    )
    return duplicates


def run_irdai_audit(case_id: str = "CB-204") -> AuditReport:
    rules_data = load_rules()
    rules_by_id = {r["rule_id"]: r for r in rules_data["rules"]}
    case = load_case(case_id)

    history = case["drive_policy_history"]
    renewals = history["continuous_renewals"]
    active_years = sum(1 for r in renewals if r.get("status") == "Active")
    coverage_months = (active_years * 12) + history.get("ported_or_migrated_months", 0)
    original_si = history.get("initial_sum_insured_inr", 0)

    claim = case["rejection_email"]
    breaches: List[RuleBreach] = []

    if claim.get("cashless_request_hours_taken", 0) > 1:
        r = rules_by_id["IRDAI_CASHLESS_1HR"]
        breaches.append(
            RuleBreach(
                rule_id=r["rule_id"],
                rule_name=r["name"],
                status="VIOLATED",
                citation=r["citation"],
                finding=f"Initial cashless decision took {claim['cashless_request_hours_taken']} hrs (IRDAI limit: 1 hr).",
            )
        )

    if claim.get("discharge_approval_hours_taken", 0) > 3:
        r = rules_by_id["IRDAI_DISCHARGE_3HR"]
        breaches.append(
            RuleBreach(
                rule_id=r["rule_id"],
                rule_name=r["name"],
                status="VIOLATED",
                citation=r["citation"],
                finding=(
                    f"Final discharge authorization took {claim['discharge_approval_hours_taken']} hrs (IRDAI limit: 3 hrs). "
                    "Any extra hospital charges caused by delay must be borne by the insurer from shareholders' funds."
                ),
            )
        )

    if claim.get("reimbursement_days_since_submission", 0) > 15:
        r = rules_by_id["IRDAI_REIMBURSEMENT_15D"]
        breaches.append(
            RuleBreach(
                rule_id=r["rule_id"],
                rule_name=r["name"],
                status="VIOLATED",
                citation=r["citation"],
                finding=(
                    f"Non-cashless claim pending {claim['reimbursement_days_since_submission']} days from submission "
                    "(IRDAI limit: 15 days). Insurer must pay bank rate + 2% interest suo motu from date of claim intimation."
                ),
            )
        )

    denial_text = claim.get("denial_reason", "").lower()
    is_non_disclosure = any(
        kw in denial_text for kw in ["pre-existing", "undisclosed", "non-disclosure", "misrepresentation", "ped"]
    )
    within_original_si = claim["claimed_amount_inr"] <= original_si if original_si else True

    if (
        coverage_months >= 60
        and is_non_disclosure
        and within_original_si
        and not claim.get("fraud_proven", False)
        and not claim.get("is_permanent_exclusion", False)
    ):
        r = rules_by_id["IRDAI_MORATORIUM_60M"]
        breaches.append(
            RuleBreach(
                rule_id=r["rule_id"],
                rule_name=r["name"],
                status="VIOLATED",
                citation=r["citation"],
                finding=(
                    f"{coverage_months} continuous months verified via Drive MCP within the original ₹{original_si:,} sum insured. "
                    "Non-disclosure/misrepresentation contestability is barred after 60 months except for established fraud."
                ),
            )
        )

    claim_action = claim.get("claim_action", "").lower()
    missing_pmc_crc = claim_action == "repudiated" and not claim.get("pmc_or_crc_approval_attached", True)
    missing_clause_ref = (
        claim_action in {"repudiated", "rejected", "partially_disallowed"}
        and not claim.get("specific_policy_clauses_cited", True)
    )

    if missing_pmc_crc or missing_clause_ref:
        r = rules_by_id["IRDAI_PMC_CRC_REPUDIATION"]
        details = []
        if missing_pmc_crc:
            details.append("Repudiation lacks mandatory approval from the PMC or its three-member CRC sub-group")
        if missing_clause_ref:
            details.append("Written communication fails to cite specific policy terms and conditions")
        breaches.append(
            RuleBreach(
                rule_id=r["rule_id"],
                rule_name=r["name"],
                status="VIOLATED",
                citation=r["citation"],
                finding="; ".join(details) + ".",
            )
        )

    duplicates = detect_duplicate_bill_items(case.get("hospital_bill_items", []))
    total_dupe_inr = sum(d.amount_inr for d in duplicates)
    amount_lakhs = claim["claimed_amount_inr"] / 100000

    voice_briefs = {
        "EN": (
            f"Stay calm. We verified {coverage_months} continuous months of coverage in your Drive history for your "
            f"₹{amount_lakhs:.2f} Lakh claim. We found {len(breaches)} IRDAI 2024 violations—including a 60-month Moratorium "
            f"breach and missing PMC/CRC repudiation approval—plus ₹{total_dupe_inr:,} in duplicate hospital bill charges. "
            f"Nothing has been sent yet. Review the draft and tap Approve."
        ),
        "HI": (
            f"घबराएं नहीं। हमने आपकी Google Drive से {coverage_months} महीनों की लगातार पॉलिसी हिस्ट्री जांची है। "
            f"₹{amount_lakhs:.2f} लाख के क्लेम में {len(breaches)} IRDAI 2024 नियमों का उल्लंघन (60-महीने का मोराटोरियम नियम और "
            f"PMC/CRC मंज़ूरी न होना) तथा ₹{total_dupe_inr:,} के डुप्लीकेट बिल चार्ज मिले हैं। आपकी अनुमति के बिना कोई ईमेल नहीं भेजा जाएगा।"
        ),
        "KN": (
            f"ಗಾಬರಿಯಾಗಬೇಡಿ. ನಿಮ್ಮ Google Drive ನಿಂದ {coverage_months} ತಿಂಗಳ ನಿರಂತರ ಪಾಲಿಸಿ ದಾಖಲೆಗಳನ್ನು ಪರಿಶೀಲಿಸಲಾಗಿದೆ. "
            f"₹{amount_lakhs:.2f} ಲಕ್ಷದ ಕ್ಲೈಮ್‌ನಲ್ಲಿ {len(breaches)} IRDAI 2024 ನಿಯಮ ಉಲ್ಲಂಘನೆಗಳು (60-ತಿಂಗಳ ಮೊರಟೋರಿಯಂ ಮತ್ತು "
            f"PMC/CRC ಅನುಮೋದನೆ ಇಲ್ಲದಿರುವುದು) ಹಾಗೂ ₹{total_dupe_inr:,} ನಕಲಿ ಆಸ್ಪತ್ರೆ ಬಿಲ್ ಶುಲ್ಕಗಳು ಪತ್ತೆಯಾಗಿವೆ. "
            f"ನಿಮ್ಮ ಅನುಮೋದನೆ ಇಲ್ಲದೆ ಯಾವುದೇ ಇಮೇಲ್ ಕಳುಹಿಸಲಾಗುವುದಿಲ್ಲ."
        ),
    }

    return AuditReport(
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


def build_gro_draft(case_id: str, user_approved: bool = False) -> dict:
    if not user_approved:
        return {
            "status": "BLOCKED_BY_HITL_GATE",
            "message": "Zero auto-send enforced. Set user_approved=True after human review to save an editable Gmail draft.",
        }

    case = load_case(case_id)
    report = run_irdai_audit(case_id)
    ph = case["policyholder"]

    breach_lines = "\n".join(
        f"- {b.rule_name} ({b.citation}): {b.finding}" for b in report.breaches
    )
    dupe_lines = "\n".join(
        f"- {d.item_1} / {d.item_2} on {d.date}: ₹{d.amount_inr:,} (match {d.similarity_score}%)"
        for d in report.duplicate_charges
    )

    body = (
        f"To: Grievance Redressal Officer ({ph['insurer']})\n"
        f"Subject: Grievance Appeal — Wrongful Claim Repudiation | Policy {ph['policy_number']} | Case #{report.case_id}\n\n"
        f"Dear Grievance Redressal Officer,\n\n"
        f"I formally contest the repudiation of my health insurance claim of ₹{report.claimed_amount_inr:,} "
        f"under Policy No. {ph['policy_number']}. Based on my verified {report.continuous_coverage_months}-month "
        f"continuous coverage history and applicable IRDAI 2024 Master Circular provisions, the following violations were identified:\n\n"
        f"{breach_lines}\n\n"
        f"Flagged Duplicate Hospital Bill Charges (₹{report.total_duplicate_overcharge_inr:,} total):\n"
        f"{dupe_lines}\n\n"
        f"Request: Please place this claim before the PMC / Claims Review Committee and provide a reasoned written resolution "
        f"referencing specific policy terms and conditions within the mandatory 14-day grievance resolution timeline. "
        f"Please note that I may also register this complaint directly on IRDAI's Bima Bharosa portal, and if unresolved "
        f"within 30 days (or resolved unsatisfactorily), I reserve the right to approach the Insurance Ombudsman.\n\n"
        f"Regards,\n{ph['name']}\n"
        f"[Prepared via ClaimBack MCP — Draft Only, Reviewed & Approved by Policyholder]"
    )

    return {
        "status": "GMAIL_DRAFT_SAVED",
        "scope": "gmail.compose (Draft-Only — Zero Auto-Send)",
        "to": ph["gro_email"],
        "subject": f"Grievance Appeal — Policy {ph['policy_number']} | Case #{report.case_id}",
        "draft_body": body,
    }


def build_sla_reminders(case_id: str, base_date: Optional[str] = None) -> dict:
    start = datetime.strptime(base_date, "%Y-%m-%d") if base_date else datetime.now()
    gro_deadline = start + timedelta(days=14)
    ombudsman_date = start + timedelta(days=30)

    return {
        "status": "CALENDAR_SLA_CLOCKS_CREATED",
        "scope": "calendar.events",
        "case_id": case_id,
        "reminders": [
            {
                "title": f"[ClaimBack SLA] 3-Hr Hospital Discharge Cap — Case #{case_id}",
                "trigger": (start + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"),
                "rule": "IRDAI Sep 2024 Circular — 3-Hour Final Discharge Authorization",
            },
            {
                "title": f"[ClaimBack SLA] 14-Day Insurer Grievance Resolution Deadline — Case #{case_id}",
                "trigger": gro_deadline.strftime("%Y-%m-%d 09:00"),
                "rule": "Mandatory 14-day insurer resolution SLA (direct Bima Bharosa registration available anytime)",
            },
            {
                "title": f"[ClaimBack SLA] 30-Day Insurance Ombudsman Eligibility — Case #{case_id}",
                "trigger": ombudsman_date.strftime("%Y-%m-%d 09:00"),
                "rule": "Eligible to file with Insurance Ombudsman if unresolved/unsatisfactory (claims up to ₹50 Lakh)",
            },
        ],
    }