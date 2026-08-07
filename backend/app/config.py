"""Runtime configuration for P2P AgentOps.

Everything has a demo-safe default so the platform boots with zero setup:
`python -m app.main` gives you a working, seeded, fully offline demo.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="P2P_", extra="ignore")

    app_name: str = "P2P AgentOps"
    version: str = "1.0.0"
    environment: str = "demo"

    # --- Persistence -----------------------------------------------------
    # SQLite by default so a client demo needs no database server.
    # Point at Postgres with:  P2P_DATABASE_URL=postgresql+psycopg://user:pw@host/db
    database_url: str = f"sqlite:///{DATA_DIR / 'p2p_agentops.db'}"

    # --- AI reasoning ----------------------------------------------------
    # "deterministic" = built-in rule/heuristic reasoner. No API key, no network,
    # reproducible output -> the correct default for client demos.
    # "anthropic" / "openai" = live LLM reasoning when keys are present.
    llm_provider: str = os.getenv("P2P_LLM_PROVIDER", "deterministic")
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    # Narration is a short, well-constrained writing task over evidence the
    # policy engine has already decided on — a mid-tier model is the right
    # default. Override if you want a larger one.
    anthropic_model: str = "claude-sonnet-5"
    openai_model: str = "gpt-4o"
    llm_timeout_seconds: float = 45.0

    # --- Human-in-the-loop governance -----------------------------------
    # Master switch. When True, NO agent action reaches a system of record
    # without an explicit human decision, regardless of per-agent autonomy.
    enforce_human_in_the_loop: bool = True
    # Global kill switch for the whole agent fleet.
    agents_paused: bool = False
    # Confidence below which an agent must always escalate to a human.
    global_confidence_floor: float = 0.90

    # --- P2P business policy defaults ------------------------------------
    amount_variance_tolerance_pct: float = 3.0
    quantity_variance_tolerance_pct: float = 2.0
    amount_variance_tolerance_abs: float = 50.0
    duplicate_similarity_threshold: float = 0.92
    sla_invoice_cycle_hours: int = 24
    sla_approval_reminder_hours: int = 48
    sla_approval_escalation_hours: int = 72
    sla_exception_resolution_hours: int = 24

    auto_approve_under_usd: float = 5000.0
    manager_review_under_usd: float = 10000.0

    # --- Demo ergonomics -------------------------------------------------
    seed_on_startup: bool = True
    reset_database_on_startup: bool = False
    cors_origins: str = "*"
    api_prefix: str = "/api"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
