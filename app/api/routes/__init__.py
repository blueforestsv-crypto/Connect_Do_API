from app.api.routes.auth import router as auth_router
from app.api.routes.profiles import router as profiles_router
from app.api.routes.publications import router as publications_router

__all__ = ["auth_router", "profiles_router", "publications_router"]
