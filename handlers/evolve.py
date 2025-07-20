import asyncio
import json
import time
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database import get_or_create_user, get_user_pokemon, update_user_pokemon_collection
from pokemon_utils import PokemonUtils
from image_cache import get_cached_pokemon_image
import difflib

router = Router()
pokemon_utils = PokemonUtils()

# --- Global cooldown dictionary ---
user_cooldowns = {}

# --- FSM States ---
class EvolveStates(StatesGroup):
    selecting_pokemon = State()
    confirming_evolution = State()

# --- Load evolution data ---
def load_evolution_data():
    """Load evolution data from evolve.json (cached)"""
    from config import get_evolution_data
    return get_evolution_data()

evolution_data = load_evolution_data()

# --- Helper function to check if user can interact with buttons ---
async def check_user_permission(callback_query: CallbackQuery, state: FSMContext) -> bool:
    """Check if the user who clicked the button is the same as the command initiator"""
    state_data = await state.get_data()
    command_user_id = state_data.get('command_user_id')
    
    if command_user_id and callback_query.from_user and callback_query.from_user.id != command_user_id:
        await callback_query.answer("❌ You can't interact with someone else's menu!", show_alert=True)
        return False
    return True

# --- Helper function to check cooldown ---
async def check_cooldown(user_id: int, callback_query: CallbackQuery) -> bool:
    """Check if user is on cooldown"""
    current_time = time.time()
    if user_id in user_cooldowns:
        if current_time - user_cooldowns[user_id] < 2:  # 2 second cooldown
            await callback_query.answer("⏳ Please wait a moment before using this again.", show_alert=True)
            return False
    
    user_cooldowns[user_id] = current_time
    return True

# --- Main Command Entry Point ---
@router.message(Command("evolve"))
async def evolve_command(message: types.Message, state: FSMContext):
    if not message.from_user:
        await message.reply("❌ User information not available!", parse_mode="HTML")
        return
    
    user_id = message.from_user.id
    
    # Get user data and Pokemon collection
    user = await get_or_create_user(user_id, getattr(message.from_user, 'username', '') or '', getattr(message.from_user, 'first_name', '') or '')
    user_pokemon = await get_user_pokemon(user_id)
    
    if not user:
        await message.reply("❌ User data not found! Please try again.", parse_mode="HTML")
        return
    if not user.get('already_started', False):
        await message.reply("❌ You need to claim your starter package first! Use /start command to begin your Pokémon journey.", parse_mode="HTML")
        return
    
    # Store the command initiator's user ID in state
    await state.update_data(command_user_id=user_id)
    
    msg_text = message.text if isinstance(message.text, str) else ''
    args = msg_text.split()[1:] if msg_text else []
    
    if not args:
        await message.reply(f"❌ Please specify a Pokémon name!\n\nUsage: <code>/evolve &lt;pokemon_name&gt;</code>", parse_mode="HTML")
        return
    
    pokemon_name = " ".join(args).lower()
    
    if not user_pokemon or not isinstance(user_pokemon, list):
        await message.reply("❌ You don't have any Pokémon yet! Use <code>/hunt</code> to catch some first.", parse_mode="HTML")
        return
    
    # Find matching Pokemon
    matching_pokemon = [p for p in user_pokemon if p and isinstance(p, dict) and p.get('name', '').lower() == pokemon_name]
    
    if not matching_pokemon:
        # Fuzzy match suggestion
        user_names = list({p.get('name', '').title() for p in user_pokemon if p and isinstance(p, dict) and p.get('name', '')})
        closest = difflib.get_close_matches(pokemon_name.title(), user_names, n=1, cutoff=0.6)
        if closest:
            suggested = closest[0]
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Yes", callback_data=f"evolve_suggested_yes_{suggested}"),
                        InlineKeyboardButton(text="No", callback_data=f"evolve_suggested_no")
                    ]
                ]
            )
            await message.reply(
                f"❌ You don't have any <b>{pokemon_name.title()}</b> in your collection!\nDid you mean: <b>{suggested}</b>?",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await state.set_state(EvolveStates.selecting_pokemon)
            await state.update_data(original_name=pokemon_name)
            return
        else:
            await message.reply(f"❌ You don't have any <b>{pokemon_name.title()}</b> in your collection!", parse_mode="HTML")
            return
    
    # Check if Pokemon can evolve
    evolvable_pokemon = []
    for pokemon in matching_pokemon:
        if can_pokemon_evolve(pokemon):
            evolvable_pokemon.append(pokemon)
    
    if not evolvable_pokemon:
        # Get the actual Pokemon name from the first match for better display
        actual_pokemon_name = matching_pokemon[0].get('name', pokemon_name.title())
        await message.reply(f"❌ None of your <b>{actual_pokemon_name}</b> can evolve right now!", parse_mode="HTML")
        return
    
    if len(evolvable_pokemon) == 1:
        await show_evolution_confirmation(message, evolvable_pokemon[0], state, user_id)
        return
    
    # Multiple Pokemon selection
    await show_pokemon_selection(message, evolvable_pokemon, state)

def can_pokemon_evolve(pokemon: dict) -> bool:
    """Check if a Pokemon can evolve based on evolve.json requirements"""
    pokemon_name = pokemon.get('name', '').title()  # Ensure proper capitalization
    pokemon_level = pokemon.get('level', 1)
    
    # Check if Pokemon has evolution data
    if pokemon_name not in evolution_data:
        return False
    
    evolution_info = evolution_data[pokemon_name]
    method = evolution_info.get('method', '')
    
    if method == 'level':
        required_level = evolution_info.get('level', 50)
        return pokemon_level >= required_level
    else:
        # For non-level methods, set requirement to level 50
        return pokemon_level >= 50

async def show_pokemon_selection(message, pokemon_list, state):
    """Show Pokemon selection interface"""
    pokemon_name = pokemon_list[0]['name']
    text = f"🔍 You have <b>{len(pokemon_list)}</b> {pokemon_name} that can evolve:\n\n"
    
    keyboard_rows = []
    current_row = []
    
    for i, pokemon in enumerate(pokemon_list, 1):
        # Fix case sensitivity for evolution data lookup
        pokemon_name = pokemon['name'].title()
        evolution_info = evolution_data.get(pokemon_name, {})
        method = evolution_info.get('method', '')
        evolves_to = evolution_info.get('evolves_to', 'Unknown')
        
        if method == 'level':
            required_level = evolution_info.get('level', 50)
            requirement_text = f"Req: Lv.{required_level}"
        else:
            requirement_text = "Req: Lv.50"
        
        # Add shiny emoji indicator if Pokemon is shiny
        is_shiny = pokemon.get('is_shiny', False)
        shiny_indicator = "✨ " if is_shiny else ""
        
        # Remove UUID for better user experience
        text += f"{i}) {shiny_indicator}<b>{pokemon['name']}</b> - Lv.{pokemon['level']} ({requirement_text}) → {evolves_to}\n"
        
        button = InlineKeyboardButton(
            text=str(i),
            callback_data=f"evolve_select_{i-1}"
        )
        current_row.append(button)
        
        if len(current_row) == 5:
            keyboard_rows.append(current_row)
            current_row = []
    
    if current_row:
        keyboard_rows.append(current_row)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await message.reply(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(pokemon_list=pokemon_list)
    await state.set_state(EvolveStates.selecting_pokemon)

async def show_evolution_confirmation(message, pokemon, state, user_id):
    """Show evolution confirmation dialog"""
    pokemon_name = pokemon.get('name', '').title()  # Ensure proper capitalization
    evolution_info = evolution_data.get(pokemon_name, {})
    evolves_to = evolution_info.get('evolves_to', 'Unknown')
    
    # Add shiny indicator to the text
    is_shiny = pokemon.get('is_shiny', False)
    shiny_indicator = "✨ " if is_shiny else ""
    
    text = f"🔄 <b>Evolution Confirmation</b>\n\n"
    text += f"{shiny_indicator}<b>{pokemon_name}</b> (Lv.{pokemon['level']}) wants to evolve into <b>{evolves_to}</b>!\n\n"
    text += f"Are you sure you want to evolve this Pokémon?"
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Yes, Evolve!", callback_data=f"evolve_confirm_{pokemon.get('uuid')}"),
                InlineKeyboardButton(text="❌ Cancel", callback_data="evolve_cancel")
            ]
        ]
    )
    
    # Get Pokemon image for the confirmation
    pokemon_id = pokemon.get('id')
    if pokemon_id and isinstance(pokemon_id, int):
        photo = get_cached_pokemon_image(pokemon_id, is_shiny)
        if photo:
            try:
                await message.reply_photo(
                    photo=photo,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except:
                await message.reply(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message.reply(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await message.reply(text, reply_markup=keyboard, parse_mode="HTML")
    
    await state.update_data(current_pokemon=pokemon)
    await state.set_state(EvolveStates.confirming_evolution)

@router.callback_query(F.data.startswith("evolve_select_"))
async def handle_pokemon_select(callback_query: CallbackQuery, state: FSMContext):
    """Handle Pokemon selection from list"""
    if not await check_user_permission(callback_query, state):
        return
    if not callback_query.from_user:
        await callback_query.answer("❌ User information not available!", show_alert=True)
        return
    if not await check_cooldown(callback_query.from_user.id, callback_query):
        return
    
    state_data = await state.get_data() or {}
    pokemon_list = state_data.get('pokemon_list')
    data = callback_query.data or ''
    
    if not pokemon_list or not isinstance(pokemon_list, list):
        await callback_query.answer("❌ Invalid selection!", show_alert=True)
        return
    
    try:
        idx = int(data.split('_')[-1])
    except Exception:
        await callback_query.answer("❌ Invalid selection!", show_alert=True)
        return
    
    if idx >= len(pokemon_list):
        await callback_query.answer("❌ Invalid selection!", show_alert=True)
        return
    
    await show_evolution_confirmation(callback_query.message, pokemon_list[idx], state, callback_query.from_user.id)
    await callback_query.answer()

@router.callback_query(F.data.startswith("evolve_suggested_yes_"))
async def handle_suggested_yes(callback_query: CallbackQuery, state: FSMContext):
    """Handle suggested Pokemon name confirmation"""
    if not await check_user_permission(callback_query, state):
        return
    if not callback_query.from_user:
        await callback_query.answer("❌ User information not available!", show_alert=True)
        return
    if not callback_query.data:
        await callback_query.answer("❌ Invalid data!", show_alert=True)
        return
    if not await check_cooldown(callback_query.from_user.id, callback_query):
        return
    
    suggested = callback_query.data.split('_', 3)[-1]
    user_id = callback_query.from_user.id
    user_pokemon = await get_user_pokemon(user_id)
    
    matching_pokemon = [p for p in user_pokemon if p and p.get('name', '').lower() == suggested.lower()]
    
    if not matching_pokemon:
        await callback_query.answer("You don't have this Pokémon!", show_alert=True)
        return
    
    # Check if any can evolve
    evolvable_pokemon = [p for p in matching_pokemon if can_pokemon_evolve(p)]
    
    if not evolvable_pokemon:
        await callback_query.answer(f"None of your {suggested} can evolve right now!", show_alert=True)
        return
    
    if len(evolvable_pokemon) == 1:
        await show_evolution_confirmation(callback_query.message, evolvable_pokemon[0], state, callback_query.from_user.id)
    else:
        await show_pokemon_selection(callback_query.message, evolvable_pokemon, state)
    
    await callback_query.answer()

@router.callback_query(F.data.startswith("evolve_suggested_no"))
async def handle_suggested_no(callback_query: CallbackQuery, state: FSMContext):
    """Handle suggested Pokemon name rejection"""
    if not await check_user_permission(callback_query, state):
        return
    
    await callback_query.message.edit_text("❌ Evolution cancelled.", parse_mode="HTML")
    await state.clear()
    await callback_query.answer()

# --- Auto Evolution Functions ---

async def check_and_evolve_pokemon(pokemon: dict, user_id: int) -> dict:
    """
    Check if a Pokemon can evolve and evolve it automatically.
    Returns the evolved Pokemon or the original if no evolution occurred.
    """
    if not can_pokemon_evolve(pokemon):
        return pokemon
    
    # Pokemon can evolve, let's evolve it
    pokemon_name = pokemon.get('name', '').title()  # Ensure proper capitalization
    evolution_info = evolution_data.get(pokemon_name, {})
    evolved_name = evolution_info.get('evolves_to', '')
    
    if not evolved_name:
        return pokemon
    
    # Find evolved Pokemon data
    evolved_pokemon_data = pokemon_utils.get_pokemon_by_name(evolved_name)
    
    if not evolved_pokemon_data:
        return pokemon
    
    # Preserve original Pokemon data but update key fields
    evolved_pokemon = pokemon.copy()
    evolved_pokemon['name'] = evolved_name
    evolved_pokemon['id'] = evolved_pokemon_data['id']
    evolved_pokemon['types'] = evolved_pokemon_data.get('types', [])
    evolved_pokemon['base_stats'] = evolved_pokemon_data.get('base_stats', {})
    evolved_pokemon['species'] = evolved_pokemon_data.get('name', '')
    evolved_pokemon['description'] = evolved_pokemon_data.get('description', '')
    
    # Handle shiny status - if original was shiny, evolved should be too
    is_shiny = pokemon.get('is_shiny', False)
    evolved_pokemon['is_shiny'] = is_shiny
    
    # Update image path based on shiny status
    pokemon_utils.update_pokemon_image_path(evolved_pokemon)
    
    # Recalculate stats with new base stats
    ivs = evolved_pokemon.get('ivs', {})
    evs = evolved_pokemon.get('evs', {})
    nature = evolved_pokemon.get('nature', 'Hardy')
    level = evolved_pokemon.get('level', 1)
    
    calculated_stats = pokemon_utils.calculate_stats(evolved_pokemon_data, level, ivs, evs, nature)
    evolved_pokemon['calculated_stats'] = calculated_stats
    evolved_pokemon['max_hp'] = calculated_stats.get('HP', 1)
    evolved_pokemon['current_hp'] = min(evolved_pokemon.get('current_hp', evolved_pokemon['max_hp']), evolved_pokemon['max_hp'])
    
    # Update moves for new level
    evolved_pokemon['moves'] = pokemon_utils.get_moves_for_level(evolved_pokemon_data['id'], level)
    
    return evolved_pokemon

async def auto_evolve_pokemon_if_ready(pokemon: dict, user_id: int) -> tuple[dict, bool]:
    """
    Check if a Pokemon should auto-evolve and evolve it.
    Returns (pokemon, evolved_flag) where evolved_flag is True if evolution occurred.
    """
    original_name = pokemon.get('name', '')
    evolved_pokemon = await check_and_evolve_pokemon(pokemon, user_id)
    
    if evolved_pokemon.get('name', '') != original_name:
        return evolved_pokemon, True
    
    return pokemon, False

@router.callback_query(F.data.startswith("evolve_confirm_"))
async def handle_evolution_confirm(callback_query: CallbackQuery, state: FSMContext):
    """Handle evolution confirmation"""
    if not await check_user_permission(callback_query, state):
        return
    if not callback_query.from_user:
        await callback_query.answer("❌ User information not available!", show_alert=True)
        return
    if not await check_cooldown(callback_query.from_user.id, callback_query):
        return
    
    state_data = await state.get_data() or {}
    pokemon = state_data.get('current_pokemon')
    user_id = callback_query.from_user.id
    
    if not pokemon:
        await callback_query.answer("❌ Pokemon not found!", show_alert=True)
        return
    
    # Get fresh Pokemon data
    user_pokemon = await get_user_pokemon(user_id)
    updated_pokemon = None
    
    for p in user_pokemon:
        if p and p.get('uuid') == pokemon.get('uuid'):
            updated_pokemon = p
            break
    
    if not updated_pokemon:
        await callback_query.answer("❌ Pokemon not found!", show_alert=True)
        return
    
    # Double-check evolution requirements
    if not can_pokemon_evolve(updated_pokemon):
        await callback_query.answer("❌ This Pokemon can no longer evolve!", show_alert=True)
        return
    
    # Perform evolution
    await evolve_pokemon(callback_query, updated_pokemon, user_id, state)

async def evolve_pokemon(callback_query: CallbackQuery, pokemon: dict, user_id: int, state: FSMContext):
    """Perform the actual evolution"""
    pokemon_name = pokemon.get('name', '').title()  # Ensure proper capitalization
    evolution_info = evolution_data.get(pokemon_name, {})
    evolves_to = evolution_info.get('evolves_to', 'Unknown')
    
    # Get evolution target Pokemon data
    evolution_target = pokemon_utils.get_pokemon_by_name(evolves_to)
    
    if not evolution_target:
        await callback_query.answer("❌ Evolution target not found!", show_alert=True)
        return
    
    # Store original name for message
    original_name = pokemon['name']
    
    # Update Pokemon data
    pokemon['name'] = evolves_to
    pokemon['id'] = evolution_target['id']
    pokemon['types'] = evolution_target.get('types', [])
    pokemon['base_stats'] = evolution_target.get('base_stats', {})
    
    # Recalculate stats
    ivs = pokemon.get('ivs', {})
    evs = pokemon.get('evs', {})
    nature = pokemon.get('nature', 'Hardy')
    level = pokemon.get('level', 1)
    
    pokemon['calculated_stats'] = pokemon_utils.calculate_stats(evolution_target, level, ivs, evs, nature)
    pokemon['max_hp'] = pokemon['calculated_stats'].get('HP', 1)
    pokemon['current_hp'] = min(pokemon.get('current_hp', pokemon['max_hp']), pokemon['max_hp'])
    
    # Update moves
    pokemon['moves'] = pokemon_utils.get_moves_for_level(evolution_target['id'], level)
    
    # Update image path based on shiny status
    pokemon_utils.update_pokemon_image_path(pokemon)
    
    # Update Pokemon in collection
    user_pokemon = await get_user_pokemon(user_id)
    for i, p in enumerate(user_pokemon):
        if p and p.get('uuid') == pokemon.get('uuid'):
            user_pokemon[i] = pokemon
            break
    
    # Update team if Pokemon is in team
    from database import db
    user = await get_or_create_user(user_id, '', '')
    user_team = user.get('team', [])
    updated_team = False
    
    for i, team_poke in enumerate(user_team):
        if team_poke and team_poke.get('uuid') == pokemon.get('uuid'):
            user_team[i] = pokemon.copy()
            updated_team = True
            break
    
    # Update database
    await update_user_pokemon_collection(user_id, user_pokemon)
    if updated_team:
        await db.users.update_one({"user_id": user_id}, {"$set": {"team": user_team}})
    
    # Show evolution result
    is_shiny = pokemon.get('is_shiny', False)
    await show_evolution_result(callback_query, original_name, evolves_to, evolution_target['id'], is_shiny, state)

async def show_evolution_result(callback_query: CallbackQuery, original_name: str, evolved_name: str, evolved_id: int, is_shiny: bool, state: FSMContext):
    """Show the evolution result with image"""
    # Add shiny indicator to the text
    shiny_indicator = "✨ " if is_shiny else ""
    
    text = f"🎉 <b>Evolution Complete!</b>\n\n"
    text += f"<b>{original_name}</b> evolved into {shiny_indicator}<b>{evolved_name}</b>!"
    
    # Get evolution image with correct shiny status
    evolution_image = get_cached_pokemon_image(evolved_id, is_shiny)
    
    if evolution_image:
        try:
            await callback_query.message.delete()
            await callback_query.message.answer_photo(
                photo=evolution_image,
                caption=text,
                parse_mode="HTML"
            )
        except:
            await callback_query.message.edit_text(text, parse_mode="HTML")
    else:
        await callback_query.message.edit_text(text, parse_mode="HTML")
    
    await state.clear()
    await callback_query.answer("Evolution successful! 🎉")

@router.callback_query(F.data == "evolve_cancel")
async def handle_evolution_cancel(callback_query: CallbackQuery, state: FSMContext):
    """Handle evolution cancellation"""
    if not await check_user_permission(callback_query, state):
        return
    
    await callback_query.message.edit_text("❌ Evolution cancelled.", parse_mode="HTML")
    await state.clear()
    await callback_query.answer() 