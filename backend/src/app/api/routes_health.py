"""Health/liveness routes."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by CI, Docker Compose, and deployment checks."""
    return {"status": "ok"}
