import os, asyncio, logging, uuid, random, re
from datetime import datetime, timezone, timedelta
from html import escape
from typing import Optional
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

load_dotenv()
BOT_TOKEN=os.getenv('BOT_TOKEN','').strip(); MONGO_URI=os.getenv('MONGO_URI','').strip(); PORT=int(os.getenv('PORT','10000')); DB_NAME=os.getenv('DB_NAME','telesombot')
try: MAIN_ADMIN=int(os.getenv('ADMIN_ID','0'))
except: MAIN_ADMIN=0
if not BOT_TOKEN or not MONGO_URI or MAIN_ADMIN<=0: raise RuntimeError('BOT_TOKEN, MONGO_URI and numeric ADMIN_ID are required')
logging.basicConfig(level=logging.INFO,format='%(asctime)s | %(levelname)s | %(message)s'); log=logging.getLogger('telesombot')
client=AsyncIOMotorClient(MONGO_URI,serverSelectionTimeoutMS=10000); db=client[DB_NAME]; bot=Bot(BOT_TOKEN); dp=Dispatcher(); router=Router(); admin_router=Router(); dp.include_router(router); dp.include_router(admin_router)

PAYMENTS={'Golis':'*883*0907868526*$#','Telesom':'*880*0907868526*$#','BNB':'0x1f12ffDc93E49eff0c78672Ab6abA62410c05a32','USDT-BEP20':'0x6AC864773259fa5175251829cb0E93ffb4cE6feC'}
TELESOM_SITE='https://www.telesom.com'
PANELS=['Dashboard','Customers','Numbers','VIP Numbers','Virtual Numbers','eSIM','Physical SIM','Data','Voice','SMS','Recharge','Wallets','Payments','Orders','Refunds','Offers','Promo Codes','Referrals','Memberships','Support','Broadcast','Notifications','Business','Corporate','Inventory','Analytics','Staff & Permissions','Security','Audit Logs','System Settings']
PANEL2=['Payment Methods','Payment Verification','Pending Orders','Completed Orders','Rejected Orders','Number Pricing','VIP Pricing','eSIM Pricing','SIM Pricing','Data Requests','Voice Requests','SMS Requests','Recharge Requests','Wallet Ledger','Deposits','Withdrawals','Manual Credits','Manual Debits','Customer Search','Customer Ban','Customer Unban','Customer Notes','Order Notes','Order Status','Fulfilment Queue','Inventory Add','Inventory Remove','Inventory Import','Inventory Export','Offer Create','Offer Toggle','Promo Create','Promo Toggle','Referral Settings','Membership Settings','Support Queue','Support Close','Broadcast History','Notification Queue','Business Requests','Corporate Requests','Security Events','Login/Access','Admin Roles','Admin Permissions','Audit Search','System Health','Database Stats','Service Toggles','Registration Toggle','Ordering Toggle','Payments Toggle','Support Toggle','Maintenance','Branding','Languages','Default Currency','Payment Instructions','Pending Timeout','Contact Settings','Website Settings','Terms','Privacy','FAQ','Announcements','Customer Menu','Admin Menu','Backup Info','Error Logs','Bot Status','Mongo Status','Telegram Status','Restart Info']
PANELS=(PANELS+PANEL2)[:100]

class Form(StatesGroup):
    payment=State(); support=State(); data=State(); voice=State(); sms=State(); admin_text=State(); admin_value=State(); broadcast=State(); number=State(); vip=State(); esim=State(); sim=State(); offer=State(); promo=State(); staff=State()

def now(): return datetime.now(timezone.utc)
def uid(p): return f'{p}-{uuid.uuid4().hex[:10].upper()}'
def money(x):
    try:return round(float(x),2)
    except:return 0.0
def tx(x): return escape(str(x or '-'))
async def setting(k,d=None):
    x=await db.settings.find_one({'_id':k}); return x.get('value',d) if x else d
async def set_setting(k,v): await db.settings.update_one({'_id':k},{'$set':{'value':v}},upsert=True)
async def user(m): return await db.users.find_one({'telegram_id':m.from_user.id})
async def ensure_user(u):
    old=await db.users.find_one({'telegram_id':u.id})
    await db.users.update_one({'telegram_id':u.id},{'$set':{'username':u.username,'first_name':u.first_name,'last_name':u.last_name,'updated_at':now()},'$setOnInsert':{'telegram_id':u.id,'language':'en','status':'active','wallet':{'available':0,'pending':0},'total_deposited':0,'total_spent':0,'referrals':0,'created_at':now()}},upsert=True)
    if not old:
        await db.audit.insert_one({'actor':u.id,'action':'customer_registered','created_at':now()})
        await bot.send_message(MAIN_ADMIN,f'🆕 <b>NEW CUSTOMER</b>\n\n👤 {tx(u.full_name)}\n🆔 <code>{u.id}</code>\n🔗 @{tx(u.username or "none")}')

def kb(rows): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in row] for row in rows],resize_keyboard=True,is_persistent=True)
def home(): return kb([['📱 Numbers','💎 VIP Numbers'],['🌐 Virtual Numbers','📲 eSIM'],['💳 Physical SIM','📡 Data'],['📞 Voice','💬 SMS'],['🔋 Recharge','💰 Wallet'],['🛒 My Orders','💵 Payments'],['🎁 Offers','👥 Referral'],['🆘 Customer Support','👤 My Profile'],['🌐 Language']])
def back(): return kb([['🏠 Main Menu']])
def admin_home():
    rows=[]
    for i in range(0,len(PANELS),2): rows.append([f'🛠️ {i+1}. {PANELS[i]}'] + ([f'🛠️ {i+2}. {PANELS[i+1]}'] if i+1<len(PANELS) else []))
    rows += [['⏳ Pending Orders','💳 Pending Payments'],['📢 Broadcast','🏠 Main Menu']]
    return kb(rows)
def inline_payment(pid): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ Confirm',callback_data=f'pc:{pid}'),InlineKeyboardButton(text='❌ Reject',callback_data=f'pr:{pid}')],[InlineKeyboardButton(text='📄 Details',callback_data=f'pd:{pid}')]])
def inline_order(oid): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ Confirm',callback_data=f'oc:{oid}'),InlineKeyboardButton(text='❌ Reject',callback_data=f'or:{oid}')],[InlineKeyboardButton(text='📄 Details',callback_data=f'od:{oid}'),InlineKeyboardButton(text='👤 Customer',callback_data=f'ou:{oid}')]])

async def admin_ok(uid): return uid==MAIN_ADMIN or bool(await db.staff.find_one({'telegram_id':uid,'active':True,'permissions':'admin'}))
async def audit(actor,action,target=None,data=None): await db.audit.insert_one({'actor':actor,'action':action,'target':target,'data':data or {},'created_at':now()})
async def notify(text,markup=None):
    try: await bot.send_message(MAIN_ADMIN,text,reply_markup=markup)
    except Exception as e: log.warning('notify: %r',e)

async def init_db():
    # Legacy-safe indexes: reuse an existing number_1 even if its old sparse option differs.
    specs=[('users','telegram_id',True),('orders','order_id',True),('payments','payment_id',True),('numbers','number',True),('support','ticket_id',True),('audit','created_at',False)]
    for c,f,u in specs:
        try:
            info=await db[c].index_information(); name=f'{f}_1'
            if name in info and info[name].get('key')==[(f,1)] and bool(info[name].get('unique',False))==u: continue
            if name in info: await db[c].drop_index(name)
            await db[c].create_index(f,unique=u,name=name)
        except Exception as e: log.warning('index %s: %r',c,e)
    defaults={'registration_open':True,'orders_open':True,'payments_open':True,'support_open':True,'pending_minutes':10,'currency':'USD','website':TELESOM_SITE}
    for k,v in defaults.items():
        if await db.settings.find_one({'_id':k}) is None: await set_setting(k,v)
    for n,d in PAYMENTS.items(): await db.payment_methods.update_one({'name':n},{'$setOnInsert':{'name':n,'destination':d,'enabled':True}},upsert=True)
    await client.admin.command('ping')

async def show_catalog(m,category,title):
    docs=[]
    async for x in db.numbers.find({'category':category,'status':'available'}).limit(15): docs.append(x)
    if not docs:
        await m.answer(f'📭 <b>{title}</b>\n\nNo items are available right now.',reply_markup=back()); return
    buttons=[]
    for x in docs:
        label=f"{x['number']}  •  ${money(x.get('price')):.2f}"
        buttons.append([KeyboardButton(text=label)])
    await m.answer(f'✨ <b>{title}</b>\n\nChoose an available item:',reply_markup=kb([[b.text] for row in buttons for b in row]+[['🏠 Main Menu']]))

@router.message(CommandStart())
async def start(m:Message,state:FSMContext):
    await state.clear(); await ensure_user(m.from_user)
    if (await user(m)).get('status')=='banned': return await m.answer('🚫 Your account is unavailable.')
    await m.answer('🌐 <b>TELESOM SERVICE CENTER</b>\n\nWelcome. All services, orders and payments are available through the buttons below.\n\nChoose a service to continue.',reply_markup=admin_home() if await admin_ok(m.from_user.id) else home())

@router.message(F.text=='🏠 Main Menu')
async def main_menu(m,state:FSMContext): await state.clear(); await m.answer('🏠 <b>Main Menu</b>\n\nChoose a service.',reply_markup=admin_home() if await admin_ok(m.from_user.id) else home())

@router.message(F.text=='🌐 Language')
async def language(m): await m.answer('🌐 <b>Language</b>\n\nChoose your language:',reply_markup=kb([['🇬🇧 English','🇸🇴 Somali'],['🇸🇦 العربية'],['🏠 Main Menu']]))
@router.message(F.text.in_({'🇬🇧 English','🇸🇴 Somali','🇸🇦 العربية'}))
async def lang(m):
    code={'🇬🇧 English':'en','🇸🇴 Somali':'so','🇸🇦 العربية':'ar'}[m.text]; await db.users.update_one({'telegram_id':m.from_user.id},{'$set':{'language':code}}); await m.answer('✅ Language saved.',reply_markup=home())

@router.message(F.text.in_({'📱 Numbers','💎 VIP Numbers','🌐 Virtual Numbers','📲 eSIM','💳 Physical SIM'}))
async def products(m):
    cat={'📱 Numbers':'regular','💎 VIP Numbers':'vip','🌐 Virtual Numbers':'virtual','📲 eSIM':'esim','💳 Physical SIM':'sim'}[m.text]
    title=m.text; docs=[]
    # Randomized availability; VIP remains sorted by number quality when admin has entered quality values.
    cur=db.numbers.find({'category':cat,'status':'available'}).limit(100); arr=[x async for x in cur]; random.shuffle(arr); arr=arr[:15]
    if cat=='vip': arr.sort(key=lambda x:x.get('quality_score',0),reverse=True)
    if not arr: return await m.answer(f'📭 <b>{title}</b>\n\nNo items available now.',reply_markup=back())
    rows=[[f"{x['number']} • ${money(x.get('price')):.2f}"] for x in arr]; rows.append(['🏠 Main Menu']); await m.answer(f'✨ <b>{title}</b>\n\nChoose an item:',reply_markup=kb(rows))

@router.message(F.text.regexp(r'^\d{7,20} • \$[0-9]+(?:\.[0-9]{2})?$'))
async def choose_number(m,state):
    number=m.text.split(' • ')[0]; x=await db.numbers.find_one({'number':number,'status':'available'})
    if not x:return await m.answer('❌ This item is no longer available.',reply_markup=home())
    oid=uid('ORD'); await db.orders.insert_one({'order_id':oid,'user_id':m.from_user.id,'service':x['category'],'item_id':x['_id'],'item':number,'amount':money(x['price']),'status':'pending_payment','payment_status':'unpaid','created_at':now(),'updated_at':now()})
    await m.answer(f'🛒 <b>Order Created</b>\n\n📦 Order ID: <code>{oid}</code>\n📱 Number: <code>{tx(number)}</code>\n💰 Amount: <b>${money(x["price"]):.2f}</b>\n\n💵 Open <b>Payments</b> below to pay.\n\n⏳ <b>Pending 5–10 Min. Please wait ⏳</b>',reply_markup=home())
    await notify(f'🛒 <b>NEW ORDER</b>\n\n🆔 <code>{oid}</code>\n👤 <code>{m.from_user.id}</code>\n📦 {tx(x["category"])}\n📱 <code>{tx(number)}</code>\n💰 ${money(x["price"]):.2f}',inline_order(oid))

@router.message(F.text=='📡 Data')
async def data(m,state):
    await m.answer(f'📡 <b>Data Service</b>\n\nData packages are requested manually through Telesom.\n\n🌐 Website: {TELESOM_SITE}\n\nTap <b>REQUEST DATA</b> and send your Telesom number + package.',reply_markup=kb([['📡 REQUEST DATA'],['🏠 Main Menu']]))
@router.message(F.text=='📡 REQUEST DATA')
async def data_req(m,state): await state.set_state(Form.data); await m.answer('📡 Send your Telesom number and the data package you want.\n\nExample: 063xxxxxxx — 10GB',reply_markup=back())
@router.message(Form.data)
async def data_save(m,state):
    rid=uid('REQ'); await db.requests.insert_one({'request_id':rid,'kind':'data','user_id':m.from_user.id,'details':m.text,'status':'pending','created_at':now()}); await state.clear(); await m.answer(f'✅ <b>Data request received</b>\n\n🆔 <code>{rid}</code>\n⏳ Pending 5–10 Min. Please wait ⏳',reply_markup=home()); await notify(f'📡 <b>DATA REQUEST</b>\n🆔 <code>{rid}</code>\n👤 <code>{m.from_user.id}</code>\n📄 {tx(m.text)}',inline_order(rid))
@router.message(F.text=='📞 Voice')
async def voice(m): await m.answer(f'📞 <b>Voice Service</b>\n\nVoice packages are requested manually.\n\n🌐 {TELESOM_SITE}',reply_markup=kb([['📞 REQUEST VOICE'],['🏠 Main Menu']]))
@router.message(F.text=='📞 REQUEST VOICE')
async def vr(m,state): await state.set_state(Form.voice); await m.answer('📞 Send your Telesom number + voice package.',reply_markup=back())
@router.message(Form.voice)
async def vs(m,state):
    rid=uid('REQ'); await db.requests.insert_one({'request_id':rid,'kind':'voice','user_id':m.from_user.id,'details':m.text,'status':'pending','created_at':now()}); await state.clear(); await m.answer(f'✅ <b>Voice request received</b>\n\n🆔 <code>{rid}</code>\n⏳ Pending 5–10 Min. Please wait ⏳',reply_markup=home()); await notify(f'📞 <b>VOICE REQUEST</b>\n🆔 <code>{rid}</code>\n👤 <code>{m.from_user.id}</code>\n📄 {tx(m.text)}')
@router.message(F.text=='💬 SMS')
async def sms(m): await m.answer('💬 <b>SMS Service</b>\n\nSend your request manually.',reply_markup=kb([['💬 REQUEST SMS'],['🏠 Main Menu']]))
@router.message(F.text=='💬 REQUEST SMS')
async def sr(m,state): await state.set_state(Form.sms); await m.answer('💬 Send your Telesom number + SMS package/request.',reply_markup=back())
@router.message(Form.sms)
async def ss(m,state):
    rid=uid('REQ'); await db.requests.insert_one({'request_id':rid,'kind':'sms','user_id':m.from_user.id,'details':m.text,'status':'pending','created_at':now()}); await state.clear(); await m.answer(f'✅ <b>SMS request received</b>\n\n🆔 <code>{rid}</code>\n⏳ Pending 5–10 Min. Please wait ⏳',reply_markup=home()); await notify(f'💬 <b>SMS REQUEST</b>\n🆔 <code>{rid}</code>\n👤 <code>{m.from_user.id}</code>\n📄 {tx(m.text)}')

@router.message(F.text=='💵 Payments')
async def payments(m):
    if not await setting('payments_open',True): return await m.answer('🔒 Payments are temporarily unavailable.',reply_markup=home())
    orders=[x async for x in db.orders.find({'user_id':m.from_user.id,'status':{'$in':['pending_payment','payment_pending']}}).sort('created_at',-1).limit(10)]
    rows=[]
    for x in orders: rows.append([f'💳 PAY {x["order_id"]} • ${money(x.get("amount")):.2f}'])
    rows.append(['💰 Payment History']); rows.append(['🏠 Main Menu']); await m.answer('💵 <b>Payments</b>\n\nChoose the order you want to pay:',reply_markup=kb(rows))
@router.message(F.text.regexp(r'^💳 PAY ORD-[A-F0-9]+ • \$[0-9]+(?:\.[0-9]{2})?$'))
async def pay_select(m,state):
    oid=m.text.split(' ')[2]; o=await db.orders.find_one({'order_id':oid,'user_id':m.from_user.id})
    if not o:return await m.answer('❌ Order not found.',reply_markup=home())
    methods=[['📱 Golis','📱 Telesom'],['🪙 BNB','₮ USDT-BEP20'],['🏠 Main Menu']]
    await state.update_data(order_id=oid); await m.answer(f'💵 <b>Payment for {oid}</b>\n\n💰 Amount: <b>${money(o["amount"]):.2f}</b>\n\nSelect a payment method:',reply_markup=kb(methods))
@router.message(F.text.in_({'📱 Golis','📱 Telesom','🪙 BNB','₮ USDT-BEP20'}))
async def method(m,state):
    d=await state.get_data(); oid=d.get('order_id'); mp={'📱 Golis':'Golis','📱 Telesom':'Telesom','🪙 BNB':'BNB','₮ USDT-BEP20':'USDT-BEP20'}[m.text]; o=await db.orders.find_one({'order_id':oid,'user_id':m.from_user.id})
    if not o:return await m.answer('❌ Order expired.',reply_markup=home())
    dest=PAYMENTS[mp]
    await state.update_data(method=mp); await state.set_state(Form.payment)
    if mp in ('Golis','Telesom'): instruction=f'📞 <b>Payment Number</b>\n<code>{dest}</code>\n\nUse your phone/USSD payment, then send the transaction/reference number.'
    else: instruction=f'🪙 <b>{mp}</b>\n\nSend payment to:\n<code>{dest}</code>\n\nAfter sending, send the transaction hash/reference.'
    await m.answer(f'{instruction}\n\n💰 Amount: <b>${money(o["amount"]):.2f}</b>\n\nThen type the transaction/reference number below.',reply_markup=back())
@router.message(Form.payment)
async def payment_submit(m,state):
    d=await state.get_data(); oid=d.get('order_id'); mp=d.get('method'); o=await db.orders.find_one({'order_id':oid,'user_id':m.from_user.id})
    if not o:return await state.clear()
    pid=uid('PAY'); await db.payments.insert_one({'payment_id':pid,'order_id':oid,'user_id':m.from_user.id,'method':mp,'destination':PAYMENTS[mp],'amount':money(o['amount']),'reference':m.text,'status':'pending','created_at':now(),'updated_at':now()}); await db.orders.update_one({'order_id':oid},{'$set':{'status':'payment_pending','payment_id':pid,'updated_at':now()}}); await state.clear()
    await m.answer(f'✅ <b>Payment submitted</b>\n\n🆔 <code>{pid}</code>\n💰 ${money(o["amount"]):.2f}\n💳 {mp}\n\n⏳ <b>Pending 5–10 Min. Please wait ⏳</b>',reply_markup=home())
    await notify(f'💳 <b>NEW PAYMENT</b>\n\n🆔 <code>{pid}</code>\n📦 <code>{oid}</code>\n👤 <code>{m.from_user.id}</code>\n💰 ${money(o["amount"]):.2f}\n💳 {mp}\n🔖 <code>{tx(m.text)}</code>',inline_payment(pid))

@router.message(F.text=='💰 Payment History')
async def ph(m):
    rows=[f'💳 <code>{x["payment_id"]}</code> • ${money(x.get("amount")):.2f} • {tx(x.get("method"))} • {tx(x.get("status"))}' async for x in db.payments.find({'user_id':m.from_user.id}).sort('created_at',-1).limit(20)]
    await m.answer('💰 <b>Payment History</b>\n\n'+('\n'.join(rows) or 'No payments yet.'),reply_markup=home())

@router.message(F.text=='🛒 My Orders')
async def orders(m):
    rows=[f'📦 <code>{x["order_id"]}</code> • {tx(x.get("service"))} • ${money(x.get("amount")):.2f}\n   Status: <b>{tx(x.get("status"))}</b>' async for x in db.orders.find({'user_id':m.from_user.id}).sort('created_at',-1).limit(20)]
    await m.answer('🛒 <b>My Orders</b>\n\n'+('\n\n'.join(rows) or 'No orders yet.'),reply_markup=home())
@router.message(F.text=='💰 Wallet')
async def wallet(m):
    u=await user(m); w=u.get('wallet',{}); await m.answer(f'💰 <b>Wallet</b>\n\nAvailable: <b>${money(w.get("available")):.2f}</b>\nPending: <b>${money(w.get("pending")):.2f}</b>\nTotal deposited: ${money(u.get("total_deposited")):.2f}\nTotal spent: ${money(u.get("total_spent")):.2f}',reply_markup=home())
@router.message(F.text=='👤 My Profile')
async def profile(m):
    u=await user(m); await m.answer(f'👤 <b>My Profile</b>\n\n🆔 <code>{m.from_user.id}</code>\n👤 {tx(m.from_user.full_name)}\n🔗 @{tx(m.from_user.username or "none")}\n🌐 Language: {tx(u.get("language"))}\n📊 Status: {tx(u.get("status"))}',reply_markup=home())
@router.message(F.text=='👥 Referral')
async def referral(m):
    u=await user(m); await m.answer(f'👥 <b>Referral</b>\n\nYour referral code: <code>{m.from_user.id}</code>\nReferrals: <b>{int(u.get("referrals",0))}</b>',reply_markup=home())
@router.message(F.text=='🎁 Offers')
async def offers(m):
    rows=[f'🎁 <b>{tx(x.get("title"))}</b>\n{tx(x.get("text"))}' async for x in db.offers.find({'enabled':True}).limit(20)]; await m.answer('🎁 <b>Offers</b>\n\n'+('\n\n'.join(rows) or 'No active offers.'),reply_markup=home())
@router.message(F.text=='🆘 Customer Support')
async def support(m,state): await state.set_state(Form.support); await m.answer('🆘 <b>Customer Support</b>\n\nSend your message. Our team will receive it.',reply_markup=back())
@router.message(Form.support)
async def support_save(m,state):
    tid=uid('TKT'); await db.support.insert_one({'ticket_id':tid,'user_id':m.from_user.id,'message':m.text,'status':'open','created_at':now()}); await state.clear(); await m.answer(f'✅ <b>Support request received</b>\n\n🆔 <code>{tid}</code>\n⏳ Pending 5–10 Min. Please wait ⏳',reply_markup=home()); await notify(f'🆘 <b>SUPPORT</b>\n🆔 <code>{tid}</code>\n👤 <code>{m.from_user.id}</code>\n💬 {tx(m.text)}')
@router.message(F.text=='🔋 Recharge')
async def recharge(m): await m.answer('🔋 <b>Recharge</b>\n\nRecharge requests are handled through the service center.\n\nSend your Telesom number and amount after tapping REQUEST RECHARGE.',reply_markup=kb([['🔋 REQUEST RECHARGE'],['🏠 Main Menu']]))
@router.message(F.text=='🔋 REQUEST RECHARGE')
async def recharge_req(m): await m.answer('Please send your Telesom number + recharge amount.',reply_markup=back()); await m.bot.get_context(m.chat.id) if False else None

# Admin button entry. Commands other than /start are intentionally not registered.
@router.message(F.text=='🛠️ ADMIN PANEL TELESOM')
async def admin_panel(m):
    if not await admin_ok(m.from_user.id): return await m.answer('❌ Access denied.')
    await m.answer('🛡️ <b>TELESOM ADMIN CONTROL CENTER</b>\n\nChoose any panel. Everything is controlled with buttons.',reply_markup=admin_home())

@router.message(F.text.regexp(r'^🛠️ (?:[1-9]|[1-9][0-9]|100)\.'))
async def admin_panel_button(m,state):
    if not await admin_ok(m.from_user.id): return
    n=int(re.match(r'^🛠️ (\d+)',m.text).group(1)); name=PANELS[n-1]
    counts={'Dashboard':await db.users.count_documents({}),'Customers':await db.users.count_documents({}),'Numbers':await db.numbers.count_documents({'category':'regular'}),'VIP Numbers':await db.numbers.count_documents({'category':'vip'}),'Virtual Numbers':await db.numbers.count_documents({'category':'virtual'}),'eSIM':await db.numbers.count_documents({'category':'esim'}),'Physical SIM':await db.numbers.count_documents({'category':'sim'}),'Payments':await db.payments.count_documents({}),'Orders':await db.orders.count_documents({}),'Support':await db.support.count_documents({}),'Offers':await db.offers.count_documents({}),'Promo Codes':await db.promos.count_documents({}),'Staff & Permissions':await db.staff.count_documents({})}
    c=counts.get(name,await db.audit.count_documents({}))
    await m.answer(f'🛠️ <b>{name}</b>\n\n📊 Records: <b>{c}</b>\n\nChoose an action:',reply_markup=admin_actions(name))
def admin_actions(name):
    if name in ('Numbers','VIP Numbers','Virtual Numbers','eSIM','Physical SIM','Inventory','Inventory Add'): return kb([['➕ Add Item','📋 View Items'],['🗑 Remove Item','🔄 Toggle Item'],['🏠 Admin Home']])
    if name in ('Payments','Payment Methods','Payment Verification','Deposits'): return kb([['💳 Pending Payments','📋 Payment History'],['💰 Payment Methods','🏠 Admin Home']])
    if name in ('Orders','Pending Orders','Completed Orders','Rejected Orders','Fulfilment Queue'): return kb([['⏳ Pending Orders','📋 All Orders'],['🏠 Admin Home']])
    if name=='Customers' or name.startswith('Customer'): return kb([['👥 Customer List','🔎 Search Customer'],['🚫 Ban Customer','✅ Unban Customer'],['🏠 Admin Home']])
    if name=='Broadcast': return kb([['📢 Send Broadcast','📜 Broadcast History'],['🏠 Admin Home']])
    if name in ('Offers','Offer Create','Offer Toggle'): return kb([['➕ Add Offer','📋 View Offers'],['🏠 Admin Home']])
    if name in ('Promo Codes','Promo Create','Promo Toggle'): return kb([['➕ Add Promo','📋 View Promos'],['🏠 Admin Home']])
    if name in ('Staff & Permissions','Admin Roles','Admin Permissions'): return kb([['➕ Add Staff','📋 Staff List'],['🏠 Admin Home']])
    return kb([['📊 View Records','⚙️ Settings'],['🏠 Admin Home']])

def is_admin_action(m): return admin_ok(m.from_user.id)

@router.message(F.text=='⏳ Pending Orders')
async def pending_orders(m):
    if not await admin_ok(m.from_user.id): return
    n=0
    async for x in db.orders.find({'status':{'$in':['pending_payment','payment_pending','pending']}}).sort('created_at',-1).limit(30):
        await m.answer(f'⏳ <b>PENDING ORDER</b>\n\n📦 <code>{x["order_id"]}</code>\n👤 <code>{x["user_id"]}</code>\n💰 ${money(x.get("amount")):.2f}\n📌 {tx(x.get("service"))}\n📱 {tx(x.get("item"))}',reply_markup=inline_order(x['order_id'])); n+=1
    if not n: await m.answer('✅ No pending orders.')
@router.message(F.text=='💳 Pending Payments')
async def pending_payments(m):
    if not await admin_ok(m.from_user.id): return
    n=0
    async for x in db.payments.find({'status':'pending'}).sort('created_at',-1).limit(30):
        await m.answer(f'💳 <b>PENDING PAYMENT</b>\n\n🆔 <code>{x["payment_id"]}</code>\n📦 <code>{x["order_id"]}</code>\n👤 <code>{x["user_id"]}</code>\n💰 ${money(x["amount"]):.2f}\n💳 {tx(x["method"])}\n🔖 {tx(x.get("reference"))}',reply_markup=inline_payment(x['payment_id'])); n+=1
    if not n: await m.answer('✅ No pending payments.')

@router.message(F.text=='➕ Add Item')
async def additem(m,state):
    if not await admin_ok(m.from_user.id): return
    await state.set_state(Form.number); await m.answer('➕ Send: NUMBER | PRICE | CATEGORY\n\nCategories: regular, vip, virtual, esim, sim\n\nExample: 0634551111 | 5 | vip',reply_markup=kb([['🏠 Admin Home']]))
@router.message(Form.number)
async def additem_save(m,state):
    try:
        p=[x.strip() for x in m.text.split('|')]; number=p[0]; price=money(p[1]); cat=p[2].lower();
        if cat not in {'regular','vip','virtual','esim','sim'}: raise ValueError()
        quality=0
        if cat=='vip': quality=sum(1 for a,b in zip(number,number[1:]) if a==b)*10 + (30 if re.search(r'(\d)\1\1',number) else 0)
        await db.numbers.update_one({'number':number},{'$set':{'number':number,'price':price,'category':cat,'quality_score':quality,'status':'available','updated_at':now()},'$setOnInsert':{'created_at':now()}},upsert=True); await audit(m.from_user.id,'inventory_upsert',number,{'category':cat,'price':price}); await state.clear(); await m.answer(f'✅ Item saved.\n\n{number} • ${price:.2f} • {cat}',reply_markup=admin_home())
    except: await m.answer('❌ Format error. Use NUMBER | PRICE | CATEGORY')

@router.message(F.text=='📋 View Items')
async def viewitems(m):
    if not await admin_ok(m.from_user.id): return
    rows=[f'{tx(x["number"])} • ${money(x.get("price")):.2f} • {tx(x.get("category"))}' async for x in db.numbers.find({}).sort('created_at',-1).limit(50)]; await m.answer('📋 <b>Inventory</b>\n\n'+('\n'.join(rows) or 'Empty.'),reply_markup=admin_home())
@router.message(F.text=='📢 Send Broadcast')
async def broad(m,state):
    if not await admin_ok(m.from_user.id): return
    await state.set_state(Form.broadcast); await m.answer('📢 Send the message to broadcast to every non-banned customer who has used this bot.',reply_markup=kb([['🏠 Admin Home']]))
@router.message(Form.broadcast)
async def broad_send(m,state):
    if not await admin_ok(m.from_user.id): return
    sent=0
    async for u in db.users.find({'status':{'$ne':'banned'}},{'telegram_id':1}):
        try: await bot.send_message(u['telegram_id'],m.text); sent+=1
        except: pass
    await db.notifications.insert_one({'type':'broadcast','text':m.text,'sent':sent,'created_at':now()}); await audit(m.from_user.id,'broadcast',data={'sent':sent}); await state.clear(); await m.answer(f'📢 <b>Broadcast complete</b>\n\nSent: <b>{sent}</b>',reply_markup=admin_home())
@router.message(F.text=='📋 Payment History')
async def admin_ph(m):
    if not await admin_ok(m.from_user.id): return
    rows=[f'<code>{x["payment_id"]}</code> • ${money(x.get("amount")):.2f} • {tx(x.get("method"))} • {tx(x.get("status"))}' async for x in db.payments.find({}).sort('created_at',-1).limit(50)]; await m.answer('📋 <b>Payments</b>\n\n'+('\n'.join(rows) or 'None.'),reply_markup=admin_home())
@router.message(F.text=='📋 All Orders')
async def admin_orders(m):
    if not await admin_ok(m.from_user.id): return
    rows=[f'<code>{x["order_id"]}</code> • {tx(x.get("service"))} • ${money(x.get("amount")):.2f} • {tx(x.get("status"))}' async for x in db.orders.find({}).sort('created_at',-1).limit(50)]; await m.answer('📋 <b>Orders</b>\n\n'+('\n'.join(rows) or 'None.'),reply_markup=admin_home())
@router.message(F.text=='👥 Customer List')
async def customers(m):
    if not await admin_ok(m.from_user.id): return
    rows=[f'<code>{x["telegram_id"]}</code> • @{tx(x.get("username") or "none")} • {tx(x.get("status"))}' async for x in db.users.find({}).sort('created_at',-1).limit(50)]; await m.answer('👥 <b>Customers</b>\n\n'+('\n'.join(rows) or 'None.'),reply_markup=admin_home())
@router.message(F.text=='📊 View Records')
async def records(m):
    if not await admin_ok(m.from_user.id): return
    vals={k:await db[k].count_documents({}) for k in ['users','orders','payments','numbers','support','offers','promos','staff','audit']}; await m.answer('📊 <b>SYSTEM OVERVIEW</b>\n\n'+'\n'.join(f'{k.title()}: <b>{v}</b>' for k,v in vals.items()),reply_markup=admin_home())
@router.message(F.text=='⚙️ Settings')
async def settings(m):
    if not await admin_ok(m.from_user.id): return
    await m.answer(f'⚙️ <b>System Settings</b>\n\nRegistration: {await setting("registration_open",True)}\nOrders: {await setting("orders_open",True)}\nPayments: {await setting("payments_open",True)}\nSupport: {await setting("support_open",True)}\nPending message: 5–10 Min\nWebsite: {TELESOM_SITE}',reply_markup=admin_home())

@admin_router.callback_query(F.data.startswith('pc:'))
async def pc(c:CallbackQuery):
    if not await admin_ok(c.from_user.id): return await c.answer('Access denied',show_alert=True)
    pid=c.data[3:]; p=await db.payments.find_one_and_update({'payment_id':pid,'status':'pending'},{'$set':{'status':'confirmed','confirmed_by':c.from_user.id,'confirmed_at':now()}})
    if not p:return await c.answer('Already processed',show_alert=True)
    await db.orders.update_one({'order_id':p['order_id']},{'$set':{'payment_status':'paid','status':'processing','updated_at':now()}})
    await db.users.update_one({'telegram_id':p['user_id']},{'$inc':{'wallet.pending':-money(p['amount']),'wallet.available':money(p['amount']),'total_deposited':money(p['amount'])}}); await audit(c.from_user.id,'payment_confirmed',pid)
    await c.message.edit_reply_markup(reply_markup=None); await c.answer('Confirmed'); await bot.send_message(p['user_id'],f'✅ <b>Payment confirmed</b>\n\n🆔 <code>{pid}</code>\n📦 <code>{p["order_id"]}</code>\n\nYour order is now being processed.');
@admin_router.callback_query(F.data.startswith('pr:'))
async def pr(c:CallbackQuery):
    if not await admin_ok(c.from_user.id): return await c.answer('Access denied',show_alert=True)
    pid=c.data[3:]; p=await db.payments.find_one_and_update({'payment_id':pid,'status':'pending'},{'$set':{'status':'rejected','rejected_by':c.from_user.id,'rejected_at':now()}})
    if not p:return await c.answer('Already processed',show_alert=True)
    await db.orders.update_one({'order_id':p['order_id']},{'$set':{'status':'payment_rejected','updated_at':now()}}); await db.users.update_one({'telegram_id':p['user_id']},{'$inc':{'wallet.pending':-money(p['amount'])}}); await audit(c.from_user.id,'payment_rejected',pid); await c.message.edit_reply_markup(reply_markup=None); await c.answer('Rejected'); await bot.send_message(p['user_id'],f'❌ <b>Payment not accepted</b>\n\n🆔 <code>{pid}</code>\nPlease submit a valid payment.');
@admin_router.callback_query(F.data.startswith('pd:'))
async def pd(c:CallbackQuery):
    if not await admin_ok(c.from_user.id): return await c.answer('Access denied',show_alert=True)
    p=await db.payments.find_one({'payment_id':c.data[3:]});
    if not p:return await c.answer('Not found',show_alert=True)
    await c.message.answer(f'📄 <b>Payment Details</b>\n\nID: <code>{p["payment_id"]}</code>\nOrder: <code>{p["order_id"]}</code>\nUser: <code>{p["user_id"]}</code>\nMethod: {tx(p["method"])}\nAmount: ${money(p["amount"]):.2f}\nReference: <code>{tx(p.get("reference"))}</code>'); await c.answer()
@admin_router.callback_query(F.data.startswith('oc:'))
async def oc(c:CallbackQuery):
    if not await admin_ok(c.from_user.id): return await c.answer('Access denied',show_alert=True)
    oid=c.data[3:]; o=await db.orders.find_one_and_update({'order_id':oid,'status':{'$in':['pending_payment','payment_pending','pending']}},{'$set':{'status':'processing','confirmed_by':c.from_user.id,'updated_at':now()}})
    if not o:return await c.answer('Already processed',show_alert=True)
    await audit(c.from_user.id,'order_confirmed',oid); await c.message.edit_reply_markup(reply_markup=None); await c.answer('Confirmed'); await bot.send_message(o['user_id'],f'✅ <b>Order confirmed</b>\n\n📦 <code>{oid}</code>\n⏳ <b>Pending 5–10 Min. Please wait ⏳</b>')
@admin_router.callback_query(F.data.startswith('or:'))
async def orr(c:CallbackQuery):
    if not await admin_ok(c.from_user.id): return await c.answer('Access denied',show_alert=True)
    oid=c.data[3:]; o=await db.orders.find_one_and_update({'order_id':oid,'status':{'$in':['pending_payment','payment_pending','pending']}},{'$set':{'status':'rejected','updated_at':now()}})
    if not o:return await c.answer('Already processed',show_alert=True)
    await audit(c.from_user.id,'order_rejected',oid); await c.message.edit_reply_markup(reply_markup=None); await c.answer('Rejected'); await bot.send_message(o['user_id'],f'❌ <b>Order rejected</b>\n\n📦 <code>{oid}</code>')
@admin_router.callback_query(F.data.startswith('od:'))
async def od(c:CallbackQuery):
    if not await admin_ok(c.from_user.id): return await c.answer('Access denied',show_alert=True)
    o=await db.orders.find_one({'order_id':c.data[3:]});
    if not o:return await c.answer('Not found',show_alert=True)
    await c.message.answer(f'📄 <b>Order Details</b>\n\nID: <code>{o["order_id"]}</code>\nUser: <code>{o["user_id"]}</code>\nService: {tx(o.get("service"))}\nItem: {tx(o.get("item"))}\nAmount: ${money(o.get("amount")):.2f}\nStatus: {tx(o.get("status"))}'); await c.answer()
@admin_router.callback_query(F.data.startswith('ou:'))
async def ou(c:CallbackQuery):
    if not await admin_ok(c.from_user.id): return await c.answer('Access denied',show_alert=True)
    o=await db.orders.find_one({'order_id':c.data[3:]});
    if o: await c.message.answer(f'👤 Customer Telegram ID: <code>{o["user_id"]}</code>');
    await c.answer()

@router.message()
async def fallback(m:Message,state:FSMContext):
    u=await db.users.find_one({'telegram_id':m.from_user.id})
    if u and u.get('status')=='banned': return await m.answer('🚫 Your account is unavailable.')
    await m.answer('Please use the buttons below.',reply_markup=admin_home() if await admin_ok(m.from_user.id) else home())

async def health(r): return web.json_response({'status':'ok','service':'Telesombot'})
async def main():
    await init_db(); await bot.delete_webhook(drop_pending_updates=False)
    app=web.Application(); app.router.add_get('/',health); app.router.add_get('/health',health); runner=web.AppRunner(app); await runner.setup(); await web.TCPSite(runner,'0.0.0.0',PORT).start(); log.info('Telesombot started')
    try: await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
    finally: await runner.cleanup(); await bot.session.close(); client.close()
if __name__=='__main__': asyncio.run(main())
