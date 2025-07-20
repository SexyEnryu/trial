import asyncio
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from database import get_or_create_user, kill_user, unkill_user, is_user_killed

# Admin user IDs
ADMIN_IDS = [7552373579, 7907063334, 1097600241, 1182033957, 1498348391, 7984578203, 1412946850]

# Create router for kill commands
kill_router = Router()

@kill_router.message(Command("kill"))
async def kill_command(message: Message):
    """
    Admin command to kill a user (disable them from using bot)
    Usage: /kill <user_id> or /kill (when replying to a user's message)
    """
    
    # Check if the user is admin
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("You don't have permission to use this command.")
        return
    
    target_user_id = None
    target_user_name = None
    target_user_link = None
    
    # Get command arguments
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    
    if args and args[0].isdigit():
        # Kill by user ID
        target_user_id = int(args[0])
        try:
            # Try to get user info from database
            user_data = await get_or_create_user(target_user_id, "", "")
            target_user_name = user_data.get('first_name', 'Unknown User')
            target_user_link = f"[{target_user_name}](tg://user?id={target_user_id})"
        except Exception:
            target_user_name = "Unknown User"
            target_user_link = f"[{target_user_name}](tg://user?id={target_user_id})"
    elif message.reply_to_message:
        # Kill by replying to user's message
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_user_name = target_user.first_name or "Unknown User"
        target_user_link = f"[{target_user_name}](tg://user?id={target_user_id})"
    else:
        await message.reply(
            "Please specify a user ID or reply to a user's message.\n"
            "<b>Usage:</b> <code>/kill &lt;user_id&gt;</code> or reply to a message with <code>/kill</code>",
            parse_mode='HTML'
        )
        return
    
    # Check if trying to kill an admin
    if target_user_id in ADMIN_IDS:
        await message.reply(f"You Cannot kill {target_user_link}", parse_mode='Markdown')
        return
    
    # Check if user is already killed
    if await is_user_killed(target_user_id):
        await message.reply(f"User {target_user_link} is already killed.", parse_mode='Markdown')
        return
    
    try:
        # Kill the user
        await kill_user(target_user_id)
        
        # Get admin info for the announcement
        admin_name = message.from_user.first_name or "Admin"
        admin_link = f"[{admin_name}](tg://user?id={message.from_user.id})"
        
        # Send kill announcement as a reply
        await message.reply(
            f"{admin_link} killed Pokemon Trainer {target_user_link}.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await message.reply(f"An error occurred: {str(e)}")

@kill_router.message(Command("revive"))
async def revive_command(message: Message):
    """
    Admin command to revive a user (re-enable them to use bot)
    Usage: /revive <user_id> or /revive (when replying to a user's message)
    """
    
    # Check if the user is admin
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("You don't have permission to use this command.")
        return
    
    target_user_id = None
    target_user_name = None
    target_user_link = None
    
    # Get command arguments
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    
    if args and args[0].isdigit():
        # Revive by user ID
        target_user_id = int(args[0])
        try:
            # Try to get user info from database
            user_data = await get_or_create_user(target_user_id, "", "")
            target_user_name = user_data.get('first_name', 'Unknown User')
            target_user_link = f"[{target_user_name}](tg://user?id={target_user_id})"
        except Exception:
            target_user_name = "Unknown User"
            target_user_link = f"[{target_user_name}](tg://user?id={target_user_id})"
    elif message.reply_to_message:
        # Revive by replying to user's message
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_user_name = target_user.first_name or "Unknown User"
        target_user_link = f"[{target_user_name}](tg://user?id={target_user_id})"
    else:
        await message.reply(
            "Please specify a user ID or reply to a user's message.\n"
            "<b>Usage:</b> <code>/revive &lt;user_id&gt;</code> or reply to a message with <code>/revive</code>",
            parse_mode='HTML'
        )
        return
    
    # Check if user is actually killed
    if not await is_user_killed(target_user_id):
        await message.reply(f"User {target_user_link} is not killed.", parse_mode='Markdown')
        return
    
    try:
        # Revive the user
        await unkill_user(target_user_id)
        
        # Get admin info for the announcement
        admin_name = message.from_user.first_name or "Admin"
        admin_link = f"[{admin_name}](tg://user?id={message.from_user.id})"
        
        # Send revive announcement as a reply
        await message.reply(
            f"{admin_link} revived Pokemon Trainer {target_user_link}.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await message.reply(f"An error occurred: {str(e)}")

@kill_router.message(Command("killedlist"))
async def killedlist_command(message: Message):
    """
    Admin command to list all killed users
    """
    
    # Check if the user is admin
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("You don't have permission to use this command.")
        return
    
    try:
        from database import get_killed_users
        killed_users = await get_killed_users()
        
        if not killed_users:
            await message.reply("No users are currently killed.")
            return
        
        # Format the list
        killed_list = "**Killed Users:**\n\n"
        for user in killed_users:
            user_id = user.get('user_id', 'Unknown')
            first_name = user.get('first_name', 'Unknown User')
            killed_list += f"• [{first_name}](tg://user?id={user_id}) (`{user_id}`)\n"
        
        await message.reply(killed_list, parse_mode='Markdown')
        
    except Exception as e:
        await message.reply(f"An error occurred: {str(e)}") 