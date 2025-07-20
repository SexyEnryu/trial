from aiogram import Router, types
from aiogram.filters import Command
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = "mongodb+srv://enryu:LULu4FQ1Ih9wz3tE@clientenryu.vw6z15z.mongodb.net/?retryWrites=true&w=majority&appName=ClientEnryu"
clientx = AsyncIOMotorClient(MONGO_URI)
db = clientx.pokemon_bot
users_collection = db.users

router = Router()

@router.message(Command("give"))
async def give_pokedollars(message: types.Message):
    try:
        args = message.text.split()
        if len(args) != 2:
            await message.reply("Usage: /give <amount>")
            return

        if not message.reply_to_message:
            await message.reply("You need to reply to a user's message to give them Pokedollars.")
            return

        sender_id = message.from_user.id
        receiver_id = message.reply_to_message.from_user.id

        if sender_id == receiver_id:
            await message.reply("You cannot give Pokedollars to yourself.")
            return

        try:
            amount = int(args[1])
            if amount <= 0:
                await message.reply("Please enter a positive amount.")
                return
        except ValueError:
            await message.reply("Invalid amount. Please enter a number.")
            return

        sender = await users_collection.find_one({"user_id": sender_id})
        if not sender or sender.get('pokedollars', 0) < amount:
            await message.reply("You do not have enough Pokedollars.")
            return

        receiver = await users_collection.find_one({"user_id": receiver_id})
        if not receiver:
            # This part is optional: create a user if they don't exist.
            # For now, we'll assume the receiver must have interacted with the bot before.
            await message.reply("The recipient has not used the bot before.")
            return

        # Perform the transaction
        await users_collection.update_one(
            {"user_id": sender_id},
            {"$inc": {"pokedollars": -amount}}
        )
        await users_collection.update_one(
            {"user_id": receiver_id},
            {"$inc": {"pokedollars": amount}},
            upsert=True
        )

        sender_name = message.from_user.first_name
        receiver_name = message.reply_to_message.from_user.first_name

        await message.reply(f"{sender_name} has given {amount} Pokedollars 💵 to {receiver_name}.")

    except Exception as e:
        print(f"Error in /give command: {e}")
        await message.reply("An error occurred while processing your request.")
