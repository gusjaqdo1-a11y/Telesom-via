from datetime import datetime, timezone
from database import db

def now():
    return datetime.now(timezone.utc)

async def save_user(tg):
    user = {
        "telegram_id": tg.id,
        "username": tg.username,
        "first_name": tg.first_name,
        "last_name": tg.last_name,
        "language": "en",
        "updated_at": now(),
    }
    await db.users.update_one({"telegram_id": tg.id}, {"$set": user, "$setOnInsert": {"created_at": now(), "status": "active"}}, upsert=True)

async def audit(actor, action, target=None, data=None):
    await db.audit_logs.insert_one({
        "actor": actor, "action": action, "target": target, "data": data or {}, "created_at": now()
    })

async def create_request(kind, user_id, data):
    count = await db.requests.count_documents({})
    rid=f"REQ-{count+1:06d}"
    doc={"request_id":rid,"kind":kind,"user_id":user_id,"data":data,"status":"pending","created_at":now()}
    await db.requests.insert_one(doc)
    return rid
