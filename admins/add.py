import re
import asyncio
from aiogram import types, Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from pokemon_utils import PokemonUtils
from database import add_pokemon_to_user, get_or_create_user
import difflib
from handlers.stats import create_info_page, create_stats_page, create_iv_ev_page, create_callback_data
import time
import logging

# Set up logging
logger = logging.getLogger(__name__)

# Admin user IDs
ADMIN_IDS = [7552373579, 7907063334,  1182033957, 1097600241, 1498348391, 7984578203, 1412946850]

router = Router()
pokemon_utils = PokemonUtils()

# Track processing states to prevent duplicate submissions
processing_adds = {}  # admin_id -> timestamp

async def cleanup_old_processing_states():
    """Remove processing states older than 30 seconds"""
    current_time = time.time()
    expired_admins = [
        admin_id for admin_id, timestamp in processing_adds.items()
        if current_time - timestamp > 30
    ]
    for admin_id in expired_admins:
        processing_adds.pop(admin_id, None)

# --- FSM States for AddPoke ---
class AddPokeStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_shiny = State()
    waiting_for_nature = State()
    waiting_for_iv_hp = State()
    waiting_for_iv_atk = State()
    waiting_for_iv_def = State()
    waiting_for_iv_spa = State()
    waiting_for_iv_spd = State()
    waiting_for_iv_spe = State()
    confirming = State()

# --- /addpoke command entry point ---
@router.message(Command("addpoke"))
async def addpoke_command(message: Message, state: FSMContext):
    try:
        if message.from_user.id not in ADMIN_IDS:
            await message.reply("You don't have permission to use this command!", parse_mode="HTML")
            return
        if not message.reply_to_message:
            await message.reply("You must reply to a user's message to add Pokémon to them!", parse_mode="HTML")
            return
        args = message.text.split()[1:]
        if not args:
            await message.reply("Usage: /addpoke <pokemon_name> [level] (reply to user)", parse_mode="HTML")
            return
        
        # Parse pokemon name and optional level
        pokemon_name = None
        level = 50  # Default level
        
        if len(args) >= 2 and args[-1].isdigit():
            # Last argument is a number, treat as level
            level = int(args[-1])
            pokemon_name = " ".join(args[:-1]).strip().lower()
        else:
            # No level specified, use default
            pokemon_name = " ".join(args).strip().lower()
        
        # Validate level
        if level < 1 or level > 100:
            await message.reply("❌ Level must be between 1 and 100!", parse_mode="HTML")
            return
        
        # Fuzzy match
        poke_names = [p['name'] for p in pokemon_utils.poke_data]
        closest = difflib.get_close_matches(pokemon_name.title(), poke_names, n=1, cutoff=0.6)
        if not pokemon_utils.get_pokemon_by_name(pokemon_name):
            if closest:
                suggested = closest[0]
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="Yes", callback_data=f"addpoke_suggested_yes_{suggested}"),
                         InlineKeyboardButton(text="No", callback_data=f"addpoke_suggested_no")]
                    ]
                )
                await message.reply(f"❌ Pokémon '{pokemon_name.title()}' not found! Did you mean: <b>{suggested}</b>?", reply_markup=keyboard, parse_mode="HTML")
                await state.set_state(AddPokeStates.waiting_for_name)
                await state.update_data(original_name=pokemon_name, admin_id=message.from_user.id, target_user_id=message.reply_to_message.from_user.id, level=level)
                return
            else:
                await message.reply(f"❌ Pokémon '{pokemon_name.title()}' not found!", parse_mode="HTML")
                return
        # Exact match, proceed
        await state.update_data(pokemon_name=pokemon_name, admin_id=message.from_user.id, target_user_id=message.reply_to_message.from_user.id, level=level, pokemon_added=False)
        await ask_shiny(message, state)
    except Exception as e:
        logger.error(f"Error in addpoke_command: {e}")
        await message.reply("❌ An error occurred. Please try again.", parse_mode="HTML")

@router.callback_query(F.data.startswith("addpoke_suggested_"))
async def handle_addpoke_suggested(callback_query: CallbackQuery, state: FSMContext):
    try:
        state_data = await state.get_data() or {}
        if callback_query.from_user.id != state_data.get('admin_id'):
            await callback_query.answer("You can't interact with this menu!", show_alert=True)
            return
        if callback_query.data.startswith("addpoke_suggested_no"):
            await callback_query.answer("Cancelled.", show_alert=True)
            # Clear any processing state
            admin_id = state_data.get('admin_id')
            if admin_id:
                processing_adds.pop(admin_id, None)
            await state.clear()
            if callback_query.message:
                await callback_query.message.edit_reply_markup(reply_markup=None)
            return
        # Yes: use suggested name
        suggested = callback_query.data.split("addpoke_suggested_yes_")[-1]
        await state.update_data(pokemon_name=suggested.lower(), pokemon_added=False)
        await ask_shiny(callback_query.message, state, edit=True)
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Error in handle_addpoke_suggested: {e}")
        await callback_query.answer("❌ An error occurred. Please try again.", show_alert=True)

async def ask_shiny(message_or_callback, state, edit=False):
    try:
        state_data = await state.get_data() or {}
        pokemon_name = state_data.get('pokemon_name')
        text = f"Is the Pokémon <b>{pokemon_name.title()}</b> shiny?"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Yes", callback_data="addpoke_shiny_yes"),
                 InlineKeyboardButton(text="No", callback_data="addpoke_shiny_no")]
            ]
        )
        if edit and hasattr(message_or_callback, 'edit_text'):
            await message_or_callback.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message_or_callback.reply(text, reply_markup=keyboard, parse_mode="HTML")
        await state.set_state(AddPokeStates.waiting_for_shiny)
    except Exception as e:
        logger.error(f"Error in ask_shiny: {e}")

@router.callback_query(F.data.startswith("addpoke_shiny_"))
async def handle_shiny(callback_query: CallbackQuery, state: FSMContext):
    try:
        state_data = await state.get_data() or {}
        if callback_query.from_user.id != state_data.get('admin_id'):
            await callback_query.answer("You can't interact with this menu!", show_alert=True)
            return
        is_shiny = callback_query.data.endswith("yes")
        await state.update_data(is_shiny=is_shiny)
        await ask_nature(callback_query.message, state, edit=True)
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Error in handle_shiny: {e}")
        await callback_query.answer("❌ An error occurred. Please try again.", show_alert=True)

async def ask_nature(message_or_callback, state, edit=False, page=0):
    try:
        natures = list(pokemon_utils.natures.keys())
        per_row = 3
        per_page = 9
        start = page * per_page
        end = start + per_page
        page_natures = natures[start:end]
        keyboard_rows = []
        for i in range(0, len(page_natures), per_row):
            row = [InlineKeyboardButton(text=n, callback_data=f"addpoke_nature_{n}") for n in page_natures[i:i+per_row]]
            keyboard_rows.append(row)
        nav_row = []
        if start > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"addpoke_nature_page_{page-1}"))
        if end < len(natures):
            nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"addpoke_nature_page_{page+1}"))
        if nav_row:
            keyboard_rows.append(nav_row)
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        text = "Choose a nature:"
        if edit and hasattr(message_or_callback, 'edit_text'):
            await message_or_callback.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message_or_callback.reply(text, reply_markup=keyboard, parse_mode="HTML")
        await state.set_state(AddPokeStates.waiting_for_nature)
    except Exception as e:
        logger.error(f"Error in ask_nature: {e}")

@router.callback_query(F.data.startswith("addpoke_nature_page_"))
async def handle_nature_page(callback_query: CallbackQuery, state: FSMContext):
    try:
        state_data = await state.get_data() or {}
        if callback_query.from_user.id != state_data.get('admin_id'):
            await callback_query.answer("You can't interact with this menu!", show_alert=True)
            return
        page = int(callback_query.data.split("addpoke_nature_page_")[-1])
        await ask_nature(callback_query.message, state, edit=True, page=page)
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Error in handle_nature_page: {e}")
        await callback_query.answer("❌ An error occurred. Please try again.", show_alert=True)

@router.callback_query(F.data.startswith("addpoke_nature_") & ~F.data.contains("page"))
async def handle_nature(callback_query: CallbackQuery, state: FSMContext):
    try:
        state_data = await state.get_data() or {}
        if callback_query.from_user.id != state_data.get('admin_id'):
            await callback_query.answer("You can't interact with this menu!", show_alert=True)
            return
        nature = callback_query.data.split("addpoke_nature_")[-1]
        await state.update_data(nature=nature)
        await ask_iv(callback_query.message, state, stat='HP', edit=True)
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Error in handle_nature: {e}")
        await callback_query.answer("❌ An error occurred. Please try again.", show_alert=True)

# --- IV selection for each stat ---
IV_STATS = [
    ('HP', AddPokeStates.waiting_for_iv_hp),
    ('Attack', AddPokeStates.waiting_for_iv_atk),
    ('Defense', AddPokeStates.waiting_for_iv_def),
    ('Sp. Attack', AddPokeStates.waiting_for_iv_spa),
    ('Sp. Defense', AddPokeStates.waiting_for_iv_spd),
    ('Speed', AddPokeStates.waiting_for_iv_spe),
]

async def ask_iv(message_or_callback, state, stat, edit=False):
    try:
        state_data = await state.get_data() or {}
        text = f"Set IV for <b>{stat}</b> (1-31):"
        keyboard_rows = []
        row = []
        for i in range(1, 32):
            row.append(InlineKeyboardButton(text=str(i), callback_data=f"addpoke_iv_{stat}_{i}"))
            if len(row) == 5:
                keyboard_rows.append(row)
                row = []
        if row:
            keyboard_rows.append(row)
        keyboard_rows.append([InlineKeyboardButton(text="No (random)", callback_data=f"addpoke_iv_{stat}_no")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        if edit and hasattr(message_or_callback, 'edit_text'):
            await message_or_callback.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message_or_callback.reply(text, reply_markup=keyboard, parse_mode="HTML")
        # Set FSM state for this stat
        for s, fsm_state in IV_STATS:
            if s == stat:
                await state.set_state(fsm_state)
                break
    except Exception as e:
        logger.error(f"Error in ask_iv: {e}")

@router.callback_query(F.data.startswith("addpoke_iv_"))
async def handle_iv(callback_query: CallbackQuery, state: FSMContext):
    try:
        state_data = await state.get_data() or {}
        if callback_query.from_user.id != state_data.get('admin_id'):
            await callback_query.answer("You can't interact with this menu!", show_alert=True)
            return
        _, _, stat, val = callback_query.data.split('_', 3)
        ivs = state_data.get('ivs', {})
        if val == 'no':
            ivs[stat] = None  # Mark as random
        else:
            ivs[stat] = int(val)
        await state.update_data(ivs=ivs)
        # Next stat or confirm
        stat_order = [s for s, _ in IV_STATS]
        idx = stat_order.index(stat)
        if idx + 1 < len(stat_order):
            next_stat = stat_order[idx + 1]
            await ask_iv(callback_query.message, state, stat=next_stat, edit=True)
        else:
            await ask_confirm(callback_query.message, state, edit=True)
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Error in handle_iv: {e}")
        await callback_query.answer("❌ An error occurred. Please try again.", show_alert=True)

async def ask_confirm(message_or_callback, state, edit=False):
    try:
        state_data = await state.get_data() or {}
        # Compose Pokémon dict for preview
        pokemon_name = state_data['pokemon_name']
        poke_data = pokemon_utils.get_pokemon_by_name(pokemon_name)
        is_shiny = state_data.get('is_shiny', False)
        nature = state_data.get('nature')
        ivs = state_data.get('ivs', {})
        
        # Fill random IVs
        for stat in ['HP', 'Attack', 'Defense', 'Sp. Attack', 'Sp. Defense', 'Speed']:
            if ivs.get(stat) is None:
                ivs[stat] = pokemon_utils.generate_boosted_iv()
        
        # Compose Pokémon dict
        level = state_data.get('level', 50)
        pokemon = pokemon_utils.create_pokemon(poke_data['id'], level)
        pokemon['is_shiny'] = is_shiny
        pokemon['nature'] = nature
        pokemon['ivs'] = ivs
        # Recalculate stats
        pokemon['calculated_stats'] = pokemon_utils.calculate_stats(pokemon, level, ivs, pokemon.get('evs', {}), nature)
        
        # Store the created Pokémon in state to avoid recreating it later
        await state.update_data(created_pokemon=pokemon)
        
        # Use stats.py helpers for formatting
        text, _ = create_info_page(pokemon, state_data['admin_id'])
        stats_text, _ = create_stats_page(pokemon, state_data['admin_id'])
        iv_text, _ = create_iv_ev_page(pokemon, state_data['admin_id'])
        text += f"\n\n{stats_text}\n\n{iv_text}"
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Confirm", callback_data="addpoke_confirm_yes"),
                 InlineKeyboardButton(text="🔙 Back", callback_data="addpoke_back")]
            ]
        )
        
        logger.info(f"[ADDPOKE DEBUG] Created confirm keyboard with callback_data: addpoke_confirm_yes")
        if edit and hasattr(message_or_callback, 'edit_text'):
            await message_or_callback.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message_or_callback.reply(text, reply_markup=keyboard, parse_mode="HTML")
        await state.set_state(AddPokeStates.confirming)
        logger.info(f"[ADDPOKE DEBUG] Set state to confirming")
        current_state = await state.get_state()
        logger.info(f"[ADDPOKE DEBUG] Current state after setting: {current_state}")
    except Exception as e:
        logger.error(f"Error in ask_confirm: {e}")

@router.callback_query(F.data == "addpoke_back")
async def handle_back(callback_query: CallbackQuery, state: FSMContext):
    try:
        logger.info(f"[ADDPOKE DEBUG] Back button pressed by user {callback_query.from_user.id}")
        logger.info(f"[ADDPOKE DEBUG] Callback data: {callback_query.data}")
        # Go back to first IV stat
        state_data = await state.get_data() or {}
        if callback_query.from_user.id != state_data.get('admin_id'):
            await callback_query.answer("You can't interact with this menu!", show_alert=True)
            return
        # Clear the created Pokémon from state since we're going back
        await state.update_data(created_pokemon=None, pokemon_added=False)
        # Clear from processing set if present
        admin_id = state_data.get('admin_id')
        if admin_id:
            processing_adds.pop(admin_id, None)
        await ask_iv(callback_query.message, state, stat='HP', edit=True)
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Error in handle_back: {e}")
        await callback_query.answer("❌ An error occurred. Please try again.", show_alert=True)

@router.callback_query(F.data == "addpoke_confirm_yes")
async def handle_confirm(callback_query: CallbackQuery, state: FSMContext):
    try:
        logger.info(f"[ADDPOKE DEBUG] Confirm button pressed by user {callback_query.from_user.id}")
        logger.info(f"[ADDPOKE DEBUG] Callback data: {callback_query.data}")
        
        current_state = await state.get_state()
        logger.info(f"[ADDPOKE DEBUG] Current FSM state: {current_state}")
        
        state_data = await state.get_data() or {}
        logger.info(f"[ADDPOKE DEBUG] State data keys: {list(state_data.keys())}")
        
        if callback_query.from_user.id != state_data.get('admin_id'):
            logger.warning(f"[ADDPOKE DEBUG] User ID mismatch: {callback_query.from_user.id} != {state_data.get('admin_id')}")
            await callback_query.answer("You can't interact with this menu!", show_alert=True)
            return
        
        # Clean up old processing states first
        await cleanup_old_processing_states()
        
        # Check if we already processed this confirmation (prevent duplicate submissions)
        if state_data.get('pokemon_added'):
            await callback_query.answer("Pokémon has already been added!", show_alert=True)
            return
        
        # Check if this admin is already processing an add operation
        admin_id = state_data.get('admin_id')
        if admin_id in processing_adds:
            await callback_query.answer("Please wait, processing previous request...", show_alert=True)
            return
        
        # Add to processing set
        processing_adds[admin_id] = time.time()
        logger.info(f"[ADDPOKE DEBUG] Added {admin_id} to processing set")
        
        try:
            # Get the Pokémon that was created in ask_confirm
            pokemon = state_data.get('created_pokemon')
            if not pokemon:
                logger.error("[ADDPOKE DEBUG] No created_pokemon found in state data")
                await callback_query.answer("Error: Pokémon data not found. Please try again.", show_alert=True)
                return
            
            # Add admin metadata
            pokemon['added_by_admin'] = True
            pokemon['added_by'] = state_data['admin_id']
            
            # Add to user
            target_user_id = state_data['target_user_id']
            logger.info(f"[ADDPOKE] Adding Pokémon: {pokemon['name']} (UUID: {pokemon.get('uuid')}) to user {target_user_id}")
            
            # First acknowledge the callback to prevent timeout
            await callback_query.answer("Processing...", show_alert=False)
            
            await get_or_create_user(target_user_id, "", "")
            success = await add_pokemon_to_user(target_user_id, pokemon)
            
            logger.info(f"[ADDPOKE] Add result: {success} for user {target_user_id}")
            
            if success:
                # Mark as added to prevent duplicate submissions
                await state.update_data(pokemon_added=True)
                
                # Verify the Pokemon was actually added by checking the collection
                from database import get_user_pokemon_collection
                collection = await get_user_pokemon_collection(target_user_id)
                added_pokemon = next((p for p in collection if p.get('uuid') == pokemon.get('uuid')), None)
                if added_pokemon:
                    logger.info(f"[ADDPOKE] Verification successful: Pokémon found in collection")
                    await callback_query.message.edit_text(f"✅ Pokémon successfully added to user's collection!\n\n**Added:** {pokemon['name'].title()} (Level {pokemon['level']})\n**UUID:** {pokemon.get('uuid')}", parse_mode="HTML")
                else:
                    logger.error(f"[ADDPOKE] Verification failed: Pokémon not found in collection")
                    await callback_query.message.edit_text(f"❌ Pokemon was reported as added but not found in collection!", parse_mode="HTML")
            else:
                logger.error(f"[ADDPOKE] Add operation failed")
                await callback_query.message.edit_text(f"❌ Failed to add Pokémon!", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error during Pokemon addition: {e}")
            await callback_query.message.edit_text(f"❌ An error occurred while adding the Pokémon: {str(e)}", parse_mode="HTML")
        finally:
            # Always remove from processing set
            processing_adds.pop(admin_id, None)
            logger.info(f"[ADDPOKE] Removed {admin_id} from processing set")
            # Clear state after completion
            await state.clear()
    except Exception as e:
        logger.error(f"Error in handle_confirm: {e}")
        try:
            await callback_query.answer("❌ An error occurred. Please try again.", show_alert=True)
        except:
            pass  # Callback might have already been answered