from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InaccessibleMessage, InputMediaPhoto, FSInputFile
from database import get_or_create_user, update_user_pokemon_collection, get_user_z_crystals, get_user_pokerating, update_user_pokerating
from elo import calculate_elo_change
from preferences import get_user_preferences, update_user_preferences
from handlers.myteam import TEAM_SIZE, sync_team_with_collection
from aiogram.utils.deep_linking import create_start_link
from aiogram.utils.markdown import hbold
from typing import Dict, Any
import asyncio
import time
from battle_logic import get_turn_order, check_faint, apply_move
import copy
import json
import os
from assets.functions import pbar, calculate_total_stat, calculate_total_hp
from pokemon_utils import PokemonUtils
from image_cache import get_cached_mega_image, get_cached_image, get_cached_arceus_form_image

DEMO_ALL_MOVES_MISS = False  # Set to False to allow normal move accuracy
BUTTON_COOLDOWN = 4  # 4 seconds cooldown before buttons become clickable
TURN_TIMEOUT = 90  # 90 seconds timeout for each turn
FORFEIT_PENALTY = 100  # 100 💵 penalty for forfeit
DUEL_EXPIRY_TIME = 120  # 2 minutes in seconds before a duel expires

router = Router()

# In-memory duel state (for demo; use persistent storage for production)
duels: Dict[str, Dict[str, Any]] = {}

# Store last action time for each duel to prevent spamming
duel_last_action: Dict[str, float] = {}

# Track active battles per user to prevent multiple battles
active_battles: Dict[int, int] = {}  # user_id -> duel_id

# Store timeout tasks for each duel
timeout_tasks: Dict[int, asyncio.Task] = {}

# Global bot instance for timeout handling
bot_instance = None

def set_bot_instance(bot):
    """Set the global bot instance for timeout handling"""
    global bot_instance
    bot_instance = bot

def extract_duel_id_from_callback(callback_data: str) -> str:
    """Extract duel ID from callback data by finding the last underscore-separated part that matches duel ID format"""
    if not callback_data:
        raise ValueError("Empty callback data")
    
    # Known callback patterns and their prefixes
    prefixes = [
        "duel_accept_", "duel_decline_", "duel_settings_", "duel_toggle_random_",
        "duel_save_settings_", "duel_settings_back_", "duel_min_level_select_",
        "duel_min_level_page2_", "duel_min_level_page3_", "duel_min_level_page4_",
        "duel_set_min_level_", "duel_min_legendary_", "duel_max_legendary_",
        "duel_set_min_legendary_", "duel_set_max_legendary_"
    ]
    
    # Try to match against known prefixes
    for prefix in prefixes:
        if callback_data.startswith(prefix):
            return callback_data[len(prefix):]
    
    # Fallback: if it starts with "duel_" but doesn't match known patterns,
    # assume it's a new pattern and extract everything after the last known prefix
    if callback_data.startswith("duel_"):
        # For patterns like "duel_something_<duel_id>", extract the duel_id part
        # The duel_id format is: chat_id_message_id_timestamp
        parts = callback_data.split('_')
        if len(parts) >= 4:  # At least "duel", "action", and 2+ parts of duel_id
            # Try to find where the duel_id starts (should be negative chat_id)
            for i in range(1, len(parts)):
                try:
                    # If this part starts with a negative number, it's likely the chat_id
                    if parts[i].startswith('-') or parts[i].isdigit():
                        # Reconstruct duel_id from this point
                        return '_'.join(parts[i:])
                except:
                    continue
    
    # If all else fails, use the old method as fallback
    return callback_data.split('_')[-1]

# Plate to type mapping for Arceus transformation
PLATE_TO_TYPE = {
    # Hyphenated format (display names)
    'flame-plate': 'Fire',
    'splash-plate': 'Water', 
    'zap-plate': 'Electric',
    'meadow-plate': 'Grass',
    'icicle-plate': 'Ice',
    'fist-plate': 'Fighting',
    'toxic-plate': 'Poison',
    'earth-plate': 'Ground',
    'sky-plate': 'Flying',
    'mind-plate': 'Psychic',
    'insect-plate': 'Bug',
    'stone-plate': 'Rock',
    'spooky-plate': 'Ghost',
    'draco-plate': 'Dragon',
    'dread-plate': 'Dark',
    'iron-plate': 'Steel',
    'pixie-plate': 'Fairy',
    # File name format (no hyphens) - actual stored names
    'flameplate': 'Fire',
    'splashplate': 'Water',
    'zapplate': 'Electric',
    'meadowplate': 'Grass',
    'icicleplate': 'Ice',
    'fistplate': 'Fighting',
    'toxicplate': 'Poison',
    'earthplate': 'Ground',
    'skyplate': 'Flying',
    'mindplate': 'Psychic',
    'insectplate': 'Bug',
    'stoneplate': 'Rock',
    'spookyplate': 'Ghost',
    'dracoplate': 'Dragon',
    'dreadplate': 'Dark',
    'ironplate': 'Steel',
    'pixieplate': 'Fairy'
}

# --- Load poke.json and move_info.json once ---
POKE_JSON_PATH = os.path.join(os.path.dirname(__file__), '..', 'poke.json')
MOVE_INFO_JSON_PATH = os.path.join(os.path.dirname(__file__), '..', 'move_info.json')

def load_poke_data():
    with open(POKE_JSON_PATH, encoding='utf-8') as f:
        return json.load(f)

def load_move_info():
    with open(MOVE_INFO_JSON_PATH, encoding='utf-8') as f:
        return json.load(f)

POKE_DATA = load_poke_data()
MOVE_INFO = load_move_info()

def heal_team_to_full(team):
    for poke in team:
        # Use calculated HP if available, otherwise fall back to max_hp, then base HP
        calculated_hp = poke.get("calculated_stats", {}).get("HP")
        if calculated_hp:
            max_hp = calculated_hp
        else:
            max_hp = poke.get("max_hp") or poke.get("stats", {}).get("hp", 1)
        
        poke["hp"] = max_hp
        poke["max_hp"] = max_hp
        # Optionally reset status, etc.
    return team

# --- Utility functions ---
def get_poke_info(name, poke_obj=None):
    name = name.lower()
    
    # Special handling for Arceus - check for plate transformation
    if name == 'arceus' and poke_obj:
        # Check if this is a transformed Arceus with types field
        if 'types' in poke_obj and poke_obj['types']:
            return {'name': name, 'types': poke_obj['types']}
        
        # Check if Arceus has any held plates to determine initial type
        # This is for display purposes in battle - actual transformation happens via plate usage
        # For now, we'll show base Normal type until a plate is used
        pass
    
    # If poke_obj is provided and has 'types', use those (for mega forms)
    if poke_obj and 'types' in poke_obj and poke_obj['types']:
        return {'name': name, 'types': poke_obj['types']}
    for poke in POKE_DATA:
        if poke['name'] == name:
            return poke
    return None

def get_move_info(move_name):
    # Normalize move name for lookup
    norm_name = PokemonUtils.normalize_move_name(move_name)
    if norm_name in MOVE_INFO:
        return MOVE_INFO[norm_name]
    
    # Try fallback variants for extra robustness
    name_variants = [
        move_name,
        move_name.title(),
        move_name.lower(),
        move_name.replace('-', ' '),
        move_name.replace(' ', '-'),
        move_name.replace('_', ' '),
        move_name.replace('_', '-'),
        norm_name,
        # Convert from "quick-attack" to "Quick Attack" format
        move_name.replace('-', ' ').title(),
        # Convert from "Quick Attack" to "quick-attack" format
        move_name.lower().replace(' ', '-')
    ]
    for name in name_variants:
        if name in MOVE_INFO:
            return MOVE_INFO[name]
    return None

# --- Formatting helpers ---
def format_poke_line(poke, is_opponent=False):
    # Use types from poke if present (for mega forms), else fallback to get_poke_info
    info = get_poke_info(poke['name'], poke_obj=poke)
    if not info:
        return poke['name'].title()
    types = info.get('types', [])
    type_str = '/'.join([t.title() for t in types])
    level = poke.get('level', poke.get('lvl', 1))
    hp = poke.get('hp', poke.get('calculated_stats', {}).get('HP') or poke.get('stats', {}).get('hp', 1))
    max_hp = poke.get('max_hp', poke.get('calculated_stats', {}).get('HP') or poke.get('stats', {}).get('hp', hp))
    bar = pbar(int(hp / max_hp * 100) if max_hp else 0)
    if is_opponent:
        return f"Opponent's {poke['name'].title()} [{type_str}]\nLv. {level}  •  HP {hp}/{max_hp}\n<code>{bar}</code>"
    else:
        return f"{poke['name'].title()} [{type_str}]\nLv. {level}  •  HP {hp}/{max_hp}\n<code>{bar}</code>"

def format_move_details(move):
    name = move.get('name', move.get('move', '')).title()
    info = get_move_info(move.get('name', move.get('move', '')))
    if not info:
        return f"<b>{name}</b>\nType: ?, <i>Power: ?, Accuracy: ?</i>"
    
    # Check if the move has been transformed (e.g., Judgment with plate)
    move_type = move.get('type', info['type'])
    if isinstance(move_type, str):
        move_type = move_type.capitalize()
    
    return f"<b>{info['name']}</b> [{move_type}]\n<i>Power: {str(info.get('power', '-')).rjust(4)},     Accuracy: {str(info.get('accuracy', '-')).rjust(4)}</i>"

def format_move_list(moves):
    return '\n'.join([format_move_details(m) for m in moves])

def format_zmove_details(zmove_info, zmoves_data):
    """Format Z-move details for display"""
    move_type = zmove_info['type']
    base_move_info = zmove_info['move_info']
    base_power = base_move_info.get('power', 0)
    
    # Find the Z-Move data for this type
    zmove_data = None
    for zmove in zmoves_data:
        if zmove['type'] == move_type:
            zmove_data = zmove
            break
    
    if not zmove_data:
        return f"<b>Unknown Z-Move</b> [{move_type.title()}]\n<i>Power: ?, Accuracy: ?</i>"
    
    # Calculate Z-Move power using power_by_base mapping
    zmove_power = 100  # Default power
    power_by_base = zmove_data.get('power_by_base', {})
    
    # Sort ranges to ensure we check from highest to lowest for proper matching
    sorted_ranges = []
    for power_range, z_power in power_by_base.items():
        if power_range.endswith('+'):
            # Handle "141+" style ranges
            min_power = int(power_range[:-1])
            sorted_ranges.append((min_power, float('inf'), z_power, power_range))
        elif '-' in power_range:
            # Handle "76-100" style ranges
            min_power, max_power = power_range.split('-')
            sorted_ranges.append((int(min_power), int(max_power), z_power, power_range))
        else:
            # Handle exact match ranges
            exact_power = int(power_range)
            sorted_ranges.append((exact_power, exact_power, z_power, power_range))
    
    # Sort by minimum power (descending) to check highest ranges first
    sorted_ranges.sort(key=lambda x: x[0], reverse=True)
    
    for min_power, max_power, z_power, power_range in sorted_ranges:
        if min_power <= base_power <= max_power:
            zmove_power = z_power
            break
    
    # Format Z-move name properly
    zmove_name = zmove_data['move'].replace('-', ' ').title()
    
    return f"<b>{zmove_name}</b> [{move_type.title()}]\n<i>Power: {str(zmove_power).rjust(4)},     Accuracy: {str(100).rjust(4)}</i>"

def format_zmove_list(available_zmoves, zmoves_data):
    """Format list of available Z-moves"""
    return '\n'.join([format_zmove_details(zmove_info, zmoves_data) for zmove_info in available_zmoves])

# --- Build Z-move selection message ---
def build_zmove_selection_message(user_state, opp_state, turn_user_id, available_zmoves, zmoves_data):
    """Build the Z-move selection interface message"""
    # Top: Opponent's Pokémon
    opp_poke = opp_state['active_poke']
    user_poke = user_state['active_poke']
    msg = []
    
    msg.append(format_poke_line(opp_poke, is_opponent=True))
    msg.append('')
    # Current turn
    current_user_name = user_state['user'].get('first_name', 'Player')
    msg.append(f"Current turn: {current_user_name}")
    msg.append(format_poke_line(user_poke, is_opponent=False))
    
    # Show switches remaining for current user
    switches_remaining = user_state.get('switches_remaining', 10)
    msg.append('')
    msg.append(f"Switches remaining for {current_user_name}: {switches_remaining}")
    
    # Z-move list
    msg.append('')
    msg.append(format_zmove_list(available_zmoves, zmoves_data))
    
    # Z-move selection prompt
    msg.append('')
    msg.append('Which z move you want to use:')
    return '\n'.join(msg)

# --- Refactor battle message UI ---
def build_battle_message(user_state, opp_state, turn_user_id, battle_text=None, choose_switch=False):
    # Top: Opponent's Pokémon
    opp_poke = opp_state['active_poke']
    user_poke = user_state['active_poke']
    msg = []
    
    # Battle log first (always if present)
    if battle_text:
        msg.append(battle_text)
        msg.append('')
    
    msg.append(format_poke_line(opp_poke, is_opponent=True))
    msg.append('')
    # Current turn
    current_user_name = user_state['user'].get('first_name', 'Player')
    msg.append(f"Current turn: {current_user_name}")
    msg.append(format_poke_line(user_poke, is_opponent=False))
    
    # Show switches remaining for current user
    switches_remaining = user_state.get('switches_remaining', 10)
    msg.append('')
    msg.append(f"<b>Switches remaining for {current_user_name}: </b>{switches_remaining}")
    
    # Move list (if not switching)
    if not choose_switch:
        msg.append('')
        msg.append(format_move_list(user_poke.get('active_moves', [])))
    
    # Switch prompt
    if choose_switch:
        msg.append('')
        msg.append('Choose your next pokemon.')
    return '\n'.join(msg)

# Helper: Check if user has at least 1 Pokémon with at least 1 move with PP > 0
def has_usable_pokemon(user):
    team = user.get("team", [])
    for poke in team:
        # Ensure Pokemon has the necessary fields
        if not poke.get("active_moves"):
            poke["active_moves"] = []
        if not poke.get("moves"):
            poke["moves"] = []
        
        active_moves = poke.get("active_moves", [])
        # If no active moves, check if Pokemon has any moves at all
        if not active_moves and poke.get("moves"):
            # Auto-assign first 4 moves as active moves
            poke["active_moves"] = poke["moves"][:4]
            active_moves = poke["active_moves"]
        
        if active_moves:  # Only Pokémon with at least one active move are usable
            return True
    return False

# Helper: Get first usable Pokémon (with at least 1 active move)
def get_first_usable_pokemon(user):
    team = user.get("team", [])
    for poke in team:
        # Ensure Pokemon has the necessary fields
        if not poke.get("active_moves"):
            poke["active_moves"] = []
        if not poke.get("moves"):
            poke["moves"] = []
        
        active_moves = poke.get("active_moves", [])
        # If no active moves, check if Pokemon has any moves at all
        if not active_moves and poke.get("moves"):
            # Auto-assign first 4 moves as active moves
            poke["active_moves"] = poke["moves"][:4]
            active_moves = poke["active_moves"]
        
        if active_moves:
            poke_copy = copy.deepcopy(poke)
            print(f"[DEBUG] get_first_usable_pokemon: {poke_copy.get('name', 'Unknown')} has {len(active_moves)} active moves before processing")
            poke_copy["active_moves"] = get_battle_moves(poke_copy)
            print(f"[DEBUG] get_first_usable_pokemon: After get_battle_moves, {poke_copy.get('name', 'Unknown')} has {len(poke_copy.get('active_moves', []))} battle-ready moves")
            # Always use the current HP from the team, not just base stat or 1
            if "hp" not in poke_copy or poke_copy["hp"] is None:
                poke_copy["hp"] = poke.get("hp", poke_copy.get("max_hp") or poke_copy.get("calculated_stats", {}).get("HP") or poke_copy.get("stats", {}).get("hp", 1))
            if "max_hp" not in poke_copy or poke_copy["max_hp"] is None:
                # Use calculated HP if available, otherwise fall back to max_hp, then base HP
                calculated_hp = poke_copy.get("calculated_stats", {}).get("HP")
                if calculated_hp:
                    poke_copy["max_hp"] = calculated_hp
                else:
                    poke_copy["max_hp"] = poke_copy.get("max_hp") or poke_copy.get("stats", {}).get("hp", poke_copy.get("hp", 1))
            print(f"[DEBUG] get_first_usable_pokemon: {poke_copy['name']} HP={poke_copy['hp']} / {poke_copy['max_hp']}")
            return poke_copy
    return None

# Helper: Get all usable Pokémon (not fainted, with at least 1 active move)
def get_usable_pokemon_list(user):
    team = user.get("team", [])
    usable = []
    for poke in team:
        # Ensure Pokemon has the necessary fields
        if not poke.get("active_moves"):
            poke["active_moves"] = []
        if not poke.get("moves"):
            poke["moves"] = []
        
        hp = poke.get("hp")
        if hp is None:
            # Use calculated HP if available, otherwise fall back to max_hp, then base HP
            calculated_hp = poke.get("calculated_stats", {}).get("HP")
            if calculated_hp:
                hp = calculated_hp
            else:
                hp = poke.get("max_hp") or poke.get("stats", {}).get("hp", 1)
        
        active_moves = poke.get("active_moves", [])
        # If no active moves, check if Pokemon has any moves at all
        if not active_moves and poke.get("moves"):
            # Auto-assign first 4 moves as active moves
            poke["active_moves"] = poke["moves"][:4]
            active_moves = poke["active_moves"]
        
        if active_moves and hp > 0:
            usable.append(poke)
    return usable

# Helper: Build move/switch/give up buttons for a user
def build_battle_keyboard(user, can_switch=True):
    poke = user["active_poke"]
    # Ensure active_moves is always set from moves if missing or empty
    if not poke.get("active_moves"):
        moves = poke.get("moves", [])
        processed_moves = []
        for move in moves:
            if isinstance(move, str):
                processed_moves.append({"name": move.lower()})
            elif isinstance(move, dict):
                name = move.get('name') or move.get('move')
                if name:
                    move['name'] = name.lower()
                processed_moves.append(move)
        poke["active_moves"] = processed_moves
    # Only use active_moves for battle
    moves = poke.get("active_moves", [])
    move_buttons = []
    row = []
    
    print(f"[DEBUG] build_battle_keyboard: {poke.get('name', 'Unknown')} has {len(moves)} moves available")
    
    for idx, move in enumerate(moves):
        move_name = move.get('name') or move.get('move')
        if not move_name:
            continue  # Skip moves without a name
        
        print(f"[DEBUG] Adding move button {idx + 1}: '{move_name}'")
        row.append(InlineKeyboardButton(text=f"{move_name.title()}", callback_data=f"duel_move_{idx}"))
        
        # Create rows of 2 moves each
        if len(row) == 2:
            move_buttons.append(row)
            row = []
    
    # Add any remaining moves in the last row
    if row:
        move_buttons.append(row)
    keyboard = move_buttons
    # --- MEGA EVOLUTION BUTTON LOGIC ---
    # Only show if not already mega evolved
    if not poke.get('mega_evolved', False):
        user_data = user.get('user', {})
        has_bracelet = user_data.get('has_mega_bracelet', False)
        mega_stones = user_data.get('mega_stones', [])
        # Map base Pokémon to possible mega forms and required stone(s)
        mega_map = {
            'venusaur': ('Venusaur Mega', 'venusaurite'),
            'charizard': [('Charizard Mega X', 'charizarditex'), ('Charizard Mega Y', 'charizarditey')],
            'blastoise': ('Blastoise Mega', 'blastoisinite'),
            'alakazam': ('Alakazam Mega', 'alakazite'),
            'gengar': ('Gengar Mega', 'gengarite'),
            'kangaskhan': ('Kangaskhan Mega', 'kangaskhanite'),
            'pinsir': ('Pinsir Mega', 'pinsirite'),
            'gyarados': ('Gyarados Mega', 'gyaradosite'),
            'aerodactyl': ('Aerodactyl Mega', 'aerodactylite'),
            'mewtwo': [('Mewtwo Mega X', 'mewtwonitex'), ('Mewtwo Mega Y', 'mewtwonitey')],
            'ampharos': ('Ampharos Mega', 'ampharosite'),
            'scizor': ('Scizor Mega', 'scizorite'),
            'heracross': ('Heracross Mega', 'heracronite'),
            'houndoom': ('Houndoom Mega', 'houndoominite'),
            'tyranitar': ('Tyranitar Mega', 'tyranitarite'),
            'blaziken': ('Blaziken Mega', 'blazikenite'),
            'gardevoir': ('Gardevoir Mega', 'gardevoirite'),
            'mawile': ('Mawile Mega', 'mawilite'),
            'aggron': ('Aggron Mega', 'aggronite'),
            'medicham': ('Medicham Mega', 'medichamite'),
            'manectric': ('Manectric Mega', 'manectite'),
            'banette': ('Banette Mega', 'banettite'),
            'absol': ('Absol Mega', 'absolite'),
            'garchomp': ('Garchomp Mega', 'garchompite'),
            'lucario': ('Lucario Mega', 'lucarionite'),
            'abomasnow': ('Abomasnow Mega', 'abomasite'),
            'beedrill': ('Beedrill Mega', 'beedrillite'),
            'pidgeot': ('Pidgeot Mega', 'pidgeotite'),
            'slowbro': ('Slowbro Mega', 'slowbronite'),
            'steelix': ('Steelix Mega', 'steelixite'),
            'sceptile': ('Sceptile Mega', 'sceptilite'),
            'swampert': ('Swampert Mega', 'swampertite'),
            'sableye': ('Sableye Mega', 'sablenite'),
            'sharpedo': ('Sharpedo Mega', 'sharpedonite'),
            'camerupt': ('Camerupt Mega', 'cameruptite'),
            'altaria': ('Altaria Mega', 'altarianite'),
            'glalie': ('Glalie Mega', 'glalitite'),
            'salamence': ('Salamence Mega', 'salamencite'),
            'metagross': ('Metagross Mega', 'metagrossite'),
            'latias': ('Latias Mega', 'latiasite'),
            'latios': ('Latios Mega', 'latiosite'),
            'lopunny': ('Lopunny Mega', 'lopunnite'),
            'gallade': ('Gallade Mega', 'galladite'),
            'audino': ('Audino Mega', 'audinite'),
            'diancie': ('Diancie Mega', 'diancite'),
        }
        base_name = poke['name'].lower().replace(' ', '').replace('-', '')
        # Find mega form and stone
        mega_options = mega_map.get(base_name)
        if mega_options:
            if isinstance(mega_options, list):
                for mega_form, stone in mega_options:
                    if stone in mega_stones and has_bracelet:
                        # Create display name for the stone
                        stone_display_name = stone.replace('_', ' ').title()
                        # Special cases for better display names
                        if stone == 'black_core':
                            stone_display_name = 'Black Core'
                        elif stone == 'white_core':
                            stone_display_name = 'White Core'
                        elif stone == 'charizarditex':
                            stone_display_name = 'Charizardite X'
                        elif stone == 'charizarditey':
                            stone_display_name = 'Charizardite Y'
                        elif stone == 'mewtwonitex':
                            stone_display_name = 'Mewtwonite X'
                        elif stone == 'mewtwonitey':
                            stone_display_name = 'Mewtwonite Y'
                        
                        keyboard.append([InlineKeyboardButton(text=f"Use {stone_display_name}", callback_data=f"duel_megastone_{mega_form.replace(' ', '_')}")])
            else:
                mega_form, stone = mega_options
                if stone in mega_stones and has_bracelet:
                    # Create display name for the stone
                    stone_display_name = stone.replace('_', ' ').title()
                    # Special cases for better display names
                    if stone == 'black_core':
                        stone_display_name = 'Black Core'
                    elif stone == 'white_core':
                        stone_display_name = 'White Core'
                    elif stone == 'charizarditex':
                        stone_display_name = 'Charizardite X'
                    elif stone == 'charizarditey':
                        stone_display_name = 'Charizardite Y'
                    elif stone == 'mewtwonitex':
                        stone_display_name = 'Mewtwonite X'
                    elif stone == 'mewtwonitey':
                        stone_display_name = 'Mewtwonite Y'
                    
                    keyboard.append([InlineKeyboardButton(text=f"Use {stone_display_name}", callback_data=f"duel_megastone_{mega_form.replace(' ', '_')}")])
    
    # --- PLATES BUTTON LOGIC ---
    # Only show if Arceus is active and user has plates and hasn't used a plate this battle
    if poke['name'].lower() == 'arceus' and not user.get('has_used_plate', False):
        # Check if user has plates by looking at the user data
        user_data = user.get('user', {})
        user_plates = user_data.get('plates', [])
        if user_plates:
            keyboard.append([InlineKeyboardButton(text="Use Plates", callback_data="duel_plates")])
    
    # --- Z-MOVE BUTTON LOGIC ---
    # Only show if user has z-ring, hasn't used z-move this battle, and has compatible z-crystals
    if not user.get('has_used_zmove', False):
        user_data = user.get('user', {})
        has_z_ring = user_data.get('has_z_ring', False)
        z_crystals = user_data.get('z_crystals', [])
        
        if has_z_ring and z_crystals:
            # Check if current pokemon has moves that can be Z-Moves
            poke_types = poke.get('types', poke.get('type', ['normal']))
            if isinstance(poke_types, str):
                poke_types = [poke_types]
            poke_types = [t.lower() for t in poke_types]
            
            # Special case for Arceus: it can use Z-moves of any type it can transform into
            if poke.get('name', '').lower() == 'arceus':
                # For Arceus, check all possible types it can transform into, not just current type
                all_possible_types = ['normal', 'fighting', 'flying', 'poison', 'ground', 'rock',
                                    'bug', 'ghost', 'steel', 'fire', 'water', 'grass', 
                                    'electric', 'psychic', 'ice', 'dragon', 'dark', 'fairy']
                poke_types.extend([t for t in all_possible_types if t not in poke_types])
            
            # Check if user has z-crystals for any of the pokemon's types
            has_compatible_crystal = False
            for poke_type in poke_types:
                # Map pokemon types to z-crystal names
                type_to_crystal = {
                    'normal': 'normaliumz', 'fighting': 'fightiniumz', 'flying': 'flyiniumz',
                    'poison': 'poisoniumz', 'ground': 'groundiumz', 'rock': 'rockiumz',
                    'bug': 'buginiumz', 'ghost': 'ghostiumz', 'steel': 'steeliumz',
                    'fire': 'firiumz', 'water': 'wateriumz', 'grass': 'grassiumz',
                    'electric': 'electriumz', 'psychic': 'psychiumz', 'ice': 'iciumz',
                    'dragon': 'dragoniumz', 'dark': 'darkiniumz', 'fairy': 'fairiumz'
                }
                crystal_name = type_to_crystal.get(poke_type)
                if crystal_name and crystal_name in z_crystals:
                    has_compatible_crystal = True
                    break
            
            if has_compatible_crystal:
                keyboard.append([InlineKeyboardButton(text="Use Z-Move", callback_data="duel_zmove")])
    
    # Last row: [Switch] [Run] [Give Up]
    last_row = []
    if can_switch:
        last_row.append(InlineKeyboardButton(text="Switch", callback_data="duel_switch"))
    last_row.append(InlineKeyboardButton(text="Run", callback_data="duel_run"))
    last_row.append(InlineKeyboardButton(text="Give Up", callback_data="duel_giveup"))
    keyboard.append(last_row)
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# Helper: Get battle moves (active_moves only)
def get_battle_moves(poke):
    # Load damaging moves database for filtering
    with open(os.path.join(os.path.dirname(__file__), '..', 'damaging_moves.json'), encoding='utf-8') as f:
        damaging_moves_db = json.load(f)
    
    # Only use 'active_moves' for battle
    moves = poke.get("active_moves", [])
    processed_moves = []
    
    print(f"[DEBUG] get_battle_moves for {poke.get('name', 'Unknown')}: Found {len(moves)} active moves")
    
    for move in moves:
        if isinstance(move, str):
            processed_moves.append({"name": move.lower()})
        elif isinstance(move, dict):
            name = move.get('name') or move.get('move')
            if name:
                move['name'] = name.lower()
            processed_moves.append(move)
    
    # Filter to only include moves that exist in the damaging moves database
    battle_ready_moves = []
    
    for move in processed_moves:
        move_name = move.get('name', '')
        original_move_name = move_name
        
        print(f"[DEBUG] Checking move: '{move_name}'")
        
        # Try various normalization approaches to find the move
        move_found = False
        
        # Create normalized versions for comparison
        move_name_normalized = move_name.lower().strip()
        move_name_no_spaces = move_name_normalized.replace(' ', '').replace('-', '').replace('_', '')
        
        for key in damaging_moves_db.keys():
            key_normalized = key.lower().strip()
            key_no_spaces = key_normalized.replace(' ', '').replace('-', '').replace('_', '')
            
            # Try multiple matching strategies
            if (move_name_normalized == key_normalized or
                move_name_no_spaces == key_no_spaces or
                move_name_normalized.replace(' ', '-') == key_normalized.replace(' ', '-') or
                move_name_normalized.replace('-', ' ') == key_normalized.replace('-', ' ') or
                move_name_normalized.replace('_', '-') == key_normalized.replace('_', '-')):
                
                # Add move power for sorting
                move_with_power = move.copy()
                power_value = damaging_moves_db[key].get('power', 0)
                # Handle None power values by converting them to 0
                move_with_power['power'] = power_value if power_value is not None else 0
                move_with_power['db_key'] = key  # Store the database key for reference
                move_with_power['name'] = key  # Use the correct name from database
                battle_ready_moves.append(move_with_power)
                move_found = True
                print(f"[DEBUG] ✅ Found damaging move: '{move_name}' -> '{key}' (Power: {damaging_moves_db[key].get('power', 0)})")
                break
        
        if not move_found:
            print(f"[DEBUG] ❌ Move '{original_move_name}' not found in damaging moves database")
            # Only log if it's a potentially missing damaging move
            if any(keyword in move_name.lower() for keyword in ['beam', 'blast', 'cannon', 'strike', 'punch', 'kick', 'attack', 'slam', 'tackle']):
                print(f"[DEBUG] Potentially missing damaging move: '{move_name}'")
    
    print(f"[DEBUG] Found {len(battle_ready_moves)} valid damaging moves out of {len(processed_moves)} total moves")
    
    # Sort moves by power (descending) to prioritize strongest moves
    # Handle any potential None values in sorting
    battle_ready_moves.sort(key=lambda x: x.get('power', 0) if x.get('power') is not None else 0, reverse=True)
    
    # Ensure at least some basic moves if no damaging moves were found
    if not battle_ready_moves:
        print(f"[DEBUG] No damaging moves found for {poke.get('name', 'Unknown')}, adding basic moves")
        # Add some universal basic moves that should always be available
        basic_moves = [
            {"name": "Tackle", "level_learned_at": 1, "method": "level-up", "power": 40},
            {"name": "Scratch", "level_learned_at": 1, "method": "level-up", "power": 40}
        ]
        battle_ready_moves = basic_moves
    
    # Return all available moves (up to 4, but don't artificially limit if we have valid moves)
    final_moves = battle_ready_moves[:4]
    
    print(f"[DEBUG] Final battle moves for {poke.get('name', 'Unknown')}: {[m.get('name', 'Unknown') for m in final_moves]}")
    
    return final_moves

# --- Utility function to sync active_poke HP to team ---
def sync_active_poke_hp_to_team(user_state):
    """Sync the in-battle active_poke's HP to the user's team list."""
    active_poke = user_state.get("active_poke")
    team = user_state["user"].get("team", [])
    if not active_poke or not team:
        return
    for poke in team:
        # Prefer matching by uuid if available, else fallback to name+level
        if (
            (poke.get("uuid") is not None and poke.get("uuid") == active_poke.get("uuid")) or
            (poke.get("uuid") is None and poke.get("name") == active_poke.get("name") and poke.get("level") == active_poke.get("level"))
        ):
            poke["hp"] = active_poke.get("hp")
            break

async def update_team_and_collection_hp(user_id, team):
    from database import db, update_user_pokemon_collection
    # Update the team in the database
    await db.users.update_one({"user_id": user_id}, {"$set": {"team": team}})
    # Also update the main collection (pokemon) with the latest HP values
    user = await get_or_create_user(user_id, '', '')
    collection = user.get('pokemon', [])
    # Map by uuid if available, else by id+level+nature
    for team_poke in team:
        for poke in collection:
            if (
                (team_poke.get('uuid') and poke.get('uuid') and team_poke['uuid'] == poke['uuid']) or
                (not team_poke.get('uuid') and not poke.get('uuid') and team_poke.get('id') == poke.get('id') and team_poke.get('level') == poke.get('level') and team_poke.get('nature') == poke.get('nature'))
            ):
                poke['hp'] = team_poke.get('hp')
                poke['max_hp'] = team_poke.get('max_hp')
                break
    await update_user_pokemon_collection(user_id, collection)
    print(f"[DEBUG] update_team_and_collection_hp: Updated HPs for user {user_id}: {[p.get('hp') for p in collection]}")

# Utility to set calculated_stats for a Pokémon (base or mega)
def set_calculated_stats(poke):
    # Check if this is a mega evolved Pokemon
    is_mega_evolved = poke.get('mega_evolved', False)
    
    # For mega evolved Pokemon, stats should already be set by mega evolution process
    # Just use the existing stats that were loaded during mega evolution
    if is_mega_evolved:
        stats = poke.get("stats", {})
        if stats:
            print(f"[DEBUG] Using existing mega stats for {poke.get('name', '')}: {stats}")
        else:
            print(f"[DEBUG] No mega stats found, this shouldn't happen for mega evolved Pokemon")
            # Fallback - shouldn't normally be needed
            stats = {}
    else:
        # For non-mega Pokemon, use regular stats processing
        stats = poke.get("stats", {})
    
    # ENHANCED STATS LOOKUP: If no stats found, try multiple fallback methods
    if not stats:
        print(f"[DEBUG] No 'stats' found for {poke.get('name')}, trying fallback methods...")
        
        # Method 1: Look for "base_stats" with different key formats
        base_stats = poke.get("base_stats", {})
        if base_stats:
            print(f"[DEBUG] Found base_stats: {base_stats}")
            # Handle multiple possible key formats
            stats = {
                "hp": (base_stats.get("hp") or base_stats.get("HP") or 
                       base_stats.get("health") or 1),
                "attack": (base_stats.get("atk") or base_stats.get("attack") or 
                          base_stats.get("Attack") or 1),
                "defense": (base_stats.get("def") or base_stats.get("defense") or 
                           base_stats.get("Defense") or 1),
                "special-attack": (base_stats.get("spa") or base_stats.get("special-attack") or 
                                  base_stats.get("Sp. Attack") or base_stats.get("special_attack") or 1),
                "special-defense": (base_stats.get("spd") or base_stats.get("special-defense") or 
                                   base_stats.get("Sp. Defense") or base_stats.get("special_defense") or 1),
                "speed": (base_stats.get("speed") or base_stats.get("Speed") or 1)
            }
            print(f"[DEBUG] Converted base_stats to stats format: {stats}")
        else:
            # Method 2: Try to get from poke.json using Pokemon name or ID
            lookup_name = poke.get("name", "")
            lookup_id = poke.get("id")
            
            # For mega Pokemon, use the base form name for poke.json lookup
            if is_mega_evolved and " Mega" in lookup_name:
                lookup_name = lookup_name.replace(" Mega X", "").replace(" Mega Y", "").replace(" Mega", "")
            
            # Try lookup by name first
            poke_info = get_poke_info(lookup_name)
            if not poke_info and lookup_id:
                # If name lookup failed, try to find by ID in POKE_DATA
                for entry in POKE_DATA:
                    if entry.get('id') == lookup_id:
                        poke_info = entry
                        break
                        
            if poke_info and "base_stats" in poke_info:
                base_stats = poke_info["base_stats"]
                print(f"[DEBUG] Found poke_info base_stats for {lookup_name}: {base_stats}")
                stats = {
                    "hp": (base_stats.get("hp") or base_stats.get("HP") or 1),
                    "attack": (base_stats.get("atk") or base_stats.get("attack") or 
                              base_stats.get("Attack") or 1),
                    "defense": (base_stats.get("def") or base_stats.get("defense") or 
                               base_stats.get("Defense") or 1),
                    "special-attack": (base_stats.get("spa") or base_stats.get("special-attack") or 
                                      base_stats.get("Sp. Attack") or base_stats.get("special_attack") or 1),
                    "special-defense": (base_stats.get("spd") or base_stats.get("special-defense") or 
                                       base_stats.get("Sp. Defense") or base_stats.get("special_defense") or 1),
                    "speed": (base_stats.get("speed") or base_stats.get("Speed") or 1)
                }
                print(f"[DEBUG] Converted poke_info base_stats to stats format: {stats}")
            else:
                # Method 3: Final fallback - use decent default stats instead of 1s
                print(f"[DEBUG] No base stats found anywhere for {lookup_name} (ID: {lookup_id}), using default stats")
                stats = {
                    "hp": 50,
                    "attack": 50,
                    "defense": 50,
                    "special-attack": 50,
                    "special-defense": 50,
                    "speed": 50
                }
    else:
        print(f"[DEBUG] Using existing stats for {poke.get('name')}: {stats}")
    
    # Validate that all stats are reasonable numbers
    for stat_name, stat_value in stats.items():
        if not isinstance(stat_value, (int, float)) or stat_value < 1:
            print(f"[DEBUG] Invalid stat value {stat_name}={stat_value}, setting to 50")
            stats[stat_name] = 50
    
    ivs = poke.get("ivs", {})
    evs = poke.get("evs", {})
    level = poke.get("level", poke.get("lvl", 1))
    nature = poke.get("nature", "Hardy")
    
    # Fallbacks for IVs/EVs - handle both naming conventions
    iv_keys = ["hp", "attack", "defense", "special-attack", "special-defense", "speed"]
    iv_alt_keys = ["HP", "Attack", "Defense", "Sp. Attack", "Sp. Defense", "Speed"]
    
    for i, stat in enumerate(iv_keys):
        if stat not in ivs:
            ivs[stat] = ivs.get(iv_alt_keys[i], 31)
        if stat not in evs:
            evs[stat] = evs.get(iv_alt_keys[i], 0)
    
    # HP
    poke["calculated_stats"] = {}
    new_max_hp = calculate_total_hp(stats.get("hp", 50), ivs["hp"], evs["hp"], level)
    poke["calculated_stats"]["HP"] = new_max_hp
    
    # Update max_hp and current hp proportionally
    old_max_hp = poke.get("max_hp", new_max_hp)
    current_hp = poke.get("hp", new_max_hp)
    
    if old_max_hp > 0 and current_hp > 0:
        # Calculate HP ratio to maintain the same HP percentage
        hp_ratio = current_hp / old_max_hp
        # Update current HP proportionally to the new max HP
        poke["hp"] = min(int(new_max_hp * hp_ratio), new_max_hp)
    else:
        # If current HP is 0 or invalid, set to max HP
        poke["hp"] = new_max_hp
    
    poke["max_hp"] = new_max_hp
    
    # Other stats
    natures_dict = {
        'Hardy': {'increase': None, 'decrease': None},
        'Lonely': {'increase': 'Attack', 'decrease': 'Defense'},
        'Brave': {'increase': 'Attack', 'decrease': 'Speed'},
        'Adamant': {'increase': 'Attack', 'decrease': 'Sp. Atk'},
        'Naughty': {'increase': 'Attack', 'decrease': 'Sp. Def'},
        'Bold': {'increase': 'Defense', 'decrease': 'Attack'},
        'Docile': {'increase': None, 'decrease': None},
        'Relaxed': {'increase': 'Defense', 'decrease': 'Speed'},
        'Impish': {'increase': 'Defense', 'decrease': 'Sp. Atk'},
        'Lax': {'increase': 'Defense', 'decrease': 'Sp. Def'},
        'Timid': {'increase': 'Speed', 'decrease': 'Attack'},
        'Hasty': {'increase': 'Speed', 'decrease': 'Defense'},
        'Serious': {'increase': None, 'decrease': None},
        'Jolly': {'increase': 'Speed', 'decrease': 'Sp. Atk'},
        'Naive': {'increase': 'Speed', 'decrease': 'Sp. Def'},
        'Modest': {'increase': 'Sp. Atk', 'decrease': 'Attack'},
        'Mild': {'increase': 'Sp. Atk', 'decrease': 'Defense'},
        'Quiet': {'increase': 'Sp. Atk', 'decrease': 'Speed'},
        'Bashful': {'increase': None, 'decrease': None},
        'Rash': {'increase': 'Sp. Atk', 'decrease': 'Sp. Def'},
        'Calm': {'increase': 'Sp. Def', 'decrease': 'Attack'},
        'Gentle': {'increase': 'Sp. Def', 'decrease': 'Defense'},
        'Sassy': {'increase': 'Sp. Def', 'decrease': 'Speed'},
        'Careful': {'increase': 'Sp. Def', 'decrease': 'Sp. Atk'},
        'Quirky': {'increase': None, 'decrease': None},
    }
    
    # Attack - handle multiple stat key formats (attack, atk, Attack)
    attack_base = (stats.get("attack") or stats.get("atk") or stats.get("Attack") or 50)
    poke["calculated_stats"]["Attack"] = calculate_total_stat(
        ivs["attack"], evs["attack"], attack_base, level, nature, "Attack", natures_dict
    )["stat"]
    
    # Defense - handle multiple stat key formats (defense, def, Defense)
    defense_base = (stats.get("defense") or stats.get("def") or stats.get("Defense") or 50)
    poke["calculated_stats"]["Defense"] = calculate_total_stat(
        ivs["defense"], evs["defense"], defense_base, level, nature, "Defense", natures_dict
    )["stat"]
    
    # Sp. Atk - handle multiple stat key formats
    sp_atk_base = (stats.get("special-attack") or stats.get("sp_attack") or stats.get("spa") or 
                   stats.get("Sp. Attack") or stats.get("special_attack") or 50)
    poke["calculated_stats"]["Sp. Atk"] = calculate_total_stat(
        ivs.get("special-attack", ivs.get("sp_atk", 31)), evs.get("special-attack", evs.get("sp_atk", 0)), 
        sp_atk_base, level, nature, "Sp. Attack", natures_dict
    )["stat"]
    
    # Sp. Def - handle multiple stat key formats  
    sp_def_base = (stats.get("special-defense") or stats.get("sp_defense") or stats.get("spd") or
                   stats.get("Sp. Defense") or stats.get("special_defense") or 50)
    poke["calculated_stats"]["Sp. Def"] = calculate_total_stat(
        ivs.get("special-defense", ivs.get("sp_def", 31)), evs.get("special-defense", evs.get("sp_def", 0)), 
        sp_def_base, level, nature, "Sp. Defense", natures_dict
    )["stat"]
    
    # Speed - handle multiple stat key formats (speed, Speed)
    speed_base = (stats.get("speed") or stats.get("Speed") or 50)
    poke["calculated_stats"]["Speed"] = calculate_total_stat(
        ivs["speed"], evs["speed"], speed_base, level, nature, "Speed", natures_dict
    )["stat"]
    
    print(f"[DEBUG] Final calculated stats for {poke.get('name')}: {poke['calculated_stats']}")
    print(f"[DEBUG] Mega evolved: {is_mega_evolved}, Base stats used: {stats}")
    print(f"[DEBUG] Stats for battle: Attack={poke['calculated_stats']['Attack']}, Defense={poke['calculated_stats']['Defense']}, Sp.Atk={poke['calculated_stats']['Sp. Atk']}, Sp.Def={poke['calculated_stats']['Sp. Def']}, Speed={poke['calculated_stats']['Speed']}")

# Patch: Set calculated_stats for both users' active_poke at start of battle and after mega evolution
# 1. At start of battle (in duel_accept_decline)
# 2. After mega evolution (in duel_megastone_callback)

# --- PATCH IN duel_accept_decline ---
# After setting active_poke for both users:
# set_calculated_stats(duel["users"][duel["challenger_id"]]["active_poke"])
# set_calculated_stats(duel["users"][duel["challenged_id"]]["active_poke"])

# --- PATCH IN duel_megastone_callback ---
# After updating poke['stats'] and mega_evolved, call set_calculated_stats(poke)

# /duel command (must be a reply)
@router.message(Command("duel"))
async def duel_command(message: types.Message):
    # Clean up expired duels periodically
    cleanup_expired_duels()
    
    if not message.reply_to_message or not getattr(message.reply_to_message, 'from_user', None):
        await message.reply("You must reply to another user's message to challenge them to a duel!")
        return
    challenger = message.from_user
    challenged = message.reply_to_message.from_user
    challenger_id = getattr(challenger, 'id', None)
    challenged_id = getattr(challenged, 'id', None)
    if challenger_id is None or challenged_id is None:
        await message.reply("User information missing!")
        return
    if challenger_id == challenged_id:
        await message.reply("You cannot duel yourself!")
        return
    
    # Check if either user is already in a battle
    if is_user_in_battle(challenger_id):
        await message.reply("You are already in a battle! Finish your current duel first.")
        return
    if is_user_in_battle(challenged_id):
        await message.reply(f"{getattr(challenged, 'first_name', 'They')} is already in a battle!")
        return
    
    # Get PokeRatings and calculate potential changes
    rating1 = await get_user_pokerating(challenger_id)
    rating2 = await get_user_pokerating(challenged_id)

    win_change, _ = calculate_elo_change(rating1, rating2, 1)
    loss_change, _ = calculate_elo_change(rating1, rating2, 0)

    challenger_rating_info = f"{rating1} (+{win_change}/{loss_change})"
    challenged_rating_info = f"{rating2} (+{-loss_change}/{-win_change})"

    # Fetch both users sequentially to avoid race conditions
    challenger_user = await get_or_create_user(challenger_id, getattr(challenger, 'username', ''), getattr(challenger, 'first_name', ''))
    challenged_user = await get_or_create_user(challenged_id, getattr(challenged, 'username', ''), getattr(challenged, 'first_name', ''))
    
    # Sync teams sequentially to avoid data inconsistencies
    if message.bot:
        challenger_user["team"] = await sync_team_with_collection(challenger_id, message.bot)
        challenged_user["team"] = await sync_team_with_collection(challenged_id, message.bot)
    else:
        await message.reply("Bot instance not available!")
        return
    # Validate teams
    if not has_usable_pokemon(challenger_user):
        await message.reply("You must have at least 1 Pokémon with a move to duel!")
        return
    if not has_usable_pokemon(challenged_user):
        await message.reply(f"{getattr(challenged, 'first_name', 'They')} must have at least 1 Pokémon with a move to duel!")
        return
    # Post challenge message
    # Generate unique duel ID using chat_id, message_id, and timestamp to prevent conflicts
    import time
    duel_id = f"{message.chat.id}_{message.message_id}_{int(time.time() * 1000)}"
    
    # Ensure the duel ID is unique (safety check)
    while duel_id in duels:
        duel_id = f"{message.chat.id}_{message.message_id}_{int(time.time() * 1000)}"
        
    duels[duel_id] = {
        "challenger_id": challenger_id,
        "challenged_id": challenged_id,
        "status": "pending",
        "message_id": None,
        "chat_id": message.chat.id,
        "created_at": time.time(),  # Add timestamp for cleanup
    }
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Accept", callback_data=f"duel_accept_{duel_id}"),
            InlineKeyboardButton(text="Decline", callback_data=f"duel_decline_{duel_id}")
        ],
        [
            InlineKeyboardButton(text="Settings", callback_data=f"duel_settings_{duel_id}")
        ]
    ])
    # Get challenger's effective duel settings
    temp_duel = {"challenger_id": challenger_id, "challenged_id": challenged_id}  # Temporary duel for settings lookup
    settings = await get_effective_duel_settings(temp_duel, challenger_id)
    random_mode_enabled = settings['random_mode']
    min_level = settings['min_level']
    max_level = settings['max_level']
    min_legendary = settings['min_legendary']
    max_legendary = settings['max_legendary']
    
    # Build message text
    message_text = (
        f"{hbold(getattr(challenger, 'first_name', 'Challenger'))} has challenged {hbold(getattr(challenged, 'first_name', 'Challenged'))} to a Pokémon duel!\n\n"
        f"{hbold(getattr(challenger, 'first_name', 'Challenger'))}'s PokeRating: {challenger_rating_info}\n"
        f"{hbold(getattr(challenged, 'first_name', 'Challenged'))}'s PokeRating: {challenged_rating_info}\n\n"
    )
    
    # Show active settings
    settings_shown = False
    if random_mode_enabled:
        message_text += f"{hbold('Random Mode')}: Enabled\n"
        settings_shown = True
    
    if min_level > 1:
        message_text += f"{hbold('Min Level')}: {min_level}\n"
        settings_shown = True
    
    if max_level < 100:
        message_text += f"{hbold('Max Level')}: {max_level}\n"
        settings_shown = True
    
    if min_legendary > 0:
        message_text += f"{hbold('Min Legendary')}: {min_legendary}\n"
        settings_shown = True
    
    if max_legendary < 6:
        message_text += f"{hbold('Max Legendary')}: {max_legendary}\n"
        settings_shown = True
    
    if settings_shown:
        message_text += "\n"
    
    message_text += f"Only {getattr(challenged, 'first_name', 'They')} can accept or decline."
    
    sent = await message.reply(
        message_text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    duels[duel_id]["message_id"] = sent.message_id


@router.callback_query(lambda c: c.data and (c.data.startswith("duel_accept_") or c.data.startswith("duel_decline_")))
async def on_duel_invite_action(callback_query: CallbackQuery):
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        # Extract full duel ID from callback data (everything after "duel_accept_" or "duel_decline_")
        if callback_query.data.startswith("duel_accept_"):
            duel_id = callback_query.data[len("duel_accept_"):]
        elif callback_query.data.startswith("duel_decline_"):
            duel_id = callback_query.data[len("duel_decline_"):]
        else:
            raise ValueError("Invalid callback data format")
    except (ValueError, IndexError):
        await callback_query.answer("Invalid duel ID!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    if duel["status"] != "pending":
        if duel["status"] == "cancelled":
            await callback_query.answer("❌ This duel was cancelled due to team requirements not being met.\n\nPlease send a new challenge to start a duel.", show_alert=True)
        else:
            await callback_query.answer("This duel is already resolved!", show_alert=True)
        return

    # --- Handle Decline ---
    if callback_query.data.startswith("duel_decline_"):
        if user_id != duel["challenged_id"]:
            await callback_query.answer("Only the challenged user can decline!", show_alert=True)
            return

        duel["status"] = "declined"

        if not callback_query.bot:
            await callback_query.answer("Bot instance not available!", show_alert=True)
            return
            
        challenger_chat = await callback_query.bot.get_chat(duel["challenger_id"])
        challenger = await get_or_create_user(duel["challenger_id"], challenger_chat.username or "", challenger_chat.first_name or "")

        challenged_chat = await callback_query.bot.get_chat(duel["challenged_id"])
        challenged = await get_or_create_user(duel["challenged_id"], challenged_chat.username or "", challenged_chat.first_name or "")

        challenger_name = challenger.get('first_name', 'Challenger')
        challenged_name = challenged.get('first_name', 'Challenged')

        msg = callback_query.message
        if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
            await msg.edit_text(
                f"{challenged_name} has declined the duel from {challenger_name}.",
                reply_markup=None
            )
        await callback_query.answer("You have declined the duel.")
        return

    # --- Handle Accept ---
    if callback_query.data.startswith("duel_accept_"):
        if user_id != duel["challenged_id"]:
            await callback_query.answer("Only the challenged user can accept!", show_alert=True)
            return

        if is_user_in_battle(duel["challenger_id"]) or is_user_in_battle(duel["challenged_id"]):
            await callback_query.answer("One of the players is already in a battle!", show_alert=True)
            duel["status"] = "cancelled"
            msg = callback_query.message
            if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
                await msg.edit_text("Duel cancelled. One of the players is already in a battle.", reply_markup=None)
            return

        duel["status"] = "active"
        start_battle(duel["challenger_id"], duel["challenged_id"], duel_id)

        if not callback_query.bot:
            await callback_query.answer("Bot instance not available!", show_alert=True)
            return
            
        challenger_chat = await callback_query.bot.get_chat(duel["challenger_id"])
        challenger_user = await get_or_create_user(duel["challenger_id"], challenger_chat.username or "", challenger_chat.first_name or "")

        challenged_chat = await callback_query.bot.get_chat(duel["challenged_id"])
        challenged_user = await get_or_create_user(duel["challenged_id"], challenged_chat.username or "", challenged_chat.first_name or "")

        challenger_user["team"] = await sync_team_with_collection(duel["challenger_id"], callback_query.bot)
        challenged_user["team"] = await sync_team_with_collection(duel["challenged_id"], callback_query.bot)
        challenger_user["team"] = heal_team_to_full(challenger_user.get("team", []))
        challenged_user["team"] = heal_team_to_full(challenged_user.get("team", []))

        # Get effective duel settings using unified system
        settings = await get_effective_duel_settings(duel, duel["challenger_id"])
        
        # Select Pokemon using unified validation system
        challenger_poke, challenger_errors = get_battle_ready_pokemon(challenger_user, settings, settings['random_mode'])
        challenged_poke, challenged_errors = get_battle_ready_pokemon(challenged_user, settings, settings['random_mode'])

        # Validate that both players have valid Pokemon based on requirements
        if not challenger_poke or not challenged_poke:
            # Clean up battle state since validation failed
            end_battle(duel["challenger_id"], duel["challenged_id"], duel_id)
            duel["status"] = "pending"  # Reset duel to pending state
            
            # Give a detailed error and keep duel in pending state
            msg = callback_query.message
            if msg and not isinstance(msg, InaccessibleMessage):
                error_msg = "❌ Cannot start duel - team requirements not met!\n\n"
                
                if not challenger_poke and challenger_errors:
                    error_msg += f"🔴 Challenger: {challenger_errors[0]}\n"
                elif not challenger_poke:
                    error_msg += f"🔴 Challenger's team has issues\n"
                
                if not challenged_poke and challenged_errors:
                    error_msg += f"🔴 Challenged: {challenged_errors[0]}\n"
                elif not challenged_poke:
                    error_msg += f"🔴 Challenged player's team has issues\n"
                
                error_msg += f"\n💡 Use Settings button to adjust requirements or send a new challenge."
                
                # Ensure message length is within Telegram's limit for alerts
                if len(error_msg) > 180:
                    # Provide shorter, more direct messages
                    short_msg = "❌ Team requirements not met!\n\n"
                    if not challenger_poke and challenger_errors:
                        short_msg += f"Challenger: {challenger_errors[0][:50]}...\n"
                    if not challenged_poke and challenged_errors:
                        short_msg += f"Challenged: {challenged_errors[0][:50]}...\n"
                    short_msg += "💡 Adjust Settings or send new challenge."
                    error_msg = short_msg
                
                await callback_query.answer(error_msg, show_alert=True)
            else:
                await callback_query.answer("Team requirements not met! Check the Settings to adjust requirements.", show_alert=True)
            return

        duel["users"] = {
            duel["challenger_id"]: {
                "user_id": duel["challenger_id"],
                "user": challenger_user,
                "active_poke": challenger_poke,
                "switches_remaining": 10,
                "wants_to_run": False,
                "has_mega_evolved": False,
                "has_used_plate": False
            },
            duel["challenged_id"]: {
                "user_id": duel["challenged_id"],
                "user": challenged_user,
                "active_poke": challenged_poke,
                "switches_remaining": 10,
                "wants_to_run": False,
                "has_mega_evolved": False,
                "has_used_plate": False
            }
        }

        challenger_poke = duel["users"][duel["challenger_id"]]["active_poke"]
        challenged_poke = duel["users"][duel["challenged_id"]]["active_poke"]

        set_calculated_stats(challenger_poke)
        set_calculated_stats(challenged_poke)

        order = get_turn_order(challenger_poke, challenged_poke)
        if order == (0, 1):
            duel["turn_order"] = [duel["challenger_id"], duel["challenged_id"]]
            duel["current_turn"] = duel["challenger_id"]
        else:
            duel["turn_order"] = [duel["challenged_id"], duel["challenger_id"]]
            duel["current_turn"] = duel["challenged_id"]

        await handle_arceus_initial_type(duel["users"][duel["challenger_id"]], callback_query.message)
        await handle_arceus_initial_type(duel["users"][duel["challenged_id"]], callback_query.message)

        current_turn_id = duel["current_turn"]
        user_state = duel["users"][current_turn_id]
        opp_id = duel["turn_order"][1] if current_turn_id == duel["turn_order"][0] else duel["turn_order"][0]
        opp_state = duel["users"][opp_id]

        msg = callback_query.message
        if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
            await msg.edit_text(
                build_battle_message(user_state, opp_state, current_turn_id),
                reply_markup=build_battle_keyboard(user_state),
                parse_mode="HTML"
            )
            set_last_action_time(duel_id)
            start_turn_timeout(duel_id, current_turn_id)

# --- Battle Action Handlers ---

@router.callback_query(lambda c: c.data and (c.data.startswith("duel_move_") or c.data == "duel_switch" or c.data == "duel_giveup" or c.data == "duel_plates" or c.data == "duel_zmove"))
async def duel_battle_action(callback_query: CallbackQuery):
    if not callback_query.message or not callback_query.data:
        await callback_query.answer("Invalid callback!", show_alert=True)
        return
    # Find duel by message id
    duel = None
    duel_id = None
    for d_id, d in duels.items():
        if d.get("message_id") == callback_query.message.message_id and d.get("status") == "active":
            duel = d
            duel_id = d_id
            break
    if not duel:
        await callback_query.answer("Battle not found!", show_alert=True)
        return
    user_id = getattr(callback_query.from_user, 'id', None)
    if user_id is None:
        await callback_query.answer("User information missing!", show_alert=True)
        return
    if user_id != duel["current_turn"]:
        await callback_query.answer("It's not your turn!", show_alert=True)
        return
    
    # Check cooldown to prevent spamming
    if not check_cooldown(duel_id):
        remaining = get_cooldown_remaining(duel_id)
        await callback_query.answer(f"⏱️ Please wait {remaining:.1f} seconds before making another action!", show_alert=True)
        return
    
    # Cancel the timeout for current turn (user made a move)
    cancel_turn_timeout(duel_id)
    
    # Set the current action time
    set_last_action_time(duel_id)
    
    user_state = duel["users"][user_id]
    opp_id = [uid for uid in duel["users"] if uid != user_id][0]
    opp_state = duel["users"][opp_id]
    # --- Move Selection ---
    if callback_query.data.startswith("duel_move_"):
        move_idx_str = callback_query.data.split("_")[-1]
        if not move_idx_str.isdigit():
            await callback_query.answer("Invalid move!", show_alert=True)
            return
        move_idx = int(move_idx_str)
        poke = user_state["active_poke"]
        moves = poke.get("active_moves", [])
        if not (0 <= move_idx < len(moves)):
            await callback_query.answer("Invalid move!", show_alert=True)
            return
        move = moves[move_idx]
        
        # Apply move logic
        if DEMO_ALL_MOVES_MISS:
            result = {"missed": True, "damage": 0}
        else:
            result = apply_move(poke, opp_state["active_poke"], move)

        # Calculate actual HP lost (before updating HP)
        old_hp = opp_state["active_poke"].get("hp", opp_state["active_poke"].get("stats", {}).get("hp", 1))
        new_hp = max(0, old_hp - result.get("damage", 0))
        hp_lost = old_hp - new_hp
        
        # Update HP
        opp_state["active_poke"]["hp"] = new_hp
        # Sync HP to team for both users (must be before faint/usable check)
        sync_active_poke_hp_to_team(user_state)
        sync_active_poke_hp_to_team(opp_state)
        
        # Update team and collection HP sequentially to avoid race conditions
        await update_team_and_collection_hp(user_id, user_state["user"].get("team", []))
        await update_team_and_collection_hp(opp_id, opp_state["user"].get("team", []))
        print(f"[DEBUG] After move: User team HPs: {[p.get('hp') for p in user_state['user'].get('team', [])]}, Opponent team HPs: {[p.get('hp') for p in opp_state['user'].get('team', [])]}")
        
        # Prepare battle text
        move_name = move.get('name') or move.get('move') or 'Unknown'
        battle_text = f"{poke['name'].title()} used <b>{move_name.title()}</b>."
        
        # Enhanced result handling with more detailed debugging
        if result.get("missed"):
            battle_text += "\nIt missed!"
            print(f"[DEBUG] Move missed")
        else:
            print(f"[DEBUG] Move hit - processing effects")
            if result.get("crit"):
                battle_text += "\n<b>Critical hit!</b>"
                print(f"[DEBUG] Critical hit!")
            # Effectiveness message is now handled in battle_logic.py and will include immunity text if needed
            if result.get("effectiveness"):
                battle_text += f"\n<i>{result['effectiveness']}</i>"
                print(f"[DEBUG] Effectiveness: {result.get('effectiveness')}")
            if hp_lost > 0:
                battle_text += f"\nDealt {hp_lost} damage!"
                print(f"[DEBUG] Damage dealt: {hp_lost}")
            else:
                print(f"[DEBUG] WARNING: No damage dealt despite move hitting! damage={result.get('damage', 0)}, hp_lost={hp_lost}")
                # Enhanced message handling for 0 damage cases
                if result.get("damage", 0) > 0:
                    battle_text += f"\nDealt {result.get('damage', 0)} damage!"
                else:
                    # Check if this was likely a bug (move should have been effective)
                    effectiveness = result.get("effectiveness", "")
                    if effectiveness and ("super effective" in effectiveness.lower() or "effective" in effectiveness.lower()):
                        # Move should have been effective but failed - show dodge message instead
                        battle_text += f"\n{opp_state['active_poke']['name'].title()} nimbly dodged the attack!"
                        print(f"[DEBUG] Applied dodge message for failed effective move")
                        # Don't show effectiveness message when dodged - it doesn't matter
                        result["effectiveness"] = None
                    elif effectiveness and "no effect" in effectiveness.lower():
                        # Legitimate immunity
                        battle_text += "\nThe attack had no effect!"
                    else:
                        # Uncertain case - use dodge to be user-friendly
                        battle_text += f"\n{opp_state['active_poke']['name'].title()} avoided the attack!"
                        print(f"[DEBUG] Applied avoid message for uncertain 0 damage case")
                        # Don't show effectiveness message when avoided
                        result["effectiveness"] = None
        
        print(f"[DEBUG] Final battle text: {battle_text}")
        
        # Check for faint (team is now up-to-date)
        if check_faint(opp_state["active_poke"]):
            battle_text += f"\n{opp_state['active_poke']['name'].title()} fainted!"
            # Check if opponent has more Pokémon
            opp_usable = get_usable_pokemon_list(opp_state["user"])
            if len(opp_usable) >= 1:
                # Prompt opponent to switch (this is a forced switch, don't count against switch limit)
                duel["current_turn"] = opp_id
                opp_state["forced_switch"] = True  # Mark this as a forced switch
                msg = callback_query.message
                if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
                    await msg.edit_text(
                        build_battle_message(opp_state, user_state, opp_id, battle_text, choose_switch=True),
                        reply_markup=build_switch_keyboard(opp_state),
                        parse_mode="HTML"
                    )
                    # Reset action time for opponent's turn
                    set_last_action_time(duel_id)
                    
                    # Start timeout for opponent's turn
                    start_turn_timeout(duel_id, opp_id)
                return
            else:
                # Duel over - award winner 500 pokedollars
                winner_id = user_id
                winner_user = user_state['user']
                loser_user = opp_state['user']
                
                # Award pokedollars to winner
                from database import db
                await db.users.update_one(
                    {"user_id": winner_id}, 
                    {"$inc": {"pokedollars": 500}}
                )

                # Update Elo ratings
                winner_rating = await get_user_pokerating(winner_id)
                loser_rating = await get_user_pokerating(opp_id)

                winner_change, loser_change = calculate_elo_change(winner_rating, loser_rating, 1)

                await update_user_pokerating(winner_id, winner_change)
                await update_user_pokerating(opp_id, loser_change)

                new_winner_rating = winner_rating + winner_change
                new_loser_rating = loser_rating + loser_change
                
                duel["status"] = "finished"
                
                # Clean up the battle
                cleanup_battle(duel_id)
                
                msg = callback_query.message
                if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
                    # Create proper user links
                    winner_link = f"<a href='tg://user?id={winner_user.get('user_id', winner_id)}'>{winner_user.get('first_name', 'Winner')}</a>"
                    loser_link = f"<a href='tg://user?id={loser_user.get('user_id', opp_id)}'>{loser_user.get('first_name', 'Loser')}</a>"
                    win_message = (
                        f"{winner_link} defeated {loser_link} in a Pokemon Duel.\nPrize: 500 💵\n\n"
                        f"{winner_user.get('first_name', 'Winner')}'s updated PokeRating: {new_winner_rating} (+{winner_change})\n"
                        f"{loser_user.get('first_name', 'Loser')}'s updated PokeRating: {new_loser_rating} ({loser_change})"
                    )
                    await msg.edit_text(
                        win_message,
                        reply_markup=None,
                        parse_mode="HTML"
                    )
                return
        # Pass turn to opponent
        duel["current_turn"] = opp_id
        msg = callback_query.message
        if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
            await msg.edit_text(
                build_battle_message(opp_state, user_state, opp_id, battle_text),
                reply_markup=build_battle_keyboard(opp_state),
                parse_mode="HTML"
            )
            # Reset action time for opponent's turn
            set_last_action_time(duel_id)
            
            # Start timeout for opponent's turn
            start_turn_timeout(duel_id, opp_id)
    # --- Switch Pokémon ---
    elif callback_query.data == "duel_switch":
        # Check if user has switches remaining
        switches_remaining = user_state.get('switches_remaining', 10)
        if switches_remaining <= 0:
            await callback_query.answer("No switches remaining!", show_alert=True)
            return
        
        # Check if user has other usable Pokemon
        usable_pokemon = get_usable_pokemon_list(user_state["user"])
        if len(usable_pokemon) <= 1:
            await callback_query.answer("You don't have any other usable Pokémon to switch to!", show_alert=True)
            return
        
        msg = callback_query.message
        if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
            await msg.edit_text(
                build_battle_message(user_state, opp_state, user_id, choose_switch=True),
                reply_markup=build_switch_keyboard(user_state),
                parse_mode="HTML"
            )
            # Reset action time for switch selection
            set_last_action_time(duel_id)
    # --- Give Up ---
    elif callback_query.data == "duel_giveup":
        # Award pokedollars to winner (opponent)
        winner_id = opp_id
        winner_user = opp_state['user']
        loser_user = user_state['user']
        
        # Award pokedollars to winner
        from database import db
        await db.users.update_one(
            {"user_id": winner_id}, 
            {"$inc": {"pokedollars": 500}}
        )

        # Update Elo ratings
        winner_rating = await get_user_pokerating(winner_id)
        loser_rating = await get_user_pokerating(user_id)

        winner_change, loser_change = calculate_elo_change(winner_rating, loser_rating, 1)

        await update_user_pokerating(winner_id, winner_change)
        await update_user_pokerating(user_id, loser_change)

        new_winner_rating = winner_rating + winner_change
        new_loser_rating = loser_rating + loser_change
        
        duel["status"] = "finished"
        
        # Clean up the battle
        cleanup_battle(duel_id)
        
        msg = callback_query.message
        if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
            # Create proper user links
            winner_link = f"<a href='tg://user?id={winner_user.get('user_id', winner_id)}'>{winner_user.get('first_name', 'Winner')}</a>"
            loser_link = f"<a href='tg://user?id={loser_user.get('user_id', user_id)}'>{loser_user.get('first_name', 'Loser')}</a>"
            win_message = (
                f"{loser_link} gave up! {winner_link} wins the duel.\nPrize: 500 💵\n\n"
                f"{winner_user.get('first_name', 'Winner')}'s updated PokeRating: {new_winner_rating} (+{winner_change})\n"
                f"{loser_user.get('first_name', 'Loser')}'s updated PokeRating: {new_loser_rating} ({loser_change})"
            )
            await msg.edit_text(
                win_message,
                reply_markup=None,
                parse_mode="HTML"
            )
        return
    
    # --- Use Plates ---
    elif callback_query.data == "duel_plates":
        # Only allow if Arceus is active and user hasn't used a plate this battle
        poke = user_state["active_poke"]
        if poke['name'].lower() != 'arceus' or user_state.get('has_used_plate', False):
            await callback_query.answer("You can only use plates with Arceus and only once per battle!", show_alert=True)
            return
        
        # Get user's plates
        from database import get_user_plates
        if user_id is None:
            await callback_query.answer("User ID not found!", show_alert=True)
            return
        user_plates = await get_user_plates(user_id)
        
        if not user_plates:
            await callback_query.answer("You don't have any plates!", show_alert=True)
            return
        
        # Show plates with pagination (3x3 grid)
        plates_keyboard = build_plates_keyboard(user_plates, 1)
        
        msg = callback_query.message
        if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
            await msg.edit_text(
                build_battle_message(user_state, opp_state, user_id, "Choose a plate to use with Arceus:", choose_switch=True),
                reply_markup=plates_keyboard,
                parse_mode="HTML"
            )
            # Reset action time for plate selection
            set_last_action_time(duel_id)
        return
    
    # --- Use Z-Move ---
    elif callback_query.data == "duel_zmove":
        # Only allow if user has z-ring, hasn't used z-move this battle, and has compatible z-crystals
        if user_state.get('has_used_zmove', False):
            await callback_query.answer("You can only use one Z-Move per battle!", show_alert=True)
            return
        
        user_data = user_state.get('user', {})
        has_z_ring = user_data.get('has_z_ring', False)
        if not has_z_ring:
            await callback_query.answer("You need a Z-Ring to use Z-Moves!", show_alert=True)
            return
        
        # Get user's z-crystals
        if user_id is None:
            await callback_query.answer("User ID not found!", show_alert=True)
            return
        user_z_crystals = await get_user_z_crystals(user_id)
        
        if not user_z_crystals:
            await callback_query.answer("You don't have any Z-Crystals!", show_alert=True)
            return
        
        # Check current pokemon types and available moves
        poke = user_state["active_poke"]
        poke_types = poke.get('types', poke.get('type', ['normal']))
        if isinstance(poke_types, str):
            poke_types = [poke_types]
        poke_types = [t.lower() for t in poke_types]
        
        # Find available z-moves for this pokemon
        available_zmoves = []
        type_to_crystal = {
            'normal': 'normaliumz', 'fighting': 'fightiniumz', 'flying': 'flyiniumz',
            'poison': 'poisoniumz', 'ground': 'groundiumz', 'rock': 'rockiumz',
            'bug': 'buginiumz', 'ghost': 'ghostiumz', 'steel': 'steeliumz',
            'fire': 'firiumz', 'water': 'wateriumz', 'grass': 'grassiumz',
            'electric': 'electriumz', 'psychic': 'psychiumz', 'ice': 'iciumz',
            'dragon': 'dragoniumz', 'dark': 'darkiniumz', 'fairy': 'fairiumz'
        }
        
        # Check pokemon's active moves for matching types with z-crystals
        active_moves = poke.get('active_moves', [])
        for move in active_moves:
            move_info = get_move_info(move.get('name', move.get('move', '')))
            if move_info:
                # Check if the move object itself has a type override (e.g., transformed Judgment)
                if 'type' in move and move['type']:
                    move_type = move['type'].lower()
                else:
                    move_type = move_info.get('type', '').lower()
                
                crystal_name = type_to_crystal.get(move_type)
                if crystal_name and crystal_name in user_z_crystals:
                    # Found a compatible move+crystal combination
                    available_zmoves.append({
                        'move': move,
                        'move_info': move_info,
                        'crystal': crystal_name,
                        'type': move_type
                    })
        
        if not available_zmoves:
            await callback_query.answer("No compatible Z-Move combinations available!", show_alert=True)
            return
        
        # Show Z-Move selection interface
        zmove_keyboard = build_zmove_keyboard(available_zmoves, user_id)
        
        # Load zmoves.json for the message formatting
        zmoves_path = os.path.join(os.path.dirname(__file__), '..', 'zmoves.json')
        with open(zmoves_path, encoding='utf-8') as f:
            zmoves_data = json.load(f)
        
        msg = callback_query.message
        if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
            await msg.edit_text(
                build_zmove_selection_message(user_state, opp_state, user_id, available_zmoves, zmoves_data),
                reply_markup=zmove_keyboard,
                parse_mode="HTML"
            )
            # Reset action time for z-move selection
            set_last_action_time(duel_id)
        return
    


# --- Run Handler (can be clicked by either user) ---
@router.callback_query(lambda c: c.data == "duel_run")
async def duel_run_action(callback_query: CallbackQuery):
    if not callback_query.message or not callback_query.data:
        await callback_query.answer("Invalid callback!", show_alert=True)
        return
    # Find duel by message id
    duel = None
    duel_id = None
    for d_id, d in duels.items():
        if d.get("message_id") == callback_query.message.message_id and d.get("status") == "active":
            duel = d
            duel_id = d_id
            break
    if not duel:
        await callback_query.answer("Battle not found!", show_alert=True)
        return
    user_id = getattr(callback_query.from_user, 'id', None)
    
    # Check if user is part of this duel
    if user_id not in duel["users"]:
        await callback_query.answer("You are not part of this duel!", show_alert=True)
        return
    
    user_state = duel["users"][user_id]
    
    # Mark that this user wants to run
    user_state["wants_to_run"] = True
    
    # Check if both users want to run
    if all(duel["users"][uid]["wants_to_run"] for uid in duel["users"]):
        # Both users want to run, stop the duel
        duel["status"] = "finished"
        
        # Get user IDs
        user1_id = duel["challenger_id"]
        user2_id = duel["challenged_id"]
        
        # End the battle
        end_battle(user1_id, user2_id, duel_id)
        
        # Update message
        msg = callback_query.message
        if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
            await msg.edit_text(
                "Both players have run from the duel. The battle is over, and no ratings have been changed.",
                reply_markup=None
            )
        await callback_query.answer("Duel ended.")
        return
    else:
        # Only one user wants to run, continue battle
        user_name = user_state["user"].get("first_name", "Player")
        await callback_query.answer(f"{user_name} wants to run. Both players must click run to stop the duel.", show_alert=True)
        return

# --- Mega Evolution Handler ---
@router.callback_query(lambda c: c.data and c.data.startswith("duel_megastone_"))
async def duel_megastone_callback(callback_query: CallbackQuery):
    if not callback_query.message or not callback_query.data:
        await callback_query.answer("Invalid callback!", show_alert=True)
        return
    # Find duel by message id
    duel = None
    duel_id = None
    for d_id, d in duels.items():
        if d.get("message_id") == callback_query.message.message_id and d.get("status") == "active":
            duel = d
            duel_id = d_id
            break
    if not duel:
        await callback_query.answer("Battle not found!", show_alert=True)
        return
    user_id = getattr(callback_query.from_user, 'id', None)
    
    # Check cooldown to prevent spamming
    if not check_cooldown(duel_id):
        remaining = get_cooldown_remaining(duel_id)
        await callback_query.answer(f"⏱️ Please wait {remaining:.1f} seconds before making another action!", show_alert=True)
        return
    
    # Cancel the timeout for current turn (user made a move)
    cancel_turn_timeout(duel_id)
    
    # Set the current action time
    set_last_action_time(duel_id)
    user_state = duel["users"][user_id]
    poke = user_state["active_poke"]
    # Only allow if not already mega evolved and user hasn't mega evolved this battle
    if poke.get("mega_evolved", False) or user_state.get("has_mega_evolved", False):
        await callback_query.answer("You can only mega evolve one Pokémon per battle!", show_alert=True)
        return
    user_data = user_state.get('user', {})
    has_bracelet = user_data.get('has_mega_bracelet', False)
    mega_stones = user_data.get('mega_stones', [])
    # Map base Pokémon to possible mega forms and required stone(s)
    mega_map = {
        'venusaur': ('Venusaur Mega', 'venusaurite'),
        'charizard': [('Charizard Mega X', 'charizarditex'), ('Charizard Mega Y', 'charizarditey')],
        'blastoise': ('Blastoise Mega', 'blastoisinite'),
        'alakazam': ('Alakazam Mega', 'alakazite'),
        'gengar': ('Gengar Mega', 'gengarite'),
        'kangaskhan': ('Kangaskhan Mega', 'kangaskhanite'),
        'pinsir': ('Pinsir Mega', 'pinsirite'),
        'gyarados': ('Gyarados Mega', 'gyaradosite'),
        'aerodactyl': ('Aerodactyl Mega', 'aerodactylite'),
        'mewtwo': [('Mewtwo Mega X', 'mewtwonitex'), ('Mewtwo Mega Y', 'mewtwonitey')],
        'ampharos': ('Ampharos Mega', 'ampharosite'),
        'scizor': ('Scizor Mega', 'scizorite'),
        'heracross': ('Heracross Mega', 'heracronite'),
        'houndoom': ('Houndoom Mega', 'houndoominite'),
        'tyranitar': ('Tyranitar Mega', 'tyranitarite'),
        'blaziken': ('Blaziken Mega', 'blazikenite'),
        'gardevoir': ('Gardevoir Mega', 'gardevoirite'),
        'mawile': ('Mawile Mega', 'mawilite'),
        'aggron': ('Aggron Mega', 'aggronite'),
        'medicham': ('Medicham Mega', 'medichamite'),
        'manectric': ('Manectric Mega', 'manectite'),
        'banette': ('Banette Mega', 'banettite'),
        'absol': ('Absol Mega', 'absolite'),
        'garchomp': ('Garchomp Mega', 'garchompite'),
        'lucario': ('Lucario Mega', 'lucarionite'),
        'abomasnow': ('Abomasnow Mega', 'abomasite'),
        'beedrill': ('Beedrill Mega', 'beedrillite'),
        'pidgeot': ('Pidgeot Mega', 'pidgeotite'),
        'slowbro': ('Slowbro Mega', 'slowbronite'),
        'steelix': ('Steelix Mega', 'steelixite'),
        'sceptile': ('Sceptile Mega', 'sceptilite'),
        'swampert': ('Swampert Mega', 'swampertite'),
        'sableye': ('Sableye Mega', 'sablenite'),
        'sharpedo': ('Sharpedo Mega', 'sharpedonite'),
        'camerupt': ('Camerupt Mega', 'cameruptite'),
        'altaria': ('Altaria Mega', 'altarianite'),
        'glalie': ('Glalie Mega', 'glalitite'),
        'salamence': ('Salamence Mega', 'salamencite'),
        'metagross': ('Metagross Mega', 'metagrossite'),
        'latias': ('Latias Mega', 'latiasite'),
        'latios': ('Latios Mega', 'latiosite'),
        'lopunny': ('Lopunny Mega', 'lopunnite'),
        'gallade': ('Gallade Mega', 'galladite'),
        'audino': ('Audino Mega', 'audinite'),
        'diancie': ('Diancie Mega', 'diancite'),
        'kyurem': [('Kyurem Black', 'black_core'), ('Kyurem White', 'white_core')],
    }
    base_name = poke['name'].lower().replace(' ', '').replace('-', '')
    mega_form = None
    stone_used = None
    # Parse which mega form is being requested
    callback_mega_name = callback_query.data.split("duel_megastone_")[-1].replace('_', ' ')
    # Find the correct mega form and stone
    mega_options = mega_map.get(base_name)
    if mega_options:
        if isinstance(mega_options, list):
            for form, stone in mega_options:
                if form.lower() == callback_mega_name.lower() and stone in mega_stones and has_bracelet:
                    mega_form = form
                    stone_used = stone
                    break
        else:
            form, stone = mega_options
            if form.lower() == callback_mega_name.lower() and stone in mega_stones and has_bracelet:
                mega_form = form
                stone_used = stone
    if not mega_form:
        await callback_query.answer("You can't mega evolve this Pokémon!", show_alert=True)
        return
    # Load mega stats
    with open(os.path.join(os.path.dirname(__file__), '..', 'mega_pokemon_stats.json'), encoding='utf-8') as f:
        mega_stats = json.load(f)
    if mega_form not in mega_stats:
        await callback_query.answer("Mega stats not found!", show_alert=True)
        return
    # Update active_poke to mega form
    poke['mega_evolved'] = True
    user_state['has_mega_evolved'] = True
    poke['name'] = mega_form
    # Set types from mega stats
    poke['types'] = mega_stats[mega_form]['types']
    poke['stats'] = {
        'hp': mega_stats[mega_form]['stats']['hp'],
        'attack': mega_stats[mega_form]['stats']['attack'],
        'defense': mega_stats[mega_form]['stats']['defense'],
        'special-attack': mega_stats[mega_form]['stats']['special-attack'],
        'special-defense': mega_stats[mega_form]['stats']['special-defense'],
        'speed': mega_stats[mega_form]['stats']['speed'],
    }
    # Do NOT change HP or max HP during Mega Evolution
    # --- PATCH: Set calculated_stats for mega form ---
    
    # IMPORTANT: Preserve HP values during mega evolution
    original_hp = poke.get("hp")
    original_max_hp = poke.get("max_hp")
    
    print(f"[DEBUG] Mega evolution - Original HP: {original_hp}/{original_max_hp}")
    
    set_calculated_stats(poke)
    
    # CRITICAL FIX: Restore HP values to prevent battle logic issues during mega evolution
    if original_hp is not None:
        poke["hp"] = original_hp
    if original_max_hp is not None:
        poke["max_hp"] = original_max_hp
    
    print(f"[DEBUG] Mega evolution - After HP restoration: {poke.get('hp')}/{poke.get('max_hp')}")
    # Show message and image
    img_filename = mega_form.lower().replace(' ', '_').replace('-', '_') + '.png'
    is_shiny = poke.get('is_shiny', False)
    if is_shiny:
        img_path_mega = os.path.join('mega_images_shiny', img_filename.replace('.png', '_shiny.png'))
        img_path_regular = os.path.join('mega_images', img_filename)
    else:
        img_path_mega = os.path.join('mega_images', img_filename)
        img_path_regular = None  # Not used if not shiny
    img_path_fallback = os.path.join('imagesx', img_filename)
    battle_text = f"<b>{callback_query.from_user.first_name}'s Pokémon evolved into {mega_form}!</b>"
    # Try to send cached mega image, then fallback to text
    print(f"[DEBUG] Trying cached mega image for: {mega_form}, is_shiny: {is_shiny}")
    img_file = get_cached_mega_image(mega_form, is_shiny)
    
    if img_file:
        await callback_query.message.reply_photo(img_file, caption=battle_text, parse_mode="HTML")
    else:
        print(f"[DEBUG] Cached mega image not found, trying fallback paths")
        # Try fallback images with cache
        fallback_img = get_cached_image(img_path_fallback)
        if fallback_img:
            await callback_query.message.reply_photo(fallback_img, caption=battle_text, parse_mode="HTML")
        else:
            print(f"[DEBUG] No cached images found, sending text only")
            await callback_query.message.reply(battle_text, parse_mode="HTML")
    # Update the battle message for the next turn
    opp_id = [uid for uid in duel["users"] if uid != user_id][0]
    opp_state = duel["users"][opp_id]
    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
        await msg.edit_text(
            build_battle_message(user_state, opp_state, user_id),
            reply_markup=build_battle_keyboard(user_state),
            parse_mode="HTML"
        )
        # Reset action time for current user's turn
        set_last_action_time(duel_id)
        
        # Start timeout for current user's turn
        start_turn_timeout(duel_id, user_id)
    await callback_query.answer()

# --- Plate Transformation Helper ---
async def transform_arceus_with_plate(user_state, poke, plate_name, message):
    """Transform Arceus with a plate and show appropriate message and image"""
    
    # Get the type for this plate
    new_type = PLATE_TO_TYPE.get(plate_name.lower(), 'Normal')
    print(f"[DEBUG] Transforming Arceus with plate '{plate_name}' to type '{new_type}'")
    
    # Change Arceus's type - ensure both 'type' and 'types' fields are updated
    poke['type'] = [new_type]
    poke['types'] = [new_type]
    
    # Update any Judgment moves to match the new type
    if 'active_moves' in poke:
        for move in poke['active_moves']:
            if move.get('name', '').lower() == 'judgment':
                move['type'] = new_type.lower()
                print(f"[DEBUG] Updated Judgment move type to '{new_type.lower()}'")
    
    # Also update the moves array if it exists
    if 'moves' in poke:
        for move in poke['moves']:
            if move.get('name', '').lower() == 'judgment':
                move['type'] = new_type.lower()
                print(f"[DEBUG] Updated Judgment move type in moves array to '{new_type.lower()}'")
    
    # Get display name for the plate
    PLATE_DISPLAY_NAMES = {
        # Hyphenated format (display names)
        'flame-plate': 'Flame', 'splash-plate': 'Splash', 'zap-plate': 'Zap',
        'meadow-plate': 'Meadow', 'icicle-plate': 'Icicle', 'fist-plate': 'Fist',
        'toxic-plate': 'Toxic', 'earth-plate': 'Earth', 'sky-plate': 'Sky',
        'mind-plate': 'Mind', 'insect-plate': 'Insect', 'stone-plate': 'Stone',
        'spooky-plate': 'Spooky', 'draco-plate': 'Draco', 'dread-plate': 'Dread',
        'iron-plate': 'Iron', 'pixie-plate': 'Pixie',
        # File name format (no hyphens) - actual stored names
        'flameplate': 'Flame', 'splashplate': 'Splash', 'zapplate': 'Zap',
        'meadowplate': 'Meadow', 'icicleplate': 'Icicle', 'fistplate': 'Fist',
        'toxicplate': 'Toxic', 'earthplate': 'Earth', 'skyplate': 'Sky',
        'mindplate': 'Mind', 'insectplate': 'Insect', 'stoneplate': 'Stone',
        'spookyplate': 'Spooky', 'dracoplate': 'Draco', 'dreadplate': 'Dread',
        'ironplate': 'Iron', 'pixieplate': 'Pixie'
    }
    
    plate_display_name = PLATE_DISPLAY_NAMES.get(plate_name.lower(), plate_name.title())
    
    # Create battle message
    first_name = user_state.get('user', {}).get('first_name', 'Trainer')
    battle_text = f"{first_name}'s Arceus transformed into {new_type} type!"
    
    # Determine if Arceus is shiny
    is_shiny = poke.get('is_shiny', False)
    
    # Get appropriate Arceus form image using the new cached function
    photo = get_cached_arceus_form_image(new_type.lower(), is_shiny)
    
    print(f"[DEBUG] Arceus form image for type '{new_type}' (shiny: {is_shiny}): {'found' if photo else 'not found'}")
    
    # Send transformation message with image
    if photo:
        await message.reply_photo(photo=photo, caption=battle_text, parse_mode="HTML")
    else:
        await message.reply(battle_text, parse_mode="HTML")

# --- Plate Selection Handlers ---
@router.callback_query(lambda c: c.data and c.data.startswith("duel_use_plate_"))
async def duel_use_plate_callback(callback_query: CallbackQuery):
    if not callback_query.message or not callback_query.data:
        await callback_query.answer("Invalid callback!", show_alert=True)
        return
    
    # Find duel by message id
    duel = None
    duel_id = None
    for d_id, d in duels.items():
        if d.get("message_id") == callback_query.message.message_id and d.get("status") == "active":
            duel = d
            duel_id = d_id
            break
    
    if not duel:
        await callback_query.answer("Battle not found!", show_alert=True)
        return
    
    user_id = getattr(callback_query.from_user, 'id', None)
    if user_id != duel["current_turn"]:
        await callback_query.answer("It's not your turn!", show_alert=True)
        return
    
    # Check cooldown to prevent spamming
    if not check_cooldown(duel_id):
        remaining = get_cooldown_remaining(duel_id)
        await callback_query.answer(f"⏱️ Please wait {remaining:.1f} seconds before making another action!", show_alert=True)
        return
    
    # Cancel the timeout for current turn (user made a move)
    cancel_turn_timeout(duel_id)
    
    # Set the current action time
    set_last_action_time(duel_id)
    
    user_state = duel["users"][user_id]
    poke = user_state["active_poke"]
    
    # Only allow if Arceus is active and user hasn't used a plate this battle
    if poke['name'].lower() != 'arceus' or user_state.get('has_used_plate', False):
        await callback_query.answer("You can only use plates with Arceus and only once per battle!", show_alert=True)
        return
    
    # Extract plate name from callback data
    plate_name = callback_query.data.replace("duel_use_plate_", "")
    
    # Get user's plates to verify they have it
    from database import get_user_plates
    if user_id is None:
        await callback_query.answer("User ID not found!", show_alert=True)
        return
    user_plates = await get_user_plates(user_id)
    
    if plate_name not in user_plates:
        await callback_query.answer("You don't have this plate!", show_alert=True)
        return
    
    # Mark that user has used a plate this battle
    user_state['has_used_plate'] = True
    
    # Transform Arceus
    await transform_arceus_with_plate(user_state, poke, plate_name, callback_query.message)
    
    # Continue with battle
    opp_id = [uid for uid in duel["users"] if uid != user_id][0]
    opp_state = duel["users"][opp_id]
    
    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
        await msg.edit_text(
            build_battle_message(user_state, opp_state, user_id),
            reply_markup=build_battle_keyboard(user_state),
            parse_mode="HTML"
        )
        # Reset action time for current user's turn
        set_last_action_time(duel_id)
        
        # Start timeout for current user's turn
        start_turn_timeout(duel_id, user_id)
    
    await callback_query.answer()

# --- Plate Pagination Handler ---
@router.callback_query(lambda c: c.data and c.data.startswith("duel_plates_page_"))
async def duel_plates_page_callback(callback_query: CallbackQuery):
    if not callback_query.message or not callback_query.data:
        await callback_query.answer("Invalid callback!", show_alert=True)
        return
    
    # Find duel by message id
    duel = None
    duel_id = None
    for d_id, d in duels.items():
        if d.get("message_id") == callback_query.message.message_id and d.get("status") == "active":
            duel = d
            duel_id = d_id
            break
    
    if not duel:
        await callback_query.answer("Battle not found!", show_alert=True)
        return
    
    user_id = getattr(callback_query.from_user, 'id', None)
    if user_id != duel["current_turn"]:
        await callback_query.answer("It's not your turn!", show_alert=True)
        return
    
    # Cancel the timeout for current turn (user made a move)
    cancel_turn_timeout(duel_id)
    
    # Extract page number
    page_str = callback_query.data.replace("duel_plates_page_", "")
    if not page_str.isdigit():
        await callback_query.answer("Invalid page!", show_alert=True)
        return
    page = int(page_str)
    
    # Get user's plates
    from database import get_user_plates
    if user_id is None:
        await callback_query.answer("User ID not found!", show_alert=True)
        return
    user_plates = await get_user_plates(user_id)
    
    if not user_plates:
        await callback_query.answer("You don't have any plates!", show_alert=True)
        return
    
    # Build plates keyboard for new page
    plates_keyboard = build_plates_keyboard(user_plates, page)
    
    user_state = duel["users"][user_id]
    opp_id = [uid for uid in duel["users"] if uid != user_id][0]
    opp_state = duel["users"][opp_id]
    
    # Update message with new page
    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
        await msg.edit_text(
            build_battle_message(user_state, opp_state, user_id, "Choose a plate to use with Arceus:", choose_switch=True),
            reply_markup=plates_keyboard,
            parse_mode="HTML"
        )
        # Reset action time for plate selection
        set_last_action_time(duel_id)
        
        # Start timeout for plate selection
        start_turn_timeout(duel_id, user_id)
    
    await callback_query.answer()

@router.callback_query(lambda c: c.data == "duel_cancel_plates")
async def duel_cancel_plates_callback(callback_query: CallbackQuery):
    if not callback_query.message:
        await callback_query.answer("Invalid callback!", show_alert=True)
        return
    
    # Find duel by message id
    duel = None
    duel_id = None
    for d_id, d in duels.items():
        if d.get("message_id") == callback_query.message.message_id and d.get("status") == "active":
            duel = d
            duel_id = d_id
            break
    
    if not duel:
        await callback_query.answer("Battle not found!", show_alert=True)
        return
    
    user_id = getattr(callback_query.from_user, 'id', None)
    if user_id != duel["current_turn"]:
        await callback_query.answer("It's not your turn!", show_alert=True)
        return
    
    # Cancel the timeout for current turn (user made a move)
    cancel_turn_timeout(duel_id)
    
    user_state = duel["users"][user_id]
    opp_id = [uid for uid in duel["users"] if uid != user_id][0]
    opp_state = duel["users"][opp_id]
    
    # Return to normal battle interface
    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
        await msg.edit_text(
            build_battle_message(user_state, opp_state, user_id),
            reply_markup=build_battle_keyboard(user_state),
            parse_mode="HTML"
        )
        # Reset action time for current user's turn
        set_last_action_time(duel_id)
        
        # Start timeout for current user's turn
        start_turn_timeout(duel_id, user_id)
    
    await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("duel_use_zmove_"))
async def duel_use_zmove_callback(callback_query: CallbackQuery):
    """Handle Z-Move usage"""
    if not callback_query.message or not callback_query.data:
        await callback_query.answer("Invalid callback!", show_alert=True)
        return
    
    # Find duel by message id
    duel = None
    duel_id = None
    for d_id, d in duels.items():
        if d.get("message_id") == callback_query.message.message_id and d.get("status") == "active":
            duel = d
            duel_id = d_id
            break
    
    if not duel:
        await callback_query.answer("Battle not found!", show_alert=True)
        return
    
    user_id = getattr(callback_query.from_user, 'id', None)
    if user_id != duel["current_turn"]:
        await callback_query.answer("It's not your turn!", show_alert=True)
        return
    
    # Parse callback data
    try:
        parts = callback_query.data.split("_")
        zmove_idx = int(parts[3])
        callback_user_id = int(parts[4])
        if callback_user_id != user_id:
            await callback_query.answer("This is not your battle!", show_alert=True)
            return
    except (ValueError, IndexError):
        await callback_query.answer("Invalid Z-Move selection!", show_alert=True)
        return
    
    # Cancel the timeout for current turn (user made a move)
    cancel_turn_timeout(duel_id)
    
    user_state = duel["users"][user_id]
    opp_id = [uid for uid in duel["users"] if uid != user_id][0]
    opp_state = duel["users"][opp_id]
    
    # Check if user has already used Z-Move
    if user_state.get('has_used_zmove', False):
        await callback_query.answer("You can only use one Z-Move per battle!", show_alert=True)
        return
    
    # Get user's z-crystals and rebuild available zmoves
    if user_id is None:
        await callback_query.answer("User ID not found!", show_alert=True)
        return
    user_z_crystals = await get_user_z_crystals(user_id)
    poke = user_state["active_poke"]
    available_zmoves = []
    type_to_crystal = {
        'normal': 'normaliumz', 'fighting': 'fightiniumz', 'flying': 'flyiniumz',
        'poison': 'poisoniumz', 'ground': 'groundiumz', 'rock': 'rockiumz',
        'bug': 'buginiumz', 'ghost': 'ghostiumz', 'steel': 'steeliumz',
        'fire': 'firiumz', 'water': 'wateriumz', 'grass': 'grassiumz',
        'electric': 'electriumz', 'psychic': 'psychiumz', 'ice': 'iciumz',
        'dragon': 'dragoniumz', 'dark': 'darkiniumz', 'fairy': 'fairiumz'
    }
    
    active_moves = poke.get('active_moves', [])
    for move in active_moves:
        move_info = get_move_info(move.get('name', move.get('move', '')))
        if move_info:
            # Check if the move object itself has a type override (e.g., transformed Judgment)
            if 'type' in move and move['type']:
                move_type = move['type'].lower()
            else:
                move_type = move_info.get('type', '').lower()
            
            crystal_name = type_to_crystal.get(move_type)
            if crystal_name and crystal_name in user_z_crystals:
                available_zmoves.append({
                    'move': move,
                    'move_info': move_info,
                    'crystal': crystal_name,
                    'type': move_type
                })
    
    if zmove_idx >= len(available_zmoves):
        await callback_query.answer("Invalid Z-Move selection!", show_alert=True)
        return
    
    selected_zmove = available_zmoves[zmove_idx]
    
    # Mark that user has used Z-Move this battle
    user_state['has_used_zmove'] = True
    
    # Calculate Z-Move power based on base move power
    base_move = selected_zmove['move']
    base_move_info = selected_zmove['move_info']
    base_power = base_move_info.get('power', 0)
    
    # Load zmoves.json for power calculation
    zmoves_path = os.path.join(os.path.dirname(__file__), '..', 'zmoves.json')
    with open(zmoves_path, encoding='utf-8') as f:
        zmoves_data = json.load(f)
    
    # Find the Z-Move data for this type
    zmove_data = None
    for zmove in zmoves_data:
        if zmove['type'] == selected_zmove['type']:
            zmove_data = zmove
            break
    
    if not zmove_data:
        await callback_query.answer("Z-Move data not found!", show_alert=True)
        return
    
    # Calculate Z-Move power using power_by_base mapping
    zmove_power = 100  # Default power
    power_by_base = zmove_data.get('power_by_base', {})
    
    # Sort ranges to ensure we check from highest to lowest for proper matching
    sorted_ranges = []
    for power_range, z_power in power_by_base.items():
        if power_range.endswith('+'):
            # Handle "141+" style ranges
            min_power = int(power_range[:-1])
            sorted_ranges.append((min_power, float('inf'), z_power, power_range))
        elif '-' in power_range:
            # Handle "76-100" style ranges
            min_power, max_power = power_range.split('-')
            sorted_ranges.append((int(min_power), int(max_power), z_power, power_range))
        else:
            # Handle exact match ranges
            exact_power = int(power_range)
            sorted_ranges.append((exact_power, exact_power, z_power, power_range))
    
    # Sort by minimum power (descending) to check highest ranges first
    sorted_ranges.sort(key=lambda x: x[0], reverse=True)
    
    for min_power, max_power, z_power, power_range in sorted_ranges:
        if min_power <= base_power <= max_power:
            zmove_power = z_power
            break
    
    # Create a modified move object for the Z-Move
    zmove_attack = {
        'name': zmove_data['move'],
        'type': selected_zmove['type'],
        'power': zmove_power,
        'category': base_move_info.get('category', 'physical'),
        'accuracy': 100  # Z-Moves never miss
    }
    
    # Z-Moves bypass accuracy checks and use direct damage calculation
    # Since Z-moves aren't in the standard moves database, we calculate damage directly
    from battle_logic import get_type_list, get_type_effectiveness, is_crit, get_damage_variance
    
    # Get stats with proper fallback handling
    level = poke.get('level', 50)
    atk_stat = poke.get('calculated_stats', {}).get('Attack', poke.get('stats', {}).get('attack', 50))
    sp_atk_stat = poke.get('calculated_stats', {}).get('Sp. Atk', poke.get('stats', {}).get('sp_attack', 50))
    def_stat = opp_state["active_poke"].get('calculated_stats', {}).get('Defense', opp_state["active_poke"].get('stats', {}).get('defense', 50))
    sp_def_stat = opp_state["active_poke"].get('calculated_stats', {}).get('Sp. Def', opp_state["active_poke"].get('stats', {}).get('sp_defense', 50))
    
    move_type = zmove_attack['type']
    category = zmove_attack['category']
    power = zmove_attack['power']
    
    # STAB (Same Type Attack Bonus)
    attacker_types = get_type_list(poke)
    stab = 1.5 if move_type.lower() in [t.lower() for t in attacker_types] else 1.0
    
    # Type effectiveness
    defender_types = get_type_list(opp_state["active_poke"])
    defender_name = opp_state["active_poke"].get('name') or ''
    type_mult, eff_msg = get_type_effectiveness(move_type, defender_types, defender_name)
    
    # Critical hit (Z-moves can crit)
    crit = is_crit()
    crit_mult = 1.5 if crit else 1.0
    
    # Damage variance
    variance = get_damage_variance()
    
    # Stat selection
    if category.lower() == 'special':
        atk = max(1, sp_atk_stat)
        defense = max(1, sp_def_stat)
    else:
        atk = max(1, atk_stat)
        defense = max(1, def_stat)
    
    # Calculate damage using the standard Pokemon damage formula
    # Damage = ((((2 * Level / 5 + 2) * Power * Atk / Def) / 50) + 2) * Modifiers
    base_damage = (((2 * level / 5 + 2) * power * atk / defense) / 50) + 2
    final_damage = int(base_damage * stab * type_mult * crit_mult * variance)
    
    damage = max(1, final_damage)  # Minimum 1 damage
    
    result = {
        "damage": damage,
        "crit": crit,
        "effectiveness": eff_msg if eff_msg else None,
        "missed": False  # Z-Moves NEVER miss
    }
    
    # Calculate actual HP loss and update
    hp_lost = min(result.get("damage", 0), opp_state["active_poke"]["hp"])
    opp_state["active_poke"]["hp"] -= hp_lost
    
    # Sync HP changes to team
    sync_active_poke_hp_to_team(opp_state)
    
    # Build battle text
    zmove_name = zmove_attack['name'].replace('-', ' ').title()
    battle_text = f"<b>{poke['name'].title()} used {zmove_name}!</b>\n"
    
    # Send Z-Move image
    try:
        # Convert Z-move name to image filename (replace spaces and hyphens with underscores)
        image_filename = zmove_attack['name'].replace('-', '_').replace(' ', '_').lower() + '.png'
        image_path = os.path.join(os.path.dirname(__file__), '..', 'zmoves', image_filename)
        
        if os.path.exists(image_path):
            # Get user's first name for caption, being careful with underscores
            user_first_name = user_state['user'].get('first_name', 'Trainer')
            # Escape underscores in the user's name to prevent markdown issues
            safe_user_name = user_first_name.replace('_', '\\_')
            # Create caption with safe Z-move name (replace underscores with spaces for display)
            safe_zmove_name = zmove_attack['name'].replace('-', ' ').replace('_', ' ').title()
            caption = f"{safe_user_name}'s {poke['name'].title()} used {safe_zmove_name}!"
            
            # Send the image as a reply to the duel message
            photo = FSInputFile(image_path)
            await callback_query.message.reply_photo(
                photo=photo,
                caption=caption,
                parse_mode="HTML"
            )
    except Exception as e:
        print(f"[DEBUG] Failed to send Z-move image: {e}")
        # Continue with battle even if image sending fails
    
    if result.get("missed"):
        battle_text += "But the Z-Move missed! (This shouldn't happen)"
    else:
        if hp_lost > 0:
            battle_text += f"It dealt {hp_lost} damage!"
            if result.get("effectiveness"):
                battle_text += f"\n<i>{result['effectiveness']}</i>"
            if result.get("crit"):
                battle_text += "\n<b>Critical hit!</b>"
        else:
            # Enhanced message handling for Z-move 0 damage cases
            effectiveness = result.get("effectiveness", "")
            if effectiveness and ("super effective" in effectiveness.lower() or "effective" in effectiveness.lower()):
                # Z-move should have been effective but failed - show dodge message
                battle_text += f"But {opp_state['active_poke']['name'].title()} skillfully evaded the Z-Power!"
                # Don't show effectiveness message when evaded
                result["effectiveness"] = None
            elif effectiveness and "no effect" in effectiveness.lower():
                # Legitimate immunity
                battle_text += "But it had no effect!"
            else:
                # Uncertain case - use user-friendly message
                battle_text += f"But {opp_state['active_poke']['name'].title()} weathered the Z-Power!"
                # Don't show effectiveness message when weathered
                result["effectiveness"] = None
    
    # Check if opponent Pokemon fainted
    if check_faint(opp_state["active_poke"]):
        battle_text += f"\n{opp_state['active_poke']['name'].title()} fainted!"
        opp_usable = get_usable_pokemon_list(opp_state["user"])
        if not opp_usable:
            # Opponent has no more usable Pokemon - duel over
            winner_id = user_id
            winner_user = user_state['user']
            loser_user = opp_state['user']
            
            # Award pokedollars to winner
            from database import db
            await db.users.update_one(
                {"user_id": winner_id}, 
                {"$inc": {"pokedollars": 500}}
            )

            # Update Elo ratings
            winner_rating = await get_user_pokerating(winner_id)
            loser_rating = await get_user_pokerating(opp_id)

            winner_change, loser_change = calculate_elo_change(winner_rating, loser_rating, 1)

            await update_user_pokerating(winner_id, winner_change)
            await update_user_pokerating(opp_id, loser_change)

            new_winner_rating = winner_rating + winner_change
            new_loser_rating = loser_rating + loser_change
            
            duel["status"] = "finished"
            cleanup_battle(duel_id)
            
            msg = callback_query.message
            if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
                winner_link = f"<a href='tg://user?id={winner_user.get('user_id', winner_id)}'>{winner_user.get('first_name', 'Winner')}</a>"
                loser_link = f"<a href='tg://user?id={loser_user.get('user_id', opp_id)}'>{loser_user.get('first_name', 'Loser')}</a>"
                win_message = (
                    f"{winner_link} defeated {loser_link} in a Pokemon Duel.\nPrize: 500 💵\n\n"
                    f"{winner_user.get('first_name', 'Winner')}'s updated PokeRating: {new_winner_rating} (+{winner_change})\n"
                    f"{loser_user.get('first_name', 'Loser')}'s updated PokeRating: {new_loser_rating} ({loser_change})"
                )
                await msg.edit_text(win_message, reply_markup=None, parse_mode="HTML")
            return
        else:
            # Opponent needs to switch
            duel["current_turn"] = opp_id
            msg = callback_query.message
            if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
                await msg.edit_text(
                    build_battle_message(opp_state, user_state, opp_id, battle_text, choose_switch=True),
                    reply_markup=build_switch_keyboard(opp_state),
                    parse_mode="HTML"
                )
                set_last_action_time(duel_id)
                start_turn_timeout(duel_id, opp_id)
            return
    else:
        # Pass turn to opponent
        duel["current_turn"] = opp_id
        msg = callback_query.message
        if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
            await msg.edit_text(
                build_battle_message(opp_state, user_state, opp_id, battle_text),
                reply_markup=build_battle_keyboard(opp_state),
                parse_mode="HTML"
            )
            set_last_action_time(duel_id)
            start_turn_timeout(duel_id, opp_id)

@router.callback_query(lambda c: c.data == "duel_cancel_zmove")
async def duel_cancel_zmove_callback(callback_query: CallbackQuery):
    """Cancel Z-Move selection and return to battle"""
    if not callback_query.message:
        await callback_query.answer("Invalid callback!", show_alert=True)
        return
    
    # Find duel by message id
    duel = None
    duel_id = None
    for d_id, d in duels.items():
        if d.get("message_id") == callback_query.message.message_id and d.get("status") == "active":
            duel = d
            duel_id = d_id
            break
    
    if not duel:
        await callback_query.answer("Battle not found!", show_alert=True)
        return
    
    user_id = getattr(callback_query.from_user, 'id', None)
    if user_id != duel["current_turn"]:
        await callback_query.answer("It's not your turn!", show_alert=True)
        return
    
    user_state = duel["users"][user_id]
    opp_id = [uid for uid in duel["users"] if uid != user_id][0]
    opp_state = duel["users"][opp_id]
    
    # Return to normal battle interface
    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
        await msg.edit_text(
            build_battle_message(user_state, opp_state, user_id),
            reply_markup=build_battle_keyboard(user_state),
            parse_mode="HTML"
        )
        # Reset action time for current user's turn
        set_last_action_time(duel_id)
        
        # Start timeout for current user's turn
        start_turn_timeout(duel_id, user_id)
    
    await callback_query.answer()

# Helper: Build plates keyboard with pagination (3x3 grid)
def build_plates_keyboard(user_plates, page=1):
    """Build plates keyboard with 3x3 grid pagination"""
    PLATE_DISPLAY_NAMES = {
        # Hyphenated format (display names)
        'flame-plate': 'Flame', 'splash-plate': 'Splash', 'zap-plate': 'Zap',
        'meadow-plate': 'Meadow', 'icicle-plate': 'Icicle', 'fist-plate': 'Fist',
        'toxic-plate': 'Toxic', 'earth-plate': 'Earth', 'sky-plate': 'Sky',
        'mind-plate': 'Mind', 'insect-plate': 'Insect', 'stone-plate': 'Stone',
        'spooky-plate': 'Spooky', 'draco-plate': 'Draco', 'dread-plate': 'Dread',
        'iron-plate': 'Iron', 'pixie-plate': 'Pixie',
        # File name format (no hyphens) - actual stored names
        'flameplate': 'Flame', 'splashplate': 'Splash', 'zapplate': 'Zap',
        'meadowplate': 'Meadow', 'icicleplate': 'Icicle', 'fistplate': 'Fist',
        'toxicplate': 'Toxic', 'earthplate': 'Earth', 'skyplate': 'Sky',
        'mindplate': 'Mind', 'insectplate': 'Insect', 'stoneplate': 'Stone',
        'spookyplate': 'Spooky', 'dracoplate': 'Draco', 'dreadplate': 'Dread',
        'ironplate': 'Iron', 'pixieplate': 'Pixie'
    }
    
    plates_per_page = 9  # 3x3 grid
    total_pages = (len(user_plates) + plates_per_page - 1) // plates_per_page
    
    # Get plates for current page
    start_idx = (page - 1) * plates_per_page
    end_idx = start_idx + plates_per_page
    current_plates = user_plates[start_idx:end_idx]
    
    # Build keyboard in 3x3 grid
    keyboard = []
    for i in range(0, len(current_plates), 3):
        row = []
        for j in range(3):
            if i + j < len(current_plates):
                plate = current_plates[i + j]
                display_name = PLATE_DISPLAY_NAMES.get(plate.lower(), plate.title())
                if display_name is None:
                    display_name = plate.title()
                # Truncate display name if too long
                if len(display_name) > 15:
                    display_name = display_name[:12] + "..."
                row.append(InlineKeyboardButton(text=display_name, callback_data=f"duel_use_plate_{plate}"))
            else:
                row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
        keyboard.append(row)
    
    # Add pagination buttons if needed
    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"duel_plates_page_{page-1}"))
        nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"duel_plates_page_{page+1}"))
        keyboard.append(nav_row)
    
    # Add cancel button
    keyboard.append([InlineKeyboardButton(text="Cancel", callback_data="duel_cancel_plates")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# Helper: Build Z-Move keyboard
def build_zmove_keyboard(available_zmoves, user_id):
    """Build Z-Move selection keyboard"""
    # Load zmoves.json for Z-Move names
    zmoves_path = os.path.join(os.path.dirname(__file__), '..', 'zmoves.json')
    with open(zmoves_path, encoding='utf-8') as f:
        zmoves_data = json.load(f)
    
    # Create type to Z-Move mapping
    type_to_zmove = {}
    for zmove in zmoves_data:
        type_to_zmove[zmove['type']] = zmove['move']
    
    # Collect all Z-move buttons
    buttons = []
    for idx, zmove_info in enumerate(available_zmoves):
        move_type = zmove_info['type']
        zmove_name = type_to_zmove.get(move_type, f"Z-{move_type.title()}")
        base_move_name = zmove_info['move_info']['name']
        
        # Create button text: "Z-Move Name"
        button_text = f"{zmove_name.replace('-', ' ').title()}"
        if len(button_text) > 25:
            button_text = button_text[:22] + "..."
        
        buttons.append(InlineKeyboardButton(
            text=button_text,
            callback_data=f"duel_use_zmove_{idx}_{user_id}"
        ))
    
    # Group buttons into rows of 2
    keyboard = []
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            # Two buttons in this row
            keyboard.append([buttons[i], buttons[i + 1]])
        else:
            # Only one button in this row
            keyboard.append([buttons[i]])
    
    # Add cancel button
    keyboard.append([InlineKeyboardButton(text="Cancel", callback_data="duel_cancel_zmove")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# Helper: Build switch keyboard
def build_switch_keyboard(user_state):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    team = user_state["user"].get("team", [])
    active_poke = user_state["active_poke"]
    usable = get_usable_pokemon_list(user_state["user"])
    # Map usable pokes to their team index
    usable_indices = {id(poke): idx for idx, poke in enumerate(team) if poke in usable}
    # Find the index of the active (fainted) poke in the team
    active_idx = None
    for idx, poke in enumerate(team):
        if poke.get("name") == active_poke.get("name") and poke.get("uuid", None) == active_poke.get("uuid", None):
            active_idx = idx
            break
    # Build buttons: [view team], [1][2], [3][4], [5][6]
    buttons = []
    # First row: view team
    buttons.append([InlineKeyboardButton(text="view team", callback_data="duel_viewteam")])
    # Next rows: 2 buttons per row, for slots 1-6
    for row in range(3):
        row_buttons = []
        for col in range(2):
            slot = row * 2 + col  # 0-based
            if slot >= 6:
                continue
            if slot >= len(team):
                # No Pokémon in this slot
                row_buttons.append(InlineKeyboardButton(text=" ", callback_data="noop"))
            elif slot == active_idx:
                # Fainted/active slot: blank/disabled
                row_buttons.append(InlineKeyboardButton(text=" ", callback_data="noop"))
            else:
                poke = team[slot]
                # Only allow switch if not fainted and has moves
                hp = poke.get("hp", poke.get("stats", {}).get("hp", 1))
                active_moves = poke.get("active_moves", [])
                if hp > 0 and active_moves:
                    row_buttons.append(InlineKeyboardButton(text=f"{slot+1}", callback_data=f"duel_switchto_{slot}"))
                else:
                    row_buttons.append(InlineKeyboardButton(text=" ", callback_data="noop"))
        buttons.append(row_buttons)
    # Add back button
    buttons.append([InlineKeyboardButton(text="Back", callback_data="duel_switchback")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Switch to selected Pokémon
@router.callback_query(lambda c: c.data and c.data.startswith("duel_switchto_"))
async def duel_switchto(callback_query: CallbackQuery):
    if not callback_query.message or not callback_query.data:
        await callback_query.answer("Invalid callback!", show_alert=True)
        return
    duel = None
    duel_id = None
    for d_id, d in duels.items():
        if d.get("message_id") == callback_query.message.message_id and d.get("status") == "active":
            duel = d
            duel_id = d_id
            break
    if not duel:
        await callback_query.answer("Battle not found!", show_alert=True)
        return
    user_id = getattr(callback_query.from_user, 'id', None)
    if user_id != duel["current_turn"]:
        await callback_query.answer("It's not your turn!", show_alert=True)
        return
    
    # Cancel the timeout for current turn (user made a move)
    cancel_turn_timeout(duel_id)
    
    user_state = duel["users"][user_id]
    team = user_state["user"].get("team", [])
    idx_str = callback_query.data.split("_")[-1]
    if not idx_str.isdigit():
        await callback_query.answer("Invalid selection!", show_alert=True)
        return
    idx = int(idx_str)
    if not (0 <= idx < len(team)):
        await callback_query.answer("Invalid selection!", show_alert=True)
        return
    poke = team[idx]
    
    # Check if trying to switch to currently active Pokemon
    active_poke = user_state["active_poke"]
    if (poke.get("uuid") and poke.get("uuid") == active_poke.get("uuid")) or \
       (not poke.get("uuid") and poke.get("name") == active_poke.get("name") and 
        poke.get("level") == active_poke.get("level")):
        await callback_query.answer("This Pokémon is currently battling!", show_alert=True)
        return
    
    # Only allow switch if not fainted and has moves
    hp = poke.get("hp", poke.get("stats", {}).get("hp", 1))
    active_moves = poke.get("active_moves", [])
    if hp <= 0 or not active_moves:
        await callback_query.answer("Invalid selection!", show_alert=True)
        return
    
    # Check if this is a forced switch (due to fainting) or voluntary switch
    is_forced_switch = user_state.get("forced_switch", False)
    
    # Only check switch limit for voluntary switches
    if not is_forced_switch:
        switches_remaining = user_state.get('switches_remaining', 10)
        if switches_remaining <= 0:
            await callback_query.answer("No switches remaining!", show_alert=True)
            return
        # Decrement switches remaining only for voluntary switches
        user_state["switches_remaining"] = switches_remaining - 1
    
    # Store previous Pokemon for switch message
    user_state["previous_active_poke"] = user_state.get("active_poke", {})
    
    # Clear the forced switch flag
    user_state.pop("forced_switch", None)
    
    poke_copy = copy.deepcopy(poke)
    poke_copy["active_moves"] = get_battle_moves(poke_copy)
    
    # IMPORTANT: Preserve the original HP values before stat calculation
    original_hp = poke_copy.get("hp")
    original_max_hp = poke_copy.get("max_hp")
    
    user_state["active_poke"] = poke_copy

    # BUG FIX: Calculate stats for newly switched Pokemon to ensure proper speed calculations
    set_calculated_stats(user_state["active_poke"])
    
    # CRITICAL FIX: Restore the original HP values to prevent battle logic issues
    # The stat calculation should not change HP when switching Pokemon
    if original_hp is not None:
        user_state["active_poke"]["hp"] = original_hp
    if original_max_hp is not None:
        user_state["active_poke"]["max_hp"] = original_max_hp
    
    print(f"[DEBUG] Switch fix - After HP restoration: HP={user_state['active_poke'].get('hp')}, Max HP={user_state['active_poke'].get('max_hp')}")
    
    # Don't modify team order - just track the active Pokémon separately
    # The battle system works fine without reordering the team
    # Sync HP to team after switch
    sync_active_poke_hp_to_team(user_state)
    await update_team_and_collection_hp(user_id, user_state["user"].get("team", []))
    print(f"[DEBUG] After switch: Team HPs: {[p.get('hp') for p in user_state['user'].get('team', [])]}")
    # REMOVED: Duplicate set_calculated_stats call that was causing HP issues
    
    # Determine next turn based on switch type
    opp_id = [uid for uid in duel["users"] if uid != user_id][0]
    opp_state = duel["users"][opp_id]
    
    if is_forced_switch:
        # For forced switches (due to fainting), determine turn by speed
        user_poke = user_state["active_poke"]
        opp_poke = opp_state["active_poke"]
        
        # Use calculated stats for speed comparison
        user_speed = user_poke.get('calculated_stats', {}).get('Speed', 0)
        opp_speed = opp_poke.get('calculated_stats', {}).get('Speed', 0)
        
        print(f"[DEBUG] Forced switch - Speed comparison: {user_poke['name']} ({user_speed}) vs {opp_poke['name']} ({opp_speed})")
        
        # Enhanced debugging for potential speed calculation issues
        print(f"[DEBUG] User Pokemon calculated_stats: {user_poke.get('calculated_stats', {})}")
        print(f"[DEBUG] Opponent Pokemon calculated_stats: {opp_poke.get('calculated_stats', {})}")
        
        # Determine turn order by speed (same logic as battle start)
        order = get_turn_order(user_poke, opp_poke)
        print(f"[DEBUG] get_turn_order returned: {order}")
        print(f"[DEBUG] Expected: User goes first = {user_speed > opp_speed}")
        
        if order == (0, 1):
            # User's Pokemon is faster
            duel["current_turn"] = user_id
            next_turn_user = user_id
            print(f"[DEBUG] User {user_id}'s Pokemon is faster, gets the turn")
        else:
            # Opponent's Pokemon is faster
            duel["current_turn"] = opp_id
            next_turn_user = opp_id
            print(f"[DEBUG] Opponent {opp_id}'s Pokemon is faster, gets the turn")
    else:
        # For voluntary switches, user wastes their turn
        duel["current_turn"] = opp_id
        next_turn_user = opp_id
        print(f"[DEBUG] Voluntary switch - User {user_id} wasted turn, opponent {opp_id} gets turn")
    
    print(f"[DEBUG] Switched Pokemon stats: {user_state['active_poke']['name']} - Speed: {user_state['active_poke'].get('calculated_stats', {}).get('Speed', 0)}")
    print(f"[DEBUG] Opponent Pokemon stats: {opp_state['active_poke']['name']} - Speed: {opp_state['active_poke'].get('calculated_stats', {}).get('Speed', 0)}")
    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
        # Create switch message with the new Pokemon's info
        old_poke_name = user_state.get('previous_active_poke', {}).get('name', 'Previous Pokémon')
        switch_text = f"{old_poke_name} switched out, {user_state['active_poke']['name'].title()} is now on the battle field."
        
        # Add speed advantage message for forced switches when the switching user gets the turn
        if is_forced_switch and duel["current_turn"] == user_id:
            switch_text += f"\n{user_state['active_poke']['name'].title()}'s speed advantage allows it to move first."
        
        # Single smooth transition to the battle interface with switch message
        await msg.edit_text(
            build_battle_message(
                duel["users"][duel["current_turn"]],
                duel["users"][user_id if duel["current_turn"] != user_id else opp_id],
                duel["current_turn"],
                battle_text=switch_text
            ),
            reply_markup=build_battle_keyboard(duel["users"][duel["current_turn"]]),
            parse_mode="HTML"
        )
        # Reset action time for current turn
        set_last_action_time(duel_id)
        
        # Start timeout for the correct user's turn
        start_turn_timeout(duel_id, duel["current_turn"])

# Switch back (cancel switch menu)
@router.callback_query(lambda c: c.data == "duel_switchback")
async def duel_switchback(callback_query: CallbackQuery):
    if not callback_query.message:
        await callback_query.answer("Invalid callback!", show_alert=True)
        return
    duel = None
    duel_id = None
    for d_id, d in duels.items():
        if d.get("message_id") == callback_query.message.message_id and d.get("status") == "active":
            duel = d
            duel_id = d_id
            break
    if not duel:
        await callback_query.answer("Battle not found!", show_alert=True)
        return
    user_id = getattr(callback_query.from_user, 'id', None)
    if user_id != duel["current_turn"]:
        await callback_query.answer("It's not your turn!", show_alert=True)
        return
    
    # Cancel the timeout for current turn (user made a move)
    cancel_turn_timeout(duel_id)
    
    user_state = duel["users"][user_id]
    opp_id = [uid for uid in duel["users"] if uid != user_id][0]
    opp_state = duel["users"][opp_id]
    
    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage) and hasattr(msg, 'edit_text'):
        await msg.edit_text(
            build_battle_message(user_state, opp_state, user_id),
            reply_markup=build_battle_keyboard(user_state),
            parse_mode="HTML"
        )
        # Reset action time for current user's turn
        set_last_action_time(duel_id)
        
        # Start timeout for current user's turn
        start_turn_timeout(duel_id, user_id)

# Add a callback handler for the view team button
@router.callback_query(lambda c: c.data == "duel_viewteam")
async def duel_viewteam(callback_query: CallbackQuery):
    user_id = getattr(callback_query.from_user, 'id', None)
    # Find duel by message id
    duel = None
    if callback_query.message is not None:
        for d in duels.values():
            if d.get("message_id") == callback_query.message.message_id and d.get("status") == "active":
                duel = d
                break
    if not duel:
        await callback_query.answer("Battle not found!", show_alert=True)
        return
    if user_id != duel["current_turn"]:
        await callback_query.answer("It's not your turn!", show_alert=True)
        return
    user_state = duel["users"][user_id]
    team = user_state["user"].get("team", [])
    if not team:
        await callback_query.answer("Your team is empty!", show_alert=True)
        return
    # Format team as a string
    team_str = "Your Team:\n"
    for idx, poke in enumerate(team):
        hp = poke.get("hp", poke.get("stats", {}).get("hp", 1))
        max_hp = poke.get("max_hp", poke.get("stats", {}).get("hp", hp))
        status = "dead" if hp <= 0 else f"alive {hp}/{max_hp} hp"
        team_str += f"{idx+1}. {poke['name'].title()} - {status}\n"
    await callback_query.answer(team_str, show_alert=True)

# Add noop handler for empty buttons
@router.callback_query(lambda c: c.data == "noop")
async def noop_callback(callback_query: CallbackQuery):
    await callback_query.answer()

# --- Initial Arceus transformation handler ---
async def handle_arceus_initial_type(user_state, message=None):
    """Handle Arceus type setup at battle start - no automatic transformation message"""
    poke = user_state.get("active_poke")
    if not poke or poke.get('name', '').lower() != 'arceus':
        return
    
    # Check if Arceus already has a non-Normal type (already transformed)
    current_types = poke.get('types', poke.get('type', ['Normal']))
    if current_types and current_types[0].lower() != 'normal':
        print(f"[DEBUG] Arceus already transformed to {current_types[0]} type")
        return  # Already transformed
    
    # Ensure Arceus has Normal type set properly (without showing transformation message)
    poke['type'] = ['Normal']
    poke['types'] = ['Normal']
    
    # No transformation message shown - users can choose to use plates during battle
    print(f"[DEBUG] Arceus set to Normal type, ready for plate usage")

# --- Cooldown Management Functions ---
def check_cooldown(duel_id):
    """Check if enough time has passed since last action"""
    if duel_id not in duel_last_action:
        return True
    
    current_time = time.time()
    time_since_last_action = current_time - duel_last_action[duel_id]
    return time_since_last_action >= BUTTON_COOLDOWN

def get_cooldown_remaining(duel_id):
    """Get remaining cooldown time in seconds"""
    if duel_id not in duel_last_action:
        return 0
    
    current_time = time.time()
    time_since_last_action = current_time - duel_last_action[duel_id]
    remaining = BUTTON_COOLDOWN - time_since_last_action
    return max(0, remaining)

def set_last_action_time(duel_id):
    """Set the current time as the last action time for a duel"""
    duel_last_action[duel_id] = time.time()

def is_duel_expired(duel):
    """Check if a duel has expired based on creation time"""
    if not duel or 'created_at' not in duel:
        return True
    return time.time() - duel['created_at'] > DUEL_EXPIRY_TIME

def extend_duel_lifetime(duel_id):
    """Extend a duel's lifetime by updating its created_at timestamp"""
    if duel_id in duels:
        duels[duel_id]['created_at'] = time.time()
        return True
    return False

def cleanup_expired_duels():
    """Remove expired duels from memory"""
    current_time = time.time()
    expired_duel_ids = []
    
    for duel_id, duel in duels.items():
        if duel.get('created_at', 0) + DUEL_EXPIRY_TIME < current_time:
            expired_duel_ids.append(duel_id)
    
    for duel_id in expired_duel_ids:
        duels.pop(duel_id, None)
        duel_last_action.pop(duel_id, None)
    
    return len(expired_duel_ids)

# Old validate_duel_and_respond function replaced by validate_duel_with_recovery

# --- Battle Management Functions ---
def is_user_in_battle(user_id):
    """Check if a user is currently in an active battle"""
    return user_id in active_battles

def start_battle(user1_id, user2_id, duel_id):
    """Register users as being in a battle"""
    active_battles[user1_id] = duel_id
    active_battles[user2_id] = duel_id
    print(f"[DEBUG] Started battle {duel_id} between users {user1_id} and {user2_id}")

def end_battle(user1_id, user2_id, duel_id):
    """Remove users from active battles and cleanup"""
    active_battles.pop(user1_id, None)
    active_battles.pop(user2_id, None)
    
    # Cancel timeout task if it exists
    if duel_id in timeout_tasks:
        timeout_tasks[duel_id].cancel()
        del timeout_tasks[duel_id]
    
    print(f"[DEBUG] Ended battle {duel_id} between users {user1_id} and {user2_id}")

async def handle_turn_timeout(duel_id, user_id):
    """Handle when a user doesn't respond within the timeout period"""
    try:
        await asyncio.sleep(TURN_TIMEOUT)
        
        # Check if duel is still active and it's still this user's turn
        duel = duels.get(duel_id)
        if not duel or duel.get("status") != "active" or duel.get("current_turn") != user_id:
            return
        
        # User forfeited due to timeout
        user_state = duel["users"][user_id]
        opp_id = [uid for uid in duel["users"] if uid != user_id][0]
        opp_state = duel["users"][opp_id]
        
        # Deduct pokedollars from forfeiting user
        from database import db
        await db.users.update_one(
            {"user_id": user_id}, 
            {"$inc": {"pokedollars": -FORFEIT_PENALTY}}
        )
        
        # Award pokedollars to winner (opponent)
        await db.users.update_one(
            {"user_id": opp_id}, 
            {"$inc": {"pokedollars": 500}}
        )

        # Update Elo ratings
        loser_rating = await get_user_pokerating(user_id)
        winner_rating = await get_user_pokerating(opp_id)

        loser_change, winner_change = calculate_elo_change(loser_rating, winner_rating, 0)

        await update_user_pokerating(user_id, loser_change)
        await update_user_pokerating(opp_id, winner_change)

        new_loser_rating = loser_rating + loser_change
        new_winner_rating = winner_rating + winner_change
        
        # End the battle
        duel["status"] = "finished"
        end_battle(user_id, opp_id, duel_id)
        
        # Update the message
        user_name = user_state["user"].get("first_name", "Player")
        winner_name = opp_state["user"].get("first_name", "Winner")
        
        # Find the message to update
        if duel.get("message_id") and bot_instance:
            try:
                await bot_instance.edit_message_text(
                    chat_id=duel["chat_id"],
                    message_id=duel["message_id"],
                    text=f"{user_name} has not moved. Player forfeits and loses {FORFEIT_PENALTY} 💵\n\n{winner_name} wins by forfeit and gets 500 💵!\n\n"
                         f"{winner_name}'s updated PokeRating: {new_winner_rating}\n"
                         f"{user_name}'s updated PokeRating: {new_loser_rating}",
                    reply_markup=None
                )
                print(f"[DEBUG] User {user_id} forfeited due to timeout in duel {duel_id}")
            except Exception as e:
                print(f"[DEBUG] Error updating forfeit message: {e}")
        
    except asyncio.CancelledError:
        # Task was cancelled, which is normal when user makes a move
        pass
    except Exception as e:
        print(f"[DEBUG] Error in timeout handler: {e}")

def start_turn_timeout(duel_id, user_id):
    """Start a timeout task for the current turn"""
    # Cancel any existing timeout task
    if duel_id in timeout_tasks:
        timeout_tasks[duel_id].cancel()
    
    # Start new timeout task
    timeout_tasks[duel_id] = asyncio.create_task(handle_turn_timeout(duel_id, user_id))
    print(f"[DEBUG] Started timeout timer for user {user_id} in duel {duel_id}")

def cancel_turn_timeout(duel_id):
    """Cancel the timeout task for a duel"""
    if duel_id in timeout_tasks:
        timeout_tasks[duel_id].cancel()
        del timeout_tasks[duel_id]
        print(f"[DEBUG] Cancelled timeout timer for duel {duel_id}")

# --- Cleanup function for battle end ---
def cleanup_battle(duel_id):
    """Clean up all resources related to a battle"""
    duel = duels.get(duel_id)
    if duel:
        # Get user IDs
        challenger_id = duel.get("challenger_id")
        challenged_id = duel.get("challenged_id")
        
        # End the battle (removes from active_battles and cancels timeouts)
        if challenger_id and challenged_id:
            end_battle(challenger_id, challenged_id, duel_id)
        
        # Reset battle-specific flags
        if "users" in duel:
            for uid in duel["users"]:
                duel["users"][uid]["has_mega_evolved"] = False
                duel["users"][uid]["has_used_plate"] = False
                duel["users"][uid].pop("forced_switch", None)
    
    # Clean up other tracking
    duel_last_action.pop(duel_id, None)
    print(f"[DEBUG] Cleaned up battle {duel_id}")

def get_random_usable_pokemon(user):
    """Get a random Pokemon with moves set for random mode"""
    usable_pokemon = get_usable_pokemon_list(user)
    if not usable_pokemon:
        return None
    
    import random
    random_poke = random.choice(usable_pokemon)
    poke_copy = copy.deepcopy(random_poke)
    
    # Ensure moves are properly set
    poke_copy["active_moves"] = get_battle_moves(poke_copy)
    
    # Set HP properly
    if "hp" not in poke_copy or poke_copy["hp"] is None:
        poke_copy["hp"] = poke_copy.get("hp", poke_copy.get("max_hp") or poke_copy.get("calculated_stats", {}).get("HP") or poke_copy.get("stats", {}).get("hp", 1))
    if "max_hp" not in poke_copy or poke_copy["max_hp"] is None:
        calculated_hp = poke_copy.get("calculated_stats", {}).get("HP")
        if calculated_hp:
            poke_copy["max_hp"] = calculated_hp
        else:
            poke_copy["max_hp"] = poke_copy.get("max_hp") or poke_copy.get("stats", {}).get("hp", poke_copy.get("hp", 1))
    
    return poke_copy

@router.callback_query(lambda c: c.data and c.data.startswith("duel_settings_"))
async def duel_settings_callback(callback_query: CallbackQuery):
    """Handle Settings button click"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        duel_id = extract_duel_id_from_callback(callback_query.data)
    except (ValueError, IndexError):
        await callback_query.answer("Invalid duel ID!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    if duel["status"] != "pending":
        if duel["status"] == "cancelled":
            await callback_query.answer("❌ This duel was cancelled due to team requirements not being met.\n\nPlease send a new challenge to start a duel.", show_alert=True)
        else:
            await callback_query.answer("This duel is already resolved!", show_alert=True)
        return

    # Only challenger can access settings
    if user_id != duel["challenger_id"]:
        await callback_query.answer("Only the challenger can access settings!", show_alert=True)
        return

    # Get effective settings using unified system
    settings = await get_effective_duel_settings(duel, user_id)
    random_mode_status = "Enabled" if settings['random_mode'] else "Disabled"
    min_level = settings['min_level']
    max_level = settings['max_level']
    min_legendary = settings['min_legendary']
    max_legendary = settings['max_legendary']
    
    # Create settings keyboard with 2 buttons per row layout
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Random Mode", callback_data=f"duel_toggle_random_{duel_id}"),
            InlineKeyboardButton(text="Min Level", callback_data=f"duel_min_level_select_{duel_id}")
        ],
        [
            InlineKeyboardButton(text="Max Level", callback_data=f"duel_max_level_select_{duel_id}"),
            InlineKeyboardButton(text="Min Legendary", callback_data=f"duel_min_legendary_{duel_id}")
        ],
        [
            InlineKeyboardButton(text="Max Legendary", callback_data=f"duel_max_legendary_{duel_id}")
        ],
        [
            InlineKeyboardButton(text="Save Settings", callback_data=f"duel_save_settings_{duel_id}"),
            InlineKeyboardButton(text="Reset", callback_data=f"duel_reset_settings_{duel_id}"),
            InlineKeyboardButton(text="Back", callback_data=f"duel_settings_back_{duel_id}")
        ]
    ])

    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage):
        # Get challenger and challenged names
        if not callback_query.bot:
            await callback_query.answer("Bot instance not available!", show_alert=True)
            return
            
        challenger_chat = await callback_query.bot.get_chat(duel["challenger_id"])
        challenged_chat = await callback_query.bot.get_chat(duel["challenged_id"])
        
        challenger_name = challenger_chat.first_name or "Challenger"
        challenged_name = challenged_chat.first_name or "Challenged"
        
        settings_text = (
            f"{hbold(challenger_name)} has challenged {hbold(challenged_name)} to a Pokémon duel!\n\n"
            f"⚙️ {hbold('Duel Settings')}\n\n"
            f"{hbold('Random Mode')}: {random_mode_status}\n"
            f"{hbold('Min Level')}: {min_level}\n"
            f"{hbold('Max Level')}: {max_level}\n"
            f"{hbold('Min Legendary')}: {min_legendary}\n"
            f"{hbold('Max Legendary')}: {max_legendary}\n\n"
            f"Only {challenged_name} can accept or decline."
        )
        
        await msg.edit_text(settings_text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("duel_toggle_random_"))
async def duel_toggle_random_callback(callback_query: CallbackQuery):
    """Handle Random Mode toggle"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        duel_id = extract_duel_id_from_callback(callback_query.data)
    except (ValueError, IndexError):
        await callback_query.answer("Invalid duel ID!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    # Only challenger can toggle settings
    if user_id != duel["challenger_id"]:
        await callback_query.answer("Only the challenger can change settings!", show_alert=True)
        return

    # Get current effective settings
    current_settings = await get_effective_duel_settings(duel, user_id)
    
    # Toggle random mode in duel settings (temporary until saved)
    if "settings" not in duel:
        duel["settings"] = {}
    
    duel["settings"]["random_mode"] = not current_settings['random_mode']
    
    # Get updated settings for display
    updated_settings = await get_effective_duel_settings(duel, user_id)
    random_mode_status = "Enabled" if updated_settings['random_mode'] else "Disabled"
    min_level = updated_settings['min_level']
    min_legendary = updated_settings['min_legendary']
    max_legendary = updated_settings['max_legendary']
    
    # Update keyboard
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Random Mode", callback_data=f"duel_toggle_random_{duel_id}"),
            InlineKeyboardButton(text="Min Level", callback_data=f"duel_min_level_select_{duel_id}")
        ],
        [
            InlineKeyboardButton(text="Min Legendary", callback_data=f"duel_min_legendary_{duel_id}"),
            InlineKeyboardButton(text="Max Legendary", callback_data=f"duel_max_legendary_{duel_id}")
        ],
        [
            InlineKeyboardButton(text="Save Settings", callback_data=f"duel_save_settings_{duel_id}"),
            InlineKeyboardButton(text="Reset", callback_data=f"duel_reset_settings_{duel_id}"),
            InlineKeyboardButton(text="Back", callback_data=f"duel_settings_back_{duel_id}")
        ]
    ])

    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage):
        # Get challenger and challenged names
        if not callback_query.bot:
            await callback_query.answer("Bot instance not available!", show_alert=True)
            return
            
        challenger_chat = await callback_query.bot.get_chat(duel["challenger_id"])
        challenged_chat = await callback_query.bot.get_chat(duel["challenged_id"])
        
        challenger_name = challenger_chat.first_name or "Challenger"
        challenged_name = challenged_chat.first_name or "Challenged"
        
        settings_text = (
            f"{hbold(challenger_name)} has challenged {hbold(challenged_name)} to a Pokémon duel!\n\n"
            f"⚙️ {hbold('Duel Settings')}\n\n"
            f"{hbold('Random Mode')}: {random_mode_status}\n"
            f"{hbold('Min Level')}: {min_level}\n"
            f"{hbold('Min Legendary')}: {min_legendary}\n"
            f"{hbold('Max Legendary')}: {max_legendary}\n\n"
            f"Only {challenged_name} can accept or decline."
        )
        
        await msg.edit_text(settings_text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("duel_save_settings_"))
async def duel_save_settings_callback(callback_query: CallbackQuery):
    """Handle Save Settings button"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        duel_id = extract_duel_id_from_callback(callback_query.data)
    except (ValueError, IndexError):
        await callback_query.answer("Invalid duel ID!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    # Only challenger can save settings
    if user_id != duel["challenger_id"]:
        await callback_query.answer("Only the challenger can save settings!", show_alert=True)
        return

    # Save settings to user preferences
    if "settings" in duel and duel["settings"]:
        # Get current effective settings to ensure we save all values
        effective_settings = await get_effective_duel_settings(duel, user_id)
        await update_user_preferences(
            user_id, 
            random_mode=effective_settings['random_mode'],
            min_level=effective_settings['min_level'],
            min_legendary=effective_settings['min_legendary'],
            max_legendary=effective_settings['max_legendary']
        )
        await callback_query.answer("Settings saved!")
    else:
        await callback_query.answer("No changes to save!")

    # Restore original invitation message directly instead of calling another callback
    # Get effective settings to display
    settings = await get_effective_duel_settings(duel, duel["challenger_id"])
    
    # Restore original keyboard
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Accept", callback_data=f"duel_accept_{duel_id}"),
            InlineKeyboardButton(text="Decline", callback_data=f"duel_decline_{duel_id}")
        ],
        [
            InlineKeyboardButton(text="Settings", callback_data=f"duel_settings_{duel_id}")
        ]
    ])

    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage):
        # Get challenger and challenged names
        if not callback_query.bot:
            await callback_query.answer("Bot instance not available!", show_alert=True)
            return
            
        challenger_chat = await callback_query.bot.get_chat(duel["challenger_id"])
        challenged_chat = await callback_query.bot.get_chat(duel["challenged_id"])
        
        challenger_name = challenger_chat.first_name or "Challenger"
        challenged_name = challenged_chat.first_name or "Challenged"
        
        # Get rating info
        challenger_user = await get_or_create_user(duel["challenger_id"], challenger_chat.username or "", challenger_name)
        challenged_user = await get_or_create_user(duel["challenged_id"], challenged_chat.username or "", challenged_name)
        
        rating1 = challenger_user.get('pokerating', 1000)
        rating2 = challenged_user.get('pokerating', 1000)
        
        win_change, loss_change = calculate_elo_change(rating1, rating2, 1)
        challenger_rating_info = f"{rating1} (+{win_change}/{loss_change})"
        challenged_rating_info = f"{rating2} (+{-loss_change}/{-win_change})"
        
        # Create message text with current effective settings
        message_text = (
            f"{hbold(challenger_name)} has challenged {hbold(challenged_name)} to a Pokémon duel!\n\n"
            f"{hbold(challenger_name)}'s PokeRating: {challenger_rating_info}\n"
            f"{hbold(challenged_name)}'s PokeRating: {challenged_rating_info}\n\n"
        )
        
        # Show active settings
        settings_shown = False
        if settings['random_mode']:
            message_text += f"{hbold('Random Mode')}: Enabled\n"
            settings_shown = True
        
        if settings['min_level'] > 1:
            message_text += f"{hbold('Min Level')}: {settings['min_level']}\n"
            settings_shown = True
        
        if settings['min_legendary'] > 0:
            message_text += f"{hbold('Min Legendary')}: {settings['min_legendary']}\n"
            settings_shown = True
        
        if settings['max_legendary'] < 6:
            message_text += f"{hbold('Max Legendary')}: {settings['max_legendary']}\n"
            settings_shown = True
        
        if settings_shown:
            message_text += "\n"
        
        message_text += f"Only {challenged_name} can accept or decline."
        
        await msg.edit_text(message_text, reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(lambda c: c.data and c.data.startswith("duel_reset_settings_"))
async def duel_reset_settings_callback(callback_query: CallbackQuery):
    """Handle Reset to Default button in settings"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        duel_id = extract_duel_id_from_callback(callback_query.data)
    except (ValueError, IndexError):
        await callback_query.answer("Invalid duel ID!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    if duel["status"] != "pending":
        await callback_query.answer("This duel is no longer pending!", show_alert=True)
        return

    # Only challenger can reset settings
    if user_id != duel["challenger_id"]:
        await callback_query.answer("Only the challenger can reset settings!", show_alert=True)
        return

    # Update user preferences with defaults
    await update_user_preferences(
        user_id,
        random_mode=False,
        min_level=1,
        min_legendary=0,
        max_legendary=6
    )
    
    await callback_query.answer("Settings reset to default values! Go back and re-enter settings to see changes.", show_alert=True)

@router.callback_query(lambda c: c.data and c.data.startswith("duel_settings_back_"))
async def duel_settings_back_callback(callback_query: CallbackQuery):
    """Handle Back button from settings - works exactly like save settings but without saving"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        duel_id = extract_duel_id_from_callback(callback_query.data)
    except (ValueError, IndexError):
        await callback_query.answer("Invalid duel ID!", show_alert=True)
        return

    # Use the same validation as save settings does
    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    # Get effective settings using unified system (includes temporary unsaved changes)
    settings = await get_effective_duel_settings(duel, duel["challenger_id"])
    random_mode_enabled = settings['random_mode']
    
    # Restore original keyboard
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Accept", callback_data=f"duel_accept_{duel_id}"),
            InlineKeyboardButton(text="Decline", callback_data=f"duel_decline_{duel_id}")
        ],
        [
            InlineKeyboardButton(text="Settings", callback_data=f"duel_settings_{duel_id}")
        ]
    ])

    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage):
        # Get challenger and challenged names
        if not callback_query.bot:
            await callback_query.answer("Bot instance not available!", show_alert=True)
            return
            
        challenger_chat = await callback_query.bot.get_chat(duel["challenger_id"])
        challenged_chat = await callback_query.bot.get_chat(duel["challenged_id"])
        
        challenger_name = challenger_chat.first_name or "Challenger"
        challenged_name = challenged_chat.first_name or "Challenged"
        
        # Get rating info
        challenger_user = await get_or_create_user(duel["challenger_id"], challenger_chat.username or "", challenger_name)
        challenged_user = await get_or_create_user(duel["challenged_id"], challenged_chat.username or "", challenged_name)
        
        rating1 = challenger_user.get('pokerating', 1000)
        rating2 = challenged_user.get('pokerating', 1000)
        
        win_change, loss_change = calculate_elo_change(rating1, rating2, 1)
        challenger_rating_info = f"{rating1} (+{win_change}/{loss_change})"
        challenged_rating_info = f"{rating2} (+{-loss_change}/{-win_change})"
        
        # Create message text with current effective settings (whether saved or temporary)
        min_level = settings['min_level']
        min_legendary = settings['min_legendary']
        max_legendary = settings['max_legendary']
        
        message_text = (
            f"{hbold(challenger_name)} has challenged {hbold(challenged_name)} to a Pokémon duel!\n\n"
            f"{hbold(challenger_name)}'s PokeRating: {challenger_rating_info}\n"
            f"{hbold(challenged_name)}'s PokeRating: {challenged_rating_info}\n\n"
        )
        
        # Show active settings (same logic as original duel_command)
        settings_shown = False
        if random_mode_enabled:
            message_text += f"{hbold('Random Mode')}: Enabled\n"
            settings_shown = True
        
        if min_level > 1:
            message_text += f"{hbold('Min Level')}: {min_level}\n"
            settings_shown = True
        
        if min_legendary > 0:
            message_text += f"{hbold('Min Legendary')}: {min_legendary}\n"
            settings_shown = True
        
        if max_legendary < 6:
            message_text += f"{hbold('Max Legendary')}: {max_legendary}\n"
            settings_shown = True
        
        if settings_shown:
            message_text += "\n"
        
        message_text += f"Only {challenged_name} can accept or decline."
        
        await msg.edit_text(message_text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("duel_min_level_select_"))
async def duel_min_level_callback(callback_query: CallbackQuery):
    """Handle Min Level button click"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        duel_id = extract_duel_id_from_callback(callback_query.data)
    except (ValueError, IndexError):
        await callback_query.answer("Invalid duel ID!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    # Only challenger can access min level settings
    if user_id != duel["challenger_id"]:
        await callback_query.answer("Only the challenger can change min level!", show_alert=True)
        return

    # Show min level selection (1-25)
    keyboard_rows = []
    for i in range(1, 26, 5):  # 5 buttons per row
        row = []
        for j in range(5):
            if i + j <= 25:
                row.append(InlineKeyboardButton(
                    text=str(i + j), 
                    callback_data=f"duel_set_min_level_{duel_id}_{i + j}"
                ))
        keyboard_rows.append(row)
    
    # Add navigation buttons
    keyboard_rows.append([
        InlineKeyboardButton(text="Next (26-50)", callback_data=f"duel_min_level_page2_{duel_id}")
    ])
    keyboard_rows.append([
        InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"duel_settings_{duel_id}")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    # Get current min level
    prefs = await get_user_preferences(user_id)
    current_min_level = prefs.get('min_level', 1)
    
    text = (
        f"<b>Select Minimum Level for Pokémon in Battle</b>\n\n"
        f"Current Min Level: <b>{current_min_level}</b>\n\n"
        f"Only Pokémon at or above the selected level will be used in battle."
    )
    
    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage):
        await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("duel_min_level_page2_"))
async def duel_min_level_page2_callback(callback_query: CallbackQuery):
    """Handle Min Level page 2 (26-50)"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        duel_id = extract_duel_id_from_callback(callback_query.data)
    except (ValueError, IndexError):
        await callback_query.answer("Invalid duel ID!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    # Show min level selection (26-50)
    keyboard_rows = []
    for i in range(26, 51, 5):  # 5 buttons per row
        row = []
        for j in range(5):
            if i + j <= 50:
                row.append(InlineKeyboardButton(
                    text=str(i + j), 
                    callback_data=f"duel_set_min_level_{duel_id}_{i + j}"
                ))
        keyboard_rows.append(row)
    
    # Add navigation buttons
    keyboard_rows.append([
        InlineKeyboardButton(text="Previous (1-25)", callback_data=f"duel_min_level_select_{duel_id}"),
        InlineKeyboardButton(text="Next (51-75)", callback_data=f"duel_min_level_page3_{duel_id}")
    ])
    keyboard_rows.append([
        InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"duel_settings_{duel_id}")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    # Get current min level
    prefs = await get_user_preferences(user_id)
    current_min_level = prefs.get('min_level', 1)
    
    text = (
        f"<b>Select Minimum Level for Pokémon in Battle</b>\n\n"
        f"Current Min Level: <b>{current_min_level}</b>\n\n"
        f"Only Pokémon at or above the selected level will be used in battle."
    )
    
    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage):
        await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("duel_min_level_page3_"))
async def duel_min_level_page3_callback(callback_query: CallbackQuery):
    """Handle Min Level page 3 (51-75)"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        duel_id = extract_duel_id_from_callback(callback_query.data)
    except (ValueError, IndexError):
        await callback_query.answer("Invalid duel ID!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    # Show min level selection (51-75)
    keyboard_rows = []
    for i in range(51, 76, 5):  # 5 buttons per row
        row = []
        for j in range(5):
            if i + j <= 75:
                row.append(InlineKeyboardButton(
                    text=str(i + j), 
                    callback_data=f"duel_set_min_level_{duel_id}_{i + j}"
                ))
        keyboard_rows.append(row)
    
    # Add navigation buttons
    keyboard_rows.append([
        InlineKeyboardButton(text="Previous (26-50)", callback_data=f"duel_min_level_page2_{duel_id}"),
        InlineKeyboardButton(text="Next (76-100)", callback_data=f"duel_min_level_page4_{duel_id}")
    ])
    keyboard_rows.append([
        InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"duel_settings_{duel_id}")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    # Get current min level
    prefs = await get_user_preferences(user_id)
    current_min_level = prefs.get('min_level', 1)
    
    text = (
        f"<b>Select Minimum Level for Pokémon in Battle</b>\n\n"
        f"Current Min Level: <b>{current_min_level}</b>\n\n"
        f"Only Pokémon at or above the selected level will be used in battle."
    )
    
    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage):
        await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("duel_min_level_page4_"))
async def duel_min_level_page4_callback(callback_query: CallbackQuery):
    """Handle Min Level page 4 (76-100)"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        duel_id = extract_duel_id_from_callback(callback_query.data)
    except (ValueError, IndexError):
        await callback_query.answer("Invalid duel ID!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    # Show min level selection (76-100)
    keyboard_rows = []
    for i in range(76, 101, 5):  # 5 buttons per row
        row = []
        for j in range(5):
            if i + j <= 100:
                row.append(InlineKeyboardButton(
                    text=str(i + j), 
                    callback_data=f"duel_set_min_level_{duel_id}_{i + j}"
                ))
        keyboard_rows.append(row)
    
    # Add navigation buttons
    keyboard_rows.append([
        InlineKeyboardButton(text="Previous (51-75)", callback_data=f"duel_min_level_page3_{duel_id}")
    ])
    keyboard_rows.append([
        InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"duel_settings_{duel_id}")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    # Get current min level
    prefs = await get_user_preferences(user_id)
    current_min_level = prefs.get('min_level', 1)
    
    text = (
        f"<b>Select Minimum Level for Pokémon in Battle</b>\n\n"
        f"Current Min Level: <b>{current_min_level}</b>\n\n"
        f"Only Pokémon at or above the selected level will be used in battle."
    )
    
    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage):
        await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("duel_set_min_level_"))
async def duel_set_min_level_callback(callback_query: CallbackQuery):
    """Handle setting the min level"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        # Extract everything after "duel_set_min_level_"
        data_part = callback_query.data[len("duel_set_min_level_"):]
        # Split and get the last part as the level, everything else as duel_id
        parts = data_part.split('_')
        min_level = int(parts[-1])
        duel_id = '_'.join(parts[:-1])
    except (ValueError, IndexError):
        await callback_query.answer("Invalid data!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    # Only challenger can set min level
    if user_id != duel["challenger_id"]:
        await callback_query.answer("Only the challenger can set min level!", show_alert=True)
        return

    # Store min level in duel settings (temporary until saved)
    if "settings" not in duel:
        prefs = await get_user_preferences(user_id)
        duel["settings"] = {
            "random_mode": prefs.get('random_mode', False),
            "min_level": prefs.get('min_level', 1),
            "max_level": prefs.get('max_level', 100),
            "min_legendary": prefs.get('min_legendary', 0),
            "max_legendary": prefs.get('max_legendary', 6)
        }
    
    duel["settings"]["min_level"] = min_level
    
    # Validate min/max level conflict and auto-adjust if needed
    current_max_level = duel["settings"].get("max_level", 100)
    if min_level > current_max_level:
        duel["settings"]["max_level"] = min_level
    
    # Get updated settings for display
    updated_settings = await get_effective_duel_settings(duel, user_id)
    random_mode_status = "Enabled" if updated_settings['random_mode'] else "Disabled"
    min_level = updated_settings['min_level']
    min_legendary = updated_settings['min_legendary']
    max_legendary = updated_settings['max_legendary']
    
    # Update keyboard
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Random Mode", callback_data=f"duel_toggle_random_{duel_id}"),
            InlineKeyboardButton(text="Min Level", callback_data=f"duel_min_level_select_{duel_id}")
        ],
        [
            InlineKeyboardButton(text="Min Legendary", callback_data=f"duel_min_legendary_{duel_id}"),
            InlineKeyboardButton(text="Max Legendary", callback_data=f"duel_max_legendary_{duel_id}")
        ],
        [
            InlineKeyboardButton(text="Save Settings", callback_data=f"duel_save_settings_{duel_id}"),
            InlineKeyboardButton(text="Reset", callback_data=f"duel_reset_settings_{duel_id}"),
            InlineKeyboardButton(text="Back", callback_data=f"duel_settings_back_{duel_id}")
        ]
    ])

    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage):
        # Get challenger and challenged names
        if not callback_query.bot:
            await callback_query.answer("Bot instance not available!", show_alert=True)
            return
            
        challenger_chat = await callback_query.bot.get_chat(duel["challenger_id"])
        challenged_chat = await callback_query.bot.get_chat(duel["challenged_id"])
        
        challenger_name = challenger_chat.first_name or "Challenger"
        challenged_name = challenged_chat.first_name or "Challenged"
        
        settings_text = (
            f"{hbold(challenger_name)} has challenged {hbold(challenged_name)} to a Pokémon duel!\n\n"
            f"⚙️ {hbold('Duel Settings')}\n\n"
            f"{hbold('Random Mode')}: {random_mode_status}\n"
            f"{hbold('Min Level')}: {min_level}\n"
            f"{hbold('Min Legendary')}: {min_legendary}\n"
            f"{hbold('Max Legendary')}: {max_legendary}\n\n"
            f"Only {challenged_name} can accept or decline."
        )
        
        await msg.edit_text(settings_text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()
    
def get_usable_pokemon_by_level(user, min_level=1, max_level=100):
    """Get usable Pokemon filtered by level range"""
    team = user.get("team", [])
    usable = []
    for poke in team:
        # Ensure Pokemon has the necessary fields
        if not poke.get("active_moves"):
            poke["active_moves"] = []
        if not poke.get("moves"):
            poke["moves"] = []
        
        # Check level requirement
        poke_level = poke.get("level", 1)
        if not (min_level <= poke_level <= max_level):
            continue
        
        hp = poke.get("hp")
        if hp is None:
            # Use calculated HP if available, otherwise fall back to max_hp, then base HP
            calculated_hp = poke.get("calculated_stats", {}).get("HP")
            if calculated_hp:
                hp = calculated_hp
            else:
                hp = poke.get("max_hp") or poke.get("stats", {}).get("hp", 1)
        
        active_moves = poke.get("active_moves", [])
        # If no active moves, check if Pokemon has any moves at all
        if not active_moves and poke.get("moves"):
            # Auto-assign first 4 moves as active moves
            poke["active_moves"] = poke["moves"][:4]
            active_moves = poke["active_moves"]
        
        if active_moves and hp > 0:
            usable.append(poke)
    return usable

def get_random_usable_pokemon_by_level(user, min_level=1, max_level=100):
    """Get a random Pokemon with moves set for random mode, filtered by level range"""
    usable_pokemon = get_usable_pokemon_by_level(user, min_level, max_level)
    if not usable_pokemon:
        return None
    
    import random
    random_poke = random.choice(usable_pokemon)
    poke_copy = copy.deepcopy(random_poke)
    
    # Ensure moves are properly set
    poke_copy["active_moves"] = get_battle_moves(poke_copy)
    
    # Set HP properly
    if "hp" not in poke_copy or poke_copy["hp"] is None:
        poke_copy["hp"] = poke_copy.get("hp", poke_copy.get("max_hp") or poke_copy.get("calculated_stats", {}).get("HP") or poke_copy.get("stats", {}).get("hp", 1))
    if "max_hp" not in poke_copy or poke_copy["max_hp"] is None:
        calculated_hp = poke_copy.get("calculated_stats", {}).get("HP")
        if calculated_hp:
            poke_copy["max_hp"] = calculated_hp
        else:
            poke_copy["max_hp"] = poke_copy.get("max_hp") or poke_copy.get("stats", {}).get("hp", poke_copy.get("hp", 1))
    
    return poke_copy

def get_first_usable_pokemon_by_level(user, min_level=1, max_level=100):
    """Get first usable Pokemon filtered by level range"""
    usable_pokemon = get_usable_pokemon_by_level(user, min_level, max_level)
    if not usable_pokemon:
        return None
    
    poke = usable_pokemon[0]
    poke_copy = copy.deepcopy(poke)
    
    # Ensure moves are properly set
    poke_copy["active_moves"] = get_battle_moves(poke_copy)
    
    # Set HP properly
    if "hp" not in poke_copy or poke_copy["hp"] is None:
        poke_copy["hp"] = poke_copy.get("hp", poke_copy.get("max_hp") or poke_copy.get("calculated_stats", {}).get("HP") or poke_copy.get("stats", {}).get("hp", 1))
    if "max_hp" not in poke_copy or poke_copy["max_hp"] is None:
        calculated_hp = poke_copy.get("calculated_stats", {}).get("HP")
        if calculated_hp:
            poke_copy["max_hp"] = calculated_hp
        else:
            poke_copy["max_hp"] = poke_copy.get("max_hp") or poke_copy.get("stats", {}).get("hp", poke_copy.get("hp", 1))
    
    return poke_copy

@router.callback_query(lambda c: c.data and c.data.startswith("duel_max_level_select_"))
async def duel_max_level_callback(callback_query: CallbackQuery):
    """Handle Max Level button click"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        duel_id = extract_duel_id_from_callback(callback_query.data)
    except (ValueError, IndexError):
        await callback_query.answer("Invalid duel ID!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    # Only challenger can access max level settings
    if user_id != duel["challenger_id"]:
        await callback_query.answer("Only the challenger can change max level!", show_alert=True)
        return

    # Show max level selection (1-25)
    keyboard_rows = []
    for i in range(1, 26, 5):  # 5 buttons per row
        row = []
        for j in range(5):
            if i + j <= 25:
                row.append(InlineKeyboardButton(
                    text=str(i + j), 
                    callback_data=f"duel_set_max_level_{duel_id}_{i + j}"
                ))
        keyboard_rows.append(row)
    
    # Add navigation buttons
    keyboard_rows.append([
        InlineKeyboardButton(text="Next (26-50)", callback_data=f"duel_max_level_page2_{duel_id}")
    ])
    keyboard_rows.append([
        InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"duel_settings_{duel_id}")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage):
        await msg.edit_text(
            f"Select Max Level (1-25):",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("duel_max_level_page2_"))
async def duel_max_level_page2_callback(callback_query: CallbackQuery):
    """Handle Max Level page 2 (26-50)"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        duel_id = extract_duel_id_from_callback(callback_query.data)
    except (ValueError, IndexError):
        await callback_query.answer("Invalid duel ID!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    # Only challenger can access max level settings
    if user_id != duel["challenger_id"]:
        await callback_query.answer("Only the challenger can change max level!", show_alert=True)
        return

    # Show max level selection (26-50)
    keyboard_rows = []
    for i in range(26, 51, 5):  # 5 buttons per row
        row = []
        for j in range(5):
            if i + j <= 50:
                row.append(InlineKeyboardButton(
                    text=str(i + j), 
                    callback_data=f"duel_set_max_level_{duel_id}_{i + j}"
                ))
        keyboard_rows.append(row)
    
    # Add navigation buttons
    keyboard_rows.append([
        InlineKeyboardButton(text="Previous (1-25)", callback_data=f"duel_max_level_select_{duel_id}"),
        InlineKeyboardButton(text="Next (51-75)", callback_data=f"duel_max_level_page3_{duel_id}")
    ])
    keyboard_rows.append([
        InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"duel_settings_{duel_id}")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage):
        await msg.edit_text(
            f"Select Max Level (26-50):",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("duel_max_level_page3_"))
async def duel_max_level_page3_callback(callback_query: CallbackQuery):
    """Handle Max Level page 3 (51-75)"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        duel_id = extract_duel_id_from_callback(callback_query.data)
    except (ValueError, IndexError):
        await callback_query.answer("Invalid duel ID!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    # Only challenger can access max level settings
    if user_id != duel["challenger_id"]:
        await callback_query.answer("Only the challenger can change max level!", show_alert=True)
        return

    # Show max level selection (51-75)
    keyboard_rows = []
    for i in range(51, 76, 5):  # 5 buttons per row
        row = []
        for j in range(5):
            if i + j <= 75:
                row.append(InlineKeyboardButton(
                    text=str(i + j), 
                    callback_data=f"duel_set_max_level_{duel_id}_{i + j}"
                ))
        keyboard_rows.append(row)
    
    # Add navigation buttons
    keyboard_rows.append([
        InlineKeyboardButton(text="Previous (26-50)", callback_data=f"duel_max_level_page2_{duel_id}"),
        InlineKeyboardButton(text="Next (76-100)", callback_data=f"duel_max_level_page4_{duel_id}")
    ])
    keyboard_rows.append([
        InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"duel_settings_{duel_id}")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage):
        await msg.edit_text(
            f"Select Max Level (51-75):",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("duel_max_level_page4_"))
async def duel_max_level_page4_callback(callback_query: CallbackQuery):
    """Handle Max Level page 4 (76-100)"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        duel_id = extract_duel_id_from_callback(callback_query.data)
    except (ValueError, IndexError):
        await callback_query.answer("Invalid duel ID!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    # Only challenger can access max level settings
    if user_id != duel["challenger_id"]:
        await callback_query.answer("Only the challenger can change max level!", show_alert=True)
        return

    # Show max level selection (76-100)
    keyboard_rows = []
    for i in range(76, 101, 5):  # 5 buttons per row
        row = []
        for j in range(5):
            if i + j <= 100:
                row.append(InlineKeyboardButton(
                    text=str(i + j), 
                    callback_data=f"duel_set_max_level_{duel_id}_{i + j}"
                ))
        keyboard_rows.append(row)
    
    # Add navigation buttons
    keyboard_rows.append([
        InlineKeyboardButton(text="Previous (51-75)", callback_data=f"duel_max_level_page3_{duel_id}")
    ])
    keyboard_rows.append([
        InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"duel_settings_{duel_id}")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage):
        await msg.edit_text(
            f"Select Max Level (76-100):",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("duel_set_max_level_"))
async def duel_set_max_level_callback(callback_query: CallbackQuery):
    """Handle setting the max level"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        # Extract everything after "duel_set_max_level_"
        parts = callback_query.data[len("duel_set_max_level_"):].split("_")
        max_level = int(parts[-1])  # Last part is the level
        duel_id = "_".join(parts[:-1])  # Everything else is the duel ID
    except (ValueError, IndexError):
        await callback_query.answer("Invalid duel ID or level!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    # Only challenger can set max level
    if user_id != duel["challenger_id"]:
        await callback_query.answer("Only the challenger can set max level!", show_alert=True)
        return

    # Store max level in duel settings (temporary until saved)
    if "settings" not in duel:
        prefs = await get_user_preferences(user_id)
        duel["settings"] = {
            "random_mode": prefs.get('random_mode', False),
            "min_level": prefs.get('min_level', 1),
            "max_level": prefs.get('max_level', 100),
            "min_legendary": prefs.get('min_legendary', 0),
            "max_legendary": prefs.get('max_legendary', 6)
        }
    
    duel["settings"]["max_level"] = max_level
    
    # Validate min/max level conflict and auto-adjust if needed
    current_min_level = duel["settings"].get("min_level", 1)
    if max_level < current_min_level:
        duel["settings"]["min_level"] = max_level
    
    # Get updated settings for display
    updated_settings = await get_effective_duel_settings(duel, user_id)
    random_mode_status = "Enabled" if updated_settings['random_mode'] else "Disabled"
    min_level = updated_settings['min_level']
    max_level = updated_settings['max_level']
    min_legendary = updated_settings['min_legendary']
    max_legendary = updated_settings['max_legendary']
    
    # Update keyboard
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Random Mode", callback_data=f"duel_toggle_random_{duel_id}"),
            InlineKeyboardButton(text="Min Level", callback_data=f"duel_min_level_select_{duel_id}")
        ],
        [
            InlineKeyboardButton(text="Max Level", callback_data=f"duel_max_level_select_{duel_id}"),
            InlineKeyboardButton(text="Min Legendary", callback_data=f"duel_min_legendary_{duel_id}")
        ],
        [
            InlineKeyboardButton(text="Max Legendary", callback_data=f"duel_max_legendary_{duel_id}")
        ],
        [
            InlineKeyboardButton(text="Save Settings", callback_data=f"duel_save_settings_{duel_id}"),
            InlineKeyboardButton(text="Reset", callback_data=f"duel_reset_settings_{duel_id}"),
            InlineKeyboardButton(text="Back", callback_data=f"duel_settings_back_{duel_id}")
        ]
    ])

    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage):
        await msg.edit_text(
            f"Duel Settings:\n\n"
            f"Random Mode: {random_mode_status}\n"
            f"Min Level: {min_level}\n"
            f"Max Level: {max_level}\n"
            f"Min Legendary: {min_legendary}\n"
            f"Max Legendary: {max_legendary}\n",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("duel_min_legendary_"))
async def duel_min_legendary_callback(callback_query: CallbackQuery):
    """Handle Min Legendary button click"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        duel_id = extract_duel_id_from_callback(callback_query.data)
    except (ValueError, IndexError):
        await callback_query.answer("Invalid duel ID!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    # Only challenger can access legendary settings
    if user_id != duel["challenger_id"]:
        await callback_query.answer("Only the challenger can change legendary settings!", show_alert=True)
        return

    # Show legendary selection (0-6 in one row)
    keyboard_rows = []
    row = []
    for i in range(7):  # 0 to 6
        row.append(InlineKeyboardButton(
            text=str(i), 
            callback_data=f"duel_set_min_legendary_{duel_id}_{i}"
        ))
    keyboard_rows.append(row)
    
    keyboard_rows.append([
        InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"duel_settings_{duel_id}")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    # Get current min legendary
    prefs = await get_user_preferences(user_id)
    current_min_legendary = prefs.get('min_legendary', 0)
    
    text = (
        f"<b>Select Minimum Legendary Pokémon Required</b>\n\n"
        f"Current Min Legendary: <b>{current_min_legendary}</b>\n\n"
        f"Minimum number of legendary/mythical Pokémon required on each team."
    )
    
    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage):
        await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("duel_max_legendary_"))
async def duel_max_legendary_callback(callback_query: CallbackQuery):
    """Handle Max Legendary button click"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        duel_id = extract_duel_id_from_callback(callback_query.data)
    except (ValueError, IndexError):
        await callback_query.answer("Invalid duel ID!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    # Only challenger can access legendary settings
    if user_id != duel["challenger_id"]:
        await callback_query.answer("Only the challenger can change legendary settings!", show_alert=True)
        return

    # Show legendary selection (0-6 in one row)
    keyboard_rows = []
    row = []
    for i in range(7):  # 0 to 6
        row.append(InlineKeyboardButton(
            text=str(i), 
            callback_data=f"duel_set_max_legendary_{duel_id}_{i}"
        ))
    keyboard_rows.append(row)
    
    keyboard_rows.append([
        InlineKeyboardButton(text="⬅️ Back to Settings", callback_data=f"duel_settings_{duel_id}")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    # Get current max legendary
    prefs = await get_user_preferences(user_id)
    current_max_legendary = prefs.get('max_legendary', 6)
    
    text = (
        f"<b>Select Maximum Legendary Pokémon Allowed</b>\n\n"
        f"Current Max Legendary: <b>{current_max_legendary}</b>\n\n"
        f"Maximum number of legendary/mythical Pokémon allowed on each team."
    )
    
    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage):
        await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("duel_set_min_legendary_"))
async def duel_set_min_legendary_callback(callback_query: CallbackQuery):
    """Handle setting the min legendary count"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        # Extract everything after "duel_set_min_legendary_"
        data_part = callback_query.data[len("duel_set_min_legendary_"):]
        # Split and get the last part as the legendary count, everything else as duel_id
        parts = data_part.split('_')
        min_legendary = int(parts[-1])
        duel_id = '_'.join(parts[:-1])
    except (ValueError, IndexError):
        await callback_query.answer("Invalid data!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    # Only challenger can set min legendary
    if user_id != duel["challenger_id"]:
        await callback_query.answer("Only the challenger can set min legendary!", show_alert=True)
        return

    # Store min legendary in duel settings (temporary until saved)
    if "settings" not in duel:
        prefs = await get_user_preferences(user_id)
        duel["settings"] = {
            "random_mode": prefs.get('random_mode', False),
            "min_level": prefs.get('min_level', 1),
            "max_level": prefs.get('max_level', 100),
            "min_legendary": prefs.get('min_legendary', 0),
            "max_legendary": prefs.get('max_legendary', 6)
        }
    
    duel["settings"]["min_legendary"] = min_legendary
    
    # Validate min/max legendary conflict and auto-adjust if needed
    current_max_legendary = duel["settings"].get("max_legendary", 6)
    if min_legendary > current_max_legendary:
        duel["settings"]["max_legendary"] = min_legendary
    
    # Get updated settings for display
    updated_settings = await get_effective_duel_settings(duel, user_id)
    random_mode_status = "Enabled" if updated_settings['random_mode'] else "Disabled"
    min_level = updated_settings['min_level']
    min_legendary = updated_settings['min_legendary']
    max_legendary = updated_settings['max_legendary']
    
    # Update keyboard
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Random Mode", callback_data=f"duel_toggle_random_{duel_id}"),
            InlineKeyboardButton(text="Min Level", callback_data=f"duel_min_level_select_{duel_id}")
        ],
        [
            InlineKeyboardButton(text="Min Legendary", callback_data=f"duel_min_legendary_{duel_id}"),
            InlineKeyboardButton(text="Max Legendary", callback_data=f"duel_max_legendary_{duel_id}")
        ],
        [
            InlineKeyboardButton(text="Save Settings", callback_data=f"duel_save_settings_{duel_id}"),
            InlineKeyboardButton(text="Reset", callback_data=f"duel_reset_settings_{duel_id}"),
            InlineKeyboardButton(text="Back", callback_data=f"duel_settings_back_{duel_id}")
        ]
    ])

    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage):
        # Get challenger and challenged names
        if not callback_query.bot:
            await callback_query.answer("Bot instance not available!", show_alert=True)
            return
            
        challenger_chat = await callback_query.bot.get_chat(duel["challenger_id"])
        challenged_chat = await callback_query.bot.get_chat(duel["challenged_id"])
        
        challenger_name = challenger_chat.first_name or "Challenger"
        challenged_name = challenged_chat.first_name or "Challenged"
        
        settings_text = (
            f"{hbold(challenger_name)} has challenged {hbold(challenged_name)} to a Pokémon duel!\n\n"
            f"⚙️ {hbold('Duel Settings')}\n\n"
            f"{hbold('Random Mode')}: {random_mode_status}\n"
            f"{hbold('Min Level')}: {min_level}\n"
            f"{hbold('Min Legendary')}: {min_legendary}\n"
            f"{hbold('Max Legendary')}: {max_legendary}\n\n"
            f"Only {challenged_name} can accept or decline."
        )
        
        await msg.edit_text(settings_text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("duel_set_max_legendary_"))
async def duel_set_max_legendary_callback(callback_query: CallbackQuery):
    """Handle setting the max legendary count"""
    if not callback_query.data:
        return

    user_id = callback_query.from_user.id
    try:
        # Extract everything after "duel_set_max_legendary_"
        data_part = callback_query.data[len("duel_set_max_legendary_"):]
        # Split and get the last part as the legendary count, everything else as duel_id
        parts = data_part.split('_')
        max_legendary = int(parts[-1])
        duel_id = '_'.join(parts[:-1])
    except (ValueError, IndexError):
        await callback_query.answer("Invalid data!", show_alert=True)
        return

    duel = await validate_duel_with_recovery(callback_query, duel_id)
    if not duel:
        return

    # Only challenger can set max legendary
    if user_id != duel["challenger_id"]:
        await callback_query.answer("Only the challenger can set max legendary!", show_alert=True)
        return

    # Store max legendary in duel settings (temporary until saved)
    if "settings" not in duel:
        prefs = await get_user_preferences(user_id)
        duel["settings"] = {
            "random_mode": prefs.get('random_mode', False),
            "min_level": prefs.get('min_level', 1),
            "max_level": prefs.get('max_level', 100),
            "min_legendary": prefs.get('min_legendary', 0),
            "max_legendary": prefs.get('max_legendary', 6)
        }
    
    duel["settings"]["max_legendary"] = max_legendary
    
    # Validate min/max legendary conflict and auto-adjust if needed
    current_min_legendary = duel["settings"].get("min_legendary", 0)
    if max_legendary < current_min_legendary:
        duel["settings"]["min_legendary"] = max_legendary
    
    # Get updated settings for display
    updated_settings = await get_effective_duel_settings(duel, user_id)
    random_mode_status = "Enabled" if updated_settings['random_mode'] else "Disabled"
    min_level = updated_settings['min_level']
    min_legendary = updated_settings['min_legendary']
    max_legendary = updated_settings['max_legendary']
    
    # Update keyboard
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Random Mode", callback_data=f"duel_toggle_random_{duel_id}"),
            InlineKeyboardButton(text="Min Level", callback_data=f"duel_min_level_select_{duel_id}")
        ],
        [
            InlineKeyboardButton(text="Min Legendary", callback_data=f"duel_min_legendary_{duel_id}"),
            InlineKeyboardButton(text="Max Legendary", callback_data=f"duel_max_legendary_{duel_id}")
        ],
        [
            InlineKeyboardButton(text="Save Settings", callback_data=f"duel_save_settings_{duel_id}"),
            InlineKeyboardButton(text="Reset", callback_data=f"duel_reset_settings_{duel_id}"),
            InlineKeyboardButton(text="Back", callback_data=f"duel_settings_back_{duel_id}")
        ]
    ])

    msg = callback_query.message
    if msg and not isinstance(msg, InaccessibleMessage):
        # Get challenger and challenged names
        if not callback_query.bot:
            await callback_query.answer("Bot instance not available!", show_alert=True)
            return
            
        challenger_chat = await callback_query.bot.get_chat(duel["challenger_id"])
        challenged_chat = await callback_query.bot.get_chat(duel["challenged_id"])
        
        challenger_name = challenger_chat.first_name or "Challenger"
        challenged_name = challenged_chat.first_name or "Challenged"
        
        settings_text = (
            f"{hbold(challenger_name)} has challenged {hbold(challenged_name)} to a Pokémon duel!\n\n"
            f"⚙️ {hbold('Duel Settings')}\n\n"
            f"{hbold('Random Mode')}: {random_mode_status}\n"
            f"{hbold('Min Level')}: {min_level}\n"
            f"{hbold('Min Legendary')}: {min_legendary}\n"
            f"{hbold('Max Legendary')}: {max_legendary}\n\n"
            f"Only {challenged_name} can accept or decline."
        )
        
        await msg.edit_text(settings_text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

def is_legendary_pokemon(poke):
    """Check if a Pokemon is legendary or mythical - deprecated, use safe_is_legendary_pokemon instead"""
    return safe_is_legendary_pokemon(poke)

def count_legendary_pokemon(team):
    """Count the number of legendary/mythical Pokemon in a team - deprecated, use safe_count_legendary_pokemon instead"""
    return safe_count_legendary_pokemon(team)

def validate_team_legendary_requirements(team, min_legendary=0, max_legendary=6):
    """Check if team meets legendary requirements"""
    legendary_count = count_legendary_pokemon(team)
    return min_legendary <= legendary_count <= max_legendary

def get_usable_pokemon_with_legendary_filter(user, min_legendary=0, max_legendary=6):
    """Get usable Pokemon if team meets legendary requirements"""
    team = user.get("team", [])
    
    # First check if team meets legendary requirements
    if not validate_team_legendary_requirements(team, min_legendary, max_legendary):
        return []
    
    # If it does, return usable Pokemon from the team
    return get_usable_pokemon_list(user)

def get_usable_pokemon_with_all_filters(user, min_level=1, max_level=100, min_legendary=0, max_legendary=6):
    """Get usable Pokemon filtered by level and legendary requirements"""
    team = user.get("team", [])
    
    # First check if team meets legendary requirements
    if not validate_team_legendary_requirements(team, min_legendary, max_legendary):
        return []
    
    # Then filter by level (only if legendary requirements are met)
    return get_usable_pokemon_by_level(user, min_level, max_level)

def get_random_usable_pokemon_with_all_filters(user, min_level=1, max_level=100, min_legendary=0, max_legendary=6):
    """Get a random Pokemon with all filters applied"""
    filtered_team = get_usable_pokemon_with_all_filters(user, min_level, max_level, min_legendary, max_legendary)
    if not filtered_team:
        return None
    
    import random
    random_poke = random.choice(filtered_team)
    poke_copy = copy.deepcopy(random_poke)
    
    # Ensure moves are properly set
    poke_copy["active_moves"] = get_battle_moves(poke_copy)
    
    # Set HP properly
    if "hp" not in poke_copy or poke_copy["hp"] is None:
        poke_copy["hp"] = poke_copy.get("hp", poke_copy.get("max_hp") or poke_copy.get("calculated_stats", {}).get("HP") or poke_copy.get("stats", {}).get("hp", 1))
    if "max_hp" not in poke_copy or poke_copy["max_hp"] is None:
        calculated_hp = poke_copy.get("calculated_stats", {}).get("HP")
        if calculated_hp:
            poke_copy["max_hp"] = calculated_hp
        else:
            poke_copy["max_hp"] = poke_copy.get("max_hp") or poke_copy.get("stats", {}).get("hp", poke_copy.get("hp", 1))
    
    return poke_copy

def get_first_usable_pokemon_with_all_filters(user, min_level=1, max_level=100, min_legendary=0, max_legendary=6):
    """Get first usable Pokemon with all filters applied"""
    filtered_team = get_usable_pokemon_with_all_filters(user, min_level, max_level, min_legendary, max_legendary)
    if not filtered_team:
        return None
    
    poke = filtered_team[0]
    poke_copy = copy.deepcopy(poke)
    
    # Ensure moves are properly set
    poke_copy["active_moves"] = get_battle_moves(poke_copy)
    
    # Set HP properly
    if "hp" not in poke_copy or poke_copy["hp"] is None:
        poke_copy["hp"] = poke_copy.get("hp", poke_copy.get("max_hp") or poke_copy.get("calculated_stats", {}).get("HP") or poke_copy.get("stats", {}).get("hp", 1))
    if "max_hp" not in poke_copy or poke_copy["max_hp"] is None:
        calculated_hp = poke_copy.get("calculated_stats", {}).get("HP")
        if calculated_hp:
            poke_copy["max_hp"] = calculated_hp
        else:
            poke_copy["max_hp"] = poke_copy.get("max_hp") or poke_copy.get("stats", {}).get("hp", poke_copy.get("hp", 1))
    
    return poke_copy

# get_turn_order function moved to top of file

# --- UNIFIED SETTINGS MANAGEMENT ---
async def get_effective_duel_settings(duel, user_id):
    """Get effective duel settings from temporary duel settings, user preferences, or defaults"""
    user_prefs = await get_user_preferences(user_id)
    
    # Check if duel has temporary settings
    if "settings" in duel:
        temp_settings = duel["settings"]
        return {
            'random_mode': temp_settings.get('random_mode', user_prefs.get('random_mode', False)),
            'min_level': temp_settings.get('min_level', user_prefs.get('min_level', 1)),
            'max_level': temp_settings.get('max_level', user_prefs.get('max_level', 100)),
            'min_legendary': temp_settings.get('min_legendary', user_prefs.get('min_legendary', 0)),
            'max_legendary': temp_settings.get('max_legendary', user_prefs.get('max_legendary', 6))
        }
    
    # Use user preferences as fallback
    return {
        'random_mode': user_prefs.get('random_mode', False),
        'min_level': user_prefs.get('min_level', 1),
        'max_level': user_prefs.get('max_level', 100),
        'min_legendary': user_prefs.get('min_legendary', 0),
        'max_legendary': user_prefs.get('max_legendary', 6)
    }

def safe_is_legendary_pokemon(poke):
    """Safely check if a Pokemon is legendary with comprehensive error handling"""
    try:
        # First check stored data
        if poke.get("is_legendary") or poke.get("is_mythical"):
            return True
        
        poke_id = poke.get("id")
        if not poke_id:
            return False
        
        # Try PokemonUtils lookup with error handling
        try:
            pokemon_utils = PokemonUtils()
            pokemon_data = pokemon_utils.pokemon_lookup.get(poke_id)
            if pokemon_data:
                return pokemon_data.get("is_legendary", False) or pokemon_data.get("is_mythical", False)
        except Exception as e:
            print(f"Warning: PokemonUtils lookup failed for ID {poke_id}: {e}")
        
        # Fallback: check against known legendary IDs (basic list)
        legendary_ids = {
            144, 145, 146, 150, 151,  # Gen 1 legendaries
            243, 244, 245, 249, 250, 251,  # Gen 2 legendaries
            377, 378, 379, 380, 381, 382, 383, 384, 385, 386,  # Gen 3 legendaries
            480, 481, 482, 483, 484, 485, 486, 487, 488, 489, 490, 491, 492, 493,  # Gen 4 legendaries
            494, 638, 639, 640, 641, 642, 643, 644, 645, 646, 647, 648, 649,  # Gen 5 legendaries
            716, 717, 718, 719, 720, 721,  # Gen 6 legendaries/mythicals
            772, 773, 785, 786, 787, 788, 789, 790, 791, 792, 800, 801, 802, 807, 808, 809  # Gen 7 legendaries/mythicals
        }
        
        return poke_id in legendary_ids
        
    except Exception as e:
        print(f"Error in safe_is_legendary_pokemon for {poke.get('name', 'unknown')}: {e}")
        return False  # Conservative fallback

def safe_count_legendary_pokemon(team):
    """Safely count legendary Pokemon with error handling"""
    count = 0
    for poke in team:
        try:
            if safe_is_legendary_pokemon(poke):
                count += 1
        except Exception as e:
            print(f"Error counting legendary for {poke.get('name', 'unknown')}: {e}")
            continue
    return count

def validate_team_with_settings(team, settings):
    """Validate team against all duel settings with detailed error reporting"""
    errors = []
    
    # Check legendary requirements
    legendary_count = safe_count_legendary_pokemon(team)
    min_legendary = settings.get('min_legendary', 0)
    max_legendary = settings.get('max_legendary', 6)
    
    if legendary_count < min_legendary:
        errors.append(f"Team has {legendary_count} legendary/mythical Pokemon, needs at least {min_legendary}")
    elif legendary_count > max_legendary:
        errors.append(f"Team has {legendary_count} legendary/mythical Pokemon, maximum allowed is {max_legendary}")
    
    # Check level requirements
    min_level = settings.get('min_level', 1)
    max_level = settings.get('max_level', 100)
    random_mode = settings.get('random_mode', False)
    usable_pokemon = []
    
    for poke in team:
        poke_level = poke.get("level", 1)
        hp = poke.get("hp")
        
        if hp is None:
            calculated_hp = poke.get("calculated_stats", {}).get("HP")
            if calculated_hp:
                hp = calculated_hp
            else:
                hp = poke.get("max_hp") or poke.get("stats", {}).get("hp", 1)
        
        # Check if Pokemon has moves
        active_moves = poke.get("active_moves", [])
        if not active_moves and poke.get("moves"):
            poke["active_moves"] = poke["moves"][:4]
            active_moves = poke["active_moves"]
        
        # Level check
        level_valid = min_level <= poke_level <= max_level
        
        # In random mode, all Pokemon that meet criteria are usable
        # In non-random mode, only Pokemon WITHOUT movesets are usable (movesets only allowed in random)
        if random_mode:
            # Random mode: Pokemon with moves and valid level/hp
            if level_valid and active_moves and hp > 0:
                usable_pokemon.append(poke)
        else:
            # Non-random mode: Pokemon without movesets, valid level/hp 
            if level_valid and not active_moves and hp > 0:
                usable_pokemon.append(poke)
    
    if not usable_pokemon:
        if random_mode:
            errors.append(f"No usable Pokemon at level {min_level}-{max_level}")
        else:
            errors.append("Your team doesn't follow criteria of duel. Duel can't be initiated like this")
    
    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'usable_pokemon': usable_pokemon,
        'legendary_count': legendary_count
    }

# --- UNIFIED POKEMON SELECTION ---
def get_battle_ready_pokemon(user, settings, random_mode=False):
    """Get battle-ready Pokemon with unified validation logic"""
    team = user.get("team", [])
    
    # First validate the team meets all requirements
    validation = validate_team_with_settings(team, settings)
    if not validation['valid']:
        return None, validation['errors']
    
    # Get usable Pokemon from validation
    usable_pokemon = validation['usable_pokemon']
    
    if not usable_pokemon:
        return None, ["No usable Pokemon available"]
    
    # Select Pokemon based on mode
    if random_mode:
        import random
        selected_poke = random.choice(usable_pokemon)
    else:
        selected_poke = usable_pokemon[0]  # First usable
    
    # Create deep copy and ensure proper setup
    poke_copy = copy.deepcopy(selected_poke)
    
    # Ensure moves are properly set
    poke_copy["active_moves"] = get_battle_moves(poke_copy)
    
    # Set HP properly
    if "hp" not in poke_copy or poke_copy["hp"] is None:
        poke_copy["hp"] = poke_copy.get("hp", poke_copy.get("max_hp") or poke_copy.get("calculated_stats", {}).get("HP") or poke_copy.get("stats", {}).get("hp", 1))
    if "max_hp" not in poke_copy or poke_copy["max_hp"] is None:
        calculated_hp = poke_copy.get("calculated_stats", {}).get("HP")
        if calculated_hp:
            poke_copy["max_hp"] = calculated_hp
        else:
            poke_copy["max_hp"] = poke_copy.get("max_hp") or poke_copy.get("stats", {}).get("hp", poke_copy.get("hp", 1))
    
    return poke_copy, []

# --- DUEL STATE RECOVERY ---
def recover_duel_state(duel_id):
    """Attempt to recover duel state if corruption is detected"""
    try:
        duel = duels.get(duel_id)
        if not duel:
            return False
        
        # Check for missing required fields and restore defaults
        required_fields = ['status', 'challenger_id', 'challenged_id', 'created_at']
        for field in required_fields:
            if field not in duel:
                if field == 'status':
                    duel[field] = 'pending'
                elif field == 'created_at':
                    duel[field] = time.time()
                else:
                    return False  # Can't recover without essential IDs
        
        # Clean up any corrupted state
        if 'users' in duel:
            for user_id, user_state in duel['users'].items():
                if 'user' not in user_state or 'active_poke' not in user_state:
                    # State is corrupted, remove users to force re-initialization
                    del duel['users']
                    break
        
        return True
        
    except Exception as e:
        print(f"Error recovering duel state for {duel_id}: {e}")
        return False

async def validate_duel_with_recovery(callback_query: CallbackQuery, duel_id: str):
    """Enhanced duel validation with state recovery"""
    cleanup_expired_duels()
    
    duel = duels.get(duel_id)
    if not duel:
        await callback_query.answer("❌ This duel invitation has expired or is no longer available!\n\nPlease send a new challenge to start a duel.", show_alert=True)
        return None
    
    if is_duel_expired(duel):
        duels.pop(duel_id, None)
        duel_last_action.pop(duel_id, None)
        await callback_query.answer("❌ This duel invitation has expired! Duel invitations expire after 2 minutes.\n\nPlease send a new challenge to start a duel.", show_alert=True)
        return None
    
    # Attempt state recovery if needed
    if not recover_duel_state(duel_id):
        duels.pop(duel_id, None)
        await callback_query.answer("❌ This duel has encountered an error and cannot continue.\n\nPlease send a new challenge to start a duel.", show_alert=True)
        return None
    
    return duel

