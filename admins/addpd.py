import asyncio
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from database import update_user_balance, get_user_balance, get_or_create_user, set_user_balance

# Admin user IDs
ADMIN_IDS = [7552373579, 7907063334,1097600241, 1182033957, 1498348391, 7984578203, 1412946850]

# Create router for admin commands
admin_router = Router()

@admin_router.message(Command("addpd"))
async def addpd_command(message: Message):
    """
    Admin command to add PokeDollars to a user
    Usage: /addpd <amount> (when replying to a user's message)
    Only admin with ID 7552373579 can use this command
    """
    
    # Check if the user is admin
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("❌ You don't have permission to use this command.")
        return
    
    # Check if the command is used as a reply to another message
    if not message.reply_to_message:
        await message.reply("❌ Please reply to a user's message to add PokeDollars to them.")
        return
    
    # Get command arguments
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    
    # Check if amount is provided
    if not args:
        await message.reply(
            "❌ Please specify an amount.\n<b>Usage:</b> <code>/addpd &lt;amount&gt;</code>",
            parse_mode='HTML'
        )
        return
    
    try:
        # Parse the amount
        amount = int(args[0])
        
        # Get the target user from the replied message
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_username = target_user.username or target_user.first_name
        
        # Ensure the target user exists in database
        await get_or_create_user(target_user_id, target_username, target_user.first_name)
        
        # Get current balance
        current_balance = await get_user_balance(target_user_id)
        
        # Update the balance
        success = await update_user_balance(target_user_id, amount)
        
        if success:
            new_balance = await get_user_balance(target_user_id)
            
            # Send success message
            await message.reply(
                f"<b>Admin Action Complete</b>\n\n"
                f"Added <b>{amount:,} PokeDollars 💵 </b> to {target_username}\n"
                f"Balance: {current_balance:,} → {new_balance:,} PokeDollars 💵 ",
                parse_mode='HTML'
            )
            
            # Optionally notify the target user
            try:
                await message.bot.send_message(
                    chat_id=target_user_id,
                    text=f"🎉 <b>You received PokeDollars!</b>\n\n"
                         f"💰 <b>+{amount:,} PokeDollars 💵 </b> added to your account\n"
                         f"New Balance: <b>{new_balance:,} PokeDollars 💵 </b>",
                    parse_mode='HTML'
                )
            except (TelegramBadRequest, TelegramForbiddenError):
                # If we can't send DM to user, that's okay
                pass
                
        else:
            await message.reply("❌ Failed to add PokeDollars. Please try again.")
            
    except ValueError:
        await message.reply(
            "❌ Invalid amount. Please enter a valid number.\n<b>Usage:</b> <code>/addpd &lt;amount&gt;</code>",
            parse_mode='HTML'
        )
    except Exception as e:
        await message.reply(f"❌ An error occurred: {str(e)}")

@admin_router.message(Command("addpd_advanced"))
async def addpd_advanced_command(message: Message):
    """
    Advanced admin command to add PokeDollars to a user
    Usage: /addpd_advanced <amount> (when replying to a user's message)
    Only admin with ID 7552373579 can use this command
    """
    
    # Check if the user is admin
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("❌ You don't have permission to use this command.")
        return
    
    # Check if the command is used as a reply to another message
    if not message.reply_to_message:
        await message.reply("❌ Please reply to a user's message to add PokeDollars to them.")
        return
    
    # Get command arguments
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    
    # Check if amount is provided
    if not args:
        await message.reply(
            "❌ Please specify an amount.\n"
            "<b>Usage:</b> <code>/addpd_advanced &lt;amount&gt;</code>",
            parse_mode='HTML'
        )
        return
    
    try:
        # Parse the amount
        amount = int(args[0])
        
        # Validate amount (optional: set limits)
        if amount < 1:
            await message.reply("❌ Amount must be positive.")
            return
        
        if amount > 1000000:  # 1M limit
            await message.reply("❌ Amount too large. Maximum is 1,000,000 PokeDollars.")
            return
        
        # Get the target user from the replied message
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_username = target_user.username or target_user.first_name
        
        # Don't allow adding to self (admin)
        if target_user_id == ADMIN_IDS:
            await message.reply("❌ Cannot add PokeDollars to yourself.")
            return
        
        # Ensure the target user exists in database
        await get_or_create_user(target_user_id, target_username, target_user.first_name)
        
        # Get current balance
        current_balance = await get_user_balance(target_user_id)
        
        # Update the balance
        success = await update_user_balance(target_user_id, amount)
        
        if success:
            new_balance = await get_user_balance(target_user_id)
            
            # Send success message
            await message.reply(
                f"<b>Admin Action Complete</b>\n\n"
                f"<b>User:</b> {target_username} (<code>{target_user_id}</code>)\n"
                f"<b>Amount:</b> +{amount:,} PokeDollars 💵 \n"
                f"<b>Balance:</b> {current_balance:,} → {new_balance:,}",
                parse_mode='HTML'
            )
            
            # Notify the target user
            try:
                await message.bot.send_message(
                    chat_id=target_user_id,
                    text=f"🎉 <b>You received PokeDollars!</b>\n\n"
                         f"💰 <b>+{amount:,} PokeDollars</b>\n"
                         f"💵 <b>New Balance:</b> {new_balance:,} PokeDollars",
                    parse_mode='HTML'
                )
            except (TelegramBadRequest, TelegramForbiddenError):
                # If we can't send DM to user, mention it
                await message.reply(
                    f"⚠️ Could not send notification to {target_username} (DMs may be disabled)",
                    parse_mode='HTML'
                )
                
        else:
            await message.reply("❌ Failed to add PokeDollars. Please try again.")
            
    except ValueError:
        await message.reply(
            "❌ Invalid amount. Please enter a valid number.\n"
            "<b>Usage:</b> <code>/addpd_advanced &lt;amount&gt;</code>",
            parse_mode='HTML'
        )
    except Exception as e:
        await message.reply(f"❌ An error occurred: {str(e)}")

@admin_router.message(Command("checkbalance"))
async def checkbalance_command(message: Message):
    """
    Admin command to check any user's balance
    Usage: /checkbalance (when replying to a user's message)
    """
    
    # Check if the user is admin
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("You don't have permission to use this command.")
        return
    
    # Check if the command is used as a reply to another message
    if not message.reply_to_message:
        await message.reply("❌ Please reply to a user's message to check their balance.")
        return
    
    try:
        # Get the target user from the replied message
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_username = target_user.username or target_user.first_name
        
        # Get user balance
        balance = await get_user_balance(target_user_id)
        
        # Send balance info
        await message.reply(
            f"💰 **Balance Check**\n\n"
            f"**User:** {target_username} (`{target_user_id}`)\n"
            f"**Balance:** {balance:,} PokeDollars 💵 ",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await message.reply(f"❌ An error occurred: {str(e)}")

@admin_router.message(Command("setpd"))
async def setpd_command(message: Message):
    """
    Admin command to set PokeDollars to a specific value for a user
    Usage: /setpd <amount> (when replying to a user's message)
    """
    # Check if the user is admin
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("❌ You don't have permission to use this command.")
        return

    # Check if the command is used as a reply to another message
    if not message.reply_to_message:
        await message.reply("❌ Please reply to a user's message to set their PokeDollars.")
        return

    # Get command arguments
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []

    # Check if amount is provided
    if not args:
        await message.reply(
            "❌ Please specify an amount.\n<b>Usage:</b> <code>/setpd &lt;amount&gt;</code>",
            parse_mode='HTML'
        )
        return

    try:
        # Parse the amount
        amount = int(args[0])
        if amount < 0:
            await message.reply("❌ Amount must be non-negative.")
            return

        # Get the target user from the replied message
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_username = target_user.username or target_user.first_name

        # Ensure the target user exists in database
        await get_or_create_user(target_user_id, target_username, target_user.first_name)

        # Get current balance
        current_balance = await get_user_balance(target_user_id)

        # Set the balance
        success = await set_user_balance(target_user_id, amount)

        if success:
            new_balance = await get_user_balance(target_user_id)
            await message.reply(
                f"<b>Admin Action Complete</b>\n\n"
                f"Set <b>{target_username}</b>'s PokeDollars to <b>{amount:,} 💵</b>\n"
                f"Balance: {current_balance:,} → {new_balance:,} PokeDollars 💵 ",
                parse_mode='HTML'
            )
            # Optionally notify the target user
            try:
                await message.bot.send_message(
                    chat_id=target_user_id,
                    text=f"🛠️ <b>Your PokeDollars have been set by an admin.</b>\n\n"
                         f"💰 <b>New Balance:</b> <b>{new_balance:,} PokeDollars 💵</b>",
                    parse_mode='HTML'
                )
            except (TelegramBadRequest, TelegramForbiddenError):
                pass
        else:
            await message.reply("❌ Failed to set PokeDollars. Please try again.")
    except ValueError:
        await message.reply(
            "❌ Invalid amount. Please enter a valid number.\n<b>Usage:</b> <code>/setpd &lt;amount&gt;</code>",
            parse_mode='HTML'
        )
    except Exception as e:
        await message.reply(f"❌ An error occurred: {str(e)}")

# Alternative implementation using filters for admin-only commands
def is_admin(message: Message) -> bool:
    """Check if user is admin"""
    return message.from_user.id in ADMIN_IDS

@admin_router.message(Command("removepd"), F.func(is_admin))
async def removepd_command(message: Message):
    """
    Admin command to remove PokeDollars from a user
    Usage: /removepd <amount> (when replying to a user's message)
    """
    
    # Check if the command is used as a reply to another message
    if not message.reply_to_message:
        await message.reply("❌ Please reply to a user's message to remove PokeDollars from them.")
        return
    
    # Get command arguments
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    
    # Check if amount is provided
    if not args:
        await message.reply(
            "❌ Please specify an amount.\n<b>Usage:</b> <code>/removepd &lt;amount&gt;</code>",
            parse_mode='HTML'
        )
        return
    
    try:
        # Parse the amount (negative for removal)
        amount = -int(args[0])
        
        # Get the target user from the replied message
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_username = target_user.username or target_user.first_name
        
        # Get current balance
        current_balance = await get_user_balance(target_user_id)
        
        # Check if user has enough balance
        if current_balance + amount < 0:
            await message.reply(
                f"❌ Cannot remove {abs(amount):,} PokeDollars.\n"
                f"User only has {current_balance:,} PokeDollars."
            )
            return
        
        # Update the balance
        success = await update_user_balance(target_user_id, amount)
        
        if success:
            new_balance = await get_user_balance(target_user_id)
            
            # Send success message
            await message.reply(
                f"<b>Admin Action Complete</b>\n\n"
                f"Removed <b>{abs(amount):,} PokeDollars 💵 </b> from {target_username}\n"
                f"Balance: {current_balance:,} → {new_balance:,} PokeDollars 💵 ",
                parse_mode='HTML'
            )
            
        else:
            await message.reply("❌ Failed to remove PokeDollars. Please try again.")
            
    except ValueError:
        await message.reply(
            "❌ Invalid amount. Please enter a valid number.\n<b>Usage:</b> <code>/removepd &lt;amount&gt;</code>",
            parse_mode='HTML'
        )
    except Exception as e:
        await message.reply(f"❌ An error occurred: {str(e)}")

# How to add these commands to your bot
def setup_admin_commands(dp):
    """
    Add admin commands to the dispatcher
    Call this function in your main bot setup
    
    Usage in main.py:
    from admin_commands import setup_admin_commands, admin_router
    setup_admin_commands(dp)
    """
    dp.include_router(admin_router)

# Example usage in your main bot file:
"""
from aiogram import Bot, Dispatcher
from admin_commands import setup_admin_commands, admin_router

# Initialize bot and dispatcher
bot = Bot(token="YOUR_BOT_TOKEN")
dp = Dispatcher()

# Setup admin commands
setup_admin_commands(dp)

# Or directly include the router
# dp.include_router(admin_router)

# Start polling
if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
"""