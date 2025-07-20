from aiogram.types import Message, CallbackQuery
import inspect
from database import get_or_create_user

def filter_kwargs_for_function(func, kwargs):
    """Only pass kwargs that the function actually accepts"""
    sig = inspect.signature(func)
    valid_params = set(sig.parameters.keys())
    
    # Always allow **kwargs if the function has it
    if any(param.kind == param.VAR_KEYWORD for param in sig.parameters.values()):
        return kwargs
    
    # Otherwise, only pass arguments the function expects
    return {k: v for k, v in kwargs.items() if k in valid_params}

def require_started_user():
    """Decorator to ensure user has started the bot before using commands"""
    def decorator(func):
        async def wrapper(message: Message, *args, **kwargs):
            # Only pass kwargs that the function actually accepts
            filtered_kwargs = filter_kwargs_for_function(func, kwargs)
            
            user_id = message.from_user.id
            user = await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)
            
            if not user.get('already_started', False):
                await message.answer("❌ You need to claim your starter package first! Use /start command to begin your Pokémon journey.")
                return
            
            return await func(message, *args, **filtered_kwargs)
        return wrapper
    return decorator

def prevent_non_started_interaction():
    """Decorator to prevent interactions between started and non-started users"""
    def decorator(func):
        async def wrapper(callback_query: CallbackQuery, *args, **kwargs):
            # Only pass kwargs that the function actually accepts
            filtered_kwargs = filter_kwargs_for_function(func, kwargs)
            
            user_id = callback_query.from_user.id
            user = await get_or_create_user(user_id, getattr(callback_query.from_user, 'username', '') or '', getattr(callback_query.from_user, 'first_name', '') or '')
            
            if not user.get('already_started', False):
                await callback_query.answer("❌ You need to claim your starter package first! Use /start command to begin your Pokémon journey.", show_alert=True)
                return
            
            # Check if the message was sent by a non-started user, but only if from_user exists and is not the bot
            message_sender = getattr(callback_query.message, 'from_user', None)
            if message_sender is not None and hasattr(message_sender, 'is_bot') and not message_sender.is_bot:
                message_sender_id = message_sender.id
                message_sender_user = await get_or_create_user(message_sender_id, getattr(message_sender, 'username', '') or '', getattr(message_sender, 'first_name', '') or '')
                if not message_sender_user.get('already_started', False):
                    await callback_query.answer("❌ This message was sent by a user who hasn't started their Pokémon journey yet!", show_alert=True)
                    return
            return await func(callback_query, *args, **filtered_kwargs)
        return wrapper
    return decorator
