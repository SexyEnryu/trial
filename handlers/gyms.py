from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database import get_user_gym_progress
from pokemon_utils import pokemon_utils
from database import get_user_pokemon, get_user_balance, update_user_balance
from gym_battle import GymBattle

router = Router()

active_gym_battles = {}

# Define the regions
REGIONS = ["Kanto", "Johto", "Hoenn", "Sinnoh", "Unova", "Kalos", "Alola", "Galar", "Paldea"]

# Define Kanto Gym Leaders
KANTO_GYM_LEADERS = ["Brock", "Misty", "Lt. Surge", "Erika", "Koga", "Sabrina", "Blaine", "Giovanni"]

def get_region_keyboard():
    buttons = [InlineKeyboardButton(text=region, callback_data=f"region_{region.lower()}") for region in REGIONS]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons[i:i+3] for i in range(0, len(buttons), 3)])
    return keyboard

def get_kanto_gyms_keyboard(user_progress):
    buttons = []
    # Gym Leaders
    # The number of defeated leaders is user_progress.get("kanto", -1) + 1
    # A leader is unlocked if their index is <= number of defeated leaders
    # Brock (index 0) is unlocked if defeated leaders >= 0 (i.e., progress is -1, so 0 <= 0)
    unlocked_until_index = user_progress.get("kanto", -1) + 1

    for i, leader in enumerate(KANTO_GYM_LEADERS):
        if i < unlocked_until_index:
            # This leader is defeated
            buttons.append(InlineKeyboardButton(text=f"✅ {leader}", callback_data=f"gym_kanto_{leader.lower()}"))
        elif i == unlocked_until_index:
            # This is the next available leader to challenge
            buttons.append(InlineKeyboardButton(text=leader, callback_data=f"gym_kanto_{leader.lower()}"))
        else:
            # This leader is locked
            buttons.append(InlineKeyboardButton(text=f"🔒 {leader}", callback_data="gym_locked"))

    # Elite Four and Champion (locked for now)
    buttons.append(InlineKeyboardButton(text="Elite Four", callback_data="gym_locked"))
    buttons.append(InlineKeyboardButton(text="Champion", callback_data="gym_locked"))

    # Arrange buttons in rows
    keyboard_rows = [buttons[i:i+2] for i in range(0, len(KANTO_GYM_LEADERS), 2)]
    keyboard_rows.append(buttons[-2:]) # Last row for E4 and Champion
    keyboard_rows.append([InlineKeyboardButton(text="⬅️ Back to Regions", callback_data="back_to_regions")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


@router.message(Command("gyms"))
async def gyms_command(message: types.Message):
    if message.chat.type != "private":
        await message.reply("Please use the /gyms command in a private chat with the bot.")
        return

    keyboard = get_region_keyboard()
    await message.answer("Which Region's Gyms do you want to challenge?", reply_markup=keyboard)

@router.callback_query(lambda c: c.data.startswith('region_'))
async def process_region_callback(callback_query: CallbackQuery):
    region = callback_query.data.split('_')[1]

    if region == "kanto":
        user_progress = await get_user_gym_progress(callback_query.from_user.id)
        keyboard = get_kanto_gyms_keyboard(user_progress)
        await callback_query.message.edit_text("Welcome to the Kanto Pokémon League!", reply_markup=keyboard)
    else:
        await callback_query.answer("Coming Soon..", show_alert=True)
    await callback_query.answer()


@router.callback_query(lambda c: c.data == 'back_to_regions')
async def back_to_regions_callback(callback_query: CallbackQuery):
    keyboard = get_region_keyboard()
    await callback_query.message.edit_text("Which Region's Gyms do you want to challenge?", reply_markup=keyboard)
    await callback_query.answer()

@router.callback_query(lambda c: c.data == 'gym_locked')
async def gym_locked_callback(callback_query: CallbackQuery):
    await callback_query.answer("You must defeat the previous Gym Leader to challenge this one.", show_alert=True)

@router.callback_query(lambda c: c.data.startswith('gym_kanto_'))
async def process_kanto_gym_callback(callback_query: CallbackQuery):
    leader_name = callback_query.data.split('_')[2]

    user_progress = await get_user_gym_progress(callback_query.from_user.id)
    kanto_progress = user_progress.get("kanto", -1)
    leader_index = KANTO_GYM_LEADERS.index(leader_name.capitalize())

    if leader_index > kanto_progress + 1:
        await callback_query.answer("You must defeat the previous Gym Leader first.", show_alert=True)
        return
    
    if leader_index <= kanto_progress:
        await callback_query.answer(f"You have already defeated {leader_name.capitalize()}.")
        # Optionally, you could allow re-challenging here
        return

    text = (
        f"Are you sure you want to challenge Gym Leader {leader_name.capitalize()}?\n\n"
        "<i><b>Rules:</b>\n"
        "1) Legendary & Mythical Pokémon are banned.\n"
        "2) Mega Evolution & Z-Moves are banned for challengers.\n"
        "3) The Gym Leader can use Mega Evolution and Z-Moves.\n"
        "4) 10 switches are allowed.</i>\n\n"
        "<b>Fee to challenge:</b> 500 Pokédollars"
    )
    buttons = [
        InlineKeyboardButton(text="Confirm", callback_data=f"confirm_gym_{leader_name}"),
        InlineKeyboardButton(text="Back", callback_data="region_kanto")
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()

@router.callback_query(lambda c: c.data.startswith('confirm_gym_'))
async def process_confirm_gym_callback(callback_query: CallbackQuery):
    leader_name = callback_query.data.split('_')[2]
    user_id = callback_query.from_user.id

    # Check user balance
    balance = await get_user_balance(user_id)
    if balance < 500:
        await callback_query.answer("You don't have enough Pokédollars to challenge the gym.", show_alert=True)
        return

    # Get user's team
    user_team = await get_user_pokemon(user_id)
    if not user_team:
        await callback_query.answer("You must have a team of Pokémon to challenge a gym.", show_alert=True)
        return

    # Get gym leader's team
    gym_team = pokemon_utils.get_gym_leader_team(leader_name)
    if not gym_team:
        await callback_query.answer("Could not load the gym leader's team. Please try again later.", show_alert=True)
        return

    # Deduct fee
    await update_user_balance(user_id, -500)

    # Start gym battle
    gym_battle = GymBattle(user_id, leader_name, gym_team, user_team, callback_query.message)
    active_gym_battles[user_id] = gym_battle

    await gym_battle.show_team_selection()
    await callback_query.answer()

@router.callback_query(lambda c: c.data.startswith('gym_select_'))
async def process_gym_select_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id not in active_gym_battles:
        await callback_query.answer("No active battle found.", show_alert=True)
        return

    gym_battle = active_gym_battles[user_id]
    
    # Extract pokemon index from callback_data
    pokemon_index = int(callback_query.data.split('_')[2])

    # Set lead pokemon and start battle
    await gym_battle.start_battle(pokemon_index)
    await callback_query.answer()
