import os
import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MONGO_URI = os.getenv("MONGO_URI", "").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "0").strip()
PORT = int(os.getenv("PORT", "10000") or "10000")
DB_NAME = os.getenv("DB_NAME", "telesombot")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")
if not MONGO_URI:
    raise RuntimeError("MONGO_URI is missing")
try:
    MAIN_ADMIN = int(ADMIN_ID_RAW)
except ValueError:
    raise RuntimeError("ADMIN_ID must be a Telegram numeric ID")
if MAIN_ADMIN <= 0:
    raise RuntimeError("ADMIN_ID is missing or invalid")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("telesombot")

client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=10000)
db = client[DB_NAME]
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
admin_router = Router()
dp.include_router(router)
dp.include_router(admin_router)

# -----------------------------
# Helpers
# -----------------------------
def now():
    return datetime.now(timezone.utc)


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def money(v) -> float:
    try:
        return round(float(v), 2)
    except Exception:
        return 0.0


def safe_text(v, default="-"):
    s = str(v or "").strip()
    return s if s else default


def admin_kb(req_id: str, kind: str = "request"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ CONFIRM", callback_data=f"approve:{kind}:{req_id}"),
         InlineKeyboardButton(text="❌ REJECT", callback_data=f"reject:{kind}:{req_id}")],
        [InlineKeyboardButton(text="📄 DETAILS", callback_data=f"details:{kind}:{req_id}")],
        [InlineKeyboardButton(text="💬 CONTACT USER", callback_data=f"contact:{kind}:{req_id}")],
    ])


async def get_setting(key, default=None):
    row = await db.settings.find_one({"_id": key})
    return row.get("value", default) if row else default


async def set_setting(key, value):
    await db.settings.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)


async def audit(actor, action, target=None, data=None):
    await db.audit_logs.insert_one({
        "actor": int(actor), "action": action, "target": target,
        "data": data or {}, "created_at": now()
    })


async def get_user(tg_id: int):
    return await db.users.find_one({"telegram_id": int(tg_id)})


async def ensure_user(user) -> bool:
    """Create/update user without the MongoDB $set/$setOnInsert path conflict."""
    tg_id = int(user.id)
    existing = await get_user(tg_id)
    update = {
        "$set": {
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "updated_at": now(),
        },
        "$setOnInsert": {
            "telegram_id": tg_id,
            "language": "en",
            "status": "active",
            "wallet": {"available": 0.0, "pending": 0.0},
            "total_deposited": 0.0,
            "total_spent": 0.0,
            "referrals": 0,
            "created_at": now(),
        },
    }
    result = await db.users.update_one({"telegram_id": tg_id}, update, upsert=True)
    is_new = existing is None and result.upserted_id is not None
    if is_new:
        await audit(tg_id, "user_registered", str(tg_id), {"username": user.username})
        await notify_admin_new_user(user)
    return is_new


async def lang_of(tg_id: int):
    u = await get_user(tg_id)
    return (u or {}).get("language", "en")


TEXT = {
    "en": {
        "welcome": "👋 Welcome to Telesombot.\n\nUse /help to see all customer commands.",
        "saved": "✅ Language changed to English.",
        "created": "✅ Request <b>{id}</b> created.\n⏳ Waiting for admin approval.",
        "help": """📚 <b>Customer Commands</b>\n\n/start — Start\n/help — Help\n/lang en|so|ar — Language\n/services — Services\n/numbers — Regular numbers\n/vip — VIP numbers\n/virtual — Virtual numbers\n/esim — eSIM\n/sim — Physical SIM\n/data — Data\n/voice — Voice\n/sms — SMS\n/recharge — Recharge\n/order SERVICE DETAILS — Create order\n/pay ORDER_ID METHOD AMOUNT [REFERENCE] — Payment\n/orders — Orders\n/payments — Payments\n/wallet — Wallet\n/referral — Referral\n/support MESSAGE — Support\n/profile — Profile\n/contact — Contact""",
        "created_short": "Request {id} created. Awaiting admin approval.",
    },
    "so": {
        "welcome": "👋 Ku soo dhowow Telesombot.\n\nIsticmaal /help si aad u aragto dhammaan amarada.",
        "saved": "✅ Luuqadda waxaa loo beddelay Somali.",
        "created": "✅ Codsiga <b>{id}</b> waa la sameeyay.\n⏳ Wuxuu sugayaa oggolaanshaha admin-ka.",
        "help": """📚 <b>Amarada Macmiilka</b>\n\n/start — Bilow\n/help — Caawimo\n/lang en|so|ar — Luuqad\n/services — Adeegyada\n/numbers — Numberro caadi ah\n/vip — VIP numbers\n/virtual — Virtual numbers\n/esim — eSIM\n/sim — SIM\n/data — Data\n/voice — Voice\n/sms — SMS\n/recharge — Recharge\n/order SERVICE DETAILS — Dalab\n/pay ORDER_ID METHOD AMOUNT [REFERENCE] — Lacag\n/orders — Dalabyada\n/payments — Lacagaha\n/wallet — Wallet\n/referral — Referral\n/support MESSAGE — Support\n/profile — Profile\n/contact — Contact""",
        "created_short": "Codsiga {id} waa la sameeyay. Wuxuu sugayaa admin.",
    },
    "ar": {
        "welcome": "👋 مرحباً بك في Telesombot.\n\nاستخدم /help لرؤية أوامر العملاء.",
        "saved": "✅ تم تغيير اللغة إلى العربية.",
        "created": "✅ تم إنشاء الطلب <b>{id}</b>.\n⏳ بانتظار موافقة المشرف.",
        "help": """📚 <b>أوامر العميل</b>\n\n/start — بدء\n/help — مساعدة\n/lang en|so|ar — اللغة\n/services — الخدمات\n/numbers — الأرقام\n/vip — أرقام VIP\n/virtual — أرقام افتراضية\n/esim — eSIM\n/sim — SIM\n/data — البيانات\n/voice — المكالمات\n/sms — SMS\n/recharge — شحن\n/order SERVICE DETAILS — طلب\n/pay ORDER_ID METHOD AMOUNT [REFERENCE] — الدفع\n/orders — الطلبات\n/payments — المدفوعات\n/wallet — المحفظة\n/referral — الإحالة\n/support MESSAGE — الدعم\n/profile — الملف\n/contact — التواصل""",
        "created_short": "تم إنشاء الطلب {id}. بانتظار موافقة المشرف.",
    },
}


def t(lang, key, **kwargs):
    d = TEXT.get(lang, TEXT["en"])
    return d.get(key, TEXT["en"].get(key, key)).format(**kwargs)


SERVICES = {
    "numbers": "Regular Numbers", "vip": "VIP Numbers", "virtual": "Virtual Numbers",
    "esim": "eSIM", "sim": "Physical SIM", "data": "Data Bundles", "voice": "Voice Bundles",
    "sms": "SMS Services", "recharge": "Recharge", "fiber": "Fiber / Internet",
    "zaad": "ZAAD Services", "business": "Business Services", "corporate": "Corporate",
    "iot": "IoT", "cloud": "Cloud", "offers": "Offers", "membership": "Memberships",
}

PAYMENT_DEFAULTS = {
    "Golis": "*883*0907868526*$#",
    "Telesom": "*880*0907868526*$#",
    "BNB": "0x1f12ffDc93E49eff0c78672Ab6abA62410c05a32",
    "USDT-BEP20": "0x6AC864773259fa5175251829cb0E93ffb4cE6feC",
}

PANELS = [
    "Dashboard", "Customers", "Numbers", "VIP Numbers", "Virtual Numbers", "eSIM",
    "Physical SIM", "Data", "Voice", "SMS", "Recharge", "Wallets", "Payments", "Orders",
    "Refunds", "Offers", "Promo Codes", "Referrals", "Memberships", "Support", "Broadcast",
    "Notifications", "Business", "Corporate", "Inventory", "Analytics", "Staff & Permissions",
    "Security", "Audit Logs", "System Settings"
]

PERMISSION_NAMES = {
    "admin", "customers", "numbers", "payments", "orders", "wallets", "refunds", "offers",
    "promos", "broadcast", "support", "analytics", "staff", "settings", "security"
}


async def is_admin(tg_id: int) -> bool:
    if int(tg_id) == MAIN_ADMIN:
        return True
    staff = await db.staff.find_one({"telegram_id": int(tg_id), "active": True})
    return bool(staff and "admin" in staff.get("permissions", []))


async def has_permission(tg_id: int, permission: str) -> bool:
    if int(tg_id) == MAIN_ADMIN:
        return True
    staff = await db.staff.find_one({"telegram_id": int(tg_id), "active": True})
    return bool(staff and (permission in staff.get("permissions", []) or "admin" in staff.get("permissions", [])))


async def require_admin(m: Message, permission="admin"):
    return await has_permission(m.from_user.id, permission)


async def notify_admin(text, reply_markup=None):
    try:
        await bot.send_message(MAIN_ADMIN, text, reply_markup=reply_markup)
    except Exception as e:
        log.warning("Admin notification failed: %r", e)


async def notify_admin_new_user(user):
    text = (
        "🆕 <b>NEW CUSTOMER</b>\n\n"
        f"👤 Name: {safe_text(user.full_name)}\n"
        f"🆔 Telegram ID: <code>{user.id}</code>\n"
        f"🔗 Username: @{safe_text(user.username, 'none')}\n\n"
        "Customer has been registered automatically."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="👤 CUSTOMER", callback_data=f"customer:{user.id}"),
        InlineKeyboardButton(text="🚫 BAN", callback_data=f"ban:{user.id}"),
    ]])
    await notify_admin(text, kb)


async def request_doc(kind, user_id, data):
    rid = uid("REQ")
    doc = {
        "request_id": rid, "kind": kind, "user_id": int(user_id), "data": data,
        "status": "pending", "created_at": now(), "updated_at": now()
    }
    await db.requests.insert_one(doc)
    return rid


async def send_request_to_admin(rid):
    r = await db.requests.find_one({"request_id": rid})
    if not r:
        return
    text = (
        "🔔 <b>NEW APPROVAL REQUEST</b>\n\n"
        f"🆔 <code>{rid}</code>\n"
        f"📌 Type: <b>{safe_text(r.get('kind'))}</b>\n"
        f"👤 User: <code>{r.get('user_id')}</code>\n"
        f"📦 Details: <code>{safe_text(r.get('data'))}</code>\n\n"
        "Choose an action:"
    )
    await notify_admin(text, admin_kb(rid, "request"))


async def create_order(user_id, service, details, amount=0.0):
    oid = uid("ORD")
    doc = {
        "order_id": oid, "user_id": int(user_id), "service": service, "details": details,
        "amount": money(amount), "status": "pending", "created_at": now(), "updated_at": now()
    }
    await db.orders.insert_one(doc)
    rid = await request_doc("order", user_id, {"order_id": oid, "service": service, "details": details, "amount": money(amount)})
    await db.orders.update_one({"order_id": oid}, {"$set": {"request_id": rid}})
    await send_request_to_admin(rid)
    return oid, rid


async def ledger(user_id, entry_type, amount, description, ref=None):
    await db.wallet_ledger.insert_one({
        "ledger_id": uid("LED"), "user_id": int(user_id), "type": entry_type,
        "amount": money(amount), "description": description, "reference": ref, "created_at": now()
    })


async def wallet_credit(user_id, amount, description, ref=None):
    amount = money(amount)
    if amount <= 0:
        return False
    await db.users.update_one({"telegram_id": int(user_id)}, {"$inc": {"wallet.available": amount, "total_deposited": amount}})
    await ledger(user_id, "credit", amount, description, ref)
    return True


async def wallet_debit(user_id, amount, description, ref=None):
    amount = money(amount)
    if amount <= 0:
        return False
    result = await db.users.update_one(
        {"telegram_id": int(user_id), "wallet.available": {"$gte": amount}},
        {"$inc": {"wallet.available": -amount, "total_spent": amount}}
    )
    if result.modified_count != 1:
        return False
    await ledger(user_id, "debit", -amount, description, ref)
    return True


async def init_db():
    indexes = [
        ("users", "telegram_id", True), ("requests", "request_id", True),
        ("orders", "order_id", True), ("payments", "payment_id", True),
        ("numbers", "number", True), ("promos", "code", True),
        ("staff", "telegram_id", True), ("audit_logs", "created_at", False),
        ("wallet_ledger", "user_id", False), ("support", "ticket_id", True),
        ("notifications", "created_at", False), ("memberships", "membership_id", True),
    ]
    for collection, field, unique in indexes:
        try:
            existing = await db[collection].index_information()
            # If an old index with the same generated name exists but has different
            # options (for example number_1 without sparse=True), do not crash.
            # Reuse compatible indexes and replace incompatible ones safely.
            name = f"{field}_1"
            current = existing.get(name)
            if current:
                same_key = current.get("key") == [(field, 1)]
                same_unique = bool(current.get("unique", False)) == bool(unique)
                if same_key and same_unique:
                    continue
                await db[collection].drop_index(name)
            await db[collection].create_index(field, unique=unique, name=name)
        except Exception as e:
            log.warning("Index %s.%s could not be initialized: %r", collection, field, e)
    for key, value in {
        "registration_open": True, "orders_open": True, "payments_open": True,
        "support_open": True, "trial_days": 1, "referral_reward": 0.0,
    }.items():
        if await db.settings.find_one({"_id": key}) is None:
            await set_setting(key, value)
    for name, destination in PAYMENT_DEFAULTS.items():
        await db.payment_methods.update_one(
            {"name": name}, {"$setOnInsert": {"name": name, "destination": destination, "enabled": True}}, upsert=True
        )
    await db.system_locks.update_one({"_id": "bot"}, {"$setOnInsert": {"owner": None}}, upsert=True)
    await client.admin.command("ping")
    log.info("MongoDB connected")


# ---------------- Customer commands ----------------
@router.message(CommandStart())
async def start(m: Message):
    await ensure_user(m.from_user)
    await m.answer(t(await lang_of(m.from_user.id), "welcome"))


@router.message(Command("help"))
async def help_cmd(m: Message):
    await ensure_user(m.from_user)
    await m.answer(t(await lang_of(m.from_user.id), "help"))


@router.message(Command("lang", "language"))
async def language_cmd(m: Message):
    await ensure_user(m.from_user)
    parts = (m.text or "").split()
    if len(parts) != 2 or parts[1].lower() not in {"en", "so", "ar"}:
        return await m.answer("Usage: /lang en\n/lang so\n/lang ar")
    code = parts[1].lower()
    await db.users.update_one({"telegram_id": m.from_user.id}, {"$set": {"language": code}})
    await m.answer(t(code, "saved"))


@router.message(Command("services"))
async def services_cmd(m: Message):
    await ensure_user(m.from_user)
    await m.answer("📋 <b>Services</b>\n\n" + "\n".join(f"/{k} — {v}" for k, v in SERVICES.items()))


@router.message(Command(*list(SERVICES.keys())))
async def service_cmd(m: Message):
    await ensure_user(m.from_user)
    if not await get_setting("orders_open", True):
        return await m.answer("🔒 Ordering is currently closed. Please try again later.")
    command = (m.text or "").split()[0][1:]
    details = (m.text or "").partition(" ")[2].strip()
    if not details:
        return await m.answer(f"Usage: /{command} <details>")
    oid, rid = await create_order(m.from_user.id, command, details)
    await m.answer(t(await lang_of(m.from_user.id), "created", id=rid) + f"\n📦 Order: <code>{oid}</code>")


@router.message(Command("order"))
async def order_cmd(m: Message):
    await ensure_user(m.from_user)
    if not await get_setting("orders_open", True):
        return await m.answer("🔒 Orders are currently closed.")
    parts = (m.text or "").split(maxsplit=2)
    if len(parts) < 3:
        return await m.answer("Usage: /order SERVICE DETAILS")
    oid, rid = await create_order(m.from_user.id, parts[1], parts[2])
    await m.answer(t(await lang_of(m.from_user.id), "created", id=rid) + f"\n📦 Order: <code>{oid}</code>")


@router.message(Command("pay"))
async def pay_cmd(m: Message):
    await ensure_user(m.from_user)
    if not await get_setting("payments_open", True):
        return await m.answer("🔒 Payments are currently closed.")
    p = (m.text or "").split(maxsplit=4)
    if len(p) < 4:
        return await m.answer("Usage: /pay ORDER_ID METHOD AMOUNT [REFERENCE]\nMethods: Golis, Telesom, BNB, USDT-BEP20")
    order_id, method = p[1], p[2]
    amount = money(p[3])
    reference = p[4] if len(p) > 4 else ""
    method_doc = await db.payment_methods.find_one({"name": method, "enabled": True})
    if not method_doc:
        return await m.answer("❌ Payment method is unavailable.")
    order = await db.orders.find_one({"order_id": order_id, "user_id": m.from_user.id})
    if not order:
        return await m.answer("❌ Order not found.")
    if amount <= 0:
        return await m.answer("❌ Amount must be greater than 0.")
    pid = uid("PAY")
    await db.payments.insert_one({
        "payment_id": pid, "user_id": m.from_user.id, "order_id": order_id,
        "method": method, "destination": method_doc["destination"], "amount": amount,
        "reference": reference, "status": "pending", "created_at": now(), "updated_at": now()
    })
    await db.users.update_one({"telegram_id": m.from_user.id}, {"$inc": {"wallet.pending": amount}})
    await notify_admin(
        "💳 <b>NEW PAYMENT</b>\n\n"
        f"🆔 <code>{pid}</code>\n📦 Order: <code>{order_id}</code>\n"
        f"👤 User: <code>{m.from_user.id}</code>\n💰 Amount: <b>${amount:.2f}</b>\n"
        f"💳 Method: <b>{method}</b>\n🔖 Reference: <code>{safe_text(reference)}</code>\n"
        f"📍 Destination: <code>{method_doc['destination']}</code>",
        admin_kb(pid, "payment")
    )
    await m.answer(f"💳 Payment <code>{pid}</code> created.\n📍 {method}: <code>{method_doc['destination']}</code>\n⏳ Pending admin confirmation.")


@router.message(Command("orders"))
async def orders_cmd(m: Message):
    await ensure_user(m.from_user)
    rows = []
    async for x in db.orders.find({"user_id": m.from_user.id}).sort("created_at", -1).limit(20):
        rows.append(f"<code>{x['order_id']}</code> | {x.get('service')} | {x.get('status')} | ${money(x.get('amount')):.2f}")
    await m.answer("📦 <b>Your Orders</b>\n\n" + ("\n".join(rows) or "No orders yet."))


@router.message(Command("payments"))
async def payments_cmd(m: Message):
    await ensure_user(m.from_user)
    rows = []
    async for x in db.payments.find({"user_id": m.from_user.id}).sort("created_at", -1).limit(20):
        rows.append(f"<code>{x['payment_id']}</code> | ${money(x.get('amount')):.2f} | {x.get('method')} | {x.get('status')}")
    await m.answer("💳 <b>Your Payments</b>\n\n" + ("\n".join(rows) or "No payments yet."))


@router.message(Command("wallet"))
async def wallet_cmd(m: Message):
    await ensure_user(m.from_user)
    u = await get_user(m.from_user.id)
    w = u.get("wallet", {}) if u else {}
    await m.answer(
        f"💰 <b>Wallet</b>\n\nAvailable: <b>${money(w.get('available')):.2f}</b>\n"
        f"Pending: <b>${money(w.get('pending')):.2f}</b>\n"
        f"Total deposited: ${money(u.get('total_deposited')):.2f}\nTotal spent: ${money(u.get('total_spent')):.2f}"
    )


@router.message(Command("profile"))
async def profile_cmd(m: Message):
    await ensure_user(m.from_user)
    u = await get_user(m.from_user.id)
    await m.answer(
        "👤 <b>Profile</b>\n\n"
        f"ID: <code>{m.from_user.id}</code>\nName: {safe_text(m.from_user.full_name)}\n"
        f"Username: @{safe_text(m.from_user.username, 'none')}\n"
        f"Language: {u.get('language', 'en')}\nStatus: {u.get('status', 'active')}"
    )


@router.message(Command("referral"))
async def referral_cmd(m: Message):
    await ensure_user(m.from_user)
    u = await get_user(m.from_user.id)
    await m.answer(f"🎁 <b>Referral</b>\n\nYour referral code: <code>{m.from_user.id}</code>\nReferrals: {int(u.get('referrals', 0))}")


@router.message(Command("support"))
async def support_cmd(m: Message):
    await ensure_user(m.from_user)
    if not await get_setting("support_open", True):
        return await m.answer("🔒 Support is currently closed.")
    text = (m.text or "").partition(" ")[2].strip()
    if not text:
        return await m.answer("Usage: /support YOUR_MESSAGE")
    tid = uid("TKT")
    await db.support.insert_one({"ticket_id": tid, "user_id": m.from_user.id, "message": text, "status": "open", "created_at": now()})
    await notify_admin("🎧 <b>NEW SUPPORT TICKET</b>\n\n" f"Ticket: <code>{tid}</code>\nUser: <code>{m.from_user.id}</code>\nMessage: {text}", admin_kb(tid, "support"))
    await m.answer(f"🎧 Ticket <code>{tid}</code> created. Awaiting admin.")


@router.message(Command("contact"))
async def contact_cmd(m: Message):
    await m.answer("☎️ Contact support with /support YOUR_MESSAGE")


# -----------------------------
# Admin commands
# -----------------------------
@admin_router.message(Command("admin"))
async def admin_cmd(m: Message):
    if not await require_admin(m): return
    await m.answer("🛠 <b>TELESOMBOT ADMIN CONTROL</b>\n\n" + "\n".join(f"{i+1}. {p}" for i, p in enumerate(PANELS)) + "\n\nUse /panel 1-30 or /pending.")


@admin_router.message(Command("panel"))
async def panel_cmd(m: Message):
    if not await require_admin(m): return
    p = (m.text or "").split()
    if len(p) != 2 or not p[1].isdigit() or not 1 <= int(p[1]) <= 30:
        return await m.answer("Usage: /panel 1-30")
    n = int(p[1]); name = PANELS[n-1]
    counts = {
        1: await db.users.count_documents({}), 2: await db.users.count_documents({}),
        3: await db.numbers.count_documents({}), 4: await db.numbers.count_documents({"category":"vip"}),
        5: await db.numbers.count_documents({"category":"virtual"}), 6: await db.orders.count_documents({"service":"esim"}),
        7: await db.orders.count_documents({"service":"sim"}), 8: await db.orders.count_documents({"service":"data"}),
        9: await db.orders.count_documents({"service":"voice"}), 10: await db.orders.count_documents({"service":"sms"}),
        11: await db.orders.count_documents({"service":"recharge"}), 12: await db.wallet_ledger.count_documents({}),
        13: await db.payments.count_documents({}), 14: await db.orders.count_documents({}),
        15: await db.requests.count_documents({"kind":"refund"}), 16: await db.offers.count_documents({}),
        17: await db.promos.count_documents({}), 18: await db.referrals.count_documents({}),
        19: await db.memberships.count_documents({}), 20: await db.support.count_documents({}),
        21: await db.notifications.count_documents({"type":"broadcast"}), 22: await db.notifications.count_documents({}),
        23: await db.requests.count_documents({"kind":"business"}), 24: await db.requests.count_documents({"kind":"corporate"}),
        25: await db.numbers.count_documents({}), 26: await db.audit_logs.count_documents({}),
        27: await db.staff.count_documents({}), 28: await db.security_events.count_documents({}),
        29: await db.audit_logs.count_documents({}), 30: await db.settings.count_documents({}),
    }
    extra = f"\nRecords: <b>{counts.get(n, 0)}</b>"
    commands = {
        3: "/addnumber NUMBER PRICE CATEGORY",
        4: "/addvip NUMBER PRICE",
        16: "/addoffer TITLE TEXT",
        17: "/addpromo CODE DISCOUNT",
        21: "/broadcast MESSAGE",
        27: "/addstaff TELEGRAM_ID permission1,permission2",
        30: "/set KEY VALUE",
    }
    await m.answer(f"🛠 <b>PANEL {n}: {name}</b>{extra}\n\n" + commands.get(n, "Use /pending and the admin action commands for this panel."))


@admin_router.message(Command("pending"))
async def pending_cmd(m: Message):
    if not await require_admin(m): return
    sent = 0
    async for x in db.requests.find({"status":"pending"}).sort("created_at", -1).limit(30):
        await m.answer(
            f"⏳ <b>PENDING REQUEST</b>\n\n<code>{x['request_id']}</code>\n"
            f"Type: {x.get('kind')}\nUser: <code>{x.get('user_id')}</code>\nDetails: {safe_text(x.get('data'))}",
            reply_markup=admin_kb(x["request_id"], "request")
        ); sent += 1
    async for x in db.payments.find({"status":"pending"}).sort("created_at", -1).limit(30):
        await m.answer(
            f"💳 <b>PENDING PAYMENT</b>\n\n<code>{x['payment_id']}</code>\nUser: <code>{x['user_id']}</code>\n"
            f"Order: <code>{x['order_id']}</code>\nAmount: ${money(x['amount']):.2f}\nMethod: {x['method']}\nReference: {safe_text(x.get('reference'))}",
            reply_markup=admin_kb(x["payment_id"], "payment")
        ); sent += 1
    await m.answer(f"📋 Pending items shown: {sent}")


async def approve_request(rid, admin_id):
    r = await db.requests.find_one_and_update({"request_id": rid, "status": "pending"}, {"$set": {"status":"confirmed", "decision_by":admin_id, "updated_at":now()}})
    if not r: return False, None
    kind = r.get("kind")
    if kind == "order":
        oid = r.get("data", {}).get("order_id")
        if oid: await db.orders.update_one({"order_id": oid}, {"$set": {"status":"processing", "updated_at":now()}})
    if kind == "refund":
        pass
    await audit(admin_id, "request_confirmed", rid, {"kind":kind})
    return True, r


async def reject_request(rid, admin_id, note=""):
    r = await db.requests.find_one_and_update({"request_id": rid, "status": "pending"}, {"$set": {"status":"rejected", "decision_by":admin_id, "decision_note":note, "updated_at":now()}})
    if not r: return False, None
    if r.get("kind") == "order":
        oid = r.get("data", {}).get("order_id")
        if oid: await db.orders.update_one({"order_id":oid}, {"$set":{"status":"rejected", "updated_at":now()}})
    await audit(admin_id, "request_rejected", rid, {"note":note})
    return True, r


async def approve_payment(pid, admin_id):
    p = await db.payments.find_one_and_update({"payment_id":pid, "status":"pending"}, {"$set":{"status":"confirmed", "decision_by":admin_id, "updated_at":now()}})
    if not p: return False, None
    amount = money(p.get("amount"))
    await db.users.update_one({"telegram_id":p["user_id"]}, {"$inc":{"wallet.pending":-amount}})
    await wallet_credit(p["user_id"], amount, f"Payment {pid}", pid)
    await db.orders.update_one({"order_id":p["order_id"]}, {"$set":{"payment_status":"paid", "status":"processing", "updated_at":now()}})
    await audit(admin_id, "payment_confirmed", pid, {"amount":amount})
    return True, p


async def reject_payment(pid, admin_id, note=""):
    p = await db.payments.find_one_and_update({"payment_id":pid, "status":"pending"}, {"$set":{"status":"rejected", "decision_by":admin_id, "decision_note":note, "updated_at":now()}})
    if not p: return False, None
    amount = money(p.get("amount"))
    await db.users.update_one({"telegram_id":p["user_id"]}, {"$inc":{"wallet.pending":-amount}})
    await audit(admin_id, "payment_rejected", pid, {"note":note})
    return True, p


@admin_router.message(Command("confirm"))
async def confirm_cmd(m: Message):
    if not await require_admin(m): return
    p=(m.text or "").split(maxsplit=2)
    if len(p)<2:return await m.answer("/confirm REQ-ID [note]")
    ok,r=await approve_request(p[1],m.from_user.id)
    await m.answer("✅ CONFIRMED" if ok else "❌ Not found or already processed.")
    if ok:
        try: await bot.send_message(r["user_id"], f"✅ Your request <code>{p[1]}</code> has been confirmed.")
        except Exception: pass


@admin_router.message(Command("reject"))
async def reject_cmd(m: Message):
    if not await require_admin(m): return
    p=(m.text or "").split(maxsplit=2)
    if len(p)<2:return await m.answer("/reject REQ-ID [note]")
    ok,r=await reject_request(p[1],m.from_user.id,p[2] if len(p)>2 else "")
    await m.answer("❌ REJECTED" if ok else "Not found or already processed.")
    if ok:
        try: await bot.send_message(r["user_id"], f"❌ Your request <code>{p[1]}</code> was rejected.\n{safe_text(p[2] if len(p)>2 else '', '')}")
        except Exception: pass


@admin_router.message(Command("payconfirm"))
async def payconfirm_cmd(m: Message):
    if not await require_admin(m, "payments"): return
    p=(m.text or "").split()
    if len(p)<2:return await m.answer("/payconfirm PAY-ID")
    ok,row=await approve_payment(p[1],m.from_user.id)
    await m.answer("✅ PAYMENT CONFIRMED" if ok else "❌ Not found or already processed.")
    if ok:
        try: await bot.send_message(row["user_id"], f"✅ Payment <code>{p[1]}</code> confirmed. ${money(row['amount']):.2f} added to your wallet.")
        except Exception: pass


@admin_router.message(Command("payreject"))
async def payreject_cmd(m: Message):
    if not await require_admin(m, "payments"): return
    p=(m.text or "").split(maxsplit=2)
    if len(p)<2:return await m.answer("/payreject PAY-ID [note]")
    ok,row=await reject_payment(p[1],m.from_user.id,p[2] if len(p)>2 else "")
    await m.answer("❌ PAYMENT REJECTED" if ok else "Not found or already processed.")
    if ok:
        try: await bot.send_message(row["user_id"], f"❌ Payment <code>{p[1]}</code> was rejected. {safe_text(p[2] if len(p)>2 else '', '')}")
        except Exception: pass


@admin_router.message(Command("stats"))
async def stats_cmd(m: Message):
    if not await require_admin(m, "analytics"): return
    labels=[("Users","users"),("Orders","orders"),("Requests","requests"),("Payments","payments"),("Numbers","numbers"),("Tickets","support"),("Staff","staff")]
    out=[f"{a}: {await db[b].count_documents({})}" for a,b in labels]
    out.append(f"Pending requests: {await db.requests.count_documents({'status':'pending'})}")
    out.append(f"Pending payments: {await db.payments.count_documents({'status':'pending'})}")
    await m.answer("📊 <b>DASHBOARD</b>\n\n"+"\n".join(out))


@admin_router.message(Command("addnumber"))
async def addnumber_cmd(m: Message):
    if not await require_admin(m, "numbers"): return
    p=(m.text or "").split(maxsplit=3)
    if len(p)<4:return await m.answer("/addnumber NUMBER PRICE CATEGORY")
    number=p[1]; price=money(p[2]); category=p[3].lower()
    await db.numbers.update_one({"number":number},{"$set":{"number":number,"price":price,"category":category,"status":"available","updated_at":now()},"$setOnInsert":{"created_at":now()}},upsert=True)
    await audit(m.from_user.id,"number_upsert",number,{"price":price,"category":category})
    await m.answer(f"✅ Number saved: {number} | ${price:.2f} | {category}")


@admin_router.message(Command("addvip"))
async def addvip_cmd(m: Message):
    if not await require_admin(m,"numbers"): return
    p=(m.text or "").split()
    if len(p)<3:return await m.answer("/addvip NUMBER PRICE")
    await db.numbers.update_one({"number":p[1]},{"$set":{"number":p[1],"price":money(p[2]),"category":"vip","status":"available","updated_at":now()},"$setOnInsert":{"created_at":now()}},upsert=True)
    await audit(m.from_user.id,"vip_upsert",p[1],{"price":money(p[2])})
    await m.answer("✅ VIP number added.")


@admin_router.message(Command("addoffer"))
async def addoffer_cmd(m: Message):
    if not await require_admin(m,"offers"): return
    p=(m.text or "").split(maxsplit=2)
    if len(p)<3:return await m.answer("/addoffer TITLE TEXT")
    oid=uid("OFF")
    await db.offers.insert_one({"offer_id":oid,"title":p[1],"text":p[2],"enabled":True,"created_at":now()})
    await audit(m.from_user.id,"offer_created",oid,{})
    await m.answer(f"✅ Offer {oid} created.")


@admin_router.message(Command("addpromo"))
async def addpromo_cmd(m: Message):
    if not await require_admin(m,"promos"): return
    p=(m.text or "").split()
    if len(p)<3:return await m.answer("/addpromo CODE DISCOUNT")
    code=p[1].upper(); discount=money(p[2])
    await db.promos.update_one({"code":code},{"$set":{"code":code,"discount":discount,"enabled":True,"updated_at":now()},"$setOnInsert":{"created_at":now(),"uses":0}},upsert=True)
    await audit(m.from_user.id,"promo_upsert",code,{"discount":discount})
    await m.answer(f"✅ Promo {code} saved with ${discount:.2f} discount.")


@admin_router.message(Command("addstaff"))
async def addstaff_cmd(m: Message):
    if int(m.from_user.id)!=MAIN_ADMIN:
        return
    p=(m.text or "").split(maxsplit=2)
    if len(p)<3:return await m.answer("/addstaff TELEGRAM_ID permission1,permission2")
    try: sid=int(p[1])
    except ValueError:return await m.answer("Invalid Telegram ID")
    perms={x.strip() for x in p[2].split(",") if x.strip()}
    perms &= PERMISSION_NAMES
    await db.staff.update_one({"telegram_id":sid},{"$set":{"telegram_id":sid,"permissions":sorted(perms),"active":True,"updated_at":now()},"$setOnInsert":{"created_at":now()}},upsert=True)
    await audit(m.from_user.id,"staff_upsert",str(sid),{"permissions":sorted(perms)})
    await m.answer(f"✅ Staff {sid} saved. Permissions: {', '.join(sorted(perms)) or 'none'}")


@admin_router.message(Command("set"))
async def set_cmd(m: Message):
    if not await require_admin(m,"settings"): return
    p=(m.text or "").split(maxsplit=2)
    if len(p)<3:return await m.answer("/set KEY VALUE")
    key,value=p[1],p[2]
    # Keep simple values typed instead of storing every value as a string.
    if value.lower() in {"true","false"}: parsed=value.lower()=="true"
    else:
        try: parsed=float(value) if "." in value else int(value)
        except ValueError: parsed=value
    await set_setting(key,parsed); await audit(m.from_user.id,"setting_changed",key,{"value":parsed})
    await m.answer(f"✅ {key} = {parsed}")


@admin_router.message(Command("broadcast"))
async def broadcast_cmd(m: Message):
    if not await require_admin(m,"broadcast"): return
    text=(m.text or "").partition(" ")[2].strip()
    if not text:return await m.answer("/broadcast MESSAGE")
    count=0
    async for u in db.users.find({"status":{"$ne":"banned"}}, {"telegram_id":1}):
        try:
            await bot.send_message(int(u["telegram_id"]), text)
            count+=1
        except Exception:
            pass
    await db.notifications.insert_one({"type":"broadcast","text":text,"count":count,"created_at":now()})
    await audit(m.from_user.id,"broadcast",None,{"count":count})
    await m.answer(f"📢 Broadcast sent to {count} users.")


@admin_router.message(Command("user"))
async def user_cmd(m: Message):
    if not await require_admin(m,"customers"): return
    p=(m.text or "").split()
    if len(p)<2:return await m.answer("/user TELEGRAM_ID")
    try: target=int(p[1])
    except ValueError:return await m.answer("Invalid ID")
    u=await get_user(target)
    if not u:return await m.answer("User not found.")
    w=u.get("wallet",{})
    await m.answer(f"👤 <b>Customer</b>\nID: <code>{target}</code>\nUsername: @{safe_text(u.get('username'),'none')}\nStatus: {u.get('status')}\nAvailable: ${money(w.get('available')):.2f}\nPending: ${money(w.get('pending')):.2f}\nReferrals: {u.get('referrals',0)}")


@admin_router.message(Command("ban"))
async def ban_cmd(m: Message):
    if not await require_admin(m,"security"): return
    p=(m.text or "").split()
    if len(p)<2:return await m.answer("/ban TELEGRAM_ID")
    try: target=int(p[1])
    except ValueError:return await m.answer("Invalid ID")
    if target==MAIN_ADMIN:return await m.answer("❌ Main admin cannot be banned.")
    await db.users.update_one({"telegram_id":target},{"$set":{"status":"banned"}})
    await audit(m.from_user.id,"user_banned",str(target))
    await m.answer("🚫 User banned.")


# ---------------- Admin callbacks ----------------
@admin_router.callback_query(F.data.startswith("approve:"))
async def approve_callback(c: CallbackQuery):
    if not await has_permission(c.from_user.id,"admin"):
        return await c.answer("Not authorized", show_alert=True)
    _, kind, ident = c.data.split(":",2)
    if kind=="request": ok,row=await approve_request(ident,c.from_user.id)
    elif kind=="payment": ok,row=await approve_payment(ident,c.from_user.id)
    else: ok,row=False,None
    if not ok:return await c.answer("Already processed / not found", show_alert=True)
    await c.answer("Confirmed")
    try: await c.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    if row:
        try:
            if kind=="payment":
                await bot.send_message(row["user_id"],f"✅ Payment <code>{ident}</code> confirmed.")
            else: await bot.send_message(row["user_id"],f"✅ Request <code>{ident}</code> confirmed.")
        except Exception: pass


@admin_router.callback_query(F.data.startswith("reject:"))
async def reject_callback(c: CallbackQuery):
    if not await has_permission(c.from_user.id,"admin"):
        return await c.answer("Not authorized", show_alert=True)
    _, kind, ident = c.data.split(":",2)
    if kind=="request": ok,row=await reject_request(ident,c.from_user.id)
    elif kind=="payment": ok,row=await reject_payment(ident,c.from_user.id)
    else: ok,row=False,None
    if not ok:return await c.answer("Already processed / not found", show_alert=True)
    await c.answer("Rejected")
    try: await c.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    if row:
        try: await bot.send_message(row["user_id"],f"❌ {kind.title()} <code>{ident}</code> rejected by admin.")
        except Exception: pass


@admin_router.callback_query(F.data.startswith("details:"))
async def details_callback(c: CallbackQuery):
    if not await has_permission(c.from_user.id,"admin"):
        return await c.answer("Not authorized", show_alert=True)
    _, kind, ident=c.data.split(":",2)
    if kind=="payment": row=await db.payments.find_one({"payment_id":ident})
    elif kind=="support": row=await db.support.find_one({"ticket_id":ident})
    else: row=await db.requests.find_one({"request_id":ident})
    if not row:return await c.answer("Not found",show_alert=True)
    await c.message.answer(f"📄 <b>DETAILS</b>\n\n<code>{row}</code>")
    await c.answer()


@admin_router.callback_query(F.data.startswith("contact:"))
async def contact_callback(c: CallbackQuery):
    if not await has_permission(c.from_user.id,"support"):
        return await c.answer("Not authorized", show_alert=True)
    _, kind, ident=c.data.split(":",2)
    row = await (db.payments.find_one({"payment_id":ident}) if kind=="payment" else db.requests.find_one({"request_id":ident}) if kind=="request" else db.support.find_one({"ticket_id":ident}))
    if not row:return await c.answer("Not found",show_alert=True)
    await c.message.answer(f"💬 Contact user: <code>{row.get('user_id')}</code>\nUse Telegram to contact them directly.")
    await c.answer()


@admin_router.callback_query(F.data.startswith("customer:"))
async def customer_callback(c: CallbackQuery):
    if not await has_permission(c.from_user.id,"customers"):
        return await c.answer("Not authorized", show_alert=True)
    target=int(c.data.split(":",1)[1]); u=await get_user(target)
    if not u:return await c.answer("User not found",show_alert=True)
    await c.message.answer(f"👤 ID: <code>{target}</code>\nUsername: @{safe_text(u.get('username'),'none')}\nStatus: {u.get('status')}")
    await c.answer()


@admin_router.callback_query(F.data.startswith("ban:"))
async def ban_callback(c: CallbackQuery):
    if not await has_permission(c.from_user.id,"security"):
        return await c.answer("Not authorized", show_alert=True)
    target=int(c.data.split(":",1)[1])
    if target==MAIN_ADMIN:return await c.answer("Main admin protected",show_alert=True)
    await db.users.update_one({"telegram_id":target},{"$set":{"status":"banned"}})
    await audit(c.from_user.id,"user_banned",str(target))
    await c.answer("Banned")


# ---------------- Banned-user guard ----------------
@router.message()
async def fallback(m: Message):
    if m.from_user:
        u=await get_user(m.from_user.id)
        if u and u.get("status")=="banned":
            return await m.answer("🚫 Your account is blocked.")
    await m.answer("❓ Unknown command. Use /help.")


# ---------------- Render health server ----------------
async def health(request):
    return web.json_response({"status":"ok","service":"Telesombot"})


async def start_health_server():
    app=web.Application()
    app.router.add_get("/",health)
    app.router.add_get("/health",health)
    runner=web.AppRunner(app)
    await runner.setup()
    site=web.TCPSite(runner,"0.0.0.0",PORT)
    await site.start()
    log.info("Health server listening on 0.0.0.0:%s",PORT)
    return runner


async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=False)
    runner=await start_health_server()
    log.info("Telesombot starting. Main admin: %s", MAIN_ADMIN)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await runner.cleanup()
        await bot.session.close()
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
