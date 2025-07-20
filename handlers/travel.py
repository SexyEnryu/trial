from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
import asyncio
from database import get_or_create_user, users_collection

router = Router()

# All regions with their numbers
REGIONS = {
    1: "Kanto",
    2: "Johto", 
    3: "Hoenn",
    4: "Sinnoh",
    5: "Unova",
    6: "Kalos",
    7: "Alola",
    8: "Galar",
    9: "Paldea"
}

def create_region_keyboard(user_id: int):
    """Create inline keyboard for region selection"""
    keyboard = []
    
    # First row: buttons 1-5
    row1 = []
    for i in range(1, 6):
        row1.append(InlineKeyboardButton(
            text=str(i),
            callback_data=f"region:{i}:{user_id}"
        ))
    keyboard.append(row1)
    
    # Second row: buttons 6-9
    row2 = []
    for i in range(6, 10):
        row2.append(InlineKeyboardButton(
            text=str(i),
            callback_data=f"region:{i}:{user_id}"
        ))
    keyboard.append(row2)
    
    # Third row: Close button (centered)
    keyboard.append([InlineKeyboardButton(
        text="Close",
        callback_data=f"close_regions:{user_id}"
    )])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@router.message(Command("travel"))
async def travel_command(message: Message):
    """Handle /travel command"""
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    
    # Get current region (default to Kanto if not set)
    current_region = user.get("current_region", "Kanto")
    
    # Create the regions list text
    regions_text = "🌍 <b>Travel to a New Region</b> 🌍\n\n"
    regions_text += "Choose your destination:\n\n"
    
    for num, region in REGIONS.items():
        emoji = "📍" if region == current_region else "🗺️"
        regions_text += f"{emoji} {num}. {region}\n"
    
    regions_text += f"\n<b>Current Location:</b> {current_region}"
    
    await message.reply(
        text=regions_text,
        reply_markup=create_region_keyboard(message.from_user.id),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("region:"))
async def handle_region_selection(callback_query: CallbackQuery):
    """Handle region selection callback"""
    data_parts = callback_query.data.split(":")
    region_num = int(data_parts[1])
    allowed_user_id = int(data_parts[2])
    
    # Check if the user who clicked is the same as the one who called the command
    if callback_query.from_user.id != allowed_user_id:
        await callback_query.answer(
            text="This button is not for you",
            show_alert=True
        )
        return
    
    region_name = REGIONS[region_num]
    
    # Get current user data
    user = await get_or_create_user(callback_query.from_user.id, callback_query.from_user.username, callback_query.from_user.first_name)
    current_region = user.get("current_region", "Kanto")
    
    # Check if user is already in the selected region
    if current_region == region_name:
        await callback_query.answer(
            text="You are already in this region",
            show_alert=True
        )
        return
    
    # Update user's region in the database
    await users_collection.update_one(
        {"user_id": callback_query.from_user.id},
        {"$set": {"current_region": region_name}}
    )
    
    # Show success message
    await callback_query.answer(
        text=f"Successfully traveled to {region_name}!",
        show_alert=True
    )
    
    # Update the message to show the new current region
    regions_text = "🌍 <b>Travel to a New Region</b> 🌍\n\n"
    regions_text += "Choose your destination:\n\n"
    
    for num, region in REGIONS.items():
        emoji = "📍" if region == region_name else "🗺️"
        regions_text += f"{emoji} {num}. {region}\n"
    
    regions_text += f"\n<b>Current Location:</b> {region_name}"
    
    await callback_query.message.edit_text(
        text=regions_text,
        reply_markup=create_region_keyboard(callback_query.from_user.id),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("close_regions:"))
async def close_regions(callback_query: CallbackQuery):
    """Handle close button"""
    data_parts = callback_query.data.split(":")
    allowed_user_id = int(data_parts[1])
    
    # Check if the user who clicked is the same as the one who called the command
    if callback_query.from_user.id != allowed_user_id:
        await callback_query.answer(
            text="This button is not for you",
            show_alert=True
        )
        return
    
    await callback_query.message.delete()
    await callback_query.answer()