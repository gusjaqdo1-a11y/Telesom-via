import os
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiohttp import web

load_dotenv()
BOT_TOKEN=os.getenv('BOT_TOKEN','').strip()
MONGO_URI=os.getenv('MONGO_URI','').strip()
ADMIN_ID_RAW=os.getenv('ADMIN_ID','0').strip()
PORT=int(os.getenv('PORT','10000') or '10000')
DB_NAME=os.getenv('DB_NAME','telesombot')
if not BOT_TOKEN: raise RuntimeError('BOT_TOKEN is missing')
if not MONGO_URI: raise RuntimeError('MONGO_URI is missing')
try: MAIN_ADMIN=int(ADMIN_ID_RAW)
except ValueError: raise RuntimeError('ADMIN_ID must be numeric')
if MAIN_ADMIN<=0: raise RuntimeError('ADMIN_ID is missing or invalid')

logging.basicConfig(level=logging.INFO,format='%(asctime)s | %(levelname)s | %(message)s')
log=logging.getLogger('telesombot')
client=AsyncIOMotorClient(MONGO_URI,serverSelectionTimeoutMS=10000)
db=client[DB_NAME]
bot=Bot(BOT_TOKEN); dp=Dispatcher(); router=Router(); admin_router=Router(); dp.include_router(router); dp.include_router(admin_router)

class UserFlow(StatesGroup):
    order_details=State(); payment_reference=State(); support=State(); admin_input=State(); broadcast=State(); search_user=State(); number_add=State(); catalog_add=State()

def now(): return datetime.now(timezone.utc)
def uid(p): return f'{p}-{uuid.uuid4().hex[:10].upper()}'
def money(v):
    try:return round(float(v),2)
    except:return 0.0
def safe(v,d='-'):
    s=str(v or '').strip(); return s if s else d

SERVICES={
 'numbers':'📱 Numbers','vip':'💎 VIP Numbers','virtual':'🌐 Virtual Numbers','esim':'📲 eSIM','sim':'💳 Physical SIM',
 'data':'📡 Data','voice':'📞 Voice','sms':'💬 SMS','recharge':'🔋 Recharge','fiber':'🌐 Fiber / Internet',
 'zaad':'💰 ZAAD Services','business':'🏢 Business','corporate':'🏢 Corporate','iot':'🔌 IoT','cloud':'☁️ Cloud','offers':'🎁 Offers','membership':'⭐ Memberships'}
PANELS=['Dashboard','Customers','Numbers','VIP Numbers','Virtual Numbers','eSIM','Physical SIM','Data','Voice','SMS','Recharge','Wallets','Payments','Orders','Refunds','Offers','Promo Codes','Referrals','Memberships','Support','Broadcast','Notifications','Business','Corporate','Inventory','Analytics','Staff & Permissions','Security','Audit Logs','System Settings']
PAYMENT_DEFAULTS={'Golis':'*883*0907868526*$#','Telesom':'*880*0907868526*$#','BNB':'0x1f12ffDc93E49eff0c78672Ab6abA62410c05a32','USDT-BEP20':'0x6AC864773259fa5175251829cb0E93ffb4cE6feC'}
PERMISSIONS={'admin','customers','numbers','payments','orders','wallets','refunds','offers','promos','broadcast','support','analytics','staff','settings','security'}

async def get_user(tg): return await db.users.find_one({'telegram_id':int(tg)})
async def get_setting(k,d=None):
    x=await db.settings.find_one({'_id':k}); return x.get('value',d) if x else d
async def set_setting(k,v): await db.settings.update_one({'_id':k},{'$set':{'value':v}},upsert=True)
async def audit(actor,action,target=None,data=None): await db.audit_logs.insert_one({'actor':int(actor),'action':action,'target':target,'data':data or {},'created_at':now()})
async def is_admin(tg):
    if int(tg)==MAIN_ADMIN:return True
    x=await db.staff.find_one({'telegram_id':int(tg),'active':True}); return bool(x and 'admin' in x.get('permissions',[]))
async def has_permission(tg,p):
    if int(tg)==MAIN_ADMIN:return True
    x=await db.staff.find_one({'telegram_id':int(tg),'active':True}); return bool(x and (p in x.get('permissions',[]) or 'admin' in x.get('permissions',[])))
async def notify_admin(text,markup=None):
    try: await bot.send_message(MAIN_ADMIN,text,reply_markup=markup)
    except Exception as e: log.warning('admin notification: %r',e)

async def ensure_user(user):
    old=await get_user(user.id)
    update={'$set':{'username':user.username,'first_name':user.first_name,'last_name':user.last_name,'updated_at':now()},'$setOnInsert':{'telegram_id':int(user.id),'language':'en','status':'active','wallet':{'available':0.0,'pending':0.0},'total_deposited':0.0,'total_spent':0.0,'referrals':0,'created_at':now()}}
    r=await db.users.update_one({'telegram_id':int(user.id)},update,upsert=True)
    if old is None and r.upserted_id is not None:
        await audit(user.id,'user_registered',str(user.id),{'username':user.username})
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='👤 CUSTOMER',callback_data=f'customer:{user.id}'),InlineKeyboardButton(text='🚫 BAN',callback_data=f'ban:{user.id}')]])
        await notify_admin('🆕 <b>NEW CUSTOMER</b>\n\n👤 Name: '+safe(user.full_name)+'\n🆔 Telegram ID: <code>'+str(user.id)+'</code>\n🔗 Username: @'+safe(user.username,'none'),kb)

async def lang(tg):
    u=await get_user(tg); return (u or {}).get('language','en')

def main_kb(admin=False):
    rows=[['📱 Numbers','💎 VIP Numbers','🌐 Virtual Numbers'],['📲 eSIM','💳 Physical SIM','📡 Data'],['📞 Voice','💬 SMS','🔋 Recharge'],['💰 Wallet','🛒 My Orders','💵 Payments'],['🎁 Offers','👥 Referral','🆘 Customer Support'],['👤 My Profile','🌐 Language']]
    if admin: rows.append(['🛠️ ADMIN PANEL TELESOM'])
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in r] for r in rows],resize_keyboard=True,is_persistent=True)

def admin_kb():
    rows=[]
    for i in range(0,30,2): rows.append([KeyboardButton(text=f'{i+1}. {PANELS[i]}'),KeyboardButton(text=f'{i+2}. {PANELS[i+1]}')])
    rows.append([KeyboardButton(text='⏳ Pending Approvals'),KeyboardButton(text='🏠 Customer Home')])
    return ReplyKeyboardMarkup(keyboard=rows,resize_keyboard=True,is_persistent=True)

def approve_kb(kind,ident):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ CONFIRM',callback_data=f'approve:{kind}:{ident}'),InlineKeyboardButton(text='❌ REJECT',callback_data=f'reject:{kind}:{ident}')],[InlineKeyboardButton(text='📄 DETAILS',callback_data=f'details:{kind}:{ident}'),InlineKeyboardButton(text='💬 CONTACT USER',callback_data=f'contact:{kind}:{ident}')]])

def back_kb(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='⬅️ Back',callback_data='home')]])

async def create_order(uid_,service,details,amount=0):
    oid=uid('ORD'); rid=uid('REQ')
    await db.orders.insert_one({'order_id':oid,'user_id':int(uid_),'service':service,'details':details,'amount':money(amount),'status':'pending','created_at':now(),'updated_at':now()})
    await db.requests.insert_one({'request_id':rid,'kind':'order','user_id':int(uid_),'order_id':oid,'data':{'service':service,'details':details,'amount':money(amount)},'status':'pending','created_at':now(),'updated_at':now()})
    return oid,rid

async def send_catalog(m,category):
    if category in ('numbers','vip','virtual'):
        cat={'numbers':'regular','vip':'vip','virtual':'virtual'}[category]
        rows=[]
        async for x in db.numbers.find({'category':cat,'status':'available'}).sort('price',1).limit(30):
            rows.append([InlineKeyboardButton(text=f"{x.get('number','?')} — ${money(x.get('price')):.2f}",callback_data=f'number:{x.get("_id")}')])
        if not rows:return await m.answer('📭 No available items currently. Admin can add inventory from the panel.')
        return await m.answer(f'<b>{SERVICES[category]}</b>\n\nSelect an available item:',reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    if category=='offers':
        rows=[]
        async for x in db.offers.find({'enabled':True}).sort('created_at',-1).limit(20): rows.append(f"🎁 <b>{safe(x.get('title'))}</b>\n{safe(x.get('text'))}")
        return await m.answer('\n\n'.join(rows) or 'No offers available.')
    if not await get_setting('orders_open',True): return await m.answer('🔒 Ordering is currently closed.')
    prices=await db.catalog.find({'service':category,'enabled':True}).sort('price',1).to_list(30)
    if prices:
        rows=[[InlineKeyboardButton(text=f"{safe(x.get('title'))} — ${money(x.get('price')):.2f}",callback_data=f"catalog:{x['_id']}")] for x in prices]
        return await m.answer(f'<b>{SERVICES.get(category,category)}</b>\n\nChoose a package:',reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await m.answer(f'📋 <b>{SERVICES.get(category,category)}</b>\n\nTap <b>📝 REQUEST SERVICE</b> to send your request.',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='📝 REQUEST SERVICE',callback_data=f'request:{category}')]]))

@router.message(CommandStart())
async def start(m:Message,state:FSMContext):
    await state.clear(); await ensure_user(m.from_user)
    admin=await is_admin(m.from_user.id)
    await m.answer('👋 <b>Welcome to Telesombot</b>\n\nAll services, orders and payments are available through the buttons below.\n\n💳 Orders remain pending until an admin confirms the payment/request.',reply_markup=main_kb(admin))

# Customer buttons
@router.message(F.text=='🏠 Customer Home')
async def customer_home(m:Message,state:FSMContext): await state.clear(); await m.answer('🏠 <b>Customer Home</b>',reply_markup=main_kb(await is_admin(m.from_user.id)))
@router.message(F.text=='🛠️ ADMIN PANEL TELESOM')
async def admin_home(m:Message):
    if not await is_admin(m.from_user.id): return await m.answer('❌ Not authorized.')
    await m.answer('🛡️ <b>TELESOM ADMIN PANEL</b>\n\nChoose a management panel:',reply_markup=admin_kb())
@router.message(F.text.in_({'📱 Numbers','💎 VIP Numbers','🌐 Virtual Numbers','📲 eSIM','💳 Physical SIM','📡 Data','📞 Voice','💬 SMS','🔋 Recharge','🎁 Offers'}))
async def service_button(m:Message):
    mapping={'📱 Numbers':'numbers','💎 VIP Numbers':'vip','🌐 Virtual Numbers':'virtual','📲 eSIM':'esim','💳 Physical SIM':'sim','📡 Data':'data','📞 Voice':'voice','💬 SMS':'sms','🔋 Recharge':'recharge','🎁 Offers':'offers'}
    await send_catalog(m,mapping[m.text])

@router.callback_query(F.data.startswith('number:'))
async def number_select(c:CallbackQuery):
    try: x=await db.numbers.find_one({'_id':__import__('bson').ObjectId(c.data.split(':',1)[1])})
    except: x=None
    if not x: return await c.answer('Item unavailable',show_alert=True)
    await c.message.answer(f"📱 <b>{safe(x.get('number'))}</b>\n\nCategory: {safe(x.get('category'))}\nPrice: <b>${money(x.get('price')):.2f}</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🛒 ORDER NOW',callback_data=f'order_number:{x["_id"]}')],[InlineKeyboardButton(text='⬅️ Back',callback_data='home')]])); await c.answer()
@router.callback_query(F.data.startswith('order_number:'))
async def order_number(c:CallbackQuery,state:FSMContext):
    try:x=await db.numbers.find_one({'_id':__import__('bson').ObjectId(c.data.split(':',1)[1]),'status':'available'})
    except:x=None
    if not x:return await c.answer('Unavailable',show_alert=True)
    oid,rid=await create_order(c.from_user.id,x.get('category','number'),f"Number: {x.get('number')}",x.get('price',0))
    await db.orders.update_one({'order_id':oid},{'$set':{'number_id':str(x['_id']),'amount':money(x.get('price'))}})
    await notify_admin(f'🛒 <b>NEW ORDER</b>\n\nOrder: <code>{oid}</code>\nUser: <code>{c.from_user.id}</code>\nService: {safe(x.get("category"))}\nNumber: <code>{safe(x.get("number"))}</code>\nAmount: <b>${money(x.get("price")):.2f}</b>',approve_kb('request',rid))
    await c.message.answer(f'✅ Order <code>{oid}</code> created.\n💰 Amount: <b>${money(x.get("price")):.2f}</b>\n\nNow open <b>💵 Payments</b> and submit your payment.\n⏳ Admin will confirm it after checking.'); await c.answer()

@router.callback_query(F.data.startswith('catalog:'))
async def catalog_select(c:CallbackQuery):
    try:x=await db.catalog.find_one({'_id':__import__('bson').ObjectId(c.data.split(':',1)[1]),'enabled':True})
    except:x=None
    if not x:return await c.answer('Package unavailable',show_alert=True)
    oid,rid=await create_order(c.from_user.id,x.get('service','service'),x.get('title','Package'),x.get('price',0))
    await notify_admin(f'🛒 <b>NEW ORDER</b>\n\nOrder: <code>{oid}</code>\nUser: <code>{c.from_user.id}</code>\nService: {safe(x.get("service"))}\nPackage: {safe(x.get("title"))}\nAmount: <b>${money(x.get("price")):.2f}</b>',approve_kb('request',rid))
    await c.message.answer(f'✅ Order <code>{oid}</code> created.\n💰 Amount: <b>${money(x.get("price")):.2f}</b>\n\nOpen <b>💵 Payments</b> to submit payment.'); await c.answer()
@router.callback_query(F.data.startswith('request:'))
async def request_service(c:CallbackQuery,state:FSMContext):
    service=c.data.split(':',1)[1]; await state.update_data(service=service); await state.set_state(UserFlow.order_details); await c.message.answer(f'📝 Send the details for <b>{SERVICES.get(service,service)}</b>.\n\nExample: package, amount, phone number or any required information.'); await c.answer()
@router.message(UserFlow.order_details)
async def order_details(m:Message,state:FSMContext):
    d=await state.get_data(); oid,rid=await create_order(m.from_user.id,d.get('service'),m.text,0); await state.clear()
    await notify_admin(f'🛒 <b>NEW SERVICE REQUEST</b>\n\nRequest: <code>{rid}</code>\nOrder: <code>{oid}</code>\nUser: <code>{m.from_user.id}</code>\nService: {safe(d.get("service"))}\nDetails: {safe(m.text)}',approve_kb('request',rid))
    await m.answer(f'✅ Request <code>{rid}</code> submitted.\n⏳ Waiting for admin confirmation.',reply_markup=main_kb(await is_admin(m.from_user.id)))

@router.message(F.text=='💵 Payments')
async def payments(m:Message):
    methods=[]
    async for x in db.payment_methods.find({'enabled':True}).sort('name',1): methods.append([InlineKeyboardButton(text=f'💳 {x["name"]}',callback_data=f'paymethod:{x["name"]}')])
    await m.answer('💵 <b>Payments</b>\n\nSelect a payment method. After you send payment, the transaction stays <b>PENDING</b> until admin verifies it.',reply_markup=InlineKeyboardMarkup(inline_keyboard=methods or [[InlineKeyboardButton(text='No payment methods',callback_data='noop')]]))
@router.callback_query(F.data.startswith('paymethod:'))
async def pay_method(c:CallbackQuery,state:FSMContext):
    method=c.data.split(':',1)[1]; x=await db.payment_methods.find_one({'name':method,'enabled':True});
    if not x:return await c.answer('Unavailable',show_alert=True)
    await state.update_data(method=method); await state.set_state(UserFlow.payment_reference)
    await c.message.answer(f'💳 <b>{method}</b>\n\n📍 Send payment to:\n<code>{x["destination"]}</code>\n\nNow send: <b>ORDER ID + AMOUNT + PAYMENT REFERENCE</b>\nExample: <code>ORD-ABC123 10 REF123</code>')
    await c.answer()
@router.message(UserFlow.payment_reference)
async def payment_submit(m:Message,state:FSMContext):
    p=m.text.split(maxsplit=2); d=await state.get_data()
    if len(p)<2:return await m.answer('❌ Format: ORDER_ID AMOUNT [REFERENCE]')
    oid=p[0]; amount=money(p[1]); ref=p[2] if len(p)>2 else ''
    order=await db.orders.find_one({'order_id':oid,'user_id':m.from_user.id})
    if not order:return await m.answer('❌ Order not found. Check My Orders.')
    if amount<=0:return await m.answer('❌ Invalid amount.')
    pid=uid('PAY'); await db.payments.insert_one({'payment_id':pid,'user_id':m.from_user.id,'order_id':oid,'method':d.get('method'),'amount':amount,'reference':ref,'status':'pending','created_at':now(),'updated_at':now()})
    await db.users.update_one({'telegram_id':m.from_user.id},{'$inc':{'wallet.pending':amount}}); await state.clear()
    await notify_admin(f'💳 <b>NEW PAYMENT</b>\n\nPayment: <code>{pid}</code>\nOrder: <code>{oid}</code>\nUser: <code>{m.from_user.id}</code>\nAmount: <b>${amount:.2f}</b>\nMethod: <b>{d.get("method")}</b>\nReference: <code>{safe(ref)}</code>',approve_kb('payment',pid))
    await m.answer(f'✅ Payment <code>{pid}</code> submitted.\n⏳ Status: <b>PENDING ADMIN CONFIRMATION</b>.',reply_markup=main_kb(await is_admin(m.from_user.id)))

@router.message(F.text=='🛒 My Orders')
async def orders(m:Message):
    rows=[]
    async for x in db.orders.find({'user_id':m.from_user.id}).sort('created_at',-1).limit(20): rows.append(f"📦 <code>{x['order_id']}</code> | {safe(x.get('service'))} | <b>{safe(x.get('status'))}</b> | ${money(x.get('amount')):.2f}")
    await m.answer('🛒 <b>My Orders</b>\n\n'+('\n'.join(rows) or 'No orders yet.'))
@router.message(F.text=='💰 Wallet')
async def wallet(m:Message):
    u=await get_user(m.from_user.id); w=(u or {}).get('wallet',{})
    await m.answer(f'💰 <b>Wallet</b>\n\nAvailable: <b>${money(w.get("available")):.2f}</b>\nPending: <b>${money(w.get("pending")):.2f}</b>\nTotal deposited: ${money((u or {}).get("total_deposited")):.2f}\nTotal spent: ${money((u or {}).get("total_spent")):.2f}')
@router.message(F.text=='👤 My Profile')
async def profile(m:Message):
    u=await get_user(m.from_user.id); await m.answer(f'👤 <b>My Profile</b>\n\nID: <code>{m.from_user.id}</code>\nName: {safe(m.from_user.full_name)}\nUsername: @{safe(m.from_user.username,"none")}\nLanguage: {safe((u or {}).get("language"),"en")}\nStatus: {safe((u or {}).get("status"),"active")}')
@router.message(F.text=='👥 Referral')
async def referral(m:Message):
    u=await get_user(m.from_user.id); await m.answer(f'👥 <b>Referral</b>\n\nYour referral code: <code>{m.from_user.id}</code>\nReferrals: <b>{int((u or {}).get("referrals",0))}</b>')
@router.message(F.text=='🌐 Language')
async def language(m:Message):
    await m.answer('🌐 <b>Select Language</b>',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🇬🇧 English',callback_data='lang:en'),InlineKeyboardButton(text='🇸🇴 Somali',callback_data='lang:so'),InlineKeyboardButton(text='🇸🇦 العربية',callback_data='lang:ar')]]))
@router.callback_query(F.data.startswith('lang:'))
async def setlang(c:CallbackQuery):
    code=c.data.split(':')[1]; await db.users.update_one({'telegram_id':c.from_user.id},{'$set':{'language':code}}); await c.message.answer({'en':'✅ English selected.','so':'✅ Somali ayaa la doortay.','ar':'✅ تم اختيار العربية.'}[code],reply_markup=main_kb(await is_admin(c.from_user.id))); await c.answer()
@router.message(F.text=='🆘 Customer Support')
async def support(m:Message,state:FSMContext):
    if not await get_setting('support_open',True):return await m.answer('🔒 Support is currently closed.')
    await state.set_state(UserFlow.support); await m.answer('🆘 Send your support message. It will be delivered to admin for handling.')
@router.message(UserFlow.support)
async def support_submit(m:Message,state:FSMContext):
    tid=uid('TKT'); await db.support.insert_one({'ticket_id':tid,'user_id':m.from_user.id,'message':m.text,'status':'open','created_at':now()}); await state.clear(); await notify_admin(f'🆘 <b>NEW SUPPORT TICKET</b>\n\nTicket: <code>{tid}</code>\nUser: <code>{m.from_user.id}</code>\nMessage: {m.text}',approve_kb('support',tid)); await m.answer(f'✅ Ticket <code>{tid}</code> sent to support.',reply_markup=main_kb(await is_admin(m.from_user.id)))

# Admin panels
async def panel_text(n):
    counts={1:await db.users.count_documents({}),2:await db.users.count_documents({}),3:await db.numbers.count_documents({'category':'regular'}),4:await db.numbers.count_documents({'category':'vip'}),5:await db.numbers.count_documents({'category':'virtual'}),6:await db.catalog.count_documents({'service':'esim'}),7:await db.catalog.count_documents({'service':'sim'}),8:await db.catalog.count_documents({'service':'data'}),9:await db.catalog.count_documents({'service':'voice'}),10:await db.catalog.count_documents({'service':'sms'}),11:await db.catalog.count_documents({'service':'recharge'}),12:await db.wallet_ledger.count_documents({}),13:await db.payments.count_documents({}),14:await db.orders.count_documents({}),15:await db.requests.count_documents({'kind':'refund'}),16:await db.offers.count_documents({}),17:await db.promos.count_documents({}),18:await db.referrals.count_documents({}),19:await db.memberships.count_documents({}),20:await db.support.count_documents({}),21:await db.notifications.count_documents({'type':'broadcast'}),22:await db.notifications.count_documents({}),23:await db.requests.count_documents({'kind':'business'}),24:await db.requests.count_documents({'kind':'corporate'}),25:await db.numbers.count_documents({}),26:await db.audit_logs.count_documents({}),27:await db.staff.count_documents({}),28:await db.security_events.count_documents({}),29:await db.audit_logs.count_documents({}),30:await db.settings.count_documents({})}
    return f'🛠️ <b>{n}. {PANELS[n-1]}</b>\n\nRecords: <b>{counts.get(n,0)}</b>\n\nChoose an action below.'

def panel_actions(n):
    acts={1:[('📊 Refresh Dashboard','p:1'),('⏳ Pending Approvals','pending')],2:[('👥 List Customers','users'),('🔎 Find Customer','finduser')],3:[('➕ Add Number','addnum:regular'),('📋 Inventory','inventory:regular')],4:[('➕ Add VIP Number','addnum:vip'),('📋 VIP Inventory','inventory:vip')],5:[('➕ Add Virtual Number','addnum:virtual'),('📋 Inventory','inventory:virtual')],16:[('➕ Add Offer','addoffer'),('🎁 Active Offers','offers')],17:[('➕ Add Promo','addpromo'),('🎟 Promo List','promos')],20:[('🎧 Open Tickets','tickets')],21:[('📢 Broadcast','broadcast')],25:[('📦 Inventory','inventory:all')],26:[('📈 Analytics','analytics')],27:[('➕ Add Staff','addstaff'),('👨‍💼 Staff List','staff')],28:[('🔐 Security','security')],29:[('📋 Audit Logs','audit')],30:[('⚙️ Services ON/OFF','settings_services'),('💳 Payment Methods','settings_payments')]}
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=a,callback_data=cb) for a,cb in acts.get(n,[('📋 View Records',f'records:{n}')])]])

@router.message(F.text.regexp(r'^([1-9]|[12][0-9]|30)\. '))
async def admin_panel_button(m:Message,state:FSMContext):
    if not await is_admin(m.from_user.id): return
    n=int(m.text.split('.',1)[0]); await m.answer(await panel_text(n),reply_markup=panel_actions(n))

@router.message(F.text=='⏳ Pending Approvals')
async def pending(m:Message):
    if not await has_permission(m.from_user.id,'admin'):return
    found=0
    async for r in db.requests.find({'status':'pending'}).sort('created_at',-1).limit(15):
        found+=1; await m.answer(f'⏳ <b>REQUEST</b> <code>{r["request_id"]}</code>\nUser: <code>{r["user_id"]}</code>\nKind: {safe(r.get("kind"))}\nDetails: <code>{safe(r.get("data"))}</code>',reply_markup=approve_kb('request',r['request_id']))
    async for p in db.payments.find({'status':'pending'}).sort('created_at',-1).limit(15):
        found+=1; await m.answer(f'💳 <b>PAYMENT</b> <code>{p["payment_id"]}</code>\nUser: <code>{p["user_id"]}</code>\nOrder: <code>{p.get("order_id")}</code>\nAmount: <b>${money(p.get("amount")):.2f}</b>\nMethod: {safe(p.get("method"))}\nReference: <code>{safe(p.get("reference"))}</code>',reply_markup=approve_kb('payment',p['payment_id']))
    if not found: await m.answer('✅ No pending approvals.')

@router.callback_query(F.data.startswith('p:'))
async def panel_callback(c:CallbackQuery):
    n=int(c.data.split(':')[1]); await c.message.answer(await panel_text(n),reply_markup=panel_actions(n)); await c.answer()

# Admin action callbacks/input
@router.callback_query(F.data.startswith('approve:'))
async def approve(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'admin'):return await c.answer('Not authorized',show_alert=True)
    _,kind,ident=c.data.split(':',2)
    if kind=='payment':
        row=await db.payments.find_one_and_update({'payment_id':ident,'status':'pending'},{'$set':{'status':'confirmed','confirmed_by':c.from_user.id,'updated_at':now()}},return_document=__import__('pymongo').ReturnDocument.AFTER)
        if row:
            await db.users.update_one({'telegram_id':row['user_id']},{'$inc':{'wallet.pending':-money(row['amount']),'wallet.available':money(row['amount']),'total_deposited':money(row['amount'])}})
            await bot.send_message(row['user_id'],f'✅ Payment <code>{ident}</code> confirmed by admin.\n💰 ${money(row["amount"]):.2f} added to your available balance.')
    else:
        row=await db.requests.find_one_and_update({'request_id':ident,'status':'pending'},{'$set':{'status':'confirmed','confirmed_by':c.from_user.id,'updated_at':now()}},return_document=__import__('pymongo').ReturnDocument.AFTER)
        if row: await db.orders.update_one({'order_id':row.get('order_id')},{'$set':{'status':'confirmed','updated_at':now()}}); await bot.send_message(row['user_id'],f'✅ Request <code>{ident}</code> confirmed. Your order is now being processed.')
    if row: await audit(c.from_user.id,'approved',ident,{'kind':kind}); await c.message.edit_reply_markup(reply_markup=None); await c.answer('Confirmed')
    else: await c.answer('Already processed / not found',show_alert=True)
@router.callback_query(F.data.startswith('reject:'))
async def reject(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'admin'):return await c.answer('Not authorized',show_alert=True)
    _,kind,ident=c.data.split(':',2); col=db.payments if kind=='payment' else db.requests; key='payment_id' if kind=='payment' else 'request_id'
    row=await col.find_one_and_update({key:ident,'status':'pending'},{'$set':{'status':'rejected','rejected_by':c.from_user.id,'updated_at':now()}},return_document=__import__('pymongo').ReturnDocument.AFTER)
    if row:
        if kind=='payment': await db.users.update_one({'telegram_id':row['user_id']},{'$inc':{'wallet.pending':-money(row['amount'])}})
        await bot.send_message(row['user_id'],f'❌ {kind.title()} <code>{ident}</code> rejected by admin.'); await audit(c.from_user.id,'rejected',ident,{'kind':kind}); await c.message.edit_reply_markup(reply_markup=None); await c.answer('Rejected')
    else: await c.answer('Already processed / not found',show_alert=True)
@router.callback_query(F.data.startswith('details:'))
async def details(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'admin'):return await c.answer('Not authorized',show_alert=True)
    _,kind,ident=c.data.split(':',2); row=await (db.payments.find_one({'payment_id':ident}) if kind=='payment' else db.support.find_one({'ticket_id':ident}) if kind=='support' else db.requests.find_one({'request_id':ident}));
    if row: await c.message.answer('📄 <b>DETAILS</b>\n\n<code>'+safe(row)+'</code>'); await c.answer()
    else: await c.answer('Not found',show_alert=True)
@router.callback_query(F.data.startswith('contact:'))
async def contact(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'support'):return await c.answer('Not authorized',show_alert=True)
    _,kind,ident=c.data.split(':',2); row=await (db.payments.find_one({'payment_id':ident}) if kind=='payment' else db.support.find_one({'ticket_id':ident}) if kind=='support' else db.requests.find_one({'request_id':ident}));
    if row: await c.message.answer(f'💬 User Telegram ID: <code>{row.get("user_id")}</code>\nOpen the user profile in Telegram to contact them.'); await c.answer()
    else: await c.answer('Not found',show_alert=True)

@router.callback_query(F.data=='home')
async def home(c:CallbackQuery): await c.message.answer('🏠 Customer Home',reply_markup=main_kb(await is_admin(c.from_user.id))); await c.answer()
@router.callback_query(F.data.startswith('customer:'))
async def customer(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'customers'):return await c.answer('Not authorized',show_alert=True)
    tid=int(c.data.split(':')[1]); u=await get_user(tid); w=(u or {}).get('wallet',{}); await c.message.answer(f'👤 <b>Customer</b>\nID: <code>{tid}</code>\nUsername: @{safe((u or {}).get("username"),"none")}\nStatus: {safe((u or {}).get("status"))}\nAvailable: ${money(w.get("available")):.2f}\nPending: ${money(w.get("pending")):.2f}\nReferrals: {int((u or {}).get("referrals",0))}'); await c.answer()
@router.callback_query(F.data.startswith('ban:'))
async def ban(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'security'):return await c.answer('Not authorized',show_alert=True)
    tid=int(c.data.split(':')[1]);
    if tid==MAIN_ADMIN:return await c.answer('Main admin protected',show_alert=True)
    await db.users.update_one({'telegram_id':tid},{'$set':{'status':'banned'}}); await audit(c.from_user.id,'user_banned',str(tid)); await c.answer('Banned')

@router.callback_query(F.data=='addnum:regular')
@router.callback_query(F.data=='addnum:vip')
@router.callback_query(F.data=='addnum:virtual')
async def addnum(c:CallbackQuery,state:FSMContext):
    if not await has_permission(c.from_user.id,'numbers'):return await c.answer('Not authorized',show_alert=True)
    cat=c.data.split(':')[1]; await state.update_data(input_kind='number',category=cat); await state.set_state(UserFlow.number_add); await c.message.answer(f'➕ Add {cat} number\n\nSend: <code>NUMBER PRICE</code>\nExample: <code>25263xxxxxx 25</code>'); await c.answer()
@router.message(UserFlow.number_add)
async def number_add(m:Message,state:FSMContext):
    if not await has_permission(m.from_user.id,'numbers'):return
    p=m.text.split(); d=await state.get_data()
    if len(p)<2:return await m.answer('Format: NUMBER PRICE')
    await db.numbers.update_one({'number':p[0]},{'$set':{'number':p[0],'price':money(p[1]),'category':d.get('category'),'status':'available','updated_at':now()},'$setOnInsert':{'created_at':now()}},upsert=True); await audit(m.from_user.id,'number_upsert',p[0],{'category':d.get('category'),'price':money(p[1])}); await state.clear(); await m.answer('✅ Number added to inventory.',reply_markup=admin_kb())

@router.callback_query(F.data=='addoffer')
async def addoffer(c:CallbackQuery,state:FSMContext):
    if not await has_permission(c.from_user.id,'offers'):return await c.answer('Not authorized',show_alert=True)
    await state.set_state(UserFlow.catalog_add); await state.update_data(input_kind='offer'); await c.message.answer('➕ Send offer as: <code>TITLE | DESCRIPTION</code>'); await c.answer()
@router.message(UserFlow.catalog_add)
async def catalog_input(m:Message,state:FSMContext):
    d=await state.get_data(); kind=d.get('input_kind')
    if kind!='offer':return
    p=[x.strip() for x in m.text.split('|',1)]
    if len(p)<2:return await m.answer('Format: TITLE | DESCRIPTION')
    oid=uid('OFF'); await db.offers.insert_one({'offer_id':oid,'title':p[0],'text':p[1],'enabled':True,'created_at':now()}); await audit(m.from_user.id,'offer_created',oid); await state.clear(); await m.answer('✅ Offer created.',reply_markup=admin_kb())

@router.callback_query(F.data=='addstaff')
async def addstaff(c:CallbackQuery,state:FSMContext):
    if c.from_user.id!=MAIN_ADMIN:return await c.answer('Main admin only',show_alert=True)
    await state.set_state(UserFlow.admin_input); await state.update_data(input_kind='staff'); await c.message.answer('👨‍💼 Send: <code>TELEGRAM_ID permission1,permission2</code>'); await c.answer()
@router.message(UserFlow.admin_input)
async def admin_input(m:Message,state:FSMContext):
    d=await state.get_data(); kind=d.get('input_kind')
    if kind!='staff':return
    p=m.text.split(maxsplit=1)
    if len(p)<2:return await m.answer('Format: TELEGRAM_ID permission1,permission2')
    try:tid=int(p[0])
    except:return await m.answer('Invalid Telegram ID')
    perms=sorted(set(p[1].split(','))&PERMISSIONS); await db.staff.update_one({'telegram_id':tid},{'$set':{'telegram_id':tid,'permissions':perms,'active':True,'updated_at':now()},'$setOnInsert':{'created_at':now()}},upsert=True); await audit(m.from_user.id,'staff_upsert',str(tid),{'permissions':perms}); await state.clear(); await m.answer('✅ Staff saved.',reply_markup=admin_kb())

@router.callback_query(F.data=='finduser')
async def finduser(c:CallbackQuery,state:FSMContext):
    if not await has_permission(c.from_user.id,'customers'):return await c.answer('Not authorized',show_alert=True)
    await state.set_state(UserFlow.search_user); await c.message.answer('🔎 Send customer Telegram ID.'); await c.answer()
@router.message(UserFlow.search_user)
async def search_user(m:Message,state:FSMContext):
    try:tid=int(m.text.strip())
    except:return await m.answer('Invalid Telegram ID')
    u=await get_user(tid); await state.clear()
    if not u:return await m.answer('Customer not found.',reply_markup=admin_kb())
    w=u.get('wallet',{}); await m.answer(f'👤 ID: <code>{tid}</code>\nUsername: @{safe(u.get("username"),"none")}\nStatus: {safe(u.get("status"))}\nAvailable: ${money(w.get("available")):.2f}\nPending: ${money(w.get("pending")):.2f}',reply_markup=admin_kb())

@router.callback_query(F.data=='broadcast')
async def broadcast(c:CallbackQuery,state:FSMContext):
    if not await has_permission(c.from_user.id,'broadcast'):return await c.answer('Not authorized',show_alert=True)
    await state.set_state(UserFlow.broadcast); await c.message.answer('📢 Send the broadcast message. It will be sent to all active customers.'); await c.answer()
@router.message(UserFlow.broadcast)
async def broadcast_send(m:Message,state:FSMContext):
    if not await has_permission(m.from_user.id,'broadcast'):return
    count=0
    async for u in db.users.find({'status':{'$ne':'banned'}},{'telegram_id':1}):
        try:await bot.send_message(int(u['telegram_id']),m.text);count+=1
        except:pass
    await db.notifications.insert_one({'type':'broadcast','text':m.text,'count':count,'created_at':now()}); await audit(m.from_user.id,'broadcast',None,{'count':count}); await state.clear(); await m.answer(f'📢 Sent to {count} customers.',reply_markup=admin_kb())

@router.callback_query(F.data=='users')
async def users(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'customers'):return await c.answer('Not authorized',show_alert=True)
    total=await db.users.count_documents({}); active=await db.users.count_documents({'status':'active'}); banned=await db.users.count_documents({'status':'banned'}); await c.message.answer(f'👥 <b>Customers</b>\n\nTotal: {total}\nActive: {active}\nBanned: {banned}'); await c.answer()
@router.callback_query(F.data.startswith('inventory:'))
async def inventory(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'numbers'):return await c.answer('Not authorized',show_alert=True)
    cat=c.data.split(':')[1]; q={} if cat=='all' else {'category':cat}; rows=[]
    async for x in db.numbers.find(q).sort('created_at',-1).limit(30): rows.append(f"<code>{safe(x.get('number'))}</code> — ${money(x.get('price')):.2f} — {safe(x.get('category'))} — {safe(x.get('status'))}")
    await c.message.answer('📦 <b>Inventory</b>\n\n'+('\n'.join(rows) or 'No inventory.')); await c.answer()
@router.callback_query(F.data=='offers')
async def offers(c:CallbackQuery):
    rows=[]
    async for x in db.offers.find({'enabled':True}).limit(30):rows.append(f"🎁 {safe(x.get('title'))} — {safe(x.get('text'))}")
    await c.message.answer('🎁 <b>Offers</b>\n\n'+('\n'.join(rows) or 'No offers.'));await c.answer()
@router.callback_query(F.data=='promos')
async def promos(c:CallbackQuery):
    rows=[]
    async for x in db.promos.find({}).limit(30):rows.append(f"🎟 <code>{safe(x.get('code'))}</code> — {money(x.get('discount')):.2f} — {'ON' if x.get('enabled') else 'OFF'}")
    await c.message.answer('🎟 <b>Promo Codes</b>\n\n'+('\n'.join(rows) or 'No promos.'));await c.answer()
@router.callback_query(F.data=='tickets')
async def tickets(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'support'):return await c.answer('Not authorized',show_alert=True)
    async for x in db.support.find({'status':'open'}).sort('created_at',-1).limit(15): await c.message.answer(f'🎧 <b>{x["ticket_id"]}</b>\nUser: <code>{x["user_id"]}</code>\n{x.get("message","")}',reply_markup=approve_kb('support',x['ticket_id']))
    await c.answer()
@router.callback_query(F.data=='analytics')
async def analytics(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'analytics'):return await c.answer('Not authorized',show_alert=True)
    await c.message.answer(f'📈 <b>Analytics</b>\n\nCustomers: {await db.users.count_documents({})}\nOrders: {await db.orders.count_documents({})}\nPayments: {await db.payments.count_documents({})}\nNumbers: {await db.numbers.count_documents({})}\nPending requests: {await db.requests.count_documents({"status":"pending"})}\nPending payments: {await db.payments.count_documents({"status":"pending"})}');await c.answer()
@router.callback_query(F.data=='staff')
async def staff(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'staff'):return await c.answer('Not authorized',show_alert=True)
    rows=[]
    async for x in db.staff.find({}).limit(30):rows.append(f"<code>{x['telegram_id']}</code> — {', '.join(x.get('permissions',[]))} — {'ON' if x.get('active') else 'OFF'}")
    await c.message.answer('👨‍💼 <b>Staff</b>\n\n'+('\n'.join(rows) or 'No staff.'));await c.answer()
@router.callback_query(F.data=='audit')
async def audit_logs(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'settings'):return await c.answer('Not authorized',show_alert=True)
    rows=[]
    async for x in db.audit_logs.find({}).sort('created_at',-1).limit(20):rows.append(f"{safe(x.get('action'))} | actor {x.get('actor')} | {safe(x.get('target'))}")
    await c.message.answer('📋 <b>Audit Logs</b>\n\n'+('\n'.join(rows) or 'No logs.'));await c.answer()
@router.callback_query(F.data=='security')
async def security(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'security'):return await c.answer('Not authorized',show_alert=True)
    await c.message.answer('🔐 <b>Security</b>\n\nMain admin is protected. All important admin actions are logged.\nUse the customer BAN button and staff permissions from the corresponding panels.');await c.answer()
@router.callback_query(F.data=='settings_services')
async def settings_services(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'settings'):return await c.answer('Not authorized',show_alert=True)
    await c.message.answer('⚙️ <b>Service Controls</b>',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🟢 Orders ON/OFF',callback_data='toggle:orders_open')],[InlineKeyboardButton(text='💳 Payments ON/OFF',callback_data='toggle:payments_open')],[InlineKeyboardButton(text='🎧 Support ON/OFF',callback_data='toggle:support_open')]]));await c.answer()
@router.callback_query(F.data.startswith('toggle:'))
async def toggle(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'settings'):return await c.answer('Not authorized',show_alert=True)
    k=c.data.split(':')[1]; v=not await get_setting(k,True); await set_setting(k,v); await audit(c.from_user.id,'setting_toggled',k,{'value':v}); await c.answer(('ON' if v else 'OFF'),show_alert=True)

# Generic records for all remaining panels
@router.callback_query(F.data.startswith('records:'))
async def records(c:CallbackQuery):
    if not await is_admin(c.from_user.id):return await c.answer('Not authorized',show_alert=True)
    n=int(c.data.split(':')[1]); colmap={6:'catalog',7:'catalog',8:'catalog',9:'catalog',10:'catalog',11:'catalog',12:'wallet_ledger',13:'payments',14:'orders',15:'requests',18:'referrals',19:'memberships',22:'notifications',23:'requests',24:'requests'}; col=colmap.get(n)
    if not col:return await c.answer('This panel is ready for configuration through its dedicated controls.',show_alert=True)
    rows=[]
    async for x in db[col].find({}).sort('created_at',-1).limit(15):rows.append(str(x.get('request_id') or x.get('order_id') or x.get('payment_id') or x.get('_id'))+' | '+safe(x.get('status'),safe(x.get('service'))))
    await c.message.answer(f'📋 <b>{PANELS[n-1]}</b>\n\n'+('\n'.join(rows) or 'No records.'));await c.answer()

# Banned guard / free text guard
@router.message()
async def fallback(m:Message,state:FSMContext):
    u=await get_user(m.from_user.id)
    if u and u.get('status')=='banned':return await m.answer('🚫 Your account is blocked.')
    if await state.get_state(): return
    await m.answer('👇 Please use the buttons on the menu.',reply_markup=main_kb(await is_admin(m.from_user.id)))

# Database initialization: legacy-safe indexes
async def init_db():
    specs=[('users','telegram_id',True,'telegram_id_unique'),('numbers','number',True,None),('orders','order_id',True,'order_id_unique'),('payments','payment_id',True,'payment_id_unique'),('requests','request_id',True,'request_id_unique'),('support','ticket_id',True,'ticket_id_unique'),('staff','telegram_id',True,'staff_telegram_id_unique')]
    for col,field,unique,name in specs:
        try:
            info=await db[col].index_information(); compatible=False
            for old,opts in info.items():
                keys=dict(opts.get('key',[]))
                if keys=={field:1} and bool(opts.get('unique',False))==unique:
                    compatible=True; break
            if not compatible:
                kwargs={'unique':unique}
                if name: kwargs['name']=name
                await db[col].create_index([(field,1)],**kwargs)
        except Exception as e: log.warning('index %s.%s: %r',col,field,e)
    defaults={'registration_open':True,'orders_open':True,'payments_open':True,'support_open':True,'trial_days':1}
    for k,v in defaults.items():
        if await db.settings.find_one({'_id':k}) is None:await set_setting(k,v)
    for name,dest in PAYMENT_DEFAULTS.items(): await db.payment_methods.update_one({'name':name},{'$setOnInsert':{'name':name,'destination':dest,'enabled':True}},upsert=True)
    await client.admin.command('ping'); log.info('MongoDB connected')

async def health(request):return web.json_response({'status':'ok','service':'Telesombot'})
async def health_server():
    app=web.Application();app.router.add_get('/',health);app.router.add_get('/health',health);runner=web.AppRunner(app);await runner.setup();await web.TCPSite(runner,'0.0.0.0',PORT).start();return runner
async def main():
    await init_db(); await bot.delete_webhook(drop_pending_updates=False); await health_server(); log.info('Telesombot button system started; admin=%s',MAIN_ADMIN); await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
if __name__=='__main__': asyncio.run(main())
