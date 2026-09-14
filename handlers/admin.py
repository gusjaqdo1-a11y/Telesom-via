from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from config import ADMIN_ID
from db import db
from core.constants import ADMIN_PANELS
from core.approval import decide
from core.payments import set_payment
router=Router()
def ok(m): return m.from_user.id==ADMIN_ID
@router.message(Command('admin'))
async def admin(m):
    if not ok(m):return
    await m.answer('🛠 ADMIN CONTROL\n\n'+'\n'.join(f'{i+1}. {x}' for i,x in enumerate(ADMIN_PANELS))+'\n\n/panel 1-30\n/pending\n/confirm REQ-ID [note]\n/reject REQ-ID [note]\n/payconfirm PAY-ID\n/payreject PAY-ID [note]\n/stats')
@router.message(Command('panel'))
async def panel(m):
    if not ok(m):return
    p=m.text.split();
    if len(p)!=2 or not p[1].isdigit() or not 1<=int(p[1])<=30:return await m.answer('/panel 1-30')
    await m.answer(f'🛠 PANEL {p[1]} — {ADMIN_PANELS[int(p[1])-1]}\nThis panel is protected by admin authorization and approval workflows.')
@router.message(Command('pending'))
async def pending(m):
    if not ok(m):return
    rows=[]
    async for x in db.requests.find({'status':'pending'}).sort('created_at',-1).limit(50): rows.append(f'{x["request_id"]} | {x["kind"]} | user={x["user_id"]}')
    await m.answer('⏳ PENDING\n\n'+('\n'.join(rows) or 'None'))
@router.message(Command('confirm','reject'))
async def decision(m):
    if not ok(m):return
    p=m.text.split(maxsplit=2); status='confirmed' if p[0]=='/confirm' else 'rejected'
    if len(p)<2:return await m.answer(f'{p[0]} REQ-ID [note]')
    good=await decide(p[1],m.from_user.id,status,p[2] if len(p)>2 else '')
    await m.answer(('✅ CONFIRMED' if status=='confirmed' else '❌ REJECTED') if good else 'Not found/already processed.')
@router.message(Command('payconfirm','payreject'))
async def paydecision(m):
    if not ok(m):return
    p=m.text.split(maxsplit=2); status='confirmed' if p[0]=='/payconfirm' else 'rejected'
    if len(p)<2:return
    good=await set_payment(p[1],m.from_user.id,status,p[2] if len(p)>2 else '')
    await m.answer('✅ PAYMENT CONFIRMED' if status=='confirmed' and good else '❌ PAYMENT REJECTED' if status=='rejected' and good else 'Not found/already processed.')
@router.message(Command('stats'))
async def stats(m):
    if not ok(m):return
    a=[('Users','users'),('Requests','requests'),('Payments','payments'),('Audit','audit_logs')]
    out=[]
    for label,col in a: out.append(f'{label}: {await db[col].count_documents({})}')
    out.append(f'Pending requests: {await db.requests.count_documents({"status":"pending"})}')
    await m.answer('📊 DASHBOARD\n'+'\n'.join(out))
