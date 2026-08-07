# Shared Skills Framework

Reusable capabilities the agents compose. Each folder holds the contract for one
skill; the implementation lives in `backend/app/skills/`.

| Skill | Purpose | Used by |
|---|---|---|
| [`invoice_extraction`](./invoice_extraction/SKILL.md) | Extract structured invoice data from PDF, image, email body or EDI payload. | Invoice Intake Agent |
| [`supplier_lookup`](./supplier_lookup/SKILL.md) | Resolve an extracted supplier name to a vendor master record. | Invoice Intake Agent, Supplier Experience Agent, Procurement Request Agent |
| [`po_lookup`](./po_lookup/SKILL.md) | Find the PO an invoice bills against, directly or by supplier + amount inference. | Invoice Intake Agent |
| [`duplicate_detection`](./duplicate_detection/SKILL.md) | Detect exact and near-duplicate invoices before they reach payment. | Invoice Intake Agent, Exception Resolution Agent |
| [`tax_validation`](./tax_validation/SKILL.md) | Validate tax arithmetic, applicable rate and supplier tax registration. | Invoice Intake Agent |
| [`variance_analysis`](./variance_analysis/SKILL.md) | Compare invoice lines against PO lines and goods receipts, line by line. | Three-Way Match Agent, Exception Resolution Agent, Contract Intelligence Agent |
| [`contract_parsing`](./contract_parsing/SKILL.md) | Compare billed lines against the contracted rate card, term dates and allowed charges. | Exception Resolution Agent, Procurement Request Agent, Contract Intelligence Agent |
| [`approval_routing`](./approval_routing/SKILL.md) | Select an approver with sufficient authority who is available and not overloaded. | — |
| [`sla_prediction`](./sla_prediction/SKILL.md) | Forecast which invoices will breach cycle-time SLA and why. | SLA Command Center Agent |
| [`vendor_risk`](./vendor_risk/SKILL.md) | Monitor sanctions, insurance, tax forms and vendor-master changes for fraud and compliance risk. | Payment Readiness Agent, Supplier Risk Agent |
| [`payment_prioritization`](./payment_prioritization/SKILL.md) | Rank approved invoices for the payment run by urgency, discount value and risk. | — |
| [`exception_resolution`](./exception_resolution/SKILL.md) | Diagnose an AP exception and propose the resolution a human should confirm. | Exception Resolution Agent |
| [`rfp_orchestration`](./rfp_orchestration/SKILL.md) | Create and manage sourcing events end to end, from requirements to award. | Sourcing Event Agent |
| [`supplier_discovery`](./supplier_discovery/SKILL.md) | Shortlist qualified suppliers for a category from vendor master and market signals. | Sourcing Event Agent |
| [`bid_evaluation`](./bid_evaluation/SKILL.md) | Score bids on commercial, technical and risk dimensions against declared weights. | Sourcing Event Agent |
| [`spend_classification`](./spend_classification/SKILL.md) | Map raw spend transactions to a category taxonomy (UNSPSC / NAICS / custom). | Spend Analytics Agent |
| [`supplier_normalization`](./supplier_normalization/SKILL.md) | Collapse supplier name variants onto a single vendor master identity. | Spend Analytics Agent |
| [`savings_identification`](./savings_identification/SKILL.md) | Quantify consolidation, contract-coverage, volume-discount and rationalization levers. | Spend Analytics Agent |
| [`maverick_detection`](./maverick_detection/SKILL.md) | Detect off-contract and off-catalog buying that bypasses negotiated channels. | Spend Analytics Agent |
| [`supplier_risk_assessment`](./supplier_risk_assessment/SKILL.md) | Score a supplier across financial, operational, compliance and ESG risk. | Supplier Risk & Compliance Agent |
| [`esg_scoring`](./esg_scoring/SKILL.md) | Assess sustainability, human-rights and diversity exposure for a supplier. | Supplier Risk & Compliance Agent |
| [`contract_authoring`](./contract_authoring/SKILL.md) | Generate MSA, SOW, NDA and amendment drafts from the standard clause library. | Contract Lifecycle Agent |
| [`clause_analysis`](./clause_analysis/SKILL.md) | Detect missing, risky, non-standard and vendor-favouring language in a contract. | Contract Lifecycle Agent |
| [`obligation_tracking`](./obligation_tracking/SKILL.md) | Extract deliverables, SLAs, rebates and dates, and forecast renewal actions. | Contract Lifecycle Agent |
| [`tail_spend_detection`](./tail_spend_detection/SKILL.md) | Isolate the long tail — the transactions that are most of the volume and least of the value. | Tail Spend Agent |
| [`catalog_compliance`](./catalog_compliance/SKILL.md) | Detect off-catalog buying where a contracted catalog item already exists. | Tail Spend Agent |
| [`vendor_consolidation`](./vendor_consolidation/SKILL.md) | Group fragmented category spend onto a preferred supplier and price the move. | Tail Spend Agent |
| [`spot_buy_automation`](./spot_buy_automation/SKILL.md) | Turn a repeated one-off purchase into a quick three-quote RFQ. | Tail Spend Agent |

Skills analyse and return evidence. They never mutate the system of record —
only an approved human checkpoint can do that.
