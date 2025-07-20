from aiogram import Router, types, Bot
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InaccessibleMessage
import asyncio
from database import get_or_create_user, get_user_pokemon_collection, db
from aiogram.utils.deep_linking import create_start_link

router = Router()

TEAM_SIZE = 6

# Helper to check if callback is from the correct user
async def is_callback_from_user(callback_query, user_id):
    if callback_query.from_user.id != user_id:
        await callback_query.answer("This button is not for you!", show_alert=True)
        return False
    return True

async def sync_team_with_collection(user_id, bot: Bot):
    """Ensure the user's team Pokémon are up-to-date with the main collection, especially active_moves."""
    from database import get_user_pokemon_collection, db, update_user_pokemon_collection
    import uuid
    
    # Get user data and collection sequentially to avoid race conditions
    chat = await bot.get_chat(user_id)
    user = await get_or_create_user(user_id, chat.username, chat.first_name)
    collection = await get_user_pokemon_collection(user_id)
    
    team = user.get("team", [])
    
    # DEBUG: Log initial team state
    print(f"DEBUG: SYNC START - User: {user_id}, Team size: {len(team)}")
    for i, poke in enumerate(team):
        print(f"  Team[{i}]: {poke.get('name')} Lv.{poke.get('level')} UUID: {poke.get('uuid')}")
    
    # Ensure all pokemon in collection have UUIDs
    collection_updated = False
    for poke in collection:
        if not poke.get('uuid'):
            poke['uuid'] = str(uuid.uuid4())
            collection_updated = True
    
    # Update collection if UUIDs were added
    if collection_updated:
        await update_user_pokemon_collection(user_id, collection)
    
    # Create UUID lookup for collection
    collection_by_uuid = {poke['uuid']: poke for poke in collection if poke.get('uuid')}
    
    updated_team = []
    for i, poke in enumerate(team):
        uuid_val = poke.get('uuid')
        print(f"DEBUG: Processing team Pokemon {i}: {poke.get('name')} Lv.{poke.get('level')} UUID: {uuid_val}")
        
        if uuid_val and uuid_val in collection_by_uuid:
            # Found in collection - but preserve team data if it's more recent
            collection_poke = collection_by_uuid[uuid_val]
            print(f"  Found in collection: {collection_poke.get('name')} Lv.{collection_poke.get('level')}")
            
            # Create a merged version that preserves team data when appropriate
            import copy
            merged_poke = copy.deepcopy(collection_poke)
            
            # Preserve team-specific data that might be more recent
            team_level = poke.get('level', 1)
            collection_level = collection_poke.get('level', 1)
            
            # If team level is higher, preserve team data (Pokemon was leveled up)
            if team_level > collection_level:
                print(f"  Team level ({team_level}) > Collection level ({collection_level}), preserving team data")
                merged_poke['level'] = team_level
                merged_poke['calculated_stats'] = poke.get('calculated_stats', {})
                merged_poke['max_hp'] = poke.get('max_hp', merged_poke.get('max_hp', 1))
                merged_poke['hp'] = poke.get('hp', poke.get('current_hp', merged_poke.get('hp', merged_poke.get('current_hp', merged_poke.get('max_hp', 1)))))
                merged_poke['moves'] = poke.get('moves', merged_poke.get('moves', []))
                merged_poke['evs'] = poke.get('evs', merged_poke.get('evs', {}))
                
                # Also update the collection to keep them in sync
                for j, collection_pokemon in enumerate(collection):
                    if collection_pokemon.get('uuid') == uuid_val:
                        collection[j] = copy.deepcopy(merged_poke)
                        collection_updated = True
                        break
                        
            # Preserve other team-specific data
            merged_poke['hp'] = poke.get('hp', poke.get('current_hp', merged_poke.get('hp', merged_poke.get('current_hp', merged_poke.get('max_hp', 1)))))
            # Prioritize collection's active_moves (latest saved moves) over team's active_moves
            merged_poke['active_moves'] = merged_poke.get('active_moves', poke.get('active_moves', []))
            
            # Ensure the Pokemon has all necessary fields for battle
            if not merged_poke.get('active_moves'):
                merged_poke['active_moves'] = []
            if not merged_poke.get('moves'):
                merged_poke['moves'] = []
            updated_team.append(merged_poke)
        elif uuid_val:
            # Pokemon has UUID but not found in collection - it may have been released
            print(f"  UUID not found in collection - Pokemon may have been released")
            # Don't add it to the team
            continue
        else:
            print(f"  No UUID - trying fallback matching")
            # Pokemon doesn't have UUID - this is a legacy pokemon
            # Try to find a unique match, but be more strict to avoid wrong matches
            possible_matches = []
            for collection_poke in collection:
                if (collection_poke.get('id') == poke.get('id') and 
                    collection_poke.get('level') == poke.get('level') and 
                    collection_poke.get('nature') == poke.get('nature')):
                    possible_matches.append(collection_poke)
            
            print(f"  Found {len(possible_matches)} possible matches")
            
            if len(possible_matches) == 1:
                # Only use the match if it's unique
                collection_poke = possible_matches[0]
                print(f"  Using unique match: {collection_poke.get('name')} Lv.{collection_poke.get('level')}")
                # Ensure the Pokemon has all necessary fields for battle
                if not collection_poke.get('active_moves'):
                    collection_poke['active_moves'] = []
                if not collection_poke.get('moves'):
                    collection_poke['moves'] = []
                updated_team.append(collection_poke)
            elif len(possible_matches) > 1:
                # Multiple matches found - this is ambiguous
                # Try to find a more specific match using additional fields
                best_match = None
                for match in possible_matches:
                    # Try to match by additional fields like IVs, EVs, or capture info
                    if (match.get('ivs') == poke.get('ivs') and 
                        match.get('evs') == poke.get('evs')):
                        best_match = match
                        break
                
                if best_match:
                    print(f"  Using best match: {best_match.get('name')} Lv.{best_match.get('level')}")
                    # Ensure the Pokemon has all necessary fields for battle
                    if not best_match.get('active_moves'):
                        best_match['active_moves'] = []
                    if not best_match.get('moves'):
                        best_match['moves'] = []
                    updated_team.append(best_match)
                else:
                    # Cannot uniquely identify - log this and use the first match
                    # This should be rare and indicates data integrity issues
                    print(f"WARNING: Multiple Pokemon matches found for team sync (user {user_id}): {poke.get('name')} Lv.{poke.get('level')}")
                    collection_poke = possible_matches[0]
                    print(f"  Using first match: {collection_poke.get('name')} Lv.{collection_poke.get('level')}")
                    # Ensure the Pokemon has all necessary fields for battle
                    if not collection_poke.get('active_moves'):
                        collection_poke['active_moves'] = []
                    if not collection_poke.get('moves'):
                        collection_poke['moves'] = []
                    updated_team.append(collection_poke)
            else:
                print(f"  No matches found - Pokemon may have been released")
            # If no matches found, the Pokemon may have been released - don't add to team
    
    # Update collection if it was modified during sync
    if collection_updated:
        await update_user_pokemon_collection(user_id, collection)
    
    # DEBUG: Log final team state
    print(f"DEBUG: SYNC END - Updated team size: {len(updated_team)}")
    for i, poke in enumerate(updated_team):
        print(f"  Updated Team[{i}]: {poke.get('name')} Lv.{poke.get('level')} UUID: {poke.get('uuid')}")
    
    # Update in DB if changed
    if updated_team != team:
        await db.users.update_one({"user_id": user_id}, {"$set": {"team": updated_team}})
    
    return updated_team

async def validate_team_integrity(user_id, bot: Bot):
    """Debug function to validate team integrity and identify potential issues"""
    from database import get_user_pokemon_collection, db
    
    chat = await bot.get_chat(user_id)
    user = await get_or_create_user(user_id, chat.username, chat.first_name)
    collection = await get_user_pokemon_collection(user_id)
    team = user.get("team", [])
    
    issues = []
    
    for i, team_poke in enumerate(team):
        # Check if team Pokemon has UUID
        if not team_poke.get('uuid'):
            issues.append(f"Team position {i+1}: {team_poke.get('name', 'Unknown')} (Lv.{team_poke.get('level', 1)}) missing UUID")
        
        # Check if team Pokemon exists in collection
        uuid_val = team_poke.get('uuid')
        if uuid_val:
            collection_poke = next((p for p in collection if p.get('uuid') == uuid_val), None)
            if not collection_poke:
                issues.append(f"Team position {i+1}: {team_poke.get('name', 'Unknown')} (UUID: {uuid_val}) not found in collection")
            elif (collection_poke.get('level') != team_poke.get('level') or 
                  collection_poke.get('name') != team_poke.get('name')):
                issues.append(f"Team position {i+1}: Mismatch between team and collection data for {team_poke.get('name', 'Unknown')}")
        
        # Check for duplicate UUIDs in team
        uuid_count = sum(1 for p in team if p.get('uuid') == uuid_val)
        if uuid_count > 1:
            issues.append(f"Team position {i+1}: Duplicate UUID {uuid_val} found in team")
    
    return issues

# /myteam command
@router.message(Command("myteam"))
async def myteam_command(message: types.Message):
    if not message or not hasattr(message, 'from_user') or not message.from_user:
        return
    user_id = message.from_user.id
    username = getattr(message.from_user, 'username', '') or ''
    first_name = getattr(message.from_user, 'first_name', '') or ''
    user = await get_or_create_user(user_id, username, first_name)
    
    # Validate team integrity (for debugging)
    integrity_issues = await validate_team_integrity(user_id, message.bot)
    if integrity_issues:
        print(f"Team integrity issues for user {user_id}: {integrity_issues}")
    
    # Sync team with collection
    team = await sync_team_with_collection(user_id, message.bot)
    text = "<b>Your Current Team:</b>\n"
    if team:
        for idx, poke in enumerate(team):
            text += f"{idx+1}. {poke['name'].title()} (Lv.{poke['level']})\n"
    else:
        text += "No Pokémon in your team!\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Edit Team", callback_data=f"myteam_edit_{user_id}")]
    ])
    if message and not isinstance(message, InaccessibleMessage) and hasattr(message, 'reply'):
        sent = await message.reply(text, reply_markup=keyboard, parse_mode="HTML")
    # Optionally pin or store sent.message_id for future edits
    # message_id is sent.message_id

# Edit team menu
@router.callback_query(lambda c: c.data and c.data.startswith("myteam_edit_"))
async def myteam_edit_menu(callback_query: CallbackQuery):
    if not callback_query.data or not callback_query.message:
        return
    user_id = int(callback_query.data.split("_")[-1]) if callback_query.data else None
    if user_id is None or not await is_callback_from_user(callback_query, user_id):
        return
    # Two buttons per row: [Add, Remove], [Change Order, Back]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Add Pokémon", callback_data=f"myteam_add_{user_id}_0"),
            InlineKeyboardButton(text="Remove Pokémon", callback_data=f"myteam_remove_{user_id}")
        ],
        [
            InlineKeyboardButton(text="Change Order", callback_data=f"myteam_reorder_{user_id}"),
            InlineKeyboardButton(text="Back", callback_data=f"myteam_back_{user_id}")
        ]
    ])
    if callback_query.message and not isinstance(callback_query.message, InaccessibleMessage) and hasattr(callback_query.message, 'edit_text'):
        await callback_query.message.edit_text("<b>Edit your team:</b>", reply_markup=keyboard, parse_mode="HTML")

# Add Pokémon to team with pagination and 5x4 grid
@router.callback_query(lambda c: c.data and c.data.startswith("myteam_add_"))
async def myteam_add_pokemon(callback_query: CallbackQuery):
    if not callback_query.message or not callback_query.data:
        return
    
    try:
        user_id = int(callback_query.data.split("_")[-2]) if callback_query.data else None
    except (ValueError, IndexError):
        await callback_query.answer("Invalid user ID!", show_alert=True)
        return
        
    if user_id is None or not await is_callback_from_user(callback_query, user_id):
        return
    username = getattr(callback_query.from_user, 'username', '') or ''
    first_name = getattr(callback_query.from_user, 'first_name', '') or ''
    
    # Get user data and collection sequentially to avoid race conditions
    user = await get_or_create_user(user_id, username, first_name)
    collection = await get_user_pokemon_collection(user_id)
    
    team = user.get("team", [])
    if len(team) >= TEAM_SIZE:
        await callback_query.answer("Your team is already full!", show_alert=True)
        return
    
    # Check if collection is empty
    if not collection:
        await callback_query.answer("You don't have any Pokémon to add! Use /hunt to catch some first.", show_alert=True)
        return
    
    # Ensure all pokemon have UUIDs - if not, generate them
    import uuid
    collection_updated = False
    for poke in collection:
        if not poke.get('uuid'):
            poke['uuid'] = str(uuid.uuid4())
            collection_updated = True
    
    # Update collection if UUIDs were added
    if collection_updated:
        from database import update_user_pokemon_collection
        await update_user_pokemon_collection(user_id, collection)
    
    # Filter available pokemon (not in team)
    team_uuids = {poke.get('uuid') for poke in team if poke.get('uuid')}
    available = [poke for poke in collection if poke.get('uuid') and poke.get('uuid') not in team_uuids]
    
    if not available:
        await callback_query.answer("All your Pokémon are already in your team!", show_alert=True)
        return
    
    available.sort(key=lambda p: (-p.get('level', 0), p.get('name', '').lower()))
    
    # Pagination
    parts = callback_query.data.split("_") if callback_query.data else []
    page = int(parts[-1]) if parts and parts[-1].isdigit() else 0
    per_page = 20
    total = len(available)
    max_page = (total - 1) // per_page if total > 0 else 0
    
    # Ensure page is within bounds
    page = max(0, min(page, max_page))
    
    start = page * per_page
    end = start + per_page
    page_pokemon = available[start:end]
    
    # Text list for current page
    text_lines = []
    for idx, poke in enumerate(page_pokemon, start=start+1):
        text_lines.append(f"{idx}. {poke.get('name', 'Unknown').title()} (Lv.{poke.get('level', 1)})")
    
    if not text_lines:
        text_lines = ["No Pokémon available on this page!"]
    
    # 5x4 grid of number buttons
    keyboard = []
    for i in range(0, len(page_pokemon), 4):
        row = []
        for j, poke in enumerate(page_pokemon[i:i+4]):
            btn_idx = start + i + j + 1
            if poke.get('uuid'):  # Only add button if UUID exists
                row.append(InlineKeyboardButton(
                    text=str(btn_idx),
                    callback_data=f"myteam_addpoke_{poke['uuid']}_{user_id}"
                ))
        if row:  # Only add row if it has buttons
            keyboard.append(row)
    
    # Pagination controls
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"myteam_add_{user_id}_{page-1}"))
    if page < max_page:
        nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"myteam_add_{user_id}_{page+1}"))
    if nav_row:
        keyboard.append(nav_row)
    
    # Back button
    keyboard.append([InlineKeyboardButton(text="Back", callback_data=f"myteam_edit_{user_id}")])
    
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    text = "<b>Select a Pokémon to add to your team:</b>\n" + "\n".join(text_lines)
    
    if callback_query.message and not isinstance(callback_query.message, InaccessibleMessage) and hasattr(callback_query.message, 'edit_text'):
        await callback_query.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

# Actually add the selected Pokémon
@router.callback_query(lambda c: c.data and c.data.startswith("myteam_addpoke_"))
async def myteam_addpoke_confirm(callback_query: CallbackQuery):
    if not callback_query.data:
        await callback_query.answer("Invalid callback data!", show_alert=True)
        return
    
    try:
        parts = callback_query.data.split("_") if callback_query.data else []
        poke_uuid = parts[2] if len(parts) > 2 else None
        user_id = int(parts[3]) if len(parts) > 3 else None
    except (ValueError, IndexError):
        await callback_query.answer("Invalid callback data format!", show_alert=True)
        return
    
    if poke_uuid is None or user_id is None or not await is_callback_from_user(callback_query, user_id):
        return
    username = getattr(callback_query.from_user, 'username', '') or ''
    first_name = getattr(callback_query.from_user, 'first_name', '') or ''
    
    # Get user data and collection sequentially to avoid race conditions
    user = await get_or_create_user(user_id, username, first_name)
    collection = await get_user_pokemon_collection(user_id)
    
    team = user.get("team", [])
    if len(team) >= TEAM_SIZE:
        await callback_query.answer("Your team is already full!", show_alert=True)
        return
    
    # Find the pokemon by UUID
    poke = next((p for p in collection if p.get('uuid') == poke_uuid), None)
    if not poke:
        await callback_query.answer("Pokémon not found! It may have been released or modified.", show_alert=True)
        return
    
    # DEBUG: Log what we're about to add
    print(f"DEBUG: Adding Pokemon to team - User: {user_id}, UUID: {poke_uuid}, Name: {poke.get('name')}, Level: {poke.get('level')}")
    
    # Additional verification - make sure we have the right Pokemon
    if not poke.get('uuid') or poke.get('uuid') != poke_uuid:
        print(f"ERROR: UUID mismatch! Expected: {poke_uuid}, Got: {poke.get('uuid')}")
        await callback_query.answer("Error: Pokémon UUID mismatch. Please try again.", show_alert=True)
        return
    
    # Check if already in team
    if any(team_poke.get('uuid') == poke_uuid for team_poke in team):
        await callback_query.answer("This Pokémon is already in your team!", show_alert=True)
        return
    
    # Create a deep copy of the pokemon to ensure data integrity
    import copy
    team_pokemon = copy.deepcopy(poke)
    
    # Ensure the Pokemon has all necessary fields for battle
    if not team_pokemon.get('active_moves'):
        team_pokemon['active_moves'] = []
    if not team_pokemon.get('moves'):
        team_pokemon['moves'] = []
    
    # Double-check that UUID is preserved
    if not team_pokemon.get('uuid'):
        team_pokemon['uuid'] = poke_uuid
    
    # Add to team
    team.append(team_pokemon)
    await db.users.update_one({"user_id": user_id}, {"$set": {"team": team}})
    
    # DEBUG: Log what was actually added
    print(f"DEBUG: Successfully added to team - UUID: {team_pokemon.get('uuid')}, Name: {team_pokemon.get('name')}, Level: {team_pokemon.get('level')}")
    
    await callback_query.answer(f"Added {team_pokemon.get('name', 'Unknown').title()} (Lv.{team_pokemon.get('level', 1)}) to your team!", show_alert=False)
    
    # Show updated team in the same message - skip sync to prevent replacement
    await myteam_command_reply(callback_query.message, user_id, skip_sync=True)

# Helper to reply/edit the same message for /myteam
async def myteam_command_reply(message, user_id, skip_sync=False):
    if not message or not hasattr(message, 'from_user') or not message.from_user:
        return
    username = getattr(message.from_user, 'username', '') or ''
    first_name = getattr(message.from_user, 'first_name', '') or ''
    user = await get_or_create_user(user_id, username, first_name)
    
    # Get team directly from database if skip_sync is True
    if skip_sync:
        team = user.get("team", [])
        print(f"DEBUG: Skipping sync for user {user_id}")
    else:
        # Sync team with collection
        team = await sync_team_with_collection(user_id, message.bot)
    
    text = "<b>Your Current Team:</b>\n"
    if team:
        for idx, poke in enumerate(team):
            text += f"{idx+1}. {poke['name'].title()} (Lv.{poke['level']})\n"
    else:
        text += "No Pokémon in your team!\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Edit Team", callback_data=f"myteam_edit_{user_id}")]
    ])
    if message and not isinstance(message, InaccessibleMessage) and hasattr(message, 'edit_text'):
        await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

# Remove Pokémon from team
@router.callback_query(lambda c: c.data and c.data.startswith("myteam_remove_"))
async def myteam_remove_menu(callback_query: CallbackQuery):
    if not callback_query.message:
        return
    user_id = int(callback_query.data.split("_")[-1]) if callback_query.data else None
    if user_id is None or not await is_callback_from_user(callback_query, user_id):
        return
    username = getattr(callback_query.from_user, 'username', '') or ''
    first_name = getattr(callback_query.from_user, 'first_name', '') or ''
    user = await get_or_create_user(user_id, username, first_name)
    team = user.get("team", [])
    if not team:
        await callback_query.answer("Your team is empty!", show_alert=True)
        return
    keyboard = []
    for idx, poke in enumerate(team):
        btn = InlineKeyboardButton(
            text=f"Remove {poke['name'].title()} (Lv.{poke['level']})",
            callback_data=f"myteam_removepoke_{idx}_{user_id}"
        )
        keyboard.append([btn])
    keyboard.append([InlineKeyboardButton(text="Back", callback_data=f"myteam_edit_{user_id}")])
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    if callback_query.message and not isinstance(callback_query.message, InaccessibleMessage) and hasattr(callback_query.message, 'edit_text'):
        await callback_query.message.edit_text("<b>Select a Pokémon to remove from your team:</b>", reply_markup=markup, parse_mode="HTML")

@router.callback_query(lambda c: c.data and c.data.startswith("myteam_removepoke_"))
async def myteam_removepoke_confirm(callback_query: CallbackQuery):
    if not callback_query.data:
        return
    parts = callback_query.data.split("_") if callback_query.data else []
    idx = int(parts[2]) if len(parts) > 2 else None
    user_id = int(parts[3]) if len(parts) > 3 else None
    if idx is None or user_id is None or not await is_callback_from_user(callback_query, user_id):
        return
    username = getattr(callback_query.from_user, 'username', '') or ''
    first_name = getattr(callback_query.from_user, 'first_name', '') or ''
    user = await get_or_create_user(user_id, username, first_name)
    team = user.get("team", [])
    if not (0 <= idx < len(team)):
        await callback_query.answer("Invalid selection!", show_alert=True)
        return
    poke = team.pop(idx)
    await db.users.update_one({"user_id": user_id}, {"$set": {"team": team}})
    await callback_query.answer(f"Removed {poke['name'].title()} from your team!", show_alert=False)
    await myteam_command_reply(callback_query.message, user_id)

# Change order of Pokémon in team
@router.callback_query(lambda c: c.data and c.data.startswith("myteam_reorder_"))
async def myteam_reorder_menu(callback_query: CallbackQuery):
    if not callback_query.message:
        return
    user_id = int(callback_query.data.split("_")[-1]) if callback_query.data else None
    if user_id is None or not await is_callback_from_user(callback_query, user_id):
        return
    username = getattr(callback_query.from_user, 'username', '') or ''
    first_name = getattr(callback_query.from_user, 'first_name', '') or ''
    user = await get_or_create_user(user_id, username, first_name)
    team = user.get("team", [])
    if len(team) < 2:
        await callback_query.answer("Need at least 2 Pokémon to reorder!", show_alert=True)
        return
    # Show each Pokémon with up/down buttons
    keyboard = []
    for idx, poke in enumerate(team):
        row = []
        if idx > 0:
            row.append(InlineKeyboardButton(text="⬆️", callback_data=f"myteam_moveup_{idx}_{user_id}"))
        if idx < len(team) - 1:
            row.append(InlineKeyboardButton(text="⬇️", callback_data=f"myteam_movedown_{idx}_{user_id}"))
        row.append(InlineKeyboardButton(text=f"{poke['name'].title()} (Lv.{poke['level']})", callback_data="noop"))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(text="Back", callback_data=f"myteam_edit_{user_id}")])
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    if callback_query.message and not isinstance(callback_query.message, InaccessibleMessage) and hasattr(callback_query.message, 'edit_text'):
        await callback_query.message.edit_text("<b>Change the order of your team:</b>", reply_markup=markup, parse_mode="HTML")

@router.callback_query(lambda c: c.data and c.data.startswith("myteam_moveup_"))
async def myteam_moveup(callback_query: CallbackQuery):
    if not callback_query.data:
        return
    parts = callback_query.data.split("_") if callback_query.data else []
    idx = int(parts[2]) if len(parts) > 2 else None
    user_id = int(parts[3]) if len(parts) > 3 else None
    if idx is None or user_id is None or not await is_callback_from_user(callback_query, user_id):
        return
    username = getattr(callback_query.from_user, 'username', '') or ''
    first_name = getattr(callback_query.from_user, 'first_name', '') or ''
    user = await get_or_create_user(user_id, username, first_name)
    team = user.get("team", [])
    if not (1 <= idx < len(team)):
        await callback_query.answer("Invalid move!", show_alert=True)
        return
    team[idx-1], team[idx] = team[idx], team[idx-1]
    await db.users.update_one({"user_id": user_id}, {"$set": {"team": team}})
    await myteam_reorder_menu(callback_query)

@router.callback_query(lambda c: c.data and c.data.startswith("myteam_movedown_"))
async def myteam_movedown(callback_query: CallbackQuery):
    if not callback_query.data:
        return
    parts = callback_query.data.split("_") if callback_query.data else []
    idx = int(parts[2]) if len(parts) > 2 else None
    user_id = int(parts[3]) if len(parts) > 3 else None
    if idx is None or user_id is None or not await is_callback_from_user(callback_query, user_id):
        return
    username = getattr(callback_query.from_user, 'username', '') or ''
    first_name = getattr(callback_query.from_user, 'first_name', '') or ''
    user = await get_or_create_user(user_id, username, first_name)
    team = user.get("team", [])
    if not (0 <= idx < len(team)-1):
        await callback_query.answer("Invalid move!", show_alert=True)
        return
    team[idx], team[idx+1] = team[idx+1], team[idx]
    await db.users.update_one({"user_id": user_id}, {"$set": {"team": team}})
    await myteam_reorder_menu(callback_query)

# Back button handler
@router.callback_query(lambda c: c.data and c.data.startswith("myteam_back_"))
async def myteam_back(callback_query: CallbackQuery):
    user_id = int(callback_query.data.split("_")[-1]) if callback_query.data else None
    if user_id is None or not await is_callback_from_user(callback_query, user_id):
        return
    await myteam_command_reply(callback_query.message, user_id)

# Manual sync command for debugging
@router.message(Command("syncteam"))
async def syncteam_command(message: types.Message):
    """Manual team sync command for debugging"""
    if not message or not hasattr(message, 'from_user') or not message.from_user:
        return
    user_id = message.from_user.id
    username = getattr(message.from_user, 'username', '') or ''
    first_name = getattr(message.from_user, 'first_name', '') or ''
    
    # Validate team integrity before sync
    integrity_issues = await validate_team_integrity(user_id, message.bot)
    if integrity_issues:
        print(f"Team integrity issues BEFORE sync for user {user_id}: {integrity_issues}")
        issues_text = "\n".join(integrity_issues)
        await message.reply(f"<b>Team integrity issues found:</b>\n{issues_text}", parse_mode="HTML")
    
    # Perform sync
    team = await sync_team_with_collection(user_id, message.bot)
    
    # Validate team integrity after sync
    integrity_issues_after = await validate_team_integrity(user_id, message.bot)
    if integrity_issues_after:
        print(f"Team integrity issues AFTER sync for user {user_id}: {integrity_issues_after}")
    
    # Show results
    text = "<b>Team synchronized!</b>\n\n<b>Current Team:</b>\n"
    if team:
        for idx, poke in enumerate(team):
            text += f"{idx+1}. {poke['name'].title()} (Lv.{poke['level']}) - UUID: {poke.get('uuid', 'N/A')[:8]}...\n"
    else:
        text += "No Pokémon in your team!\n"
    
    if message and not isinstance(message, InaccessibleMessage) and hasattr(message, 'reply'):
        await message.reply(text, parse_mode="HTML") 