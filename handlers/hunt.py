from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import random
import json
from datetime import datetime
import os
import asyncio
import time
from database import get_or_create_user, add_pokemon_to_user, update_user_pokeballs, update_user_balance, get_user_pokemon_collection, add_mega_stone_to_user, get_user_mega_stones, add_z_crystal_to_user, get_user_z_crystals
from pokemon_utils import PokemonUtils
from config import POKEBALLS
import glob
import inspect
from image_cache import get_cached_pokemon_image, get_cached_mega_stone_image, get_cached_z_crystal_image, get_cached_image
from handlers.duel import heal_team_to_full, update_team_and_collection_hp

router = Router()
pokemon_utils = PokemonUtils()

def filter_kwargs_for_function(func, kwargs):
    """Only pass kwargs that the function actually accepts"""
    sig = inspect.signature(func)
    valid_params = set(sig.parameters.keys())
    
    # Always allow **kwargs if the function has it
    if any(param.kind == param.VAR_KEYWORD for param in sig.parameters.values()):
        return kwargs
    
    # Otherwise, only pass arguments the function expects
    return {k: v for k, v in kwargs.items() if k in valid_params}

class HuntStates(StatesGroup):
    waiting_for_catch = State()

active_hunts = {}
# Track users who have started hunting in this session
hunt_started_users = set()

# Cooldown system to prevent spam (4 seconds)
COOLDOWN_DURATION = 2.5  # seconds
user_cooldowns = {}

def require_started_user():
    """Decorator to ensure user has started the bot before using commands"""
    def decorator(func):
        async def wrapper(message: types.Message, *args, **kwargs):
            # Only pass kwargs that the function actually accepts
            filtered_kwargs = filter_kwargs_for_function(func, kwargs)
            
            if not message.from_user:
                await message.answer("❌ User information not available.")
                return
                
            user_id = message.from_user.id
            username = getattr(message.from_user, 'username', '') or ''
            first_name = getattr(message.from_user, 'first_name', '') or ''
            user = await get_or_create_user(user_id, username, first_name)
            
            if not user.get('already_started', False):
                await message.answer("❌ You need to claim your starter package first! Use /start command to begin your Pokémon journey.")
                return
            
            return await func(message, *args, **filtered_kwargs)
        return wrapper
    return decorator

def prevent_non_started_interaction():
    """Decorator to prevent interactions between started and non-started users"""
    def decorator(func):
        async def wrapper(callback_query: CallbackQuery, *args, **kwargs):
            # Only pass kwargs that the function actually accepts  
            filtered_kwargs = filter_kwargs_for_function(func, kwargs)
            
            if not callback_query.from_user:
                await callback_query.answer("❌ User information not available.", show_alert=True)
                return
                
            user_id = callback_query.from_user.id
            username = getattr(callback_query.from_user, 'username', '') or ''
            first_name = getattr(callback_query.from_user, 'first_name', '') or ''
            user = await get_or_create_user(user_id, username, first_name)
            
            if not user.get('already_started', False):
                await callback_query.answer("❌ You need to claim your starter package first! Use /start command to begin your Pokémon journey.", show_alert=True)
                return
            
            # Skip message sender check as it's unreliable with InaccessibleMessage
            return await func(callback_query, *args, **filtered_kwargs)
        return wrapper
    return decorator

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

# Load Pokemon data from JSON file
def load_pokemon_data():
    """Load Pokemon data from poke.json file"""
    try:
        with open('poke.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print("Error: poke.json file not found!")
        return []
    except json.JSONDecodeError:
        print("Error: Invalid JSON format in poke.json!")
        return []

# Cache the Pokemon data
POKEMON_DATA = load_pokemon_data()

def get_pokemon_level_range(pokemon_id):
    """Get the level range for a specific Pokemon from JSON data"""
    for pokemon in POKEMON_DATA:
        if pokemon['id'] == pokemon_id:
            wild_range = pokemon.get('wild_range', {'min': 1, 'max': 50})
            return wild_range['min'], wild_range['max']
    
    # Default range if Pokemon not found
    return 1, 50

def generate_random_level(pokemon_id):
    """Generate a random level within the Pokemon's wild range"""
    min_level, max_level = get_pokemon_level_range(pokemon_id)
    return random.randint(min_level, max_level)

async def check_starter_package(user_id: int, username: str | None = None, first_name: str | None = None):
    """Check if user has claimed their starter package"""
    user = await get_or_create_user(user_id, username or "", first_name or "")
    
    if not user:
        return False, "❌ User data not found! Please try again."
    
    if not user.get('already_started', False):
        return False, "❌ You need to claim your starter package first! Use /start command to begin your Pokémon journey."
    
    return True, user

async def has_usable_pokemon_for_hunt(user_id: int):
    """Check if user has usable Pokemon with active moves for hunting"""
    try:
        from database import get_user_team
        user_team = await get_user_team(user_id) or []
        
        for poke in user_team:
            # Check if Pokemon has HP
            if poke.get("hp", 0) <= 0:
                continue
                
            # Check if Pokemon has active moves
            active_moves = poke.get("active_moves", [])
            if not active_moves and poke.get("moves"):
                # Auto-assign first 4 moves as active moves if none set
                poke["active_moves"] = poke["moves"][:4]
                active_moves = poke["active_moves"]
                
            if active_moves:  # Found a usable Pokemon
                return True
                
        return False
    except Exception as e:
        print(f"Error checking usable Pokemon: {e}")
        return False

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

async def check_mega_stone_reward(user_id: int):
    """Check and process mega stone reward concurrently"""
    try:
        if random.random() < 0.01:
            # Get user stones and stone files concurrently
            user_stones_task = asyncio.create_task(get_user_mega_stones(user_id))
            stone_files = glob.glob('mega_stones/*.png')
            
            user_stones = await user_stones_task
            
            if stone_files:
                available_stones = [f for f in stone_files if os.path.splitext(os.path.basename(f))[0].lower() not in [s.lower() for s in user_stones]]
                if available_stones:
                    stone_path = random.choice(available_stones)
                    stone_name = os.path.splitext(os.path.basename(stone_path))[0]
                    
                    # Stone display names
                    STONE_DISPLAY_NAMES = {
                        'redorb': 'Red Orb',
                        'blueorb': 'Blue Orb',
                        'jadeorb': 'Jade Orb',
                        'rusted_sword': 'Rusted Sword',
                        'rusted_shield': 'Rusted Shield',
                        'black_core': 'Black Core',
                        'white_core': 'White Core',
                    }
                    
                    display_name = STONE_DISPLAY_NAMES.get(stone_name.lower(), stone_name.title())
                    await add_mega_stone_to_user(user_id, stone_name)
                    return True, stone_path, display_name
                else:
                    return True, None, "You already have all available Mega Stones!"
        return False, None, None
    except Exception as e:
        print(f"Error checking mega stone reward: {e}")
        return False, None, None

async def check_z_crystal_reward(user_id: int):
    """Check and process Z-crystal reward concurrently"""
    try:
        if random.random() < 0.01:
            # Get user z-crystals and z-crystal files concurrently
            user_z_task = asyncio.create_task(get_user_z_crystals(user_id))
            z_files = glob.glob('z_crystals/*.png')
            
            user_z = await user_z_task
            
            if z_files:
                available_z = [f for f in z_files if os.path.splitext(os.path.basename(f))[0].lower() not in [z.lower() for z in user_z]]
                if available_z:
                    z_path = random.choice(available_z)
                    z_name = os.path.splitext(os.path.basename(z_path))[0]
                    
                    # Z-crystal display names
                    Z_DISPLAY_NAMES = {
                        'firiumz': 'Firium Z', 'wateriumz': 'Waterium Z', 'grassiumz': 'Grassium Z', 'electriumz': 'Electrium Z',
                        'psychiumz': 'Psychium Z', 'rockiumz': 'Rockium Z', 'snorliumz': 'Snorlium Z', 'steeliumz': 'Steelium Z',
                        'tapuniumz': 'Tapunium Z', 'mimikiumz': 'Mimikium Z', 'normaliumz': 'Normalium Z', 'pikaniumz': 'Pikanium Z',
                        'pikashuniumz': 'Pikashunium Z', 'poisoniumz': 'Poisonium Z', 'primariumz': 'Primarium Z', 'kommoniumz': 'Kommonium Z',
                        'lycaniumz': 'Lycanium Z', 'marshadiumz': 'Marshadium Z', 'mewniumz': 'Mewnium Z', 'groundiumz': 'Groundium Z',
                        'iciumz': 'Icium Z', 'inciniumz': 'Incinium Z', 'fightiniumz': 'Fightinium Z', 'flyiniumz': 'Flyinium Z',
                        'ghostiumz': 'Ghostium Z', 'dragoniumz': 'Dragonium Z', 'eeviumz': 'Eevium Z', 'fairiumz': 'Fairium Z',
                        'darkiniumz': 'Darkinium Z', 'aloraichiumz': 'Aloraichium Z', 'buginiumz': 'Buginium Z', 'decidiumz': 'Decidium Z'
                    }
                    
                    display_name = Z_DISPLAY_NAMES.get(z_name.lower(), z_name.title())
                    await add_z_crystal_to_user(user_id, z_name)
                    return True, z_path, display_name
        return False, None, None
    except Exception as e:
        print(f"Error checking Z-crystal reward: {e}")
        return False, None, None

async def check_plate_reward(user_id: int):
    """Check and process plate reward concurrently"""
    try:
        if random.random() < 0.01:
            # Get user plates and plate files concurrently
            from database import get_user_plates, add_plate_to_user
            user_plates_task = asyncio.create_task(get_user_plates(user_id))
            plate_files = glob.glob('plates/*.png')
            
            user_plates = await user_plates_task
            
            if plate_files:
                available_plates = [f for f in plate_files if os.path.splitext(os.path.basename(f))[0].lower() not in [p.lower() for p in user_plates]]
                if available_plates:
                    plate_path = random.choice(available_plates)
                    plate_name = os.path.splitext(os.path.basename(plate_path))[0]
                    
                    # Plate display names
                    PLATE_DISPLAY_NAMES = {
                        'flame-plate': 'Flame Plate', 'splash-plate': 'Splash Plate', 'zap-plate': 'Zap Plate',
                        'meadow-plate': 'Meadow Plate', 'icicle-plate': 'Icicle Plate', 'fist-plate': 'Fist Plate',
                        'toxic-plate': 'Toxic Plate', 'earth-plate': 'Earth Plate', 'sky-plate': 'Sky Plate',
                        'mind-plate': 'Mind Plate', 'insect-plate': 'Insect Plate', 'stone-plate': 'Stone Plate',
                        'spooky-plate': 'Spooky Plate', 'draco-plate': 'Draco Plate', 'dread-plate': 'Dread Plate',
                        'iron-plate': 'Iron Plate', 'pixie-plate': 'Pixie Plate'
                    }
                    
                    display_name = PLATE_DISPLAY_NAMES.get(plate_name.lower(), plate_name.title())
                    await add_plate_to_user(user_id, plate_name)
                    return True, plate_path, display_name
        return False, None, None
    except Exception as e:
        print(f"Error checking plate reward: {e}")
        return False, None, None

def get_shiny_chance():
    """Get shiny encounter chance for hunting (default 1/8192)"""
    return 1/8192

def should_pokemon_be_shiny():
    """Determine if encountered Pokemon should be shiny (for hunting)"""
    return random.random() < get_shiny_chance()

@router.message(Command("hunt"))
@require_started_user()
async def hunt_command(message: types.Message, state: FSMContext):
    if not message.from_user:
        return
    
    # Check if command is used in DM only
    if message.chat.type != "private":
        await message.answer("❌ The hunt command can only be used in private messages with the bot!")
        return
    
    user_id = message.from_user.id
    
    # Check cooldown before processing the command
    can_use, remaining_time = check_cooldown(user_id, "hunt")
    if not can_use:
        await message.answer(f"⏱️ Please wait {remaining_time:.1f} seconds before hunting again!")
        return
    
    # Set cooldown for this user
    set_cooldown(user_id, "hunt")
    
    # Add reply keyboard with /hunt and /close
    reply_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/hunt"), KeyboardButton(text="/close")]
        ],
        resize_keyboard=True
    )
    # Show 'Hunt started.' only the first time in this session
    if user_id not in hunt_started_users:
        await message.answer("Hunt started.", reply_markup=reply_keyboard)
        hunt_started_users.add(user_id)
    # Do NOT send any message on subsequent uses
    
    # Check if user has claimed starter package
    username = getattr(message.from_user, 'username', '') or ''
    first_name = getattr(message.from_user, 'first_name', '') or ''
    is_valid, result = await check_starter_package(user_id, username, first_name)
    if not is_valid:
        await message.answer(str(result))
        return
    
    user = result  # result contains user data if valid
    
    # Heal team before checking if usable
    from database import get_user_team, db
    user_team = await get_user_team(user_id)
    if user_team:
        healed_team = heal_team_to_full(user_team)
        # Save healed team back to database
        await db.users.update_one({"user_id": user_id}, {"$set": {"team": healed_team}})
        # Also update the collection
        await update_team_and_collection_hp(user_id, healed_team)
    
    # Check if user has usable Pokemon with moves for hunting
    has_usable = await has_usable_pokemon_for_hunt(user_id)
    if not has_usable:
        await message.answer("❌ You need Pokémon with moves to hunt! Visit /myteam to set active moves for your Pokémon first.")
        return
    
    if user_id in active_hunts:
        del active_hunts[user_id]
    
    await state.clear()
    
    # Check for rewards concurrently
    mega_stone_task = asyncio.create_task(check_mega_stone_reward(user_id))
    z_crystal_task = asyncio.create_task(check_z_crystal_reward(user_id))
    plate_task = asyncio.create_task(check_plate_reward(user_id))
    
    # Wait for all reward checks to complete
    mega_stone_result, z_crystal_result, plate_result = await asyncio.gather(mega_stone_task, z_crystal_task, plate_task, return_exceptions=True)
    
    # Handle mega stone reward
    if not isinstance(mega_stone_result, Exception) and isinstance(mega_stone_result, tuple) and len(mega_stone_result) == 3:
        got_mega_stone, stone_path, display_name = mega_stone_result
        if got_mega_stone:
            if stone_path:
                dramatic_msg = f"<b>Amazing!!!</b>\nYou Found <b>{display_name}</b>!"
                # Use cached image instead of FSInputFile
                photo = get_cached_image(stone_path)
                if photo:
                    await message.reply_photo(photo=photo, caption=dramatic_msg, parse_mode="HTML")
                else:
                    await message.reply(dramatic_msg, parse_mode="HTML")
                return
            else:
                if display_name:
                    await message.reply(display_name, parse_mode="HTML")
                return
    
    # Handle Z-crystal reward
    if not isinstance(z_crystal_result, Exception) and isinstance(z_crystal_result, tuple) and len(z_crystal_result) == 3:
        got_z_crystal, z_path, display_name = z_crystal_result
        if got_z_crystal:
            if z_path:
                dramatic_msg = f"<b>Incredible!!</b>\nYou Found <b>{display_name}</b>!"
                # Use cached image instead of FSInputFile
                photo = get_cached_image(z_path)
                if photo:
                    await message.reply_photo(photo=photo, caption=dramatic_msg, parse_mode="HTML")
                else:
                    await message.reply(dramatic_msg, parse_mode="HTML")
                return
    
    # Handle plate reward
    if not isinstance(plate_result, Exception) and isinstance(plate_result, tuple) and len(plate_result) == 3:
        got_plate, plate_path, display_name = plate_result
        if got_plate:
            if plate_path:
                dramatic_msg = f"<b>Spectacular!!</b>\nYou Found <b>{display_name}</b>!"
                # Use cached image instead of FSInputFile
                photo = get_cached_image(plate_path)
                if photo:
                    await message.reply_photo(photo=photo, caption=dramatic_msg, parse_mode="HTML")
                else:
                    await message.reply(dramatic_msg, parse_mode="HTML")
                return
    
    # Get user's current region
    if not isinstance(user, dict):
        await message.reply("❌ Invalid user data!", parse_mode="HTML")
        return
    current_region = user.get('current_region', 'Kanto')
    print(f"DEBUG: User {user_id} is hunting in region: {current_region}")
    
    # Test region data loading
    pokemon_utils.test_region_data(current_region)
    
    # Generate Pokemon encounter concurrently with checking if already caught
    pokemon_id, pokemon_data = pokemon_utils.get_random_region_pokemon(current_region)
    level = generate_random_level(pokemon_id)
    is_shiny = should_pokemon_be_shiny()
    
    # Create Pokemon and check if already caught concurrently
    wild_pokemon = pokemon_utils.create_pokemon(pokemon_id, level)
    already_caught_task = asyncio.create_task(has_pokemon_been_caught(user_id, pokemon_id))
    
    # Set EV yield data for the Pokemon
    wild_pokemon['ev_yield'] = pokemon_utils.get_ev_yield(pokemon_id)
    
    if is_shiny:
        wild_pokemon['is_shiny'] = True
        # Update image path based on shiny status
        pokemon_utils.update_pokemon_image_path(wild_pokemon)
    
    # Defensive: Ensure 'name' exists
    if 'name' not in wild_pokemon or not wild_pokemon['name']:
        await message.reply("❌ Error: Pokémon data is missing a name. Please contact the admin.", parse_mode="HTML")
        return
    
    # Wait for the already caught check to complete
    already_caught = await already_caught_task
    
    hunt_id = f"{user_id}_{datetime.now().timestamp()}"
    
    active_hunts[user_id] = {
        'pokemon': wild_pokemon,
        'timestamp': datetime.now(),
        'hunt_id': hunt_id,
        'photo_message_id': None,
        'region': current_region
    }
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Catch", callback_data=f"catch_{hunt_id}"),
            InlineKeyboardButton(text="EV Yields", callback_data=f"ev_{hunt_id}")
        ]
    ])
    
    # Build hunt text with star indicator if already caught
    pokemon_name = wild_pokemon['name'].title()
    types = wild_pokemon.get('types', [])
    types_display = " / ".join([t.title() for t in types]) if types else "Normal"
    
    if wild_pokemon.get('is_shiny', False):
        hunt_text = f"✨ <b>SHINY {pokemon_name}</b> ✨ (Lv. {wild_pokemon['level']})\n"
        hunt_text += f"<b>Type:</b> {types_display}\n"
        hunt_text += f"<b>Region:</b> {current_region}"
    else:
        hunt_text = f"You encountered a wild <b>{pokemon_name}</b> (Lv. {wild_pokemon['level']})\n"
        hunt_text += f"<b>Type:</b> {types_display}\n"
        hunt_text += f"<b>Region:</b> {current_region}"
    if already_caught:
        hunt_text += " ☆"
    
    # Check image path and send message using cached image
    pokemon_id = wild_pokemon.get('id')
    is_shiny = wild_pokemon.get('is_shiny', False)
    
    if pokemon_id and isinstance(pokemon_id, int):
        photo = get_cached_pokemon_image(pokemon_id, is_shiny)
    else:
        photo = None
    
    if photo:
        photo_msg = await message.reply_photo(
            photo=photo,
            caption=hunt_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        active_hunts[user_id]['photo_message_id'] = photo_msg.message_id
    else:
        photo_msg = await message.reply(
            hunt_text, 
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        active_hunts[user_id]['photo_message_id'] = photo_msg.message_id
    
    await state.set_state(HuntStates.waiting_for_catch)

@router.callback_query(F.data.startswith("ev_"))
@prevent_non_started_interaction()
async def show_ev_yields(callback_query: CallbackQuery):
    """Display EV yield information for the encountered Pokémon as an alert."""
    user_id = callback_query.from_user.id

    hunt_id = callback_query.data.replace("ev_", "") if callback_query.data else ""

    hunt = active_hunts.get(user_id)
    if not hunt or hunt.get("hunt_id") != hunt_id:
        await callback_query.answer("⚠️ This hunt session has expired. Use /hunt to find a new Pokémon!", show_alert=True)
        return

    wild_pokemon = hunt["pokemon"]
    pokemon_id = wild_pokemon.get('id')
    
    # Get EV yield from evYield.json
    ev_yield = pokemon_utils.get_ev_yield(pokemon_id) if pokemon_id else {}
    
    pokemon_name = wild_pokemon['name'].title()
    
    if not ev_yield:
        alert_text = f"{pokemon_name} does not grant any EVs."
    else:
        # Format EV yield display for alert
        parts = []
        for stat, value in ev_yield.items():
            parts.append(f"+{value} {stat}")
        
        alert_text = f"{pokemon_name} EV Yield:\n" + "\n".join(parts)

    # Show as alert popup
    await callback_query.answer(alert_text, show_alert=True)

@router.callback_query(F.data.startswith("catch_"))
@prevent_non_started_interaction()
async def catch_pokemon(callback_query: CallbackQuery, state: FSMContext):
    """Start battle with wild Pokemon instead of pokeball selection"""
    user_id = callback_query.from_user.id
    
    # Check if user has claimed starter package
    username = getattr(callback_query.from_user, 'username', '') or ''
    first_name = getattr(callback_query.from_user, 'first_name', '') or ''
    is_valid, result = await check_starter_package(user_id, username, first_name)
    if not is_valid:
        await callback_query.answer(str(result), show_alert=True)
        return
    
    callback_data_parts = callback_query.data.split("_") if callback_query.data else []
    if len(callback_data_parts) < 2:
        await callback_query.answer("❌ Invalid callback data!", show_alert=True)
        return
        
    hunt_id = "_".join(callback_data_parts[1:])
    
    # Check if hunt is still active
    if user_id not in active_hunts:
        await callback_query.answer("⚠️ This hunt session has expired. Use /hunt to find a new Pokémon!", show_alert=True)
        return
    
    current_hunt = active_hunts[user_id]
    if current_hunt['hunt_id'] != hunt_id:
        await callback_query.answer("⚠️ This hunt session has expired. Use /hunt to find a new Pokémon!", show_alert=True)
        return

    # Check if user has usable Pokemon before starting battle
    from database import get_user_team
    user_team = await get_user_team(user_id) or []
    
    # Helper function to check if Pokemon is usable
    def _is_pokemon_usable(poke):
        if poke.get("hp", 0) <= 0:
            return False
        # Pokemon is usable if it has HP > 0 (moves can be added in battle if needed)
        return True
    
    usable_pokemon = [p for p in user_team if _is_pokemon_usable(p)]
    
    if not user_team or not usable_pokemon:
        await callback_query.answer("You don't have any usable Pokémon! Visit a Pokémon Center to heal your team.", show_alert=True)
        return

    # Start battle
    await callback_query.answer("Starting battle...")
    
    # Heal team before starting wild battle (ensure team is healed and saved)
    from database import get_user_team, db
    user_team = await get_user_team(user_id)
    if user_team:
        healed_team = heal_team_to_full(user_team)
        await db.users.update_one({"user_id": user_id}, {"$set": {"team": healed_team}})
        await update_team_and_collection_hp(user_id, healed_team)

    # Start turn-based battle
    from handlers.wild_battle import start_battle as start_wild_battle
    await start_wild_battle(callback_query, user_id, current_hunt["pokemon"])
    
    # Do NOT clear active_hunts here; let the battle logic handle it
    await state.clear()

@router.message(Command("close"))
@require_started_user()
async def close_keyboard(message: types.Message):
    # Remove the reply keyboard without sending any text
    await message.answer("Keyboard closed.", reply_markup=types.ReplyKeyboardRemove())



