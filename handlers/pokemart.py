from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import asyncio
from database import get_or_create_user, set_user_balance, get_user_inventory, update_user_inventory, update_user_pokeballs, update_user_fishing_rods, set_user_mega_bracelet, set_user_z_ring, get_user_tms, batch_tm_purchase_operations
from config import POKEBALLS, FISHING_RODS, BERRIES, VITAMINS, MISC_ITEMS
from pokemon_utils import pokemon_utils

router = Router()

@router.message(Command("pokemart"))
async def pokemart_command(message: types.Message):
    """Show Pokemart main page"""
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or ""
    user = await get_or_create_user(user_id, username, first_name)
    
    # Create keyboard with main options
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="PokeBalls", callback_data=f"pokemart_pokeballs_{user_id}"),
            InlineKeyboardButton(text="Fishing Rods", callback_data=f"pokemart_fishingrods_{user_id}")
        ],
        [
            InlineKeyboardButton(text="Training Items", callback_data=f"pokemart_training_{user_id}"),
            InlineKeyboardButton(text="Miscellaneous", callback_data=f"pokemart_misc_{user_id}")
        ],
        [
            InlineKeyboardButton(text="TM Shop", callback_data=f"pokemart_tms_{user_id}")
        ]
    ])
    
    text = f"""🏪 <b>Welcome to PokeMart!</b>

What would you like to buy today?

💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"""
    
    await message.reply(text, reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(lambda c: c.data.startswith("pokemart_"))
async def pokemart_callback(callback_query: CallbackQuery):
    """Handle all Pokemart interactions"""
    user_id = callback_query.from_user.id
    if not callback_query.data:
        return
    
    data_parts = callback_query.data.split("_")
    
    # Check if user is authorized to interact with this message
    if len(data_parts) > 2:
        try:
            # For pagination callbacks like "pokemart_tms_123456_1", user_id is at position -2
            # For regular callbacks like "pokemart_pokeballs_123456", user_id is at position -1
            if data_parts[1] == "tms" and len(data_parts) == 4:
                # This is a TM pagination callback: pokemart_tms_user_id_page
                callback_user_id = int(data_parts[2])
            elif data_parts[1] == "tmtype" and len(data_parts) == 5:
                # This is a TM type pagination callback: pokemart_tmtype_type_user_id_page
                callback_user_id = int(data_parts[3])
            else:
                # Regular callback: get the last part as user_id
                callback_user_id = int(data_parts[-1])
            
            if callback_user_id != user_id:
                await callback_query.answer("This is not your PokeMart!", show_alert=True)
                return
        except (ValueError, IndexError):
            # If we can't parse user_id, check if it's a main callback
            if data_parts[1] not in ["main", "pokeballs", "fishingrods", "tms"]:
                await callback_query.answer("This is not your PokeMart!", show_alert=True)
                return
    
    username = callback_query.from_user.username or ""
    first_name = callback_query.from_user.first_name or ""
    user = await get_or_create_user(user_id, username, first_name)
    
    if data_parts[1] == "pokeballs":
        # Show pokeball selection page
        keyboard_rows = []
        
        # Create buttons for each pokeball type (4 per row)
        for i in range(0, len(POKEBALLS), 4):
            row = []
            for j in range(4):
                if i + j < len(POKEBALLS):
                    pokeball = POKEBALLS[i + j]
                    row.append(InlineKeyboardButton(
                        text=f"{pokeball['name']}", 
                        callback_data=f"pokemart_select_{pokeball['name']}_{user_id}"
                    ))
            keyboard_rows.append(row)
        
        # Add back button
        keyboard_rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_main_{user_id}")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        text = f"""<b>Which Pokeball would you like to buy?</b>

"""
        
        # Add pokeball info
        for pokeball in POKEBALLS:
            text += f"<b>{pokeball['name']} Ball:</b> {pokeball['rate']} PokeDollars 💵\n"
        
        text += f"\n💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "fishingrods":
    # Show fishing rod selection page
        keyboard_rows = []
    
    # Create buttons for each fishing rod type (3 per row)
        for i in range(0, len(FISHING_RODS), 3):
            row = []
            for j in range(3):
                if i + j < len(FISHING_RODS):
                    rod = FISHING_RODS[i + j]
                    # Check if user already has this rod
                    user_rods = user.get('fishing_rods', {})
                    if rod['name'] in user_rods:
                    # User already has this rod, show as owned
                        row.append(InlineKeyboardButton(
                        text=f"✅ {rod['name']} ", 
                        callback_data=f"pokemart_rod_owned_{user_id}"
                    ))
                    else:
                    # User doesn't have this rod, allow purchase
                        row.append(InlineKeyboardButton(
                        text=f"{rod['name']}", 
                        callback_data=f"pokemart_buyrod_{rod['name']}_{user_id}"
                    ))
            keyboard_rows.append(row)
    
    # Add back button
        keyboard_rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_main_{user_id}")])
    
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
        text = f"""<b>Which Fishing Rod would you like to buy?</b>

"""
    
    # Add fishing rod info
        for rod in FISHING_RODS:
            user_rods = user.get('fishing_rods', {})
            status = "Owned" if rod['name'] in user_rods else f"{rod['rate']} PokeDollars 💵"
            text += f"<b>{rod['name']}:</b> {status}\n"
    
        text += f"\n💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"
    
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

# Updated purchase confirmation text (remove fishing emoji)

    elif data_parts[1] == "buyrod":
    # Show purchase confirmation for fishing rod
        rod_name = data_parts[2]
    
        rod_info = next((r for r in FISHING_RODS if r['name'] == rod_name), None)
        if not rod_info:
            await callback_query.answer("Invalid fishing rod selection!", show_alert=True)
            return
    
    # Check if user already has this rod
        user_rods = user.get('fishing_rods', {})
        if rod_name in user_rods:
            await callback_query.answer("You already own this fishing rod!", show_alert=True)
            return
    
        total_cost = rod_info['rate']
    
    # Check if user has enough money
        if user['pokedollars'] < total_cost:
            await callback_query.answer("You don't have sufficient PokeDollars!", show_alert=True)
            return
    
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Yes", callback_data=f"pokemart_confirmrod_{rod_name}_{user_id}"),
            InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_fishingrods_{user_id}")
        ]
    ])
    
        text = f"""<b>🔴 Purchase Confirmation</b>

<b>{rod_name}: </b>
{rod_info['description']}

💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵
💰 <b>Total Cost:</b> {total_cost} 💵

Are you sure you want to buy this fishing rod?"""
    
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "confirmrod":
        # Process the fishing rod purchase
        rod_name = data_parts[2]
        
        rod_info = next((r for r in FISHING_RODS if r['name'] == rod_name), None)
        if not rod_info:
            await callback_query.answer("Invalid fishing rod selection!", show_alert=True)
            return
        
        # Check if user already has this rod
        user_rods = user.get('fishing_rods', {})
        if rod_name in user_rods:
            await callback_query.answer("You already own this fishing rod!", show_alert=True)
            return
        
        total_cost = rod_info['rate']
        
        # Double-check user has enough money
        if user['pokedollars'] < total_cost:
            await callback_query.answer("You don't have sufficient PokeDollars!", show_alert=True)
            return
        
        # Process the purchase
        new_pokedollars = user['pokedollars'] - total_cost
        
        # Update fishing rod inventory
        current_rods = user.get('fishing_rods', {})
        current_rods[rod_name] = True  # Just mark as owned
        
        # Execute balance update and fishing rod update concurrently
        await asyncio.gather(
            set_user_balance(user_id, new_pokedollars),
            update_user_fishing_rods(user_id, current_rods)
        )
        
        # Show success message and return to main
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏪 Continue Shopping", callback_data=f"pokemart_main_{user_id}")]
        ])
        
        text = f"""✅ <b>Purchase Successful!</b>

You bought <b>{rod_name}</b> for <b>{total_cost} PokeDollars</b> 💵

💰 <b>Remaining PokeDollars:</b> {new_pokedollars} 💵


Thank you for shopping at PokeMart! 🏪"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

    elif data_parts[1] == "select":
        # Show quantity selection for specific pokeball
        pokeball_name = data_parts[2]
        pokeball_info = next((p for p in POKEBALLS if p['name'] == pokeball_name), None)
        
        if not pokeball_info:
            await callback_query.answer("Invalid pokeball selection!", show_alert=True)
            return
        
        # Create quantity buttons (1-25)
        keyboard_rows = []
        for i in range(1, 26, 5):  # 5 buttons per row
            row = []
            for j in range(5):
                if i + j <= 25:
                    row.append(InlineKeyboardButton(
                        text=str(i + j), 
                        callback_data=f"pokemart_qty_{pokeball_name}_{i + j}_{user_id}"
                    ))
            keyboard_rows.append(row)
        
        # Add navigation buttons
        keyboard_rows.append([
            InlineKeyboardButton(text="Next (26-50)", callback_data=f"pokemart_qty2_{pokeball_name}_{user_id}")
        ])
        keyboard_rows.append([
            InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_pokeballs_{user_id}")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        text = f"""<b>How many {pokeball_name} Balls do you want to buy?</b>

<b>Price:</b> {pokeball_info['rate']} PokeDollars 💵 per ball
💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "qty2":
        # Show quantity selection 26-50
        pokeball_name = data_parts[2]
        pokeball_info = next((p for p in POKEBALLS if p['name'] == pokeball_name), None)
        
        keyboard_rows = []
        for i in range(26, 51, 5):  # 5 buttons per row
            row = []
            for j in range(5):
                if i + j <= 50:
                    row.append(InlineKeyboardButton(
                        text=str(i + j), 
                        callback_data=f"pokemart_qty_{pokeball_name}_{i + j}_{user_id}"
                    ))
            keyboard_rows.append(row)
        
        # Add navigation buttons
        keyboard_rows.append([
            InlineKeyboardButton(text="Previous (1-25)", callback_data=f"pokemart_select_{pokeball_name}_{user_id}"),
            InlineKeyboardButton(text="Next (51-75)", callback_data=f"pokemart_qty3_{pokeball_name}_{user_id}")
        ])
        keyboard_rows.append([
            InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_pokeballs_{user_id}")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        text = f"""<b>How many {pokeball_name} Balls do you want to buy?</b>

<b>Price:</b> {pokeball_info['rate']} PokeDollars 💵 per ball
💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "qty3":
        # Show quantity selection 51-75
        pokeball_name = data_parts[2]
        pokeball_info = next((p for p in POKEBALLS if p['name'] == pokeball_name), None)
        
        keyboard_rows = []
        for i in range(51, 76, 5):  # 5 buttons per row
            row = []
            for j in range(5):
                if i + j <= 75:
                    row.append(InlineKeyboardButton(
                        text=str(i + j), 
                        callback_data=f"pokemart_qty_{pokeball_name}_{i + j}_{user_id}"
                    ))
            keyboard_rows.append(row)
        
        # Add navigation buttons
        keyboard_rows.append([
            InlineKeyboardButton(text="Previous (26-50)", callback_data=f"pokemart_qty2_{pokeball_name}_{user_id}"),
            InlineKeyboardButton(text="Next (76-100)", callback_data=f"pokemart_qty4_{pokeball_name}_{user_id}")
        ])
        keyboard_rows.append([
            InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_pokeballs_{user_id}")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        text = f"""<b>How many {pokeball_name} Balls do you want to buy?</b>

<b>Price:</b> {pokeball_info['rate']} PokeDollars 💵 per ball
💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "qty4":
        # Show quantity selection 76-100
        pokeball_name = data_parts[2]
        pokeball_info = next((p for p in POKEBALLS if p['name'] == pokeball_name), None)
        
        keyboard_rows = []
        for i in range(76, 101, 5):  # 5 buttons per row
            row = []
            for j in range(5):
                if i + j <= 100:
                    row.append(InlineKeyboardButton(
                        text=str(i + j), 
                        callback_data=f"pokemart_qty_{pokeball_name}_{i + j}_{user_id}"
                    ))
            keyboard_rows.append(row)
        
        # Add navigation buttons
        keyboard_rows.append([
            InlineKeyboardButton(text="Previous (51-75)", callback_data=f"pokemart_qty3_{pokeball_name}_{user_id}")
        ])
        keyboard_rows.append([
            InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_pokeballs_{user_id}")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        text = f"""<b>How many {pokeball_name} Balls do you want to buy?</b>

<b>Price:</b> {pokeball_info['rate']} PokeDollars 💵 per ball
💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "qty":
        # Show purchase confirmation
        pokeball_name = data_parts[2]
        quantity = int(data_parts[3])
        
        pokeball_info = next((p for p in POKEBALLS if p['name'] == pokeball_name), None)
        if not pokeball_info:
            await callback_query.answer("Invalid pokeball selection!", show_alert=True)
            return
        
        total_cost = pokeball_info['rate'] * quantity
        
        # Check if user has enough money
        if user['pokedollars'] < total_cost:
            await callback_query.answer("You don't have sufficient PokeDollars!", show_alert=True)
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Yes", callback_data=f"pokemart_buy_{pokeball_name}_{quantity}_{user_id}"),
                InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_select_{pokeball_name}_{user_id}")
            ]
        ])
        
        text = f"""🔴 <b>Purchase Confirmation</b>

<b>{pokeball_name} Ball x {quantity}</b>

💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵
💰 <b>Total Cost:</b> {total_cost} 💵 ({pokeball_info['rate']} × {quantity})

Are you sure you want to buy this?"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "buy":
        # Process the purchase
        pokeball_name = data_parts[2]
        quantity = int(data_parts[3])
        
        pokeball_info = next((p for p in POKEBALLS if p['name'] == pokeball_name), None)
        if not pokeball_info:
            await callback_query.answer("Invalid pokeball selection!", show_alert=True)
            return
        
        total_cost = pokeball_info['rate'] * quantity
        
        # Double-check user has enough money
        if user['pokedollars'] < total_cost:
            await callback_query.answer("You don't have sufficient PokeDollars!", show_alert=True)
            return
        
        # Process the purchase
        new_pokedollars = user['pokedollars'] - total_cost
        
        # Update pokeball inventory
        current_pokeballs = user['pokeballs'].copy()
        current_pokeballs[pokeball_name] = current_pokeballs.get(pokeball_name, 0) + quantity
        
        # Execute balance update and pokeball update concurrently
        await asyncio.gather(
            set_user_balance(user_id, new_pokedollars),
            update_user_pokeballs(user_id, current_pokeballs)
        )
        
        new_pokeball_count = current_pokeballs[pokeball_name]
        
        # Show success message and return to main
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏪 Continue Shopping", callback_data=f"pokemart_main_{user_id}")]
        ])
        
        text = f"""✅ <b>Purchase Successful!</b>

You bought <b>{quantity} {pokeball_name} Ball(s)</b> for <b>{total_cost} PokeDollars</b> 💵

💰 <b>Remaining PokeDollars:</b> {new_pokedollars} 💵
<b>Total {pokeball_name} Balls:</b> {new_pokeball_count}

Thank you for shopping at PokeMart! 🏪"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "training":
        # Show training items selection page
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Berries", callback_data=f"pokemart_berries_{user_id}"),
                InlineKeyboardButton(text="Vitamins", callback_data=f"pokemart_vitamins_{user_id}")
            ],
            [InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_main_{user_id}")]
        ])
        
        text = f"""<b>Training Items</b>

<b>Berries:</b> Decrease EVs of a particular stat by 5
<b>Vitamins:</b> Increase EVs of a particular stat by 5

💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "berries":
        # Show berries selection page
        keyboard_rows = []
        
        # Create buttons for each berry type (3 per row)
        for i in range(0, len(BERRIES), 3):
            row = []
            for j in range(3):
                if i + j < len(BERRIES):
                    berry = BERRIES[i + j]
                    row.append(InlineKeyboardButton(
                        text=f"{berry['name']}", 
                        callback_data=f"pokemart_selectberry_{berry['name']}_{user_id}"
                    ))
            keyboard_rows.append(row)
        
        # Add back button
        keyboard_rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_training_{user_id}")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        text = f"""<b>Which Berry would you like to buy?</b>

"""
        
        # Add berry info
        for berry in BERRIES:
            text += f"<b>{berry['name']}:</b> {berry['price']} PokeDollars 💵 - {berry['effect']}\n"
        
        text += f"\n💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "vitamins":
        # Show vitamins selection page
        keyboard_rows = []
        
        # Create buttons for each vitamin type (3 per row)
        for i in range(0, len(VITAMINS), 3):
            row = []
            for j in range(3):
                if i + j < len(VITAMINS):
                    vitamin = VITAMINS[i + j]
                    row.append(InlineKeyboardButton(
                        text=f"{vitamin['name']}", 
                        callback_data=f"pokemart_selectvitamin_{vitamin['name']}_{user_id}"
                    ))
            keyboard_rows.append(row)
        
        # Add back button
        keyboard_rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_training_{user_id}")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        text = f"""<b>Which Vitamin would you like to buy?</b>

"""
        
        # Add vitamin info
        for vitamin in VITAMINS:
            text += f"<b>{vitamin['name']}:</b> {vitamin['price']} PokeDollars 💵 - {vitamin['effect']}\n"
        
        text += f"\n💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "selectberry":
        # Show quantity selection for specific berry
        berry_name = data_parts[2]
        berry_info = next((b for b in BERRIES if b['name'] == berry_name), None)
        
        if not berry_info:
            await callback_query.answer("Invalid berry selection!", show_alert=True)
            return
        
        # Create quantity buttons (1-25)
        keyboard_rows = []
        for i in range(1, 26, 5):  # 5 buttons per row
            row = []
            for j in range(5):
                if i + j <= 25:
                    row.append(InlineKeyboardButton(
                        text=str(i + j), 
                        callback_data=f"pokemart_qtyberry_{berry_name}_{i + j}_{user_id}"
                    ))
            keyboard_rows.append(row)
        
        # Add navigation buttons
        keyboard_rows.append([
            InlineKeyboardButton(text="Next (26-50)", callback_data=f"pokemart_qtyberry2_{berry_name}_{user_id}")
        ])
        keyboard_rows.append([
            InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_berries_{user_id}")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        text = f"""<b>How many {berry_name} do you want to buy?</b>

<b>Price:</b> {berry_info['price']} PokeDollars 💵 per berry
💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "selectvitamin":
        # Show quantity selection for specific vitamin
        vitamin_name = data_parts[2]
        vitamin_info = next((v for v in VITAMINS if v['name'] == vitamin_name), None)
        
        if not vitamin_info:
            await callback_query.answer("Invalid vitamin selection!", show_alert=True)
            return
        
        # Create quantity buttons (1-25)
        keyboard_rows = []
        for i in range(1, 26, 5):  # 5 buttons per row
            row = []
            for j in range(5):
                if i + j <= 25:
                    row.append(InlineKeyboardButton(
                        text=str(i + j), 
                        callback_data=f"pokemart_qtyvitamin_{vitamin_name}_{i + j}_{user_id}"
                    ))
            keyboard_rows.append(row)
        
        # Add navigation buttons
        keyboard_rows.append([
            InlineKeyboardButton(text="Next (26-50)", callback_data=f"pokemart_qtyvitamin2_{vitamin_name}_{user_id}")
        ])
        keyboard_rows.append([
            InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_vitamins_{user_id}")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        text = f"""<b>How many {vitamin_name} do you want to buy?</b>

<b>Price:</b> {vitamin_info['price']} PokeDollars 💵 per vitamin
💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "qtyberry2":
        # Show quantity selection 26-50 for berries
        berry_name = data_parts[2]
        berry_info = next((b for b in BERRIES if b['name'] == berry_name), None)
        
        keyboard_rows = []
        for i in range(26, 51, 5):  # 5 buttons per row
            row = []
            for j in range(5):
                if i + j <= 50:
                    row.append(InlineKeyboardButton(
                        text=str(i + j), 
                        callback_data=f"pokemart_qtyberry_{berry_name}_{i + j}_{user_id}"
                    ))
            keyboard_rows.append(row)
        
        # Add navigation buttons
        keyboard_rows.append([
            InlineKeyboardButton(text="Previous (1-25)", callback_data=f"pokemart_selectberry_{berry_name}_{user_id}"),
            InlineKeyboardButton(text="Next (51-75)", callback_data=f"pokemart_qtyberry3_{berry_name}_{user_id}")
        ])
        keyboard_rows.append([
            InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_berries_{user_id}")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        text = f"""<b>How many {berry_name} do you want to buy?</b>

<b>Price:</b> {berry_info['price']} PokeDollars 💵 per berry
💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "qtyberry3":
        # Show quantity selection 51-75 for berries
        berry_name = data_parts[2]
        berry_info = next((b for b in BERRIES if b['name'] == berry_name), None)
        
        keyboard_rows = []
        for i in range(51, 76, 5):  # 5 buttons per row
            row = []
            for j in range(5):
                if i + j <= 75:
                    row.append(InlineKeyboardButton(
                        text=str(i + j), 
                        callback_data=f"pokemart_qtyberry_{berry_name}_{i + j}_{user_id}"
                    ))
            keyboard_rows.append(row)
        
        # Add navigation buttons
        keyboard_rows.append([
            InlineKeyboardButton(text="Previous (26-50)", callback_data=f"pokemart_qtyberry2_{berry_name}_{user_id}"),
            InlineKeyboardButton(text="Next (76-100)", callback_data=f"pokemart_qtyberry4_{berry_name}_{user_id}")
        ])
        keyboard_rows.append([
            InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_berries_{user_id}")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        text = f"""<b>How many {berry_name} do you want to buy?</b>

<b>Price:</b> {berry_info['price']} PokeDollars 💵 per berry
💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "qtyberry4":
        # Show quantity selection 76-100 for berries
        berry_name = data_parts[2]
        berry_info = next((b for b in BERRIES if b['name'] == berry_name), None)
        
        keyboard_rows = []
        for i in range(76, 101, 5):  # 5 buttons per row
            row = []
            for j in range(5):
                if i + j <= 100:
                    row.append(InlineKeyboardButton(
                        text=str(i + j), 
                        callback_data=f"pokemart_qtyberry_{berry_name}_{i + j}_{user_id}"
                    ))
            keyboard_rows.append(row)
        
        # Add navigation buttons
        keyboard_rows.append([
            InlineKeyboardButton(text="Previous (51-75)", callback_data=f"pokemart_qtyberry3_{berry_name}_{user_id}")
        ])
        keyboard_rows.append([
            InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_berries_{user_id}")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        text = f"""<b>How many {berry_name} do you want to buy?</b>

<b>Price:</b> {berry_info['price']} PokeDollars 💵 per berry
💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "qtyvitamin2":
        # Show quantity selection 26-50 for vitamins
        vitamin_name = data_parts[2]
        vitamin_info = next((v for v in VITAMINS if v['name'] == vitamin_name), None)
        
        keyboard_rows = []
        for i in range(26, 51, 5):  # 5 buttons per row
            row = []
            for j in range(5):
                if i + j <= 50:
                    row.append(InlineKeyboardButton(
                        text=str(i + j), 
                        callback_data=f"pokemart_qtyvitamin_{vitamin_name}_{i + j}_{user_id}"
                    ))
            keyboard_rows.append(row)
        
        # Add navigation buttons
        keyboard_rows.append([
            InlineKeyboardButton(text="Previous (1-25)", callback_data=f"pokemart_selectvitamin_{vitamin_name}_{user_id}"),
            InlineKeyboardButton(text="Next (51-75)", callback_data=f"pokemart_qtyvitamin3_{vitamin_name}_{user_id}")
        ])
        keyboard_rows.append([
            InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_vitamins_{user_id}")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        text = f"""<b>How many {vitamin_name} do you want to buy?</b>

<b>Price:</b> {vitamin_info['price']} PokeDollars 💵 per vitamin
💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "qtyvitamin3":
        # Show quantity selection 51-75 for vitamins
        vitamin_name = data_parts[2]
        vitamin_info = next((v for v in VITAMINS if v['name'] == vitamin_name), None)
        
        keyboard_rows = []
        for i in range(51, 76, 5):  # 5 buttons per row
            row = []
            for j in range(5):
                if i + j <= 75:
                    row.append(InlineKeyboardButton(
                        text=str(i + j), 
                        callback_data=f"pokemart_qtyvitamin_{vitamin_name}_{i + j}_{user_id}"
                    ))
            keyboard_rows.append(row)
        
        # Add navigation buttons
        keyboard_rows.append([
            InlineKeyboardButton(text="Previous (26-50)", callback_data=f"pokemart_qtyvitamin2_{vitamin_name}_{user_id}"),
            InlineKeyboardButton(text="Next (76-100)", callback_data=f"pokemart_qtyvitamin4_{vitamin_name}_{user_id}")
        ])
        keyboard_rows.append([
            InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_vitamins_{user_id}")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        text = f"""<b>How many {vitamin_name} do you want to buy?</b>

<b>Price:</b> {vitamin_info['price']} PokeDollars 💵 per vitamin
💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "qtyvitamin4":
        # Show quantity selection 76-100 for vitamins
        vitamin_name = data_parts[2]
        vitamin_info = next((v for v in VITAMINS if v['name'] == vitamin_name), None)
        
        keyboard_rows = []
        for i in range(76, 101, 5):  # 5 buttons per row
            row = []
            for j in range(5):
                if i + j <= 100:
                    row.append(InlineKeyboardButton(
                        text=str(i + j), 
                        callback_data=f"pokemart_qtyvitamin_{vitamin_name}_{i + j}_{user_id}"
                    ))
            keyboard_rows.append(row)
        
        # Add navigation buttons
        keyboard_rows.append([
            InlineKeyboardButton(text="Previous (51-75)", callback_data=f"pokemart_qtyvitamin3_{vitamin_name}_{user_id}")
        ])
        keyboard_rows.append([
            InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_vitamins_{user_id}")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        text = f"""<b>How many {vitamin_name} do you want to buy?</b>

<b>Price:</b> {vitamin_info['price']} PokeDollars 💵 per vitamin
💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "qtyberry":
        # Show purchase confirmation for berries
        berry_name = data_parts[2]
        quantity = int(data_parts[3])
        
        berry_info = next((b for b in BERRIES if b['name'] == berry_name), None)
        if not berry_info:
            await callback_query.answer("Invalid berry selection!", show_alert=True)
            return
        
        total_cost = berry_info['price'] * quantity
        
        # Check if user has enough money
        if user['pokedollars'] < total_cost:
            await callback_query.answer("You don't have sufficient PokeDollars!", show_alert=True)
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Yes", callback_data=f"pokemart_buyberry_{berry_name}_{quantity}_{user_id}"),
                InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_selectberry_{berry_name}_{user_id}")
            ]
        ])
        
        text = f"""🔴 <b>Purchase Confirmation</b>

<b>{berry_name} x {quantity}</b>
<b>Effect:</b> {berry_info['effect']}

💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵
💰 <b>Total Cost:</b> {total_cost} 💵 ({berry_info['price']} × {quantity})

Are you sure you want to buy this?"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "qtyvitamin":
        # Show purchase confirmation for vitamins
        vitamin_name = data_parts[2]
        quantity = int(data_parts[3])
        
        vitamin_info = next((v for v in VITAMINS if v['name'] == vitamin_name), None)
        if not vitamin_info:
            await callback_query.answer("Invalid vitamin selection!", show_alert=True)
            return
        
        total_cost = vitamin_info['price'] * quantity
        
        # Check if user has enough money
        if user['pokedollars'] < total_cost:
            await callback_query.answer("You don't have sufficient PokeDollars!", show_alert=True)
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Yes", callback_data=f"pokemart_buyvitamin_{vitamin_name}_{quantity}_{user_id}"),
                InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_selectvitamin_{vitamin_name}_{user_id}")
            ]
        ])
        
        text = f"""🔴 <b>Purchase Confirmation</b>

<b>{vitamin_name} x {quantity}</b>
<b>Effect:</b> {vitamin_info['effect']}

💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵
💰 <b>Total Cost:</b> {total_cost} 💵 ({vitamin_info['price']} × {quantity})

Are you sure you want to buy this?"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "buyberry":
        # Process the berry purchase
        berry_name = data_parts[2]
        quantity = int(data_parts[3])
        
        berry_info = next((b for b in BERRIES if b['name'] == berry_name), None)
        if not berry_info:
            await callback_query.answer("Invalid berry selection!", show_alert=True)
            return
        
        total_cost = berry_info['price'] * quantity
        
        # Double-check user has enough money
        if user['pokedollars'] < total_cost:
            await callback_query.answer("You don't have sufficient PokeDollars!", show_alert=True)
            return
        
        # Process the purchase
        new_pokedollars = user['pokedollars'] - total_cost
        
        # Get inventory and update balance concurrently
        inventory = await get_user_inventory(user_id)
        inventory[berry_name] = inventory.get(berry_name, 0) + quantity
        
        # Execute balance update and inventory update concurrently
        await asyncio.gather(
            set_user_balance(user_id, new_pokedollars),
            update_user_inventory(user_id, inventory)
        )
        
        new_berry_count = inventory[berry_name]
        
        # Show success message and return to main
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏪 Continue Shopping", callback_data=f"pokemart_main_{user_id}")]
        ])
        
        text = f"""✅ <b>Purchase Successful!</b>

You bought <b>{quantity} {berry_name}</b> for <b>{total_cost} PokeDollars</b> 💵

💰 <b>Remaining PokeDollars:</b> {new_pokedollars} 💵
<b>Total {berry_name}:</b> {new_berry_count}

Thank you for shopping at PokeMart! 🏪"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "buyvitamin":
        # Process the vitamin purchase
        vitamin_name = data_parts[2]
        quantity = int(data_parts[3])
        
        vitamin_info = next((v for v in VITAMINS if v['name'] == vitamin_name), None)
        if not vitamin_info:
            await callback_query.answer("Invalid vitamin selection!", show_alert=True)
            return
        
        total_cost = vitamin_info['price'] * quantity
        
        # Double-check user has enough money
        if user['pokedollars'] < total_cost:
            await callback_query.answer("You don't have sufficient PokeDollars!", show_alert=True)
            return
        
        # Process the purchase
        new_pokedollars = user['pokedollars'] - total_cost
        
        # Get inventory and update balance concurrently
        inventory = await get_user_inventory(user_id)
        inventory[vitamin_name] = inventory.get(vitamin_name, 0) + quantity
        
        # Execute balance update and inventory update concurrently
        await asyncio.gather(
            set_user_balance(user_id, new_pokedollars),
            update_user_inventory(user_id, inventory)
        )
        
        new_vitamin_count = inventory[vitamin_name]
        
        # Show success message and return to main
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏪 Continue Shopping", callback_data=f"pokemart_main_{user_id}")]
        ])
        
        text = f"""✅ <b>Purchase Successful!</b>

You bought <b>{quantity} {vitamin_name}</b> for <b>{total_cost} PokeDollars</b> 💵

💰 <b>Remaining PokeDollars:</b> {new_pokedollars} 💵
<b>Total {vitamin_name}:</b> {new_vitamin_count}

Thank you for shopping at PokeMart! 🏪"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "misc":
        # Show miscellaneous items selection page
        keyboard_rows = []
        for i in range(0, len(MISC_ITEMS), 2):
            row = []
            for j in range(2):
                if i + j < len(MISC_ITEMS):
                    item = MISC_ITEMS[i + j]
                    row.append(InlineKeyboardButton(
                        text=f"{item['emoji']} {item['name'].replace('-', ' ').title()}",
                        callback_data=f"pokemart_selectmisc_{item['name']}_{user_id}"
                    ))
            keyboard_rows.append(row)
        keyboard_rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_main_{user_id}")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        text = f"<b>Miscellaneous Items</b>\n\n"
        for item in MISC_ITEMS:
            text += f"{item['emoji']} <b>{item['name'].replace('-', ' ').title()}:</b> {item['price']} PokeDollars 💵 - {item['effect']}\n"
        text += f"\n💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    elif data_parts[1] == "selectmisc":
        # Show quantity selection for specific misc item
        item_name = data_parts[2]
        item_info = next((m for m in MISC_ITEMS if m['name'] == item_name), None)
        if not item_info:
            await callback_query.answer("Invalid item selection!", show_alert=True)
            return
        # Block Mega Bracelet if already owned
        if item_name == "mega-bracelet" and user.get("has_mega_bracelet", False):
            await callback_query.answer("You already own a Mega Bracelet!", show_alert=True)
            return
        
        # Block Z-Ring if already owned
        if item_name == "z-ring" and user.get("has_z_ring", False):
            await callback_query.answer("You already own a Z-Ring!", show_alert=True)
            return
            
        keyboard_rows = []
        # Only allow quantity 1 for Mega Bracelet and Z-Ring
        max_qty = 1 if item_name in ["mega-bracelet", "z-ring"] else 25
        for i in range(1, max_qty + 1, 5):
            row = []
            for j in range(5):
                if i + j <= max_qty:
                    row.append(InlineKeyboardButton(
                        text=str(i + j),
                        callback_data=f"pokemart_qtymisc_{item_name}_{i + j}_{user_id}"
                    ))
            keyboard_rows.append(row)
        if item_name not in ["mega-bracelet", "z-ring"]:
            keyboard_rows.append([
                InlineKeyboardButton(text="Next (26-50)", callback_data=f"pokemart_qtymisc2_{item_name}_{user_id}")
            ])
        keyboard_rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_misc_{user_id}")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        text = f"<b>How many {item_info['name'].replace('-', ' ').title()} do you want to buy?</b>\n\n<b>Price:</b> {item_info['price']} PokeDollars 💵 per item\n💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    elif data_parts[1] == "qtymisc2":
        # Show quantity selection 26-50 for misc item
        item_name = data_parts[2]
        item_info = next((m for m in MISC_ITEMS if m['name'] == item_name), None)
        keyboard_rows = []
        for i in range(26, 51, 5):
            row = []
            for j in range(5):
                if i + j <= 50:
                    row.append(InlineKeyboardButton(
                        text=str(i + j),
                        callback_data=f"pokemart_qtymisc_{item_name}_{i + j}_{user_id}"
                    ))
            keyboard_rows.append(row)
        keyboard_rows.append([
            InlineKeyboardButton(text="Previous (1-25)", callback_data=f"pokemart_selectmisc_{item_name}_{user_id}"),
            InlineKeyboardButton(text="Next (51-75)", callback_data=f"pokemart_qtymisc3_{item_name}_{user_id}")
        ])
        keyboard_rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_misc_{user_id}")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        text = f"<b>How many {item_info['name'].replace('-', ' ').title()} do you want to buy?</b>\n\n<b>Price:</b> {item_info['price']} PokeDollars 💵 per item\n💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    elif data_parts[1] == "qtymisc3":
        # Show quantity selection 51-75 for misc item
        item_name = data_parts[2]
        item_info = next((m for m in MISC_ITEMS if m['name'] == item_name), None)
        keyboard_rows = []
        for i in range(51, 76, 5):
            row = []
            for j in range(5):
                if i + j <= 75:
                    row.append(InlineKeyboardButton(
                        text=str(i + j),
                        callback_data=f"pokemart_qtymisc_{item_name}_{i + j}_{user_id}"
                    ))
            keyboard_rows.append(row)
        keyboard_rows.append([
            InlineKeyboardButton(text="Previous (26-50)", callback_data=f"pokemart_qtymisc2_{item_name}_{user_id}"),
            InlineKeyboardButton(text="Next (76-100)", callback_data=f"pokemart_qtymisc4_{item_name}_{user_id}")
        ])
        keyboard_rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_misc_{user_id}")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        text = f"<b>How many {item_info['name'].replace('-', ' ').title()} do you want to buy?</b>\n\n<b>Price:</b> {item_info['price']} PokeDollars 💵 per item\n💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    elif data_parts[1] == "qtymisc4":
        # Show quantity selection 76-100 for misc item
        item_name = data_parts[2]
        item_info = next((m for m in MISC_ITEMS if m['name'] == item_name), None)
        keyboard_rows = []
        for i in range(76, 101, 5):
            row = []
            for j in range(5):
                if i + j <= 100:
                    row.append(InlineKeyboardButton(
                        text=str(i + j),
                        callback_data=f"pokemart_qtymisc_{item_name}_{i + j}_{user_id}"
                    ))
            keyboard_rows.append(row)
        keyboard_rows.append([
            InlineKeyboardButton(text="Previous (51-75)", callback_data=f"pokemart_qtymisc3_{item_name}_{user_id}")
        ])
        keyboard_rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_misc_{user_id}")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        text = f"<b>How many {item_info['name'].replace('-', ' ').title()} do you want to buy?</b>\n\n<b>Price:</b> {item_info['price']} PokeDollars 💵 per item\n💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    elif data_parts[1] == "qtymisc":
        # Show purchase confirmation for misc item
        item_name = data_parts[2]
        quantity = int(data_parts[3])
        item_info = next((m for m in MISC_ITEMS if m['name'] == item_name), None)
        if not item_info:
            await callback_query.answer("Invalid item selection!", show_alert=True)
            return
        # Block Mega Bracelet if already owned
        if item_name == "mega-bracelet" and user.get("has_mega_bracelet", False):
            await callback_query.answer("You already own a Mega Bracelet!", show_alert=True)
            return
        
        # Block Z-Ring if already owned
        if item_name == "z-ring" and user.get("has_z_ring", False):
            await callback_query.answer("You already own a Z-Ring!", show_alert=True)
            return
            
        # Always set quantity to 1 for Mega Bracelet and Z-Ring
        if item_name in ["mega-bracelet", "z-ring"]:
            quantity = 1
        total_cost = item_info['price'] * quantity
        if user['pokedollars'] < total_cost:
            await callback_query.answer("You don't have sufficient PokeDollars!", show_alert=True)
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Yes", callback_data=f"pokemart_buymisc_{item_name}_{quantity}_{user_id}"),
                InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_selectmisc_{item_name}_{user_id}")
            ]
        ])
        text = f"🔴 <b>Purchase Confirmation</b>\n\n<b>{item_info['emoji']} {item_info['name'].replace('-', ' ').title()} x {quantity}</b>\n<b>Effect:</b> {item_info['effect']}\n\n💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵\n💰 <b>Total Cost:</b> {total_cost} 💵 ({item_info['price']} × {quantity})\n\nAre you sure you want to buy this?"
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    elif data_parts[1] == "buymisc":
        # Process the misc item purchase
        item_name = data_parts[2]
        quantity = int(data_parts[3])
        item_info = next((m for m in MISC_ITEMS if m['name'] == item_name), None)
        if not item_info:
            await callback_query.answer("Invalid item selection!", show_alert=True)
            return
        # Block Mega Bracelet if already owned
        if item_name == "mega-bracelet":
            # Always set quantity to 1 for Mega Bracelet
            quantity = 1
            # Refresh user from DB to get latest has_mega_bracelet
            user = await get_or_create_user(user_id, callback_query.from_user.username or "", callback_query.from_user.first_name or "")
            if user.get("has_mega_bracelet", False):
                await callback_query.answer("You already own a Mega Bracelet!", show_alert=True)
                return
                
        # Block Z-Ring if already owned
        if item_name == "z-ring":
            # Always set quantity to 1 for Z-Ring
            quantity = 1
            # Refresh user from DB to get latest has_z_ring
            user = await get_or_create_user(user_id, callback_query.from_user.username or "", callback_query.from_user.first_name or "")
            if user.get("has_z_ring", False):
                await callback_query.answer("You already own a Z-Ring!", show_alert=True)
                return
        total_cost = item_info['price'] * quantity
        if user['pokedollars'] < total_cost:
            await callback_query.answer("You don't have sufficient PokeDollars!", show_alert=True)
            return
        new_pokedollars = user['pokedollars'] - total_cost

        if item_name == "mega-bracelet":
            # Execute balance update and mega bracelet update concurrently
            await asyncio.gather(
                set_user_balance(user_id, new_pokedollars),
                set_user_mega_bracelet(user_id, True)
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏪 Continue Shopping", callback_data=f"pokemart_main_{user_id}")]
            ])
            text = (
                "✅ <b>Purchase Successful!</b>\n\n"
                "You bought <b> Mega Bracelet</b> for <b>20000 PokeDollars</b> 💵\n\n"
                f"💰 <b>Remaining PokeDollars:</b> {new_pokedollars} 💵\n"
                "\nThank you for shopping at PokeMart! 🏪"
            )
            await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            return

        if item_name == "z-ring":
            # Execute balance update and z-ring update concurrently
            await asyncio.gather(
                set_user_balance(user_id, new_pokedollars),
                set_user_z_ring(user_id, True)
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏪 Continue Shopping", callback_data=f"pokemart_main_{user_id}")]
            ])
            text = (
                "✅ <b>Purchase Successful!</b>\n\n"
                "You bought <b>⚡ Z-Ring</b> for <b>50000 PokeDollars</b> 💵\n\n"
                f"💰 <b>Remaining PokeDollars:</b> {new_pokedollars} 💵\n"
                "\nThank you for shopping at PokeMart! 🏪"
            )
            await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            return

        # Default: add to inventory
        inventory = await get_user_inventory(user_id)
        inventory[item_name] = inventory.get(item_name, 0) + quantity
        
        # Execute balance update and inventory update concurrently
        await asyncio.gather(
            set_user_balance(user_id, new_pokedollars),
            update_user_inventory(user_id, inventory)
        )
        new_item_count = inventory[item_name]
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏪 Continue Shopping", callback_data=f"pokemart_main_{user_id}")]
        ])
        text = (
            f"✅ <b>Purchase Successful!</b>\n\n"
            f"You bought <b>{quantity} {item_info['emoji']} {item_info['name'].replace('-', ' ').title()}</b> for <b>{total_cost} PokeDollars</b> 💵\n\n"
            f"💰 <b>Remaining PokeDollars:</b> {new_pokedollars} 💵\n"
            f"<b>Total {item_info['name'].replace('-', ' ').title()}:</b> {new_item_count}\n\n"
            "Thank you for shopping at PokeMart! 🏪"
        )
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "main":
        # Return to main pokemart page
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="PokeBalls", callback_data=f"pokemart_pokeballs_{user_id}"),
                InlineKeyboardButton(text="Fishing Rods", callback_data=f"pokemart_fishingrods_{user_id}")
            ],
            [
                InlineKeyboardButton(text="Training Items", callback_data=f"pokemart_training_{user_id}"),
                InlineKeyboardButton(text="Miscellaneous", callback_data=f"pokemart_misc_{user_id}")
            ],
            [
                InlineKeyboardButton(text="TM Shop", callback_data=f"pokemart_tms_{user_id}")
            ]
        ])
        
        text = f"""🏪 <b>Welcome to PokeMart!</b>

What would you like to buy today?

💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "tms":
        # Show TM type selection page
        types = pokemon_utils.get_tm_types()
        keyboard_rows = []
        
        # Show 9 types per page (3x3 grid)
        page = 0
        if len(data_parts) > 3:
            try:
                page = int(data_parts[3])
            except ValueError:
                page = 0
        
        start_idx = page * 9
        end_idx = start_idx + 9
        page_types = types[start_idx:end_idx]
        
        # Create 3x3 grid of type buttons
        for i in range(0, len(page_types), 3):
            row = []
            for j in range(3):
                if i + j < len(page_types):
                    type_name = page_types[i + j]
                    row.append(InlineKeyboardButton(
                        text=type_name,
                        callback_data=f"pokemart_tmtype_{type_name}_{user_id}"
                    ))
            keyboard_rows.append(row)
        
        # Add pagination if needed
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️ Previous", callback_data=f"pokemart_tms_{user_id}_{page-1}"))
        if end_idx < len(types):
            nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"pokemart_tms_{user_id}_{page+1}"))
        if nav_row:
            keyboard_rows.append(nav_row)
        
        keyboard_rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_main_{user_id}")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        text = f"""🎯 <b>TM Shop - Select Type</b>

Which type of TM would you like to browse?

💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "tmtype":
        # Show TMs of selected type
        selected_type = data_parts[2]
        page = 0
        if len(data_parts) > 4:
            try:
                page = int(data_parts[4])
            except ValueError:
                page = 0
        
        tms, total_pages, total_tms = pokemon_utils.get_paginated_tms_by_type(selected_type, page, 10)
        
        if not tms:
            await callback_query.answer(f"No TMs found for {selected_type} type!", show_alert=True)
            return
        
        keyboard_rows = []
        
        # Create TM buttons (2 per row)
        for i in range(0, len(tms), 2):
            row = []
            for j in range(2):
                if i + j < len(tms):
                    tm_id, tm_data = tms[i + j]
                    tm_number = tm_id.replace('tm', '')
                    row.append(InlineKeyboardButton(
                        text=f"TM{tm_number}",
                        callback_data=f"pokemart_tmdetails_{tm_id}_{user_id}"
                    ))
            keyboard_rows.append(row)
        
        # Add pagination if needed
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️ Previous", callback_data=f"pokemart_tmtype_{selected_type}_{user_id}_{page-1}"))
        if page + 1 < total_pages:
            nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"pokemart_tmtype_{selected_type}_{user_id}_{page+1}"))
        if nav_row:
            keyboard_rows.append(nav_row)
        
        keyboard_rows.append([InlineKeyboardButton(text="⬅️ Back to Types", callback_data=f"pokemart_tms_{user_id}")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        text = f"""🎯 <b>TM Shop - {selected_type} Type</b>

<b>Available TMs ({total_tms} total):</b>

"""
        
        for tm_id, tm_data in tms:
            tm_number = tm_id.replace('tm', '')
            name = tm_data.get('name', 'Unknown')
            category = tm_data.get('category', 'Unknown')
            power = tm_data.get('power', 0)
            accuracy = tm_data.get('accuracy', 0)
            
            power_str = str(power) if power and power > 0 else "—"
            accuracy_str = f"{accuracy}%" if accuracy else "—"
            
            text += f"<b>TM{tm_number} - {name}</b> | {category} | Power: {power_str} | Acc: {accuracy_str}\n"
        
        text += f"\n💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵"
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "tmdetails":
        # Show TM details and purchase confirmation
        tm_id = data_parts[2]
        tm_data = pokemon_utils.get_tm_by_id(tm_id)
        
        if not tm_data:
            await callback_query.answer("TM not found!", show_alert=True)
            return
        
        price = pokemon_utils.calculate_tm_price(tm_data)
        
        # Check if user has enough money
        if user['pokedollars'] < price:
            await callback_query.answer("You don't have sufficient PokeDollars!", show_alert=True)
            return
        
        tm_number = tm_id.replace('tm', '')
        name = tm_data.get('name', 'Unknown')
        type_name = tm_data.get('type', 'Unknown')
        category = tm_data.get('category', 'Unknown')
        power = tm_data.get('power', 0)
        accuracy = tm_data.get('accuracy', 0)
        
        power_str = str(power) if power and power > 0 else "—"
        accuracy_str = f"{accuracy}%" if accuracy else "—"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Purchase", callback_data=f"pokemart_buytm_{tm_id}_{user_id}"),
                InlineKeyboardButton(text="⬅️ Back", callback_data=f"pokemart_tmtype_{type_name}_{user_id}")
            ]
        ])
        
        text = f"""🔴 <b>TM Purchase</b>

<b>TM{tm_number} - {name}</b>

<b>Type:</b> {type_name}
<b>Category:</b> {category}
<b>Power:</b> {power_str}
<b>Accuracy:</b> {accuracy_str}

💰 <b>Your PokeDollars:</b> {user['pokedollars']} 💵
💰 <b>Price:</b> {price} 💵

Are you sure you want to purchase this TM?"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    elif data_parts[1] == "buytm":
        # Process TM purchase
        tm_id = data_parts[2]
        tm_data = pokemon_utils.get_tm_by_id(tm_id)
        
        if not tm_data:
            await callback_query.answer("TM not found!", show_alert=True)
            return
        
        price = pokemon_utils.calculate_tm_price(tm_data)
        
        # Execute purchase using batch operations
        success, message = await batch_tm_purchase_operations(user_id, tm_id, 1, price)
        
        if not success:
            await callback_query.answer(f"Purchase failed: {message}", show_alert=True)
            return
        
        # Get updated user data
        user = await get_or_create_user(user_id, username, first_name)
        
        tm_number = tm_id.replace('tm', '')
        name = tm_data.get('name', 'Unknown')
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏪 Continue Shopping", callback_data=f"pokemart_main_{user_id}")]
        ])
        
        text = f"""✅ <b>Purchase Successful!</b>

You bought <b>TM{tm_number} - {name}</b> for <b>{price} PokeDollars</b> 💵

💰 <b>Remaining PokeDollars:</b> {user['pokedollars']} 💵

Thank you for shopping at PokeMart! 🏪"""
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    await callback_query.answer()