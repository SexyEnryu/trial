from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from database import is_user_killed

class KillCheckMiddleware(BaseMiddleware):
    """
    Middleware to check if a user is killed before processing any command.
    Killed users will be ignored and the bot won't respond to them.
    """

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        # Skip the check for non-user events (like admin messages in channels)
        if not hasattr(event, 'from_user') or not event.from_user:
            return await handler(event, data)
        
        user_id = event.from_user.id
        
        # Check if user is killed
        if await is_user_killed(user_id):
            # User is killed, don't process the command
            # Just silently ignore the message/callback
            return
        
        # User is not killed, proceed with normal command processing
        return await handler(event, data) 