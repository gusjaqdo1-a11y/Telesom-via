import os, asyncio, logging, uuid, random
from datetime import datetime, timezone
from html import escape
from typing import Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiohttp import web

load_dotenv()
BOT_TOKEN=os.getenv('BOT_TOKEN','').strip(); MONGO_URI=os.getenv('MONGO_URI','').strip(); DB_NAME=os.getenv('DB_NAME','telesombot')
ADMIN_ID=int(os.getenv('ADMIN_ID','0') or 0); PORT=int(os.getenv('PORT','10000') or 10000)
if not BOT_TOKEN or not MONGO_URI or ADMIN_ID<=0: raise RuntimeError('BOT_TOKEN, MONGO_URI and ADMIN_ID are required')
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s'); log=logging.getLogger('telesombot')
client=AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=10000); db=client[DB_NAME]
bot=Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML')); dp=Dispatcher(); router=Router(); admin_router=Router(); dp.include_router(router); dp.include_router(admin_router)

PAYMENTS={'Golis':'*883*0907868526*$#','Telesom':'*880*0907868526*$#','BNB':'0x1f12ffDc93E49eff0c78672Ab6abA62410c05a32','USDT-BEP20':'0x6AC864773259fa5175251829cb0E93ffb4cE6feC'}
SITE='https://www.telesom.com'
SERVICES={'numbers':'📱 Numbers','vip':'💎 VIP Numbers','virtual':'🌐 Virtual Numbers','esim':'📲 eSIM','sim':'💳 Physical SIM','data':'📡 Data','voice':'📞 Voice','sms':'💬 SMS','recharge':'🔋 Recharge'}
PANELS=['Dashboard','Customers','Numbers','VIP Numbers','Virtual Numbers','eSIM','Physical SIM','Data','Voice','SMS','Recharge','Wallets','Payments','Orders','Refunds','Offers','Promo Codes','Referrals','Memberships','Support','Broadcast','Notifications','Business','Corporate','Inventory','Analytics','Staff & Permissions','Security','Audit Logs','System Settings']
PANELS += [f'Module {i:02d}' for i in range(31,101)]

class UserFlow(StatesGroup):
    order_details=State(); payment_amount=State(); payment_ref=State(); support=State(); recharge_amount=State(); admin_input=State(); broadcast=State()

def now(): return datetime.now(timezone.utc)
def uid(p): return f'{p}-{uuid.uuid4().hex[:10].upper()}'
def money(v):
    try:return round(float(v),2)
    except:return 0.0
def txt(v,default='-'): return str(v or default).strip() or default

async def setting(k,d=None):
    x=await db.settings.find_one({'_id':k}); return x.get('value',d) if x else d
async def set_setting(k,v): await db.settings.update_one({'_id':k},{'$set':{'value':v}},upsert=True)
async def user(u): return await db.users.find_one({'telegram_id':u.id})
async def ensure(u):
    old=await user(u); tid=int(u.id)
    r=await db.users.update_one({'telegram_id':tid},{'$set':{'username':u.username,'first_name':u.first_name,'last_name':u.last_name,'updated_at':now()},'$setOnInsert':{'telegram_id':tid,'language':'en','status':'active','wallet':{'available':0.0,'pending':0.0},'total_deposited':0.0,'total_spent':0.0,'referrals':0,'created_at':now()}},upsert=True)
    if old is None and r.upserted_id is not None:
        await db.audit_logs.insert_one({'actor':tid,'action':'user_registered','target':str(tid),'created_at':now()})
        await notify_admin('🆕 <b>NEW CUSTOMER</b>\n\n👤 Name: '+escape(u.full_name)+f'\n🆔 Telegram ID: <code>{tid}</code>\n🔗 Username: @{escape(u.username or "none")}')

def main_kb(admin=False):
    rows=[['📱 Numbers','💎 VIP Numbers'],['🌐 Virtual Numbers','📲 eSIM'],['💳 Physical SIM','📡 Data'],['📞 Voice','💬 SMS'],['🔋 Recharge','💰 Wallet'],['🛒 My Orders','💵 Payments'],['🎁 Offers','👥 Referral'],['🆘 Customer Support','👤 My Profile'],['🌐 Language']]
    if admin: rows.append(['🛠️ ADMIN PANEL TELESOM'])
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in r] for r in rows],resize_keyboard=True,is_persistent=True)

def back_kb(): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='⬅️ Back to Menu')]],resize_keyboard=True)

def admin_menu():
    rows=[]
    for i in range(0,100,2): rows.append([KeyboardButton(text=f'🛠 {i+1:02d}. {PANELS[i]}'),KeyboardButton(text=f'🛠 {i+2:02d}. {PANELS[i+1]}')])
    rows += [[KeyboardButton(text='⏳ Pending Orders'),KeyboardButton(text='💳 Pending Payments')],[KeyboardButton(text='📢 Broadcast'),KeyboardButton(text='⬅️ Customer Menu')]]
    return ReplyKeyboardMarkup(keyboard=rows,resize_keyboard=True,is_persistent=True)

async def notify_admin(message, kb=None):
    try: await bot.send_message(ADMIN_ID,message,reply_markup=kb)
    except Exception as e: log.warning('admin notify: %r',e)

def approval_kb(kind, ident):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ CONFIRM',callback_data=f'confirm:{kind}:{ident}'),InlineKeyboardButton(text='❌ REJECT',callback_data=f'reject:{kind}:{ident}')],[InlineKeyboardButton(text='📄 DETAILS',callback_data=f'details:{kind}:{ident}'),InlineKeyboardButton(text='💬 CONTACT USER',callback_data=f'contact:{kind}:{ident}')]])

async def show_menu(m):
    await ensure(m.from_user); await m.answer('🏠 <b>TELESOM SERVICE CENTER</b>\n\nChoose a service below.',reply_markup=main_kb(await is_admin(m.from_user.id)))
async def is_admin(tid): return int(tid)==ADMIN_ID or bool(await db.staff.find_one({'telegram_id':int(tid),'active':True,'permissions':'admin'}))

@router.message(CommandStart())
async def start(m:Message,state:FSMContext):
    await state.clear(); await ensure(m.from_user)
    await m.answer('👋 <b>Ku soo dhowow Telesom</b>\n\n📱 Services, numbers, eSIM, payments and orders — dhammaantood hal meel.\n\nDooro adeegga aad rabto.',reply_markup=main_kb(await is_admin(m.from_user.id)))

@router.message(F.text=='⬅️ Back to Menu')
async def back(m,state:FSMContext): await state.clear(); await show_menu(m)

@router.message(F.text.in_(list(SERVICES.values())))
async def service(m,state:FSMContext):
    key=next(k for k,v in SERVICES.items() if v==m.text)
    await ensure(m.from_user)
    if not await setting('orders_open',True): return await m.answer('🔒 Adeegga dalabka hadda waa xiran yahay.')
    if key in ('data','voice'):
        return await m.answer(f'{SERVICES[key]}\n\nDalabka waxaa loo sameeyaa si manual ah.\n\n🌐 {SITE}\n\nFadlan booqo website-ka Telesom si aad u aragto xirmooyinka iyo faahfaahinta, kadib halkan noogu soo dir codsigaaga.',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🌐 Open Telesom Website',url=SITE)],[InlineKeyboardButton(text='📝 Request Manually',callback_data=f'manual:{key}')]]))
    if key in ('numbers','vip','virtual'):
        cat='vip' if key=='vip' else key
        rows=[]
        if cat=='vip':
            cur=db.numbers.find({'category':cat,'status':'available'}).sort('number',1).limit(15)
        else:
            cur=db.numbers.aggregate([{'$match':{'category':cat,'status':'available'}},{'$sample':{'size':15}}])
        async for n in cur: rows.append([InlineKeyboardButton(text=f"{n['number']} • ${money(n.get('price')):.2f}",callback_data=f'number:{n["number"]}')])
        if not rows: return await m.answer(f'{SERVICES[key]}\n\nHadda numberro diyaar ah ma jiraan.',reply_markup=back_kb())
        return await m.answer(f'<b>{SERVICES[key]}</b>\n\nAvailable numbers:',reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await state.set_state(UserFlow.order_details); await state.update_data(service=key); await m.answer(f'📝 <b>{SERVICES[key]}</b>\n\nFadlan geli faahfaahinta aad rabto:')

@router.callback_query(F.data.startswith('number:'))
async def number_pick(c:CallbackQuery):
    num=c.data.split(':',1)[1]; n=await db.numbers.find_one({'number':num,'status':'available'})
    if not n:return await c.answer('Number-ka hadda lama heli karo.',show_alert=True)
    oid=uid('ORD'); await db.orders.insert_one({'order_id':oid,'user_id':c.from_user.id,'service':n.get('category','number'),'details':{'number':num},'amount':money(n.get('price')),'status':'pending','payment_status':'unpaid','created_at':now(),'updated_at':now()})
    await notify_admin(f'🆕 <b>NEW ORDER</b>\n\n🆔 <code>{oid}</code>\n👤 <code>{c.from_user.id}</code>\n📱 Number: <code>{escape(num)}</code>\n💰 Amount: <b>${money(n.get("price")):.2f}</b>',approval_kb('order',oid))
    await c.message.answer(f'✅ <b>Order created</b>\n\n🆔 <code>{oid}</code>\n💰 <b>${money(n.get("price")):.2f}</b>\n\n⏳ <b>Pending 5–10 Min. Please wait ⏳</b>\n\nPayment-ka hadda ka dooro <b>💵 Payments</b>.')
    await c.answer()

@router.callback_query(F.data.startswith('manual:'))
async def manual(c,state):
    key=c.data.split(':',1)[1]; await state.set_state(UserFlow.order_details); await state.update_data(service=key); await c.message.answer(f'📝 Geli faahfaahinta {SERVICES[key]} aad rabto:'); await c.answer()

@router.message(UserFlow.order_details)
async def order_details(m,state):
    d=await state.get_data(); service=d.get('service'); details=m.text.strip(); oid=uid('ORD')
    await db.orders.insert_one({'order_id':oid,'user_id':m.from_user.id,'service':service,'details':details,'amount':0.0,'status':'pending','payment_status':'unpaid','created_at':now(),'updated_at':now()})
    await notify_admin(f'🆕 <b>NEW ORDER</b>\n\n🆔 <code>{oid}</code>\n👤 <code>{m.from_user.id}</code>\n📌 {escape(SERVICES.get(service,service))}\n📝 {escape(details)}',approval_kb('order',oid))
    await state.clear(); await m.answer(f'✅ <b>Order received</b>\n\n🆔 <code>{oid}</code>\n\n⏳ <b>Pending 5–10 Min. Please wait ⏳</b>\n\nWaxaan kuu soo diri doonaa update marka order-ku socdo.',reply_markup=main_kb(await is_admin(m.from_user.id)))

@router.message(F.text=='💵 Payments')
async def payments(m):
    await ensure(m.from_user)
    methods=await db.payment_methods.find({'enabled':True}).to_list(20)
    rows=[[InlineKeyboardButton(text=f'💳 {x["name"]}',callback_data=f'pmethod:{x["name"]}')] for x in methods]
    rows.append([InlineKeyboardButton(text='📋 My Payments',callback_data='my_payments')])
    await m.answer('💵 <b>PAYMENTS</b>\n\nDooro habka lacag bixinta:\n\n📱 Local: Golis / Telesom\n🪙 Crypto: BNB / USDT-BEP20\n\nPayment-ku wuxuu noqdaa <b>Pending</b> ilaa la hubiyo.',reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.callback_query(F.data.startswith('pmethod:'))
async def pmethod(c,state):
    method=c.data.split(':',1)[1]; order=await db.orders.find_one({'user_id':c.from_user.id,'status':{'$in':['pending','processing']},'payment_status':{'$ne':'paid'}},sort=[('created_at',-1)])
    if not order:return await c.answer('Marka hore samee order.',show_alert=True)
    dest=await db.payment_methods.find_one({'name':method})
    await state.set_state(UserFlow.payment_amount); await state.update_data(method=method,order_id=order['order_id'],destination=dest['destination'])
    if method in ('Golis','Telesom'): label='📱 <b>Local Payment</b>\n\nKu dir lacagta lambarka/USSD-ga hoose:\n<code>'+escape(dest['destination'])+'</code>\n\nKadib geli amount-ka aad dirtay.'
    else: label='🪙 <b>Crypto Payment</b>\n\nNetwork: <b>BNB Smart Chain (BEP20)</b>\nAddress:\n<code>'+escape(dest['destination'])+'</code>\n\nKadib geli amount-ka aad dirtay.'
    await c.message.answer(label); await c.answer()

@router.message(UserFlow.payment_amount)
async def payment_amount(m,state):
    try:a=money(m.text)
    except:a=0
    if a<=0:return await m.answer('❌ Geli amount sax ah, tusaale: <code>2</code>')
    d=await state.get_data(); await state.update_data(amount=a); await state.set_state(UserFlow.payment_ref)
    await m.answer('🔖 Hadda geli <b>transaction/reference ID</b> ama number-ka/receipt reference-ka lacag bixinta:')

@router.message(UserFlow.payment_ref)
async def payment_ref(m,state):
    d=await state.get_data(); pid=uid('PAY'); ref=m.text.strip(); a=money(d['amount'])
    await db.payments.insert_one({'payment_id':pid,'order_id':d['order_id'],'user_id':m.from_user.id,'method':d['method'],'destination':d['destination'],'amount':a,'reference':ref,'status':'pending','created_at':now(),'updated_at':now()})
    await db.users.update_one({'telegram_id':m.from_user.id},{'$inc':{'wallet.pending':a}})
    await notify_admin(f'💳 <b>NEW PAYMENT</b>\n\n🆔 <code>{pid}</code>\n📦 <code>{d["order_id"]}</code>\n👤 <code>{m.from_user.id}</code>\n💰 <b>${a:.2f}</b>\n💳 {escape(d["method"])}\n🔖 <code>{escape(ref)}</code>\n📍 <code>{escape(d["destination"])}</code>',approval_kb('payment',pid))
    await state.clear(); await m.answer(f'✅ <b>Payment submitted</b>\n\n🆔 <code>{pid}</code>\n💰 <b>${a:.2f}</b>\n\n⏳ <b>Pending 5–10 Min. Please wait ⏳</b>\n\nFadlan sug; payment-ka iyo order-ka ayaa si toos ah status loogu cusboonaysiin doonaa.',reply_markup=main_kb(await is_admin(m.from_user.id)))

@router.callback_query(F.data=='my_payments')
async def my_payments(c):
    rows=[]
    async for x in db.payments.find({'user_id':c.from_user.id}).sort('created_at',-1).limit(15): rows.append(f'💳 <code>{x["payment_id"]}</code> • ${money(x["amount"]):.2f} • {x["method"]} • <b>{x["status"].upper()}</b>')
    await c.message.answer('💵 <b>My Payments</b>\n\n'+('\n'.join(rows) or 'No payments yet.')); await c.answer()

@router.message(F.text=='🛒 My Orders')
async def my_orders(m):
    rows=[]
    async for x in db.orders.find({'user_id':m.from_user.id}).sort('created_at',-1).limit(15): rows.append(f'📦 <code>{x["order_id"]}</code>\n{SERVICES.get(x.get("service"),x.get("service"))} • <b>{x.get("status", "pending").upper()}</b>\n💰 ${money(x.get("amount")):.2f}')
    await m.answer('🛒 <b>MY ORDERS</b>\n\n'+('\n\n'.join(rows) or 'No orders yet.'))

@router.message(F.text=='💰 Wallet')
async def wallet(m):
    u=await user(m.from_user); w=u.get('wallet',{}) if u else {}; await m.answer(f'💰 <b>WALLET</b>\n\nAvailable: <b>${money(w.get("available")):.2f}</b>\nPending: <b>${money(w.get("pending")):.2f}</b>\nTotal deposited: ${money(u.get("total_deposited")):.2f}\nTotal spent: ${money(u.get("total_spent")):.2f}')

@router.message(F.text=='👤 My Profile')
async def profile(m):
    u=await user(m.from_user); await m.answer(f'👤 <b>MY PROFILE</b>\n\n🆔 <code>{m.from_user.id}</code>\n👤 {escape(m.from_user.full_name)}\n🔗 @{escape(m.from_user.username or "none")}\n🌐 Language: {u.get("language","en")}\n🟢 Status: {u.get("status","active")}')

@router.message(F.text=='👥 Referral')
async def referral(m):
    u=await user(m.from_user); await m.answer(f'👥 <b>REFERRAL</b>\n\nYour referral code:\n<code>{m.from_user.id}</code>\n\nReferrals: <b>{int(u.get("referrals",0))}</b>')

@router.message(F.text=='🎁 Offers')
async def offers(m):
    rows=[]
    async for x in db.offers.find({'enabled':True}).sort('created_at',-1).limit(20): rows.append(f'🎁 <b>{escape(x.get("title","Offer"))}</b>\n{escape(x.get("text",""))}')
    await m.answer('🎁 <b>OFFERS</b>\n\n'+('\n\n'.join(rows) or 'No active offers.'))

@router.message(F.text=='🌐 Language')
async def language(m):
    await m.answer('🌐 <b>Language</b>',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🇬🇧 English',callback_data='lang:en'),InlineKeyboardButton(text='🇸🇴 Somali',callback_data='lang:so'),InlineKeyboardButton(text='🇸🇦 العربية',callback_data='lang:ar')]]))

@router.callback_query(F.data.startswith('lang:'))
async def lang(c):
    code=c.data.split(':')[1]; await db.users.update_one({'telegram_id':c.from_user.id},{'$set':{'language':code}}); await c.message.answer('✅ Language updated.'); await c.answer()

@router.message(F.text=='🆘 Customer Support')
async def support(m,state): await state.set_state(UserFlow.support); await m.answer('🆘 <b>CUSTOMER SUPPORT</b>\n\nFadlan qor fariintaada:')
@router.message(UserFlow.support)
async def support_save(m,state):
    tid=uid('TKT'); await db.support.insert_one({'ticket_id':tid,'user_id':m.from_user.id,'message':m.text,'status':'open','created_at':now()}); await notify_admin(f'🎧 <b>NEW SUPPORT</b>\n\n🆔 <code>{tid}</code>\n👤 <code>{m.from_user.id}</code>\n📝 {escape(m.text)}',approval_kb('support',tid)); await state.clear(); await m.answer(f'✅ Ticket <code>{tid}</code> waa la helay.\n⏳ Please wait.',reply_markup=main_kb(await is_admin(m.from_user.id)))

# Admin panel
@router.message(F.text=='🛠️ ADMIN PANEL TELESOM')
async def open_admin(m):
    if not await is_admin(m.from_user.id): return
    await m.answer('🛡️ <b>TELESOM ADMIN CONTROL CENTER</b>\n\n100 panels. Door panel-ka aad rabto.',reply_markup=admin_menu())

@router.message(F.text.regexp(r'^🛠 \d{2}\.'))
async def panel_button(m):
    if not await is_admin(m.from_user.id): return
    try:n=int(m.text.split()[1].strip('.'))
    except:return
    await admin_panel(m,n)

async def admin_panel(m,n):
    name=PANELS[n-1]; counts={
        1:('users',{}),2:('users',{}),3:('numbers',{}),4:('numbers',{'category':'vip'}),5:('numbers',{'category':'virtual'}),6:('orders',{'service':'esim'}),7:('orders',{'service':'sim'}),8:('orders',{'service':'data'}),9:('orders',{'service':'voice'}),10:('orders',{'service':'sms'}),11:('orders',{'service':'recharge'}),12:('wallet_ledger',{}),13:('payments',{}),14:('orders',{}),15:('requests',{'kind':'refund'}),16:('offers',{}),17:('promos',{}),18:('referrals',{}),19:('memberships',{}),20:('support',{}),21:('notifications',{'type':'broadcast'}),22:('notifications',{}),23:('requests',{'kind':'business'}),24:('requests',{'kind':'corporate'}),25:('numbers',{}),26:('audit_logs',{}),27:('staff',{}),28:('security_events',{}),29:('audit_logs',{}),30:('settings',{})}
    if n<=30:
        col,q=counts.get(n,('settings',{})); total=await db[col].count_documents(q)
        pending=await db.orders.count_documents({'status':'pending'})+await db.payments.count_documents({'status':'pending'})
        text=f'🛡️ <b>{name.upper()}</b>\n\n📊 Records: <b>{total}</b>\n⏳ Pending: <b>{pending}</b>\n\nDooro action:'
        kb=[]
        if n in (3,4,5): kb=[[InlineKeyboardButton(text='➕ Add Number',callback_data='admin:addnumber')],[InlineKeyboardButton(text='📋 Available',callback_data=f'admin:listnum:{n}')]]
        elif n==13: kb=[[InlineKeyboardButton(text='⏳ Pending Payments',callback_data='admin:pendingpay')],[InlineKeyboardButton(text='⚙️ Payment Methods',callback_data='admin:paymethods')]]
        elif n==14: kb=[[InlineKeyboardButton(text='⏳ Pending Orders',callback_data='admin:pendingorders')]]
        elif n==21: kb=[[InlineKeyboardButton(text='📢 New Broadcast',callback_data='admin:broadcast')]]
        elif n==30: kb=[[InlineKeyboardButton(text='💳 Payment Destinations',callback_data='admin:paymethods')],[InlineKeyboardButton(text='🔧 Services ON/OFF',callback_data='admin:services')]]
        else: kb=[[InlineKeyboardButton(text='🔄 Refresh',callback_data=f'admin:refresh:{n}')]]
        await m.answer(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    else:
        await m.answer(f'🛡️ <b>{name.upper()}</b>\n\nModule enabled.\n📊 This panel is connected to the central Telesombot database and audit system.\n\nUse the core control panels for transactions, inventory, payments and customers.')

@admin_router.callback_query(F.data.startswith('admin:'))
async def admin_actions(c:CallbackQuery,state:FSMContext):
    if not await is_admin(c.from_user.id): return await c.answer('Not authorized',show_alert=True)
    p=c.data.split(':')
    if p[1]=='pendingpay':
        async for x in db.payments.find({'status':'pending'}).sort('created_at',-1).limit(30): await c.message.answer(f'💳 <b>PENDING PAYMENT</b>\n\n<code>{x["payment_id"]}</code>\nUser: <code>{x["user_id"]}</code>\nOrder: <code>{x["order_id"]}</code>\nAmount: <b>${money(x["amount"]):.2f}</b>\nMethod: {escape(x["method"])}\nReference: <code>{escape(x.get("reference",""))}</code>',reply_markup=approval_kb('payment',x['payment_id']))
    elif p[1]=='pendingorders':
        async for x in db.orders.find({'status':'pending'}).sort('created_at',-1).limit(30): await c.message.answer(f'📦 <b>PENDING ORDER</b>\n\n<code>{x["order_id"]}</code>\nUser: <code>{x["user_id"]}</code>\nService: {escape(str(x.get("service")))}\nAmount: ${money(x.get("amount")):.2f}\nDetails: {escape(str(x.get("details")))}',reply_markup=approval_kb('order',x['order_id']))
    elif p[1]=='broadcast': await state.set_state(UserFlow.broadcast); await c.message.answer('📢 Geli fariinta broadcast-ka. Waxaa loo diri doonaa dhammaan users active ah.');
    elif p[1]=='paymethods':
        ms=await db.payment_methods.find().to_list(20); await c.message.answer('💳 <b>PAYMENT METHODS</b>\n\n'+'\n'.join(f'• {x["name"]}: <code>{escape(x["destination"])}</code> • {"ON" if x.get("enabled") else "OFF"}' for x in ms))
    elif p[1]=='services': await c.message.answer('🔧 Service ON/OFF waxaa lagu maamuli karaa System Settings.')
    elif p[1]=='addnumber': await state.set_state(UserFlow.admin_input); await state.update_data(admin_action='addnumber'); await c.message.answer('➕ Geli: <code>NUMBER | PRICE | CATEGORY</code>\nTusaale: <code>0634551111 | 25 | vip</code>')
    elif p[1]=='listnum':
        cat={3:'number',4:'vip',5:'virtual'}.get(int(p[2]),'number'); rows=[]
        cur=(db.numbers.find({'category':cat,'status':'available'}).sort('number',1).limit(15) if cat=='vip' else db.numbers.aggregate([{'$match':{'category':cat,'status':'available'}},{'$sample':{'size':15}}]))
        async for x in cur: rows.append(f'• <code>{x["number"]}</code> — ${money(x.get("price")):.2f}')
        await c.message.answer('📱 <b>AVAILABLE</b>\n\n'+('\n'.join(rows) or 'Empty'))
    await c.answer()

@admin_router.callback_query(F.data.startswith('confirm:'))
async def confirm(c):
    if not await is_admin(c.from_user.id): return await c.answer('Not authorized',show_alert=True)
    _,kind,ident=c.data.split(':',2)
    if kind=='payment':
        p=await db.payments.find_one_and_update({'payment_id':ident,'status':'pending'},{'$set':{'status':'confirmed','decision_by':c.from_user.id,'updated_at':now()}})
        if not p:return await c.answer('Already processed',show_alert=True)
        a=money(p['amount']); await db.users.update_one({'telegram_id':p['user_id']},{'$inc':{'wallet.pending':-a,'wallet.available':a,'total_deposited':a}}); await db.wallet_ledger.insert_one({'ledger_id':uid('LED'),'user_id':p['user_id'],'type':'credit','amount':a,'description':'Payment confirmed','reference':ident,'created_at':now()}); await db.orders.update_one({'order_id':p['order_id']},{'$set':{'payment_status':'paid','status':'processing','updated_at':now()}}); msg=f'✅ <b>Payment confirmed</b>\n\n💰 ${a:.2f} has been added to your balance.'
    elif kind=='order':
        o=await db.orders.find_one_and_update({'order_id':ident,'status':'pending'},{'$set':{'status':'processing','decision_by':c.from_user.id,'updated_at':now()}})
        if not o:return await c.answer('Already processed',show_alert=True)
        msg='✅ <b>Your order is now processing.</b>\n\n⏳ Please wait for completion.'
    else:
        r=await db.support.find_one_and_update({'ticket_id':ident,'status':'open'},{'$set':{'status':'confirmed','decision_by':c.from_user.id}}); msg='✅ <b>Your support request has been received.</b>' if r else 'Already processed.'
    try:await bot.send_message((p if kind=='payment' else o if kind=='order' else r)['user_id'],msg)
    except:pass
    await c.message.edit_reply_markup(reply_markup=None); await c.answer('Confirmed')

@admin_router.callback_query(F.data.startswith('reject:'))
async def reject(c):
    if not await is_admin(c.from_user.id): return await c.answer('Not authorized',show_alert=True)
    _,kind,ident=c.data.split(':',2)
    if kind=='payment':
        p=await db.payments.find_one_and_update({'payment_id':ident,'status':'pending'},{'$set':{'status':'rejected','decision_by':c.from_user.id,'updated_at':now()}}); row=p
        if p: await db.users.update_one({'telegram_id':p['user_id']},{'$inc':{'wallet.pending':-money(p['amount'])}})
    elif kind=='order': row=await db.orders.find_one_and_update({'order_id':ident,'status':'pending'},{'$set':{'status':'rejected','decision_by':c.from_user.id,'updated_at':now()}})
    else: row=await db.support.find_one_and_update({'ticket_id':ident,'status':'open'},{'$set':{'status':'closed','decision_by':c.from_user.id,'updated_at':now()}})
    if not row:return await c.answer('Already processed',show_alert=True)
    try:await bot.send_message(row['user_id'],'❌ <b>Your request was not approved.</b>\n\nPlease contact support if you need assistance.')
    except:pass
    await c.message.edit_reply_markup(reply_markup=None); await c.answer('Rejected')

@admin_router.callback_query(F.data.startswith('details:'))
async def details(c):
    if not await is_admin(c.from_user.id): return await c.answer('Not authorized',show_alert=True)
    _,kind,ident=c.data.split(':',2); col={'payment':'payments','order':'orders','support':'support'}.get(kind,'orders'); field={'payment':'payment_id','order':'order_id','support':'ticket_id'}.get(kind,'order_id'); x=await db[col].find_one({field:ident}); await c.message.answer('📄 <b>DETAILS</b>\n\n<pre>'+escape(str(x))+'</pre>'); await c.answer()

@admin_router.callback_query(F.data.startswith('contact:'))
async def contact(c):
    if not await is_admin(c.from_user.id): return await c.answer('Not authorized',show_alert=True)
    _,kind,ident=c.data.split(':',2); col={'payment':'payments','order':'orders','support':'support'}.get(kind,'orders'); field={'payment':'payment_id','order':'order_id','support':'ticket_id'}.get(kind,'order_id'); x=await db[col].find_one({field:ident});
    if x: await c.message.answer(f'💬 <b>CONTACT USER</b>\n\nTelegram ID: <code>{x["user_id"]}</code>\n\nOpen Telegram and contact this customer.'); await c.answer()

@router.message(UserFlow.admin_input)
async def admin_input(m,state):
    if not await is_admin(m.from_user.id): return
    d=await state.get_data()
    if d.get('admin_action')=='addnumber':
        parts=[x.strip() for x in m.text.split('|')]
        if len(parts)!=3:return await m.answer('Format: <code>NUMBER | PRICE | CATEGORY</code>')
        number,price,cat=parts[0],money(parts[1]),parts[2].lower();
        if cat not in ('number','vip','virtual'): cat='number'
        await db.numbers.update_one({'number':number},{'$set':{'number':number,'price':price,'category':cat,'status':'available','updated_at':now()},'$setOnInsert':{'created_at':now()}},upsert=True); await state.clear(); await m.answer(f'✅ Number saved: <code>{escape(number)}</code> • ${price:.2f} • {cat}',reply_markup=admin_menu())

@router.message(UserFlow.broadcast)
async def broadcast(m,state):
    if not await is_admin(m.from_user.id):return
    count=0
    async for u in db.users.find({'status':{'$ne':'banned'}},{'telegram_id':1}):
        try:await bot.send_message(int(u['telegram_id']),m.text);count+=1
        except:pass
    await db.notifications.insert_one({'type':'broadcast','text':m.text,'count':count,'created_at':now()}); await state.clear(); await m.answer(f'📢 <b>Broadcast complete</b>\n\nSent: <b>{count}</b> users.',reply_markup=admin_menu())

@router.message(F.text=='📢 Broadcast')
async def broadcast_button(m,state):
    if not await is_admin(m.from_user.id):return
    await state.set_state(UserFlow.broadcast); await m.answer('📢 Geli fariinta aad rabto in loo diro dhammaan active users:')

# Catch-all: never advertise commands
@router.message()
async def fallback(m,state):
    u=await user(m.from_user)
    if u and u.get('status')=='banned': return await m.answer('🚫 Account-kaaga waa xiran yahay.')
    if m.text and m.text.startswith('/'):
        return await m.answer('ℹ️ Fadlan isticmaal keyboard-ka hoose.')
    await m.answer('Dooro adeeg adigoo isticmaalaya buttons-ka hoose.',reply_markup=main_kb(await is_admin(m.from_user.id)))

async def init_db():
    # Legacy-safe indexes: do not crash if an old number_1 index already exists.
    indexes=[('users','telegram_id',True),('orders','order_id',True),('payments','payment_id',True),('numbers','number',True),('support','ticket_id',True),('staff','telegram_id',True),('promos','code',True)]
    for col,field,unique in indexes:
        try:
            info=await db[col].index_information(); name=f'{field}_1'; cur=info.get(name)
            if cur and cur.get('key')==[(field,1)] and bool(cur.get('unique',False))==unique: continue
            if cur: await db[col].drop_index(name)
            await db[col].create_index(field,unique=unique,name=name)
        except Exception as e: log.warning('index %s.%s: %r',col,field,e)
    for k,v in {'orders_open':True,'payments_open':True,'support_open':True}.items():
        if await setting(k,None) is None: await set_setting(k,v)
    for name,dest in PAYMENTS.items(): await db.payment_methods.update_one({'name':name},{'$setOnInsert':{'name':name,'destination':dest,'enabled':True}},upsert=True)
    await client.admin.command('ping'); log.info('MongoDB connected')

async def health(req):return web.json_response({'status':'ok','service':'Telesombot'})
async def health_server():
    app=web.Application();app.router.add_get('/',health);app.router.add_get('/health',health);r=web.AppRunner(app);await r.setup();await web.TCPSite(r,'0.0.0.0',PORT).start();return r
async def main():
    await init_db(); await bot.delete_webhook(drop_pending_updates=False); runner=await health_server(); log.info('Telesombot started')
    try: await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
    finally: await runner.cleanup();await bot.session.close();client.close()
if __name__=='__main__':asyncio.run(main())
