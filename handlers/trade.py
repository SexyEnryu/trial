import json
import asyncio
import math
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import get_user_pokemon, update_user_pokemon_collection
import config

router = Router()

# Store active trade requests
active_trades = {}

class TradeRequest:
    def __init__(self, initiator_id, target_id, initiator_name, target_name, message_id, chat_id):
        self.initiator_id = initiator_id
        self.target_id = target_id
        self.initiator_name = initiator_name
        self.target_name = target_name
        self.initiator_pokemon_index = None
        self.target_pokemon_index = None
        self.initiator_confirmed = False
        self.target_confirmed = False
        self.message_id = message_id
        self.chat_id = chat_id
        self.trade_id = f"{initiator_id}_{target_id}_{asyncio.get_event_loop().time()}"
        self.current_phase = "waiting_response"  # waiting_response, initiator_selecting, target_selecting, confirming
        self.current_page = 0  # For pagination

def create_user_link(user_id, first_name):
    """Create a clickable user link"""
    return f"<a href='tg://user?id={user_id}'>{first_name}</a>"

def get_pokemon_display_name(pokemon):
    """Get Pokemon display name with shiny sparkles if shiny"""
    name = pokemon.get('name', 'Unknown').title()
    is_shiny = pokemon.get('is_shiny', False)
    return f"✨ {name} ✨" if is_shiny else name

def get_pokemon_iv_display(pokemon):
    """Get Pokemon IV values in correct format"""
    ivs = pokemon.get('ivs', {})
    
    # Handle both formats: {'HP': 31, 'Attack': 25, ...} and {'hp': 31, 'atk': 25, ...}
    iv_hp = ivs.get('HP', ivs.get('hp', 0))
    iv_atk = ivs.get('Attack', ivs.get('atk', ivs.get('attack', 0)))
    iv_def = ivs.get('Defense', ivs.get('def', ivs.get('defense', 0)))
    iv_spa = ivs.get('Sp. Attack', ivs.get('spa', ivs.get('special-attack', 0)))
    iv_spd = ivs.get('Sp. Defense', ivs.get('spd', ivs.get('special-defense', 0)))
    iv_spe = ivs.get('Speed', ivs.get('speed', 0))
    
    return f"HP:{iv_hp} ATK:{iv_atk} DEF:{iv_def} SpA:{iv_spa} SpD:{iv_spd} SPE:{iv_spe}"

def get_pokemon_ev_display(pokemon):
    """Get Pokemon EV values in correct format"""
    evs = pokemon.get('evs', {})
    
    # Handle both formats: {'HP': 31, 'Attack': 25, ...} and {'hp': 31, 'atk': 25, ...}
    ev_hp = evs.get('HP', evs.get('hp', 0))
    ev_atk = evs.get('Attack', evs.get('atk', evs.get('attack', 0)))
    ev_def = evs.get('Defense', evs.get('def', evs.get('defense', 0)))
    ev_spa = evs.get('Sp. Attack', evs.get('spa', evs.get('special-attack', 0)))
    ev_spd = evs.get('Sp. Defense', evs.get('spd', evs.get('special-defense', 0)))
    ev_spe = evs.get('Speed', evs.get('speed', 0))
    
    return f"HP:{ev_hp} ATK:{ev_atk} DEF:{ev_def} SpA:{ev_spa} SpD:{ev_spd} SPE:{ev_spe}"

@router.message(Command("trade"))
async def trade(message: types.Message):
    """Initiate a trade with a user by replying to their message"""
    if not message.reply_to_message:
        await message.answer(
            "You must reply to a message to initiate a trade with that user!\n\n"
            "Usage: Reply to someone's message with <code>/trade</code> to start trading with them.",
            parse_mode='HTML'
        )
        return
    
    # Add null checks for linter errors
    if not message.from_user:
        await message.answer("Unable to identify user. Please try again.", parse_mode='HTML')
        return
    
    if not message.reply_to_message.from_user:
        await message.answer("Unable to identify target user. Please try again.", parse_mode='HTML')
        return
    
    initiator_id = message.from_user.id
    target_id = message.reply_to_message.from_user.id
    
    if initiator_id == target_id:
        await message.answer("You cannot trade with yourself!", parse_mode='HTML')
        return
    
    initiator_name = message.from_user.first_name or "User"
    target_name = message.reply_to_message.from_user.first_name or "User"
    
    # Check if there's already an active trade between these users
    for trade_id, trade_request in active_trades.items():
        if ((trade_request.initiator_id == initiator_id and trade_request.target_id == target_id) or
            (trade_request.initiator_id == target_id and trade_request.target_id == initiator_id)):
            await message.answer("There's already an active trade request between you two!", parse_mode='HTML')
            return
    
    # Create trade message with user links
    initiator_link = create_user_link(initiator_id, initiator_name)
    target_link = create_user_link(target_id, target_name)
    
    trade_text = f"<b><u>Trade Request</u></b>\n\n"
    trade_text += f"<b>{initiator_name}</b> has requested a Pokemon trade with <b>{target_name}</b>\n\n"
    trade_text += f"{initiator_link} ↔ {target_link}\n\n"
    trade_text += "<i>Waiting for response...</i>"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Accept", callback_data=f"trade_accept_{initiator_id}_{target_id}"),
            InlineKeyboardButton(text="Decline", callback_data=f"trade_decline_{initiator_id}_{target_id}")
        ]
    ])
    
    # Send trade message as reply to the original message
    if message.reply_to_message:
        trade_message = await message.reply_to_message.reply(
            text=trade_text,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
        
        # Create new trade request
        trade_request = TradeRequest(initiator_id, target_id, initiator_name, target_name, trade_message.message_id, message.chat.id)
        active_trades[trade_request.trade_id] = trade_request

@router.callback_query(lambda c: c.data and (c.data.startswith("trade_accept_") or c.data.startswith("trade_decline_")))
async def handle_trade_response(callback_query: types.CallbackQuery):
    """Handle accept/decline responses to trade requests"""
    await callback_query.answer()
    
    if not callback_query.data:
        return
    
    data = callback_query.data
    action = data.split('_')[1]
    initiator_id = int(data.split('_')[2])
    target_id = int(data.split('_')[3])
    
    # Find the correct trade by matching initiator and target IDs
    trade_id = None
    for tid, trade_request in active_trades.items():
        if trade_request.initiator_id == initiator_id and trade_request.target_id == target_id:
            trade_id = tid
            break
    
    if not trade_id or trade_id not in active_trades:
        try:
            if callback_query.message and hasattr(callback_query.message, 'edit_text'):
                await callback_query.message.edit_text(
                    "This trade request has expired or been cancelled.", 
                    parse_mode='HTML'
                )
        except:
            pass
        return
    
    trade_request = active_trades[trade_id]
    
    # Check if the user clicking is the target user
    if not callback_query.from_user or callback_query.from_user.id != trade_request.target_id:
        await callback_query.answer("Only the target user can respond to this trade request!", show_alert=True)
        return
    
    if action == "decline":
        # Update message to show declined
        initiator_link = create_user_link(trade_request.initiator_id, trade_request.initiator_name)
        target_link = create_user_link(trade_request.target_id, trade_request.target_name)
        
        try:
            if callback_query.message and hasattr(callback_query.message, 'edit_text'):
                await callback_query.message.edit_text(
                    f"<b><u>Trade Declined</u></b>\n\n"
                    f"<b>{trade_request.target_name}</b> declined the trade request from <b>{trade_request.initiator_name}</b>.\n\n"
                    f"{target_link} ↔ {initiator_link}",
                    parse_mode='HTML'
                )
        except:
            pass
        del active_trades[trade_id]
        return
    
    elif action == "accept":
        # Start initiator's Pokemon selection phase
        trade_request.current_phase = "initiator_selecting"
        await show_pokemon_selection_phase(callback_query.bot, trade_id)

async def show_pokemon_selection_phase(bot, trade_id: str):
    """Show Pokemon selection phase for current user"""
    if trade_id not in active_trades:
        return
    
    trade_request = active_trades[trade_id]
    
    if trade_request.current_phase == "initiator_selecting":
        current_user_id = trade_request.initiator_id
        current_user_name = trade_request.initiator_name
        pokemon_list = await get_user_pokemon(current_user_id)
    elif trade_request.current_phase == "target_selecting":
        current_user_id = trade_request.target_id
        current_user_name = trade_request.target_name
        pokemon_list = await get_user_pokemon(current_user_id)
    else:
        return
    
    # Check if user has Pokemon to trade
    if not pokemon_list:
        # Update message to show no Pokemon available
        no_pokemon_text = f"<b><u>No Pokemon Available</u></b>\n\n"
        no_pokemon_text += f"<b>{current_user_name}</b> doesn't have any Pokemon to trade.\n\n"
        no_pokemon_text += "The trade has been cancelled."
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Close", callback_data=f"cancel_trade_{trade_id}")]
        ])
        
        try:
            await bot.edit_message_text(
                chat_id=trade_request.chat_id,
                message_id=trade_request.message_id,
                text=no_pokemon_text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"Error updating trade message: {e}")
        return
    
    # Pagination settings
    pokemon_per_page = 15
    total_pages = math.ceil(len(pokemon_list) / pokemon_per_page)
    current_page = trade_request.current_page
    
    # Ensure current_page is within valid range
    if current_page >= total_pages:
        current_page = total_pages - 1
        trade_request.current_page = current_page
    
    # Calculate start and end indices for current page
    start_idx = current_page * pokemon_per_page
    end_idx = min(start_idx + pokemon_per_page, len(pokemon_list))
    current_pokemon = pokemon_list[start_idx:end_idx]
    
    # Create text display of Pokemon
    pokemon_text = f"<b><u>{current_user_name}'s Pokemon Collection</u></b>\n\n"
    pokemon_text += f"<i>Page {current_page + 1}/{total_pages} • Select your Pokemon to trade:</i>\n\n"
    
    for i, pokemon in enumerate(current_pokemon):
        pokemon_name = get_pokemon_display_name(pokemon)
        level = pokemon.get('level', 1)
        nature = pokemon.get('nature', 'Hardy')
        pokemon_text += f"<b>{start_idx + i + 1}.</b> {pokemon_name} (Lv.{level}) - {nature}\n"
    
    # Create keyboard for Pokemon selection
    keyboard = []
    
    # Pokemon selection buttons (4 per row for better layout)
    for i in range(0, len(current_pokemon), 4):
        row = []
        for j in range(4):
            if i + j < len(current_pokemon):
                pokemon_index = start_idx + i + j
                row.append(InlineKeyboardButton(
                    text=f"{start_idx + i + j + 1}",
                    callback_data=f"select_pokemon_{pokemon_index}_{trade_id}"
                ))
        keyboard.append(row)
    
    # Navigation buttons
    nav_buttons = []
    if current_page > 0:
        nav_buttons.append(InlineKeyboardButton(text="Previous", callback_data=f"prev_page_{trade_id}"))
    if current_page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Next", callback_data=f"next_page_{trade_id}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # Cancel button
    keyboard.append([InlineKeyboardButton(text="Cancel Trade", callback_data=f"cancel_trade_{trade_id}")])
    
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    try:
        await bot.edit_message_text(
            chat_id=trade_request.chat_id,
            message_id=trade_request.message_id,
            text=pokemon_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    except Exception as e:
        print(f"Error updating trade message: {e}")

@router.callback_query(lambda c: c.data and (c.data.startswith("select_pokemon_") or c.data.startswith("prev_page_") or c.data.startswith("next_page_") or c.data.startswith("cancel_trade_")))
async def handle_pokemon_selection(callback_query: types.CallbackQuery):
    """Handle Pokemon selection and navigation"""
    await callback_query.answer()
    
    if not callback_query.data:
        return
    
    data = callback_query.data
    
    # Extract trade_id from callback data
    if data.startswith("select_pokemon_"):
        # Format: select_pokemon_{pokemon_index}_{trade_id}
        remaining = data[len("select_pokemon_"):]
        parts = remaining.split('_', 1)
        trade_id = parts[1] if len(parts) > 1 else ""
    else:
        # Format: {action}_page_{trade_id} or cancel_trade_{trade_id}
        if data.startswith("cancel_trade_"):
            trade_id = data[len("cancel_trade_"):]
        elif data.startswith("prev_page_"):
            trade_id = data[len("prev_page_"):]
        elif data.startswith("next_page_"):
            trade_id = data[len("next_page_"):]
        else:
            trade_id = data.split('_')[-1]
    
    if not trade_id or trade_id not in active_trades:
        return
    
    trade_request = active_trades[trade_id]
    
    if data.startswith("cancel_trade_"):
        # Create user links for cancellation message
        initiator_link = create_user_link(trade_request.initiator_id, trade_request.initiator_name)
        target_link = create_user_link(trade_request.target_id, trade_request.target_name)
        
        user_name = callback_query.from_user.first_name or "User" if callback_query.from_user else "User"
        
        try:
            if callback_query.message and hasattr(callback_query.message, 'edit_text'):
                await callback_query.message.edit_text(
                    f"<b><u>Trade Cancelled</u></b>\n\n"
                    f"<b>{user_name}</b> cancelled the trade between <b>{trade_request.initiator_name}</b> and <b>{trade_request.target_name}</b>.\n\n"
                    f"{initiator_link} ↔ {target_link}",
                    parse_mode='HTML'
                )
        except:
            pass
        del active_trades[trade_id]
        return
    
    # Check if user has permission to interact
    user_id = callback_query.from_user.id if callback_query.from_user else None
    if not user_id:
        return
    
    if not ((trade_request.current_phase == "initiator_selecting" and trade_request.initiator_id == user_id) or
            (trade_request.current_phase == "target_selecting" and trade_request.target_id == user_id)):
        await callback_query.answer("It's not your turn to select!", show_alert=True)
        return
    
    if data.startswith("prev_page_"):
        trade_request.current_page = max(0, trade_request.current_page - 1)
        await show_pokemon_selection_phase(callback_query.bot, trade_id)
        return
    
    if data.startswith("next_page_"):
        # Get current user's Pokemon to check total pages
        if trade_request.current_phase == "initiator_selecting":
            pokemon_list = await get_user_pokemon(trade_request.initiator_id)
        else:
            pokemon_list = await get_user_pokemon(trade_request.target_id)
        
        total_pages = math.ceil(len(pokemon_list) / 15)
        if trade_request.current_page < total_pages - 1:
            trade_request.current_page += 1
            await show_pokemon_selection_phase(callback_query.bot, trade_id)
        else:
            await callback_query.answer("Already on the last page!", show_alert=True)
        return
    
    if data.startswith("select_pokemon_"):
        # Extract pokemon_index and trade_id from select_pokemon_{pokemon_index}_{trade_id}
        remaining = data[len("select_pokemon_"):]
        parts = remaining.split('_', 1)
        pokemon_index = int(parts[0])
        
        # Validate Pokemon index
        if trade_request.current_phase == "initiator_selecting":
            pokemon_list = await get_user_pokemon(trade_request.initiator_id)
        else:
            pokemon_list = await get_user_pokemon(trade_request.target_id)
        
        if pokemon_index >= len(pokemon_list):
            await callback_query.answer("Invalid Pokemon selection!", show_alert=True)
            return
        
        selected_pokemon = pokemon_list[pokemon_index]
        pokemon_name = get_pokemon_display_name(selected_pokemon)
        
        # Store the selected Pokemon index
        if trade_request.current_phase == "initiator_selecting":
            trade_request.initiator_pokemon_index = pokemon_index
            # Move to target selection phase
            trade_request.current_phase = "target_selecting"
            trade_request.current_page = 0  # Reset page for target
            
            # Show confirmation message
            initiator_link = create_user_link(trade_request.initiator_id, trade_request.initiator_name)
            target_link = create_user_link(trade_request.target_id, trade_request.target_name)
            
            selection_text = f"<b><u>Pokemon Selected</u></b>\n\n"
            selection_text += f"<b>{trade_request.initiator_name}</b> selected: {pokemon_name}\n\n"
            selection_text += f"Now <b>{trade_request.target_name}</b> should select their Pokemon...\n\n"
            selection_text += f"{initiator_link} ↔ {target_link}"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Continue", callback_data=f"continue_selection_{trade_id}")]
            ])
            
            try:
                if callback_query.message and hasattr(callback_query.message, 'edit_text'):
                    await callback_query.message.edit_text(
                        text=selection_text,
                        reply_markup=keyboard,
                        parse_mode='HTML'
                    )
            except Exception as e:
                print(f"Error updating selection message: {e}")
                
        elif trade_request.current_phase == "target_selecting":
            trade_request.target_pokemon_index = pokemon_index
            # Move to confirmation phase
            trade_request.current_phase = "confirming"
            await show_trade_confirmation(callback_query.bot, trade_id)

@router.callback_query(lambda c: c.data and c.data.startswith("continue_selection_"))
async def continue_selection(callback_query: types.CallbackQuery):
    """Continue to next user's Pokemon selection"""
    await callback_query.answer()
    
    if not callback_query.data:
        return
    
    # Extract trade_id from callback data
    trade_id = callback_query.data[len("continue_selection_"):]
    
    if trade_id and trade_id in active_trades:
        await show_pokemon_selection_phase(callback_query.bot, trade_id)

async def show_trade_confirmation(bot, trade_id: str):
    """Show trade confirmation with detailed Pokemon info"""
    if trade_id not in active_trades:
        return
    
    trade_request = active_trades[trade_id]
    
    # Get Pokemon details
    initiator_pokemon_list = await get_user_pokemon(trade_request.initiator_id)
    target_pokemon_list = await get_user_pokemon(trade_request.target_id)
    
    initiator_pokemon = initiator_pokemon_list[trade_request.initiator_pokemon_index] if trade_request.initiator_pokemon_index is not None and trade_request.initiator_pokemon_index < len(initiator_pokemon_list) else {}
    target_pokemon = target_pokemon_list[trade_request.target_pokemon_index] if trade_request.target_pokemon_index is not None and trade_request.target_pokemon_index < len(target_pokemon_list) else {}
    
    # Create user links
    initiator_link = create_user_link(trade_request.initiator_id, trade_request.initiator_name)
    target_link = create_user_link(trade_request.target_id, trade_request.target_name)
    
    # Get Pokemon display names with shiny sparkles
    initiator_pokemon_name = get_pokemon_display_name(initiator_pokemon)
    target_pokemon_name = get_pokemon_display_name(target_pokemon)
    
    # Create detailed confirmation message
    confirmation_text = f"<b><u>Trade Confirmation</u></b>\n\n"
    confirmation_text += f"<b>{trade_request.initiator_name}</b> will trade:\n"
    confirmation_text += f"<b>{initiator_pokemon_name}</b>\n"
    confirmation_text += f"   <u>Level:</u> {initiator_pokemon.get('level', 1)}\n"
    confirmation_text += f"   <u>Nature:</u> {initiator_pokemon.get('nature', 'Hardy')}\n"
    confirmation_text += f"   <u>IVs:</u> {get_pokemon_iv_display(initiator_pokemon)}\n"
    confirmation_text += f"   <u>EVs:</u> {get_pokemon_ev_display(initiator_pokemon)}\n\n"
    
    confirmation_text += f"<b>{trade_request.target_name}</b> will trade:\n"
    confirmation_text += f"<b>{target_pokemon_name}</b>\n"
    confirmation_text += f"   <u>Level:</u> {target_pokemon.get('level', 1)}\n"
    confirmation_text += f"   <u>Nature:</u> {target_pokemon.get('nature', 'Hardy')}\n"
    confirmation_text += f"   <u>IVs:</u> {get_pokemon_iv_display(target_pokemon)}\n"
    confirmation_text += f"   <u>EVs:</u> {get_pokemon_ev_display(target_pokemon)}\n\n"
    
    confirmation_text += f"<i>Both trainers must confirm to complete the trade.</i>\n\n"
    confirmation_text += f"{initiator_link} ↔ {target_link}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Confirm Trade", callback_data=f"confirm_trade_{trade_id}"),
            InlineKeyboardButton(text="Cancel Trade", callback_data=f"cancel_trade_{trade_id}")
        ]
    ])
    
    try:
        await bot.edit_message_text(
            chat_id=trade_request.chat_id,
            message_id=trade_request.message_id,
            text=confirmation_text,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    except Exception as e:
        print(f"Error updating confirmation message: {e}")

@router.callback_query(lambda c: c.data and c.data.startswith("confirm_trade_"))
async def handle_trade_confirmation(callback_query: types.CallbackQuery):
    """Handle trade confirmation"""
    await callback_query.answer()
    
    if not callback_query.data:
        return
    
    # Extract trade_id from callback data
    trade_id = callback_query.data[len("confirm_trade_"):]
    
    if not trade_id or trade_id not in active_trades:
        await callback_query.answer("No active trade found!", show_alert=True)
        return
    
    trade_request = active_trades[trade_id]
    
    # Check if user has permission to interact
    user_id = callback_query.from_user.id if callback_query.from_user else None
    if not user_id:
        return
    
    if user_id != trade_request.initiator_id and user_id != trade_request.target_id:
        await callback_query.answer("You are not part of this trade!", show_alert=True)
        return
    
    # Mark user as confirmed
    if user_id == trade_request.initiator_id:
        trade_request.initiator_confirmed = True
    else:
        trade_request.target_confirmed = True
    
    # Check if both users confirmed
    if trade_request.initiator_confirmed and trade_request.target_confirmed:
        await execute_trade(callback_query.bot, trade_id)
    else:
        # Create user links
        initiator_link = create_user_link(trade_request.initiator_id, trade_request.initiator_name)
        target_link = create_user_link(trade_request.target_id, trade_request.target_name)
        
        # Update message to show waiting status
        confirmation_text = f"<b><u>Trade Confirmation</u></b>\n\n"
        confirmation_text += f"<b>{trade_request.initiator_name}:</b> {'Confirmed' if trade_request.initiator_confirmed else '<i>Waiting</i>'}\n"
        confirmation_text += f"<b>{trade_request.target_name}:</b> {'Confirmed' if trade_request.target_confirmed else '<i>Waiting</i>'}\n\n"
        confirmation_text += f"<i>Waiting for both trainers to confirm...</i>\n\n"
        confirmation_text += f"{initiator_link} ↔ {target_link}"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Confirm Trade", callback_data=f"confirm_trade_{trade_id}"),
                InlineKeyboardButton(text="Cancel Trade", callback_data=f"cancel_trade_{trade_id}")
            ]
        ])
        
        try:
            if callback_query.message and hasattr(callback_query.message, 'edit_text'):
                await callback_query.message.edit_text(
                    text=confirmation_text,
                    reply_markup=keyboard,
                    parse_mode='HTML'
                )
        except Exception as e:
            print(f"Error updating confirmation status: {e}")

async def execute_trade(bot, trade_id: str):
    """Execute the trade between users"""
    if trade_id not in active_trades:
        return
    
    trade_request = active_trades[trade_id]
    
    try:
        # Get current Pokemon collections
        initiator_pokemon = await get_user_pokemon(trade_request.initiator_id)
        target_pokemon = await get_user_pokemon(trade_request.target_id)
        
        # Validate that Pokemon still exist and indices are valid
        if (trade_request.initiator_pokemon_index is None or 
            trade_request.initiator_pokemon_index >= len(initiator_pokemon) or
            trade_request.target_pokemon_index is None or 
            trade_request.target_pokemon_index >= len(target_pokemon)):
            
            error_text = f"<b><u>Trade Failed</u></b>\n\n"
            error_text += "One or both Pokemon are no longer available.\n"
            error_text += "The trade has been cancelled."
            
            try:
                await bot.edit_message_text(
                    chat_id=trade_request.chat_id,
                    message_id=trade_request.message_id,
                    text=error_text,
                    parse_mode='HTML'
                )
            except Exception as e:
                print(f"Error updating failed trade message: {e}")
            
            del active_trades[trade_id]
            return
        
        # Get the Pokemon data before removing
        initiator_pokemon_data = initiator_pokemon[trade_request.initiator_pokemon_index]
        target_pokemon_data = target_pokemon[trade_request.target_pokemon_index]
        
        # Remove Pokemon from original owners
        initiator_pokemon.pop(trade_request.initiator_pokemon_index)
        target_pokemon.pop(trade_request.target_pokemon_index)
        
        # Add Pokemon to new owners
        initiator_pokemon.append(target_pokemon_data)
        target_pokemon.append(initiator_pokemon_data)
        
        # Update database
        success1 = await update_user_pokemon_collection(trade_request.initiator_id, initiator_pokemon)
        success2 = await update_user_pokemon_collection(trade_request.target_id, target_pokemon)
        
        if not success1 or not success2:
            # Database update failed
            error_text = f"<b><u>Trade Failed</u></b>\n\n"
            error_text += "An error occurred while updating the database.\n"
            error_text += "Please try again later."
            
            try:
                await bot.edit_message_text(
                    chat_id=trade_request.chat_id,
                    message_id=trade_request.message_id,
                    text=error_text,
                    parse_mode='HTML'
                )
            except Exception as e:
                print(f"Error updating database error message: {e}")
            
            del active_trades[trade_id]
            return
        
        # Create user links
        initiator_link = create_user_link(trade_request.initiator_id, trade_request.initiator_name)
        target_link = create_user_link(trade_request.target_id, trade_request.target_name)
        
        # Get Pokemon display names with shiny sparkles
        initiator_pokemon_name = get_pokemon_display_name(initiator_pokemon_data)
        target_pokemon_name = get_pokemon_display_name(target_pokemon_data)
        
        # Success message
        success_text = f"<b><u>Trade Completed Successfully!</u></b>\n\n"
        success_text += f"<b>{trade_request.initiator_name}</b> received: {target_pokemon_name}\n"
        success_text += f"<b>{trade_request.target_name}</b> received: {initiator_pokemon_name}\n\n"
        success_text += f"<i>Both trainers are now happy with their new Pokemon!</i>\n\n"
        success_text += f"{initiator_link} ↔ {target_link}"
        
        # Update the trade message
        try:
            await bot.edit_message_text(
                chat_id=trade_request.chat_id,
                message_id=trade_request.message_id,
                text=success_text,
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"Error updating trade success message: {e}")
        
        # Clean up
        del active_trades[trade_id]
        
    except Exception as e:
        # Error handling
        print(f"Error executing trade: {e}")
        error_text = "An error occurred during the trade. Please try again."
        try:
            await bot.edit_message_text(
                chat_id=trade_request.chat_id,
                message_id=trade_request.message_id,
                text=error_text,
                parse_mode='HTML'
            )
        except Exception as inner_e:
            print(f"Error updating error message: {inner_e}")
        
        del active_trades[trade_id]

@router.message(Command("canceltrade"))
async def cancel_trade(message: types.Message):
    """Cancel a trade (command handler)"""
    if not message.from_user:
        await message.answer("Unable to identify user. Please try again.", parse_mode='HTML')
        return
    
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "User"
    
    # Find and cancel any active trades involving this user
    cancelled_trades = []
    for trade_id, trade_request in list(active_trades.items()):
        if trade_request.initiator_id == user_id or trade_request.target_id == user_id:
            cancelled_trades.append(trade_id)
            
            # Try to update the trade message
            try:
                initiator_link = create_user_link(trade_request.initiator_id, trade_request.initiator_name)
                target_link = create_user_link(trade_request.target_id, trade_request.target_name)
                
                cancel_text = f"<b><u>Trade Cancelled</u></b>\n\n"
                cancel_text += f"<b>{user_name}</b> cancelled the trade between <b>{trade_request.initiator_name}</b> and <b>{trade_request.target_name}</b>.\n\n"
                cancel_text += f"{initiator_link} ↔ {target_link}"
                
                if message.bot:
                    await message.bot.edit_message_text(
                        chat_id=trade_request.chat_id,
                        message_id=trade_request.message_id,
                        text=cancel_text,
                        parse_mode='HTML'
                    )
            except Exception as e:
                print(f"Error updating cancelled trade message: {e}")
            
            del active_trades[trade_id]
    
    if cancelled_trades:
        await message.answer(f"Cancelled {len(cancelled_trades)} active trade(s).", parse_mode='HTML')
    else:
        await message.answer("You don't have any active trades to cancel.", parse_mode='HTML')