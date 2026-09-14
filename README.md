# TelesomBot — 3-language command-driven Telegram system

A production-oriented starter for a Telesom-style digital marketplace: virtual-card inventory, VIP numbers, local payment instructions, crypto payment references, admin confirmation, customer support, broadcasts, audit log, backups, and Somali/English/Arabic language switching.

## Important integration boundary
This package does **not** pretend to be an official Telesom/Golis payment gateway or a card issuer. The supplied USSD strings are presented to customers as payment instructions. A Telegram bot running on Railway/Render cannot directly execute a phone USSD session unless you connect an official telecom API or a controlled Android/USSD gateway. Likewise, real virtual cards require a licensed card-issuer/provider API.

The included inventory system lets an admin create card/number records and release them after payment confirmation. Replace `services/card_provider.py` with the official provider adapter before live card issuance.

## Features
- 3 languages: Somali, English, Arabic
- `/lang` and `/language` switching
- Command-only customer experience; no customer button menus
- Virtual-card inventory and VIP-number inventory
- Product IDs, prices, currencies, stock states
- Telesom and Golis USSD payment instructions
- BNB and USDT-BEP20 wallet addresses
- Customer payment reference submission
- Admin confirmation/rejection
- New-user admin notification with Telegram ID/name/username/language
- 30+ admin commands/panels
- Customer support tickets
- Broadcast
- Audit log
- Database export and backup
- Maintenance flag
- SQLite by default; easy to migrate to PostgreSQL later

## Setup
1. Copy `.env.example` to `.env`.
2. Put the Telegram BotFather token in `BOT_TOKEN`.
3. Put at least one Telegram admin ID in `ADMIN_IDS`.
4. Install dependencies: `pip install -r requirements.txt`.
5. Run: `python bot.py`.

## Example admin commands
`/addcard VisaDemo 4111111111111111 5 USD`
`/addvip GoldVIP 0634999999 25 USD`
`/products_admin`
`/orders_admin`
`/confirm 1`
`/reject 1`
`/broadcast Hello customers`

## Customer commands
`/start` `/help` `/lang` `/products` `/cards` `/vip` `/buy` `/pay` `/confirm` `/orders` `/status` `/support` `/profile`

## Production checklist
- Obtain official telecom/payment API credentials and terms.
- Obtain a licensed virtual-card issuer/provider.
- Move database to managed PostgreSQL for multi-instance deployment.
- Add webhook verification/signature checks for payment callbacks.
- Encrypt sensitive provider credentials using platform secrets.
- Add rate limiting and fraud controls.
- Do not store full payment-card PAN/CVV unless your provider explicitly requires it and your compliance setup permits it.
- Add KYC/AML and age/region controls where legally required.
