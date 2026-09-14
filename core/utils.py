from datetime import datetime,timezone
from db import db
def now(): return datetime.now(timezone.utc)
async def next_id(collection,prefix): return f'{prefix}-{await db[collection].count_documents({})+1:07d}'
async def audit(actor,action,target=None,data=None): await db.audit_logs.insert_one({'actor':actor,'action':action,'target':target,'data':data or {},'created_at':now()})
async def get_user(uid): return await db.users.find_one({'telegram_id':uid})
async def ensure_user(u):
    old=await get_user(u.id); doc={'telegram_id':u.id,'username':u.username,'first_name':u.first_name,'last_name':u.last_name,'updated_at':now()}
    if not old: doc.update({'language':'en','status':'active','wallet':{'available':0,'pending':0},'created_at':now(),'referrals':0})
    await db.users.update_one({'telegram_id':u.id},{'$set':doc,'$setOnInsert':doc},upsert=True); return old is None
