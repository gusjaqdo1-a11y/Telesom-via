# Telesombot — Auto Local Payment + Telesom Website Sync

## ENV
- BOT_TOKEN
- MONGO_URI
- ADMIN_ID
- DB_NAME (optional)
- PORT (optional; Render provides this)

## Start
python bot.py

## Local payment
When a user selects Golis or Telesom, the bot does not display the USSD code. It creates a PAY NOW button with a `tel:` link containing the selected amount, e.g. `*883*0907868526*2#` or `*880*0907868526*2#`.

The phone's dialer/payment screen decides whether the USSD can be executed directly. Telegram/Android security restrictions can prevent fully automatic submission; the bot cannot bypass those restrictions.

## Telesom website sync
The bot periodically reads public Telesom pages for publicly visible products/prices and any publicly exposed SIM numbers. It does not invent inventory. Telesom's public website does not guarantee a complete live-number inventory API, so a true 100% live inventory feed would require an official Telesom API/authorized integration.
