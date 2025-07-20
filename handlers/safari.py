import aiogram
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import random
import json
from datetime import datetime, timedelta, time as dt_time
import os
import asyncio
import time
from database import get_or_create_user, update_user_balance, add_pokemon_to_user, get_user_pokemon_collection, db
from pokemon_utils import PokemonUtils
from image_cache import get_cached_pokemon_image

router = Router()
pokemon_utils = PokemonUtils()

class SafariStates(StatesGroup):
    waiting_for_confirmation = State()
    in_safari = State()

active_safari = {}
SAFARI_BALLS = 50
SAFARI_ENTRY_FEE = 500
SAFARI_CATCH_MODIFIER = 10  # Fixed Safari Ball catch rate modifier

# Track last safari time per user
daily_safari_tracker = {}

# Track if user has started encounter in this safari session
safari_encounter_started = set()

# Cooldown system to prevent spam (4 seconds)
COOLDOWN_DURATION = 4  # seconds
user_cooldowns = {}

def check_cooldown(user_id: int, command_name: str) -> tuple[bool, float]:
    """Check if user is on cooldown for a specific command
    Returns (can_use, remaining_time)"""
    current_time = time.time()
    user_key = f"{user_id}_{command_name}"
    
    if user_key in user_cooldowns:
        last_use = user_cooldowns[user_key]
        time_passed = current_time - last_use
        
        if time_passed < COOLDOWN_DURATION:
            remaining = COOLDOWN_DURATION - time_passed
            return False, remaining
    
    return True, 0.0

def set_cooldown(user_id: int, command_name: str):
    """Set cooldown for user and command"""
    user_key = f"{user_id}_{command_name}"
    user_cooldowns[user_key] = time.time()

# Helper to get all legendary Pokémon IDs for a region
def get_legendary_pokemon_ids_for_region(region_name):
    region_mapping = {
        "Kanto": "1",
        "Johto": "2",
        "Hoenn": "3",
        "Sinnoh": "4",
        "Unova": "5",
        "Kalos": "6",
        "Alola": "7",
        "Galar": "8",
        "Paldea": "9"
    }
    region_number = region_mapping.get(region_name, "1")
    region_pokemon = pokemon_utils.regions.get(region_number, [])
    legendary_ids = []
    for poke in region_pokemon:
        if isinstance(poke, str):
            poke_data = pokemon_utils.pokemon_name_lookup.get(poke.lower())
        else:
            poke_data = pokemon_utils.pokemon_lookup.get(poke)
        if poke_data and poke_data.get('is_legendary', False):
            legendary_ids.append(poke_data['id'])
    return legendary_ids

def get_next_reset():
    now = datetime.now()
    reset_time = now.replace(hour=5, minute=0, second=0, microsecond=0)
    if now >= reset_time:
        reset_time += timedelta(days=1)
    return reset_time

def can_do_safari(user_id):
    last_time = daily_safari_tracker.get(user_id)
    now = datetime.now()
    reset_time = now.replace(hour=5, minute=0, second=0, microsecond=0)
    if last_time is None or last_time < reset_time - timedelta(days=1):
        return True
    if now >= reset_time:
        return True
    if last_time < reset_time:
        return True
    return False

def set_safari_time(user_id):
    daily_safari_tracker[user_id] = datetime.now()

async def has_pokemon_been_caught(user_id: int, pokemon_id: int):
    """Check if user has already caught this Pokemon species"""
    try:
        user_pokemon = await get_user_pokemon_collection(user_id)
        for pokemon in user_pokemon:
            if pokemon.get('id') == pokemon_id:
                return True
        return False
    except Exception as e:
        print(f"Error checking if Pokemon was caught: {e}")
        return False

# --- Persistence helpers for Safari session ---
async def save_active_safari():
    # Save all active safari sessions to DB
    if active_safari:
        for uid, data in active_safari.items():
            await db.safari_sessions.replace_one({'_id': str(uid)}, {'_id': str(uid), **data}, upsert=True)

async def load_active_safari():
    # Load all active safari sessions from DB
    global active_safari
    sessions = await db.safari_sessions.find().to_list(length=1000)
    active_safari = {int(doc['_id']): {k: v for k, v in doc.items() if k != '_id'} for doc in sessions}

# Call this on bot startup (e.g. in main.py)
# await load_active_safari()

# --- End persistence helpers ---

@router.message(Command("safari"))
async def safari_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = getattr(message.from_user, 'username', '') or ''
    first_name = getattr(message.from_user, 'first_name', '') or ''
    
    # Check cooldown before processing the command
    can_use, remaining_time = check_cooldown(user_id, "safari")
    if not can_use:
        await message.answer(f"⏱️ Please wait {remaining_time:.1f} seconds before using safari again!")
        return
    
    # Set cooldown for this user
    set_cooldown(user_id, "safari")
    
    # Run user creation and safari validation concurrently
    user_task = asyncio.create_task(get_or_create_user(user_id, username, first_name))
    safari_check = can_do_safari(user_id)
    
    user = await user_task
    
    # Check daily limit
    if not safari_check:
        next_reset = get_next_reset().strftime('%H:%M')
        await message.reply(f"❌ You can only enter the Safari Zone once per day. Next reset at 5:00 AM.", parse_mode="HTML")
        return
    
    # Check entry fee
    if user['pokedollars'] < SAFARI_ENTRY_FEE:
        await message.reply(f"❌ You need at least {SAFARI_ENTRY_FEE} Pokédollars to enter the Safari Zone.", parse_mode="HTML")
        return
    
    # Ask for confirmation
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Yes", callback_data=f"safari_confirm_yes_{user_id}"),
         InlineKeyboardButton(text="No", callback_data=f"safari_confirm_no_{user_id}")]
    ])
    await message.reply(f"Do you want to enter the Safari Zone for 500 Pokédollars?", reply_markup=kb, parse_mode="HTML")
    await state.set_state(SafariStates.waiting_for_confirmation)

@router.callback_query(F.data.startswith("safari_confirm_"))
async def safari_confirm_callback(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    data = callback_query.data
    parts = data.split('_')
    action = parts[2]
    allowed_user_id = int(parts[3])
    if user_id != allowed_user_id:
        await callback_query.answer("This button is not for you.", show_alert=True)
        return
    if action == "no":
        await callback_query.message.edit_text("You chose not to enter the Safari Zone.", parse_mode="HTML")
        await state.clear()
        return
    # Yes: proceed
    username = getattr(callback_query.from_user, 'username', '') or ''
    first_name = getattr(callback_query.from_user, 'first_name', '') or ''
    user = await get_or_create_user(user_id, username, first_name)
    if user['pokedollars'] < SAFARI_ENTRY_FEE:
        await callback_query.message.edit_text(f"❌ You need at least {SAFARI_ENTRY_FEE} Pokédollars to enter the Safari Zone.", parse_mode="HTML")
        await state.clear()
        return
    
    # Update balance and set safari time
    await update_user_balance(user_id, -SAFARI_ENTRY_FEE)
    set_safari_time(user_id)
    
    active_safari[user_id] = {
        'balls': SAFARI_BALLS,
        'region': user.get('current_region', 'Kanto'),
        'caught': [],
        'owner': user_id
    }
    
    await save_active_safari()
    await state.set_state(SafariStates.in_safari)
    reply_keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="/explore"), KeyboardButton(text="/close")]],
        resize_keyboard=True
    )
    await callback_query.message.edit_text(f"Welcome to the Safari Zone! You have {SAFARI_BALLS} Safari Balls. Only legendary Pokémon from {active_safari[user_id]['region']} appear here! Use /explore to encounter a Pokémon.", parse_mode="HTML")
    await callback_query.message.answer("Safari started.", reply_markup=reply_keyboard, parse_mode="HTML")

@router.message(Command("explore"))
async def safari_catch_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Check cooldown before processing the command
    can_use, remaining_time = check_cooldown(user_id, "explore")
    if not can_use:
        await message.answer(f"⏱️ Please wait {remaining_time:.1f} seconds before exploring again!")
        return
    
    # Set cooldown for this user
    set_cooldown(user_id, "explore")
    
    if user_id not in active_safari:
        await message.reply("You are not in the Safari Zone. Use /safari to enter.", parse_mode="HTML")
        return
    safari = active_safari[user_id]
    if safari['balls'] <= 0:
        await message.reply("You have no Safari Balls left! You are thrown out of the Safari Zone.", parse_mode="HTML")
        del active_safari[user_id]
        await save_active_safari()
        await state.clear()
        safari_encounter_started.discard(user_id)
        return
    
    # Get legendary Pokemon for region and check if already caught concurrently
    legendary_ids = get_legendary_pokemon_ids_for_region(safari['region'])
    if not legendary_ids:
        await message.reply("No legendary Pokémon found in this region!", parse_mode="HTML")
        return
    
    pokemon_id = random.choice(legendary_ids)
    level = random.randint(50, 70)
    is_shiny = random.random() < (1/8192)
    
    # Create Pokemon and check if already caught concurrently
    wild_pokemon = pokemon_utils.create_pokemon(pokemon_id, level)
    already_caught_task = asyncio.create_task(has_pokemon_been_caught(user_id, pokemon_id))
    
    if is_shiny:
        wild_pokemon['is_shiny'] = True
        # Update image path based on shiny status
        pokemon_utils.update_pokemon_image_path(wild_pokemon)
    
    safari['current'] = wild_pokemon
    
    # Save safari state and wait for already caught check concurrently
    save_task = asyncio.create_task(save_active_safari())
    already_caught = await already_caught_task
    await save_task
    
    # Use cached image instead of FSInputFile
    if pokemon_id and isinstance(pokemon_id, int):
        photo = get_cached_pokemon_image(pokemon_id, is_shiny)
    else:
        photo = None
    
    region_display = safari['region'] if safari['region'] else 'Paldea'
    caption = f"<b>A wild {wild_pokemon['name'].title()} appeared in {region_display} Safari Zone!</b>\nSafari Balls: {safari['balls']}"
    
    if already_caught:
        caption += " ☆"
    
    if is_shiny:
        caption = f"<b>✨ A SHINY {wild_pokemon['name'].title()} appeared in {region_display} Safari Zone! ✨</b>\nSafari Balls: {safari['balls']}"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Throw Safari Ball", callback_data=f"safari_throw_{user_id}")],
        [InlineKeyboardButton(text="Run", callback_data=f"safari_run_{user_id}")]
    ])
    reply_keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="/explore"), KeyboardButton(text="/close")]],
        resize_keyboard=True
    )
    
    # Only show 'Safari encounter started.' the first time in a session
    if user_id not in safari_encounter_started:
        await message.answer("Safari encounter started.", reply_markup=reply_keyboard, parse_mode="HTML")
        safari_encounter_started.add(user_id)
    
    if photo:
        await message.bot.send_photo(
            chat_id=message.chat.id,
            photo=photo,
            caption=caption,
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await message.bot.send_message(
            chat_id=message.chat.id,
            text=caption,
            reply_markup=kb,
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("safari_throw_"))
async def safari_throw_callback(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    if user_id not in active_safari:
        await callback_query.answer("Not in Safari Zone.", show_alert=True)
        return
    safari = active_safari[user_id]
    if safari['owner'] != user_id:
        await callback_query.answer("This button is not for you.", show_alert=True)
        return
    if safari['balls'] <= 0:
        await callback_query.bot.send_message(
            chat_id=callback_query.message.chat.id,
            text="You have no Safari Balls left! You are thrown out of the Safari Zone.",
            parse_mode="HTML"
        )
        del active_safari[user_id]
        await save_active_safari()
        await state.clear()
        safari_encounter_started.discard(user_id)
        return
    wild_pokemon = safari.get('current')
    if not wild_pokemon:
        await callback_query.answer("No Pokémon to catch! Use /explore.", show_alert=True)
        return
    balls_left = safari['balls']
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Catch", callback_data=f"safari_catch_{user_id}")],
        [InlineKeyboardButton(text="Run", callback_data=f"safari_run_{user_id}")]
    ])
    text = f"Safari Balls: {balls_left}\n<b>What would you like to do?</b>"
    sent_msg = await callback_query.bot.send_message(
        chat_id=callback_query.message.chat.id,
        text=text,
        reply_markup=kb,
        parse_mode="HTML"
    )
    safari['catch_message_id'] = sent_msg.message_id
    await save_active_safari()
    await callback_query.answer()

@router.callback_query(F.data.startswith("safari_catch_"))
async def safari_catch_callback(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    if user_id not in active_safari:
        await callback_query.answer("Not in Safari Zone.", show_alert=True)
        return
    safari = active_safari[user_id]
    if safari['owner'] != user_id:
        await callback_query.answer("This button is not for you.", show_alert=True)
        return
    if safari['balls'] <= 0:
        await callback_query.bot.send_message(
            chat_id=callback_query.message.chat.id,
            text="You have no Safari Balls left! You are thrown out of the Safari Zone.",
            parse_mode="HTML"
        )
        del active_safari[user_id]
        await save_active_safari()
        await state.clear()
        safari_encounter_started.discard(user_id)
        return
    wild_pokemon = safari.get('current')
    if not wild_pokemon:
        await callback_query.answer("No Pokémon to catch! Use /explore.", show_alert=True)
        return
    pokeball_data = {'name': 'Safari', 'catch_rate': SAFARI_CATCH_MODIFIER}
    catch_rate = pokemon_utils.calculate_enhanced_catch_rate(wild_pokemon, pokeball_data)
    catch_message_id = safari.get('catch_message_id')
    
    success = random.random() < catch_rate
    safari['balls'] -= 1
    
    if success:
        safari['caught'].append(wild_pokemon['name'])
        safari.pop('current', None)
        
        # Run database operations sequentially to avoid race conditions
        await add_pokemon_to_user(user_id, wild_pokemon)
        await save_active_safari()
        
        result_text = f"🎉 <b>Congratulations! You caught {wild_pokemon['name']} in the Safari Zone!</b>\n\n"
        result_text += f"<b>Level:</b> {wild_pokemon['level']}\n"
        result_text += f"<b>Nature:</b> {wild_pokemon['nature']}\n"
        result_text += f"<b>Types:</b> {'/'.join(wild_pokemon['types'])}\n\n"
        result_text += f"Safari Balls left: {safari['balls']}"
        
        if catch_message_id:
            await callback_query.bot.edit_message_text(
                chat_id=callback_query.message.chat.id,
                message_id=catch_message_id,
                text=result_text,
                parse_mode="HTML"
            )
    else:
        await save_active_safari()
        balls_left = safari['balls']
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Try Again", callback_data=f"safari_catch_{user_id}")],
            [InlineKeyboardButton(text="Run", callback_data=f"safari_run_{user_id}")]
        ])
        fail_text = f"💥 <b>{wild_pokemon['name'].title()} broke free from the Safari Ball!</b>\n\n"
        fail_text += f"Safari Balls left: {balls_left}\n"
        fail_text += f"<b>What would you like to do next?</b>"
        if catch_message_id:
            await callback_query.bot.edit_message_text(
                chat_id=callback_query.message.chat.id,
                message_id=catch_message_id,
                text=fail_text,
                reply_markup=kb,
                parse_mode="HTML"
            )
    await callback_query.answer()
    if safari['balls'] <= 0:
        await callback_query.bot.send_message(
            chat_id=callback_query.message.chat.id,
            text="You have no Safari Balls left! You are thrown out of the Safari Zone.",
            parse_mode="HTML"
        )
        del active_safari[user_id]
        await save_active_safari()
        await state.clear()
        safari_encounter_started.discard(user_id)

@router.callback_query(F.data.startswith("safari_run_"))
async def safari_run_callback(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    if user_id not in active_safari:
        await callback_query.answer("Not in Safari Zone.", show_alert=True)
        return
    safari = active_safari[user_id]
    if safari['owner'] != user_id:
        await callback_query.answer("This button is not for you.", show_alert=True)
        return
    catch_message_id = safari.get('catch_message_id')
    run_text = f"You ran away! Safari Balls left: {safari['balls']}"
    if catch_message_id:
        # Only edit if the text is different to avoid TelegramBadRequest
        try:
            await callback_query.bot.edit_message_text(
                chat_id=callback_query.message.chat.id,
                message_id=catch_message_id,
                text=run_text,
                parse_mode="HTML"
            )
        except Exception as e:
            # If message is not modified, just pass
            if 'message is not modified' in str(e):
                pass
            else:
                raise
    safari.pop('current', None)
    await save_active_safari()
    if safari['balls'] <= 0:
        await callback_query.bot.send_message(
            chat_id=callback_query.message.chat.id,
            text="You have no Safari Balls left! You are thrown out of the Safari Zone.",
            parse_mode="HTML"
        )
        del active_safari[user_id]
        await save_active_safari()
        await state.clear()
        safari_encounter_started.discard(user_id) 