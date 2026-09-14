# TELESOMBOT COMPANY SYSTEM

Telegram-only telecom company management system.

## Required environment
- BOT_TOKEN
- MONGO_URI
- ADMIN_ID

## Render
Build: `pip install -r requirements.txt`
Start: `python bot.py`
Service: Web Service

## Customer UI
Customers use buttons for Numbers, VIP Numbers, Virtual Numbers, eSIM, Physical SIM, Data, Voice, SMS, Recharge, Wallet, Orders, Payments, Offers, Referral, Support, Profile and Language.

## Admin UI
Main admin opens the button-based `🛠️ ADMIN PANEL TELESOM` and gets 30 control panels. Sensitive orders/payments/requests use Confirm/Reject workflows and are logged.

## Important
This system manages catalog, inventory, orders, approvals and manual fulfillment. Real operator-side provisioning (eSIM activation, SIM activation, live balance/recharge, etc.) requires an authorized operator/API integration. The bot does not falsely claim that manual approval is automatic telecom provisioning.
