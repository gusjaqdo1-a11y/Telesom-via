import os
import asyncio
import logging
import uuid
import re
from urllib.parse import quote
from html import escape
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
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
bot=Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)); dp=Dispatcher(); router=Router(); admin_router=Router(); dp.include_router(router); dp.include_router(admin_router)

class UserFlow(StatesGroup):
    order_details=State(); target_number=State(); payment_reference=State(); support=State(); admin_input=State(); broadcast=State(); search_user=State(); number_add=State(); catalog_add=State(); quote_amount=State()

def now(): return datetime.now(timezone.utc)
def uid(p): return f'{p}-{uuid.uuid4().hex[:10].upper()}'
def money(v):
    try:return round(float(v),2)
    except:return 0.0
def safe(v,d='-'):
    s=str(v or '').strip()
    return escape(s if s else d, quote=False)

def raw_safe(v,d='-'):
    s=str(v or '').strip()
    return s if s else d

SERVICES={
 'numbers':'📱 Numbers','vip':'💎 VIP Numbers','virtual':'🌐 Virtual Numbers','esim':'📲 eSIM','sim':'💳 Physical SIM',
 'data':'📡 Data','voice':'📞 Voice','sms':'💬 SMS','recharge':'🔋 Recharge','fiber':'🌐 Fiber / Internet',
 'zaad':'💰 ZAAD Services','business':'🏢 Business','corporate':'🏢 Corporate','iot':'🔌 IoT','cloud':'☁️ Cloud','offers':'🎁 Offers','membership':'⭐ Memberships','5g':'📶 5G'}
PANELS=['Dashboard','Customers','Numbers','VIP Numbers','Virtual Numbers','eSIM','Physical SIM','Data','Voice','SMS','Recharge','Wallets','Payments','Orders','Refunds','Offers','Promo Codes','Referrals','Memberships','Support','Broadcast','Notifications','Business','Corporate','Inventory','Analytics','Staff & Permissions','Security','Audit Logs','System Settings']
PAYMENT_DEFAULTS={'Golis':'*883*0907868526*','Telesom':'*880*0907868526*','BNB':'0x1f12ffDc93E49eff0c78672Ab6abA62410c05a32','USDT-BEP20':'0x6AC864773259fa5175251829cb0E93ffb4cE6feC'}
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
    rows=[
        ['📱 Numbers','💎 VIP Numbers','🌐 Virtual Numbers'],
        ['📲 eSIM','💳 Physical SIM','📡 Data'],
        ['📞 Voice','💬 SMS','🔋 Recharge'],
        ['📶 5G','🌐 Fiber','💰 ZAAD'],
        ['🏢 Business','🏢 Corporate','🔌 IoT'],
        ['☁️ Cloud','🎁 More Services','🎁 Offers'],
        ['💰 Wallet','🛒 My Orders','💵 Payments'],
        ['👥 Referral','🆘 Customer Support','👤 My Profile'],
        ['🌐 Language']
    ]
    if admin: rows.append(['🛠️ ADMIN PANEL TELESOM'])
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in r] for r in rows],resize_keyboard=True,is_persistent=True)

ADMIN_PANELS = (PANELS + [
    'Payment Approvals','Order Approvals','Request Approvals','Customer Wallets','Wallet Adjustments',
    'Number Pricing','Number Import','Data Pricing','Voice Pricing','SMS Pricing','Recharge Pricing',
    'eSIM Pricing','SIM Pricing','Business Pricing','Corporate Pricing','5G Pricing','Fiber Pricing',
    'Service Availability','Catalog Sync','Telesom Sync','Payment Destinations','Payment Settings',
    'Order Settings','Registration Settings','Support Settings','Broadcast History','Message Templates',
    'Customer Search','Customer Export','Orders Search','Payments Search','Refund Queue','Offer Manager',
    'Promo Manager','Referral Manager','Membership Manager','Notification Manager','Business Requests',
    'Corporate Requests','SIM Requests','eSIM Requests','Data Requests','Voice Requests','SMS Requests',
    'Recharge Requests','5G Requests','Fiber Requests','ZAAD Requests','IoT Requests','Cloud Requests',
    'Inventory Search','Inventory Import','Inventory Export','Low Stock','Unavailable Numbers',
    'Reserved Numbers','Sold Numbers','Failed Orders','Completed Orders','Cancelled Orders',
    'Revenue','Sales by Service','Sales by Day','Top Customers','Conversion Stats','Staff Manager',
    'Permissions','Security Events','Login Activity','Audit Logs','Database Stats','System Settings',
    'Service ON/OFF','Payment ON/OFF','Maintenance','Backup Info','Health Check','Refresh Website Data',
    'Refresh Number Inventory','Admin Broadcast','Customer Announcements','Danger Zone'
])[:100]

def admin_kb():
    rows=[]
    for i in range(0,len(ADMIN_PANELS),2):
        pair=[]
        for j in (i,i+1):
            if j<len(ADMIN_PANELS): pair.append(KeyboardButton(text=f'🛠 {j+1:02d}. {ADMIN_PANELS[j]}'))
        rows.append(pair)
    rows += [[KeyboardButton(text='⏳ Pending Approvals'),KeyboardButton(text='📢 BROADCAST')],[KeyboardButton(text='🏠 Customer Home')]]
    return ReplyKeyboardMarkup(keyboard=rows,resize_keyboard=True,is_persistent=True)

def approve_kb(kind,ident):
    rows=[[InlineKeyboardButton(text='✅ CONFIRM',callback_data=f'approve:{kind}:{ident}'),InlineKeyboardButton(text='❌ REJECT',callback_data=f'reject:{kind}:{ident}')],[InlineKeyboardButton(text='📄 DETAILS',callback_data=f'details:{kind}:{ident}'),InlineKeyboardButton(text='💬 CONTACT USER',callback_data=f'contact:{kind}:{ident}')]]
    if kind=='request': rows.append([InlineKeyboardButton(text='💰 SET PRICE & CONFIRM',callback_data=f'setprice:{ident}')])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def back_kb(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='⬅️ Back',callback_data='home')]])

async def create_order(uid_,service,details,amount=0):
    oid=uid('ORD')
    await db.orders.insert_one({'order_id':oid,'user_id':int(uid_),'service':service,'details':details,'amount':money(amount),'status':'awaiting_payment','payment_status':'unpaid','created_at':now(),'updated_at':now()})
    return oid

async def payment_target_text(order_id=None):
    methods=[]
    async for x in db.payment_methods.find({'enabled':True}).sort('name',1):
        methods.append([InlineKeyboardButton(text=f'💳 {safe(x.get("name"))}',callback_data=f'paymethod:{x.get("name")}'+(f':{order_id}' if order_id else ''))])
    return InlineKeyboardMarkup(inline_keyboard=methods or [[InlineKeyboardButton(text='❌ No payment method available',callback_data='noop')]])

async def send_catalog(m,category):
    if category in ('numbers','vip','virtual'):
        cat={'numbers':'regular','vip':'vip','virtual':'virtual'}[category]
        rows=[]
        if category=='vip':
            cursor=db.numbers.find({'category':cat,'status':'available'}).sort('number',1).limit(15)
        else:
            cursor=db.numbers.aggregate([{'$match':{'category':cat,'status':'available'}},{'$sample':{'size':15}}])
        async for x in cursor:
            rows.append([InlineKeyboardButton(text=f"{x.get('number','?')} — ${money(x.get('price')):.2f}",callback_data=f'number:{x.get('_id')}')])
        if not rows:return await m.answer('📭 No available items currently. Admin can add inventory from the panel.')
        return await m.answer(f'<b>{SERVICES[category]}</b>\n\nShowing up to 15 available choices:',reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
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
    await m.answer('👋 <b>Welcome to Telesombot</b>\n\nAll services, orders and payments are available through the buttons below.\n\n⏳ <b>Pending 5-10 Min. Please wait</b>',reply_markup=main_kb(admin))

# Customer buttons
@router.message(F.text=='🏠 Customer Home')
async def customer_home(m:Message,state:FSMContext): await state.clear(); await m.answer('🏠 <b>Customer Home</b>',reply_markup=main_kb(await is_admin(m.from_user.id)))
@router.message(F.text=='🛠️ ADMIN PANEL TELESOM')
async def admin_home(m:Message):
    if not await is_admin(m.from_user.id): return await m.answer('❌ Not authorized.')
    await m.answer('🛡️ <b>TELESOM ADMIN PANEL</b>\n\nChoose a management panel:',reply_markup=admin_kb())
@router.message(F.text=='🎁 More Services')
async def more_services(m:Message):
    rows=[
        [InlineKeyboardButton(text='📞 Call Conference',callback_data='serviceinfo:call_conference'),InlineKeyboardButton(text='🎵 Ila Maqal',callback_data='serviceinfo:ila_maqal')],
        [InlineKeyboardButton(text='📚 Aqoonmaal',callback_data='serviceinfo:aqoonmaal'),InlineKeyboardButton(text='🩺 Shaafi',callback_data='serviceinfo:shaafi')],
        [InlineKeyboardButton(text='🚗 ILA SOCO',callback_data='serviceinfo:ila_soco'),InlineKeyboardButton(text='🛡️ Antitheft',callback_data='serviceinfo:antitheft')],
        [InlineKeyboardButton(text='🛍️ Mobile Market',callback_data='serviceinfo:mobile_market'),InlineKeyboardButton(text='📡 5G',callback_data='serviceinfo:5g')],
        [InlineKeyboardButton(text='📞 Roaming',callback_data='serviceinfo:roaming'),InlineKeyboardButton(text='🌍 International Calling',callback_data='serviceinfo:international_calling')],
        [InlineKeyboardButton(text='📋 Postpaid',callback_data='serviceinfo:postpaid'),InlineKeyboardButton(text='📞 Fixed Line',callback_data='serviceinfo:fixed_line')],
    ]
    await m.answer('🎁 <b>More Telesom Services</b>\n\nThese services are based on the current Telesom service catalogue. Purchasable packages appear when admin has configured a price/package for them.',reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.callback_query(F.data.startswith('serviceinfo:'))
async def service_info(c:CallbackQuery):
    key=c.data.split(':',1)[1]
    names={'call_conference':'Call Conference','ila_maqal':'Ila Maqal','aqoonmaal':'Aqoonmaal','shaafi':'Shaafi','ila_soco':'ILA SOCO','antitheft':'Antitheft','mobile_market':'Mobile Market','5g':'5G','roaming':'Roaming','international_calling':'International Calling','postpaid':'Postpaid Plans','fixed_line':'Fixed Line Service'}
    await c.message.answer(f'📋 <b>{safe(names.get(key,key))}</b>\n\nThis service is available in the Telesom catalogue. If an orderable package is configured by admin, it will appear under the relevant service menu.')
    await c.answer()

@router.message(F.text.in_({'📱 Numbers','💎 VIP Numbers','🌐 Virtual Numbers','📲 eSIM','💳 Physical SIM','📡 Data','📞 Voice','💬 SMS','🔋 Recharge','🌐 Fiber','💰 ZAAD','🏢 Business','🏢 Corporate','🔌 IoT','☁️ Cloud','🎁 Offers','📶 5G'}))
async def service_button(m:Message):
    mapping={'📱 Numbers':'numbers','💎 VIP Numbers':'vip','🌐 Virtual Numbers':'virtual','📲 eSIM':'esim','💳 Physical SIM':'sim','📡 Data':'data','📞 Voice':'voice','💬 SMS':'sms','🔋 Recharge':'recharge','🌐 Fiber':'fiber','💰 ZAAD':'zaad','🏢 Business':'business','🏢 Corporate':'corporate','🔌 IoT':'iot','☁️ Cloud':'cloud','🎁 Offers':'offers','📶 5G':'5g'}
    await send_catalog(m,mapping[m.text])

@router.callback_query(F.data.startswith('number:'))
async def number_select(c:CallbackQuery):
    try: x=await db.numbers.find_one({'_id':__import__('bson').ObjectId(c.data.split(':',1)[1])})
    except: x=None
    if not x: return await c.answer('Item unavailable',show_alert=True)
    await c.message.answer(f"📱 <b>{safe(x.get('number'))}</b>\n\nCategory: {safe(x.get('category'))}\nPrice: <b>${money(x.get('price')):.2f}</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🛒 ORDER NOW',callback_data=f'order_number:{x["_id"]}')],[InlineKeyboardButton(text='⬅️ Back',callback_data='home')]])); await c.answer()
@router.callback_query(F.data.startswith('order_number:'))
async def order_number(c:CallbackQuery,state:FSMContext):
    try: x=await db.numbers.find_one({'_id':__import__('bson').ObjectId(c.data.split(':',1)[1]),'status':'available'})
    except: x=None
    if not x:return await c.answer('Number unavailable',show_alert=True)
    oid=await create_order(c.from_user.id,x.get('category','number'),f"Number: {x.get('number')}",x.get('price',0))
    await db.orders.update_one({'order_id':oid},{'$set':{'number_id':str(x['_id'])}})
    await c.message.answer(f'🛒 <b>Order Created</b>\n\nOrder: <code>{escape(oid)}</code>\nNumber: <code>{safe(x.get("number"))}</code>\nAmount: <b>${money(x.get("price")):.2f}</b>\n\n⏳ <b>Pending 5-10 Min. Please wait</b>\n\nTap <b>💵 PAY NOW</b> to continue your payment.',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='💵 PAY NOW',callback_data=f'choosepay:{oid}')],[InlineKeyboardButton(text='🛒 My Orders',callback_data='myorders'),InlineKeyboardButton(text='🏠 Home',callback_data='home')]]))
    await c.answer()

@router.callback_query(F.data.startswith('catalog:'))
async def catalog_select(c:CallbackQuery,state:FSMContext):
    try: x=await db.catalog.find_one({'_id':__import__('bson').ObjectId(c.data.split(':',1)[1]),'enabled':True})
    except: x=None
    if not x:return await c.answer('Package unavailable',show_alert=True)
    service=x.get('service','service')
    if service in {'data','voice','sms','recharge','5g'}:
        await state.update_data(catalog_id=str(x['_id']),catalog_service=service,catalog_title=x.get('title'),catalog_price=money(x.get('price')))
        await state.set_state(UserFlow.target_number)
        await c.message.answer(f'📱 <b>{safe(SERVICES.get(service,service))}</b>\n\nPackage: <b>{safe(x.get("title"))}</b>\nPrice: <b>${money(x.get("price")):.2f}</b>\n\n📞 Send the Telesom number that should receive this service.\nExample: <code>0634XXXXXX</code>')
        return await c.answer()
    oid=await create_order(c.from_user.id,service,x.get('title','Package'),x.get('price',0))
    await c.message.answer(f'🛒 <b>Order Created</b>\n\nOrder: <code>{escape(oid)}</code>\nService: {safe(service)}\nPackage: {safe(x.get("title"))}\nAmount: <b>${money(x.get("price")):.2f}</b>\n\n⏳ <b>Pending 5-10 Min. Please wait</b>\n\n💳 Choose <b>PAY NOW</b> to complete payment.',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='💵 PAY NOW',callback_data=f'choosepay:{oid}')],[InlineKeyboardButton(text='🛒 My Orders',callback_data='myorders'),InlineKeyboardButton(text='🏠 Home',callback_data='home')]]))
    await c.answer()

@router.message(UserFlow.target_number)
async def target_number_submit(m:Message,state:FSMContext):
    d=await state.get_data(); number=re.sub(r'\D','',m.text or '')
    if number.startswith('252') and len(number)>=12: number='0'+number[-9:]
    if not re.fullmatch(r'06\d{8}',number): return await m.answer('❌ Invalid Telesom number. Please send a valid 10-digit number, for example <code>0634XXXXXX</code>.')
    service=d.get('catalog_service','data'); title=d.get('catalog_title','Package'); price=money(d.get('catalog_price'))
    oid=await create_order(m.from_user.id,service,f'{title} | Recipient: {number}',price)
    await db.orders.update_one({'order_id':oid},{'$set':{'target_number':number,'catalog_id':d.get('catalog_id')}})
    await state.clear()
    await m.answer(f'🛒 <b>Order Created</b>\n\nOrder: <code>{escape(oid)}</code>\nService: {safe(SERVICES.get(service,service))}\nPackage: {safe(title)}\nNumber: <code>{number}</code>\nAmount: <b>${price:.2f}</b>\n\n⏳ <b>Pending 5-10 Min. Please wait</b>\n\n💳 Tap <b>PAY NOW</b> to continue.',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='💵 PAY NOW',callback_data=f'choosepay:{oid}')],[InlineKeyboardButton(text='🛒 My Orders',callback_data='myorders'),InlineKeyboardButton(text='🏠 Home',callback_data='home')]]))

@router.callback_query(F.data.startswith('request:'))
async def request_service(c:CallbackQuery,state:FSMContext):
    service=c.data.split(':',1)[1]; await state.update_data(service=service); await state.set_state(UserFlow.order_details)
    await c.message.answer(f'📝 <b>{safe(SERVICES.get(service,service))}</b>\n\nSend the required details. Your request will be sent to our service queue.\n💡 <b>No payment is requested yet.</b> The service price will be shown before payment.')
    await c.answer()

@router.message(UserFlow.order_details)
async def order_details(m:Message,state:FSMContext):
    d=await state.get_data(); service=d.get('service'); details=(m.text or '').strip()
    if not details:return await m.answer('❌ Please send the required details.')
    oid=await create_order(m.from_user.id,service,details,0); rid=uid('REQ')
    await db.requests.insert_one({'request_id':rid,'user_id':m.from_user.id,'kind':service,'order_id':oid,'data':{'details':details,'service':service},'status':'pending','created_at':now(),'updated_at':now()})
    await state.clear()
    await notify_admin(f'📝 <b>NEW SERVICE REQUEST</b>\n\nRequest: <code>{rid}</code>\nOrder: <code>{oid}</code>\nUser: <code>{m.from_user.id}</code>\nService: <b>{safe(SERVICES.get(service,service))}</b>\nDetails: {safe(details)}\n\nSet/confirm the price before requesting payment.',approve_kb('request',rid))
    await m.answer(f'✅ <b>Request Received</b>\n\nReference: <code>{rid}</code>\n⏳ <b>Pending 5-10 Min. Please wait</b>\n\nYou do not need to pay yet. Once the price is confirmed, the bot will show <b>PAY NOW</b>.',reply_markup=main_kb(await is_admin(m.from_user.id)))

@router.message(F.text=='💵 Payments')
async def payments(m:Message):
    await m.answer('💵 <b>Payments</b>\n\nFirst choose an unpaid order from <b>🛒 My Orders</b>, or use the payment button shown after creating an order.',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🛒 My Orders',callback_data='myorders')],[InlineKeyboardButton(text='🏠 Home',callback_data='home')]]))

@router.callback_query(F.data.startswith('choosepay:'))
async def choose_pay(c:CallbackQuery):
    oid=c.data.split(':',1)[1]
    order=await db.orders.find_one({'order_id':oid,'user_id':c.from_user.id,'status':{'$in':['awaiting_payment','pending']}})
    if not order:return await c.answer('Order is unavailable or already paid.',show_alert=True)
    amount=money(order.get('amount'))
    if amount<=0:
        await c.message.answer(f'💵 <b>Payment for {escape(oid)}</b>\n\nThis service requires a custom amount. Select a payment method and then enter the amount you actually paid.')
    else:
        await c.message.answer(f'💵 <b>Payment for {escape(oid)}</b>\n\nAmount to pay: <b>${amount:.2f}</b>\n\nSelect your payment method:',reply_markup=await payment_target_text(oid))
    await c.answer()

@router.callback_query(F.data.startswith('paymethod:'))
async def pay_method(c:CallbackQuery,state:FSMContext):
    parts=c.data.split(':',2); method=parts[1]; oid=parts[2] if len(parts)>2 else ''
    x=await db.payment_methods.find_one({'name':method,'enabled':True})
    if not x:return await c.answer('Payment method unavailable',show_alert=True)
    order=await db.orders.find_one({'order_id':oid,'user_id':c.from_user.id}) if oid else None
    if oid and not order:return await c.answer('Order not found',show_alert=True)
    amount=money(order.get('amount')) if order else 0
    if amount<=0:
        return await c.answer('This order has no price yet.',show_alert=True)
    await state.update_data(method=method,order_id=oid,expected_amount=amount)
    await state.set_state(UserFlow.payment_reference)

    if method in ('Golis','Telesom'):
        base=str(x.get('destination') or PAYMENT_DEFAULTS[method]).strip()
        ussd=base + f'{amount:g}#'
        dial_url='tel:' + quote(ussd, safe='*')
        wallet_name='Golis' if method=='Golis' else 'Telesom / ZAAD'
        text=(f'💵 <b>{wallet_name} PAYMENT</b>\n\n'
              f'💰 Amount: <b>${amount:.2f}</b>\n\n'
              f'👇 Tap <b>PAY NOW</b>. Your phone dialer/payment screen will open with the payment code and amount already filled in.\n\n'
              f'After the payment is completed, return here and tap <b>✅ I HAVE PAID</b>.')
        kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💳 PAY NOW',url=dial_url)],
            [InlineKeyboardButton(text='✅ I HAVE PAID',callback_data='paid_confirm')],
            [InlineKeyboardButton(text='❌ CANCEL',callback_data='cancelpay')]
        ])
        await c.message.answer(text,reply_markup=kb)
    else:
        text=(f'🪙 <b>{safe(method)}</b>\n\n'
              f'💰 Amount: <b>${amount:.2f}</b>\n\n'
              f'📍 Send the exact amount to the address below, then tap <b>✅ I HAVE PAID</b>.\n\n'
              f'<code>{escape(str(x.get("destination","")))}</code>')
        await c.message.answer(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ I HAVE PAID',callback_data='paid_confirm')],[InlineKeyboardButton(text='❌ CANCEL',callback_data='cancelpay')]]))
    await c.answer()

@router.callback_query(F.data=='paid_confirm')
async def paid_confirm(c:CallbackQuery,state:FSMContext):
    if await state.get_state()!=UserFlow.payment_reference.state:
        return await c.answer('Choose a payment method first.',show_alert=True)
    d=await state.get_data()
    method=d.get('method','')
    if method in ('Golis','Telesom'):
        prompt='🔎 <b>Payment Confirmation</b>\n\nSend the payment reference/transaction ID. If your wallet does not show a reference, send the phone number you paid from.\n\nExample: <code>TXN123456</code>'
    else:
        prompt='🔎 <b>Payment Confirmation</b>\n\nSend the transaction hash/reference.\n\nExample: <code>TXN123456</code>'
    await c.message.answer(prompt)
    await c.answer()

@router.callback_query(F.data=='cancelpay')
async def cancelpay(c:CallbackQuery,state:FSMContext):
    await state.clear(); await c.message.answer('❌ Payment cancelled.',reply_markup=main_kb(await is_admin(c.from_user.id))); await c.answer()

@router.message(UserFlow.payment_reference)
async def payment_submit(m:Message,state:FSMContext):
    d=await state.get_data(); ref=m.text.strip(); oid=d.get('order_id'); method=d.get('method'); expected=money(d.get('expected_amount'))
    order=await db.orders.find_one({'order_id':oid,'user_id':m.from_user.id}) if oid else None
    if oid and not order:return await m.answer('❌ Order not found.')
    amount=expected
    if amount<=0:
        amount=money(ref.split()[1]) if len(ref.split())>1 and ref.split()[1].replace('.','',1).isdigit() else 0
    if amount<=0:return await m.answer('❌ Amount could not be determined. Send: <code>REFERENCE AMOUNT</code>, for example <code>TXN123456 10</code>.')
    if expected>0 and abs(amount-expected)>0.009:return await m.answer(f'❌ The payment must be exactly <b>${expected:.2f}</b>.')
    if not await get_setting('payments_open',True):return await m.answer('🔒 Payments are currently closed.')
    pid=uid('PAY')
    await db.payments.insert_one({'payment_id':pid,'user_id':m.from_user.id,'order_id':oid,'method':method,'amount':amount,'reference':ref,'status':'pending','user_confirmed_at':now(),'created_at':now(),'updated_at':now()})
    if oid:
        await db.orders.update_one({'order_id':oid,'user_id':m.from_user.id},{'$set':{'payment_status':'pending_verification','status':'payment_submitted','payment_id':pid,'updated_at':now()}})
    await state.clear()
    await notify_admin(f'💳 <b>PAYMENT VERIFICATION REQUIRED</b>\n\nPayment: <code>{escape(pid)}</code>\nOrder: <code>{escape(oid or "WALLET")}</code>\nUser: <code>{m.from_user.id}</code>\nAmount: <b>${amount:.2f}</b>\nMethod: <b>{safe(method)}</b>\nReference: <code>{safe(ref)}</code>\n\n👤 The customer confirmed they already sent the payment.',approve_kb('payment',pid))
    await m.answer(f'✅ <b>Payment Confirmation Sent</b>\n\nPayment: <code>{escape(pid)}</code>\nAmount: <b>${amount:.2f}</b>\nStatus: <b>WAITING FOR ADMIN VERIFICATION</b>\n\nYour payment has now been sent to admin for verification.',reply_markup=main_kb(await is_admin(m.from_user.id)))

async def show_orders(chat, user_id):
    rows=[]
    async for x in db.orders.find({'user_id':user_id}).sort('created_at',-1).limit(20):
        oid=escape(str(x.get('order_id',''))); status=safe(x.get('status')); service=safe(x.get('service')); amount=money(x.get('amount'))
        rows.append(f'📦 <code>{oid}</code>\n{service} — <b>{status}</b>\nAmount: <b>${amount:.2f}</b>')
    text='🛒 <b>My Orders</b>\n\n'+('\n\n'.join(rows) or 'No orders yet.')
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='💵 PAY UNPAID ORDER',callback_data='pick_unpaid')],[InlineKeyboardButton(text='🏠 Home',callback_data='home')]])
    await chat.answer(text,reply_markup=kb)

@router.message(F.text=='🛒 My Orders')
async def orders(m:Message): await show_orders(m,m.from_user.id)
@router.callback_query(F.data=='myorders')
async def myorders(c:CallbackQuery): await show_orders(c.message,c.from_user.id); await c.answer()
@router.callback_query(F.data=='pick_unpaid')
async def pick_unpaid(c:CallbackQuery):
    rows=[]
    async for x in db.orders.find({'user_id':c.from_user.id,'status':{'$in':['awaiting_payment','payment_submitted']},'payment_status':{'$ne':'paid'}}).sort('created_at',-1).limit(20):
        rows.append([InlineKeyboardButton(text=f'{x.get("order_id")} — ${money(x.get("amount")):.2f}',callback_data=f'choosepay:{x.get("order_id")}')])
    if not rows:return await c.answer('No unpaid orders.',show_alert=True)
    await c.message.answer('💵 <b>Select an unpaid order</b>',reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await c.answer()

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
    tid=uid('TKT'); await db.support.insert_one({'ticket_id':tid,'user_id':m.from_user.id,'message':m.text,'status':'open','created_at':now()}); await state.clear(); await notify_admin(f'🆘 <b>NEW SUPPORT TICKET</b>\n\nTicket: <code>{tid}</code>\nUser: <code>{m.from_user.id}</code>\nMessage: {safe(m.text)}',approve_kb('support',tid)); await m.answer(f'✅ Ticket <code>{tid}</code> sent to support.',reply_markup=main_kb(await is_admin(m.from_user.id)))

# Admin panels
async def panel_text(n):
    counts={1:await db.users.count_documents({}),2:await db.users.count_documents({}),3:await db.numbers.count_documents({'category':'regular'}),4:await db.numbers.count_documents({'category':'vip'}),5:await db.numbers.count_documents({'category':'virtual'}),6:await db.catalog.count_documents({'service':'esim'}),7:await db.catalog.count_documents({'service':'sim'}),8:await db.catalog.count_documents({'service':'data'}),9:await db.catalog.count_documents({'service':'voice'}),10:await db.catalog.count_documents({'service':'sms'}),11:await db.catalog.count_documents({'service':'recharge'}),12:await db.wallet_ledger.count_documents({}),13:await db.payments.count_documents({}),14:await db.orders.count_documents({}),15:await db.requests.count_documents({'kind':'refund'}),16:await db.offers.count_documents({}),17:await db.promos.count_documents({}),18:await db.referrals.count_documents({}),19:await db.memberships.count_documents({}),20:await db.support.count_documents({}),21:await db.notifications.count_documents({'type':'broadcast'}),22:await db.notifications.count_documents({}),23:await db.requests.count_documents({'kind':'business'}),24:await db.requests.count_documents({'kind':'corporate'}),25:await db.numbers.count_documents({}),26:await db.audit_logs.count_documents({}),27:await db.staff.count_documents({}),28:await db.security_events.count_documents({}),29:await db.audit_logs.count_documents({}),30:await db.settings.count_documents({})}
    extra_col={31:('payments',{'status':'pending'}),32:('orders',{'status':{'$in':['awaiting_payment','payment_submitted','pending']}}),33:('requests',{'status':'pending'}),34:('users',{}),35:('wallet_ledger',{}),36:('numbers',{}),37:('numbers',{}),38:('catalog',{'service':'data'}),39:('catalog',{'service':'voice'}),40:('catalog',{'service':'sms'}),41:('catalog',{'service':'recharge'}),42:('catalog',{'service':'esim'}),43:('catalog',{'service':'sim'}),44:('catalog',{'service':'business'}),45:('requests',{'kind':'corporate'}),46:('catalog',{'service':'5g'}),47:('catalog',{'service':'fiber'}),48:('settings',{}),49:('catalog',{}),50:('audit_logs',{}),51:('payment_methods',{}),52:('payment_methods',{}),53:('orders',{}),54:('users',{}),55:('support',{}),56:('notifications',{'type':'broadcast'}),57:('notifications',{}),58:('users',{}),59:('users',{}),60:('orders',{}),61:('payments',{}),62:('requests',{'kind':'refund'}),63:('offers',{}),64:('promos',{}),65:('referrals',{}),66:('memberships',{}),67:('notifications',{}),68:('requests',{'kind':'business'}),69:('requests',{'kind':'corporate'}),70:('requests',{'kind':'sim'}),71:('requests',{'kind':'esim'}),72:('requests',{'kind':'data'}),73:('requests',{'kind':'voice'}),74:('requests',{'kind':'sms'}),75:('requests',{'kind':'recharge'}),76:('requests',{'kind':'5g'}),77:('requests',{'kind':'fiber'}),78:('requests',{'kind':'zaad'}),79:('requests',{'kind':'iot'}),80:('requests',{'kind':'cloud'}),81:('numbers',{}),82:('numbers',{}),83:('numbers',{}),84:('numbers',{'status':'low'}),85:('numbers',{'status':'unavailable'}),86:('numbers',{'status':'reserved'}),87:('numbers',{'status':'sold'}),88:('orders',{'status':'failed'}),89:('orders',{'status':'completed'}),90:('orders',{'status':'cancelled'}),91:('payments',{'status':'confirmed'}),92:('orders',{}),93:('orders',{}),94:('orders',{}),95:('users',{}),96:('staff',{}),97:('security_events',{}),98:('audit_logs',{}),99:('settings',{}),100:('settings',{})}
    if n>30 and n in extra_col:
        col,q=extra_col[n]
        try: counts[n]=await db[col].count_documents(q)
        except: counts[n]=0
    name=PANELS[n-1] if n<=len(PANELS) else ADMIN_PANELS[n-1]
    return f'🛠️ <b>{n}. {safe(name)}</b>\n\nRecords: <b>{counts.get(n,0)}</b>\n\nChoose an action below.'

def panel_actions(n):
    acts={1:[('📊 Refresh Dashboard','p:1'),('⏳ Pending Approvals','pending')],2:[('👥 List Customers','users'),('🔎 Find Customer','finduser')],3:[('➕ Add Number','addnum:regular'),('📋 Inventory','inventory:regular')],4:[('➕ Add VIP Number','addnum:vip'),('📋 VIP Inventory','inventory:vip')],5:[('➕ Add Virtual Number','addnum:virtual'),('📋 Inventory','inventory:virtual')],6:[('➕ Add eSIM Package','addcatalog:esim'),('📋 eSIM Packages','cataloglist:esim')],7:[('➕ Add SIM Package','addcatalog:sim'),('📋 SIM Packages','cataloglist:sim')],8:[('➕ Add Data Package','addcatalog:data'),('📋 Data Packages','cataloglist:data')],9:[('➕ Add Voice Package','addcatalog:voice'),('📋 Voice Packages','cataloglist:voice')],10:[('➕ Add SMS Package','addcatalog:sms'),('📋 SMS Packages','cataloglist:sms')],11:[('➕ Add Recharge Package','addcatalog:recharge'),('📋 Recharge Packages','cataloglist:recharge')],16:[('➕ Add Offer','addoffer'),('🎁 Active Offers','offers')],17:[('➕ Add Promo','addpromo'),('🎟 Promo List','promos')],20:[('🎧 Open Tickets','tickets')],21:[('📢 Broadcast','broadcast')],23:[('➕ Business Package','addcatalog:business'),('📋 Business Catalogue','cataloglist:business')],24:[('➕ Corporate Package','addcatalog:corporate'),('📋 Corporate Catalogue','cataloglist:corporate')],25:[('📦 Inventory','inventory:all')],26:[('📈 Analytics','analytics')],27:[('➕ Add Staff','addstaff'),('👨‍💼 Staff List','staff')],28:[('🔐 Security','security')],29:[('📋 Audit Logs','audit')],30:[('⚙️ Services ON/OFF','settings_services'),('💳 Payment Methods','settings_payments')]}
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=a,callback_data=cb) for a,cb in acts.get(n,[('📋 View Records',f'records:{n}')])]])

@router.message(F.text.regexp(r'^🛠\s+\d{2,3}\. '))
async def admin_panel_button(m:Message,state:FSMContext):
    if not await is_admin(m.from_user.id): return
    n=int(re.search(r'🛠\s+(\d+)\.',m.text).group(1)); await m.answer(await panel_text(n),reply_markup=panel_actions(n))

@router.message(F.text=='📢 BROADCAST')
async def broadcast_button(m:Message,state:FSMContext):
    if not await has_permission(m.from_user.id,'broadcast'): return await m.answer('❌ Not authorized.')
    await state.set_state(UserFlow.broadcast); await m.answer('📢 <b>Broadcast</b>\n\nSend the message to broadcast to all active customers.')

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
    if not await is_admin(c.from_user.id): return await c.answer('Not authorized',show_alert=True)
    n=int(c.data.split(':')[1]); await c.message.answer(await panel_text(n),reply_markup=panel_actions(n)); await c.answer()

# Admin action callbacks/input
@router.callback_query(F.data.startswith('setprice:'))
async def set_request_price(c:CallbackQuery,state:FSMContext):
    if not await has_permission(c.from_user.id,'orders'): return await c.answer('Not authorized',show_alert=True)
    rid=c.data.split(':',1)[1]; row=await db.requests.find_one({'request_id':rid,'status':'pending'})
    if not row:return await c.answer('Request already processed.',show_alert=True)
    await state.update_data(quote_request_id=rid); await state.set_state(UserFlow.quote_amount)
    await c.message.answer(f'💰 <b>Set service price</b>\n\nRequest: <code>{rid}</code>\nSend the final customer price, for example: <code>25</code>'); await c.answer()

@router.message(UserFlow.quote_amount)
async def quote_amount_submit(m:Message,state:FSMContext):
    if not await has_permission(m.from_user.id,'orders'): return
    d=await state.get_data(); rid=d.get('quote_request_id'); amount=money((m.text or '').strip())
    if amount<=0:return await m.answer('❌ Send a valid price, e.g. <code>25</code>.')
    req=await db.requests.find_one({'request_id':rid,'status':'pending'})
    if not req: await state.clear(); return await m.answer('❌ Request not found.')
    oid=req.get('order_id')
    await db.requests.update_one({'request_id':rid},{'$set':{'status':'confirmed','price':amount,'confirmed_by':m.from_user.id,'updated_at':now()}})
    if oid: await db.orders.update_one({'order_id':oid},{'$set':{'amount':amount,'status':'awaiting_payment','payment_status':'unpaid','quoted_by':m.from_user.id,'quoted_at':now(),'updated_at':now()}})
    await audit(m.from_user.id,'request_price_confirmed',rid,{'amount':amount}); await state.clear()
    await bot.send_message(req['user_id'],f'💰 <b>Price Confirmed</b>\n\nReference: <code>{rid}</code>\nAmount: <b>${amount:.2f}</b>\n\n⏳ <b>Pending 5-10 Min. Please wait</b>',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='💵 PAY NOW',callback_data=f'choosepay:{oid}')],[InlineKeyboardButton(text='🛒 My Orders',callback_data='myorders')]]))
    await m.answer(f'✅ Price ${amount:.2f} confirmed and payment opened for the customer.',reply_markup=admin_kb())

@router.callback_query(F.data.startswith('approve:'))
async def approve(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'admin'):return await c.answer('Not authorized',show_alert=True)
    _,kind,ident=c.data.split(':',2)
    if kind=='payment':
        row=await db.payments.find_one_and_update({'payment_id':ident,'status':'pending'},{'$set':{'status':'confirmed','confirmed_by':c.from_user.id,'confirmed_at':now(),'updated_at':now()}},return_document=__import__('pymongo').ReturnDocument.AFTER)
        if row:
            oid=row.get('order_id')
            if oid:
                await db.orders.update_one({'order_id':oid,'user_id':row['user_id']},{'$set':{'payment_status':'paid','status':'processing','payment_confirmed_by':c.from_user.id,'updated_at':now()}})
                await bot.send_message(row['user_id'],f'✅ <b>Payment Confirmed</b>\n\nPayment: <code>{escape(ident)}</code>\nAmount: <b>${money(row["amount"]):.2f}</b>\n\nYour order is now <b>PROCESSING</b>.')
            else:
                await bot.send_message(row['user_id'],f'✅ <b>Payment Confirmed</b>\n\nPayment: <code>{escape(ident)}</code>\nAmount: <b>${money(row["amount"]):.2f}</b>.')
    elif kind=='request':
        row=await db.requests.find_one({'request_id':ident,'status':'pending'})
        if row:
            amount=money(row.get('price'))
            if amount<=0:
                await c.answer('Set the customer price first.',show_alert=True); return
            row=await db.requests.find_one_and_update({'request_id':ident,'status':'pending'},{'$set':{'status':'confirmed','confirmed_by':c.from_user.id,'updated_at':now()}},return_document=__import__('pymongo').ReturnDocument.AFTER)
            oid=row.get('order_id') or row.get('data',{}).get('order_id')
            if oid: await db.orders.update_one({'order_id':oid},{'$set':{'amount':amount,'status':'awaiting_payment','payment_status':'unpaid','updated_at':now()}})
            await bot.send_message(row['user_id'],f'💰 <b>Price Confirmed</b>\n\nReference: <code>{escape(ident)}</code>\nAmount: <b>${amount:.2f}</b>\n\n⏳ <b>Pending 5-10 Min. Please wait</b>',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='💵 PAY NOW',callback_data=f'choosepay:{oid}')],[InlineKeyboardButton(text='🛒 My Orders',callback_data='myorders')]]))
    else: row=None
    if row: await audit(c.from_user.id,'approved',ident,{'kind':kind}); await c.message.edit_reply_markup(reply_markup=None); await c.answer('Confirmed')
    else: await c.answer('Already processed / not found',show_alert=True)
@router.callback_query(F.data.startswith('reject:'))
async def reject(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'admin'):return await c.answer('Not authorized',show_alert=True)
    _,kind,ident=c.data.split(':',2); col=db.payments if kind=='payment' else db.requests; key='payment_id' if kind=='payment' else 'request_id'
    row=await col.find_one_and_update({key:ident,'status':'pending'},{'$set':{'status':'rejected','rejected_by':c.from_user.id,'updated_at':now()}},return_document=__import__('pymongo').ReturnDocument.AFTER)
    if row:
        if kind=='payment' and row.get('order_id'):
            await db.orders.update_one({'order_id':row['order_id']},{'$set':{'payment_status':'rejected','status':'awaiting_payment','updated_at':now()}})
        await bot.send_message(row['user_id'],f'❌ <b>{kind.title()} Rejected</b>\n\nReference: <code>{escape(ident)}</code>\nPlease check the payment details and try again.')
        await audit(c.from_user.id,'rejected',ident,{'kind':kind}); await c.message.edit_reply_markup(reply_markup=None); await c.answer('Rejected')
    else: await c.answer('Already processed / not found',show_alert=True)
@router.callback_query(F.data.startswith('details:'))
async def details(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'admin'):return await c.answer('Not authorized',show_alert=True)
    _,kind,ident=c.data.split(':',2); row=await (db.payments.find_one({'payment_id':ident}) if kind=='payment' else db.support.find_one({'ticket_id':ident}) if kind=='support' else db.requests.find_one({'request_id':ident}));
    if row: await c.message.answer('📄 <b>DETAILS</b>\n\n'+safe(row)); await c.answer()
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
    if kind=='promo':
        p=[x.strip() for x in (m.text or '').split('|',1)]
        if len(p)!=2 or money(p[1])<=0:return await m.answer('Format: <code>CODE | DISCOUNT</code>')
        await db.promos.update_one({'code':p[0].upper()},{'$set':{'code':p[0].upper(),'discount':money(p[1]),'enabled':True,'updated_at':now()},'$setOnInsert':{'created_at':now()}},upsert=True)
        await audit(m.from_user.id,'promo_upsert',p[0].upper(),{'discount':money(p[1])}); await state.clear(); return await m.answer('✅ Promo saved.',reply_markup=admin_kb())
    if kind!='offer':return
    p=[x.strip() for x in (m.text or '').split('|',1)]
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

@router.callback_query(F.data.startswith('addcatalog:'))
async def add_catalog(c:CallbackQuery,state:FSMContext):
    if not await has_permission(c.from_user.id,'settings'): return await c.answer('Not authorized',show_alert=True)
    service=c.data.split(':',1)[1]
    await state.update_data(input_kind='catalog',catalog_service=service)
    await state.set_state(UserFlow.catalog_add)
    await c.message.answer(f'➕ <b>Add {safe(service)} package</b>\n\nSend: <code>TITLE | PRICE</code>\nExample: <code>10 GB - 30 Days | 5</code>')
    await c.answer()

@router.message(UserFlow.catalog_add)
async def catalog_add_submit(m:Message,state:FSMContext):
    if not await has_permission(m.from_user.id,'settings'): return
    d=await state.get_data(); parts=[x.strip() for x in (m.text or '').split('|',1)]
    if len(parts)!=2 or money(parts[1])<=0:
        return await m.answer('❌ Format: <code>TITLE | PRICE</code>')
    title,price=parts[0],money(parts[1]); service=d.get('catalog_service','data')
    await db.catalog.update_one({'service':service,'title':title},{'$set':{'service':service,'title':title,'price':price,'enabled':True,'updated_at':now()},'$setOnInsert':{'created_at':now()}},upsert=True)
    await audit(m.from_user.id,'catalog_upsert',title,{'service':service,'price':price}); await state.clear()
    await m.answer(f'✅ Package saved.\n\n{safe(title)} — <b>${price:.2f}</b>',reply_markup=admin_kb())

@router.callback_query(F.data.startswith('cataloglist:'))
async def catalog_list(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'settings'): return await c.answer('Not authorized',show_alert=True)
    service=c.data.split(':',1)[1]; rows=[]
    async for x in db.catalog.find({'service':service}).sort('price',1).limit(50): rows.append(f'📦 <b>{safe(x.get("title"))}</b> — ${money(x.get("price")):.2f} — {"ON" if x.get("enabled") else "OFF"}')
    await c.message.answer(f'📋 <b>{safe(service)} Catalogue</b>\n\n'+('\n'.join(rows) or 'No packages configured.')); await c.answer()

@router.callback_query(F.data=='broadcast')
async def broadcast(c:CallbackQuery,state:FSMContext):
    if not await has_permission(c.from_user.id,'broadcast'):return await c.answer('Not authorized',show_alert=True)
    await state.set_state(UserFlow.broadcast); await c.message.answer('📢 Send any message (text, photo, video, document, etc.). It will be copied to all active customers.'); await c.answer()
@router.message(UserFlow.broadcast)
async def broadcast_send(m:Message,state:FSMContext):
    if not await has_permission(m.from_user.id,'broadcast'): return
    count=0
    async for u in db.users.find({'status':{'$ne':'banned'}},{'telegram_id':1}):
        try:
            await bot.copy_message(chat_id=int(u['telegram_id']),from_chat_id=m.chat.id,message_id=m.message_id)
            count+=1
        except: pass
    await db.notifications.insert_one({'type':'broadcast','text':m.text or m.caption or '[media]','count':count,'created_at':now()})
    await audit(m.from_user.id,'broadcast',None,{'count':count}); await state.clear()
    await m.answer(f'📢 Broadcast sent to <b>{count}</b> customers.',reply_markup=admin_kb())

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
@router.callback_query(F.data=='pending')
async def pending_callback(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'admin'): return await c.answer('Not authorized',show_alert=True)
    await pending(c.message); await c.answer()

@router.callback_query(F.data=='settings_payments')
async def settings_payments(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'payments'): return await c.answer('Not authorized',show_alert=True)
    rows=[]
    async for x in db.payment_methods.find({}).sort('name',1):
        state='🟢 ON' if x.get('enabled') else '🔴 OFF'
        rows.append([InlineKeyboardButton(text=f'{x.get("name")} — {state}',callback_data=f'togglepay:{x.get("name")}')])
    await c.message.answer('💳 <b>Payment Methods</b>\n\nTap a method to turn it ON/OFF.',reply_markup=InlineKeyboardMarkup(inline_keyboard=rows or [[InlineKeyboardButton(text='No methods',callback_data='noop')]])); await c.answer()

@router.callback_query(F.data.startswith('togglepay:'))
async def toggle_payment_method(c:CallbackQuery):
    if not await has_permission(c.from_user.id,'payments'): return await c.answer('Not authorized',show_alert=True)
    name=c.data.split(':',1)[1]
    row=await db.payment_methods.find_one({'name':name})
    if not row:return await c.answer('Not found',show_alert=True)
    enabled=not bool(row.get('enabled'))
    await db.payment_methods.update_one({'name':name},{'$set':{'enabled':enabled,'updated_at':now()}})
    await audit(c.from_user.id,'payment_method_toggle',name,{'enabled':enabled})
    await c.answer('ON' if enabled else 'OFF',show_alert=True)

@router.callback_query(F.data=='addpromo')
async def addpromo(c:CallbackQuery,state:FSMContext):
    if not await has_permission(c.from_user.id,'promos'): return await c.answer('Not authorized',show_alert=True)
    await state.update_data(input_kind='promo'); await state.set_state(UserFlow.catalog_add)
    await c.message.answer('🎟 <b>Add Promo</b>\n\nSend: <code>CODE | DISCOUNT</code>\nExample: <code>WELCOME10 | 10</code>'); await c.answer()

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

# Public Telesom website catalogue sync. This reads publicly visible products/prices; it does not invent inventory.
TELESOM_PUBLIC_PAGES=[
    'https://telesom.com/personal/products',
    'https://telesom.com/personal/data_bundles/0',
    'https://telesom.com/personal/network/4g',
    'https://telesom.com/personal/network/5g',
    'https://telesom.com/personal/esim',
    'https://telesom.com/personal/kaafiye',
]

async def sync_telesom_catalog():
    try:
        import aiohttp
        from bs4 import BeautifulSoup
        timeout=aiohttp.ClientTimeout(total=25)
        headers={'User-Agent':'Mozilla/5.0 (compatible; Telesombot/1.0)'}
        async with aiohttp.ClientSession(timeout=timeout,headers=headers) as session:
            for url in TELESOM_PUBLIC_PAGES:
                try:
                    async with session.get(url,allow_redirects=True) as r:
                        if r.status != 200: continue
                        html=await r.text(errors='ignore')
                    soup=BeautifulSoup(html,'html.parser')
                    text='\n'.join(x.strip() for x in soup.stripped_strings if x.strip())
                    service=('data' if 'data_bundles' in url else ('voice' if '/network/4g' in url or '/kaafiye' in url else ('5g' if '/network/5g' in url else ('esim' if '/esim' in url else 'sim'))))
                    # Capture nearby product/price lines from the public page.
                    lines=text.splitlines()
                    for i,line in enumerate(lines):
                        m=re.search(r'\$\s*([0-9]+(?:\.[0-9]+)?)',line)
                        if not m: continue
                        price=money(m.group(1))
                        if price<=0 or price>1000: continue
                        title=re.sub(r'\s+',' ',re.sub(r'\$\s*[0-9]+(?:\.[0-9]+)?','',line)).strip(' -:')
                        if not title or len(title)<3 or len(title)>120: continue
                        if title.lower() in {'buy now','top-up','price','pricing'}: continue
                        await db.catalog.update_one({'service':service,'title':title},{'$set':{'service':service,'title':title,'price':price,'enabled':True,'source':'telesom.com','source_url':url,'synced_at':now()}},upsert=True)
                except Exception as e:
                    log.warning('Telesom sync page failed %s: %r',url,e)
    except Exception as e:
        log.warning('Telesom website sync unavailable: %r',e)

async def sync_telesom_numbers():
    """Import publicly visible Telesom SIM numbers when the public order page exposes them.
    The public site may expose only a subset/dynamically generated number, so this never invents numbers.
    """
    try:
        import aiohttp
        from bs4 import BeautifulSoup
        timeout=aiohttp.ClientTimeout(total=30)
        headers={'User-Agent':'Mozilla/5.0 (compatible; Telesombot/1.0)'}
        async with aiohttp.ClientSession(timeout=timeout,headers=headers) as session:
            async with session.get('https://telesom.com/personal/products',allow_redirects=True) as r:
                if r.status != 200: return
                html=await r.text(errors='ignore')
            soup=BeautifulSoup(html,'html.parser')
            links=[]
            for a in soup.find_all('a',href=True):
                href=a.get('href','')
                if 'sim_device' in href and href not in links:
                    links.append(href if href.startswith('http') else 'https://telesom.com'+href)
            for url in links[:10]:
                try:
                    async with session.get(url,allow_redirects=True) as rr:
                        if rr.status != 200: continue
                        page=await rr.text(errors='ignore')
                    text='\n'.join(BeautifulSoup(page,'html.parser').stripped_strings)
                    nums=set(re.findall(r'\b63\d{7}\b',text))
                    for number in nums:
                        pos=text.find(number)
                        nearby=text[max(0,pos-500):pos+500] if pos>=0 else text[:1000]
                        pm=re.search(r'\$\s*([0-9]+(?:\.[0-9]+)?)',nearby)
                        price=money(pm.group(1)) if pm else 10.0
                        category='vip' if re.search(r'vip',nearby,re.I) else 'regular'
                        await db.numbers.update_one({'number':number},{'$set':{'number':number,'price':price,'category':category,'status':'available','source':'telesom.com','source_url':url,'updated_at':now()},'$setOnInsert':{'created_at':now()}},upsert=True)
                except Exception as e:
                    log.warning('Telesom number sync failed %s: %r',url,e)
    except Exception as e:
        log.warning('Telesom number sync unavailable: %r',e)

async def telesom_sync_loop():
    while True:
        try:
            await sync_telesom_catalog()
            await sync_telesom_numbers()
        except Exception as e: log.warning('catalog sync loop: %r',e)
        await asyncio.sleep(6*60*60)

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
    for name,dest in PAYMENT_DEFAULTS.items(): await db.payment_methods.update_one({'name':name},{'$set':{'destination':dest,'enabled':True},'$setOnInsert':{'name':name}},upsert=True)
    website_catalog=[
        ('data','24 Hours Unlimited Data',0.50),
        ('data','24 Hours Unlimited Calls + Data',1.00),
        ('data','7 Days Unlimited Data',3.00),
        ('data','30 Days Unlimited Data',15.00),
        ('data','30 Days Unlimited Calls + Data',20.00),
        ('data','24 Hours 400 MB',0.12),('data','24 Hours 1 GB',0.25),
        ('data','7 Days 400 MB',0.12),('data','7 Days 3.5 GB',1.00),
        ('data','7 Days 1.8 GB',0.50),('data','7 Days 900 MB',0.25),
        ('data','30 Days 17 GB',5.00),
        ('data','30 Days 8 GB VIP',3.00),('data','30 Days 25 GB VIP',5.00),
        ('data','30 Days 55 GB VIP',10.00),('data','30 Days 100 GB VIP',15.00),
        ('data','30 Days 130 GB VIP',20.00),('data','30 Days 140 GB VIP',25.00),
        ('voice','24 Hours Unlimited Calls + 100 SMS',0.30),
        ('voice','7 Days Unlimited Calls + 500 SMS',2.00),
        ('voice','14 Days Unlimited Calls + 750 SMS',4.00),
        ('voice','30 Days Unlimited Calls + 1000 SMS',7.00),
        ('5g','24 Hours 10 GB',1.00),('5g','7 Days 5 GB/Day',4.00),
        ('5g','30 Days 120 GB',15.00),('5g','30 Days 10 GB/Day',25.00),
        ('5g','30 Days 20Mbps Fixed Wireless',30.00),('5g','30 Days 50Mbps Fixed Wireless',90.00),
        ('5g','30 Days 100Mbps Fixed Wireless',150.00),
        ('esim','Telesom eSIM',10.00),('sim','Regular SIM Card',10.00),
        ('sim','VIP SIM Card — from',30.00),('business','Business SIM Card — from',10.00),('business','Business 20Mbps Fixed Wireless',30.00),('business','Business 50Mbps Fixed Wireless',90.00),('business','Business 100Mbps Fixed Wireless',150.00),
    ]
    for service,title,price in website_catalog:
        await db.catalog.update_one({'service':service,'title':title},{'$setOnInsert':{'service':service,'title':title,'price':price,'enabled':True,'source':'telesom.com','created_at':now()}},upsert=True)
    await client.admin.command('ping'); await sync_telesom_catalog(); await sync_telesom_numbers(); log.info('MongoDB connected')

async def health(request):return web.json_response({'status':'ok','service':'Telesombot'})
async def health_server():
    app=web.Application();app.router.add_get('/',health);app.router.add_get('/health',health);runner=web.AppRunner(app);await runner.setup();await web.TCPSite(runner,'0.0.0.0',PORT).start();return runner
async def main():
    await init_db(); asyncio.create_task(telesom_sync_loop()); await bot.delete_webhook(drop_pending_updates=False); await health_server(); log.info('Telesombot button system started; admin=%s',MAIN_ADMIN); await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
if __name__=='__main__': asyncio.run(main())
