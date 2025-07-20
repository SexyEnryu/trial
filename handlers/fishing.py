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
from database import get_or_create_user, add_pokemon_to_user, update_user_pokeballs, update_user_balance, get_user_pokemon_collection, get_user_fishing_rods, add_mega_stone_to_user, get_user_mega_stones, add_z_crystal_to_user, get_user_z_crystals
from pokemon_utils import PokemonUtils
from config import POKEBALLS, FISHING_RODS
from typing import Optional
import glob
from image_cache import get_cached_pokemon_image, get_cached_mega_stone_image, get_cached_z_crystal_image, get_cached_image

router = Router()
pokemon_utils = PokemonUtils()

class FishingStates(StatesGroup):
    waiting_for_catch = State()
    selecting_pokeball = State()

active_fishing = {}
# Track users who have started fishing in this session
fishing_started_users = set()

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

# Load Pokemon data from JSON file (cached)
def load_pokemon_data():
    """Load Pokemon data from poke.json file (cached)"""
    from config import get_pokemon_data
    pokemon_data = get_pokemon_data()
    # Convert dict to list if needed for compatibility
    if isinstance(pokemon_data, dict):
        return list(pokemon_data.values()) if pokemon_data else []
    return pokemon_data if pokemon_data else []

# Cache the Pokemon data
POKEMON_DATA = load_pokemon_data()

def get_water_type_pokemon():
    """Get all Water-type Pokemon from JSON data"""
    water_pokemon = []
    for pokemon in POKEMON_DATA:
        if 'water' in [t.lower() for t in pokemon.get('types', [])]:
            water_pokemon.append(pokemon)
    return water_pokemon

def get_ice_type_pokemon():
    """Get all Ice-type Pokemon from JSON data"""
    ice_pokemon = []
    for pokemon in POKEMON_DATA:
        if 'ice' in [t.lower() for t in pokemon.get('types', [])]:
            ice_pokemon.append(pokemon)
    return ice_pokemon

def get_deep_sea_pokemon():
    """Get deep sea Pokemon (Water types with high HP or special abilities)"""
    water_pokemon = get_water_type_pokemon()
    deep_sea_pokemon = []
    
    for pokemon in water_pokemon:
        base_stats = pokemon.get('base_stats', {})
        hp = base_stats.get('hp', 0)
        
        # Consider Pokemon with high HP or specific deep-sea characteristics as deep sea Pokemon
        if hp >= 80 or pokemon.get('capture_rate', 255) < 100:
            deep_sea_pokemon.append(pokemon)
    
    return deep_sea_pokemon

def get_pokemon_by_fishing_rod(rod_name):
    """Get Pokemon that can be caught with specific fishing rod based on rarity"""
    water_pokemon = get_water_type_pokemon()
    ice_pokemon = get_ice_type_pokemon()
    deep_sea_pokemon = get_deep_sea_pokemon()
    
    if not water_pokemon:
        return []
    
    # Define Pokemon rarity based on capture rate
    # Lower capture rate = rarer Pokemon
    common_pokemon = [p for p in water_pokemon if p.get('capture_rate', 255) >= 150]
    uncommon_pokemon = [p for p in water_pokemon if 100 <= p.get('capture_rate', 255) < 150]
    rare_pokemon = [p for p in water_pokemon if 50 <= p.get('capture_rate', 255) < 100]
    very_rare_pokemon = [p for p in water_pokemon if p.get('capture_rate', 255) < 50]
    
    # Define what each rod can catch based on FISHING_RODS config
    rod_pokemon_pools = {
        'Old Rod': common_pokemon,
        'Good Rod': common_pokemon + uncommon_pokemon,
        'Super Rod': common_pokemon + uncommon_pokemon + rare_pokemon,
        'Ultra Rod': common_pokemon + uncommon_pokemon + rare_pokemon + very_rare_pokemon,
        'Master Rod': water_pokemon,  # Can catch all water Pokemon
        'Shiny Rod': water_pokemon,  # Can catch all water Pokemon (shiny chance handled separately)
        'Deep Sea Rod': deep_sea_pokemon + rare_pokemon + very_rare_pokemon,  # Deep sea and rare Pokemon
        'Crystal Rod': water_pokemon + ice_pokemon  # Water and Ice type Pokemon
    }
    
    return rod_pokemon_pools.get(rod_name, common_pokemon)

def get_shiny_chance(rod_name):
    """Get shiny encounter chance based on fishing rod"""
    shiny_chances = {
        'Old Rod': 1/8192,      # Base shiny rate
        'Good Rod': 1/8192,     # Base shiny rate
        'Super Rod': 1/8192,    # Base shiny rate
        'Ultra Rod': 1/6144,    # Slightly better
        'Master Rod': 1/4096,   # Better shiny rate
        'Shiny Rod': 1/512,     # Significantly increased shiny rate
        'Deep Sea Rod': 1/5120, # Slightly better than base
        'Crystal Rod': 1/4096   # Better shiny rate
    }
    return shiny_chances.get(rod_name, 1/8192)

def should_pokemon_be_shiny(rod_name):
    """Determine if encountered Pokemon should be shiny"""
    shiny_chance = get_shiny_chance(rod_name)
    return random.random() < shiny_chance

def get_pokemon_image_path(pokemon_id, is_shiny=False):
    """Get the correct image path for Pokemon (shiny or normal)"""
    if is_shiny:
        shiny_path = f"shiny_pokemon/{pokemon_id}.png"
        if os.path.exists(shiny_path):
            return shiny_path
    
    # Fallback to normal image
    normal_path = f"assets/images/{pokemon_id}.png"
    return normal_path

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

def get_fishing_encounter_rate(rod_name):
    """Get the encounter rate based on fishing rod"""
    for rod in FISHING_RODS:
        if rod['name'] == rod_name:
            # Base encounter rate is 30%, modified by rod's fish_rate
            base_rate = 0.3
            return min(base_rate * rod['fish_rate'], 0.9)  # Cap at 90%
    return 0.3  # Default rate if rod not found

def calculate_lure_ball_effectiveness(pokemon_data, pokeball_data):
    """Calculate enhanced catch rate for Lure Ball when fishing"""
    if pokeball_data['name'] == 'Lure':
        # Lure Ball is 3x more effective when fishing
        return pokeball_data['catch_rate'] * 5
    return pokeball_data['catch_rate']

def create_pokemon_from_json(pokemon_data, level, is_shiny=False):
    """Create a Pokemon object from JSON data compatible with pokemon_utils"""
    # Convert JSON structure to pokemon_utils expected format
    pokemon = {
        'id': pokemon_data['id'],
        'name': pokemon_data['name'].title(),
        'level': level,
        'type': pokemon_data.get('types', []),  # Use 'types' from JSON
        'base_stats': {
            'HP': pokemon_data.get('base_stats', {}).get('hp', 45),
            'Attack': pokemon_data.get('base_stats', {}).get('atk', 45),
            'Defense': pokemon_data.get('base_stats', {}).get('def', 45),
            'Sp. Attack': pokemon_data.get('base_stats', {}).get('spa', 45),
            'Sp. Defense': pokemon_data.get('base_stats', {}).get('spd', 45),
            'Speed': pokemon_data.get('base_stats', {}).get('speed', 45)
        },
        'capture_rate': pokemon_data.get('capture_rate', 255),
        'is_legendary': pokemon_data.get('is_legendary', False),
        'is_mythical': pokemon_data.get('is_mythical', False),
        'is_shiny': is_shiny,
        'image': get_pokemon_image_path(pokemon_data['id'], is_shiny),
        'nature': pokemon_utils.get_random_nature(),
        'ivs': pokemon_utils.generate_random_ivs(),
        'evs': {stat: 0 for stat in ['HP', 'Attack', 'Defense', 'Sp. Attack', 'Sp. Defense', 'Speed']},
        'moves': [],  # Will be populated below
        'hp': 1,  # Will be calculated
        'max_hp': 1,     # Will be calculated
        'status': None,
        'experience': 0,
        'captured_with': None,
        'caught_date': None,
        'trainer_id': None,
        'caught_method': None,
        'caught_with_rod': None
    }
    
    # Get moves for the Pokemon at this level using pokemon_utils
    moves = pokemon_utils.get_moves_for_level(pokemon_data['id'], level)
    pokemon['moves'] = moves
    
    # Calculate actual stats using pokemon_utils
    calculated_stats = pokemon_utils.calculate_stats(
        {'base_stats': pokemon_data.get('base_stats', {})}, 
        level, 
        pokemon['ivs'], 
        pokemon['evs'], 
        pokemon['nature']
    )
    
    pokemon['calculated_stats'] = calculated_stats
    pokemon['hp'] = calculated_stats.get('HP', 1)
    pokemon['max_hp'] = calculated_stats.get('HP', 1)
    
    return pokemon

async def check_starter_package(user_id: int, username: Optional[str] = None, first_name: Optional[str] = None):
    """Check if user has claimed their starter package"""
    # Ensure username and first_name are always str
    username = username or ""
    first_name = first_name or ""
    user = await get_or_create_user(user_id, username, first_name)
    
    if not user:
        return False, "User data not found! Please try again."
    
    if not user.get('already_started', False):
        return False, "You need to claim your starter package first! Use /start command to begin your Pokémon journey."
    
    return True, user

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

async def check_fishing_rewards(user_id: int):
    """Check for mega stone, z-crystal, and plate rewards concurrently"""
    try:
        # Check all rewards concurrently
        mega_stone_chance = random.random() < 0.005  # 0.5% chance for fishing
        z_crystal_chance = random.random() < 0.005   # 0.5% chance for fishing
        plate_chance = random.random() < 0.005       # 0.5% chance for fishing
        
        rewards = []
        
        if mega_stone_chance:
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
                    }
                    
                    display_name = STONE_DISPLAY_NAMES.get(stone_name.lower(), stone_name.title())
                    await add_mega_stone_to_user(user_id, stone_name)
                    rewards.append(('mega_stone', stone_path, display_name))
        
        if z_crystal_chance:
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
                    rewards.append(('z_crystal', z_path, display_name))
        
        if plate_chance:
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
                    rewards.append(('plate', plate_path, display_name))
        
        return rewards
    except Exception as e:
        print(f"Error checking fishing rewards: {e}")
        return []

@router.message(Command("fishing"))
async def fishing_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else None
    if user_id is None:
        await message.answer("User information not found.")
        return
    
    # Check if command is used in DM only
    if message.chat.type != "private":
        await message.answer("❌ The fishing command can only be used in private messages with the bot!")
        return
    
    # Check cooldown before processing the command
    can_use, remaining_time = check_cooldown(user_id, "fishing")
    if not can_use:
        await message.answer(f"⏱️ Please wait {remaining_time:.1f} seconds before fishing again!")
        return
    
    # Set cooldown for this user
    set_cooldown(user_id, "fishing")
    
    # Add reply keyboard with /fishing and /close
    reply_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/fishing"), KeyboardButton(text="/close")]
        ],
        resize_keyboard=True
    )
    
    # Show 'Fishing started.' only the first time in this session
    if user_id not in fishing_started_users:
        await message.answer("Fishing started.", reply_markup=reply_keyboard)
        fishing_started_users.add(user_id)
    
    # Check if user has claimed starter package and get fishing rods concurrently
    username = getattr(message.from_user, 'username', '') or ''
    first_name = getattr(message.from_user, 'first_name', '') or ''
    
    # Run user validation and fishing rod check concurrently
    user_check_task = asyncio.create_task(check_starter_package(user_id, username, first_name))
    fishing_rods_task = asyncio.create_task(get_user_fishing_rods(user_id))
    
    is_valid, result = await user_check_task
    user_rods = await fishing_rods_task
    
    if not is_valid:
        await message.answer(str(result))
        return
    
    user = result  # result contains user data if valid
    
    if user_id in active_fishing:
        del active_fishing[user_id]
    
    await state.clear()
    
    # Check for fishing rewards concurrently
    rewards = await check_fishing_rewards(user_id)
    
    # Handle rewards if any
    for reward_type, reward_path, display_name in rewards:
        if reward_type == 'mega_stone':
            dramatic_msg = f"<b>Amazing!!!</b>\nYou found <b>{display_name}</b> while fishing!"
        elif reward_type == 'z_crystal':
            dramatic_msg = f"<b>Incredible!!</b>\nYou found <b>{display_name}</b> while fishing!"
        else:  # plate
            dramatic_msg = f"<b>Spectacular!!</b>\nYou found <b>{display_name}</b> while fishing!"
        
        # Use cached image instead of FSInputFile
        photo = get_cached_image(reward_path)
        if photo:
            await message.reply_photo(photo=photo, caption=dramatic_msg, parse_mode="HTML")
        else:
            await message.reply(dramatic_msg, parse_mode="HTML")
        return
    
    # Check if user has any fishing rods
    if not user_rods:
        await message.answer("❌ You don't have any fishing rods! Visit the Pokémart to buy one.")
        return
    
    # Get encounter rate based on equipped rod
    encounter_rate = get_fishing_encounter_rate(user_rods.get('equipped_rod'))
    
    # Try to encounter a Pokemon
    if random.random() > encounter_rate:
        await message.answer("🎣 You cast your line into the water...\n\nNothing bit! Try again later.")
        return
    
    # Get Pokemon that can be caught with this rod
    available_pokemon = get_pokemon_by_fishing_rod(user_rods.get('equipped_rod'))
    if not available_pokemon:
        rod_type = "Water and Ice-type" if user_rods.get('equipped_rod') == "Crystal Rod" else "Water-type"
        await message.answer(f"No {rod_type} Pokemon found for this fishing rod!")
        return
    
    # Select a random Pokemon from the available pool
    selected_pokemon_data = random.choice(available_pokemon)
    pokemon_id = selected_pokemon_data['id']
    level = generate_random_level(pokemon_id)
    
    # Check if Pokemon should be shiny
    is_shiny = should_pokemon_be_shiny(user_rods.get('equipped_rod'))
    
    # Create Pokemon object and check if already caught concurrently
    wild_pokemon = create_pokemon_from_json(selected_pokemon_data, level, is_shiny)
    already_caught_task = asyncio.create_task(has_pokemon_been_caught(user_id, pokemon_id))
    
    # Set EV yield data for the Pokemon
    wild_pokemon['ev_yield'] = pokemon_utils.get_ev_yield(pokemon_id)
    
    fishing_id = f"{user_id}_{datetime.now().timestamp()}"
    
    active_fishing[user_id] = {
        'pokemon': wild_pokemon,
        'timestamp': datetime.now(),
        'fishing_id': fishing_id,
        'photo_message_id': None,
        'pokeball_message_id': None,
        'equipped_rod': user_rods.get('equipped_rod')
    }
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Catch", callback_data=f"fish_catch_{fishing_id}"),
            InlineKeyboardButton(text="EV Yields", callback_data=f"fish_ev_{fishing_id}")
        ]
    ])
    
    # Wait for the already caught check to complete
    already_caught = await already_caught_task
    
    # Get rod info for display
    rod_info = None
    for rod in FISHING_RODS:
        if rod['name'] == user_rods.get('equipped_rod'):
            rod_info = rod
            break
    
    # Build fishing text with star indicator if already caught and shiny indicator
    fishing_text = f"You hooked a wild "
    if is_shiny:
        fishing_text += f"✨ <b>SHINY {wild_pokemon['name']}</b> ✨"
    else:
        fishing_text += f"<b>{wild_pokemon['name']}</b>"
    
    fishing_text += f" (Lv. {wild_pokemon['level']}) with your {user_rods.get('equipped_rod')}!"
    
    if already_caught:
        fishing_text += " ☆"
    
    # Add special rod effects description
    if user_rods.get('equipped_rod') == "Shiny Rod":
        fishing_text += "\n\n✨ <b>Your Shiny Rod is sparkling with mystical energy!</b>"
    elif user_rods.get('equipped_rod') == "Deep Sea Rod":
        fishing_text += "\n\n🌊 <b>Your Deep Sea Rod pulled this from the ocean depths!</b>"
    elif user_rods.get('equipped_rod') == "Crystal Rod":
        fishing_text += "\n\n❄️ <b>Your Crystal Rod shimmers with icy power!</b>"
    
    # Use cached image instead of FSInputFile
    pokemon_id = wild_pokemon.get('id')
    is_shiny = wild_pokemon.get('is_shiny', False)
    
    if pokemon_id and isinstance(pokemon_id, int):
        photo = get_cached_pokemon_image(pokemon_id, is_shiny)
    else:
        photo = None
    
    if photo:
        photo_msg = await message.reply_photo(
            photo=photo,
            caption=fishing_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        active_fishing[user_id]['photo_message_id'] = photo_msg.message_id
    else:
        photo_msg = await message.reply(
            fishing_text, 
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        active_fishing[user_id]['photo_message_id'] = photo_msg.message_id
    
    await state.set_state(FishingStates.waiting_for_catch)

@router.callback_query(F.data.startswith("fish_ev_"))
async def fish_show_ev_yields(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fishing_id = callback_query.data.replace("fish_ev_", "") if callback_query.data else ""

    fishing = active_fishing.get(user_id)
    if not fishing or fishing.get("fishing_id") != fishing_id:
        await callback_query.answer("This fishing session has expired.", show_alert=True)
        return

    wild_pokemon = fishing["pokemon"]
    ev_yield = wild_pokemon.get("ev_yield", {})
    if not ev_yield:
        text = f"{wild_pokemon['name']} does not grant any EVs."
    else:
        parts = [f"{stat.upper()}: {value}" for stat, value in ev_yield.items()]
        text = f"<b>{wild_pokemon['name']} EV Yield</b>\n" + "\n".join(parts)

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Catch", callback_data=f"fish_catch_{fishing_id}"),
        InlineKeyboardButton(text="EV Yields", callback_data=f"fish_ev_{fishing_id}")
    ]])

    if callback_query.message and hasattr(callback_query.message, 'edit_text'):
        await callback_query.message.edit_caption(text, reply_markup=kb, parse_mode="HTML") if callback_query.message.photo else await callback_query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

    await callback_query.answer()


@router.callback_query(F.data.startswith("fish_catch_"))
async def fish_catch_pokemon(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id if callback_query.from_user else None
    if user_id is None:
        await callback_query.answer("User information not found!", show_alert=True)
        return
    
    # Check if user has claimed starter package
    username = getattr(callback_query.from_user, 'username', '') or ''
    first_name = getattr(callback_query.from_user, 'first_name', '') or ''
    is_valid, result = await check_starter_package(user_id, username, first_name)
    if not is_valid:
        await callback_query.answer(str(result) if isinstance(result, str) else "An error occurred.", show_alert=True)
        return
    
    user = result  # result contains user data if valid
    
    if not callback_query.data:
        await callback_query.answer("Invalid callback data!", show_alert=True)
        return
    callback_data_parts = callback_query.data.split("_")
    if len(callback_data_parts) < 3:
        await callback_query.answer("Invalid callback data!", show_alert=True)
        return
        
    fishing_id = "_".join(callback_data_parts[2:])
    
    if user_id not in active_fishing:
        await callback_query.answer("🐟 The fish got away!", show_alert=True)
        return
    
    current_fishing = active_fishing[user_id]
    if current_fishing['fishing_id'] != fishing_id:
        await callback_query.answer("🐟 The fish got away!", show_alert=True)
        return
    
    current_state = await state.get_state()
    if current_state != FishingStates.waiting_for_catch:
        await callback_query.answer("Invalid fishing state!", show_alert=True)
        return

    # --- Start turn-based battle instead of Pokéball menu ---
    from handlers.wild_battle import start_battle as start_wild_battle  # inline import to avoid circular deps
    await start_wild_battle(callback_query, user_id, current_fishing["pokemon"])
    # Cleanup fishing session; battle logic now controls flow
    active_fishing.pop(user_id, None)
    await state.clear()
    return



@router.message(Command("close"))
async def close_keyboard(message: types.Message):
    # Remove the reply keyboard without sending any text
    await message.answer("Keyboard closed.", reply_markup=types.ReplyKeyboardRemove())