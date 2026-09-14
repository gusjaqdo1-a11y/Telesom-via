import os, sys, time, sqlite3, shutil
import telebot
from telebot import types
from config import BOT_TOKEN, ADMIN_IDS, BOT_NAME, DB_PATH, SUPPORT_USERNAME
from db import *
from i18n import t, LANGS, TEXT
from services.payments import instructions
from utils.admin import is_admin, log

if not BOT_TOKEN:
    raise SystemExit('BOT_TOKEN is missing. Copy .env.example to .env and set BOT_TOKEN.')

init_db(); bot=telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

ADMIN_COMMANDS = [
'/admin','/stats','/users','/user','/block','/unblock','/addadmin','/deladmin','/addcard','/addvip',
'/delproduct','/products_admin','/orders_admin','/confirm','/reject','/broadcast','/setprice','/settings',
'/audit','/tickets','/reply','/notify','/maintenance','/export','/backup','/health','/payments','/inventory',
'/provider','/helpadmin'
]

def lang(uid):
    u=get_user(uid); return u['language'] if u and u['language'] in LANGS else 'so'

def notify_admins(text):
    for aid in ADMIN_IDS:
        try: bot.send_message(aid,text)
        except Exception: pass

def user_info(u):
    return (f'👤 NEW USER\nName: {u.first_name or "-"} {u.last_name or ""}\nUsername: @{u.username}' if u.username else f'👤 NEW USER\nName: {u.first_name or "-"} {u.last_name or ""}\nUsername: -') + f'\nTelegram ID: <code>{u.id}</code>\nLanguage: {lang(u.id)}'

def send_products(chat_id, kind=None):
    ps=list_products(kind)
    if not ps:
        bot.send_message(chat_id,t('products_empty',lang(chat_id))); return
    lines=['🛍 <b>Available Products</b>']
    for p in ps:
        lines.append(f"#{p['id']} • {p['title']} • {p['price']:.2f} {p['currency']} • {p['kind']}\nNumber/Card: <code>{p['number']}</code>")
    lines.append('\nBuy: <code>/buy PRODUCT_ID METHOD</code>\nMethods: telesom, golis, bnb, usdt-bep20')
    bot.send_message(chat_id,'\n'.join(lines))

@bot.message_handler(commands=['start'])
def start(m):
    new=upsert_user(m.from_user)
    if new: notify_admins(user_info(m.from_user))
    u=get_user(m.from_user.id)
    if u['blocked']:
        bot.reply_to(m,t('blocked',lang(m.from_user.id))); return
    bot.reply_to(m,t('welcome',lang(m.from_user.id)))

@bot.message_handler(commands=['help'])
def help_cmd(m):
    upsert_user(m.from_user); bot.reply_to(m,t('help',lang(m.from_user.id)))

@bot.message_handler(commands=['lang','language'])
def language(m):
    upsert_user(m.from_user)
    if len(m.text.split())==1:
        bot.reply_to(m, t('lang',lang(m.from_user.id))+'\nUse: /lang so | /lang en | /lang ar'); return
    code=m.text.split()[1].lower();
    if code not in LANGS: bot.reply_to(m,'Use: so, en, ar'); return
    set_lang(m.from_user.id,code); bot.reply_to(m,t('welcome',code))

@bot.message_handler(commands=['products'])
def products(m): upsert_user(m.from_user); send_products(m.chat.id)
@bot.message_handler(commands=['cards'])
def cards(m): upsert_user(m.from_user); send_products(m.chat.id,'card')
@bot.message_handler(commands=['vip'])
def vip(m): upsert_user(m.from_user); send_products(m.chat.id,'vip')

@bot.message_handler(commands=['buy'])
def buy(m):
    upsert_user(m.from_user); a=m.text.split()
    if len(a)<3: bot.reply_to(m,'Usage: /buy PRODUCT_ID METHOD\nMethods: telesom, golis, bnb, usdt-bep20'); return
    try: pid=int(a[1])
    except: bot.reply_to(m,'Invalid product ID'); return
    p=get_product(pid)
    if not p or p['status']!='available': bot.reply_to(m,'Product unavailable'); return
    method=a[2].lower(); oid=create_order(m.from_user.id,pid,p['price'],p['currency'],method)
    bot.reply_to(m,t('order_created',lang(m.from_user.id),id=oid)+'\n\n'+instructions(method,p['price']))
    notify_admins(f'🧾 NEW ORDER #{oid}\nUser: {m.from_user.id} @{m.from_user.username or "-"}\nProduct: {p["title"]}\nAmount: {p["price"]} {p["currency"]}\nMethod: {method}\nConfirm: /confirm {oid}')

@bot.message_handler(commands=['pay'])
def pay(m):
    upsert_user(m.from_user); a=m.text.split()
    if len(a)!=2: bot.reply_to(m,'Usage: /pay ORDER_ID'); return
    try:o=get_order(int(a[1]))
    except:o=None
    if not o or o['user_id']!=m.from_user.id: bot.reply_to(m,t('unknown_order',lang(m.from_user.id))); return
    bot.reply_to(m,instructions(o['method'],o['amount']))

@bot.message_handler(commands=['confirm'])
def confirm(m):
    upsert_user(m.from_user); a=m.text.split(maxsplit=2)
    if is_admin(m.from_user.id) and len(a)==2 and a[1].isdigit():
        oid=int(a[1]); o=get_order(oid)
        if not o: bot.reply_to(m,'Not found'); return
        ok=confirm_order(oid,m.from_user.id)
        if ok:
            bot.reply_to(m,f'✅ Order #{oid} confirmed.')
            try: bot.send_message(o['user_id'],f'✅ Order #{oid} confirmed. Product: {o["title"]}\nNumber/Card: <code>{o["number"]}</code>')
            except Exception: pass
        else: bot.reply_to(m,'Already processed')
        log(m.from_user.id,'confirm',str(oid)); return
    if len(a)<3:
        bot.reply_to(m,'Usage: /confirm ORDER_ID TRANSACTION_REFERENCE'); return
    try:o=get_order(int(a[1]))
    except:o=None
    if not o or o['user_id']!=m.from_user.id: bot.reply_to(m,'Order not found'); return
    c=conn(); c.execute('UPDATE orders SET reference=? WHERE id=? AND status=\"pending\"',(a[2],o['id'])); c.commit(); c.close()
    bot.reply_to(m,'✅ Payment reference received. Your order is waiting for admin confirmation.')
    notify_admins(f'🔔 PAYMENT PROOF\nOrder: #{o["id"]}\nUser: {m.from_user.id} @{m.from_user.username or "-"}\nMethod: {o["method"]}\nReference: <code>{a[2]}</code>\nApprove: /confirm {o["id"]}\nReject: /reject {o["id"]}')

@bot.message_handler(commands=['orders'])
def orders(m):
    upsert_user(m.from_user); c=conn(); rs=c.execute('SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 20',(m.from_user.id,)).fetchall(); c.close()
    if not rs: bot.reply_to(m,'No orders.'); return
    bot.reply_to(m,'\n'.join([f"#{r['id']} • {r['status']} • {r['amount']} {r['currency']} • {r['method']}" for r in rs]))

@bot.message_handler(commands=['status'])
def status(m):
    a=m.text.split();
    if len(a)!=2: bot.reply_to(m,'Usage: /status ORDER_ID'); return
    try:o=get_order(int(a[1]))
    except:o=None
    if not o or o['user_id']!=m.from_user.id: bot.reply_to(m,'Order not found'); return
    bot.reply_to(m,f'Order #{o["id"]}\nStatus: {o["status"]}\nProduct: {o["title"]}')

@bot.message_handler(commands=['support'])
def support(m):
    upsert_user(m.from_user); msg=m.text.partition(' ')[2].strip()
    if not msg: bot.reply_to(m,'Usage: /support your message'); return
    c=conn(); cur=c.execute('INSERT INTO tickets(user_id,subject,message,created_at) VALUES(?,?,?,?)',(m.from_user.id,'Customer support',msg,now())); c.commit(); tid=cur.lastrowid; c.close()
    bot.reply_to(m,f'🎫 Ticket #{tid} created.'); notify_admins(f'🎫 SUPPORT #{tid}\nUser: {m.from_user.id}\n{msg}\nReply: /reply {tid} your message')

@bot.message_handler(commands=['profile'])
def profile(m):
    u=get_user(m.from_user.id) or m.from_user
    bot.reply_to(m,f'👤 {u["first_name"]} {u["last_name"] or ""}\nUsername: @{u["username"] or "-"}\nTelegram ID: <code>{u["id"]}</code>\nLanguage: {u["language"]}')

# -------- ADMIN / 30+ CONTROL PANELS --------
def admin_only(m):
    if not is_admin(m.from_user.id): bot.reply_to(m,t('admin_only',lang(m.from_user.id))); return False
    return True

@bot.message_handler(commands=['admin','helpadmin'])
def admin(m):
    if not admin_only(m): return
    bot.reply_to(m,'🛡 <b>TELESOMBOT ADMIN CENTER</b>\n\n'+'\n'.join(ADMIN_COMMANDS)+'\n\nExamples:\n/addcard Visa 4111111111111111 5 USD\n/addvip GoldVIP 0634999999 25 USD\n/broadcast Hello\n/confirm 12\n/reject 12')

@bot.message_handler(commands=['stats'])
def stats_cmd(m):
    if not admin_only(m): return
    s=stats(); bot.reply_to(m,'📊 '+ ' | '.join(f'{k}: {v}' for k,v in s.items()))

@bot.message_handler(commands=['users'])
def users(m):
    if not admin_only(m): return
    us=all_users(); bot.reply_to(m,'\n'.join([f"{u['id']} | @{u['username'] or '-'} | {u['first_name']} | {u['language']} | blocked={u['blocked']}" for u in us[:100]]) or 'No users')

@bot.message_handler(commands=['user'])
def user(m):
    if not admin_only(m): return
    a=m.text.split();
    if len(a)!=2: bot.reply_to(m,'/user TELEGRAM_ID'); return
    u=get_user(int(a[1])) if a[1].isdigit() else None
    bot.reply_to(m,dict(u) and '\n'.join(f'{k}: {u[k]}' for k in u.keys()) or 'Not found')

@bot.message_handler(commands=['block','unblock'])
def block(m):
    if not admin_only(m): return
    a=m.text.split();
    if len(a)!=2 or not a[1].isdigit(): bot.reply_to(m,'Usage: /block ID or /unblock ID'); return
    c=conn(); c.execute('UPDATE users SET blocked=? WHERE id=?',(1 if m.text.startswith('/block') else 0,int(a[1]))); c.commit(); c.close(); log(m.from_user.id,m.text.split()[0],a[1]); bot.reply_to(m,'Done')

@bot.message_handler(commands=['addadmin','deladmin'])
def admins(m):
    if not admin_only(m): return
    a=m.text.split();
    if len(a)!=2 or not a[1].isdigit(): bot.reply_to(m,'Usage: /addadmin ID or /deladmin ID'); return
    uid=int(a[1]);
    if uid in ADMIN_IDS and m.text.startswith('/deladmin'): bot.reply_to(m,'Main ADMIN_IDS cannot be removed from .env'); return
    c=conn();
    if m.text.startswith('/addadmin'): c.execute('INSERT OR REPLACE INTO admins(user_id,role,added_at) VALUES(?,?,?)',(uid,'admin',now()))
    else: c.execute('DELETE FROM admins WHERE user_id=?',(uid,))
    c.commit(); c.close(); bot.reply_to(m,'Done')

@bot.message_handler(commands=['addcard','addvip'])
def add_product_cmd(m):
    if not admin_only(m): return
    a=m.text.split()
    if len(a)<5: bot.reply_to(m,'/addcard TITLE NUMBER PRICE CURRENCY\n/addvip TITLE NUMBER PRICE CURRENCY'); return
    kind='card' if m.text.startswith('/addcard') else 'vip'
    try: price=float(a[-2])
    except: bot.reply_to(m,'Invalid price'); return
    title=' '.join(a[1:-2]); number=a[-3]; currency=a[-1]
    pid=add_product(kind,title,number,price,currency); log(m.from_user.id,'add_product',str(pid)); bot.reply_to(m,f'Added #{pid}')

@bot.message_handler(commands=['delproduct'])
def delproduct(m):
    if not admin_only(m): return
    a=m.text.split();
    if len(a)!=2 or not a[1].isdigit(): bot.reply_to(m,'/delproduct ID'); return
    c=conn(); c.execute('UPDATE products SET status="deleted" WHERE id=?',(int(a[1]),)); c.commit(); c.close(); bot.reply_to(m,'Deleted')

@bot.message_handler(commands=['products_admin','inventory'])
def products_admin(m):
    if not admin_only(m): return
    ps=list_products(None,False); bot.reply_to(m,'\n'.join([f"#{p['id']} {p['kind']} {p['title']} {p['number']} {p['price']} {p['currency']} [{p['status']}]" for p in ps]) or 'Empty')

@bot.message_handler(commands=['orders_admin','payments'])
def orders_admin(m):
    if not admin_only(m): return
    rs=pending_orders();
    if not rs: bot.reply_to(m,'No pending orders'); return
    bot.reply_to(m,'\n\n'.join([f"#{r['id']} | {r['title']} | {r['amount']} {r['currency']} | {r['method']} | @{r['username'] or '-'}\nRef: {r['reference'] or '-'}\n/confirm {r['id']} | /reject {r['id']}" for r in rs]))

@bot.message_handler(commands=['confirm','reject'])
def admin_order(m):
    if not admin_only(m): return
    a=m.text.split();
    if len(a)!=2 or not a[1].isdigit(): bot.reply_to(m,'/confirm ORDER_ID or /reject ORDER_ID'); return
    oid=int(a[1]); o=get_order(oid)
    if not o: bot.reply_to(m,'Not found'); return
    if m.text.startswith('/confirm'):
        ok=confirm_order(oid,m.from_user.id); msg='Confirmed' if ok else 'Already processed';
        if ok:
            try: bot.send_message(o['user_id'],f'✅ Order #{oid} confirmed. Product: {o["title"]}\nNumber/Card: <code>{o["number"]}</code>')
            except: pass
    else: reject_order(oid,m.from_user.id); msg='Rejected';
    log(m.from_user.id,m.text.split()[0],str(oid)); bot.reply_to(m,msg)

@bot.message_handler(commands=['broadcast'])
def broadcast(m):
    if not admin_only(m): return
    text=m.text.partition(' ')[2].strip();
    if not text: bot.reply_to(m,'/broadcast MESSAGE'); return
    count=0
    for u in all_users():
        try: bot.send_message(u['id'],text); count+=1
        except: pass
    bot.reply_to(m,f'Broadcast sent: {count}')

@bot.message_handler(commands=['setprice'])
def setprice(m):
    if not admin_only(m): return
    a=m.text.split();
    if len(a)!=3: bot.reply_to(m,'/setprice PRODUCT_ID PRICE'); return
    c=conn(); c.execute('UPDATE products SET price=? WHERE id=?',(float(a[2]),int(a[1]))); c.commit(); c.close(); bot.reply_to(m,'Updated')

@bot.message_handler(commands=['setlangdefault'])
def setlangdefault(m):
    if not admin_only(m): return
    a=m.text.split()
    if len(a)!=2 or a[1] not in LANGS: bot.reply_to(m,'/setlangdefault so|en|ar'); return
    c=conn(); c.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',('default_language',a[1])); c.commit(); c.close(); bot.reply_to(m,'Default language set to '+a[1])

@bot.message_handler(commands=['settings'])
def settings(m):
    if not admin_only(m): return
    c=conn(); rs=c.execute('SELECT key,value FROM settings ORDER BY key').fetchall(); c.close(); bot.reply_to(m,'\n'.join(f'{r[0]}={r[1]}' for r in rs) or 'No custom settings')

@bot.message_handler(commands=['audit'])
def audit_cmd(m):
    if not admin_only(m): return
    c=conn(); rs=c.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 50').fetchall(); c.close(); bot.reply_to(m,'\n'.join(f"#{r['id']} admin={r['admin_id']} {r['action']} {r['details']}" for r in rs) or 'No audit')

@bot.message_handler(commands=['tickets'])
def tickets(m):
    if not admin_only(m): return
    c=conn(); rs=c.execute('SELECT * FROM tickets WHERE status="open" ORDER BY id DESC').fetchall(); c.close(); bot.reply_to(m,'\n'.join(f"#{r['id']} user={r['user_id']} {r['message']}\n/reply {r['id']} ..." for r in rs) or 'No tickets')

@bot.message_handler(commands=['reply'])
def reply_ticket(m):
    if not admin_only(m): return
    a=m.text.split(maxsplit=2)
    if len(a)<3: bot.reply_to(m,'/reply TICKET_ID MESSAGE'); return
    c=conn(); r=c.execute('SELECT user_id FROM tickets WHERE id=?',(int(a[1]),)).fetchone(); c.execute('UPDATE tickets SET status="closed" WHERE id=?',(int(a[1]),)); c.commit(); c.close()
    if r:
        bot.send_message(r['user_id'],'💬 Support:\n'+a[2]); bot.reply_to(m,'Sent')
    else: bot.reply_to(m,'Ticket not found')

@bot.message_handler(commands=['notify'])
def notify(m):
    if not admin_only(m): return
    a=m.text.split(maxsplit=2)
    if len(a)<3: bot.reply_to(m,'/notify USER_ID MESSAGE'); return
    try: bot.send_message(int(a[1]),a[2]); bot.reply_to(m,'Sent')
    except Exception as e: bot.reply_to(m,str(e))

@bot.message_handler(commands=['maintenance'])
def maintenance(m):
    if not admin_only(m): return
    a=m.text.split();
    if len(a)!=2 or a[1] not in ('on','off'): bot.reply_to(m,'/maintenance on|off'); return
    c=conn(); c.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',('maintenance',a[1])); c.commit(); c.close(); bot.reply_to(m,'Maintenance '+a[1])

@bot.message_handler(commands=['export'])
def export(m):
    if not admin_only(m): return
    path='data/export.sql';
    with open(path,'w',encoding='utf8') as f:
        for line in conn().iterdump(): f.write(line+'\n')
    with open(path,'rb') as f: bot.send_document(m.chat.id,f,caption='Database export')

@bot.message_handler(commands=['backup'])
def backup(m):
    if not admin_only(m): return
    dst=f'data/backup_{int(time.time())}.sqlite3'; shutil.copy2(DB_PATH,dst)
    with open(dst,'rb') as f: bot.send_document(m.chat.id,f,caption='SQLite backup')

@bot.message_handler(commands=['health'])
def health(m):
    if not admin_only(m): return
    bot.reply_to(m,f'✅ Bot online\nDB: {DB_PATH}\nAdmins: {len(ADMIN_IDS)}\nTime: {now()}')

@bot.message_handler(commands=['provider'])
def provider(m):
    if not admin_only(m): return
    bot.reply_to(m,'Card Provider: LOCAL INVENTORY MODE\nTo issue real virtual cards automatically, connect a licensed card issuer API in services/card_provider.py.\nDo not put card-issuer secrets in source code.')

@bot.message_handler(func=lambda m: True)
def fallback(m):
    if m.text and m.text.startswith('/'):
        upsert_user(m.from_user); bot.reply_to(m,t('notfound',lang(m.from_user.id)))
    else:
        # customer bot is command-driven; no menu buttons
        bot.reply_to(m,'Use /help for commands.')

if __name__=='__main__':
    print(BOT_NAME+' running...')
    bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
