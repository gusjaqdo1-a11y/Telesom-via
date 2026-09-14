from db import db
from core.utils import next_id,now,audit
async def create_request(kind,user_id,data):
    rid=await next_id('requests','REQ'); await db.requests.insert_one({'request_id':rid,'kind':kind,'user_id':user_id,'data':data,'status':'pending','created_at':now(),'updated_at':now()}); return rid
async def decide(rid,admin_id,status,note=''):
    r=await db.requests.find_one_and_update({'request_id':rid,'status':'pending'},{'$set':{'status':status,'decision_by':admin_id,'decision_note':note,'updated_at':now()}}) if status in ('confirmed','rejected') else None
    if not r:return False
    await audit(admin_id,status,rid,{'note':note,'kind':r['kind']}); return True
