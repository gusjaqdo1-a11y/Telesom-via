import sqlite3, os, json, secrets
from datetime import datetime, timezone
from config import DB_PATH

os.makedirs(os.path.dirname(DB_PATH) or '.', exist_ok=True)

def conn():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; return c

def now(): return datetime.now(timezone.utc).isoformat()

def init_db():
    c=conn(); c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, language TEXT DEFAULT 'so', phone TEXT, created_at TEXT, last_seen TEXT, blocked INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS admins(user_id INTEGER PRIMARY KEY, role TEXT DEFAULT 'admin', added_at TEXT);
    CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, title TEXT, number TEXT, price REAL, currency TEXT DEFAULT 'USD', status TEXT DEFAULT 'available', meta TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product_id INTEGER, amount REAL, currency TEXT, method TEXT, status TEXT DEFAULT 'pending', reference TEXT, created_at TEXT, confirmed_at TEXT, confirmed_by INTEGER);
    CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, method TEXT, amount REAL, currency TEXT, reference TEXT, status TEXT DEFAULT 'pending', created_at TEXT, reviewed_by INTEGER);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, action TEXT, details TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, subject TEXT, message TEXT, status TEXT DEFAULT 'open', created_at TEXT);
    CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message TEXT, sent INTEGER DEFAULT 0, created_at TEXT);
    '''); c.commit(); c.close()

def upsert_user(u):
    c=conn(); old=c.execute('SELECT id FROM users WHERE id=?',(u.id,)).fetchone(); t=now()
    c.execute('''INSERT INTO users(id,username,first_name,last_name,language,created_at,last_seen) VALUES(?,?,?,?,?,?,?)
                 ON CONFLICT(id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name,last_name=excluded.last_name,last_seen=excluded.last_seen''',
              (u.id,u.username or '',u.first_name or '',u.last_name or '', 'so', t,t)); c.commit(); c.close(); return old is None

def get_user(uid):
    c=conn(); r=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); c.close(); return r

def set_lang(uid, lang):
    c=conn(); c.execute('UPDATE users SET language=? WHERE id=?',(lang,uid)); c.commit(); c.close()

def add_product(kind,title,number,price,currency='USD',meta=None):
    c=conn(); cur=c.execute('INSERT INTO products(kind,title,number,price,currency,status,meta,created_at) VALUES(?,?,?,?,?,?,?,?)',(kind,title,number,price,currency,'available',json.dumps(meta or {}),now())); c.commit(); i=cur.lastrowid; c.close(); return i

def list_products(kind=None, available_only=True):
    c=conn(); q='SELECT * FROM products WHERE 1=1'; args=[]
    if kind: q+=' AND kind=?'; args.append(kind)
    if available_only: q+=" AND status='available'"
    q+=' ORDER BY id DESC'; r=c.execute(q,args).fetchall(); c.close(); return r

def get_product(pid):
    c=conn(); r=c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone(); c.close(); return r

def create_order(uid,pid,amount,currency,method,ref=''):
    c=conn(); cur=c.execute('INSERT INTO orders(user_id,product_id,amount,currency,method,reference,created_at) VALUES(?,?,?,?,?,?,?)',(uid,pid,amount,currency,method,ref,now())); c.commit(); i=cur.lastrowid; c.close(); return i

def get_order(oid):
    c=conn(); r=c.execute('SELECT o.*,p.title,p.number,p.kind,u.username,u.first_name,u.last_name FROM orders o JOIN products p ON p.id=o.product_id JOIN users u ON u.id=o.user_id WHERE o.id=?',(oid,)).fetchone(); c.close(); return r

def pending_orders():
    c=conn(); r=c.execute("SELECT o.*,p.title,p.number,u.username,u.first_name FROM orders o JOIN products p ON p.id=o.product_id JOIN users u ON u.id=o.user_id WHERE o.status='pending' ORDER BY o.id DESC").fetchall(); c.close(); return r

def confirm_order(oid,admin_id):
    c=conn(); o=c.execute('SELECT product_id FROM orders WHERE id=? AND status=\'pending\'',(oid,)).fetchone()
    if not o: c.close(); return False
    c.execute("UPDATE orders SET status='confirmed',confirmed_at=?,confirmed_by=? WHERE id=?",(now(),admin_id,oid)); c.execute("UPDATE products SET status='sold' WHERE id=?",(o['product_id'],)); c.commit(); c.close(); return True

def reject_order(oid,admin_id):
    c=conn(); c.execute("UPDATE orders SET status='rejected',confirmed_at=?,confirmed_by=? WHERE id=? AND status='pending'",(now(),admin_id,oid)); c.commit(); c.close()

def stats():
    c=conn(); out={}
    for k,q in {'users':'SELECT COUNT(*) n FROM users','available':'SELECT COUNT(*) n FROM products WHERE status="available"','sold':'SELECT COUNT(*) n FROM products WHERE status="sold"','pending':'SELECT COUNT(*) n FROM orders WHERE status="pending"','confirmed':'SELECT COUNT(*) n FROM orders WHERE status="confirmed"'}.items(): out[k]=c.execute(q).fetchone()['n']
    c.close(); return out

def audit(admin,action,details=''):
    c=conn(); c.execute('INSERT INTO audit(admin_id,action,details,created_at) VALUES(?,?,?,?)',(admin,action,details,now())); c.commit(); c.close()

def all_users():
    c=conn(); r=c.execute('SELECT * FROM users ORDER BY id DESC').fetchall(); c.close(); return r
