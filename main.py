import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from motor.motor_asyncio import AsyncIOMotorClient
from handlers import start, myinventory, travel, hunt, mypokemons, stats, display, sort, pokemart, rods, fishing, guess, trade, candy, safari, xpin, gyms, give
from admins import add, addpd
from admins import kill
from admins import additems
from handlers import berry_vitamin
from handlers import release
from handlers.safari import load_active_safari
from handlers import myteam,duel, tms, evolve, wild_battle
from kill_middleware import KillCheckMiddleware

from config import BOT_TOKEN, MONGO_URI

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Add kill check middleware
dp.message.middleware(KillCheckMiddleware())
dp.callback_query.middleware(KillCheckMiddleware())

# Set bot instance for duel timeout handling
duel.set_bot_instance(bot)

# MongoDB client
clientx = AsyncIOMotorClient(MONGO_URI)
db = clientx.pokemon_bot
users_collection = db.users

async def main():

    async def on_startup(dispatcher):
        await load_active_safari() 
    
    # Set bot instance for xpin handler
    xpin.set_bot_instance(bot)
    
    # Include handlers
    """dp.include_router(give.router)
    dp.include_router(gyms.router)
    dp.include_router(xpin.router)
    dp.include_router(duel.router)
    dp.include_router(myteam.router)
    dp.include_router(tms.router)
    dp.include_router(candy.router)
    dp.include_router(evolve.router)
    dp.include_router(safari.router)
    dp.include_router(berry_vitamin.router)
    dp.include_router(release.router)
    dp.include_router(trade.router)
    dp.include_router(wild_battle.router)
    dp.include_router(addpd.admin_router)
    dp.include_router(add.router)
    dp.include_router(start.router)
    dp.include_router(myinventory.router)
    dp.include_router(travel.router)
    dp.include_router(hunt.router)
    dp.include_router(mypokemons.router)
    dp.include_router(stats.router)
    dp.include_router(sort.router)
    dp.include_router(display.router)
    dp.include_router(pokemart.router)
    dp.include_router(rods.router)
    dp.include_router(fishing.router)
    dp.include_router(guess.router)"""

    handlers = [
    kill.kill_router,  # Add kill router first for admin priority
    give.router,
    gyms.router,
    xpin.router,
    duel.router,
    myteam.router,
    tms.router,
    candy.router,
    evolve.router,
    safari.router,
    berry_vitamin.router,
    release.router,
    trade.router,
    wild_battle.router,
    addpd.admin_router,
    add.router,
    additems.router,
    start.router,
    myinventory.router,
    travel.router,
    hunt.router,
    mypokemons.router,
    stats.router,
    sort.router,
    display.router,
    pokemart.router,
    rods.router,
    fishing.router,
    guess.router,
]
    dp.include_routers(*handlers)
    

    
    
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())