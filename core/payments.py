from db import db
from core.utils import next_id,now,audit
async def create_payment(user_id,order_id,method,amount,reference=''):
    pid=await next_id('payments','PAY'); await db.payments.insert_one({'payment_id':pid,'user_id':user_id,'order_id':order_id,'method':method,'amount':float(amount),'reference':reference,'status':'pending','created_at':now()}); return pid
async def set_payment(pid,admin_id,status,note=''):
    if status not in ('confirmed','rejected'): return False
    r=await db.payments.find_one_and_update({'payment_id':pid,'status':'pending'},{'$set':{'status':status,'decision_by':admin_id,'note':note,'updated_at':now()}})
    if not r:return False
    await audit(admin_id,'payment_'+status,pid,{'note':note}); return True
