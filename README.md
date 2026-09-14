# Telesombot — Full Telegram Service System

## ENV
- BOT_TOKEN
- MONGO_URI
- ADMIN_ID
- DB_NAME (optional)
- PORT (optional)

## Run
`python bot.py`

## Payment
Local: ZAAD and SAHAL. The bot creates a `tel:` link with the amount filled in, e.g. SAHAL `*883*0907868526*2#` and ZAAD `*880*0907868526*2#`.
Crypto: BNB and USDT-BEP20.

The bot cannot enter wallet PINs or cryptographically verify local payments without an official payment API. Admin verification remains required after the customer confirms payment.

## Telesom sync
The bot refreshes the public Telesom catalogue and publicly discoverable SIM order pages every 120 seconds. It only imports numbers actually exposed by telesom.com and never invents inventory.

## Render
Run as a Web Service with `python bot.py`; the bot exposes `/health` on Render's PORT.
