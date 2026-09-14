# Telesombot — Full Button System

## ENV
- `BOT_TOKEN` — Telegram bot token
- `MONGO_URI` — MongoDB connection string
- `ADMIN_ID` — main Telegram numeric admin ID
- `DB_NAME` — optional, default `telesombot`
- `PORT` — optional, default `10000`

## Start
`python bot.py`

## Main changes
- `/start` and customer UI are button-first.
- Data, Voice, SMS, Recharge and 5G packages ask for the recipient Telesom number before creating the order.
- Business shows configured packages/prices instead of immediately asking the customer to pay for an unpriced request.
- Custom Business/Corporate/Fiber/IoT/Cloud requests create a service request first. No `I HAVE PAID` button is shown before a price exists.
- Admin can set a final price with **SET PRICE & CONFIRM**. Only then does the customer receive **PAY NOW**.
- Local Golis/Telesom payment uses a `tel:` PAY NOW button with the USSD amount prefilled where the Telegram/Android client permits it. The bot cannot bypass Android/Telegram security to press the final payment/ZAAD PIN for the user.
- After returning from payment, the customer taps **I HAVE PAID** and submits the payment reference/phone number; the payment goes to admin verification.
- Crypto payment supports BNB and USDT-BEP20 destination addresses with admin verification.
- Number inventory displays up to 15 choices; regular/virtual numbers are randomized, VIP numbers are ordered.
- Telesom public pages are synced periodically and public prices are seeded for data, voice, 5G, SIM/eSIM and Business services.
- Admin menu contains 100 numbered panels plus direct Pending Approvals and BROADCAST controls.
- Broadcast can copy text, photo, video, document or other Telegram messages to active customers.

## Important integration limitation
This project implements the Telegram order/payment workflow and admin approval system. It does **not** pretend to have private Telesom operator APIs. Actual automatic bundle activation, SIM/eSIM provisioning, automatic local-wallet transaction verification, or blockchain settlement verification requires authorized provider/API access. Without those credentials, the correct production behavior is pending/admin verification rather than falsely marking a payment as completed.
