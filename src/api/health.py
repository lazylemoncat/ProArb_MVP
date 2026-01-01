from datetime import datetime, timezone

from fastapi import APIRouter

from .models import HealthResponse

health_router = APIRouter(tags=["health"])

@health_router.get("/api/health", response_model=HealthResponse)
def get_health():
    return HealthResponse(
        status="OK",
        service="arb-engine",
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds")
    )