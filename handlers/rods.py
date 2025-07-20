from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database import get_or_create_user, get_user_fishing_rods, update_user_fishing_rods, get_user_balance
from config import FISHING_RODS

router = Router()

class RodStates(StatesGroup):
    viewing_rod = State()
    confirming_equip = State()

async def check_starter_package(user_id: int, username: str = None, first_name: str = None):
    """Check if user has claimed their starter package"""
    user = await get_or_create_user(user_id, username, first_name)
    
    if not user:
        return False, "❌ User data not found! Please try again."
    
    if not user.get('already_started', False):
        return False, "❌ You need to claim your starter package first! Use /start command to begin your Pokémon journey."
    
    return True, user

@router.message(Command("rods"))
async def rods_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Check if user has claimed starter package
    is_valid, result = await check_starter_package(user_id, message.from_user.username, message.from_user.first_name)
    if not is_valid:
        await message.reply(result)
        return
    
    user = result  # result contains user data if valid
    
    await state.clear()
    
    # Get user's fishing rods
    user_rods = await get_user_fishing_rods(user_id)
    
    rods_text = "🎣 <b>Fishing Rods Collection</b>\n\n"
    rods_text += "Choose a fishing rod to view details:\n\n"
    
    keyboard_rows = []
    current_row = []
    
    for rod in FISHING_RODS:
        name = rod["name"]
        owned = name in user_rods and user_rods[name] > 0
        equipped = user_rods.get('equipped_rod') == name
        
        # Add status emoji
        if equipped:
            status_emoji = "✅"  # Equipped
        else:
            status_emoji = ""  # Not owned
        
        button_text = f"{status_emoji} {name}"
        
        button = InlineKeyboardButton(
            text=button_text, 
            callback_data=f"view_rod_{name}_{user_id}"
        )
        current_row.append(button)
        
        # Create new row after 2 buttons
        if len(current_row) == 2:
            keyboard_rows.append(current_row)
            current_row = []
    
    # Add remaining buttons
    if current_row:
        keyboard_rows.append(current_row)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    await message.reply(rods_text, reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(F.data.startswith("view_rod_"))
async def view_rod_details(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    
    # Extract rod name and original user ID from callback data
    callback_parts = callback_query.data.replace("view_rod_", "").rsplit("_", 1)
    if len(callback_parts) != 2:
        await callback_query.answer("❌ Invalid callback data!", show_alert=True)
        return
    
    rod_name, original_user_id = callback_parts
    original_user_id = int(original_user_id)
    
    # Check if the user clicking is the same as the original user
    if user_id != original_user_id:
        await callback_query.answer("You can only interact with your own fishing rods!", show_alert=True)
        return
    
    # Check if user has claimed starter package
    is_valid, result = await check_starter_package(user_id, callback_query.from_user.username, callback_query.from_user.first_name)
    if not is_valid:
        await callback_query.answer(result, show_alert=True)
        return
    
    user = result  # result contains user data if valid
    
    # Find the rod data
    rod_data = None
    for rod in FISHING_RODS:
        if rod["name"] == rod_name:
            rod_data = rod
            break
    
    if not rod_data:
        await callback_query.answer("❌ Rod not found!", show_alert=True)
        return
    
    # Get user's fishing rods
    user_rods = await get_user_fishing_rods(user_id)
    
    owned = rod_name in user_rods and user_rods[rod_name] > 0
    equipped = user_rods.get('equipped_rod') == rod_name
    
    # Build rod details text
    rod_text = f"<b>{rod_data['name']}</b>\n\n"
    rod_text += f"📋 <b>Description:</b>\n{rod_data['description']}\n\n"
    rod_text += f"🎯 <b>Catch Rate:</b> {rod_data['fish_rate']}x\n\n"
    
    # Create buttons
    keyboard_rows = []
    
    if owned:
        if equipped:
            rod_text += "<b>Status:</b> Currently Equipped"
            # If equipped, show back button only
            keyboard_rows.append([
                InlineKeyboardButton(text="🔙 Back", callback_data=f"back_to_rods_{user_id}")
            ])
        else:
            rod_text += "<b>Status:</b> Owned"
            # If owned but not equipped, show equip and back buttons
            keyboard_rows.append([
                InlineKeyboardButton(text="Equip Rod", callback_data=f"equip_rod_{rod_name}_{user_id}"),
                InlineKeyboardButton(text="🔙 Back", callback_data=f"back_to_rods_{user_id}")
            ])
    else:
        rod_text += "<b>Status:</b> You don't have this rod"
        # If not owned, show back button only
        keyboard_rows.append([
            InlineKeyboardButton(text="🔙 Back", callback_data=f"back_to_rods_{user_id}")
        ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    await callback_query.message.edit_text(rod_text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()

@router.callback_query(F.data.startswith("equip_rod_"))
async def equip_rod(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    
    # Extract rod name and original user ID from callback data
    callback_parts = callback_query.data.replace("equip_rod_", "").rsplit("_", 1)
    if len(callback_parts) != 2:
        await callback_query.answer("❌ Invalid callback data!", show_alert=True)
        return
    
    rod_name, original_user_id = callback_parts
    original_user_id = int(original_user_id)
    
    # Check if the user clicking is the same as the original user
    if user_id != original_user_id:
        await callback_query.answer("You can only interact with your own fishing rods!", show_alert=True)
        return
    
    # Check if user has claimed starter package
    is_valid, result = await check_starter_package(user_id, callback_query.from_user.username, callback_query.from_user.first_name)
    if not is_valid:
        await callback_query.answer(result, show_alert=True)
        return
    
    user = result  # result contains user data if valid
    
    # Find the rod data
    rod_data = None
    for rod in FISHING_RODS:
        if rod["name"] == rod_name:
            rod_data = rod
            break
    
    if not rod_data:
        await callback_query.answer("❌ Rod not found!", show_alert=True)
        return
    
    # Get user's current fishing rods
    user_rods = await get_user_fishing_rods(user_id)
    
    # Check if user owns this rod
    if rod_name not in user_rods or user_rods[rod_name] <= 0:
        await callback_query.answer("You don't have this rod!", show_alert=True)
        return
    
    # Check if rod is already equipped
    if user_rods.get('equipped_rod') == rod_name:
        await callback_query.answer("This rod is already equipped!", show_alert=True)
        return
    
    # Equip the rod
    user_rods['equipped_rod'] = rod_name
    await update_user_fishing_rods(user_id, user_rods)
    
    # Success message
    success_text = f"<b>Rod Equipped!</b>\n\n"
    success_text += f"You have equipped <b>{rod_data['name']}</b>!\n\n"
    success_text += f"🎯 <b>Catch Rate:</b> {rod_data['fish_rate']}x\n\n"
    success_text += f"🎣 You can now use this rod for fishing!"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Rods", callback_data=f"back_to_rods_{user_id}")]
    ])
    
    await callback_query.message.edit_text(success_text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer("🔥 Rod equipped successfully!")

@router.callback_query(F.data.startswith("back_to_rods_"))
async def back_to_rods(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    
    # Extract original user ID from callback data
    original_user_id = int(callback_query.data.replace("back_to_rods_", ""))
    
    # Check if the user clicking is the same as the original user
    if user_id != original_user_id:
        await callback_query.answer("❌ You can only interact with your own fishing rods!", show_alert=True)
        return
    
    # Check if user has claimed starter package
    is_valid, result = await check_starter_package(user_id, callback_query.from_user.username, callback_query.from_user.first_name)
    if not is_valid:
        await callback_query.answer(result, show_alert=True)
        return
    
    user = result  # result contains user data if valid
    
    # Get user's fishing rods
    user_rods = await get_user_fishing_rods(user_id)
    
    rods_text = "🎣 <b>Fishing Rods Collection</b>\n\n"
    rods_text += "Choose a fishing rod to view details:\n\n"
    
    keyboard_rows = []
    current_row = []
    
    for rod in FISHING_RODS:
        name = rod["name"]
        owned = name in user_rods and user_rods[name] > 0
        equipped = user_rods.get('equipped_rod') == name
        
        # Add status emoji
        if equipped:
            status_emoji = "✅"  # Equipped
        else:
            status_emoji = ""
        
        button_text = f"{status_emoji} {name}"
        
        button = InlineKeyboardButton(
            text=button_text, 
            callback_data=f"view_rod_{name}_{user_id}"
        )
        current_row.append(button)
        
        # Create new row after 2 buttons
        if len(current_row) == 2:
            keyboard_rows.append(current_row)
            current_row = []
    
    # Add remaining buttons
    if current_row:
        keyboard_rows.append(current_row)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    await callback_query.message.edit_text(rods_text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()