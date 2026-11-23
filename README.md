# ClaimBack MCP 🛡️
**An MCP-powered personal health insurance claims auditor & human-approved appeal assistant for Indian families.**
[![Track](https://img.shields.io/badge/Track%201-Make%20MCP%20Matter-C2410C?style=flat-square)](https://github.com/armit26/DietCode-ClaimBack-MCP)
[![Stack](https://img.shields.io/badge/Core-FastMCP%20%7C%20AWS%20%7C%20ElevenLabs-15803D?style=flat-square)](https://github.com/armit26/DietCode-ClaimBack-MCP)
[![Status](https://img.shields.io/badge/Status-Runnable%20Ideathon%20Prototype-FD9B36?style=flat-square)](https://github.com/armit26/DietCode-ClaimBack-MCP)

> **Team Diet Code**
> *Built for wHACKiest 2026 — Track 1: Make MCP Matter (Less Magic, More Utility)*

---

## 🚨 The Problem
During a medical emergency, families cannot audit a **40-page policy PDF** and an inflated **12-page hospital bill** scattered across Gmail and Drive—so under stress, they quietly absorb thousands of rupees in **unfair rejections and hidden deductions**.

| Reality Check | Verified Signal |
| :--- | :--- |
| **58 Crore+** | Insured Indians (~33.5 Cr private retail & group) filing **3.26 Crore+ health claims/year** *(IRDAI)* |
| **2.97 Lakh** | Grievances hit IRDAI's *Bima Bharosa* portal in FY26 alone (up from 2.58L in FY25; ~69% claim disputes — *Finance Ministry / IRDAI*) |
| **₹2 Crore** | Nov 2026: IRDAI fined Star Health ₹2 Crore for unjustified claim rejections and unsupported bill deductions |

**Why current options fail:** Grievance portals (*Bima Bharosa*) are filing channels only—no bill audit or deadline tracking; claim agents are slow, mostly English, and take a **10–15% payout cut**; generic AI chatbots hallucinate insurance regulations and lack controlled access to real records.

---

## 💡 Our Solution: ClaimBack MCP
**ClaimBack MCP** connects a family's everyday apps via **Model Context Protocol (MCP)** using strict **read/draft-only scopes**, audits policies and hospital bills against **codified IRDAI 2024 rules**, explains rights aloud in regional languages, and enforces a **strict Human-in-the-Loop (HITL) approval gate**.

### The 4 Scoped FastMCP Tools (`mcp_server/server.py`)
1. **`drive_policy_fetcher`** — Fetches policy metadata and multi-year continuous renewal history via read-only Google Drive scope to verify moratorium eligibility.
2. **`irdai_rule_auditor`** — Runs deterministic Python/JSON checks against IRDAI 2024 rules and uses `RapidFuzz` fuzzy matching to catch duplicate hospital bill charges.
3. **`gmail_draft_escalator`** — Generates an editable Grievance Redressal Officer (GRO) appeal draft in Gmail (**zero autonomous sending**; hard-blocked until explicit human approval).
4. **`calendar_sla_tracker`** — Schedules automated SLA clocks (3-hr discharge cap, 14-day insurer grievance resolution deadline, and 30-day Ombudsman eligibility) via Google Calendar.

### Deterministic IRDAI 2024 Rules Checked (`rules/irdai_2024_rules.json`)
| Rule ID | IRDAI 2024 Mandate | Regulatory Basis |
| :--- | :--- | :--- |
| **`IRDAI_CASHLESS_1HR`** | Initial cashless decision within **1 hour** of receipt of request | Sep 2024 Circular, Sec I, Part B, V.3(i), 1(i) |
| **`IRDAI_DISCHARGE_3HR`** | Final discharge approval within **3 hours** (extra stay cost borne by insurer from shareholders' funds) | Sep 2024 Circular, Sec I, Part B, V.3(i), 2(i)–(ii) |
| **`IRDAI_REIMBURSEMENT_15D`** | Non-cashless settlement within **15 days from claim submission**; delays attract **bank rate + 2% interest** paid *suo motu* from claim intimation until payment | Sep 2024 Circular, Sec I, Part B, V.2(ii) & V.3(iii)(6) |
| **`IRDAI_MORATORIUM_60M`** | After **60 continuous months** (including ported/migrated credits), non-disclosure/misrepresentation contestability is barred except **established fraud** *(applies to initial sum insured; separate 60-mo clock on enhanced sum insured; permanent exclusions remain separate)* | IRDAI (Insurance Products) Regs 2024, Sch. III, Para 8 & May 2024 Circular, Ch. I, Para 13 |
| **`IRDAI_PMC_CRC_REPUDIATION`** | No claim repudiation without **PMC** or 3-member **CRC** approval; all repudiated, rejected, or partially disallowed claims must cite specific policy terms in writing | Sep 2024 Circular, Sec I, Part B, V.3(iii) & May 2024 Circular, Ch. I, Para 17 |
| **Bill Dupe Audit** | Fuzzy line-item matching (`RapidFuzz`) catches repeated consumables & split hospital charges | Line-item billing verification |

> **Escalation Rights Encoded:** Policyholders may register complaints with the insurer's **GRO** or directly on IRDAI's **Bima Bharosa** portal (no waiting period required; 14-day insurer resolution SLA), and approach the **Insurance Ombudsman** (claims up to ₹50 Lakh) if unresolved after 30 days or resolved unsatisfactorily after written representation to the insurer.

---

## 🏗️ System Architecture & Data Flow

```text
[1. INPUT & FRONTEND]            [2. AWS + AI & IRDAI ENGINE]           [3. SAFETY GATE & VOICE]         [4. SAFE MCP OUTPUTS]
Next.js · Tailwind · OAuth       FastAPI · FastMCP (AWS Lambda)         STRICT ZERO AUTO-SEND            Everyday Apps (MCP)
┌─────────────────────────┐      ┌────────────────────────────────┐     ┌─────────────────────────┐      ┌─────────────────────────┐
│ • Upload hospital bill  │HTTPS │ • AWS Textract + PyMuPDF OCR   │Audit│ • HITL Approval Gate    │User  │ • Gmail MCP:            │
│ • Forward rejection mail├─────►│ • Presidio PII Masking         ├────►│   Red/Green clause diff │Appr. │   Editable GRO draft    │
│ • Sync 6-yr Drive docs  │+PDFs │ • Claude API + Pydantic JSON   │Rpt. │   1-Click Human Approve ├─────►│ • Calendar MCP:         │
│ • View Red/Green diff   │      │ • 5 IRDAI Rules + RapidFuzz    │     │ • ElevenLabs Voice      │      │   3-hr, 14-d & 30-d SLA │
└─────────────────────────┘      └───────────────┬────────────────┘     │   Brief (EN · HI · KN)  │      │ • PDF Dossier:          │
                                                 │ Store                └────────────┬────────────┘      │   Bima Bharosa/Ombuds.  │
                                                 ▼                                   ▼ Log               └────────────┬────────────┘
                           ┌──────────────────────────────────────────────────────────────────────────────────────────┴───┐
                           │        ENCRYPTED DATABASE & AUDIT TRAIL (DPDP ACT ALIGNED)                                   │
                           │   AWS S3 (SSE-KMS PDFs)  ·  AWS DynamoDB (Audit & Approval Logs)  ·  1-Click User Delete     │
                           └──────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start (Run the Core Prototype Locally)

```bash
git clone [https://github.com/armit26/DietCode-ClaimBack-MCP.git](https://github.com/armit26/DietCode-ClaimBack-MCP.git)
cd DietCode-ClaimBack-MCP

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 1. Run the interactive IRDAI 2024 audit + RapidFuzz + HITL approval demo
python demo_run.py

# 2. Launch the 4-tool Python FastMCP server
python -m mcp_server.server
```

---

## 🛠️ Tech Stack

| Layer | Technology / API | Purpose |
| :--- | :--- | :--- |
| **Frontend** | Next.js + Tailwind CSS | Responsive web app for phone/laptop use right at the hospital desk |
| **MCP Layer** | Python FastMCP SDK + Google OAuth 2.0 | Standard tool bridge to Gmail, Drive & Calendar with read/draft-only scopes |
| **Backend & Cloud** | FastAPI (Python) on AWS Lambda + API Gateway | Serverless execution hosting our 4 MCP tools |
| **Document Parsing** | AWS Textract + PyMuPDF + RapidFuzz | Extracts multi-column hospital bills & catches duplicate line items |
| **AI & IRDAI Rules** | Claude API + IRDAI 2024 JSON + Pydantic | AI structures messy clauses; deterministic Python rules verify the law |
| **Voice Co-Pilot** | ElevenLabs Multilingual v2 TTS | Calm 30s spoken rights briefs in English, Hindi & Kannada |
| **Database & Privacy** | AWS S3 (SSE-KMS) + DynamoDB + Microsoft Presidio | Masks patient IDs before AI calls, encrypts files & logs user approvals |

---

## 📂 Repository Structure & Ideathon Build Status
> *In line with wHACKiest 2026 guidelines, this repository contains a runnable core prototype and will continue to be expanded through the **26–27 Nov Ideation presentation**.*

```text
├── rules/
│   └── irdai_2024_rules.json      # Verified IRDAI May & Sep 2024 rulebook & citations
├── mcp_server/
│   ├── __init__.py
│   ├── auditor.py                 # Deterministic 5-rule engine + RapidFuzz bill dupe audit
│   └── server.py                  # Python FastMCP server exposing all 4 scoped tools
├── sample_data/
│   └── case_cb_204.json           # End-to-end test case (72-mo moratorium + ₹8,600 dupes)
├── demo_run.py                    # 1-command interactive CLI prototype with HITL gate
├── requirements.txt
├── .gitignore
└── README.md
```

### Ideathon Prototype Checklist (Nov 23 – Nov 26)
- [x] Problem validation, IRDAI 2024 regulatory mapping & architecture design
- [x] `rules/irdai_2024_rules.json` — Verified 5-rule IRDAI 2024 dataset with exact circular citations
- [x] `mcp_server/` — Working Python `FastMCP` server with 4 tools & `RapidFuzz` duplicate bill detector
- [x] `sample_data/case_cb_204.json` + `demo_run.py` — End-to-end runnable HITL audit prototype
- [ ] `frontend/` — Interactive Next.js Red/Green Audit Card + live ElevenLabs audio playback *(in progress for Nov 26–27 Ideation Day)*

---

## 🔒 Privacy & Safe Positioning
- **Strict Human-in-the-Loop (HITL):** Gmail MCP is scoped to save **editable drafts only**—ClaimBack MCP never sends an email autonomously.
- **DPDP Act Aligned:** Patient identifiers are masked before LLM processing, documents are stored encrypted on AWS S3, and users have 1-click delete control.
- **Disclaimer:** ClaimBack MCP is a clause-backed audit and appeal-drafting helper, **not formal legal advice**. All escalation decisions remain 100% with the policyholder.

---

## 👥 Team Diet Code