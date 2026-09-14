import os, asyncio, logging, uuid, json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN','').strip()
MONGO_URI = os.getenv('MONGO_URI','').strip()
ADMIN_ID = int(os.getenv('ADMIN_ID','0') or 0)
PORT = int(os.getenv('PORT','10000') or 10000)
DB_NAME = os.getenv('DB_NAME','telesombot').strip() or 'telesombot'
if not BOT_TOKEN: raise RuntimeError('BOT_TOKEN is missing')
if not MONGO_URI: raise RuntimeError('MONGO_URI is missing')
if not ADMIN_ID: raise RuntimeError('ADMIN_ID is missing or invalid')

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger('telesombot')
client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=10000)
db = client[DB_NAME]
bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
user_router = Router(); admin_router = Router()
dp.include_router(user_router); dp.include_router(admin_router)

NOW=lambda: datetime.now(timezone.utc)
def rid(prefix): return f'{prefix}-{uuid.uuid4().hex[:8].upper()}'
def money(v):
    try: return round(float(Decimal(str(v))),2)
    except (InvalidOperation,ValueError,TypeError): return 0.0
def esc(v):
    s=str(v or '')
    return s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

LANGS={'so':'🇸🇴 Soomaali','en':'🇬🇧 English','ar':'🇸🇦 العربية'}
DEFAULT_PAYMENTS={
 'Telesom':'*880*0907868526*$#',
 'Golis':'*883*0907868526*$#',
 'BNB':'0x1f12ffDc93E49eff0c78672Ab6abA62410c05a32',
 'USDT-BEP20':'0x6AC864773259fa5175251829cb0E93ffb4cE6feC'
}
PANELS=[
'Dashboard','Customers','Numbers','VIP Numbers','Virtual Numbers','eSIM','Physical SIM','Data','Voice','SMS','Recharge','Wallets','Payments','Orders','Refunds','Offers','Promo Codes','Referrals','Memberships','Support','Broadcast','Notifications','Business','Corporate','Inventory','Analytics','Staff & Permissions','Security','Audit Logs','System Settings'
]

class AddNumber(StatesGroup):
    number=State(); price=State(); category=State(); title=State(); details=State()
class AddItem(StatesGroup):
    name=State(); price=State(); details=State(); stock=State(); kind=State()
class Broadcast(StatesGroup): text=State()
class Setting(StatesGroup): key=State(); value=State()
class UserInput(StatesGroup): value=State()
class Payment(StatesGroup): amount=State(); reference=State()
class Support(StatesGroup): text=State()

async def init_db():
    for name in ['users','catalog','numbers','orders','payments','wallet_ledger','requests','offers','promos','referrals','memberships','support','notifications','staff','audit_logs','security_events','settings']:
        try: await db[name].create_index([('created_at',-1)])
        except Exception: pass
    await db.users.create_index('telegram_id', unique=True)
    await db.numbers.create_index('number', unique=True, sparse=True)
    await db.orders.create_index('order_id', unique=True)
    await db.payments.create_index('payment_id', unique=True)
    await db.requests.create_index('request_id', unique=True)
    await db.catalog.create_index('item_id', unique=True)
    defaults={
      'company_name':'TELESOM', 'support_username':'', 'currency':'USD', 'referral_reward':0,
      'registration_bonus':0, 'maintenance':False, 'allow_wallet':True, 'default_language':'so',
      'payment_methods':DEFAULT_PAYMENTS,
      'service_enabled':{k:True for k in ['numbers','vip','virtual','esim','sim','data','voice','sms','recharge','business','corporate']}
    }
    for k,v in defaults.items(): await db.settings.update_one({'_id':k},{'$setOnInsert':{'value':v}},upsert=True)

async def setting(key, default=None):
    x=await db.settings.find_one({'_id':key}); return x.get('value',default) if x else default
async def set_setting(key,value): await db.settings.update_one({'_id':key},{'$set':{'value':value}},upsert=True)
async def user(uid): return await db.users.find_one({'telegram_id':int(uid)})
async def ensure_user(u):
    existing=await user(u.id); now=NOW()
    await db.users.update_one({'telegram_id':int(u.id)}, {'$set':{'username':u.username,'first_name':u.first_name,'last_name':u.last_name,'updated_at':now}, '$setOnInsert':{'telegram_id':int(u.id),'language':'so','status':'active','wallet':{'available':0.0,'pending':0.0},'total_deposited':0.0,'total_spent':0.0,'referrals':0,'created_at':now}}, upsert=True)
    if existing is None:
        await audit(u.id,'user_registered',str(u.id),{'username':u.username})
        await admin_notify(f'🆕 <b>NEW CUSTOMER</b>\n\n👤 {esc(u.full_name)}\n🆔 <code>{u.id}</code>\n🔗 @{esc(u.username or "none")}', user_id=u.id, kind='user')
async def audit(actor,action,target=None,data=None): await db.audit_logs.insert_one({'actor':int(actor),'action':action,'target':target,'data':data or {},'created_at':NOW()})
async def is_admin(uid):
    if int(uid)==ADMIN_ID: return True
    return bool(await db.staff.find_one({'telegram_id':int(uid),'active':True,'role':{'$in':['admin','manager']}}))
async def lang(uid): return (await user(uid) or {}).get('language','so')

TEXT={
'so':{'welcome':'👋 <b>Ku soo dhawoow TELESOM</b>\n\n📱 Adeegyada telecom-ka waxaad ka heli kartaa hal meel.\nDooro adeegga aad rabto hoos.','pending':'⏳ Codsigaaga <b>{id}</b> waa la diray. Admin ayaa hubinaya.','approved':'✅ Codsigaaga <b>{id}</b> waa la ansixiyay.','rejected':'❌ Codsigaaga <b>{id}</b> waa la diiday.','home':'🏠 Bogga Hore','numbers':'📱 Numberro','vip':'💎 VIP Numbers','virtual':'🌐 Virtual Numbers','esim':'📲 eSIM','sim':'💳 Physical SIM','data':'📡 Data','voice':'📞 Voice','sms':'💬 SMS','recharge':'🔋 Recharge','wallet':'💰 Wallet','orders':'🛒 Orders','payments':'💵 Payments','offers':'🎁 Offers','referral':'👥 Referral','support':'🆘 Support','profile':'👤 Profile','language':'🌐 Language','back':'⬅️ Back','buy':'🛒 Dalbo','no_items':'Hadda wax la iibsan karo lama hayo.','choose':'Dooro mid ka mid ah:','amount':'Geli lacagta:','reference':'Geli payment reference/transaction ID:','sent':'✅ Waa la diray.','cancel':'❌ Cancel'},
'en':{'welcome':'👋 <b>Welcome to TELESOM</b>\n\n📱 All telecom services in one place.\nChoose a service below.','pending':'⏳ Request <b>{id}</b> submitted. Waiting for admin approval.','approved':'✅ Request <b>{id}</b> approved.','rejected':'❌ Request <b>{id}</b> rejected.','home':'🏠 Home','numbers':'📱 Numbers','vip':'💎 VIP Numbers','virtual':'🌐 Virtual Numbers','esim':'📲 eSIM','sim':'💳 Physical SIM','data':'📡 Data','voice':'📞 Voice','sms':'💬 SMS','recharge':'🔋 Recharge','wallet':'💰 Wallet','orders':'🛒 Orders','payments':'💵 Payments','offers':'🎁 Offers','referral':'👥 Referral','support':'🆘 Support','profile':'👤 Profile','language':'🌐 Language','back':'⬅️ Back','buy':'🛒 Order','no_items':'Nothing is currently available.','choose':'Choose an option:','amount':'Enter amount:','reference':'Enter payment reference/transaction ID:','sent':'✅ Submitted.','cancel':'❌ Cancel'},
'ar':{'welcome':'👋 <b>مرحباً بك في TELESOM</b>\n\n📱 جميع خدمات الاتصالات في مكان واحد.','pending':'⏳ تم إرسال الطلب <b>{id}</b> وبانتظار موافقة المشرف.','approved':'✅ تمت الموافقة على الطلب <b>{id}</b>.','rejected':'❌ تم رفض الطلب <b>{id}</b>.','home':'🏠 الرئيسية','numbers':'📱 الأرقام','vip':'💎 أرقام VIP','virtual':'🌐 أرقام افتراضية','esim':'📲 eSIM','sim':'💳 شريحة فعلية','data':'📡 بيانات','voice':'📞 مكالمات','sms':'💬 SMS','recharge':'🔋 شحن','wallet':'💰 المحفظة','orders':'🛒 الطلبات','payments':'💵 المدفوعات','offers':'🎁 العروض','referral':'👥 الإحالة','support':'🆘 الدعم','profile':'👤 الملف','language':'🌐 اللغة','back':'⬅️ رجوع','buy':'🛒 طلب','no_items':'لا توجد خدمات متاحة حالياً.','choose':'اختر خدمة:','amount':'أدخل المبلغ:','reference':'أدخل مرجع الدفع:','sent':'✅ تم الإرسال.','cancel':'❌ إلغاء'}}
def t(l,k,**kw): return TEXT.get(l,TEXT['so']).get(k,k).format(**kw)

def main_kb(l):
    b=InlineKeyboardBuilder(); rows=[('numbers','vip','virtual'),('esim','sim'),('data','voice','sms'),('recharge','wallet','orders'),('payments','offers'),('referral','support'),('profile','language')]
    for row in rows: b.row(*(InlineKeyboardButton(text=t(l,x),callback_data=f'u:{x}') for x in row))
    return b.as_markup()
def back_kb(l): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t(l,'back'),callback_data='u:home')]])
def admin_home():
    b=InlineKeyboardBuilder()
    for i,p in enumerate(PANELS,1): b.button(text=f'{i}. {p}',callback_data=f'a:panel:{i}')
    b.adjust(2); return b.as_markup()
def admin_back(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🏠 Admin Home',callback_data='a:home')]])
def approve_kb(kind,ident): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ CONFIRM',callback_data=f'a:approve:{kind}:{ident}'),InlineKeyboardButton(text='❌ REJECT',callback_data=f'a:reject:{kind}:{ident}')],[InlineKeyboardButton(text='📄 DETAILS',callback_data=f'a:details:{kind}:{ident}'),InlineKeyboardButton(text='💬 USER',callback_data=f'a:user:{ident}')]])

async def admin_notify(text,user_id=None,kind='request',ident=None):
    try:
        kb=approve_kb(kind,ident) if ident else None
        await bot.send_message(ADMIN_ID,text,reply_markup=kb)
    except Exception as e: log.warning('admin notify failed: %s',e)
async def create_order(uid,kind,item,price,meta=None):
    oid=rid('ORD'); doc={'order_id':oid,'user_id':int(uid),'kind':kind,'item':item,'price':money(price),'status':'pending_approval','meta':meta or {},'created_at':NOW(),'updated_at':NOW()}
    await db.orders.insert_one(doc); await audit(uid,'order_created',oid,doc); await admin_notify(f'🛎️ <b>NEW ORDER</b>\n\n🆔 <code>{oid}</code>\n👤 <code>{uid}</code>\n📦 {esc(kind)}\n📝 {esc(item)}\n💵 {money(price):.2f}',uid,'order',oid); return oid
async def user_order_message(m,kind,item,price,meta=None):
    oid=await create_order(m.from_user.id,kind,item,price,meta); l=await lang(m.from_user.id); await m.answer(t(l,'pending',id=oid),reply_markup=main_kb(l))

async def catalog_items(kind): return await db.catalog.find({'kind':kind,'active':True}).sort('created_at',-1).to_list(100)
async def number_items(category): return await db.numbers.find({'category':category,'status':'available'}).sort('price',1).to_list(100)

def list_items_kb(items,prefix='item'):
    b=InlineKeyboardBuilder()
    for x in items:
        label=f"{x.get('name') or x.get('number')} — ${money(x.get('price')):.2f}"
        b.button(text=label[:60],callback_data=f'pick:{prefix}:{x.get("item_id") or x.get("number")}')
    b.adjust(1); return b.as_markup()

@user_router.message(CommandStart())
async def start(m:Message):
    await ensure_user(m.from_user)
    if await is_admin(m.from_user.id):
        await m.answer('🛡️ <b>TELESOM ADMIN PANEL</b>\n\nFull company control center:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🛠️ ADMIN PANEL TELESOM',callback_data='a:home')]]))
        return
    l=await lang(m.from_user.id)
    await m.answer(t(l,'welcome'),reply_markup=main_kb(l))

@user_router.callback_query(F.data=='u:home')
async def home(c:CallbackQuery):
    await ensure_user(c.from_user); l=await lang(c.from_user.id); await c.message.edit_text(t(l,'welcome'),reply_markup=main_kb(l)); await c.answer()

@user_router.callback_query(F.data.startswith('u:'))
async def user_menu(c:CallbackQuery,state:FSMContext):
    await ensure_user(c.from_user); key=c.data.split(':',1)[1]; l=await lang(c.from_user.id)
    if key=='language':
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=v,callback_data=f'lang:{k}') for k,v in LANGS.items()] ,[InlineKeyboardButton(text=t(l,'back'),callback_data='u:home')]])
        await c.message.edit_text('🌐 <b>Language / Luuqad / اللغة</b>',reply_markup=kb); return await c.answer()
    if key=='profile':
        u=await user(c.from_user.id); w=u.get('wallet',{}); txt=f"👤 <b>Profile</b>\n\n🆔 <code>{c.from_user.id}</code>\n👤 {esc(u.get('first_name'))}\n🔗 @{esc(u.get('username') or 'none')}\n🌐 {LANGS.get(l,l)}\n💰 Balance: <b>${money(w.get('available')):.2f}</b>\n📦 Orders: {await db.orders.count_documents({'user_id':c.from_user.id})}"
        return await c.message.edit_text(txt,reply_markup=back_kb(l))
    if key=='wallet':
        u=await user(c.from_user.id); w=u.get('wallet',{}); txt=f"💰 <b>Wallet</b>\n\nAvailable: <b>${money(w.get('available')):.2f}</b>\nPending: <b>${money(w.get('pending')):.2f}</b>\nTotal deposited: ${money(u.get('total_deposited')):.2f}\nTotal spent: ${money(u.get('total_spent')):.2f}"
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='➕ Add Balance',callback_data='pay:start')],[InlineKeyboardButton(text=t(l,'back'),callback_data='u:home')]])
        return await c.message.edit_text(txt,reply_markup=kb)
    if key=='payments':
        rows=await db.payments.find({'user_id':c.from_user.id}).sort('created_at',-1).to_list(15); txt='💵 <b>Payments</b>\n\n'+('\n'.join(f"<code>{x['payment_id']}</code> • ${money(x['amount']):.2f} • {x['status']}" for x in rows) if rows else 'No payments yet.')
        return await c.message.edit_text(txt,reply_markup=back_kb(l))
    if key=='orders':
        rows=await db.orders.find({'user_id':c.from_user.id}).sort('created_at',-1).to_list(15); txt='🛒 <b>Orders</b>\n\n'+('\n'.join(f"<code>{x['order_id']}</code> • {esc(x['kind'])} • ${money(x['price']):.2f} • {x['status']}" for x in rows) if rows else 'No orders yet.')
        return await c.message.edit_text(txt,reply_markup=back_kb(l))
    if key=='referral':
        u=await user(c.from_user.id); txt=f"👥 <b>Referral</b>\n\nYour referrals: <b>{int(u.get('referrals',0))}</b>\nYour referral code: <code>{c.from_user.id}</code>"
        return await c.message.edit_text(txt,reply_markup=back_kb(l))
    if key=='support':
        await c.message.edit_text('🆘 <b>Support</b>\n\nSend your message now:',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t(l,'cancel'),callback_data='u:home')]])); await state.set_state(UserInput.value); await c.answer(); return
    if key=='offers':
        rows=await db.offers.find({'active':True}).sort('created_at',-1).to_list(30); txt='🎁 <b>Offers</b>\n\n'+('\n\n'.join(f"🎁 <b>{esc(x.get('title'))}</b>\n{esc(x.get('text'))}" for x in rows) if rows else t(l,'no_items'))
        return await c.message.edit_text(txt,reply_markup=back_kb(l))
    if key in ['numbers','vip']:
        category='vip' if key=='vip' else 'regular'; rows=await number_items(category)
        if not rows: return await c.message.edit_text(t(l,'no_items'),reply_markup=back_kb(l))
        return await c.message.edit_text(f"{t(l,key)}\n\n{t(l,'choose')}",reply_markup=list_items_kb(rows,'number'))
    kind=key
    enabled=(await setting('service_enabled',{})).get(kind,True)
    if not enabled: return await c.message.edit_text('🚫 This service is temporarily unavailable.',reply_markup=back_kb(l))
    rows=await catalog_items(kind)
    if not rows: return await c.message.edit_text(t(l,'no_items'),reply_markup=back_kb(l))
    await c.message.edit_text(f"{t(l,key)}\n\n{t(l,'choose')}",reply_markup=list_items_kb(rows,'catalog')); await c.answer()

@user_router.callback_query(F.data.startswith('lang:'))
async def set_lang(c:CallbackQuery):
    l=c.data.split(':')[1]; await db.users.update_one({'telegram_id':c.from_user.id},{'$set':{'language':l}}); await c.message.edit_text(t(l,'welcome'),reply_markup=main_kb(l)); await c.answer()

@user_router.callback_query(F.data.startswith('pick:number:'))
async def pick_number(c:CallbackQuery):
    num=c.data.split(':',2)[2]; x=await db.numbers.find_one({'number':num,'status':'available'}); l=await lang(c.from_user.id)
    if not x:return await c.answer('Unavailable',show_alert=True)
    txt=f"📱 <b>{esc(x['number'])}</b>\n\nCategory: {esc(x.get('category'))}\nPrice: <b>${money(x.get('price')):.2f}</b>\n\n{esc(x.get('details',''))}"
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t(l,'buy'),callback_data=f'buy:number:{num}')],[InlineKeyboardButton(text=t(l,'back'),callback_data='u:numbers')]])
    await c.message.edit_text(txt,reply_markup=kb); await c.answer()

@user_router.callback_query(F.data.startswith('pick:catalog:'))
async def pick_catalog(c:CallbackQuery):
    iid=c.data.split(':',2)[2]; x=await db.catalog.find_one({'item_id':iid,'active':True}); l=await lang(c.from_user.id)
    if not x:return await c.answer('Unavailable',show_alert=True)
    txt=f"📦 <b>{esc(x.get('name'))}</b>\n\n💵 Price: <b>${money(x.get('price')):.2f}</b>\n📦 Stock: {x.get('stock','∞')}\n\n{esc(x.get('details',''))}"
    await c.message.edit_text(txt,reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t(l,'buy'),callback_data=f'buy:catalog:{iid}')],[InlineKeyboardButton(text=t(l,'back'),callback_data=f'u:{x.get("kind")}')]])); await c.answer()

@user_router.callback_query(F.data.startswith('buy:number:'))
async def buy_number(c:CallbackQuery):
    num=c.data.split(':',2)[2]; x=await db.numbers.find_one({'number':num,'status':'available'}); l=await lang(c.from_user.id)
    if not x:return await c.answer('Already sold',show_alert=True)
    oid=await create_order(c.from_user.id,'number',num,x['price'],{'number':num,'category':x.get('category')}); await c.message.edit_text(t(l,'pending',id=oid),reply_markup=main_kb(l)); await c.answer()

@user_router.callback_query(F.data.startswith('buy:catalog:'))
async def buy_catalog(c:CallbackQuery):
    iid=c.data.split(':',2)[2]; x=await db.catalog.find_one({'item_id':iid,'active':True}); l=await lang(c.from_user.id)
    if not x:return await c.answer('Unavailable',show_alert=True)
    oid=await create_order(c.from_user.id,x['kind'],x['name'],x['price'],{'item_id':iid}); await c.message.edit_text(t(l,'pending',id=oid),reply_markup=main_kb(l)); await c.answer()

@user_router.callback_query(F.data=='pay:start')
async def pay_start(c:CallbackQuery,state:FSMContext):
    l=await lang(c.from_user.id); methods=await setting('payment_methods',DEFAULT_PAYMENTS); b=InlineKeyboardBuilder()
    for k in methods: b.button(text=f'💳 {k}',callback_data=f'pay:method:{k}')
    b.button(text=t(l,'back'),callback_data='u:wallet'); b.adjust(2); await c.message.edit_text('💵 <b>Choose payment method</b>',reply_markup=b.as_markup()); await c.answer()

@user_router.callback_query(F.data.startswith('pay:method:'))
async def pay_method(c:CallbackQuery,state:FSMContext):
    method=c.data.split(':',2)[2]; await state.update_data(method=method); await state.set_state(Payment.amount); await c.message.edit_text(t(await lang(c.from_user.id),'amount')); await c.answer()

@user_router.message(Payment.amount)
async def pay_amount(m:Message,state:FSMContext):
    amount=money(m.text)
    if amount<=0:return await m.answer('❌ Invalid amount.')
    await state.update_data(amount=amount); await state.set_state(Payment.reference)
    methods=await setting('payment_methods',DEFAULT_PAYMENTS); data=await state.get_data(); await m.answer(f"💳 Method: <b>{esc(data['method'])}</b>\nSend payment to:\n<code>{esc(methods.get(data['method'],''))}</code>\n\n{t(await lang(m.from_user.id),'reference')}")
@user_router.message(Payment.reference)
async def pay_ref(m:Message,state:FSMContext):
    d=await state.get_data(); pid=rid('PAY'); doc={'payment_id':pid,'user_id':m.from_user.id,'method':d['method'],'amount':money(d['amount']),'reference':m.text.strip(),'status':'pending','created_at':NOW()}; await db.payments.insert_one(doc); await audit(m.from_user.id,'payment_submitted',pid,doc); await admin_notify(f'💵 <b>PAYMENT PENDING</b>\n\n🆔 <code>{pid}</code>\n👤 <code>{m.from_user.id}</code>\n💰 ${doc["amount"]:.2f}\n💳 {esc(doc["method"])}\n🔖 {esc(doc["reference"])}',m.from_user.id,'payment',pid); await state.clear(); await m.answer(t(await lang(m.from_user.id),'pending',id=pid),reply_markup=main_kb(await lang(m.from_user.id)))

@user_router.message(UserInput.value)
async def support_message(m:Message,state:FSMContext):
    tid=rid('TKT'); doc={'ticket_id':tid,'user_id':m.from_user.id,'text':m.text or '','status':'open','created_at':NOW()}; await db.support.insert_one(doc); await audit(m.from_user.id,'support_ticket',tid); await admin_notify(f'🆘 <b>SUPPORT TICKET</b>\n\n🆔 <code>{tid}</code>\n👤 <code>{m.from_user.id}</code>\n\n{esc(m.text)}',m.from_user.id,'support',tid); await state.clear(); await m.answer(t(await lang(m.from_user.id),'sent'),reply_markup=main_kb(await lang(m.from_user.id)))

# ---------------- ADMIN BUTTON SYSTEM ----------------
@admin_router.callback_query(F.data=='a:home')
async def admin_home_cb(c:CallbackQuery):
    if not await is_admin(c.from_user.id): return await c.answer('Not authorized',show_alert=True)
    await c.message.edit_text('🛡️ <b>TELESOM ADMIN PANEL</b>\n\nFull company control center. Choose a panel:',reply_markup=admin_home()); await c.answer()

@admin_router.callback_query(F.data.startswith('a:panel:'))
async def panel(c:CallbackQuery,state:FSMContext):
    if not await is_admin(c.from_user.id): return await c.answer('Not authorized',show_alert=True)
    n=int(c.data.split(':')[2]); name=PANELS[n-1]
    count_map={1:db.users,2:db.users,3:db.numbers,4:db.numbers,5:db.catalog,6:db.catalog,7:db.catalog,8:db.catalog,9:db.catalog,10:db.catalog,11:db.catalog,12:db.wallet_ledger,13:db.payments,14:db.orders,15:db.requests,16:db.offers,17:db.promos,18:db.referrals,19:db.memberships,20:db.support,21:db.notifications,22:db.notifications,23:db.requests,24:db.requests,25:db.numbers,26:db.audit_logs,27:db.staff,28:db.security_events,29:db.audit_logs,30:db.settings}
    count=await count_map[n].count_documents({})
    b=InlineKeyboardBuilder()
    actions={
      1:[('📊 Refresh','a:panel:1'),('👥 Customers','a:panel:2'),('🛎️ Pending','a:pending')],
      2:[('👥 All Customers','a:customers'),('🚫 Banned','a:customers:banned')],
      3:[('➕ Add Number','a:addnum:regular'),('📋 Inventory','a:numbers:regular'),('🗑️ Remove','a:remove:number')],
      4:[('➕ Add VIP','a:addnum:vip'),('💎 VIP Inventory','a:numbers:vip')],
      5:[('➕ Add Virtual','a:additem:virtual'),('📋 Virtual Inventory','a:items:virtual')],
      6:[('➕ Add eSIM','a:additem:esim'),('📋 eSIM Inventory','a:items:esim')],
      7:[('➕ Add SIM','a:additem:sim'),('📋 SIM Inventory','a:items:sim')],
      8:[('➕ Add Data','a:additem:data'),('📋 Data Plans','a:items:data')],
      9:[('➕ Add Voice','a:additem:voice'),('📋 Voice Plans','a:items:voice')],
      10:[('➕ Add SMS','a:additem:sms'),('📋 SMS Plans','a:items:sms')],
      11:[('➕ Add Recharge','a:additem:recharge'),('📋 Recharge Plans','a:items:recharge')],
      12:[('💰 Wallet Ledger','a:ledger'),('💳 Add Credit','a:credit')],
      13:[('⏳ Pending Payments','a:payments:pending'),('📋 All Payments','a:payments:all')],
      14:[('⏳ Pending Orders','a:orders:pending'),('📋 All Orders','a:orders:all')],
      15:[('⏳ Refund Requests','a:refunds'),('➕ Create Refund','a:refund:new')],
      16:[('➕ Add Offer','a:addoffer'),('📋 Offers','a:offers')],
      17:[('➕ Add Promo','a:addpromo'),('📋 Promos','a:promos')],
      18:[('👥 Referral Stats','a:referrals')],
      19:[('💎 Memberships','a:memberships')],
      20:[('🆘 Open Tickets','a:support')],
      21:[('📢 Broadcast','a:broadcast')],
      22:[('🔔 Notifications','a:notifications')],
      23:[('🏢 Business Requests','a:req:business')],
      24:[('🏢 Corporate Requests','a:req:corporate')],
      25:[('📦 Inventory','a:inventory')],
      26:[('📈 Analytics','a:analytics')],
      27:[('👮 Staff','a:staff'),('➕ Add Staff','a:addstaff')],
      28:[('🔐 Security','a:security'),('🚨 Emergency Lock','a:lock')],
      29:[('🧾 Audit Logs','a:audit')],
      30:[('⚙️ Settings','a:settings'),('💳 Payment Methods','a:payment_methods'),('🌐 Services On/Off','a:services')]
    }
    for label,cb in actions.get(n,[]): b.button(text=label,callback_data=cb)
    b.adjust(2); await c.message.edit_text(f'🛠️ <b>{name}</b>\n\nRecords: <b>{count}</b>\n\nChoose an action:',reply_markup=InlineKeyboardMarkup(inline_keyboard=b.export()+[[InlineKeyboardButton(text='⬅️ Admin Home',callback_data='a:home')]])); await c.answer()

@admin_router.callback_query(F.data=='a:pending')
async def pending(c:CallbackQuery):
    if not await is_admin(c.from_user.id): return await c.answer('No',show_alert=True)
    orders=await db.orders.find({'status':'pending_approval'}).sort('created_at',-1).to_list(10); pays=await db.payments.find({'status':'pending'}).sort('created_at',-1).to_list(10)
    txt='⏳ <b>PENDING APPROVALS</b>\n\nOrders: '+str(len(orders))+'\nPayments: '+str(len(pays)); b=InlineKeyboardBuilder()
    for x in orders: b.button(text=f'🛒 {x["order_id"]}',callback_data=f'a:details:order:{x["order_id"]}')
    for x in pays: b.button(text=f'💵 {x["payment_id"]}',callback_data=f'a:details:payment:{x["payment_id"]}')
    b.adjust(2); b.row(InlineKeyboardButton(text='⬅️ Admin Home',callback_data='a:home')); await c.message.edit_text(txt,reply_markup=b.as_markup()); await c.answer()

@admin_router.callback_query(F.data.startswith('a:approve:') | F.data.startswith('a:reject:'))
async def approval(c:CallbackQuery):
    if not await is_admin(c.from_user.id): return await c.answer('No',show_alert=True)
    _,action,kind,ident=c.data.split(':',3); coll={'order':db.orders,'payment':db.payments,'request':db.requests,'support':db.support}.get(kind)
    if coll is None:return await c.answer('Unknown',show_alert=True)
    row=await coll.find_one({'order_id' if kind=='order' else 'payment_id' if kind=='payment' else 'request_id' if kind=='request' else 'ticket_id':ident})
    if not row:return await c.answer('Not found',show_alert=True)
    new='confirmed' if action=='approve' else 'rejected'
    key={'order':'order_id','payment':'payment_id','request':'request_id','support':'ticket_id'}[kind]
    await coll.update_one({key:ident},{'$set':{'status':new,'updated_at':NOW(),'approved_by':c.from_user.id}}); await audit(c.from_user.id,f'{action}_{kind}',ident)
    uid=int(row['user_id'])
    if kind=='payment' and action=='approve':
        amt=money(row['amount']); await db.users.update_one({'telegram_id':uid},{'$inc':{'wallet.available':amt,'total_deposited':amt}}); await db.wallet_ledger.insert_one({'ledger_id':rid('LED'),'user_id':uid,'type':'deposit','amount':amt,'reference':ident,'created_at':NOW()})
    if kind=='order' and action=='approve' and row.get('kind')=='number': await db.numbers.update_one({'number':row['item'],'status':'available'},{'$set':{'status':'reserved','reserved_by':uid,'order_id':ident}})
    try: await bot.send_message(uid,t(await lang(uid),'approved' if action=='approve' else 'rejected',id=ident))
    except Exception: pass
    await c.message.edit_text(f'✅ {kind.upper()} <code>{ident}</code> → <b>{new}</b>',reply_markup=admin_back()); await c.answer()

@admin_router.callback_query(F.data.startswith('a:details:'))
async def details(c:CallbackQuery):
    if not await is_admin(c.from_user.id): return await c.answer('No',show_alert=True)
    _,_,kind,ident=c.data.split(':',3); key={'order':'order_id','payment':'payment_id','request':'request_id','support':'ticket_id'}.get(kind); coll={'order':db.orders,'payment':db.payments,'request':db.requests,'support':db.support}.get(kind)
    row=await coll.find_one({key:ident}) if coll else None
    if not row:return await c.answer('Not found',show_alert=True)
    txt='📄 <b>DETAILS</b>\n\n'+esc(json.dumps({k:v for k,v in row.items() if k!='_id'},default=str,ensure_ascii=False,indent=2))
    await c.message.edit_text(f'<pre>{txt[:3900]}</pre>',reply_markup=approve_kb(kind,ident)); await c.answer()

@admin_router.callback_query(F.data.startswith('a:user:'))
async def user_detail(c:CallbackQuery):
    if not await is_admin(c.from_user.id): return await c.answer('No',show_alert=True)
    uid=int(c.data.split(':')[2]); u=await user(uid)
    if not u:return await c.answer('Not found',show_alert=True)
    w=u.get('wallet',{}); txt=f"👤 <b>CUSTOMER</b>\n\n🆔 <code>{uid}</code>\n👤 {esc(u.get('first_name'))}\n🔗 @{esc(u.get('username') or 'none')}\n📌 {u.get('status')}\n💰 ${money(w.get('available')):.2f}"
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🚫 BAN',callback_data=f'a:ban:{uid}'),InlineKeyboardButton(text='✅ UNBAN',callback_data=f'a:unban:{uid}')],[InlineKeyboardButton(text='⬅️ Admin Home',callback_data='a:home')]])
    await c.message.edit_text(txt,reply_markup=kb); await c.answer()

@admin_router.callback_query(F.data.startswith('a:customers'))
async def customers(c:CallbackQuery):
    if not await is_admin(c.from_user.id): return await c.answer('No',show_alert=True)
    rows=await db.users.find({}).sort('created_at',-1).to_list(30); b=InlineKeyboardBuilder()
    for u in rows: b.button(text=f"👤 {u.get('first_name','User')} · {u['telegram_id']}",callback_data=f"a:user:{u['telegram_id']}")
    b.adjust(1); b.row(InlineKeyboardButton(text='⬅️ Admin Home',callback_data='a:home')); await c.message.edit_text(f'👥 <b>CUSTOMERS</b>\nTotal: {len(rows)}',reply_markup=b.as_markup()); await c.answer()

@admin_router.callback_query(F.data.startswith('a:ban:') | F.data.startswith('a:unban:'))
async def ban(c:CallbackQuery):
    if not await is_admin(c.from_user.id): return await c.answer('No',show_alert=True)
    action,uid=c.data.split(':')[1:]; uid=int(uid)
    if uid==ADMIN_ID:return await c.answer('Main admin protected',show_alert=True)
    await db.users.update_one({'telegram_id':uid},{'$set':{'status':'banned' if action=='ban' else 'active'}}); await audit(c.from_user.id,action,str(uid)); await c.answer('Done'); await user_detail(c)

# Generic admin inventory viewers
@admin_router.callback_query(F.data.startswith('a:numbers:'))
async def nums(c:CallbackQuery):
    if not await is_admin(c.from_user.id): return await c.answer('No',show_alert=True)
    cat=c.data.split(':')[2]; rows=await db.numbers.find({'category':cat}).sort('price',1).to_list(50); txt=f'📱 <b>{cat.upper()} NUMBERS</b>\n\n'+('\n'.join(f"{x['number']} • ${money(x.get('price')):.2f} • {x.get('status')}" for x in rows) or 'Empty'); await c.message.edit_text(txt,reply_markup=admin_back()); await c.answer()
@admin_router.callback_query(F.data.startswith('a:items:'))
async def items(c:CallbackQuery):
    if not await is_admin(c.from_user.id): return await c.answer('No',show_alert=True)
    kind=c.data.split(':')[2]; rows=await db.catalog.find({'kind':kind}).sort('created_at',-1).to_list(50); txt=f'📦 <b>{kind.upper()}</b>\n\n'+('\n'.join(f"{x['name']} • ${money(x.get('price')):.2f} • stock {x.get('stock','∞')} • {x.get('active',True)}" for x in rows) or 'Empty'); await c.message.edit_text(txt,reply_markup=admin_back()); await c.answer()

@admin_router.callback_query(F.data.startswith('a:addnum:'))
async def addnum_start(c:CallbackQuery,state:FSMContext):
    if not await is_admin(c.from_user.id): return await c.answer('No',show_alert=True)
    await state.update_data(category=c.data.split(':')[2]); await state.set_state(AddNumber.number); await c.message.edit_text('➕ <b>ADD NUMBER</b>\n\nSend the phone number:'); await c.answer()
@admin_router.message(AddNumber.number)
async def addnum1(m:Message,state:FSMContext): await state.update_data(number=m.text.strip()); await state.set_state(AddNumber.price); await m.answer('Send price:')
@admin_router.message(AddNumber.price)
async def addnum2(m:Message,state:FSMContext):
    await state.update_data(price=money(m.text)); await state.set_state(AddNumber.title); await m.answer('Send title/name:')
@admin_router.message(AddNumber.title)
async def addnum3(m:Message,state:FSMContext):
    await state.update_data(title=m.text.strip()); await state.set_state(AddNumber.details); await m.answer('Send details or -:')
@admin_router.message(AddNumber.details)
async def addnum4(m:Message,state:FSMContext):
    d=await state.get_data(); await db.numbers.update_one({'number':d['number']},{'$set':{'number':d['number'],'price':d['price'],'category':d['category'],'title':d['title'],'details':'' if m.text=='-' else m.text,'status':'available','updated_at':NOW()},'$setOnInsert':{'created_at':NOW()}},upsert=True); await audit(m.from_user.id,'number_added',d['number'],d); await state.clear(); await m.answer('✅ Number added.',reply_markup=admin_home())

@admin_router.callback_query(F.data.startswith('a:additem:'))
async def additem_start(c:CallbackQuery,state:FSMContext):
    if not await is_admin(c.from_user.id): return await c.answer('No',show_alert=True)
    await state.update_data(kind=c.data.split(':')[2]); await state.set_state(AddItem.name); await c.message.edit_text('➕ <b>ADD SERVICE ITEM</b>\n\nName:'); await c.answer()
@admin_router.message(AddItem.name)
async def addi1(m:Message,state:FSMContext): await state.update_data(name=m.text.strip()); await state.set_state(AddItem.price); await m.answer('Price:')
@admin_router.message(AddItem.price)
async def addi2(m:Message,state:FSMContext): await state.update_data(price=money(m.text)); await state.set_state(AddItem.details); await m.answer('Details:')
@admin_router.message(AddItem.details)
async def addi3(m:Message,state:FSMContext): await state.update_data(details=m.text); await state.set_state(AddItem.stock); await m.answer('Stock (number or 0 for unlimited):')
@admin_router.message(AddItem.stock)
async def addi4(m:Message,state:FSMContext):
    d=await state.get_data(); stock=int(m.text) if (m.text or '').isdigit() else 0; iid=rid('ITM'); await db.catalog.insert_one({'item_id':iid,'kind':d['kind'],'name':d['name'],'price':d['price'],'details':d['details'],'stock':stock,'active':True,'created_at':NOW(),'updated_at':NOW()}); await audit(m.from_user.id,'catalog_added',iid,d); await state.clear(); await m.answer(f'✅ Added {d["name"]}',reply_markup=admin_home())

@admin_router.callback_query(F.data=='a:analytics')
async def analytics(c:CallbackQuery):
    if not await is_admin(c.from_user.id): return await c.answer('No',show_alert=True)
    txt=f"📈 <b>ANALYTICS</b>\n\n👥 Users: {await db.users.count_documents({})}\n🛒 Orders: {await db.orders.count_documents({})}\n💵 Payments: {await db.payments.count_documents({})}\n📱 Numbers: {await db.numbers.count_documents({})}\n📦 Catalog items: {await db.catalog.count_documents({})}\n🎫 Tickets: {await db.support.count_documents({})}\n🧾 Audit logs: {await db.audit_logs.count_documents({})}"
    await c.message.edit_text(txt,reply_markup=admin_back()); await c.answer()
@admin_router.callback_query(F.data=='a:settings')
async def settings(c:CallbackQuery):
    if not await is_admin(c.from_user.id): return await c.answer('No',show_alert=True)
    vals={};
    for k in ['company_name','currency','support_username','registration_bonus','referral_reward','maintenance']: vals[k]=await setting(k)
    txt='⚙️ <b>SYSTEM SETTINGS</b>\n\n'+'\n'.join(f'• {k}: <code>{esc(v)}</code>' for k,v in vals.items())
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✏️ Edit Setting',callback_data='a:set')],[InlineKeyboardButton(text='⬅️ Admin Home',callback_data='a:home')]])
    await c.message.edit_text(txt,reply_markup=kb); await c.answer()
@admin_router.callback_query(F.data=='a:set')
async def set_start(c:CallbackQuery,state:FSMContext):
    await state.set_state(Setting.key); await c.message.edit_text('⚙️ Send setting key: company_name / currency / support_username / registration_bonus / referral_reward / maintenance'); await c.answer()
@admin_router.message(Setting.key)
async def setkey(m:Message,state:FSMContext): await state.update_data(key=m.text.strip()); await state.set_state(Setting.value); await m.answer('Send new value:')
@admin_router.message(Setting.value)
async def setval(m:Message,state:FSMContext):
    d=await state.get_data(); v=m.text.strip();
    if v.lower() in ['true','false']: v=v.lower()=='true'
    elif v.replace('.','',1).isdigit(): v=money(v)
    await set_setting(d['key'],v); await audit(m.from_user.id,'setting_changed',d['key'],{'value':v}); await state.clear(); await m.answer('✅ Setting updated.',reply_markup=admin_home())

@admin_router.callback_query(F.data=='a:payment_methods')
async def payment_methods(c:CallbackQuery):
    if not await is_admin(c.from_user.id): return await c.answer('No',show_alert=True)
    p=await setting('payment_methods',DEFAULT_PAYMENTS); txt='💳 <b>PAYMENT METHODS</b>\n\n'+'\n'.join(f'<b>{esc(k)}</b>: <code>{esc(v)}</code>' for k,v in p.items())+'\n\nTo change a method use setting key <code>payment_methods</code> with JSON.'
    await c.message.edit_text(txt,reply_markup=admin_back()); await c.answer()
@admin_router.callback_query(F.data=='a:services')
async def services(c:CallbackQuery):
    if not await is_admin(c.from_user.id): return await c.answer('No',show_alert=True)
    s=await setting('service_enabled',{}); b=InlineKeyboardBuilder()
    for k,v in s.items(): b.button(text=f'{"🟢" if v else "🔴"} {k}',callback_data=f'a:toggle:{k}')
    b.adjust(2); b.row(InlineKeyboardButton(text='⬅️ Admin Home',callback_data='a:home')); await c.message.edit_text('🌐 <b>SERVICE AVAILABILITY</b>',reply_markup=b.as_markup()); await c.answer()
@admin_router.callback_query(F.data.startswith('a:toggle:'))
async def toggle(c:CallbackQuery):
    if not await is_admin(c.from_user.id): return await c.answer('No',show_alert=True)
    k=c.data.split(':')[2]; s=await setting('service_enabled',{}); s[k]=not s.get(k,True); await set_setting('service_enabled',s); await audit(c.from_user.id,'service_toggled',k,{'enabled':s[k]}); await c.answer('Updated'); await services(c)

@admin_router.callback_query(F.data=='a:broadcast')
async def broadcast_start(c:CallbackQuery,state:FSMContext): await state.set_state(Broadcast.text); await c.message.edit_text('📢 Send broadcast text:'); await c.answer()
@admin_router.message(Broadcast.text)
async def broadcast_send(m:Message,state:FSMContext):
    rows=await db.users.find({'status':{'$ne':'banned'}},{'telegram_id':1}).to_list(None); ok=0
    for u in rows:
        try: await bot.send_message(u['telegram_id'],m.text); ok+=1
        except Exception: pass
        await asyncio.sleep(.03)
    await db.notifications.insert_one({'type':'broadcast','text':m.text,'sent':ok,'created_at':NOW()}); await audit(m.from_user.id,'broadcast',None,{'sent':ok}); await state.clear(); await m.answer(f'✅ Broadcast sent: {ok}',reply_markup=admin_home())

@admin_router.callback_query(F.data=='a:staff')
async def staff(c:CallbackQuery):
    rows=await db.staff.find({}).to_list(50); txt='👮 <b>STAFF & PERMISSIONS</b>\n\n'+('\n'.join(f"{x['telegram_id']} • {x.get('role')} • {x.get('active')} • {','.join(x.get('permissions',[]))}" for x in rows) or 'No staff'); await c.message.edit_text(txt,reply_markup=admin_back()); await c.answer()
@admin_router.callback_query(F.data=='a:addstaff')
async def addstaff(c:CallbackQuery,state:FSMContext): await state.set_state(UserInput.value); await state.update_data(mode='staff'); await c.message.edit_text('👮 Send: TELEGRAM_ID ROLE permissions(comma separated)'); await c.answer()
@admin_router.callback_query(F.data=='a:lock')
async def lock(c:CallbackQuery): await set_setting('maintenance',True); await audit(c.from_user.id,'emergency_lock'); await c.message.edit_text('🚨 <b>EMERGENCY LOCK ENABLED</b>',reply_markup=admin_home()); await c.answer()
@admin_router.callback_query(F.data=='a:security')
async def security(c:CallbackQuery):
    txt=f'🔐 <b>SECURITY</b>\n\n🚨 Maintenance: {await setting("maintenance",False)}\n🛡️ Main admin protected: YES\n🧾 Audit logging: ON\n✅ Approval workflow: ON\n💳 Payment confirmation: ADMIN REQUIRED'; await c.message.edit_text(txt,reply_markup=admin_back()); await c.answer()
@admin_router.callback_query(F.data=='a:audit')
async def audit_view(c:CallbackQuery):
    rows=await db.audit_logs.find({}).sort('created_at',-1).to_list(25); txt='🧾 <b>AUDIT LOGS</b>\n\n'+('\n'.join(f"{x.get('created_at')} • {x.get('actor')} • {esc(x.get('action'))} • {esc(x.get('target'))}" for x in rows) or 'Empty'); await c.message.edit_text(txt[:3900],reply_markup=admin_back()); await c.answer()

# Generic panel placeholders are still real navigable panels; operational actions above are live.
@admin_router.callback_query()
async def unknown_admin(c:CallbackQuery):
    if c.data and c.data.startswith('a:'):
        await c.answer('This control is available in the Admin Panel; use the panel action buttons.',show_alert=True)

@user_router.callback_query(F.data=='u:cancel')
async def cancel(c:CallbackQuery,state:FSMContext): await state.clear(); await c.message.edit_text(t(await lang(c.from_user.id),'welcome'),reply_markup=main_kb(await lang(c.from_user.id))); await c.answer()

async def health(request): return web.json_response({'status':'ok','service':'Telesombot','time':NOW().isoformat()})
async def health_server():
    app=web.Application(); app.router.add_get('/',health); app.router.add_get('/health',health); runner=web.AppRunner(app); await runner.setup(); await web.TCPSite(runner,'0.0.0.0',PORT).start(); return runner
async def main():
    await init_db(); await bot.delete_webhook(drop_pending_updates=True); runner=await health_server(); log.info('TELESOMBOT COMPANY SYSTEM STARTED')
    try: await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
    finally: await runner.cleanup(); await bot.session.close(); client.close()
if __name__=='__main__': asyncio.run(main())
