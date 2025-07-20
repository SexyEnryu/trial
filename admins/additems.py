import re
import asyncio
import glob
import os
import difflib
from aiogram import types, Router, F
from aiogram.filters import Command
from aiogram.types import Message
from database import add_mega_stone_to_user, add_z_crystal_to_user, add_plate_to_user, get_or_create_user, get_user_plates, get_user_mega_stones, get_user_z_crystals

# Admin user IDs
ADMIN_IDS = [7552373579, 7907063334, 1182033957, 1097600241, 1498348391, 7984578203, 1412946850]

router = Router()

def get_available_mega_stones():
    """Get list of available mega stones from files"""
    stone_files = glob.glob('mega_stones/*.png')
    return [os.path.splitext(os.path.basename(f))[0] for f in stone_files]

def get_available_z_crystals():
    """Get list of available Z-crystals from files"""
    crystal_files = glob.glob('z_crystals/*.png')
    return [os.path.splitext(os.path.basename(f))[0] for f in crystal_files]

def get_available_plates():
    """Get list of available plates from files"""
    plate_files = glob.glob('plates/*.png')
    return [os.path.splitext(os.path.basename(f))[0] for f in plate_files]

def fuzzy_match_item(query, available_items, threshold=0.6):
    """Find the best matching item using fuzzy string matching"""
    if not query or not available_items:
        return None
    
    query = query.lower().strip()
    
    # First try exact match
    for item in available_items:
        if query == item.lower():
            return item
    
    # Then try partial match
    for item in available_items:
        if query in item.lower() or item.lower() in query:
            return item
    
    # Finally try fuzzy matching
    matches = difflib.get_close_matches(query, available_items, n=1, cutoff=threshold)
    return matches[0] if matches else None

@router.message(Command("addmega"))
async def addmega_command(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("❌ You don't have permission to use this command!", parse_mode="HTML")
        return
    
    if not message.reply_to_message:
        await message.reply("❌ You must reply to a user's message to add mega stones to them!", parse_mode="HTML")
        return
    
    args = message.text.split()[1:]
    if not args:
        await message.reply("❌ Usage: /addmega <stone_name> or /addmega all (reply to user)", parse_mode="HTML")
        return
    
    target_user_id = message.reply_to_message.from_user.id
    target_user = await get_or_create_user(
        target_user_id,
        getattr(message.reply_to_message.from_user, 'username', '') or '',
        getattr(message.reply_to_message.from_user, 'first_name', '') or ''
    )
    
    stone_query = ' '.join(args).lower().strip()
    available_stones = get_available_mega_stones()
    
    if stone_query == "all":
        # Add all mega stones (skip duplicates)
        success_count = 0
        skipped_count = 0
        user_stones = await get_user_mega_stones(target_user_id)
        
        for stone in available_stones:
            try:
                if stone not in user_stones:
                    await add_mega_stone_to_user(target_user_id, stone)
                    success_count += 1
                else:
                    skipped_count += 1
            except Exception as e:
                print(f"Error adding stone {stone}: {e}")
        
        target_name = getattr(message.reply_to_message.from_user, 'first_name', 'User')
        if skipped_count > 0:
            await message.reply(f"✅ Added {success_count}/{len(available_stones)} mega stones to {target_name}! (Skipped {skipped_count} duplicates)", parse_mode="HTML")
        else:
            await message.reply(f"✅ Added {success_count}/{len(available_stones)} mega stones to {target_name}!", parse_mode="HTML")
        return
    
    # Try to find matching stone
    matched_stone = fuzzy_match_item(stone_query, available_stones)
    
    if not matched_stone:
        available_list = ', '.join(available_stones[:10])  # Show first 10
        await message.reply(f"❌ Mega stone not found! Available stones include: {available_list}...", parse_mode="HTML")
        return
    
    # Check if user already has this stone
    user_stones = await get_user_mega_stones(target_user_id)
    if matched_stone in user_stones:
        target_name = getattr(message.reply_to_message.from_user, 'first_name', 'User')
        await message.reply(f"⚠️ {target_name} already has {matched_stone.title()}!", parse_mode="HTML")
        return
    
    try:
        await add_mega_stone_to_user(target_user_id, matched_stone)
        target_name = getattr(message.reply_to_message.from_user, 'first_name', 'User')
        await message.reply(f"✅ Added {matched_stone.title()} to {target_name}!", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Error adding mega stone: {e}", parse_mode="HTML")

@router.message(Command("addcrystal"))
async def addcrystal_command(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("❌ You don't have permission to use this command!", parse_mode="HTML")
        return
    
    if not message.reply_to_message:
        await message.reply("❌ You must reply to a user's message to add Z-crystals to them!", parse_mode="HTML")
        return
    
    args = message.text.split()[1:]
    if not args:
        await message.reply("❌ Usage: /addcrystal <crystal_name> or /addcrystal all (reply to user)", parse_mode="HTML")
        return
    
    target_user_id = message.reply_to_message.from_user.id
    target_user = await get_or_create_user(
        target_user_id,
        getattr(message.reply_to_message.from_user, 'username', '') or '',
        getattr(message.reply_to_message.from_user, 'first_name', '') or ''
    )
    
    crystal_query = ' '.join(args).lower().strip()
    available_crystals = get_available_z_crystals()
    
    if crystal_query == "all":
        # Add all Z-crystals (skip duplicates)
        success_count = 0
        skipped_count = 0
        user_crystals = await get_user_z_crystals(target_user_id)
        
        for crystal in available_crystals:
            try:
                if crystal not in user_crystals:
                    await add_z_crystal_to_user(target_user_id, crystal)
                    success_count += 1
                else:
                    skipped_count += 1
            except Exception as e:
                print(f"Error adding crystal {crystal}: {e}")
        
        target_name = getattr(message.reply_to_message.from_user, 'first_name', 'User')
        if skipped_count > 0:
            await message.reply(f"✅ Added {success_count}/{len(available_crystals)} Z-crystals to {target_name}! (Skipped {skipped_count} duplicates)", parse_mode="HTML")
        else:
            await message.reply(f"✅ Added {success_count}/{len(available_crystals)} Z-crystals to {target_name}!", parse_mode="HTML")
        return
    
    # Try to find matching crystal
    matched_crystal = fuzzy_match_item(crystal_query, available_crystals)
    
    if not matched_crystal:
        available_list = ', '.join(available_crystals[:10])  # Show first 10
        await message.reply(f"❌ Z-crystal not found! Available crystals include: {available_list}...", parse_mode="HTML")
        return
    
    # Check if user already has this crystal
    user_crystals = await get_user_z_crystals(target_user_id)
    if matched_crystal in user_crystals:
        target_name = getattr(message.reply_to_message.from_user, 'first_name', 'User')
        await message.reply(f"⚠️ {target_name} already has {matched_crystal.title()}!", parse_mode="HTML")
        return
    
    try:
        await add_z_crystal_to_user(target_user_id, matched_crystal)
        target_name = getattr(message.reply_to_message.from_user, 'first_name', 'User')
        await message.reply(f"✅ Added {matched_crystal.title()} to {target_name}!", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Error adding Z-crystal: {e}", parse_mode="HTML")

@router.message(Command("addplate"))
async def addplate_command(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("❌ You don't have permission to use this command!", parse_mode="HTML")
        return
    
    if not message.reply_to_message:
        await message.reply("❌ You must reply to a user's message to add plates to them!", parse_mode="HTML")
        return
    
    args = message.text.split()[1:]
    if not args:
        await message.reply("❌ Usage: /addplate <plate_name> or /addplate all (reply to user)", parse_mode="HTML")
        return
    
    target_user_id = message.reply_to_message.from_user.id
    target_user = await get_or_create_user(
        target_user_id,
        getattr(message.reply_to_message.from_user, 'username', '') or '',
        getattr(message.reply_to_message.from_user, 'first_name', '') or ''
    )
    
    plate_query = ' '.join(args).lower().strip()
    available_plates = get_available_plates()
    
    if plate_query == "all":
        # Add all plates (skip duplicates)
        success_count = 0
        skipped_count = 0
        user_plates = await get_user_plates(target_user_id)
        
        for plate in available_plates:
            try:
                if plate not in user_plates:
                    await add_plate_to_user(target_user_id, plate)
                    success_count += 1
                else:
                    skipped_count += 1
            except Exception as e:
                print(f"Error adding plate {plate}: {e}")
        
        target_name = getattr(message.reply_to_message.from_user, 'first_name', 'User')
        if skipped_count > 0:
            await message.reply(f"✅ Added {success_count}/{len(available_plates)} plates to {target_name}! (Skipped {skipped_count} duplicates)", parse_mode="HTML")
        else:
            await message.reply(f"✅ Added {success_count}/{len(available_plates)} plates to {target_name}!", parse_mode="HTML")
        return
    
    # Try to find matching plate
    matched_plate = fuzzy_match_item(plate_query, available_plates)
    
    if not matched_plate:
        available_list = ', '.join(available_plates[:10])  # Show first 10
        await message.reply(f"❌ Plate not found! Available plates include: {available_list}...", parse_mode="HTML")
        return
    
    # Check if user already has this plate
    user_plates = await get_user_plates(target_user_id)
    if matched_plate in user_plates:
        target_name = getattr(message.reply_to_message.from_user, 'first_name', 'User')
        await message.reply(f"⚠️ {target_name} already has {matched_plate.title()}!", parse_mode="HTML")
        return
    
    try:
        await add_plate_to_user(target_user_id, matched_plate)
        target_name = getattr(message.reply_to_message.from_user, 'first_name', 'User')
        await message.reply(f"✅ Added {matched_plate.title()} to {target_name}!", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Error adding plate: {e}", parse_mode="HTML") 