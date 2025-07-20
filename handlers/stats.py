from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import os
import asyncio
from database import get_or_create_user, get_user_pokemon, update_pokemon_moves
from pokemon_utils import PokemonUtils
import difflib
from typing import Optional
from aiogram.types import Message
import json
from handlers.myteam import sync_team_with_collection
from handlers.duel import duels
from image_cache import get_cached_pokemon_image, get_pokemon_image_path as get_cached_pokemon_image_path
from battle_logic import normalize_move_name
from handlers.exp_system import create_exp_bar, get_pokemon_growth_rate, get_exp_for_level

router = Router()
pokemon_utils = PokemonUtils()

# --- Poke.json loader and base stat lookup (cached) ---
def load_pokejson():
    """Load Pokemon data using cached system"""
    from config import get_pokemon_data
    pokemon_data = get_pokemon_data()
    # Convert dict to list if needed for compatibility
    if isinstance(pokemon_data, dict):
        return list(pokemon_data.values()) if pokemon_data else []
    return pokemon_data if pokemon_data else []

def get_base_stats_from_pokejson(pokemon_id):
    data = load_pokejson()
    for entry in data:
        if entry.get('id') == pokemon_id:
            base = entry.get('base_stats', {})
            # Map short keys to display keys
            return {
                'HP': base.get('hp', 0),
                'Attack': base.get('atk', 0),
                'Defense': base.get('def', 0),
                'Sp. Attack': base.get('spa', 0),
                'Sp. Defense': base.get('spd', 0),
                'Speed': base.get('speed', 0)
            }
    # Not found
    return {'HP': 0, 'Attack': 0, 'Defense': 0, 'Sp. Attack': 0, 'Sp. Defense': 0, 'Speed': 0}

# Load damaging moves at module level
with open('damaging_moves.json', 'r', encoding='utf-8') as f:
    DAMAGING_MOVES_DICT = json.load(f)
# Create a set of normalized move names for comparison
DAMAGING_MOVES = set()
for move_name in DAMAGING_MOVES_DICT.keys():
    normalized_name = normalize_move_name(move_name)
    DAMAGING_MOVES.add(normalized_name)

def get_move_name_from_move_object(move):
    """Extract move name from move object, handling both 'move' and 'name' fields"""
    return move.get('name', move.get('move', ''))

class StatsStates(StatesGroup):
    selecting_pokemon = State()
    viewing_stats = State()
    setting_moves = State()

async def check_starter_package(user_id: int, username: str = "", first_name: str = ""):
    """Check if user has claimed their starter package"""
    user = await get_or_create_user(user_id, username, first_name)
    
    if not user:
        return False, "❌ User data not found! Please try again."
    
    if not user.get('already_started', False):
        return False, "❌ You need to claim your starter package first! Use /start command to begin your Pokémon journey."
    
    return True, user

def create_callback_data(base_data: str, user_id: int, pokemon_uuid: str | None = None) -> str:
    """Create callback data with user ID and optional Pokemon UUID for security"""
    if pokemon_uuid:
        return f"{base_data}_{pokemon_uuid}_{user_id}"
    return f"{base_data}_{user_id}"

def verify_callback_user(callback_data: str, user_id: int) -> bool:
    """Verify callback is from the correct user"""
    return callback_data.endswith(f"_{user_id}")

@router.message(Command("show"))
async def stats_command(message: types.Message, state: FSMContext):
    if not message or not message.from_user:
        return
    user_id = message.from_user.id
    
    is_valid, result = await check_starter_package(user_id, message.from_user.username or "", message.from_user.first_name or "")
    if not is_valid:
        await message.reply(str(result), parse_mode="HTML")
        return
    
    user = result
    
    if not message.text:
        await message.reply("❌ Please specify a Pokémon name!\n\nUsage: <code>/stats &lt;pokemon_name&gt;</code>", parse_mode="HTML")
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    
    if not args:
        await message.reply("❌ Please specify a Pokémon name!\n\nUsage: <code>/stats &lt;pokemon_name&gt;</code>", parse_mode="HTML")
        return
    
    pokemon_name = " ".join(args).lower()
    
    user_pokemon = await get_user_pokemon(user_id)
    
    if not user_pokemon:
        await message.reply("❌ You don't have any Pokémon yet! Use <code>/hunt</code> to catch some first.", parse_mode="HTML")
        return
    
    matching_pokemon = []
    for pokemon in user_pokemon:
        if pokemon.get('name', '').lower() == pokemon_name:
            matching_pokemon.append(pokemon)
    
    # --- MEGA EVOLUTION PATCH: Check if this Pokémon is currently Mega Evolved in an active duel ---
    # Only one active duel per user (by user_id as key in duels)
    for duel in duels.values():
        if duel.get('status') == 'active' and user_id in duel.get('users', {}):
            user_state = duel['users'][user_id]
            active_poke = user_state.get('active_poke', {})
            # Try to match by uuid if available, else by name+level
            for idx, poke in enumerate(matching_pokemon):
                if (
                    poke.get('uuid') and active_poke.get('uuid') and poke['uuid'] == active_poke['uuid']
                ) or (
                    not poke.get('uuid') and not active_poke.get('uuid') and poke.get('name', '').lower() == active_poke.get('name', '').lower() and poke.get('level') == active_poke.get('level')
                ):
                    # If Mega Evolved, update the display info to use the mega form
                    if active_poke.get('mega_evolved', False):
                        # Overwrite the matching_pokemon entry with the in-battle mega-evolved state
                        matching_pokemon[idx] = active_poke.copy()
                    break
    
    if not matching_pokemon:
        # Fuzzy match suggestion using user's Pokémon list
        user_names = list({p.get('name', '').title() for p in user_pokemon})
        closest = difflib.get_close_matches(pokemon_name.title(), user_names, n=1, cutoff=0.6)
        if closest:
            suggested = closest[0]
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Yes", callback_data=create_callback_data(f"show_suggested_{suggested}", user_id)),
                        InlineKeyboardButton(text="No", callback_data=create_callback_data(f"show_suggested_no", user_id))
                    ]
                ]
            )
            await message.reply(
                f"❌ You don't have any <b>{pokemon_name.title()}</b> in your collection!\nDid you mean: <b>{suggested}</b>?", 
                reply_markup=keyboard, 
                parse_mode="HTML",
                reply_to_message_id=message.message_id,
                allow_sending_without_reply=True
            )
            return
        else:
            await message.reply(f"❌ You don't have any <b>{pokemon_name.title()}</b> in your collection!", parse_mode="HTML")
            return
    
    if len(matching_pokemon) == 1:
        await show_pokemon_stats(message, matching_pokemon[0], state, page=1, user_id=user_id)
        return
    
    await show_pokemon_selection(message, matching_pokemon, state, user_id)

async def show_pokemon_selection(message: types.Message, pokemon_list: list, state: FSMContext, user_id: int):
    """Show selection menu for multiple Pokemon"""
    if not pokemon_list:
        await message.reply("❌ No Pokémon found!")
        return
    
    pokemon_name = pokemon_list[0]['name']
    
    text = f"🔍 You have **{len(pokemon_list)}** {pokemon_name}:\n\n"
    
    keyboard_rows = []
    current_row = []
    
    for i, pokemon in enumerate(pokemon_list, 1):
        text += f"{i}) **{pokemon['name']}** - Lv.{pokemon['level']}\n"
        # Use UUID if available, otherwise use index in the current selection list
        if pokemon.get('uuid'):
            unique_id = pokemon['uuid']
        else:
            # Use index in the current pokemon_list to ensure uniqueness
            unique_id = f"idx_{i-1}"
        button = InlineKeyboardButton(
            text=str(i),
            callback_data=create_callback_data(f"selectpokemon_{unique_id}", user_id)
        )
        current_row.append(button)
        
        if len(current_row) == 5:
            keyboard_rows.append(current_row)
            current_row = []
    
    if current_row:
        keyboard_rows.append(current_row)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    # Store the pokemon_list in state for index-based lookup
    await state.update_data(selection_pokemon_list=pokemon_list)
    await message.reply(text, reply_markup=keyboard, parse_mode="Markdown")

# Update the callback handler to use UUID or index-based selection
@router.callback_query(F.data.startswith("selectpokemon_"))
async def select_pokemon(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    if not callback_query.data:
        await callback_query.answer("❌ Callback data missing!", show_alert=True)
        return
    if not verify_callback_user(callback_query.data, user_id):
        await callback_query.answer("❌ You can only use your own buttons!", show_alert=True)
        return

    # Extract unique_id from callback_data
    data_parts = callback_query.data.split("_")
    # selectpokemon_{unique_id}_{user_id}
    if len(data_parts) < 3:
        print(f"[DEBUG] Invalid callback data: {callback_query.data}")
        await callback_query.answer("❌ Invalid Pokémon selection!", show_alert=True)
        return
    
    unique_id = data_parts[1]
    selected_pokemon = None
    
    # Check if it's an index-based selection
    if unique_id.startswith("idx_"):
        try:
            idx = int(unique_id.split("_")[1])
            state_data = await state.get_data() or {}
            pokemon_list = state_data.get('selection_pokemon_list', [])
            if 0 <= idx < len(pokemon_list):
                selected_pokemon = pokemon_list[idx]
                print(f"[DEBUG] Matched by index: {idx}")
            else:
                print(f"[DEBUG] Invalid index: {idx}, list length: {len(pokemon_list)}")
        except (ValueError, IndexError):
            print(f"[DEBUG] Failed to parse index: {unique_id}")
            await callback_query.answer("❌ Invalid Pokémon selection!", show_alert=True)
            return
    else:
        # UUID-based selection
        user_pokemon = await get_user_pokemon(user_id)
        print(f"[DEBUG] select_pokemon callback: uuid={unique_id}")
        print(f"[DEBUG] User's Pokémon UUIDs: {[p.get('uuid', 'N/A') for p in user_pokemon]}")
        
        for p in user_pokemon:
            if p.get('uuid') == unique_id:
                selected_pokemon = p
                print(f"[DEBUG] Matched by UUID: {p.get('uuid')}")
                break

    if not selected_pokemon:
        print(f"[DEBUG] No matching Pokémon found for unique_id={unique_id}")
        await callback_query.answer("❌ Pokémon not found! Please check if your Pokémon data is up-to-date.", show_alert=True)
        return

    # Ensure callback_query.message is a valid Message
    from aiogram.types import Message
    if not hasattr(callback_query, 'message') or not isinstance(callback_query.message, Message):
        await callback_query.answer("❌ Message not found!", show_alert=True)
        return

    await show_pokemon_stats(callback_query.message, selected_pokemon, state, page=1, user_id=user_id, edit=True)
    await callback_query.answer()

async def get_pokemon_image_path(pokemon: dict) -> str:
    """Get Pokemon image path using ID, prioritizing shiny if applicable"""
    pokemon_id = pokemon.get('id')
    is_shiny = pokemon.get('is_shiny', False)
    
    if not pokemon_id or not isinstance(pokemon_id, int):
        return ""
    
    # Use cached image path lookup
    # Type assertion since we already checked pokemon_id is not None and is int
    return get_cached_pokemon_image_path(pokemon_id, is_shiny)

async def show_pokemon_stats(message: types.Message, pokemon: dict, state: FSMContext, page: int = 1, user_id: Optional[int] = None, edit: bool = False, moves_page: int = 1):
    """Show Pokemon stats with pagination and moves pagination"""
    # Defensive: ensure user_id and page are int
    if user_id is None or not isinstance(user_id, int):
        print(f"[DEBUG] show_pokemon_stats: Invalid user_id: {user_id}")
        return
    if page is None or not isinstance(page, int):
        print(f"[DEBUG] show_pokemon_stats: Invalid page: {page}")
        return
    if moves_page is None or not isinstance(moves_page, int):
        moves_page = 1
    await state.update_data(current_pokemon=pokemon, current_page=page, original_user_id=user_id, moves_page=moves_page)
    await state.set_state(StatsStates.viewing_stats)
    if page == 1:
        text, keyboard = create_info_page(pokemon, user_id)
    elif page == 2:
        text, keyboard = create_stats_page(pokemon, user_id)
    elif page == 3:
        text, keyboard = create_moves_page(pokemon, user_id, moves_page)
    elif page == 4:
        text, keyboard = create_iv_ev_page(pokemon, user_id)
    else:
        text = "❌ Invalid page!"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    # Use cached image instead of creating FSInputFile directly
    pokemon_id = pokemon.get('id')
    is_shiny = pokemon.get('is_shiny', False)
    
    if pokemon_id and isinstance(pokemon_id, int):
        photo = get_cached_pokemon_image(pokemon_id, is_shiny)
    else:
        photo = None
    
    if edit:
        if photo:
            try:
                await message.edit_media(
                    media=types.InputMediaPhoto(media=photo, caption=text, parse_mode="HTML"),
                    reply_markup=keyboard
                )
            except Exception as e:
                print(f"[DEBUG] Failed to edit media: {e}")
                await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        if photo:
            try:
                await message.reply_photo(photo, caption=text, reply_markup=keyboard, parse_mode="HTML")
            except Exception as e:
                print(f"[DEBUG] Failed to reply with photo: {e}")
                await message.reply(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message.reply(text, reply_markup=keyboard, parse_mode="HTML")

def create_info_page(pokemon: dict, user_id: int) -> tuple:
    """Create info page content with EXP bar."""
    type_emojis = {
        'Normal': '⚪',
        'Fire': '🔥',
        'Water': '💧',
        'Electric': '⚡',
        'Grass': '🌿',
        'Ice': '🧊',
        'Fighting': '🥊',
        'Poison': '☠️',
        'Ground': '🌍',
        'Flying': '🕊️',
        'Psychic': '🔮',
        'Bug': '🐛',
        'Rock': '🪨',
        'Ghost': '👻',
        'Dragon': '🐉',
        'Dark': '🌑',
        'Steel': '⚙️',
        'Fairy': '🧚',
        'Stellar': '✨'
    }

    level = pokemon.get('level', 1)
    nature = pokemon.get('nature', 'N/A').title()
    # Normalize and format types (strip whitespace and capitalize)
    raw_types = pokemon.get('types', []) or []
    types = [t.strip().title() for t in raw_types]
    current_exp = pokemon.get('exp', 0)
    pokemon_id = pokemon.get('id')

    # Shiny prefix
    shiny_prefix = "✨ Shiny " if pokemon.get('is_shiny') else ""

    # Types with emojis
    type_str = " / ".join([f"{t} {type_emojis.get(t, '')}" for t in types])

    # Get growth rate and ensure EXP is at least the minimum for current level
    growth_rate = get_pokemon_growth_rate(pokemon_id)
    min_exp_for_level = get_exp_for_level(level, growth_rate)
    if current_exp < min_exp_for_level:
        current_exp = min_exp_for_level
        pokemon['exp'] = current_exp  # update in-memory object so subsequent pages are consistent

    exp_bar, exp_to_next_lv = create_exp_bar(current_exp, level, growth_rate)

    # Format the final string
    text = (
        f"<b>{shiny_prefix}{pokemon.get('name', 'N/A').title()}</b>\n"
        f"<b>Lv.</b> {level} | <b>Nature:</b> {nature}\n"
        f"<b>Types:</b> [{type_str}]\n"
        f"<b>Exp.</b> {current_exp:,}\n"
        f"<b>To Next Lv.</b> {exp_to_next_lv:,}\n"
        f"<b>EXP</b> <code>{exp_bar}</code>"
    )

    pokemon_uuid = pokemon.get('uuid', '')
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Stats", callback_data=create_callback_data("stats_page_2", user_id, pokemon_uuid)),
            InlineKeyboardButton(text="Moves", callback_data=create_callback_data("stats_page_3", user_id, pokemon_uuid)),
            InlineKeyboardButton(text="IVs/EVs", callback_data=create_callback_data("stats_page_4", user_id, pokemon_uuid))
        ]
    ])

    return text, keyboard


def create_stats_page(pokemon: dict, user_id: int) -> tuple:
    """Create stats page content, always using poke.json for base stats and stat calculation"""
    name = pokemon.get('name', 'Unknown')
    level = pokemon.get('level', 1)
    nature = pokemon.get('nature', 'Unknown')
    is_shiny = pokemon.get('is_shiny', False)
    display_name = f"✨ {name} ✨" if is_shiny else name
    # Use the Pokémon's own base_stats if present, otherwise fall back to poke.json
    poke_id = pokemon.get('id')
    raw_base_stats = pokemon.get('base_stats') or get_base_stats_from_pokejson(poke_id)
    # For display, map to display keys if needed
    if all(k in raw_base_stats for k in ['hp', 'atk', 'def', 'spa', 'spd', 'speed']):
        display_base_stats = {
            'HP': raw_base_stats.get('hp', 0),
            'Attack': raw_base_stats.get('atk', 0),
            'Defense': raw_base_stats.get('def', 0),
            'Sp. Attack': raw_base_stats.get('spa', 0),
            'Sp. Defense': raw_base_stats.get('spd', 0),
            'Speed': raw_base_stats.get('speed', 0)
        }
    else:
        display_base_stats = raw_base_stats
    # Use raw_base_stats for calculation
    ivs = pokemon.get('ivs', {}) or {}
    evs = pokemon.get('evs', {}) or {}
    for stat in ['HP', 'Attack', 'Defense', 'Sp. Attack', 'Sp. Defense', 'Speed']:
        if stat not in ivs:
            ivs[stat] = 0
        if stat not in evs:
            evs[stat] = 0
    calculated_stats = pokemon_utils.calculate_stats(
        {'base_stats': raw_base_stats},
        level,
        ivs,
        evs,
        nature
    )
    nature_data = pokemon_utils.natures.get(nature, {'increase': None, 'decrease': None})
    increased_stat = nature_data.get('increase')
    decreased_stat = nature_data.get('decrease')
    text = ""
    stat_order = ['HP', 'Attack', 'Defense', 'Sp. Attack', 'Sp. Defense', 'Speed']
    stat_emojis = {
        'HP': '❤️',
        'Attack': '⚔️',
        'Defense': '🛡️',
        'Sp. Attack': '✨',
        'Sp. Defense': '🔰',
        'Speed': '🏃'
    }
    # Build simplified current stats list with modifiers
    for stat in stat_order:
        val = calculated_stats.get(stat, 0)
        modifier = ""
        if stat == increased_stat:
            modifier = " (+)"
        elif stat == decreased_stat:
            modifier = " (-)"
        text += f"\n<b>{stat}:</b> {val}{modifier}"
    # Remove leading newline if present
    text = text.lstrip("\n")

    pokemon_uuid = pokemon.get('uuid', '')
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Info", callback_data=create_callback_data("stats_page_1", user_id, pokemon_uuid)),
            InlineKeyboardButton(text="Moves", callback_data=create_callback_data("stats_page_3", user_id, pokemon_uuid)),
            InlineKeyboardButton(text="IVs/EVs", callback_data=create_callback_data("stats_page_4", user_id, pokemon_uuid))
        ]
    ])
    return text, keyboard


def create_moves_page(pokemon: dict, user_id: int, moves_page: int = 1) -> tuple:
    """Create moves page content with pagination (10 moves per page)"""
    name = pokemon.get('name', 'Unknown')
    level = pokemon.get('level', 1)
    is_shiny = pokemon.get('is_shiny', False)
    display_name = f"✨ {name} ✨" if is_shiny else name
    # Filter moves to only damaging moves (normalized)
    moves = [m for m in (pokemon.get('moves', []) or []) if normalize_move_name(get_move_name_from_move_object(m)) in DAMAGING_MOVES]
    active_moves = [m for m in (pokemon.get('active_moves', []) or []) if normalize_move_name(get_move_name_from_move_object(m)) in DAMAGING_MOVES]
    MOVES_PER_PAGE = 10
    type_emojis = {
        'Normal': '🔘',
        'Fire': '🔥',
        'Water': '💧',
        'Electric': '⚡',
        'Grass': '🌱',
        'Ice': '❄',
        'Fighting': '🥊',
        'Poison': '☣',
        'Ground': '🌍',
        'Flying': '🪽',
        'Psychic': '🔮',
        'Bug': '🪲',
        'Rock': '🪨',
        'Ghost': '👁‍🗨',
        'Dragon': '🐉',
        'Dark': '🌑',
        'Steel': '🔩',
        'Fairy': '🧚',
        'Stellar': '✨'
    }
    total_pages = (len(moves) + MOVES_PER_PAGE - 1) // MOVES_PER_PAGE or 1
    moves_page = max(1, min(moves_page, total_pages))
    start_idx = (moves_page - 1) * MOVES_PER_PAGE
    end_idx = start_idx + MOVES_PER_PAGE
    text = f"<b>Available Moves (Page {moves_page}/{total_pages}):</b>\n"
    if not moves:
        text += "\nNo moves available!"
    else:
        for i, move in enumerate(moves[start_idx:end_idx], start=start_idx + 1):
            move_name_raw = get_move_name_from_move_object(move) or 'Unknown'
            move_name = normalize_move_name(move_name_raw)
            move_level = move.get('level_learned_at', 0)
            move_method = move.get('method', 'level-up')
            is_active = any(normalize_move_name(get_move_name_from_move_object(active_move)) == move_name for active_move in (active_moves or []))
            status = " ✅" if is_active else ""
            
            # Add TM indicator for machine-learned moves
            tm_indicator = " [TM]" if move_method == 'machine' else ""
            
            # Lookup move details
            move_info = DAMAGING_MOVES_DICT.get(move_name)
            if move_info:
                move_type = move_info.get('type', '?')
                move_power = move_info.get('power', '?')
                move_accuracy = move_info.get('accuracy', '?')
                move_category = move_info.get('category', '?')
            else:
                move_type = move_power = move_accuracy = move_category = '?'
            emoji = type_emojis.get(move_type, '')
            text += f"\n{i}. <b>{move_name}</b> [{move_type} {emoji}]{tm_indicator}\nPower: {str(move_power).rjust(4)}, Accuracy: {str(move_accuracy).rjust(4)} ({move_category}){status}"
    text += f"\n\n<b>Current Active Moves ({len(active_moves)}/4):</b>"
    if not active_moves:
        text += "\nNone"
    else:
        for move in active_moves:
            move_name = normalize_move_name(get_move_name_from_move_object(move) or 'Unknown')
            text += f"\n• {move_name}"
    # Keyboard with pagination
    pokemon_uuid = pokemon.get('uuid', '')
    nav_buttons = []
    if moves_page > 1:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Prev", callback_data=create_callback_data(f"stats_page_3_{moves_page-1}", user_id, pokemon_uuid)))
    if moves_page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="Next ▶️", callback_data=create_callback_data(f"stats_page_3_{moves_page+1}", user_id, pokemon_uuid)))
    keyboard_rows = []
    if nav_buttons:
        keyboard_rows.append(nav_buttons)
    keyboard_rows.append([InlineKeyboardButton(text="Set Moves", callback_data=create_callback_data("set_moves", user_id, pokemon_uuid))])
    keyboard_rows.append([
        InlineKeyboardButton(text="Info", callback_data=create_callback_data("stats_page_1", user_id, pokemon_uuid)),
        InlineKeyboardButton(text="Stats", callback_data=create_callback_data("stats_page_2", user_id, pokemon_uuid)),
        InlineKeyboardButton(text="IVs/EVs", callback_data=create_callback_data("stats_page_4", user_id, pokemon_uuid))
    ])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    return text, keyboard


def create_iv_ev_page(pokemon: dict, user_id: int) -> tuple:
    """Create IV/EV page content with vertical alignment using <pre> formatting and totals at the end"""
    name = pokemon.get('name', 'Unknown')
    is_shiny = pokemon.get('is_shiny', False)
    display_name = f"✨ {name} ✨" if is_shiny else name
    ivs = pokemon.get('ivs', {}) or {}
    evs = pokemon.get('evs', {}) or {}
    stat_names = [
        ('HP', 'HP'),
        ('Attack', 'Atk'),
        ('Defense', 'Def'),
        ('Sp. Attack', 'SpA'),
        ('Sp. Defense', 'SpD'),
        ('Speed', 'Spe'),
    ]
    # Build aligned IV/EV table
    col1_width = 13  # "Sp. Defense" length
    text_lines = []
    header = f"{'Points':<{col1_width}}  IV |  EV"
    sep = "—" * len(header)
    text_lines.append(header)
    text_lines.append(sep)
    total_iv = total_ev = 0
    for stat_full, _ in stat_names:
        iv = ivs.get(stat_full, 0)
        ev = evs.get(stat_full, 0)
        total_iv += iv
        total_ev += ev
        text_lines.append(f"{stat_full:<{col1_width}} {str(iv).rjust(3)} | {str(ev).rjust(3)}")
    text_lines.append(sep)
    text_lines.append(f"{'Total':<{col1_width}} {str(total_iv).rjust(3)} | {str(total_ev).rjust(3)}")
    text = "<pre>" + "\n".join(text_lines) + "</pre>"
    pokemon_uuid = pokemon.get('uuid', '')
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Info", callback_data=create_callback_data("stats_page_1", user_id, pokemon_uuid)),
            InlineKeyboardButton(text="Stats", callback_data=create_callback_data("stats_page_2", user_id, pokemon_uuid)),
            InlineKeyboardButton(text="Moves", callback_data=create_callback_data("stats_page_3", user_id, pokemon_uuid))
        ]
    ])
    return text, keyboard

@router.callback_query(F.data.startswith("stats_page_"))
async def handle_stats_page(callback_query: CallbackQuery, state: FSMContext):
    # Debug: print callback data if not stats_page_
    if callback_query.data and not callback_query.data.startswith("stats_page_"):
        print(f"[DEBUG][handle_stats_page] Received non-stats_page_ callback: {callback_query.data}")
    user_id = callback_query.from_user.id
    if not callback_query.data:
        await callback_query.answer("❌ Callback data missing!", show_alert=True)
        return
    if not verify_callback_user(callback_query.data, user_id):
        await callback_query.answer("❌ You can only use your own buttons!", show_alert=True)
        return
    is_valid, result = await check_starter_package(
        user_id,
        callback_query.from_user.username or "",
        callback_query.from_user.first_name or ""
    )
    if not is_valid:
        await callback_query.answer(str(result), show_alert=True)
        return
    data_parts = callback_query.data.split("_")
    # New format: stats_page_{page}_{pokemon_uuid}_{user_id} or stats_page_3_{moves_page}_{pokemon_uuid}_{user_id}
    # Old format (fallback): stats_page_{page}_{user_id} or stats_page_3_{moves_page}_{user_id}
    try:
        pokemon_uuid = None
        if len(data_parts) == 6 and data_parts[2] == "3":
            # New format: stats_page_3_{moves_page}_{pokemon_uuid}_{user_id}
            page = 3
            moves_page = int(data_parts[3])
            pokemon_uuid = data_parts[4]
        elif len(data_parts) == 4 and data_parts[2] == "3":
            # Old format: stats_page_3_{moves_page}_{user_id}
            page = 3
            moves_page = int(data_parts[3])
        elif len(data_parts) == 5:
            # New format: stats_page_{page}_{pokemon_uuid}_{user_id}
            page = int(data_parts[2])
            pokemon_uuid = data_parts[3]
            moves_page = 1
        elif len(data_parts) == 3:
            # Old format: stats_page_{page}_{user_id}
            page = int(data_parts[2])
            moves_page = 1
        else:
            # Invalid format
            raise ValueError(f"Invalid callback data format: {len(data_parts)} parts")
    except (IndexError, ValueError):
        await callback_query.answer("❌ Invalid page!", show_alert=True)
        return
    
    # Get Pokemon data by UUID if available, otherwise fall back to state
    pokemon = None
    if pokemon_uuid:
        user_pokemon = await get_user_pokemon(user_id)
        for p in user_pokemon:
            if p.get('uuid') == pokemon_uuid:
                pokemon = p
                break
        if not pokemon:
            await callback_query.answer("❌ Pokemon not found!", show_alert=True)
            return
    else:
        # Fallback to old method using state
        state_data = await state.get_data() or {}
        pokemon = state_data.get('current_pokemon')
        if not pokemon:
            await callback_query.answer("❌ Pokemon data not found!", show_alert=True)
            return
    if not hasattr(callback_query, 'message') or not isinstance(callback_query.message, Message):
        await callback_query.answer("❌ Message not found!", show_alert=True)
        return
    if user_id is None or page is None or not isinstance(user_id, int) or not isinstance(page, int):
        await callback_query.answer("❌ User ID or page missing!", show_alert=True)
        return
    await show_pokemon_stats(callback_query.message, pokemon, state, page=page, user_id=user_id, edit=True, moves_page=moves_page)
    await callback_query.answer()

@router.callback_query(F.data.startswith("set_moves_"))
async def set_moves(callback_query: CallbackQuery, state: FSMContext):
    """Handle move setting"""
    user_id = callback_query.from_user.id
    
    if not callback_query.data:
        await callback_query.answer("❌ Callback data missing!", show_alert=True)
        return
    if not verify_callback_user(callback_query.data, user_id):
        await callback_query.answer("❌ You can only use your own buttons!", show_alert=True)
        return
    is_valid, result = await check_starter_package(user_id, callback_query.from_user.username or "", callback_query.from_user.first_name or "")
    if not is_valid:
        await callback_query.answer(str(result), show_alert=True)
        return
    
    # Extract Pokemon UUID from callback data: set_moves_{pokemon_uuid}_{user_id}
    data_parts = callback_query.data.split("_")
    pokemon_uuid = None
    if len(data_parts) >= 3:
        # New format: set_moves_{pokemon_uuid}_{user_id}
        pokemon_uuid = data_parts[2]
    
    # Get Pokemon data - prioritize state data (contains local modifications) over fresh DB data
    state_data = await state.get_data() or {}
    pokemon = state_data.get('current_pokemon')
    
    # If no state data or UUID mismatch, fall back to fresh DB data
    if not pokemon or (pokemon_uuid and pokemon.get('uuid') != pokemon_uuid):
        if pokemon_uuid:
            user_pokemon = await get_user_pokemon(user_id)
            for p in user_pokemon:
                if p.get('uuid') == pokemon_uuid:
                    pokemon = p
                    break
            if not pokemon:
                await callback_query.answer("❌ Pokemon not found!", show_alert=True)
                return
        else:
            await callback_query.answer("❌ Pokemon data not found!", show_alert=True)
            return
    
    # Only show moves that are allowed (e.g., in DAMAGING_MOVES)
    moves = [m for m in (pokemon.get('moves', []) or []) if normalize_move_name(get_move_name_from_move_object(m)) in DAMAGING_MOVES]
    # Only show active moves that are allowed
    active_moves = [m for m in (pokemon.get('active_moves', []) or []) if normalize_move_name(get_move_name_from_move_object(m)) in DAMAGING_MOVES]
    
    if not moves:
        await callback_query.answer("❌ This Pokémon has no moves to set!", show_alert=True)
        return
    
    text = f"""<b>Set Active Moves for {pokemon.get('name','').title()}:</b>

<b>Available Moves:</b>"""
    
    keyboard_rows = []
    current_row = []
    
    for i, move in enumerate(moves):
        move_name_raw = get_move_name_from_move_object(move) or 'Unknown'
        move_name = normalize_move_name(move_name_raw)
        move_level = move.get('level_learned_at', 0)
        
        is_active = any(normalize_move_name(get_move_name_from_move_object(active_move)) == move_name for active_move in active_moves)
        status = " ✅" if is_active else ""
        
        text += f"\n{i+1}. <b>{move_name}</b> (Lv.{move_level}){status}"
        
        # Create button with number and checkmark if active
        button_text = f"{i+1}"
        if is_active:
            button_text += "✅"
        
        pokemon_uuid = pokemon.get('uuid', '')
        callback_data = create_callback_data(f"toggle_move_{i}", user_id, pokemon_uuid)
        print(f"[DEBUG][set_moves] Move button callback_data: {callback_data}")
        button = InlineKeyboardButton(
            text=button_text,
            callback_data=callback_data
        )
        
        current_row.append(button)
        
        # Add row when it reaches 6 buttons or at the end of moves
        if len(current_row) == 6 or i == len(moves) - 1:
            keyboard_rows.append(current_row)
            current_row = []
    
    # Add control buttons at the bottom
    pokemon_uuid = pokemon.get('uuid', '')
    keyboard_rows.append([
        InlineKeyboardButton(text="💾 Save", callback_data=create_callback_data("save_moves", user_id, pokemon_uuid)),
        InlineKeyboardButton(text="🔙 Back", callback_data=create_callback_data("stats_page_3", user_id, pokemon_uuid))
    ])
    
    text += f"\n\n<b>Current Active Moves ({len(active_moves)}/4):</b>"
    if not active_moves:
        text += "\nNone"
    else:
        for move in active_moves:
            move_name = normalize_move_name(get_move_name_from_move_object(move) or 'Unknown')
            text += f"\n• {move_name}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    # Check if the message has media (photo)
    if not hasattr(callback_query, 'message') or not isinstance(callback_query.message, Message):
        await callback_query.answer("❌ Message not found!", show_alert=True)
        return
    photo = getattr(callback_query.message, 'photo', None)
    if photo:
        # If it has a photo, use edit_media to change the caption
        await callback_query.message.edit_media(
            media=types.InputMediaPhoto(
                media=photo[-1].file_id,
                caption=text,
                parse_mode="HTML"
            ),
            reply_markup=keyboard
        )
    else:
        # If it's text-only, use edit_text
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    await state.set_state(StatsStates.setting_moves)
    await callback_query.answer()

@router.callback_query(F.data.startswith("toggle_move_"))
async def toggle_move(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    if not callback_query.data:
        print("[DEBUG] Callback data missing!")
        await callback_query.answer("❌ Callback data missing!", show_alert=True)
        return
    if not verify_callback_user(callback_query.data, user_id):
        print(f"[DEBUG] Callback user verification failed: {callback_query.data} vs {user_id}")
        await callback_query.answer("❌ You can only use your own buttons!", show_alert=True)
        return
    try:
        print(f"[DEBUG] toggle_move callback_data: {callback_query.data}")
        # Extract move index and Pokemon UUID from callback data: toggle_move_{index}_{pokemon_uuid}_{user_id}
        data_parts = callback_query.data.split("_")
        print(f"[DEBUG] data_parts: {data_parts}")
        if len(data_parts) < 4:
            print("[DEBUG] Invalid callback data format!")
            await callback_query.answer("❌ Invalid callback data format!", show_alert=True)
            return
        try:
            move_index = int(data_parts[2])
        except (ValueError, IndexError):
            print(f"[DEBUG] Invalid move index: {data_parts[2] if len(data_parts) > 2 else 'N/A'}")
            await callback_query.answer("❌ Invalid move index!", show_alert=True)
            return
        # For format: toggle_move_{index}_{pokemon_uuid}_{user_id}
        if len(data_parts) >= 4:
            pokemon_uuid = data_parts[3]
        else:
            pokemon_uuid = None
        print(f"[DEBUG] move_index: {move_index}, pokemon_uuid: {pokemon_uuid}")
        # Get Pokemon data - prioritize state data (contains local modifications) over fresh DB data
        state_data = await state.get_data() or {}
        pokemon = state_data.get('current_pokemon')
        
        # If no state data or UUID mismatch, fall back to fresh DB data
        if not pokemon or (pokemon_uuid and pokemon.get('uuid') != pokemon_uuid):
            if pokemon_uuid:
                user_pokemon = await get_user_pokemon(user_id)
                print(f"[DEBUG] User's Pokémon UUIDs: {[p.get('uuid', 'N/A') for p in user_pokemon]}")
                for p in user_pokemon:
                    if p.get('uuid') == pokemon_uuid:
                        pokemon = p
                        break
                if not pokemon:
                    print(f"[DEBUG] Pokemon not found for UUID: {pokemon_uuid}")
                    await callback_query.answer("❌ Pokemon not found!", show_alert=True)
                    return
            else:
                print("[DEBUG] Pokemon data not found in state!")
                await callback_query.answer("❌ Pokemon data not found!", show_alert=True)
                return
        # Only show moves that are allowed (e.g., in DAMAGING_MOVES)
        moves = [m for m in (pokemon.get('moves', []) or []) if normalize_move_name(get_move_name_from_move_object(m)) in DAMAGING_MOVES]
        print(f"[DEBUG] Available moves: {[normalize_move_name(get_move_name_from_move_object(m)) for m in moves]}")
        if not moves or move_index >= len(moves):
            print(f"[DEBUG] Invalid move selection: move_index={move_index}, moves_len={len(moves)}")
            await callback_query.answer("❌ Invalid move selection!", show_alert=True)
            return
        selected_move = moves[move_index]
        selected_move_name = normalize_move_name(get_move_name_from_move_object(selected_move))
        print(f"[DEBUG] Selected move: {selected_move_name}")
        # --- Always operate on the actual pokemon['active_moves'] list ---
        if 'active_moves' not in pokemon or not isinstance(pokemon['active_moves'], list):
            pokemon['active_moves'] = []
        # Remove any moves from active_moves that are not in DAMAGING_MOVES (cleanup)
        pokemon['active_moves'] = [m for m in (pokemon.get('active_moves', []) or []) if normalize_move_name(get_move_name_from_move_object(m)) in DAMAGING_MOVES]
        print(f"[DEBUG] Active moves before toggle: {[normalize_move_name(get_move_name_from_move_object(m)) for m in pokemon['active_moves']]}")
        is_active = any(normalize_move_name(get_move_name_from_move_object(active_move)) == selected_move_name for active_move in pokemon['active_moves'])
        if is_active:
            # Remove the move
            pokemon['active_moves'] = [move for move in (pokemon['active_moves'] or []) if normalize_move_name(get_move_name_from_move_object(move)) != selected_move_name]
            print(f"[DEBUG] Move {selected_move_name} removed from active moves.")
        else:
            if len(pokemon['active_moves'] or []) >= 4:
                print(f"[DEBUG] Maximum 4 moves can be active. Current: {len(pokemon['active_moves'])}")
                await callback_query.answer("❌ Maximum 4 moves can be active!", show_alert=True)
                return
            pokemon['active_moves'].append(selected_move)
            print(f"[DEBUG] Move {selected_move_name} added to active moves.")
        print(f"[DEBUG] Active moves after toggle: {[normalize_move_name(get_move_name_from_move_object(m)) for m in pokemon['active_moves']]}")
        await state.update_data(current_pokemon=pokemon)
        # Filter moves and active_moves again to ensure only allowed moves are shown
        moves = [m for m in (pokemon.get('moves', []) or []) if normalize_move_name(get_move_name_from_move_object(m)) in DAMAGING_MOVES]
        active_moves = [m for m in (pokemon.get('active_moves', []) or []) if normalize_move_name(get_move_name_from_move_object(m)) in DAMAGING_MOVES]
        text = f"""<b>⚙️ Set Active Moves for {pokemon.get('name','')}</b>\n\n<b>Available Moves:</b>\n\n"""
        keyboard_rows = []
        current_row = []
        for i, move in enumerate(moves):
            move_name_raw = get_move_name_from_move_object(move) or 'Unknown'
            move_name = normalize_move_name(move_name_raw)
            move_level = move.get('level_learned_at', 0)
            is_active = any(normalize_move_name(get_move_name_from_move_object(active_move)) == move_name for active_move in (active_moves or []))
            status = " ✅" if is_active else ""
            text += f"\n{i+1}. <b>{move_name}</b> (Lv.{move_level}){status}"
            button_text = f"{i+1}"
            if is_active:
                button_text += "✅"
            pokemon_uuid = pokemon.get('uuid', '')
            button = InlineKeyboardButton(
                text=button_text,
                callback_data=create_callback_data(f"toggle_move_{i}", user_id, pokemon_uuid)
            )
            current_row.append(button)
            if len(current_row) == 6 or i == len(moves) - 1:
                keyboard_rows.append(current_row)
                current_row = []
        pokemon_uuid = pokemon.get('uuid', '')
        keyboard_rows.append([
            InlineKeyboardButton(text="💾 Save", callback_data=create_callback_data("save_moves", user_id, pokemon_uuid)),
            InlineKeyboardButton(text="🔙 Back", callback_data=create_callback_data("stats_page_3", user_id, pokemon_uuid))
        ])
        text += f"\n\n<b>Current Active Moves ({len(active_moves)}/4):</b>"
        if not active_moves:
            text += "\nNone"
        else:
            for move in active_moves:
                move_name = normalize_move_name(get_move_name_from_move_object(move) or 'Unknown')
                text += f"\n• {move_name}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        if not hasattr(callback_query, 'message') or not isinstance(callback_query.message, Message):
            print("[DEBUG] Message not found on callback_query!")
            await callback_query.answer("❌ Message not found!", show_alert=True)
            return
        photo = getattr(callback_query.message, 'photo', None)
        if photo:
            await callback_query.message.edit_media(
                media=types.InputMediaPhoto(
                    media=photo[-1].file_id,
                    caption=text,
                    parse_mode="HTML"
                ),
                reply_markup=keyboard
            )
        else:
            await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()
    except Exception as e:
        import traceback
        print(f"[ERROR] Exception in toggle_move: {e}\n{traceback.format_exc()}")
        await callback_query.answer("❌ An error occurred while toggling the move!", show_alert=True)

@router.callback_query(F.data.startswith("save_moves_"))
async def save_moves(callback_query: CallbackQuery, state: FSMContext):
    """Save active moves"""
    user_id = callback_query.from_user.id
    
    if not callback_query.data:
        await callback_query.answer("❌ Callback data missing!", show_alert=True)
        return
    if not verify_callback_user(callback_query.data, user_id):
        await callback_query.answer("❌ You can only use your own buttons!", show_alert=True)
        return
    # Extract Pokemon UUID from callback data: save_moves_{pokemon_uuid}_{user_id}
    data_parts = callback_query.data.split("_")
    pokemon_uuid = None
    if len(data_parts) >= 3:
        # New format: save_moves_{pokemon_uuid}_{user_id}
        pokemon_uuid = data_parts[2]
    
    # Get Pokemon data - prioritize state data (contains local modifications) over fresh DB data
    state_data = await state.get_data() or {}
    pokemon = state_data.get('current_pokemon')
    
    # If no state data or UUID mismatch, fall back to fresh DB data
    if not pokemon or (pokemon_uuid and pokemon.get('uuid') != pokemon_uuid):
        if pokemon_uuid:
            user_pokemon = await get_user_pokemon(user_id)
            for p in user_pokemon:
                if p.get('uuid') == pokemon_uuid:
                    pokemon = p
                    break
            if not pokemon:
                await callback_query.answer("❌ Pokemon not found!", show_alert=True)
                return
        else:
            await callback_query.answer("❌ Pokemon data not found!", show_alert=True)
            return
    
    if pokemon.get('id') is None:
        await callback_query.answer("❌ Pokemon data not found!", show_alert=True)
        return
    
    # Only save allowed moves
    active_moves = [m for m in (pokemon.get('active_moves', []) or []) if normalize_move_name(get_move_name_from_move_object(m)) in DAMAGING_MOVES]
    # Save to database using update_pokemon_moves
    poke_id = pokemon.get('id')
    poke_uuid = str(pokemon.get('uuid')) if pokemon and pokemon.get('uuid') is not None else ''
    if poke_id is None:
        await callback_query.answer("❌ Pokemon ID missing!", show_alert=True)
        return
    success = await update_pokemon_moves(int(user_id), poke_id, active_moves, poke_uuid)
    
    if not hasattr(callback_query, 'message') or not isinstance(callback_query.message, Message):
        await callback_query.answer("❌ Message not found!", show_alert=True)
        return
    if success:
        # Ensure team is synced with collection after saving moves
        if callback_query.bot:
            await sync_team_with_collection(user_id, callback_query.bot)
        await callback_query.answer("✅ Moves saved successfully!", show_alert=True)
        await show_pokemon_stats(callback_query.message, pokemon, state, page=3, user_id=user_id, edit=True)
    else:
        await callback_query.answer("❌ Failed to save moves!", show_alert=True)

@router.callback_query(F.data.startswith("show_suggested_"))
async def handle_show_suggested(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    if not callback_query.data:
        await callback_query.answer("❌ Callback data missing!", show_alert=True)
        return
    if not verify_callback_user(callback_query.data, user_id):
        await callback_query.answer("❌ You can only use your own buttons!", show_alert=True)
        return
    if callback_query.data.startswith(f"show_suggested_no"):
        await callback_query.answer("Cancelled.", show_alert=True)
        if hasattr(callback_query, 'message') and isinstance(callback_query.message, Message):
            await callback_query.message.edit_reply_markup(reply_markup=None)
        return
    # Extract suggested name
    try:
        suggested_name = callback_query.data.split("show_suggested_")[1].rsplit("_", 1)[0]
    except Exception:
        await callback_query.answer("❌ Invalid suggestion!", show_alert=True)
        return
    user_pokemon = await get_user_pokemon(user_id)
    matching_pokemon = [p for p in user_pokemon if p.get('name', '').lower() == suggested_name.lower()]
    if not matching_pokemon:
        await callback_query.answer("You don't have this Pokémon!", show_alert=True)
        return
    if not hasattr(callback_query, 'message') or not isinstance(callback_query.message, Message):
        await callback_query.answer("❌ Message not found!", show_alert=True)
        return
    if user_id is None or not matching_pokemon or not isinstance(user_id, int):
        await callback_query.answer("❌ User ID or Pokémon missing!", show_alert=True)
        return
    await show_pokemon_stats(callback_query.message, matching_pokemon[0], state, page=1, user_id=user_id, edit=True)
    await callback_query.answer()