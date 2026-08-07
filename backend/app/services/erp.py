"""ERP integration layer.

ERP-agnostic connector interface with simulated SAP S/4HANA, Oracle Fusion,
Coupa and Ariba adapters. The demo runs entirely against the local system of
record; swapping in a real adapter means implementing this same protocol.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Invoice, PurchaseOrder, Receipt, Supplier


@dataclass
class ERPResult:
    success: bool
    document_number: str | None = None
    system: str = "SAP_S4HANA"
    message: str = ""
    payload: dict | None = None


class ERPConnector(Protocol):
    system_name: str

    def fetch_po(self, db: Session, po_number: str) -> PurchaseOrder | None: ...
    def fetch_receipts(self, db: Session, po_id: str) -> list[Receipt]: ...
    def lookup_supplier(self, db: Session, name: str) -> Supplier | None: ...
    def post_invoice(self, db: Session, invoice: Invoice) -> ERPResult: ...


class BaseERPConnector:
    system_name = "SAP_S4HANA"
    doc_prefix = "51"

    def fetch_po(self, db: Session, po_number: str) -> PurchaseOrder | None:
        if not po_number:
            return None
        normalized = po_number.strip().upper()
        po = db.execute(
            select(PurchaseOrder).where(PurchaseOrder.po_number == normalized)
        ).scalar_one_or_none()
        if po:
            return po
        # Tolerate common OCR/format drift: PO-4471 vs PO4471 vs 4471
        digits = "".join(ch for ch in normalized if ch.isdigit())
        if not digits:
            return None
        for candidate in db.execute(select(PurchaseOrder)).scalars().all():
            if "".join(ch for ch in candidate.po_number if ch.isdigit()) == digits:
                return candidate
        return None

    def fetch_receipts(self, db: Session, po_id: str) -> list[Receipt]:
        return list(
            db.execute(select(Receipt).where(Receipt.po_id == po_id)).scalars().all()
        )

    def lookup_supplier(self, db: Session, name: str) -> Supplier | None:
        if not name:
            return None
        cleaned = _normalize(name)
        suppliers = db.execute(select(Supplier)).scalars().all()
        best: tuple[float, Supplier | None] = (0.0, None)
        for supplier in suppliers:
            score = max(
                _similarity(cleaned, _normalize(supplier.name)),
                _similarity(cleaned, _normalize(supplier.legal_name or "")),
            )
            if score > best[0]:
                best = (score, supplier)
        return best[1] if best[0] >= 0.72 else None

    def post_invoice(self, db: Session, invoice: Invoice) -> ERPResult:
        rng = random.Random(invoice.id)
        doc = f"{self.doc_prefix}{rng.randint(10_000_000, 99_999_999)}"
        return ERPResult(
            success=True,
            document_number=doc,
            system=self.system_name,
            message=f"Invoice posted to {self.system_name} as document {doc}.",
            payload={
                "company_code": "1000",
                "fiscal_year": date.today().year,
                "posting_date": date.today().isoformat(),
                "document_type": "RE",
                "reference": invoice.invoice_number,
            },
        )


class SAPConnector(BaseERPConnector):
    system_name = "SAP_S4HANA"
    doc_prefix = "51"


class OracleFusionConnector(BaseERPConnector):
    system_name = "ORACLE_FUSION"
    doc_prefix = "AP"


class CoupaConnector(BaseERPConnector):
    system_name = "COUPA"
    doc_prefix = "CP"


class AribaConnector(BaseERPConnector):
    system_name = "ARIBA"
    doc_prefix = "AR"


CONNECTORS: dict[str, BaseERPConnector] = {
    "SAP_S4HANA": SAPConnector(),
    "ORACLE_FUSION": OracleFusionConnector(),
    "COUPA": CoupaConnector(),
    "ARIBA": AribaConnector(),
}


def get_connector(system: str | None = None) -> BaseERPConnector:
    return CONNECTORS.get((system or "SAP_S4HANA").upper(), CONNECTORS["SAP_S4HANA"])


def connector_health() -> list[dict]:
    return [
        {
            "system": name,
            "status": "connected",
            "mode": "simulated",
            "latency_ms": 40 + (index * 17) % 90,
            "capabilities": ["po_fetch", "gr_fetch", "supplier_master", "invoice_post"],
        }
        for index, name in enumerate(CONNECTORS)
    ]


# --------------------------------------------------------------------------
# Fuzzy helpers used for supplier / PO resolution
# --------------------------------------------------------------------------
_NOISE = {
    "inc", "inc.", "llc", "ltd", "ltd.", "corp", "corp.", "co", "co.",
    "company", "gmbh", "plc", "sa", "nv", "bv", "the", "&", "and",
}


def _normalize(value: str) -> str:
    tokens = [
        "".join(ch for ch in token.lower() if ch.isalnum())
        for token in (value or "").split()
    ]
    return " ".join(t for t in tokens if t and t not in _NOISE)


def _similarity(a: str, b: str) -> float:
    """Token-overlap similarity (Jaccard with a bigram assist) — no extra deps."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta, tb = set(a.split()), set(b.split())
    jaccard = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0

    def bigrams(text: str) -> set[str]:
        squashed = text.replace(" ", "")
        return {squashed[i: i + 2] for i in range(len(squashed) - 1)}

    ba, bb = bigrams(a), bigrams(b)
    dice = (2 * len(ba & bb) / (len(ba) + len(bb))) if (ba or bb) else 0.0
    return round(max(jaccard, 0.45 * jaccard + 0.55 * dice), 4)


def text_similarity(a: str, b: str) -> float:
    """Public helper used by duplicate detection."""
    return _similarity(_normalize(a), _normalize(b))
