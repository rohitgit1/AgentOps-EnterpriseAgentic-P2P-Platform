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

Skills analyse and return evidence. They never mutate the system of record —
only an approved human checkpoint can do that.
