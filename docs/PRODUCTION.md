# Production integrations still required

The Telegram application, multilingual command layer, MongoDB models, request/approval state machine, payment records, admin protection and 30-panel routing are included.

To make actual telecom operations live, connect the authorized APIs for number inventory/provisioning, eSIM/QR provisioning, ZAAD/payment verification, SMS, data/voice bundles, fiber/business services and blockchain verification. Each integration belongs in modules/.

For real money: never trust a user-submitted transaction reference alone. Verify it independently and make confirmation idempotent.
