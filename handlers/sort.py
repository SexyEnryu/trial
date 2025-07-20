from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from preferences import get_user_preferences, update_user_preferences, get_sort_display_name, check_starter_package

router = Router()

@router.message(Command("sort"))
async def sort_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Check if user has claimed starter package
    is_valid, result = await check_starter_package(user_id, message.from_user.username, message.from_user.first_name)
    if not is_valid:
        await message.answer(result, parse_mode="HTML")
        return
    
    await show_sort_menu(message, user_id)

async def show_sort_menu(message_or_callback, user_id):
    """Show sort options menu"""
    preferences = await get_user_preferences(user_id)  # Added await
    
    text = f"<b>How would you like to sort your pokemon?</b>\n\n"
    
    # Regular sort options
    text += "<b>1.</b> Order caught\n"
    text += "<b>2.</b> Pokedex number\n"
    text += "<b>3.</b> Level\n"
    text += "<b>4.</b> IV points\n"
    text += "<b>5.</b> EV points\n"
    text += "<b>6.</b> Name\n"
    text += "<b>7.</b> Nature\n"
    text += "<b>8.</b> Type\n"
    text += "<b>9.</b> Catch rate\n\n"
    
    # Stats sort options
    text += "<b>Sort by pokemon stat points:</b>\n"
    text += "—————————————————————\n"
    text += "<b>10.</b> HP points\n"
    text += "<b>11.</b> Attack points\n"
    text += "<b>12.</b> Defense points\n"
    text += "<b>13.</b> Sp. Attack points\n"
    text += "<b>14.</b> Sp defense points\n"
    text += "<b>15.</b> Speed points\n"
    text += "<b>16.</b> Total stats points\n\n"
    
    # Current settings
    current_sort = get_sort_display_name(preferences['sort_by'])
    direction = preferences['sort_direction'].title()
    text += f"<b>Currently sorting by:</b> <b>{current_sort}</b>\n"
    text += f"<b>Direction:</b> <b>{direction}</b>"
    
    # Create keyboard with 5 buttons per row
    keyboard_rows = []
    
    # Row 1: 1-5
    row1 = []
    for i in range(1, 6):
        row1.append(InlineKeyboardButton(text=str(i), callback_data=f"sort_{i}_{user_id}"))
    keyboard_rows.append(row1)
    
    # Row 2: 6-10
    row2 = []
    for i in range(6, 11):
        row2.append(InlineKeyboardButton(text=str(i), callback_data=f"sort_{i}_{user_id}"))
    keyboard_rows.append(row2)
    
    # Row 3: 11-15
    row3 = []
    for i in range(11, 16):
        row3.append(InlineKeyboardButton(text=str(i), callback_data=f"sort_{i}_{user_id}"))
    keyboard_rows.append(row3)
    
    # Row 4: 16 and direction toggle
    row4 = []
    row4.append(InlineKeyboardButton(text="16", callback_data=f"sort_16_{user_id}"))
    direction_text = "Toggle Direction"
    row4.append(InlineKeyboardButton(text=direction_text, callback_data=f"sort_direction_{user_id}"))
    keyboard_rows.append(row4)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    if isinstance(message_or_callback, types.Message):
        await message_or_callback.reply(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await message_or_callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(F.data.startswith("sort_"))
async def handle_sort_selection(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    
    data_parts = callback_query.data.split("_")
    if len(data_parts) < 3:
        await callback_query.answer("❌ Invalid sort data!", show_alert=True)
        return
    
    # Check if user is authorized to interact with this button
    if len(data_parts) >= 3:
        if data_parts[1] == "direction":
            # For direction toggle: sort_direction_user_id
            if data_parts[2] != str(user_id):
                await callback_query.answer("❌ You can only interact with your own sort menu!", show_alert=True)
                return
        else:
            # For regular sort options: sort_number_user_id
            if data_parts[2] != str(user_id):
                await callback_query.answer("❌ You can only interact with your own sort menu!", show_alert=True)
                return
    
    # Check if user has claimed starter package
    is_valid, result = await check_starter_package(user_id, callback_query.from_user.username, callback_query.from_user.first_name)
    if not is_valid:
        await callback_query.answer(result, show_alert=True)
        return
    
    preferences = await get_user_preferences(user_id)  # Added await
    
    if data_parts[1] == "direction":
        # Toggle direction
        new_direction = 'descending' if preferences['sort_direction'] == 'ascending' else 'ascending'
        await update_user_preferences(user_id, sort_direction=new_direction)  # Added await
        await callback_query.answer(f"✅ Direction changed to {new_direction.title()}")
    else:
        # Handle sort option selection
        sort_option = int(data_parts[1])
        
        sort_mapping = {
            1: 'order_caught',
            2: 'pokedex_number',
            3: 'level',
            4: 'iv_points',
            5: 'ev_points',
            6: 'name',
            7: 'nature',
            8: 'type',
            9: 'catch_rate',
            10: 'hp_points',
            11: 'attack_points',
            12: 'defense_points',
            13: 'sp_attack_points',
            14: 'sp_defense_points',
            15: 'speed_points',
            16: 'total_stats_points'
        }
        
        if sort_option in sort_mapping:
            await update_user_preferences(user_id, sort_by=sort_mapping[sort_option])  # Added await
            sort_name = get_sort_display_name(sort_mapping[sort_option])
            await callback_query.answer(f"✅ Now sorting by {sort_name}")
        else:
            await callback_query.answer("❌ Invalid sort option!", show_alert=True)
            return
    
    # Update the menu
    await show_sort_menu(callback_query, user_id)