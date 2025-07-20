import asyncio
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InaccessibleMessage

router = Router()

# Store active pin timers
active_pins = {}

# Store original message references temporarily
pending_pins = {}

def is_bot_trade_or_duel_message(message: types.Message) -> bool:
    """Check if message is a trade or duel message from the bot"""
    if not message or not message.text:
        return False
    
    # Check for trade message indicators
    trade_indicators = [
        "Trade Request",
        "Trade Confirmation", 
        "Pokemon Selected",
        "Trade Failed",
        "Trade Successful"
    ]
    
    # Check for duel message indicators
    duel_indicators = [
        "challenges",
        "duel",
        "Current turn:",
        "Choose your next Pokémon",
        "wins the duel"
    ]
    
    text = message.text
    
    # Check if it's a trade message
    if any(indicator in text for indicator in trade_indicators):
        return True
    
    # Check if it's a duel message
    if any(indicator in text for indicator in duel_indicators):
        return True
    
    # Also check for inline keyboard with trade/duel callback data
    if message.reply_markup and message.reply_markup.inline_keyboard:
        for row in message.reply_markup.inline_keyboard:
            for button in row:
                if button.callback_data:
                    if (button.callback_data.startswith("trade_") or 
                        button.callback_data.startswith("duel_") or
                        button.callback_data.startswith("confirm_trade_") or
                        button.callback_data.startswith("continue_selection_")):
                        return True
    
    return False

@router.message(Command("xpin"))
async def xpin_command(message: types.Message):
    """Handle /xpin command to pin trade/duel messages"""
    
    # Check if the command is a reply to a message
    if not message.reply_to_message:
        await message.reply(
            "You must reply to a trade or duel message to use this command!",
            parse_mode='HTML'
        )
        return
    
    # Check if the replied message is from the bot
    if not message.reply_to_message.from_user or not message.reply_to_message.from_user.is_bot:
        await message.reply(
            "You can only pin messages from the bot!",
            parse_mode='HTML'
        )
        return
    
    # Check if it's a trade or duel message
    if not is_bot_trade_or_duel_message(message.reply_to_message):
        await message.reply(
            "You can only pin trade or duel messages!",
            parse_mode='HTML'
        )
        return
    
    # Check if user info is available
    if not message.from_user:
        await message.reply(
            "Unable to identify user. Please try again.",
            parse_mode='HTML'
        )
        return
    
    # Store the original message info in the callback data
    original_chat_id = message.reply_to_message.chat.id
    original_message_id = message.reply_to_message.message_id
    user_id = message.from_user.id
    
    # Store the original message reference temporarily 
    pin_ref_key = f"{user_id}_{original_chat_id}_{original_message_id}"
    pending_pins[pin_ref_key] = message.reply_to_message
    
    # Schedule cleanup of pending pin after 5 minutes if not used
    asyncio.create_task(cleanup_pending_pin_after_delay(pin_ref_key, 300))  # 5 minutes
    
    # Create inline keyboard with duration options
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="5 minutes", callback_data=f"xpin_5_{user_id}_{original_chat_id}_{original_message_id}"),
            InlineKeyboardButton(text="10 minutes", callback_data=f"xpin_10_{user_id}_{original_chat_id}_{original_message_id}")
        ]
    ])
    
    await message.reply(
        "<b>Choose pin duration:</b>",
        reply_markup=keyboard,
        parse_mode='HTML'
    )

@router.callback_query(lambda c: c.data and c.data.startswith("xpin_"))
async def handle_xpin_callback(callback_query: CallbackQuery):
    """Handle xpin duration selection"""
    
    if not callback_query.data or not callback_query.from_user:
        await callback_query.answer("Invalid callback data!", show_alert=True)
        return
    
    # Parse callback data
    try:
        parts = callback_query.data.split("_")
        if len(parts) == 5:
            # New format: xpin_duration_user_id_chat_id_message_id
            _, duration_str, original_user_id_str, original_chat_id_str, original_message_id_str = parts
            duration = int(duration_str)
            original_user_id = int(original_user_id_str)
            original_chat_id = int(original_chat_id_str)
            original_message_id = int(original_message_id_str)
        elif len(parts) == 3:
            # Old format: xpin_duration_user_id (for backward compatibility)
            _, duration_str, original_user_id_str = parts
            duration = int(duration_str)
            original_user_id = int(original_user_id_str)
            # Fall back to old method for finding original message
            original_chat_id = None
            original_message_id = None
        else:
            raise ValueError("Invalid callback data format")
    except (ValueError, IndexError):
        await callback_query.answer("Invalid callback data format!", show_alert=True)
        return
    
    # Check if the user who clicked is the same as who called the command
    if callback_query.from_user.id != original_user_id:
        await callback_query.answer("Only the user who called the command can interact with these buttons!", show_alert=True)
        return
    
    # Get the original message that should be pinned
    original_message = None
    pin_ref_key = None
    
    if original_chat_id is not None and original_message_id is not None:
        # New format - try to get from pending_pins
        pin_ref_key = f"{original_user_id}_{original_chat_id}_{original_message_id}"
        if pin_ref_key in pending_pins:
            original_message = pending_pins[pin_ref_key]
        else:
            await callback_query.answer("Could not find the original message to pin! Please try the /xpin command again.", show_alert=True)
            return
    else:
        # Old format - fall back to message chain method
        if (callback_query.message and 
            not isinstance(callback_query.message, InaccessibleMessage) and
            callback_query.message.reply_to_message and 
            callback_query.message.reply_to_message.reply_to_message):
            original_message = callback_query.message.reply_to_message.reply_to_message
        else:
            await callback_query.answer("Could not find the original message to pin!", show_alert=True)
            return
    
    if not original_message:
        await callback_query.answer("Could not find the original message to pin!", show_alert=True)
        return
    
    try:
        # Pin the message
        await original_message.pin(disable_notification=True)
        
        # Calculate expiry time
        expiry_time = asyncio.get_event_loop().time() + (duration * 60)
        
        # Store the pin info
        pin_key = f"{original_message.chat.id}_{original_message.message_id}"
        active_pins[pin_key] = {
            'chat_id': original_message.chat.id,
            'message_id': original_message.message_id,
            'expiry_time': expiry_time,
            'user_id': original_user_id
        }
        
        # Clean up the pending pin reference
        if pin_ref_key:
            pending_pins.pop(pin_ref_key, None)
        
        # Schedule auto-unpin
        asyncio.create_task(auto_unpin_after_delay(pin_key, duration * 60))
        
        # Update the callback message
        if (callback_query.message and 
            not isinstance(callback_query.message, InaccessibleMessage) and
            hasattr(callback_query.message, 'edit_text')):
            await callback_query.message.edit_text(
                f"<b>Message pinned successfully!</b>\n"
                f"Duration: {duration} minutes\n"
                f"Will auto-unpin after {duration} minutes",
                parse_mode='HTML'
            )
        
        await callback_query.answer(f"Message pinned for {duration} minutes!")
        
    except Exception as e:
        # Clean up the pending pin reference on error
        if pin_ref_key:
            pending_pins.pop(pin_ref_key, None)
        await callback_query.answer(f"❌ Failed to pin message: {str(e)}", show_alert=True)

# Store the bot instance for auto-unpinning
_bot_instance = None

def set_bot_instance(bot):
    """Set the bot instance for auto-unpinning"""
    global _bot_instance
    _bot_instance = bot

async def auto_unpin_after_delay(pin_key: str, delay_seconds: int):
    """Auto-unpin message after delay"""
    await asyncio.sleep(delay_seconds)
    
    if pin_key in active_pins:
        pin_info = active_pins[pin_key]
        
        try:
            # Use the stored bot instance
            if _bot_instance:
                # Unpin the message
                await _bot_instance.unpin_chat_message(
                    chat_id=pin_info['chat_id'],
                    message_id=pin_info['message_id']
                )
                
                # Send notification (optional)
                await _bot_instance.send_message(
                    chat_id=pin_info['chat_id'],
                    text=f"<b>Auto-unpinned message</b>\n"
                         f"Pin duration expired",
                    parse_mode='HTML'
                )
            else:
                print("Bot instance not available for auto-unpinning")
                
        except Exception as e:
            print(f"Error auto-unpinning message: {e}")
        
        finally:
            # Remove from active pins
            if pin_key in active_pins:
                del active_pins[pin_key]

async def cleanup_pending_pin_after_delay(pin_ref_key: str, delay_seconds: int):
    """Cleanup a pending pin if it's not interacted with within the delay."""
    await asyncio.sleep(delay_seconds)
    
    if pin_ref_key in pending_pins:
        # Just remove the pending reference, don't unpin anything
        # since these are messages waiting for duration selection, not pinned messages
        pending_pins.pop(pin_ref_key, None)
        print(f"Cleaned up unused pending pin reference: {pin_ref_key}")