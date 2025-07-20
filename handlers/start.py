from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import get_or_create_user, mark_user_as_started, add_pokemon_to_user
import datetime
from pokemon_utils import PokemonUtils

router = Router()

# Initialize pokemon utils
pokemon_utils = PokemonUtils()

@router.message(Command("start"))
async def start_command(message: types.Message):
    """Start command - Initialize user and welcome them"""
    # Check if command is used in DM
    if message.chat.type != 'private':
        await message.answer("❌ This command can only be used in private messages!")
        return
    """Start command - Initialize user and welcome them"""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    user = await get_or_create_user(user_id, username, first_name)
    
    # Check if user already exists (has started adventure)
    if user.get('already_started', False):
        already_started_text = f"You have already begun your adventure, {first_name}!"
        await message.answer(already_started_text, parse_mode="HTML")
        return
    
    # Start Professor Enryu's introduction
    intro_text = f"🔬 <b>Professor Enryu:</b> Greetings, {first_name}! Welcome to the world of Pokémon!"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Next ➡️", callback_data="intro_step_2")]
    ])
    
    await message.answer(intro_text, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(lambda c: c.data == "intro_step_2")
async def intro_step_2(callback_query: types.CallbackQuery):
    """Second step of Professor Enryu's introduction"""
    text = "🔬 <b>Professor Enryu:</b> This world is inhabited by creatures called Pokémon. They live alongside humans as partners and friends."
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Next ➡️", callback_data="intro_step_3")]
    ])
    
    await callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(lambda c: c.data == "intro_step_3")
async def intro_step_3(callback_query: types.CallbackQuery):
    """Third step of Professor Enryu's introduction"""
    text = "🔬 <b>Professor Enryu:</b> Your journey as a Pokémon Trainer is about to begin! You'll catch, train, and battle with these amazing creatures."
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Next ➡️", callback_data="intro_step_4")]
    ])
    
    await callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(lambda c: c.data == "intro_step_4")
async def intro_step_4(callback_query: types.CallbackQuery):
    """Fourth step of Professor Enryu's introduction"""
    text = "🔬 <b>Professor Enryu:</b> I've prepared a special starter package to help you on your adventure. It contains everything you need to begin!"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Next ➡️", callback_data="intro_step_5")]
    ])
    
    await callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(lambda c: c.data == "intro_step_5")
async def intro_step_5(callback_query: types.CallbackQuery):
    """Starter selection scene"""
    text = "🔬 <b>Professor Enryu:</b> Before you can receive your starter package, I need you to choose a starter Pokémon! Please select one from the grid below:"
    
    # Create a 3x9 grid of starter Pokémon buttons
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Bulbasaur", callback_data="starter_1"),
            InlineKeyboardButton(text="Charmander", callback_data="starter_4"),
            InlineKeyboardButton(text="Squirtle", callback_data="starter_7")
        ],
        [
            InlineKeyboardButton(text="Chikorita", callback_data="starter_152"),
            InlineKeyboardButton(text="Cyndaquil", callback_data="starter_155"),
            InlineKeyboardButton(text="Totodile", callback_data="starter_158")
        ],
        [
            InlineKeyboardButton(text="Treecko", callback_data="starter_252"),
            InlineKeyboardButton(text="Torchic", callback_data="starter_255"),
            InlineKeyboardButton(text="Mudkip", callback_data="starter_258")
        ],
        [
            InlineKeyboardButton(text="Turtwig", callback_data="starter_387"),
            InlineKeyboardButton(text="Chimchar", callback_data="starter_390"),
            InlineKeyboardButton(text="Piplup", callback_data="starter_393")
        ],
        [
            InlineKeyboardButton(text="Snivy", callback_data="starter_495"),
            InlineKeyboardButton(text="Tepig", callback_data="starter_498"),
            InlineKeyboardButton(text="Oshawott", callback_data="starter_501")
        ],
        [
            InlineKeyboardButton(text="Chespin", callback_data="starter_650"),
            InlineKeyboardButton(text="Fennekin", callback_data="starter_653"),
            InlineKeyboardButton(text="Froakie", callback_data="starter_656")
        ],
        [
            InlineKeyboardButton(text="Rowlet", callback_data="starter_722"),
            InlineKeyboardButton(text="Litten", callback_data="starter_725"),
            InlineKeyboardButton(text="Popplio", callback_data="starter_728")
        ],
        [
            InlineKeyboardButton(text="Grookey", callback_data="starter_810"),
            InlineKeyboardButton(text="Scorbunny", callback_data="starter_813"),
            InlineKeyboardButton(text="Sobble", callback_data="starter_816")
        ],
        [
            InlineKeyboardButton(text="Sprigatito", callback_data="starter_906"),
            InlineKeyboardButton(text="Fuecoco", callback_data="starter_909"),
            InlineKeyboardButton(text="Quaxly", callback_data="starter_912")
        ]
    ])
    
    await callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(lambda c: c.data.startswith("starter_"))
async def select_starter(callback_query: types.CallbackQuery):
    """Handle starter Pokémon selection"""
    starter_id = int(callback_query.data.split("_")[1])
    first_name = callback_query.from_user.first_name
    user_id = callback_query.from_user.id
    
    # Check if user has already started to prevent multiple starters
    user = await get_or_create_user(user_id, callback_query.from_user.username, first_name)
    if user.get('already_started', False):
        await callback_query.answer("You have already chosen your starter Pokémon!", show_alert=True)
        return
    
    # Get starter Pokémon name from ID
    starter_names = {
        1: "Bulbasaur", 4: "Charmander", 7: "Squirtle",
        152: "Chikorita", 155: "Cyndaquil", 158: "Totodile",
        252: "Treecko", 255: "Torchic", 258: "Mudkip",
        387: "Turtwig", 390: "Chimchar", 393: "Piplup",
        495: "Snivy", 498: "Tepig", 501: "Oshawott",
        650: "Chespin", 653: "Fennekin", 656: "Froakie",
        722: "Rowlet", 725: "Litten", 728: "Popplio",
        810: "Grookey", 813: "Scorbunny", 816: "Sobble",
        906: "Sprigatito", 909: "Fuecoco", 912: "Quaxly"
    }
    
    starter_name = starter_names.get(starter_id, "Unknown Pokémon")
    
    # Create starter Pokémon using enhanced pokemon_utils method
    starter_pokemon = pokemon_utils.create_pokemon(pokemon_id=starter_id, level=5)
    
    # Add starter Pokémon to user's collection
    await add_pokemon_to_user(user_id, starter_pokemon)
    
    # Mark user as started immediately to prevent multiple starters
    await mark_user_as_started(user_id)
    
    text = f"🔬 <b>Professor Enryu:</b> Excellent choice, {first_name}! You've selected {starter_name}! Now, let's move on to your starter package!"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Next ➡️", callback_data="intro_final")]
    ])
    
    await callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(lambda c: c.data == "intro_final")
async def intro_final(callback_query: types.CallbackQuery):
    """Final step - offer starter package"""
    text = "🔬 <b>Professor Enryu:</b> Claim your starter package using the equip button below!"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎒 Equip Starter Package", callback_data="equip_starter")]
    ])
    
    await callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(lambda c: c.data == "equip_starter")
async def equip_starter(callback_query: types.CallbackQuery):
    """Handle starter package equipment"""
    user_id = callback_query.from_user.id
    first_name = callback_query.from_user.first_name
    
    starter_text = f"""🎉 <b>Congratulations, {first_name}!</b> 🎉

📦 <b>You received the following in your starter package:</b>

<b>1000 PokéDollars 💵</b>
<b>10 Regular Poké Balls</b>
<b>5 Great Balls</b>
<b>3 Ultra Balls</b>

<b>Your Pokémon journey begins now!</b>
<b>Good luck, Trainer! 🍀</b>"""
    
    # Remove all buttons by not including reply_markup
    await callback_query.message.edit_text(starter_text, parse_mode="HTML")
    
    # Answer the callback query to remove loading state
    await callback_query.answer("Starter package equipped successfully!")

