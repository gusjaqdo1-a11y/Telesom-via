from aiogram import Router
from aiogram.filters import Command,CommandStart
from aiogram.types import Message
from db import db
from core.utils import ensure_user,get_user
from core.i18n import t
from core.constants import SERVICES,PAYMENTS
from core.approval import create_request
from core.payments import create_payment
router=Router()
async def lg(uid): return (await get_user(uid) or {}).get('language','en')
@router.message(CommandStart())
async def start(m): await ensure_user(m.from_user); await m.answer(t(await lg(m.from_user.id),'welcome'))
@router.message(Command('help'))
async def help_(m): await ensure_user(m.from_user); await m.answer(t(await lg(m.from_user.id),'help'))
@router.message(Command('lang','language'))
async def language(m):
    p=m.text.split(); code=p[1].lower() if len(p)>1 else ''
    if code not in ('en','so','ar'): return await m.answer('/lang en\n/lang so\n/lang ar')
    await db.users.update_one({'telegram_id':m.from_user.id},{'$set':{'language':code}},upsert=True); await m.answer(t(code,'saved'))
@router.message(Command('services'))
async def services(m): await m.answer('\n'.join(f'/{k} - {v}' for k,v in SERVICES.items()))
@router.message(Command(*list(SERVICES.keys())))
async def service(m):
    await ensure_user(m.from_user); rid=await create_request(m.text.split()[0][1:],m.from_user.id,{'command':m.text}); await m.answer(t(await lg(m.from_user.id),'created',id=rid))
@router.message(Command('order'))
async def order(m):
    p=m.text.split(maxsplit=2)
    if len(p)<3:return await m.answer('/order <service> <details>')
    rid=await create_request('order',m.from_user.id,{'service':p[1],'details':p[2]}); await m.answer(t(await lg(m.from_user.id),'created',id=rid))
@router.message(Command('pay'))
async def pay(m):
    p=m.text.split(maxsplit=3)
    if len(p)<3:return await m.answer('/pay <order_id> <Golis|Telesom|BNB|USDT-BEP20> [reference]')
    if p[2] not in PAYMENTS:return await m.answer('Methods: Golis, Telesom, BNB, USDT-BEP20')
    pid=await create_payment(m.from_user.id,p[1],p[2],0,p[3] if len(p)>3 else ''); await m.answer(f'💳 {pid}\nMethod: {p[2]}\nDestination: {PAYMENTS[p[2]]}\n⏳ Pending admin confirmation.')
@router.message(Command('orders','payments','wallet','referral','profile','contact'))
async def account(m):
    u=await get_user(m.from_user.id); cmd=m.text.split()[0][1:]
    if cmd=='profile': return await m.answer(f'ID: {u["telegram_id"]}\nUsername: @{u.get("username") or "none"}\nLanguage: {u.get("language","en")}\nStatus: {u.get("status","active")}')
    if cmd=='wallet': return await m.answer(f'Available: ${u.get("wallet",{}).get("available",0):.2f}\nPending: ${u.get("wallet",{}).get("pending",0):.2f}')
    if cmd=='contact': return await m.answer('/support <message>')
    if cmd=='referral': return await m.answer(f'Referral ID: {m.from_user.id}')
    col='requests' if cmd=='orders' else 'payments'; rows=[]
    async for x in db[col].find({'user_id':m.from_user.id}).sort('created_at',-1).limit(20): rows.append(f'{x.get("request_id",x.get("payment_id"))} | {x.get("status")}')
    await m.answer('\n'.join(rows) or 'None')
@router.message(Command('support'))
async def support(m):
    text=m.text.partition(' ')[2].strip()
    if not text:return await m.answer('/support <message>')
    rid=await create_request('support',m.from_user.id,{'message':text}); await m.answer(f'🎧 Ticket {rid} created. Awaiting admin.')
