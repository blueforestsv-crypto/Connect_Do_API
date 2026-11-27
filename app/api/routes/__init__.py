from app.api.routes.account import router as account_router
from app.api.routes.devices import router as devices_router
from app.api.routes.legal import router as legal_router
from app.api.routes.media import router as media_router
from app.api.routes.professional import router as professional_router
from app.api.routes.safety import router as safety_router
from app.api.routes.stickers import router as stickers_router
from app.api.routes.stories import router as stories_router
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
    "legal_router",
    "media_router",
    "stories_router",
    "stickers_router",
    "safety_router",
    "professional_router",
    "auth_router",
    "profiles_router",
    "publications_router",
    "contacts_router",
    "chats_router",
    "notifications_router",
    "applications_router",
]
