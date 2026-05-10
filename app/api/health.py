from fastapi import APIRouter


def create_health_router() -> APIRouter:
    router = APIRouter(tags=["infra"])

    @router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    return router
