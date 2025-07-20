import asyncio
import time
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database import get_or_create_user, get_user_pokemon, update_user_pokemon_collection, get_user_inventory, update_user_inventory
from config import BERRIES, VITAMINS
import difflib

router = Router()

# --- Global cooldown dictionary ---
user_cooldowns = {}

# --- FSM States ---
class BerryVitaminStates(StatesGroup):
    selecting_pokemon = State()
    selecting_item = State()
    using_item = State()

# --- Helper: Find stat for berry/vitamin ---
BERRY_STAT_MAP = {
    "pomeg-berry": "HP",
    "kelpsy-berry": "Attack",
    "qualot-berry": "Defense",
    "hondew-berry": "Sp. Attack",
    "grepa-berry": "Sp. Defense",
    "tamato-berry": "Speed",
}
VITAMIN_STAT_MAP = {
    "hp-up": "HP",
    "protein": "Attack",
    "iron": "Defense",
    "calcium": "Sp. Attack",
    "zinc": "Sp. Defense",
    "carbos": "Speed",
}

# --- Helper function to check if user can interact with buttons ---
async def check_user_permission(callback_query: CallbackQuery, state: FSMContext) -> bool:
    """Check if the user who clicked the button is the same as the command initiator"""
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

# --- Main command entry points ---
@router.message(Command("berry"))
async def berry_command(message: types.Message, state: FSMContext):
    await handle_item_command(message, state, is_berry=True)

@router.message(Command("vitamin"))
async def vitamin_command(message: types.Message, state: FSMContext):
    await handle_item_command(message, state, is_berry=False)

async def handle_item_command(message, state, is_berry):
    if not message.from_user:
        await message.reply("❌ User information not available!", parse_mode="HTML")
        return
    
    user_id = message.from_user.id
    
    # Get user data and Pokemon collection sequentially to avoid race conditions
    user = await get_or_create_user(user_id, message.from_user.username or "", message.from_user.first_name or "")
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
    if isinstance(msg_text, str) and msg_text:
        msg_split = msg_text.split()
    else:
        msg_split = []
    args = msg_split[1:] if len(msg_split) > 1 else []
    if not args:
        await message.reply(f"❌ Please specify a Pokémon name!\n\nUsage: <code>/{'berry' if is_berry else 'vitamin'} &lt;pokemon_name&gt;</code>", parse_mode="HTML")
        return
    pokemon_name = " ".join(args).lower()
    if not user_pokemon or not isinstance(user_pokemon, list):
        await message.reply("❌ You don't have any Pokémon yet! Use <code>/hunt</code> to catch some first.", parse_mode="HTML")
        return
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
                        InlineKeyboardButton(text="Yes", callback_data=f"item_suggested_yes_{suggested}"),
                        InlineKeyboardButton(text="No", callback_data=f"item_suggested_no")
                    ]
                ]
            )
            await message.reply(
                f"❌ You don't have any <b>{pokemon_name.title()}</b> in your collection!\nDid you mean: <b>{suggested}</b>?",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await state.set_state(BerryVitaminStates.selecting_pokemon)
            await state.update_data(is_berry=is_berry, original_name=pokemon_name)
            return
        else:
            await message.reply(f"❌ You don't have any <b>{pokemon_name.title()}</b> in your collection!", parse_mode="HTML")
            return
    if len(matching_pokemon) == 1:
        await show_item_menu(message, matching_pokemon[0], state, is_berry)
        return
    # Multiple Pokémon selection
    await show_pokemon_selection(message, matching_pokemon, state, is_berry)

async def show_pokemon_selection(message, pokemon_list, state, is_berry):
    pokemon_name = pokemon_list[0]['name']
    text = f"🔍 You have <b>{len(pokemon_list)}</b> {pokemon_name}:\n\n"
    keyboard_rows = []
    current_row = []
    for i, pokemon in enumerate(pokemon_list, 1):
        text += f"{i}) <b>{pokemon['name']}</b> - Lv.{pokemon['level']} (UUID: {pokemon.get('uuid', 'N/A')[:8]}...)\n"
        button = InlineKeyboardButton(
            text=str(i),
            callback_data=f"item_select_{i-1}"
        )
        current_row.append(button)
        if len(current_row) == 5:
            keyboard_rows.append(current_row)
            current_row = []
    if current_row:
        keyboard_rows.append(current_row)
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await message.reply(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(pokemon_list=pokemon_list, is_berry=is_berry)
    await state.set_state(BerryVitaminStates.selecting_pokemon)

@router.callback_query(F.data.startswith("item_select_"))
async def handle_pokemon_select(callback_query: CallbackQuery, state: FSMContext):
    # Check if user has permission to interact with this button
    if not await check_user_permission(callback_query, state):
        return
    if not callback_query.from_user:
        await callback_query.answer("❌ User information not available!", show_alert=True)
        return
    if not await check_cooldown(callback_query.from_user.id, callback_query):
        return
    
    state_data = await state.get_data() or {}
    pokemon_list = state_data.get('pokemon_list')
    is_berry = state_data.get('is_berry', True)
    
    if not callback_query.data:
        await callback_query.answer("❌ Invalid selection!", show_alert=True)
        return
    
    try:
        idx = int(callback_query.data.split('_')[-1])
    except (ValueError, IndexError):
        await callback_query.answer("❌ Invalid selection!", show_alert=True)
        return
    
    if not pokemon_list or idx >= len(pokemon_list):
        await callback_query.answer("❌ Invalid selection!", show_alert=True)
        return
    await show_item_menu(callback_query.message, pokemon_list[idx], state, is_berry)
    await callback_query.answer()

@router.callback_query(F.data.startswith("item_suggested_yes_"))
async def handle_suggested_yes(callback_query: CallbackQuery, state: FSMContext):
    # Check if user has permission to interact with this button
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
    state_data = await state.get_data() or {}
    is_berry = state_data.get('is_berry', True)
    user_id = callback_query.from_user.id
    user_pokemon = await get_user_pokemon(user_id)
    matching_pokemon = [p for p in user_pokemon if p and p.get('name', '').lower() == suggested.lower()]
    if not matching_pokemon:
        await callback_query.answer("You don't have this Pokémon!", show_alert=True)
        return
    if len(matching_pokemon) == 1:
        await show_item_menu(callback_query.message, matching_pokemon[0], state, is_berry)
    else:
        await show_pokemon_selection(callback_query.message, matching_pokemon, state, is_berry)
    await callback_query.answer()

@router.callback_query(F.data == "item_suggested_no")
async def handle_suggested_no(callback_query: CallbackQuery, state: FSMContext):
    # Check if user has permission to interact with this button
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

async def show_item_menu(message, pokemon, state, is_berry):
    # Fixed user_id extraction
    user_id = None
    if hasattr(message, 'from_user') and message.from_user:
        user_id = message.from_user.id
    elif hasattr(message, 'chat') and message.chat:
        user_id = message.chat.id
    
    if user_id is None:
        # If we still can't get user_id, try to get it from the message object differently
        if hasattr(message, 'reply_to_message') and message.reply_to_message:
            user_id = message.reply_to_message.from_user.id
        else:
            # Last resort: return error
            error_msg = "❌ Could not determine user ID!"
            if hasattr(message, 'reply'):
                await message.reply(error_msg, parse_mode="HTML")
            elif hasattr(message, 'answer'):
                await message.answer(error_msg, parse_mode="HTML")
            return
    
    items = BERRIES if is_berry else VITAMINS
    item_map = BERRY_STAT_MAP if is_berry else VITAMIN_STAT_MAP
    
    try:
        inventory = await get_user_inventory(user_id)
        if not isinstance(inventory, dict):
            inventory = {}
    except Exception as e:
        print(f"Error getting user inventory: {e}")
        inventory = {}
    
    text = f"<b>{pokemon.get('name', 'Unknown')} (Lv.{pokemon.get('level', '?')})</b>\n"
    text += f"Current EVs: {pokemon.get('evs', {})}\n"
    text += f"Select a {'berry' if is_berry else 'vitamin'} to use:\n\n"
    
    keyboard_rows = []
    current_row = []
    
    for item in items:
        name = item['name']
        stat = item_map[name]
        amount = inventory.get(name, 0)
        btn_text = f"{name.replace('-', ' ').title()}"
        desc = item['effect']
        
        current_row.append(InlineKeyboardButton(text=btn_text, callback_data=f"item_use_{name}"))
        
        # Create rows with 3 buttons for the first row, then 2 buttons for subsequent rows
        if len(current_row) == 3 and len(keyboard_rows) == 0:
            keyboard_rows.append(current_row)
            current_row = []
        elif len(current_row) == 2 and len(keyboard_rows) > 0:
            keyboard_rows.append(current_row)
            current_row = []
        
        text += f"<b>{name.replace('-', ' ').title()}</b> ({stat}): {desc} <i>(You have: {amount})</i>\n"
    
    # Add any remaining buttons
    if current_row:
        keyboard_rows.append(current_row)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    # Send the message
    try:
        if hasattr(message, 'reply'):
            await message.reply(text, reply_markup=keyboard, parse_mode="HTML")
        elif hasattr(message, 'edit_text'):
            await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        print(f"Error sending item menu: {e}")
        return
    
    await state.update_data(current_pokemon=pokemon, is_berry=is_berry)
    await state.set_state(BerryVitaminStates.using_item)

@router.callback_query(F.data.startswith("item_use_"))
async def handle_item_use(callback_query: CallbackQuery, state: FSMContext):
    # Check if user has permission to interact with this button
    if not await check_user_permission(callback_query, state):
        return
    if not callback_query.from_user:
        await callback_query.answer("❌ User information not available!", show_alert=True)
        return
    if not await check_cooldown(callback_query.from_user.id, callback_query):
        return
    
    state_data = await state.get_data() or {}
    pokemon = state_data.get('current_pokemon')
    is_berry = state_data.get('is_berry', True)
    user_id = callback_query.from_user.id
    
    if not callback_query.data:
        await callback_query.answer("❌ Invalid data!", show_alert=True)
        return
    
    # Parse callback data to determine if it's bulk usage
    callback_data = callback_query.data
    is_bulk = "_10_" in callback_data
    use_count = 10 if is_bulk else 1
    
    # Extract item name
    if is_bulk:
        item_name = callback_data.replace("item_use_10_", "")
    else:
        item_name = callback_data.replace("item_use_", "")
    
    item_map = BERRY_STAT_MAP if is_berry else VITAMIN_STAT_MAP
    stat = item_map.get(item_name, None)
    
    if not stat:
        await callback_query.answer("❌ Invalid item!", show_alert=True)
        return
    
    try:
        inventory = await get_user_inventory(user_id)
        if not isinstance(inventory, dict):
            inventory = {}
    except Exception as e:
        print(f"Error getting user inventory: {e}")
        inventory = {}
    
    amount = inventory.get(item_name, 0)
    if amount < use_count:
        await callback_query.answer(f"You don't have enough {item_name.replace('-', ' ').title()}! You need {use_count} but only have {amount}.", show_alert=True)
        return
    
    # Get fresh Pokemon data using UUID to prevent data loss
    user_pokemon = await get_user_pokemon(user_id)
    if not isinstance(user_pokemon, list):
        user_pokemon = []
    
    # Find Pokemon by UUID
    updated_pokemon = None
    for p in user_pokemon:
        if p and p.get('uuid') == (pokemon.get('uuid') if pokemon else None):
            updated_pokemon = p
            break
    
    if not updated_pokemon:
        await callback_query.answer("❌ Pokemon not found!", show_alert=True)
        return
    
    # Update EVs
    evs = updated_pokemon.get('evs', {})
    old_val = evs.get(stat, 0)
    
    if is_berry:
        # Berry reduces EVs by 5 per use (or 10 per use for bulk)
        reduction = 5 * use_count
        new_val = max(0, old_val - reduction)
        actual_change = old_val - new_val
        actual_uses = min(use_count, amount, (old_val + 4) // 5)  # How many can actually be used
    else:
        # Vitamin: max 252 per stat, 510 total
        total_evs = sum(evs.values())
        addable_per_stat = 252 - old_val
        addable_total = 510 - total_evs
        
        # Check if any EVs can be added
        max_addable = min(addable_per_stat, addable_total)
        if max_addable <= 0:
            await callback_query.answer(f"Cannot increase {stat} EVs further!", show_alert=True)
            return
        
        # Calculate how many vitamins can actually be used
        # Each vitamin normally adds 5 EVs, but can add less if near the cap
        actual_uses = 0
        actual_addition = 0
        
        for i in range(min(use_count, amount)):
            if actual_addition + 5 <= max_addable:
                # Can add full 5 EVs
                actual_addition += 5
                actual_uses += 1
            elif actual_addition < max_addable:
                # Can only add partial EVs to reach the cap
                actual_addition = max_addable
                actual_uses += 1
                break
            else:
                break
        
        if actual_uses <= 0:
            await callback_query.answer(f"Cannot increase {stat} EVs further!", show_alert=True)
            return
        
        new_val = old_val + actual_addition
        actual_change = actual_addition
    
    # Apply the changes
    evs[stat] = new_val
    updated_pokemon['evs'] = evs
    
    # Update user inventory
    inventory[item_name] = amount - actual_uses
    
    # Update Pokemon in collection using UUID
    for i, poke in enumerate(user_pokemon):
        if poke and updated_pokemon and poke.get('uuid') == updated_pokemon.get('uuid'):
            user_pokemon[i] = updated_pokemon
            break
    
    # Update team data if Pokemon is in team
    from database import db
    user = await get_or_create_user(user_id, '', '')
    user_team = user.get('team', [])
    updated_team = False
    for i, team_poke in enumerate(user_team):
        if team_poke and updated_pokemon and team_poke.get('uuid') == updated_pokemon.get('uuid'):
            user_team[i]['evs'] = updated_pokemon.get('evs', {})
            updated_team = True
            break
    
    # Execute inventory, Pokemon collection, and team updates sequentially to avoid race conditions
    await update_user_inventory(user_id, inventory)
    await update_user_pokemon_collection(user_id, user_pokemon)
    if updated_team:
        await db.users.update_one({"user_id": user_id}, {"$set": {"team": user_team}})
    
    # Show confirmation and "use another" button
    item_text = f"{actual_uses}x {item_name.replace('-', ' ').title()}" if actual_uses > 1 else f"{item_name.replace('-', ' ').title()}"
    change_text = f"decreased by {actual_change}" if is_berry else f"increased by {actual_change}"
    text = f"<b>{updated_pokemon.get('name', 'Unknown')} (Lv.{updated_pokemon.get('level', '?')})</b>\n{item_text} used!\n{stat} EVs: {old_val} → {new_val} ({change_text})"
    
    keyboard_rows = []
    remaining_items = amount - actual_uses
    
    # Add single use button
    if remaining_items > 0:
        keyboard_rows.append([InlineKeyboardButton(text=f"Use another {item_name.replace('-', ' ').title()}", callback_data=f"item_use_{item_name}")])
    
    # Add bulk use button if enough items
    if remaining_items >= 10:
        keyboard_rows.append([InlineKeyboardButton(text=f"Use 10x {item_name.replace('-', ' ').title()}", callback_data=f"item_use_10_{item_name}")])
    
    # Add back button
    keyboard_rows.append([InlineKeyboardButton(text="Back", callback_data="item_back")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    try:
        if callback_query.message and hasattr(callback_query.message, 'edit_text'):
            await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        elif callback_query.message and hasattr(callback_query.message, 'reply'):
            await callback_query.message.reply(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        print(f"Error editing message: {e}")
    
    await state.update_data(current_pokemon=updated_pokemon, is_berry=is_berry)
    await callback_query.answer()

@router.callback_query(F.data == "item_back")
async def handle_item_back(callback_query: CallbackQuery, state: FSMContext):
    # Check if user has permission to interact with this button
    if not await check_user_permission(callback_query, state):
        return
    if not callback_query.from_user:
        await callback_query.answer("❌ User information not available!", show_alert=True)
        return
    if not await check_cooldown(callback_query.from_user.id, callback_query):
        return
    
    state_data = await state.get_data() or {}
    pokemon = state_data.get('current_pokemon')
    is_berry = state_data.get('is_berry', True)
    await show_item_menu(callback_query.message, pokemon, state, is_berry)
    await callback_query.answer()