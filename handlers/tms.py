from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database import get_or_create_user, get_user_tms, get_user_pokemon, remove_tm_from_user, update_pokemon_moveset
from pokemon_utils import PokemonUtils
from handlers.myteam import sync_team_with_collection

router = Router()
pokemon_utils = PokemonUtils()

@router.message(Command("tms"))
async def tms_command(message: types.Message):
    """Show user's TMs with pagination"""
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or ""
    user = await get_or_create_user(user_id, username, first_name)
    
    user_tms = await get_user_tms(user_id)
    
    # Get TM data and sort by TM number
    tm_list = []
    for tm_id, quantity in user_tms.items():
        if quantity > 0:
            tm_data = pokemon_utils.get_tm_by_id(tm_id)
            if tm_data:
                tm_number = int(tm_id.replace('tm', ''))
                tm_list.append((tm_number, tm_id, tm_data, quantity))
    
    # Sort by TM number (ascending)
    tm_list.sort(key=lambda x: x[0])
    
    if not tm_list:
        await message.reply("❌ You don't have any TMs in your inventory!")
        return
    
    # Show first page
    await show_tm_page(message, tm_list, user_id, page=0, edit=False)

async def show_tm_page(message_or_callback, tm_list, user_id, page=0, edit=True):
    """Show TM page with pagination"""
    tms_per_page = 10
    total_tms = len(tm_list)
    total_pages = (total_tms - 1) // tms_per_page + 1 if total_tms > 0 else 1
    
    # Ensure page is within bounds
    page = max(0, min(page, total_pages - 1))
    
    start = page * tms_per_page
    end = start + tms_per_page
    tms_to_show = tm_list[start:end]
    
    text = f"<b>🎯 Your TMs Collection</b>\n\n"
    text += f"<b>Page {page + 1}/{total_pages}</b>\n\n"
    
    keyboard_rows = []
    
    # Create TM buttons (2 per row)
    for i in range(0, len(tms_to_show), 2):
        row = []
        for j in range(2):
            if i + j < len(tms_to_show):
                tm_number, tm_id, tm_data, quantity = tms_to_show[i + j]
                name = tm_data.get('name', 'Unknown')
                type_name = tm_data.get('type', 'Unknown')
                category = tm_data.get('category', 'Unknown')
                power = tm_data.get('power', 0)
                accuracy = tm_data.get('accuracy', 0)
                
                power_str = str(power) if power and power > 0 else "—"
                accuracy_str = f"{accuracy}%" if accuracy else "—"
                
                text += f"<b>TM{tm_number} - {name}</b>\n"
                text += f"Type: {type_name} | Category: {category}\n"
                text += f"Power: {power_str} | Accuracy: {accuracy_str}\n"
                text += f"Quantity: {quantity}\n\n"
                
                row.append(InlineKeyboardButton(
                    text=f"TM{tm_number}",
                    callback_data=f"tm_select_{tm_id}_{user_id}"
                ))
        if row:
            keyboard_rows.append(row)
    
    # Pagination buttons
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(
            text="⬅️ Previous",
            callback_data=f"tm_page_{user_id}_{page-1}"
        ))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(
            text="Next ➡️",
            callback_data=f"tm_page_{user_id}_{page+1}"
        ))
    
    if nav_row:
        keyboard_rows.append(nav_row)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    if edit and hasattr(message_or_callback, 'message'):
        await message_or_callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await message_or_callback.reply(text, reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(lambda c: c.data.startswith("tm_"))
async def tm_callback(callback_query: CallbackQuery):
    """Handle TM-related callbacks"""
    user_id = callback_query.from_user.id
    data_parts = callback_query.data.split("_")
    
    # Check if user is authorized - handle different callback formats
    if len(data_parts) > 2:
        try:
            # For different callback formats, user_id is in different positions:
            # tm_page_{user_id}_{page} -> user_id at index 2
            # tm_select_{tm_id}_{user_id} -> user_id at index 3
            # tm_learners_{tm_id}_{user_id}_{page} -> user_id at index 3
            # tm_learn_{tm_id}_{pokemon_index}_{user_id} -> user_id at index 4
            # tm_confirm_{tm_id}_{pokemon_index}_{user_id} -> user_id at index 4
            # tm_back_{user_id}_{page} -> user_id at index 2
            
            callback_user_id = None
            
            if data_parts[1] == "page":
                # tm_page_{user_id}_{page}
                callback_user_id = int(data_parts[2])
            elif data_parts[1] == "select":
                # tm_select_{tm_id}_{user_id}
                callback_user_id = int(data_parts[3])
            elif data_parts[1] == "learners":
                # tm_learners_{tm_id}_{user_id}_{page}
                callback_user_id = int(data_parts[3])
            elif data_parts[1] == "learn":
                # tm_learn_{tm_id}_{pokemon_index}_{user_id}
                callback_user_id = int(data_parts[4])
            elif data_parts[1] == "confirm":
                # tm_confirm_{tm_id}_{pokemon_index}_{user_id}
                callback_user_id = int(data_parts[4])
            elif data_parts[1] == "back":
                # tm_back_{user_id}_{page}
                callback_user_id = int(data_parts[2])
            
            if callback_user_id and callback_user_id != user_id:
                await callback_query.answer("❌ This is not your TM collection!", show_alert=True)
                return
                
        except (ValueError, IndexError):
            await callback_query.answer("❌ Invalid callback data!", show_alert=True)
            return
    
    username = callback_query.from_user.username or ""
    first_name = callback_query.from_user.first_name or ""
    user = await get_or_create_user(user_id, username, first_name)
    
    if data_parts[1] == "page":
        # Handle pagination
        try:
            page = int(data_parts[3])
        except (ValueError, IndexError):
            page = 0
        
        user_tms = await get_user_tms(user_id)
        
        # Get TM data and sort by TM number
        tm_list = []
        for tm_id, quantity in user_tms.items():
            if quantity > 0:
                tm_data = pokemon_utils.get_tm_by_id(tm_id)
                if tm_data:
                    tm_number = int(tm_id.replace('tm', ''))
                    tm_list.append((tm_number, tm_id, tm_data, quantity))
        
        # Sort by TM number (ascending)
        tm_list.sort(key=lambda x: x[0])
        
        if not tm_list:
            await callback_query.answer("❌ You don't have any TMs!", show_alert=True)
            return
        
        await show_tm_page(callback_query, tm_list, user_id, page=page, edit=True)
    
    elif data_parts[1] == "select":
        # Show Pokemon that can learn this TM
        tm_id = data_parts[2]
        await show_tm_learners(callback_query, tm_id, user_id, page=0)
    
    elif data_parts[1] == "learners":
        # Handle Pokemon learners pagination
        tm_id = data_parts[2]
        try:
            page = int(data_parts[4])
        except (ValueError, IndexError):
            page = 0
        
        await show_tm_learners(callback_query, tm_id, user_id, page=page)
    
    elif data_parts[1] == "learn":
        # Handle learning TM
        tm_id = data_parts[2]
        try:
            pokemon_index = int(data_parts[3])
        except (ValueError, IndexError):
            await callback_query.answer("❌ Invalid Pokemon selection!", show_alert=True)
            return
        
        await confirm_tm_learning(callback_query, tm_id, pokemon_index, user_id)
    
    elif data_parts[1] == "confirm":
        # Confirm learning TM
        tm_id = data_parts[2]
        try:
            pokemon_index = int(data_parts[3])
        except (ValueError, IndexError):
            await callback_query.answer("❌ Invalid Pokemon selection!", show_alert=True)
            return
        
        await execute_tm_learning(callback_query, tm_id, pokemon_index, user_id)
    
    elif data_parts[1] == "back":
        # Back to TM list
        try:
            page = int(data_parts[3])
        except (ValueError, IndexError):
            page = 0
        
        user_tms = await get_user_tms(user_id)
        
        # Get TM data and sort by TM number
        tm_list = []
        for tm_id, quantity in user_tms.items():
            if quantity > 0:
                tm_data = pokemon_utils.get_tm_by_id(tm_id)
                if tm_data:
                    tm_number = int(tm_id.replace('tm', ''))
                    tm_list.append((tm_number, tm_id, tm_data, quantity))
        
        # Sort by TM number (ascending)
        tm_list.sort(key=lambda x: x[0])
        
        if not tm_list:
            await callback_query.answer("❌ You don't have any TMs!", show_alert=True)
            return
        
        await show_tm_page(callback_query, tm_list, user_id, page=page, edit=True)
    
    await callback_query.answer()

async def show_tm_learners(callback_query: CallbackQuery, tm_id: str, user_id: int, page: int = 0):
    """Show Pokemon that can learn the selected TM"""
    tm_data = pokemon_utils.get_tm_by_id(tm_id)
    if not tm_data:
        await callback_query.answer("❌ TM not found!", show_alert=True)
        return
    
    # Get user's Pokemon
    user_pokemon = await get_user_pokemon(user_id)
    if not user_pokemon:
        await callback_query.answer("❌ You don't have any Pokemon!", show_alert=True)
        return
    
    # Find which user Pokemon can learn this TM
    compatible_pokemon = pokemon_utils.get_user_pokemon_that_can_learn_tm(tm_id, user_pokemon)
    
    if not compatible_pokemon:
        tm_number = tm_id.replace('tm', '')
        name = tm_data.get('name', 'Unknown')
        await callback_query.answer(f"❌ None of your Pokemon can learn TM{tm_number} - {name}!", show_alert=True)
        return
    
    # Pagination
    pokemon_per_page = 20
    total_pokemon = len(compatible_pokemon)
    total_pages = (total_pokemon - 1) // pokemon_per_page + 1 if total_pokemon > 0 else 1
    
    # Ensure page is within bounds
    page = max(0, min(page, total_pages - 1))
    
    start = page * pokemon_per_page
    end = start + pokemon_per_page
    pokemon_to_show = compatible_pokemon[start:end]
    
    tm_number = tm_id.replace('tm', '')
    name = tm_data.get('name', 'Unknown')
    type_name = tm_data.get('type', 'Unknown')
    category = tm_data.get('category', 'Unknown')
    power = tm_data.get('power', 0)
    accuracy = tm_data.get('accuracy', 0)
    
    power_str = str(power) if power and power > 0 else "—"
    accuracy_str = f"{accuracy}%" if accuracy else "—"
    
    text = f"<b>🎯 TM{tm_number} - {name}</b>\n\n"
    text += f"Type: {type_name} | Category: {category}\n"
    text += f"Power: {power_str} | Accuracy: {accuracy_str}\n\n"
    text += f"<b>Your Pokemon that can learn this move:</b>\n"
    text += f"Page {page + 1}/{total_pages}\n\n"
    
    keyboard_rows = []
    
    # Create Pokemon buttons (2 per row)
    for i in range(0, len(pokemon_to_show), 2):
        row = []
        for j in range(2):
            if i + j < len(pokemon_to_show):
                pokemon = pokemon_to_show[i + j]
                pokemon_name = pokemon.get('name', 'Unknown')
                pokemon_level = pokemon.get('level', 1)
                is_shiny = pokemon.get('is_shiny', False)
                
                display_name = f"✨ {pokemon_name}" if is_shiny else pokemon_name
                
                # Find the original index in user's Pokemon list
                original_index = -1
                for idx, user_poke in enumerate(user_pokemon):
                    if user_poke.get('uuid') == pokemon.get('uuid'):
                        original_index = idx
                        break
                
                if original_index == -1:
                    continue
                
                text += f"{original_index + 1}. {display_name} (Lv.{pokemon_level})\n"
                
                row.append(InlineKeyboardButton(
                    text=f"{original_index + 1}",
                    callback_data=f"tm_learn_{tm_id}_{original_index}_{user_id}"
                ))
        if row:
            keyboard_rows.append(row)
    
    # Pagination buttons
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(
            text="⬅️ Previous",
            callback_data=f"tm_learners_{tm_id}_{user_id}_{page-1}"
        ))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(
            text="Next ➡️",
            callback_data=f"tm_learners_{tm_id}_{user_id}_{page+1}"
        ))
    
    if nav_row:
        keyboard_rows.append(nav_row)
    
    # Back button
    keyboard_rows.append([InlineKeyboardButton(
        text="⬅️ Back to TMs",
        callback_data=f"tm_back_{user_id}_0"
    )])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

async def confirm_tm_learning(callback_query: CallbackQuery, tm_id: str, pokemon_index: int, user_id: int):
    """Show confirmation for TM learning"""
    tm_data = pokemon_utils.get_tm_by_id(tm_id)
    if not tm_data:
        await callback_query.answer("❌ TM not found!", show_alert=True)
        return
    
    user_pokemon = await get_user_pokemon(user_id)
    if not user_pokemon or pokemon_index >= len(user_pokemon):
        await callback_query.answer("❌ Pokemon not found!", show_alert=True)
        return
    
    pokemon = user_pokemon[pokemon_index]
    
    tm_number = tm_id.replace('tm', '')
    name = tm_data.get('name', 'Unknown')
    type_name = tm_data.get('type', 'Unknown')
    category = tm_data.get('category', 'Unknown')
    power = tm_data.get('power', 0)
    accuracy = tm_data.get('accuracy', 0)
    
    power_str = str(power) if power and power > 0 else "—"
    accuracy_str = f"{accuracy}%" if accuracy else "—"
    
    pokemon_name = pokemon.get('name', 'Unknown')
    pokemon_level = pokemon.get('level', 1)
    is_shiny = pokemon.get('is_shiny', False)
    
    display_name = f"✨ {pokemon_name}" if is_shiny else pokemon_name
    
    text = f"<b>🎯 Confirm TM Learning</b>\n\n"
    text += f"<b>TM{tm_number} - {name}</b>\n"
    text += f"Type: {type_name} | Category: {category}\n"
    text += f"Power: {power_str} | Accuracy: {accuracy_str}\n\n"
    text += f"<b>Pokemon:</b> {display_name} (Lv.{pokemon_level})\n\n"
    text += f"⚠️ <b>Are you sure you want {display_name} to learn {name}?</b>\n"
    text += f"This will remove the TM from your inventory."
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Yes, Learn Move",
                callback_data=f"tm_confirm_{tm_id}_{pokemon_index}_{user_id}"
            ),
            InlineKeyboardButton(
                text="❌ Cancel",
                callback_data=f"tm_learners_{tm_id}_{user_id}_0"
            )
        ]
    ])
    
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

async def execute_tm_learning(callback_query: CallbackQuery, tm_id: str, pokemon_index: int, user_id: int):
    """Execute the TM learning process"""
    # Show immediate feedback - answer the callback first
    await callback_query.answer("🔄 Teaching move...")
    
    tm_data = pokemon_utils.get_tm_by_id(tm_id)
    if not tm_data:
        error_text = "❌ <b>Error:</b> TM not found!"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back to TMs", callback_data=f"tm_back_{user_id}_0")]
        ])
        await callback_query.message.edit_text(error_text, reply_markup=keyboard, parse_mode="HTML")
        return
    
    user_pokemon = await get_user_pokemon(user_id)
    if not user_pokemon or pokemon_index >= len(user_pokemon):
        error_text = "❌ <b>Error:</b> Pokemon not found!"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back to TMs", callback_data=f"tm_back_{user_id}_0")]
        ])
        await callback_query.message.edit_text(error_text, reply_markup=keyboard, parse_mode="HTML")
        return
    
    pokemon = user_pokemon[pokemon_index]
    
    # Check if user has this TM
    user_tms = await get_user_tms(user_id)
    if tm_id not in user_tms or user_tms[tm_id] <= 0:
        error_text = "❌ <b>Error:</b> You don't have this TM!"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back to TMs", callback_data=f"tm_back_{user_id}_0")]
        ])
        await callback_query.message.edit_text(error_text, reply_markup=keyboard, parse_mode="HTML")
        return
    
    # Check if Pokemon can learn this TM
    compatible_pokemon = pokemon_utils.get_user_pokemon_that_can_learn_tm(tm_id, user_pokemon)
    if not any(p.get('uuid') == pokemon.get('uuid') for p in compatible_pokemon):
        error_text = "❌ <b>Error:</b> This Pokemon cannot learn this TM!"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back to TMs", callback_data=f"tm_back_{user_id}_0")]
        ])
        await callback_query.message.edit_text(error_text, reply_markup=keyboard, parse_mode="HTML")
        return
    
    # Create the move data
    move_data = {
        'move': pokemon_utils.normalize_move_name(tm_data.get('name', '')),
        'method': 'machine',
        'level_learned_at': 0
    }
    
    # Get current moves
    current_moves = pokemon.get('moves', [])
    
    # Check if Pokemon already knows this move
    for move in current_moves:
        if pokemon_utils.normalize_move_name(move.get('move', '')) == move_data['move']:
            error_text = "❌ <b>Error:</b> This Pokemon already knows this move!"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back to TMs", callback_data=f"tm_back_{user_id}_0")]
            ])
            await callback_query.message.edit_text(error_text, reply_markup=keyboard, parse_mode="HTML")
            return
    
    # Add the move to Pokemon's moveset
    current_moves.append(move_data)
    
    try:
        # Update Pokemon moves in database
        pokemon_uuid = pokemon.get('uuid')
        success = await update_pokemon_moveset(user_id, pokemon.get('id'), current_moves, pokemon_uuid)
        
        if not success:
            error_text = "❌ <b>Error:</b> Failed to teach the move!"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back to TMs", callback_data=f"tm_back_{user_id}_0")]
            ])
            await callback_query.message.edit_text(error_text, reply_markup=keyboard, parse_mode="HTML")
            return
        
        # Remove TM from inventory
        tm_removed = await remove_tm_from_user(user_id, tm_id, 1)
        
        if not tm_removed:
            error_text = "❌ <b>Error:</b> Failed to remove TM from inventory!"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back to TMs", callback_data=f"tm_back_{user_id}_0")]
            ])
            await callback_query.message.edit_text(error_text, reply_markup=keyboard, parse_mode="HTML")
            return
        
        # Sync team with collection
        await sync_team_with_collection(user_id, callback_query.bot)
        
        # Success message
        tm_number = tm_id.replace('tm', '')
        name = tm_data.get('name', 'Unknown')
        pokemon_name = pokemon.get('name', 'Unknown')
        is_shiny = pokemon.get('is_shiny', False)
        
        display_name = f"✨ {pokemon_name}" if is_shiny else pokemon_name
        
        text = f"<b>✅ Success!</b>\n\n"
        text += f"{display_name} learned <b>{name}</b>!\n\n"
        text += f"TM{tm_number} has been removed from your inventory."
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🔙 Back to TMs",
                callback_data=f"tm_back_{user_id}_0"
            )]
        ])
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        
    except Exception as e:
        print(f"Error in TM learning: {e}")
        error_text = "❌ <b>Error:</b> An unexpected error occurred while teaching the move!"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back to TMs", callback_data=f"tm_back_{user_id}_0")]
        ])
        await callback_query.message.edit_text(error_text, reply_markup=keyboard, parse_mode="HTML") 