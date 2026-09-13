# Telesombot

Telegram-only Telesom-style service management foundation.

## ENV
BOT_TOKEN=Telegram bot token
MONGO_URI=MongoDB connection string
ADMIN_ID=main admin Telegram ID

## Run
pip install -r requirements.txt
python bot.py

## Deploy
Railway/Render: create a worker/background service and add the three ENV variables.

## Important
This package contains the Telegram UX, multilingual command framework, MongoDB persistence, request/approval engine, 30 admin-control categories, audit logging, and starter service routing.

Actual Telesom/ZAAD/eSIM/SMS/number provisioning requires authorized official APIs or an approved operator integration. The bot does not pretend that an order is provisioned merely because an admin confirms it.

## Languages
English: /lang en
Somali: /lang so
Arabic: /lang ar

## Admin
/admin
/pending
/confirm REQ-000001
/reject REQ-000001
