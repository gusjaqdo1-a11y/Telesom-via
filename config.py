import os
from dotenv import load_dotenv
load_dotenv()
BOT_TOKEN=os.getenv('BOT_TOKEN','')
BOT_NAME=os.getenv('BOT_NAME','TelesomBot')
DB_PATH=os.getenv('DB_PATH','data/telesombot.sqlite3')
ADMIN_IDS={int(x.strip()) for x in os.getenv('ADMIN_IDS','').split(',') if x.strip().isdigit()}
DEFAULT_LANGUAGE=os.getenv('DEFAULT_LANGUAGE','so')
SUPPORT_USERNAME=os.getenv('SUPPORT_USERNAME','@YOUR_SUPPORT')
BSCSCAN_API_KEY=os.getenv('BSCSCAN_API_KEY','')
BNB_ADDRESS=os.getenv('BNB_ADDRESS','0x1f12ffDc93E49eff0c78672Ab6abA62410c05a32')
USDT_BEP20_ADDRESS=os.getenv('USDT_BEP20_ADDRESS','0x6AC864773259fa5175251829cb0E93ffb4cE6feC')
LOCAL_PAYMENTS={
 'golis':'*883*0907868526*{amount}#',
 'telesom':'*880*0907868526*{amount}#'
}
