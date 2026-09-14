import os
from dotenv import load_dotenv
load_dotenv()
BOT_TOKEN=os.getenv('BOT_TOKEN','').strip()
MONGO_URI=os.getenv('MONGO_URI','').strip()
ADMIN_ID=int(os.getenv('ADMIN_ID','0') or 0)
DB_NAME=os.getenv('DB_NAME','telesombot')
if not BOT_TOKEN or not MONGO_URI or not ADMIN_ID:
    raise RuntimeError('Required ENV: BOT_TOKEN, MONGO_URI, ADMIN_ID')
