from aiogram import Bot, Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import asyncio
import time
from database import get_or_create_user, get_user_pokemon, update_user_pokemon_collection, get_user_inventory, update_user_inventory
from config import MISC_ITEMS
import difflib
from pokemon_utils import PokemonUtils
from handlers.evolve import auto_evolve_pokemon_if_ready, can_pokemon_evolve
from image_cache import get_cached_pokemon_image

router = Router()
pokemon_utils = PokemonUtils()

# --- Global cooldown dictionary ---
user_cooldowns = {}

# --- FSM States ---
class CandyStates(StatesGroup):
    selecting_pokemon = State()
    using_candy = State()
    confirming_evolution = State()

# --- Rare Candy Config ---
RARE_CANDY = next((item for item in MISC_ITEMS if item['name'] == 'rare-candy'), None)
RARE_CANDY_NAME = 'rare-candy'
RARE_CANDY_EMOJI = RARE_CANDY.get('emoji', '🍬') if RARE_CANDY else '🍬'

# --- Helper: Permission Check ---
async def check_user_permission(callback_query: CallbackQuery, state: FSMContext) -> bool:
    state_data = await state.get_data()
    command_user_id = state_data.get('command_user_id')
    if command_user_id and callback_query.from_user and callback_query.from_user.id != command_user_id:
        await callback_query.answer("❌ You can't interact with someone else's menu!", show_alert=True)
        return False
    return True

# --- Helper: Cooldown Check ---
async def check_cooldown(user_id: int, callback_query: CallbackQuery) -> bool:
    current_time = time.time()
    if user_id in user_cooldowns:
        if current_time - user_cooldowns[user_id] < 2.0:  # 2 second cooldown
            await callback_query.answer("⏳ Please wait a moment before using again!", show_alert=True)
            return False
    user_cooldowns[user_id] = current_time
    return True

# --- Helper: Safe message edit ---
async def safe_edit_message(callback_query: CallbackQuery, text: str, reply_markup=None):
    """Safely edit message or send alert if editing fails"""
    try:
        if (callback_query.message and 
            hasattr(callback_query.message, 'edit_text') and 
            not isinstance(callback_query.message, types.InaccessibleMessage)):
            if reply_markup:
                await callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
            else:
                await callback_query.message.edit_text(text, parse_mode="HTML")
        else:
            await callback_query.answer(text, show_alert=True)
    except Exception:
        await callback_query.answer(text, show_alert=True)

# --- Main Command Entry Point ---
@router.message(Command("candy"))
async def candy_command(message: types.Message, state: FSMContext):
    if not message.from_user:
        await message.reply("❌ User information not available!", parse_mode="HTML")
        return
    
    user_id = message.from_user.id
    
    # Get user data and Pokemon collection sequentially to avoid race conditions
    user = await get_or_create_user(user_id, getattr(message.from_user, 'username', '') or '', getattr(message.from_user, 'first_name', '') or '')
    user_pokemon = await get_user_pokemon(user_id)
    
    if not user:
        await message.reply("❌ User data not found! Please try again.", parse_mode="HTML")
        return
    if not user.get('already_started', False):
        await message.reply("❌ You need to claim your starter package first! Use /start command to begin your Pokémon journey.", parse_mode="HTML")
        return
    await state.update_data(command_user_id=user_id)
    msg_text = message.text if isinstance(message.text, str) else ''
    args = msg_text.split()[1:] if msg_text else []
    if not args:
        await message.reply(f"❌ Please specify a Pokémon name!\n\nUsage: <code>/candy &lt;pokemon_name&gt;</code>", parse_mode="HTML")
        return
    pokemon_name = " ".join(args).lower()
    if not user_pokemon or not isinstance(user_pokemon, list):
        await message.reply("❌ You don't have any Pokémon yet! Use <code>/hunt</code> to catch some first.", parse_mode="HTML")
        return
    matching_pokemon = [p for p in user_pokemon if p and isinstance(p, dict) and p.get('name', '').lower() == pokemon_name]
    if not matching_pokemon:
        user_names = list({p.get('name', '').title() for p in user_pokemon if p and isinstance(p, dict) and p.get('name', '')})
        closest = difflib.get_close_matches(pokemon_name.title(), user_names, n=1, cutoff=0.6)
        if closest:
            suggested = closest[0]
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Yes", callback_data=f"candy_suggested_yes_{suggested}"),
                        InlineKeyboardButton(text="No", callback_data=f"candy_suggested_no")
                    ]
                ]
            )
            await message.reply(
                f"❌ You don't have any <b>{pokemon_name.title()}</b> in your collection!\nDid you mean: <b>{suggested}</b>?",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await state.set_state(CandyStates.selecting_pokemon)
            await state.update_data(original_name=pokemon_name)
            return
        else:
            await message.reply(f"❌ You don't have any <b>{pokemon_name.title()}</b> in your collection!", parse_mode="HTML")
            return
    if len(matching_pokemon) == 1:
        await show_candy_menu(message, matching_pokemon[0], state, user_id)
        return
    await show_pokemon_selection(message, matching_pokemon, state)

async def show_pokemon_selection(message, pokemon_list, state):
    pokemon_name = pokemon_list[0]['name']
    text = f"🔍 You have <b>{len(pokemon_list)}</b> {pokemon_name}:\n\n"
    keyboard_rows = []
    current_row = []
    for i, pokemon in enumerate(pokemon_list, 1):
        text += f"{i}) <b>{pokemon['name']}</b> - Lv.{pokemon['level']} (UUID: {pokemon.get('uuid', 'N/A')[:8]}...)\n"
        button = InlineKeyboardButton(
            text=str(i),
            callback_data=f"candy_select_{i-1}"
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
    await state.set_state(CandyStates.selecting_pokemon)

@router.callback_query(F.data.startswith("candy_select_"))
async def handle_pokemon_select(callback_query: CallbackQuery, state: FSMContext):
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
    await show_candy_menu(callback_query.message, pokemon_list[idx], state, callback_query.from_user.id)
    await callback_query.answer()

@router.callback_query(F.data.startswith("candy_suggested_yes_"))
async def handle_suggested_yes(callback_query: CallbackQuery, state: FSMContext):
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
    if len(matching_pokemon) == 1:
        await show_candy_menu(callback_query.message, matching_pokemon[0], state, callback_query.from_user.id)
    else:
        await show_pokemon_selection(callback_query.message, matching_pokemon, state)
    await callback_query.answer()

@router.callback_query(F.data == "candy_suggested_no")
async def handle_suggested_no(callback_query: CallbackQuery, state: FSMContext):
    if not await check_user_permission(callback_query, state):
        return
    if not callback_query.from_user:
        await callback_query.answer("❌ User information not available!", show_alert=True)
        return
    if not await check_cooldown(callback_query.from_user.id, callback_query):
        return
    
    await callback_query.answer("Cancelled.", show_alert=True)
    msg = getattr(callback_query, 'message', None)
    if msg and hasattr(msg, 'edit_reply_markup') and callable(msg.edit_reply_markup):
        try:
            result = msg.edit_reply_markup(reply_markup=None)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            pass

async def show_candy_menu(message, pokemon, state, user_id=None):
    if user_id is None:
        if hasattr(message, 'from_user') and message.from_user:
            user_id = message.from_user.id
        elif hasattr(message, 'chat') and message.chat:
            user_id = message.chat.id
    
    if user_id is None:
        if hasattr(message, 'reply') and callable(getattr(message, 'reply', None)):
            await message.reply("❌ Could not determine user ID!", parse_mode="HTML")
        return
    
    # Always get fresh inventory data directly from database
    inventory = await get_user_inventory(user_id)
    
    candy_count = inventory.get(RARE_CANDY_NAME, 0)
    
    text = f"<b>{pokemon.get('name', 'Unknown')} (Lv.{pokemon.get('level', '?')})</b>\n{RARE_CANDY_EMOJI} <b>Rare Candy</b>\nYou have: <b>{candy_count}</b>"
    
    keyboard_rows = []
    if candy_count > 0:
        keyboard_rows.append([InlineKeyboardButton(text=f"Use {RARE_CANDY_EMOJI} Rare Candy", callback_data=f"candy_use_{pokemon.get('uuid')}")])
        if candy_count >= 10:
            keyboard_rows.append([InlineKeyboardButton(text=f"Use 10x {RARE_CANDY_EMOJI}", callback_data=f"candy_use_10_{pokemon.get('uuid')}")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    try:
        await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await message.reply(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(current_pokemon=pokemon)
    await state.set_state(CandyStates.using_candy)

@router.callback_query(F.data.startswith("candy_use_"))
async def handle_candy_use(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
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
    
    # Parse callback data to determine if it's bulk usage
    callback_data = callback_query.data or ''
    is_bulk = "candy_use_10_" in callback_data
    use_count = 10 if is_bulk else 1
    
    # Get user data and Pokemon collection sequentially to avoid race conditions
    chat = await bot.get_chat(user_id)
    user = await get_or_create_user(user_id, chat.username, chat.first_name)
    user_pokemon = await get_user_pokemon(user_id)
    
    # Always get fresh inventory data directly from database
    inventory = await get_user_inventory(user_id)
    candy_count = inventory.get(RARE_CANDY_NAME, 0)
    
    if candy_count < use_count:
        text = f"❌ You don't have enough {RARE_CANDY_EMOJI} Rare Candy! You need {use_count} but only have {candy_count}."
        await safe_edit_message(callback_query, text)
        return
    
    # Find Pokemon by UUID to prevent data loss
    updated_pokemon = None
    for p in user_pokemon:
        if p and p.get('uuid') == (pokemon.get('uuid') if pokemon else None):
            updated_pokemon = p
            break
    
    if not updated_pokemon:
        text = "❌ Pokémon not found!"
        await safe_edit_message(callback_query, text)
        return
    
    old_level = updated_pokemon.get('level', 1)
    if old_level >= 100:
        text = f"{updated_pokemon.get('name', 'Unknown')} is already at level 100!"
        await safe_edit_message(callback_query, text)
        return
    
    # Calculate how many candies can actually be used
    max_usable = min(use_count, candy_count, 100 - old_level)
    new_level = min(old_level + max_usable, 100)
    
    updated_pokemon['level'] = new_level
    poke_data = pokemon_utils.get_pokemon_by_name(updated_pokemon['name'])
    if poke_data:
        ivs = updated_pokemon.get('ivs', {})
        evs = updated_pokemon.get('evs', {})
        nature = updated_pokemon.get('nature', 'Hardy')
        updated_pokemon['calculated_stats'] = pokemon_utils.calculate_stats(poke_data, new_level, ivs, evs, nature)
        updated_pokemon['max_hp'] = updated_pokemon['calculated_stats'].get('HP', 1)
        updated_pokemon['current_hp'] = min(updated_pokemon.get('current_hp', updated_pokemon['max_hp']), updated_pokemon['max_hp'])
        updated_pokemon['moves'] = pokemon_utils.get_moves_for_level(poke_data['id'], new_level)
    
    inventory[RARE_CANDY_NAME] = candy_count - max_usable
    
    # Update Pokemon in collection using UUID
    for i, poke in enumerate(user_pokemon):
        if poke and updated_pokemon and poke.get('uuid') == updated_pokemon.get('uuid'):
            user_pokemon[i] = updated_pokemon
            break
    
    # --- PATCH: Also update the Pokémon in the user's team if present ---
    from database import db
    user_team = user.get('team', [])
    updated_team = False
    for i, team_poke in enumerate(user_team):
        if team_poke and updated_pokemon and team_poke.get('uuid') == updated_pokemon.get('uuid'):
            user_team[i]['level'] = updated_pokemon['level']
            user_team[i]['calculated_stats'] = updated_pokemon.get('calculated_stats', {})
            user_team[i]['max_hp'] = updated_pokemon.get('max_hp', 1)
            user_team[i]['current_hp'] = updated_pokemon.get('current_hp', user_team[i].get('current_hp', user_team[i].get('max_hp', 1)))
            user_team[i]['moves'] = updated_pokemon.get('moves', [])
            user_team[i]['ivs'] = updated_pokemon.get('ivs', {})
            user_team[i]['evs'] = updated_pokemon.get('evs', {})
            user_team[i]['nature'] = updated_pokemon.get('nature', 'Hardy')
            updated_team = True
            break
    
    # Execute database updates sequentially to avoid race conditions
    await update_user_inventory(user_id, inventory)
    await update_user_pokemon_collection(user_id, user_pokemon)
    if updated_team:
        await db.users.update_one({"user_id": user_id}, {"$set": {"team": user_team}})

    candy_text = f"{max_usable}x {RARE_CANDY_EMOJI}" if max_usable > 1 else f"{RARE_CANDY_EMOJI}"
    text = f"<b>{updated_pokemon.get('name', 'Unknown')} (Lv.{old_level} → Lv.{new_level})</b>\n{candy_text} <b>Rare Candy</b> used!\nLevel increased by {max_usable}."
    
    # Check if Pokemon can evolve after leveling up
    if can_pokemon_evolve(updated_pokemon):
        # Show evolution confirmation dialog
        await show_evolution_confirmation_candy(callback_query, updated_pokemon, state, text)
        return
    
    # Show buttons for continued usage
    keyboard_rows = []
    remaining_candy = candy_count - max_usable
    if remaining_candy > 0 and new_level < 100:
        keyboard_rows.append([InlineKeyboardButton(text=f"Use another {RARE_CANDY_EMOJI}", callback_data=f"candy_use_{updated_pokemon.get('uuid')}")])
        if remaining_candy >= 10:
            keyboard_rows.append([InlineKeyboardButton(text=f"Use 10x {RARE_CANDY_EMOJI}", callback_data=f"candy_use_10_{updated_pokemon.get('uuid')}")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    await safe_edit_message(callback_query, text, keyboard)
    await state.update_data(current_pokemon=updated_pokemon)
    await state.set_state(CandyStates.using_candy) 

# --- Evolution Confirmation Functions ---

async def show_evolution_confirmation_candy(callback_query: CallbackQuery, pokemon: dict, state: FSMContext, level_up_text: str):
    """Show evolution confirmation dialog after candy usage"""
    from handlers.evolve import evolution_data
    
    pokemon_name = pokemon.get('name', '').title()
    evolution_info = evolution_data.get(pokemon_name, {})
    evolves_to = evolution_info.get('evolves_to', 'Unknown')
    
    # Add shiny indicator
    is_shiny = pokemon.get('is_shiny', False)
    shiny_indicator = "✨ " if is_shiny else ""
    
    # Create confirmation text
    confirmation_text = f"{level_up_text}\n\n"
    confirmation_text += f"🎉 <b>Evolution Ready!</b>\n\n"
    confirmation_text += f"Your {shiny_indicator}<b>{pokemon_name}</b> is ready to evolve into <b>{evolves_to}</b>!\n\n"
    confirmation_text += f"Do you want to evolve your Pokémon?"
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Yes, Evolve!", callback_data=f"candy_evolve_yes_{pokemon.get('uuid')}"),
                InlineKeyboardButton(text="❌ Not Now", callback_data=f"candy_evolve_no_{pokemon.get('uuid')}")
            ]
        ]
    )
    
    # Get Pokemon image for the confirmation
    pokemon_id = pokemon.get('id')
    if pokemon_id and isinstance(pokemon_id, int):
        photo = get_cached_pokemon_image(pokemon_id, is_shiny)
        if photo:
            try:
                await callback_query.message.reply_photo(
                    photo=photo,
                    caption=confirmation_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except:
                await safe_edit_message(callback_query, confirmation_text, keyboard)
        else:
            await safe_edit_message(callback_query, confirmation_text, keyboard)
    else:
        await safe_edit_message(callback_query, confirmation_text, keyboard)
    
    await state.update_data(pending_evolution_pokemon=pokemon)
    await state.set_state(CandyStates.confirming_evolution)

@router.callback_query(F.data.startswith("candy_evolve_yes_"))
async def handle_candy_evolution_confirm(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
    """Handle evolution confirmation - Yes"""
    if not await check_user_permission(callback_query, state):
        return
        
    user_id = callback_query.from_user.id
    
    # Get the Pokemon from state data
    data = await state.get_data()
    pokemon = data.get('pending_evolution_pokemon')
    
    if not pokemon:
        await callback_query.answer("❌ Pokemon data not found!", show_alert=True)
        await state.clear()
        return
    
    # Evolve the Pokemon using the evolve function
    try:
        chat = await bot.get_chat(user_id)
        user = await get_or_create_user(user_id, chat.username, chat.first_name)
        evolved_pokemon = await evolve_pokemon_data(pokemon, user_id, bot)
        if not evolved_pokemon:
            await callback_query.answer("❌ Evolution failed!", show_alert=True)
            await state.clear()
            return
        
        # Get evolved Pokemon info
        evolved_name = evolved_pokemon.get('name', 'Unknown')
        evolved_id = evolved_pokemon.get('id', 0)
        is_shiny = evolved_pokemon.get('is_shiny', False)
        original_name = pokemon.get('name', 'Unknown')
        
        # Validate evolved_id
        if not isinstance(evolved_id, int) or evolved_id <= 0:
            await callback_query.answer("❌ Invalid evolution data!", show_alert=True)
            await state.clear()
            return
        
        # Show evolution result with image
        await show_evolution_result_candy(callback_query, original_name, evolved_name, evolved_id, is_shiny, state)
        
    except Exception as e:
        print(f"Error in candy evolution: {e}")
        await callback_query.answer("❌ Evolution failed!", show_alert=True)
        await state.clear()

@router.callback_query(F.data.startswith("candy_evolve_no_"))
async def handle_candy_evolution_decline(callback_query: CallbackQuery, state: FSMContext):
    """Handle evolution confirmation - No"""
    if not await check_user_permission(callback_query, state):
        return
    
    # Get the Pokemon from state data
    data = await state.get_data()
    pokemon = data.get('pending_evolution_pokemon')
    
    if not pokemon:
        await callback_query.answer("❌ Pokemon data not found!", show_alert=True)
        await state.clear()
        return
    
    # Show declined evolution message
    pokemon_name = pokemon.get('name', '').title()
    is_shiny = pokemon.get('is_shiny', False)
    shiny_indicator = "✨ " if is_shiny else ""
    
    text = f"{shiny_indicator}<b>{pokemon_name}</b> evolution cancelled.\n\n"
    text += f"You can evolve your Pokémon later using the <b>/evolve</b> command."
    
    # Show buttons for continued candy usage
    user_inventory = await get_user_inventory(callback_query.from_user.id)
    candy_count = user_inventory.get(RARE_CANDY_NAME, 0)
    
    keyboard_rows = []
    if candy_count > 0 and pokemon.get('level', 1) < 100:
        keyboard_rows.append([InlineKeyboardButton(text=f"Use another {RARE_CANDY_EMOJI}", callback_data=f"candy_use_{pokemon.get('uuid')}")])
        if candy_count >= 10:
            keyboard_rows.append([InlineKeyboardButton(text=f"Use 10x {RARE_CANDY_EMOJI}", callback_data=f"candy_use_10_{pokemon.get('uuid')}")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    await safe_edit_message(callback_query, text, keyboard)
    await state.clear()
    await callback_query.answer()

async def show_evolution_result_candy(callback_query: CallbackQuery, original_name: str, evolved_name: str, evolved_id: int, is_shiny: bool, state: FSMContext):
    """Show the evolution result with image after candy evolution"""
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
            await safe_edit_message(callback_query, text)
    else:
        await safe_edit_message(callback_query, text)
    
    await state.clear()
    await callback_query.answer("Evolution successful! 🎉")

async def evolve_pokemon_data(pokemon: dict, user_id: int, bot: Bot) -> dict:
    """Evolve Pokemon data and update in database"""
    from handlers.evolve import evolution_data
    
    pokemon_name = pokemon.get('name', '').title()
    evolution_info = evolution_data.get(pokemon_name, {})
    evolves_to = evolution_info.get('evolves_to', 'Unknown')
    
    # Get evolution target Pokemon data
    evolution_target = pokemon_utils.get_pokemon_by_name(evolves_to)
    
    if not evolution_target:
        return None
    
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
    chat = await bot.get_chat(user_id)
    user = await get_or_create_user(user_id, chat.username, chat.first_name)
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
    
    return pokemon 