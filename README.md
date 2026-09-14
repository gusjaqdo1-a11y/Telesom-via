# Telesombot Full Telegram System

## Required ENV
BOT_TOKEN
MONGO_URI
ADMIN_ID

## 30 Admin panels
Dashboard, Customers, Numbers, VIP Numbers, Virtual Numbers, eSIM, Physical SIM, Data, Voice, SMS, Recharge, Wallets, Payments, Orders, Refunds, Offers, Promo Codes, Referrals, Memberships, Support, Broadcast, Notifications, Business, Corporate, Inventory, Analytics, Staff & Permissions, Security, Audit Logs, System Settings.

## User commands
/start /help /lang /services /numbers /vip /esim /sim /virtual /data /voice /sms /recharge /business /fiber /zaad /iot /cloud /order /pay /orders /payments /wallet /referral /support /profile /contact

## Admin commands
/admin /panel 1-30 /pending /confirm REQ-ID [note] /reject REQ-ID [note] /payconfirm PAY-ID /payreject PAY-ID [note] /stats

## Languages
English, Somali, Arabic. /lang en, /lang so, /lang ar.

## Payment destinations
Golis: *883*0907868526*$#
Telesom: *880*0907868526*$#
BNB: 0x1f12ffDc93E49eff0c78672Ab6abA62410c05a32
USDT-BEP20: 0x6AC864773259fa5175251829cb0E93ffb4cE6feC

The bot records payment requests as pending until an admin confirms them. Automatic telecom/ZAAD/eSIM provisioning requires authorized provider APIs; this package does not fabricate confirmations.

## Railway
Create a service, add the three variables, and use start command: python bot.py.
