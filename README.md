# Telesombot — Button Telecom System

## ENV
- BOT_TOKEN
- MONGO_URI
- ADMIN_ID
- DB_NAME (optional, default telesombot)
- PORT (optional, Render sets this automatically)

## Run
python bot.py

## Important
The bot refreshes public Telesom catalogue/number pages every 120 seconds. It only imports publicly visible data and never invents live inventory.

Local payment opens the phone dialer with the amount pre-filled. Automatic payment verification/provisioning still requires an authorized operator/payment API; Telegram cannot bypass a user's PIN or confirm a wallet transaction by itself.
