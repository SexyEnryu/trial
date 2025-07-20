from __future__ import annotations

"""Wild Pokémon battle handler.

Turn-based battle system for wild encounters with detailed UI showing 
Pokemon stats, move details, HP bars, and proper battle flow.
"""

from aiogram import Router, types
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from database import (
    get_user_team, update_user_team, update_user_pokeballs, 
    get_or_create_user, add_pokemon_to_user, update_user_balance
)
from pokemon_utils import PokemonUtils
from battle_logic import apply_move, check_faint, normalize_move_name
from config import POKEBALLS
from handlers.exp_system import get_pokemon_growth_rate, get_exp_for_level, create_exp_bar
from handlers.duel import heal_team_to_full
import random
import asyncio
from datetime import datetime
from typing import Dict, Any, List
import copy

router = Router()
utils = PokemonUtils()

# In-memory store for ongoing wild battles. Keyed by user-id.
wild_battles: Dict[int, Dict[str, Any]] = {}

HP_BAR_LENGTH = 11  # characters for HP bar

# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------

def _get_move_name(move: dict) -> str:
    """Return a human-readable move name."""
    if not isinstance(move, dict):
        return "Unknown"
    return move.get("name") or move.get("move") or "Unknown"

def _build_hp_bar(current: int, maximum: int) -> str:
    """Return a visual HP bar like ███████████ with proper fill."""
    if maximum <= 0:
        maximum = 1
    current = max(0, current)
    filled = int(HP_BAR_LENGTH * current / maximum)
    empty = HP_BAR_LENGTH - filled
    
    # Create the bar with filled and empty portions
    bar = "█" * filled + "▒" * empty
    return bar

def _get_first_usable_pokemon(team: List[dict]) -> dict | None:
    """Return the first Pokémon in team that can still battle."""
    for poke in team:
        if poke.get("hp", 0) <= 0:
            continue  # fainted

        # Check for active moves
        active_moves = poke.get("active_moves") or []
        if not active_moves:
            continue  # No moves to use
        
        return poke
    return None

def _pick_random_move(poke: dict) -> dict:
    """Wild Pokemon AI - choose a random damaging move."""
    import json
    
    # Load damaging moves data
    try:
        with open('damaging_moves.json', 'r') as f:
            damaging_moves = json.load(f)
        # Create a set of normalized damaging move names for comparison
        damaging_move_names = set()
        for move_name in damaging_moves.keys():
            normalized_name = normalize_move_name(move_name)
            damaging_move_names.add(normalized_name)
    except (FileNotFoundError, json.JSONDecodeError):
        damaging_move_names = set()
    
    moves = poke.get("active_moves") or poke.get("moves") or []
    
    # Filter to only damaging moves
    damaging_moves_list = []
    for move in moves:
        move_name = move.get("name") or move.get("move", "")
        normalized_move_name = normalize_move_name(move_name)
        if normalized_move_name in damaging_move_names:
            damaging_moves_list.append(move)
    
    # If no damaging moves found, use any move as fallback
    if not damaging_moves_list:
        damaging_moves_list = moves
    
    if damaging_moves_list:
        return random.choice(damaging_moves_list)
    
    return {"name": "Struggle", "power": 50, "accuracy": 100, "type": "Normal"}

def _format_types(types_list: List[str]) -> str:
    """Format Pokemon types for display with proper capitalization."""
    if not types_list:
        return "Normal"
    return " / ".join([t.title() for t in types_list])

def _calculate_exp_gain(player_pokemon: dict, wild_pokemon: dict, victory: bool = True) -> int:
    """Calculate experience gain for a battle."""
    # Base experience calculation
    wild_level = wild_pokemon.get('level', 1)
    player_level = player_pokemon.get('level', 1)
    
    # Base exp ranges from 50-150 depending on level difference
    base_exp = min(150, max(50, 80 + (wild_level - player_level) * 5))
    
    if victory:
        # More experience for winning
        exp_gain = int(base_exp * 1.5)
    else:
        # Less experience for losing, but still gain some
        exp_gain = int(base_exp * 0.3)
    
    return max(10, exp_gain)  # Minimum 10 exp

def _calculate_participation_exp_gain(player_pokemon: dict, wild_pokemon: dict) -> int:
    """Calculate experience gain for pokemon that participated but didn't deal final blow."""
    # Base experience calculation
    wild_level = wild_pokemon.get('level', 1)
    player_level = player_pokemon.get('level', 1)
    
    # Base exp ranges from 50-150 depending on level difference
    base_exp = min(150, max(50, 80 + (wild_level - player_level) * 5))
    
    # Participation experience (less than winner but more than defeat)
    exp_gain = int(base_exp * 0.8)
    
    return max(8, exp_gain)  # Minimum 8 exp

async def _distribute_experience_to_participants(state: Dict[str, Any], victory: bool = True) -> str:
    """Distribute experience to all participating pokemon."""
    participants = state.get("participants", set())
    current_poke = state["player_poke"]
    wild_poke = state["wild_poke"]
    user_id = state["player_id"]
    
    # Make sure current pokemon is in participants
    if current_poke.get('uuid'):
        participants.add(current_poke.get('uuid'))
    
    exp_messages = []
    
    # Get team to update all pokemon
    team = state["player_team"]
    updated_pokemon = []
    
    for poke in team:
        poke_uuid = poke.get('uuid')
        if not poke_uuid or poke_uuid not in participants:
            continue
            
        # Determine experience type
        if victory and poke_uuid == current_poke.get('uuid'):
            # Winner experience for pokemon that dealt final blow
            exp_gained = _calculate_exp_gain(poke, wild_poke, victory=True)
            exp_type = "victory"
        elif not victory:
            # Defeat experience for all when losing
            exp_gained = _calculate_exp_gain(poke, wild_poke, victory=False)
            exp_type = "defeat"
        else:
            # Participation experience for pokemon that helped but didn't finish
            exp_gained = _calculate_participation_exp_gain(poke, wild_poke)
            exp_type = "participation"
        
        # Apply experience
        leveled_up, new_level, level_up_messages = _apply_experience_gain(poke, exp_gained)
        
        # Add to messages
        if exp_type == "victory":
            exp_messages.append(f"{poke['name']} gained {exp_gained} EXP for winning!")
        elif exp_type == "defeat":
            exp_messages.append(f"{poke['name']} gained {exp_gained} EXP for participating!")
        else:
            exp_messages.append(f"{poke['name']} gained {exp_gained} EXP for participating!")
        
        # Add level up messages
        for msg in level_up_messages:
            exp_messages.append(msg)
            
        updated_pokemon.append(poke)
    
    # Update all participating pokemon in database
    for poke in updated_pokemon:
        await _update_pokemon_in_team(user_id, poke)
    
    return "\n".join(exp_messages)

def _apply_experience_gain(pokemon: dict, exp_gained: int) -> tuple[bool, int, list]:
    """Apply experience gain to a Pokemon and check for level ups.
    
    Returns: (leveled_up, new_level, level_up_messages)
    """
    current_exp = pokemon.get('experience', 0)
    current_level = pokemon.get('level', 1)
    pokemon_id = pokemon.get('id', 1)
    
    # Debug logging
    print(f"DEBUG: Applying {exp_gained} exp to {pokemon.get('name', 'Unknown')} (Level {current_level}, Current exp: {current_exp})")
    
    # Initialize experience if not present
    if 'experience' not in pokemon:
        # Calculate experience for current level as a starting point
        growth_rate = get_pokemon_growth_rate(pokemon_id)
        pokemon['experience'] = get_exp_for_level(current_level, growth_rate)
        print(f"DEBUG: Initialized exp to {pokemon['experience']} for level {current_level}")
    
    # Add experience
    new_exp = current_exp + exp_gained
    pokemon['experience'] = new_exp
    
    print(f"DEBUG: New exp total: {new_exp}")
    
    # Check for level ups
    growth_rate = get_pokemon_growth_rate(pokemon_id)
    level_up_messages = []
    new_level = current_level
    leveled_up = False
    
    # Check if we can level up (max level 100)
    while new_level < 100:
        exp_needed = get_exp_for_level(new_level + 1, growth_rate)
        if new_exp >= exp_needed:
            new_level += 1
            leveled_up = True
            level_up_messages.append(f"{pokemon['name'].title()} grew to level {new_level}!")
            
            # Heal some HP on level up (25% of max HP)
            max_hp = pokemon.get('max_hp', 50)
            current_hp = pokemon.get('hp', 0)
            heal_amount = max_hp // 4
            new_hp = min(max_hp, current_hp + heal_amount)
            pokemon['hp'] = new_hp
            if heal_amount > 0:
                level_up_messages.append(f"{pokemon['name'].title()} recovered {heal_amount} HP!")
        else:
            break
    
    pokemon['level'] = new_level
    print(f"DEBUG: Final level: {new_level}, Leveled up: {leveled_up}")
    return leveled_up, new_level, level_up_messages

async def _update_pokemon_in_team(user_id: int, updated_pokemon: dict):
    """Update a specific Pokemon in the user's team."""
    team = await get_user_team(user_id) or []
    pokemon_uuid = updated_pokemon.get('uuid')
    
    if not pokemon_uuid:
        return  # Can't update without UUID
    
    # Find and update the Pokemon in the team
    for i, poke in enumerate(team):
        if poke.get('uuid') == pokemon_uuid:
            team[i] = updated_pokemon
            break
    
    await update_user_team(user_id, team)

def _format_pokemon_line(poke: dict, is_opponent: bool = False) -> str:
    """Format Pokemon display line with proper capitalization."""
    # Get types with proper capitalization
    types = poke.get("types", []) or poke.get("type", [])
    type_str = _format_types(types)
    
    # Get stats
    level = poke.get('level', 1)
    hp = poke.get('hp', 0)
    max_hp = poke.get('max_hp', 1)
    
    # Build HP bar
    bar = _build_hp_bar(hp, max_hp)
    
    # Get name with proper capitalization and make it bold
    name = poke.get('name', 'Unknown').title()
    
    if is_opponent:
        return f"Wild <b>{name}</b> [{type_str}]\nLv. {level}  •  HP {hp}/{max_hp}\n<code>{bar}</code>"
    else:
        return f"<b>{name}</b> [{type_str}]\nLv. {level}  •  HP {hp}/{max_hp}\n<code>{bar}</code>"

def _format_move_details(move: dict) -> str:
    """Format move details with proper capitalization and bold/italic formatting."""
    if not isinstance(move, dict):
        return "<b>Unknown</b>\n<i>Power: ?, Accuracy: ?</i>"
    
    # Get move info
    name = _get_move_name(move).title()
    move_type = move.get('type', 'Normal').title()
    power = move.get('power', 0) or move.get('base_power', 0)
    accuracy = move.get('accuracy', 100)
    
    # Format with proper capitalization
    return f"<b>{name}</b> [{move_type}]\n<i>Power: {str(power if power else '-').rjust(4)},     Accuracy: {str(accuracy).rjust(4)}</i>"

def _format_move_list(moves: List[dict]) -> str:
    """Format list of moves with reduced spacing."""
    return '\n'.join([_format_move_details(m) for m in moves])

def _build_battle_interface(state: Dict[str, Any]) -> str:
    """Build the main battle interface display to match duel formatting."""
    player_poke = state["player_poke"]
    wild_poke = state["wild_poke"]
    user_first_name = state["user_first_name"]
    
    lines = []
    
    # Wild Pokemon (opponent)
    lines.append(_format_pokemon_line(wild_poke, is_opponent=True))
    lines.append('')
    
    # Current turn
    lines.append(f"Current turn: {user_first_name}")
    
    # Player Pokemon
    lines.append(_format_pokemon_line(player_poke, is_opponent=False))
    lines.append('')
    
    # Only show active moves that user has selected
    active_moves = player_poke.get("active_moves", [])
    if active_moves:
        lines.append(_format_move_list(active_moves))
    else:
        lines.append("<b>No moves available!</b>")
    
    return "\n".join(lines)

def _build_keyboard(player_poke: dict, battle_id: int) -> InlineKeyboardMarkup:
    """Build the battle action keyboard with only active moves."""
    active_moves = player_poke.get("active_moves", [])
    
    # Move buttons in 2x2 grid (only active moves)
    move_buttons = []
    for idx, move in enumerate(active_moves[:4]):  # Max 4 moves
        move_buttons.append(
            InlineKeyboardButton(
                text=_get_move_name(move), 
                callback_data=f"wild_move_{battle_id}_{idx}"
            )
        )
    
    # Create grid layout for moves
    grid = []
    for i in range(0, len(move_buttons), 2):
        row = move_buttons[i:i+2]
        grid.append(row)
    
    # Action buttons row
    action_row = [
        InlineKeyboardButton(text="Pokéballs", callback_data=f"wild_ball_{battle_id}"),
        InlineKeyboardButton(text="Run", callback_data=f"wild_run_{battle_id}"),
        InlineKeyboardButton(text="Switch", callback_data=f"wild_switch_{battle_id}")
    ]
    grid.append(action_row)
    
    return InlineKeyboardMarkup(inline_keyboard=grid)

def _get_usable_pokemon_list(team: List[dict], exclude_current: dict = None) -> List[dict]:
    """Get list of usable Pokemon for switching."""
    usable = []
    current_uuid = exclude_current.get('uuid') if exclude_current else None
    
    for poke in team:
        # Skip fainted Pokemon
        if poke.get("hp", 0) <= 0:
            continue
            
        # Skip current Pokemon
        if current_uuid and poke.get('uuid') == current_uuid:
            continue
            
        # Check for active moves
        active_moves = poke.get("active_moves", [])
        if not active_moves:
            continue
            
        usable.append(poke)
    
    return usable

# -----------------------------------------------------------------------------
# Public API – called from hunt / fishing
# -----------------------------------------------------------------------------

async def start_battle(
    message: types.Message | CallbackQuery,
    user_id: int,
    wild_pokemon: dict,
) -> None:
    """Start a new wild Pokemon battle."""
    # Get user data for first name
    tg_user = message.from_user if isinstance(message, CallbackQuery) else getattr(message, 'from_user', None)
    username = getattr(tg_user, 'username', '') or '' if tg_user else ''
    first_name = getattr(tg_user, 'first_name', '') or '' if tg_user else ''

    user_data = await get_or_create_user(user_id, username, first_name)
    # Use first_name instead of username
    display_name = user_data.get('first_name') or (tg_user.first_name if tg_user else 'Trainer') or 'Trainer'
    
    # Get user's team
    user_team = await get_user_team(user_id) or []
    player_poke = _get_first_usable_pokemon(user_team)
    
    if not user_team or not player_poke:
        if isinstance(message, CallbackQuery):
            await message.answer("You don't have any usable Pokémon with moves!", show_alert=True)
        else:
            await message.reply("You don't have any usable Pokémon with moves!")
        return

    # Ensure HP stats are properly set for both Pokemon
    for poke in (player_poke, wild_pokemon):
        stats = poke.get("calculated_stats", {}) or poke.get("stats", {})
        max_hp = stats.get("HP") or stats.get("hp") or 50
        poke.setdefault("max_hp", max_hp)
        poke.setdefault("hp", max_hp)

    battle_id = random.randint(100000, 999999)
    
    # Initialize participants tracking with starting pokemon
    participants = set()
    if player_poke.get('uuid'):
        participants.add(player_poke.get('uuid'))
    
    state = {
        "battle_id": battle_id,
        "player_id": user_id,
        "player_team": user_team,
        "player_poke": player_poke,
        "wild_poke": wild_pokemon,
        "turn": "player",
        "user_first_name": display_name,
        "participants": participants  # Track all pokemon that participate in battle
    }
    wild_battles[user_id] = state

    # Send initial battle message
    initial_text = "Battle begins!"
    
    if isinstance(message, CallbackQuery):
        # Try to edit the original message
        edited = False
        try:
            await message.message.edit_text(initial_text, parse_mode="HTML")
            edited = True
        except TelegramBadRequest:
            try:
                await message.message.edit_caption(initial_text, parse_mode="HTML")
                edited = True
            except TelegramBadRequest:
                pass

        if not edited:
            await message.message.reply(initial_text, parse_mode="HTML")

        await message.answer()

        # Send the main battle interface
        battle_text = _build_battle_interface(state)
        kb = _build_keyboard(player_poke, battle_id)
        await message.message.reply(battle_text, reply_markup=kb, parse_mode="HTML")
    else:
        # Regular message
        try:
            await message.edit_text(initial_text, parse_mode="HTML")
        except TelegramBadRequest:
            try:
                await message.edit_caption(initial_text, parse_mode="HTML")
            except TelegramBadRequest:
                await message.reply(initial_text, parse_mode="HTML")

        # Send battle interface as new message
        battle_text = _build_battle_interface(state)
        kb = _build_keyboard(player_poke, battle_id)
        await message.reply(battle_text, reply_markup=kb, parse_mode="HTML")

# -----------------------------------------------------------------------------
# Player actions
# -----------------------------------------------------------------------------

@router.callback_query(lambda c: c.data and c.data.startswith("wild_move_"))
async def player_choose_move(callback_query: CallbackQuery):
    """Handle player move selection."""
    user_id = callback_query.from_user.id
    state = wild_battles.get(user_id)
    if not state or state["turn"] != "player":
        await callback_query.answer("It's not your turn or battle expired.", show_alert=True)
        return

    # Parse callback data
    data_parts = callback_query.data.split("_")
    if len(data_parts) < 4:
        await callback_query.answer("Invalid move data.", show_alert=True)
        return
    
    battle_id_str = data_parts[2]
    idx_str = data_parts[3]
    
    try:
        battle_id = int(battle_id_str)
        idx = int(idx_str)
    except ValueError:
        await callback_query.answer("Invalid move data.", show_alert=True)
        return
    
    if battle_id != state["battle_id"]:
        await callback_query.answer("Battle session expired.", show_alert=True)
        return
    
    # Only use active moves
    active_moves = state["player_poke"].get("active_moves", [])
    if idx >= len(active_moves):
        await callback_query.answer("Invalid move.", show_alert=True)
        return
    
    move = active_moves[idx]

    # Apply move
    result = apply_move(state["player_poke"], state["wild_poke"], move)
    damage = result.get("damage", 0)
    missed = result.get("missed", False)
    effectiveness = result.get("effectiveness")
    
        # Update wild Pokemon HP
    if not missed:
        old_hp = state["wild_poke"].get("hp", 0)
        new_hp = max(0, old_hp - damage)
        state["wild_poke"]["hp"] = new_hp
        # Cap damage to actual HP lost
        actual_damage = old_hp - new_hp
    else:
        actual_damage = 0

    # Build action message
    player_name = state['player_poke']['name'].title()
    move_name = _get_move_name(move).title()
    if missed:
        action_log = f"<b>{player_name}</b> used <b>{move_name}</b>.\n<b>{player_name}</b>'s attack missed!"
    else:
        action_parts = [f"<b>{player_name}</b> used <b>{move_name}</b>."]
        if effectiveness:
            action_parts.append(effectiveness)
        action_parts.append(f"Dealt {actual_damage} damage.")
        action_log = "\n".join(action_parts)
    
    # Update message to show what happened
    await callback_query.message.edit_text(action_log, parse_mode="HTML")
    await callback_query.answer()

    # Check if wild Pokemon fainted
    if check_faint(state["wild_poke"]):
        await asyncio.sleep(1.5)
        
        # Heal all Pokemon to full HP after victory
        user_id = state["player_id"]
        team = await get_user_team(user_id)
        if team:
            heal_team_to_full(team)
            await update_user_team(user_id, team)
        
        # Distribute experience to all participating pokemon (but don't show exp text)
        exp_message = await _distribute_experience_to_participants(state, victory=True)
        
        wild_name = state['wild_poke']['name'].title()
        victory_msg = f"{action_log}\n\n<b>{wild_name}</b> has been defeated!"
        
        await callback_query.message.edit_text(victory_msg, parse_mode="HTML")
        del wild_battles[user_id]
        return

    # Wild Pokemon's turn
    state["turn"] = "wild"
    await asyncio.sleep(1.5)
    
    # Show "Wild Pokemon is attacking..." message
    wild_name = state['wild_poke']['name'].title()
    await callback_query.message.edit_text(f"{action_log}\n\n<b>{wild_name}</b> is attacking...", parse_mode="HTML")
    await asyncio.sleep(1)
    
    # Wild Pokemon attacks
    await _wild_turn(callback_query.message, state)

async def _wild_turn(message: types.Message, state: Dict[str, Any]):
    """Handle wild Pokemon's turn."""
    if check_faint(state["wild_poke"]):
        return  # Already fainted

    move = _pick_random_move(state["wild_poke"])
    result = apply_move(state["wild_poke"], state["player_poke"], move)
    damage = result.get("damage", 0)
    missed = result.get("missed", False)
    effectiveness = result.get("effectiveness")
    
        # Update player Pokemon HP
    if not missed:
        old_hp = state["player_poke"].get("hp", 0)
        new_hp = max(0, old_hp - damage)
        state["player_poke"]["hp"] = new_hp
        # Cap damage to actual HP lost
        actual_damage = old_hp - new_hp
    else:
        actual_damage = 0

    # Build action message
    wild_name = state['wild_poke']['name'].title()
    move_name = _get_move_name(move).title()
    if missed:
        action_log = f"<b>{wild_name}</b> used <b>{move_name}</b>.\n<b>{wild_name}</b>'s attack missed!"
    else:
        action_parts = [f"<b>{wild_name}</b> used <b>{move_name}</b>."]
        if effectiveness:
            action_parts.append(effectiveness)
        action_parts.append(f"Dealt {actual_damage} damage.")
        action_log = "\n".join(action_parts)
    
    # Show what happened
    await message.edit_text(action_log, parse_mode="HTML")
    
    # Check if player Pokemon fainted
    if check_faint(state["player_poke"]):
        await asyncio.sleep(1.5)
        
        # Try to switch to next usable Pokemon
        usable_pokemon = _get_usable_pokemon_list(state["player_team"], state["player_poke"])
        if usable_pokemon:
            # Store fainted pokemon name before switching
            fainted_pokemon_name = state["player_poke"]["name"]
            
            # Auto-switch to next Pokemon
            next_poke = usable_pokemon[0]
            
            # Track new participant
            if next_poke.get('uuid'):
                state["participants"].add(next_poke.get('uuid'))
            
            state["player_poke"] = next_poke
            defeat_msg = f"{action_log}\n\n<b>{fainted_pokemon_name}</b> fainted!"
            defeat_msg += f"\nGo, <b>{next_poke['name'].title()}</b>!"
            await message.edit_text(defeat_msg, parse_mode="HTML")
            await asyncio.sleep(1.5)
        else:
            # Distribute experience to all participating pokemon for losing (but don't show exp text)
            exp_message = await _distribute_experience_to_participants(state, victory=False)
            
            # Heal all Pokemon to full HP even after defeat
            user_id = state["player_id"]
            team = await get_user_team(user_id)
            if team:
                heal_team_to_full(team)
                await update_user_team(user_id, team)
            
            player_name = state['player_poke']['name'].title()
            defeat_msg = f"{action_log}\n\nYour <b>{player_name}</b> fainted!\nYou have no more usable Pokémon! You ran away from the battle!"
            defeat_msg += f"\n✨ All your Pokémon have been fully healed!"
            
            await message.edit_text(defeat_msg, parse_mode="HTML")
            del wild_battles[state["player_id"]]
            return

    # Player's turn again
    state["turn"] = "player"
    await asyncio.sleep(1.5)
    
    # Show battle interface again
    battle_text = _build_battle_interface(state)
    kb = _build_keyboard(state["player_poke"], state["battle_id"])
    await message.edit_text(battle_text, reply_markup=kb, parse_mode="HTML")

# -----------------------------------------------------------------------------
# Pokeball throwing - Turn-based system
# -----------------------------------------------------------------------------

@router.callback_query(lambda c: c.data and c.data.startswith("wild_ball_"))
async def throw_pokeball(callback_query: CallbackQuery):
    """Handle pokeball selection."""
    user_id = callback_query.from_user.id
    state = wild_battles.get(user_id)
    if not state:
        await callback_query.answer("Battle expired.", show_alert=True)
        return

    # Get user pokeballs
    user_data = await get_or_create_user(user_id, "", "")
    pokeballs = user_data.get('pokeballs', {})
    
    if not pokeballs or sum(pokeballs.values()) == 0:
        await callback_query.answer("You don't have any Pokéballs!", show_alert=True)
        return
    
    # Build pokeball selection keyboard
    keyboard_rows = []
    current_row = []
    
    for pokeball in POKEBALLS:
        name = pokeball["name"]
        count = pokeballs.get(name, 0)
        
        if count > 0:
            button = InlineKeyboardButton(
                text=name, 
                callback_data=f"wild_use_ball_{state['battle_id']}_{name}"
            )
            current_row.append(button)
            
            if len(current_row) == 4:  # 4 pokeballs per row
                keyboard_rows.append(current_row)
                current_row = []
    
    if current_row:
        keyboard_rows.append(current_row)
    
    # Add back button
    keyboard_rows.append([
        InlineKeyboardButton(text="« Back to Battle", callback_data=f"wild_back_{state['battle_id']}")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    pokeball_text = "<b>Choose a Pokéball:</b>"
    
    await callback_query.message.edit_text(pokeball_text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("wild_use_ball_"))
async def use_pokeball(callback_query: CallbackQuery):
    """Handle using a specific pokeball with turn-based system."""
    user_id = callback_query.from_user.id
    state = wild_battles.get(user_id)
    if not state:
        await callback_query.answer("Battle expired.", show_alert=True)
        return

    # Parse callback data
    data_parts = callback_query.data.split("_")
    if len(data_parts) < 5:
        await callback_query.answer("Invalid pokeball data.", show_alert=True)
        return
    
    battle_id_str = data_parts[3]
    pokeball_name = "_".join(data_parts[4:])
    
    try:
        battle_id = int(battle_id_str)
    except ValueError:
        await callback_query.answer("Invalid battle data.", show_alert=True)
        return
    
    if battle_id != state["battle_id"]:
        await callback_query.answer("Battle session expired.", show_alert=True)
        return

    # Get user data and pokeballs
    user_data = await get_or_create_user(user_id, "", "")
    pokeballs = user_data.get('pokeballs', {})
    
    if pokeballs.get(pokeball_name, 0) <= 0:
        await callback_query.answer("You don't have this Pokéball!", show_alert=True)
        return
    
    # Find pokeball data
    pokeball_data = None
    for pokeball in POKEBALLS:
        if pokeball["name"] == pokeball_name:
            pokeball_data = pokeball
            break
    
    if not pokeball_data:
        await callback_query.answer("Invalid Pokéball!", show_alert=True)
        return
    
    # Calculate catch rate
    catch_rate = utils.calculate_enhanced_catch_rate(
        state["wild_poke"], 
        pokeball_data,
        'wild'
    )
    
    success = random.random() < catch_rate
    
    # Update pokeballs
    pokeballs[pokeball_name] -= 1
    await update_user_pokeballs(user_id, pokeballs)
    
    # Show throwing animation sequence
    throw_msg = f"You threw a {pokeball_name} Ball!"
    await callback_query.message.edit_text(throw_msg, parse_mode="HTML")
    await callback_query.answer()
    
    # Animation sequence: "•", then "• •", then "• • •"
    for dots in ["•", "• •", "• • •"]:
        await asyncio.sleep(2)  # Increased to 2 seconds to avoid Telegram rate limits
        animation_msg = f"{throw_msg}\n{dots}"
        await callback_query.message.edit_text(animation_msg, parse_mode="HTML")
    
    if success:
        # Pokemon caught!
        wild_pokemon = state["wild_poke"]
        wild_pokemon['captured_with'] = pokeball_name
        wild_pokemon['caught_date'] = datetime.now()
        wild_pokemon['trainer_id'] = user_id
        
        # Add to user collection and give reward
        await add_pokemon_to_user(user_id, wild_pokemon)
        await update_user_balance(user_id, 50)
        
        pokemon_name = wild_pokemon['name'].title()
        success_msg = f"🎉 You caught <b>{pokemon_name}</b>!"
        
        # Show result with view stats and release buttons
        result_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                # Removed 'View Stats' and 'Release' buttons
            ]
        ])
        
        await callback_query.message.edit_text(success_msg, reply_markup=result_keyboard, parse_mode="HTML")
        
        # Store caught pokemon data for view stats
        state['caught_pokemon'] = wild_pokemon

        # Heal team after successful catch
        await heal_team_to_full(user_id)

    else:
        # Failed to catch, wild pokemon's turn
        fail_message = f"{wild_pokemon['name'].title()} broke free!"
        await callback_query.message.edit_text(fail_message, parse_mode="HTML")
        await asyncio.sleep(1.5)
        
        # Wild Pokemon's turn after failed capture
        state["turn"] = "wild" 
        await callback_query.message.edit_text(f"{fail_message}\n\n<b>{wild_pokemon['name'].title()}</b> is attacking...", parse_mode="HTML")
        await asyncio.sleep(1)
        
        # Wild Pokemon attacks
        await _wild_turn(callback_query.message, state)

@router.callback_query(lambda c: c.data and c.data.startswith("wild_back_"))
async def back_to_battle(callback_query: CallbackQuery):
    """Return to battle interface."""
    user_id = callback_query.from_user.id
    state = wild_battles.get(user_id)
    if not state:
        await callback_query.answer("Battle expired.", show_alert=True)
        return
    
    # Show battle interface
    battle_text = _build_battle_interface(state)
    kb = _build_keyboard(state["player_poke"], state["battle_id"])
    await callback_query.message.edit_text(battle_text, reply_markup=kb, parse_mode="HTML")
    await callback_query.answer()

# -----------------------------------------------------------------------------
# Other actions
# -----------------------------------------------------------------------------

@router.callback_query(lambda c: c.data and c.data.startswith("wild_switch_"))
async def switch_pokemon(callback_query: CallbackQuery):
    """Handle Pokemon switching using duel-style logic."""
    user_id = callback_query.from_user.id
    state = wild_battles.get(user_id)
    if not state:
        await callback_query.answer("Battle expired.", show_alert=True)
        return

    # Get usable Pokemon from team (excluding current)
    usable_pokemon = _get_usable_pokemon_list(state["player_team"], state["player_poke"])
    
    if not usable_pokemon:
        await callback_query.answer("You have no other usable Pokémon!", show_alert=True)
        return
    
    # Build switch keyboard
    keyboard_rows = []
    for i, poke in enumerate(usable_pokemon[:6]):  # Show up to 6 Pokemon
        types = poke.get('types', []) or poke.get('type', [])
        type_str = '/'.join(types) if types else 'normal'
        hp = poke.get('hp', 0)
        max_hp = poke.get('max_hp', 1)
        
        button_text = f"{poke['name'].title()} (Lv.{poke.get('level', 1)}) - {hp}/{max_hp} HP"
        button = InlineKeyboardButton(
            text=button_text,
            callback_data=f"wild_switch_to_{state['battle_id']}_{i}"
        )
        keyboard_rows.append([button])
    
    # Add back button
    keyboard_rows.append([
        InlineKeyboardButton(text="« Back to Battle", callback_data=f"wild_back_{state['battle_id']}")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    switch_text = f"<b>Choose a Pokémon to switch to:</b>\n\nCurrent: <b>{state['player_poke']['name'].title()}</b> (HP: {state['player_poke'].get('hp', 0)}/{state['player_poke'].get('max_hp', 1)})"
    
    await callback_query.message.edit_text(switch_text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("wild_switch_to_"))
async def switch_to_pokemon(callback_query: CallbackQuery):
    """Handle switching to a specific Pokemon."""
    user_id = callback_query.from_user.id
    state = wild_battles.get(user_id)
    if not state:
        await callback_query.answer("Battle expired.", show_alert=True)
        return

    # Parse callback data
    data_parts = callback_query.data.split("_")
    if len(data_parts) < 5:
        await callback_query.answer("Invalid switch data.", show_alert=True)
        return
    
    try:
        battle_id = int(data_parts[3])
        poke_idx = int(data_parts[4])
    except ValueError:
        await callback_query.answer("Invalid switch data.", show_alert=True)
        return
    
    if battle_id != state["battle_id"]:
        await callback_query.answer("Battle session expired.", show_alert=True)
        return

    # Get usable Pokemon
    usable_pokemon = _get_usable_pokemon_list(state["player_team"], state["player_poke"])
    
    if poke_idx >= len(usable_pokemon):
        await callback_query.answer("Invalid Pokémon selection.", show_alert=True)
        return
    
    new_poke = usable_pokemon[poke_idx]
    old_poke = state["player_poke"]
    
    # Track new participant
    if new_poke.get('uuid'):
        state["participants"].add(new_poke.get('uuid'))
    
    # Switch Pokemon
    state["player_poke"] = new_poke
    
    # Show switch message
    switch_msg = f"{old_poke['name']}, come back!\nGo, {new_poke['name']}!"
    await callback_query.message.edit_text(switch_msg, parse_mode="HTML")
    await callback_query.answer()
    
    # Wild Pokemon attacks after switch (user loses turn)
    state["turn"] = "wild"
    await asyncio.sleep(1.5)
    
    await callback_query.message.edit_text(f"{switch_msg}\n\n{state['wild_poke']['name']} is attacking...", parse_mode="HTML")
    await asyncio.sleep(1)
    
    await _wild_turn(callback_query.message, state)

@router.callback_query(lambda c: c.data and c.data.startswith("wild_run_"))
async def run_away(callback_query: CallbackQuery):
    """Handle running away from battle with flee chance."""
    user_id = callback_query.from_user.id
    state = wild_battles.get(user_id)
    if not state:
        await callback_query.answer("Battle expired.", show_alert=True)
        return
    
    # Calculate flee chance based on speed difference
    player_speed = state["player_poke"].get("calculated_stats", {}).get("Speed", 50)
    wild_speed = state["wild_poke"].get("calculated_stats", {}).get("Speed", 50)
    
    # Base flee chance is 50%, modified by speed difference
    base_chance = 0.5
    speed_modifier = (player_speed - wild_speed) * 0.01  # 1% per speed point difference
    flee_chance = min(0.9, max(0.1, base_chance + speed_modifier))  # Between 10% and 90%
    
    success = random.random() < flee_chance
    
    if success:
        # Successfully fled - heal all Pokemon to full HP
        team = await get_user_team(user_id)
        if team:
            heal_team_to_full(team)
            await update_user_team(user_id, team)
        
        await callback_query.message.edit_text("You successfully ran away from the battle!\n✨ All your Pokémon have been fully healed!")
        del wild_battles[user_id]
    else:
        # Failed to flee - wild Pokemon attacks
        flee_msg = "You couldn't get away!"
        await callback_query.message.edit_text(flee_msg, parse_mode="HTML")
        await asyncio.sleep(1.5)
        
        # Wild Pokemon's turn after failed flee
        state["turn"] = "wild"
        await callback_query.message.edit_text(f"{flee_msg}\n\n{state['wild_poke']['name']} is attacking...", parse_mode="HTML")
        await asyncio.sleep(1)
        
        # Wild Pokemon attacks
        await _wild_turn(callback_query.message, state)
    
    await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("wild_view_stats_"))
async def view_wild_caught_stats(callback_query: CallbackQuery):
    """Show stats of pokemon caught in wild battle."""
    user_id = callback_query.from_user.id
    state = wild_battles.get(user_id)
    if not state:
        await callback_query.answer("Battle session expired.", show_alert=True)
        return

    # Parse battle ID
    try:
        battle_id = int(callback_query.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback_query.answer("Invalid battle data.", show_alert=True)
        return
    
    if battle_id != state["battle_id"]:
        await callback_query.answer("Battle session expired.", show_alert=True)
        return

    caught_pokemon = state.get('caught_pokemon')
    if not caught_pokemon:
        await callback_query.answer("No caught pokemon data found.", show_alert=True)
        return

    pokemon_name = caught_pokemon['name'].title()
    types = caught_pokemon.get('types', [])
    types_display = " / ".join([t.title() for t in types]) if types else "Normal"
    nature = caught_pokemon.get('nature', 'Hardy')
    level = caught_pokemon.get('level', 1)
    
    stats = caught_pokemon.get('calculated_stats', {})
    stats_text = "\n".join([
        f"<b>HP:</b> {stats.get('HP', 0)}",
        f"<b>Attack:</b> {stats.get('Attack', 0)}",
        f"<b>Defense:</b> {stats.get('Defense', 0)}",
        f"<b>Sp. Attack:</b> {stats.get('Sp. Attack', 0)}",
        f"<b>Sp. Defense:</b> {stats.get('Sp. Defense', 0)}",
        f"<b>Speed:</b> {stats.get('Speed', 0)}"
    ])
    
    stats_msg = f"<b>{pokemon_name}</b> (Lv. {level})\n"
    stats_msg += f"<b>Type:</b> {types_display}\n"
    stats_msg += f"<b>Nature:</b> {nature.title()}\n\n"
    stats_msg += f"<b>Stats:</b>\n{stats_text}"
    
    # Return button
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Back", callback_data=f"wild_back_to_result_{battle_id}")]
    ])
    
    await callback_query.message.edit_text(stats_msg, reply_markup=back_kb, parse_mode="HTML")
    await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("wild_release_"))
async def release_wild_caught_pokemon(callback_query: CallbackQuery):
    """Release pokemon caught in wild battle."""
    user_id = callback_query.from_user.id
    state = wild_battles.get(user_id)
    if not state:
        await callback_query.answer("Battle session expired.", show_alert=True)
        return

    # Parse battle ID
    try:
        battle_id = int(callback_query.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback_query.answer("Invalid battle data.", show_alert=True)
        return
    
    if battle_id != state["battle_id"]:
        await callback_query.answer("Battle session expired.", show_alert=True)
        return

    caught_pokemon = state.get('caught_pokemon')
    if not caught_pokemon:
        await callback_query.answer("No caught pokemon data found.", show_alert=True)
        return

    # Note: Pokemon release functionality would need database implementation
    # For now, just show the release message
    pokemon_name = caught_pokemon['name'].title()
    release_msg = f"You released <b>{pokemon_name}</b> back into the wild.\n\nGoodbye, <b>{pokemon_name}</b>!"
    
    # Heal all Pokemon to full HP after releasing caught Pokemon
    team = await get_user_team(user_id)
    if team:
        heal_team_to_full(team)
        await update_user_team(user_id, team)
    
    release_msg += f"\n✨ All your Pokémon have been fully healed!"
    await callback_query.message.edit_text(release_msg, parse_mode="HTML")
    
    # Cleanup battle session
    del wild_battles[user_id]
    await callback_query.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("wild_back_to_result_"))
async def back_to_wild_result(callback_query: CallbackQuery):
    """Return to catch result screen in wild battle."""
    user_id = callback_query.from_user.id
    state = wild_battles.get(user_id)
    if not state:
        await callback_query.answer("Battle session expired.", show_alert=True)
        return

    # Parse battle ID
    try:
        battle_id = int(callback_query.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback_query.answer("Invalid battle data.", show_alert=True)
        return
    
    if battle_id != state["battle_id"]:
        await callback_query.answer("Battle session expired.", show_alert=True)
        return

    caught_pokemon = state.get('caught_pokemon')
    if not caught_pokemon:
        await callback_query.answer("No caught pokemon data found.", show_alert=True)
        return

    pokemon_name = caught_pokemon['name'].title()
    success_msg = f"🎉 You caught <b>{pokemon_name}</b>!"
    
    # Show result with view stats and release buttons
    result_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="View Stats", callback_data=f"wild_view_stats_{battle_id}"),
            InlineKeyboardButton(text="Release", callback_data=f"wild_release_{battle_id}")
        ]
    ])
    
    await callback_query.message.edit_text(success_msg, reply_markup=result_keyboard, parse_mode="HTML")
    await callback_query.answer()
