import os
from dataclasses import dataclass

@dataclass
class Settings:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    MONGO_URI: str = os.getenv("MONGO_URI", "")
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))

settings = Settings()
if not settings.BOT_TOKEN or not settings.MONGO_URI or not settings.ADMIN_ID:
    raise RuntimeError("Set BOT_TOKEN, MONGO_URI and ADMIN_ID in Railway/Render Variables.")
