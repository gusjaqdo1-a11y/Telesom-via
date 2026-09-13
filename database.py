from motor.motor_asyncio import AsyncIOMotorClient
from config import settings

client = AsyncIOMotorClient(settings.MONGO_URI)
db = client["telesombot"]

async def ensure_indexes():
    await db.users.create_index("telegram_id", unique=True)
    await db.orders.create_index("order_id", unique=True)
    await db.payments.create_index("payment_id", unique=True)
    await db.audit_logs.create_index("created_at")
