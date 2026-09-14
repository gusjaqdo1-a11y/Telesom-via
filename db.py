from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI,DB_NAME
client=AsyncIOMotorClient(MONGO_URI); db=client[DB_NAME]
async def init_db():
    for c,f,u in [('users','telegram_id',True),('requests','request_id',True),('orders','order_id',True),('payments','payment_id',True),('admins','telegram_id',True)]:
        await db[c].create_index(f,unique=u)
    await db.audit_logs.create_index('created_at')
