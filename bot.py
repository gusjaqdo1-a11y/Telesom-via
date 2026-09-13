import asyncio
from aiogram import Bot, Dispatcher
from config import settings
from database import db
from handlers.user import router as user_router
from handlers.admin import router as admin_router
from handlers.customer import router as customer_router

async def main():
    bot = Bot(settings.BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(user_router)
    dp.include_router(customer_router)
    dp.include_router(admin_router)
    await db.ensure_indexes()
    print("Telesombot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
