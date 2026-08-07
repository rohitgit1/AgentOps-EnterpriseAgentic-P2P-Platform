from fastapi import APIRouter

from . import admin, agents, analytics, auth, core, hitl

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(core.router)
api_router.include_router(hitl.router)
api_router.include_router(agents.router)
api_router.include_router(agents.orchestration)
api_router.include_router(analytics.router)
api_router.include_router(admin.router)

__all__ = ["api_router"]
