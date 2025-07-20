from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from preferences import get_user_preferences, update_user_preferences, get_display_name, check_starter_package

router = Router()

@router.message(Command("display"))
async def display_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Check if user has claimed starter package
    is_valid, result = await check_starter_package(user_id, message.from_user.username, message.from_user.first_name)
    if not is_valid:
        await message.answer(result, parse_mode="HTML")
        return
    
    await show_display_menu(message, user_id)

async def show_display_menu(message_or_callback, user_id):
    """Show display options menu"""
    preferences = await get_user_preferences(user_id)  # Added await
    
    text = f"<b>Which pokemon detail would you like to display?</b>\n\n"
    
    # Regular display options
    text += "<b>1.</b> None\n"
    text += "<b>2.</b> Level\n"
    text += "<b>3.</b> IV points\n"
    text += "<b>4.</b> EV points\n"
    text += "<b>5.</b> Nature\n"
    text += "<b>6.</b> Type\n"
    text += "<b>7.</b> Type symbol\n"
    text += "<b>8.</b> Catch rate\n\n"
    
    # Stats display options
    text += "<b>Display pokemon stat points:</b>\n"
    text += "—————————————————————\n"
    text += "<b>9.</b> HP points\n"
    text += "<b>10.</b> Attack points\n"
    text += "<b>11.</b> Defense points\n"
    text += "<b>12.</b> Sp. Attack points\n"
    text += "<b>13.</b> Sp defense points\n"
    text += "<b>14.</b> Speed points\n"
    text += "<b>15.</b> Total stats points\n\n"
    
    # Current settings
    if preferences['display_options']:
        current_display = ', '.join([get_display_name(opt) for opt in preferences['display_options']])
    else:
        current_display = 'None'
    
    numbering_status = "Yes" if preferences['show_numbering'] else "No"
    
    text += f"<b>Currently displaying:</b> <b>{current_display}</b>\n"
    text += f"<b>Show pokemon numbering:</b> <b>{numbering_status}</b>"
    
    # Create keyboard with 5 buttons per row
    keyboard_rows = []
    
    # Row 1: 1-5
    row1 = []
    for i in range(1, 6):
        row1.append(InlineKeyboardButton(text=str(i), callback_data=f"display_{i}_{user_id}"))
    keyboard_rows.append(row1)
    
    # Row 2: 6-10
    row2 = []
    for i in range(6, 11):
        row2.append(InlineKeyboardButton(text=str(i), callback_data=f"display_{i}_{user_id}"))
    keyboard_rows.append(row2)
    
    # Row 3: 11-15
    row3 = []
    for i in range(11, 16):
        row3.append(InlineKeyboardButton(text=str(i), callback_data=f"display_{i}_{user_id}"))
    keyboard_rows.append(row3)
    
    # Row 4: Toggle numbering and clear all
    row4 = []
    numbering_text = "Toggle Numbering"
    row4.append(InlineKeyboardButton(text=numbering_text, callback_data=f"display_numbering_{user_id}"))
    row4.append(InlineKeyboardButton(text="🗑️ Clear All", callback_data=f"display_clear_{user_id}"))
    keyboard_rows.append(row4)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    if isinstance(message_or_callback, types.Message):
        await message_or_callback.reply(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await message_or_callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(F.data.startswith("display_"))
async def handle_display_selection(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    
    data_parts = callback_query.data.split("_")
    if len(data_parts) < 3:
        await callback_query.answer("❌ Invalid display data!", show_alert=True)
        return
    
    # Check if user is authorized to interact with this button
    if len(data_parts) >= 3:
        if data_parts[1] == "numbering":
            # For numbering toggle: display_numbering_user_id
            if data_parts[2] != str(user_id):
                await callback_query.answer("❌ You can only interact with your own display menu!", show_alert=True)
                return
        elif data_parts[1] == "clear":
            # For clear all: display_clear_user_id
            if data_parts[2] != str(user_id):
                await callback_query.answer("❌ You can only interact with your own display menu!", show_alert=True)
                return
        else:
            # For regular display options: display_number_user_id
            if data_parts[2] != str(user_id):
                await callback_query.answer("❌ You can only interact with your own display menu!", show_alert=True)
                return
    
    # Check if user has claimed starter package
    is_valid, result = await check_starter_package(user_id, callback_query.from_user.username, callback_query.from_user.first_name)
    if not is_valid:
        await callback_query.answer(result, show_alert=True)
        return
    
    preferences = await get_user_preferences(user_id)  # Added await
    
    if data_parts[1] == "numbering":
        # Toggle numbering
        new_numbering = not preferences['show_numbering']
        await update_user_preferences(user_id, show_numbering=new_numbering)  # Added await
        status = "enabled" if new_numbering else "disabled"
        await callback_query.answer(f"✅ Pokemon numbering {status}")
    elif data_parts[1] == "clear":
        # Clear all display options
        await update_user_preferences(user_id, display_options=[])  # Added await
        await callback_query.answer("✅ All display options cleared")
    else:
        # Handle display option selection
        display_option = int(data_parts[1])
        
        display_mapping = {
            1: 'none',
            2: 'level',
            3: 'iv_points',
            4: 'ev_points',
            5: 'nature',
            6: 'type',
            7: 'type_symbol',
            8: 'catch_rate',
            9: 'hp_points',
            10: 'attack_points',
            11: 'defense_points',
            12: 'sp_attack_points',
            13: 'sp_defense_points',
            14: 'speed_points',
            15: 'total_stats_points'
        }
        
        if display_option in display_mapping:
            option_key = display_mapping[display_option]
            
            if option_key == 'none':
                # Set display options to empty list
                await update_user_preferences(user_id, display_options=[])  # Added await
                await callback_query.answer("✅ Display set to None")
            else:
                # Toggle the display option
                current_options = preferences['display_options'].copy()
                
                if option_key in current_options:
                    # Remove the option
                    current_options.remove(option_key)
                    await update_user_preferences(user_id, display_options=current_options)  # Added await
                    option_name = get_display_name(option_key)
                    await callback_query.answer(f"✅ {option_name} removed from display")
                else:
                    # Add the option
                    current_options.append(option_key)
                    await update_user_preferences(user_id, display_options=current_options)  # Added await
                    option_name = get_display_name(option_key)
                    await callback_query.answer(f"✅ {option_name} added to display")
        else:
            await callback_query.answer("❌ Invalid display option!", show_alert=True)
            return
    
    # Update the menu
    await show_display_menu(callback_query, user_id)