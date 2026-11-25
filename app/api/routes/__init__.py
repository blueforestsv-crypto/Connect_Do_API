from app.api.routes.account import router as account_router
from app.api.routes.devices import router as devices_router
from app.api.routes.auth import router as auth_router
from app.api.routes.profiles import router as profiles_router
from app.api.routes.publications import router as publications_router
from app.api.routes.contacts import router as contacts_router
from app.api.routes.chats import router as chats_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.applications import router as applications_router

__all__ = [
    "account_router",
    "devices_router",
    "auth_router",
    "profiles_router",
    "publications_router",
    "contacts_router",
    "chats_router",
    "notifications_router",
    "applications_router",
]
