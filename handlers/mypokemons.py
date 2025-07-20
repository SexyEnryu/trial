from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from database import get_or_create_user
from pokemon_utils import PokemonUtils
from preferences import get_user_preferences, check_starter_package

router = Router()
pokemon_utils = PokemonUtils()

def sort_pokemon(pokemon_list, sort_by, sort_direction):
    """Sort Pokemon based on user preferences"""
    reverse = sort_direction == 'descending'
    
    if sort_by == 'order_caught':
        # Maintain original order for order caught
        return pokemon_list if not reverse else pokemon_list[::-1]
    elif sort_by == 'pokedex_number':
        return sorted(pokemon_list, key=lambda p: p['id'], reverse=reverse)
    elif sort_by == 'level':
        return sorted(pokemon_list, key=lambda p: p['level'], reverse=reverse)
    elif sort_by == 'iv_points':
        return sorted(pokemon_list, key=lambda p: sum(p.get('ivs', {}).values()), reverse=reverse)
    elif sort_by == 'ev_points':
        return sorted(pokemon_list, key=lambda p: sum(p.get('evs', {}).values()), reverse=reverse)
    elif sort_by == 'name':
        return sorted(pokemon_list, key=lambda p: p['name'].lower(), reverse=reverse)
    elif sort_by == 'nature':
        return sorted(pokemon_list, key=lambda p: p.get('nature', '').lower(), reverse=reverse)
    elif sort_by == 'type':
        return sorted(pokemon_list, key=lambda p: p.get('type', [''])[0].lower(), reverse=reverse)
    elif sort_by == 'catch_rate':
        return sorted(pokemon_list, key=lambda p: pokemon_utils.get_pokemon_info(p['id']).get('capture_rate', 255), reverse=reverse)
    elif sort_by == 'hp_points':
        return sorted(pokemon_list, key=lambda p: p.get('calculated_stats', {}).get('HP', 0), reverse=reverse)
    elif sort_by == 'attack_points':
        return sorted(pokemon_list, key=lambda p: p.get('calculated_stats', {}).get('Attack', 0), reverse=reverse)
    elif sort_by == 'defense_points':
        return sorted(pokemon_list, key=lambda p: p.get('calculated_stats', {}).get('Defense', 0), reverse=reverse)
    elif sort_by == 'sp_attack_points':
        return sorted(pokemon_list, key=lambda p: p.get('calculated_stats', {}).get('Sp. Attack', 0), reverse=reverse)
    elif sort_by == 'sp_defense_points':
        return sorted(pokemon_list, key=lambda p: p.get('calculated_stats', {}).get('Sp. Defense', 0), reverse=reverse)
    elif sort_by == 'speed_points':
        return sorted(pokemon_list, key=lambda p: p.get('calculated_stats', {}).get('Speed', 0), reverse=reverse)
    elif sort_by == 'total_stats_points':
        return sorted(pokemon_list, key=lambda p: sum(p.get('calculated_stats', {}).values()), reverse=reverse)
    else:
        return pokemon_list

def format_pokemon_display(pokemon, display_options, show_numbering=False, index=None):
    """Format Pokemon display based on user preferences"""
    display_parts = []
    
    # Add numbering if enabled (fixed formatting)
    if show_numbering and index is not None:
        display_parts.append(f"{index})")
    
    # Pokemon name
    pokemon_name = pokemon['name'].title()
    if pokemon.get('shiny', False):
        pokemon_name += " ✨"
    display_parts.append(f"<b>{pokemon_name}</b>")
    
    # Add display options
    for option in display_options:
        if option == 'level':
            display_parts.append(f"Lv.{pokemon['level']}")
        elif option == 'iv_points':
            iv_total = sum(pokemon.get('ivs', {}).values())
            display_parts.append(f"IV: {iv_total}")
        elif option == 'ev_points':
            ev_total = sum(pokemon.get('evs', {}).values())
            display_parts.append(f"EV: {ev_total}")
        elif option == 'nature':
            display_parts.append(f"{pokemon.get('nature', 'Unknown')}")
        elif option == 'type':
            types = pokemon.get('type', [])
            display_parts.append(f"Type: {'/'.join(types)}")
        elif option == 'type_symbol':
            # Add type symbols (emojis)
            type_symbols = {
                'Normal': '⚪', 'Fire': '🔥', 'Water': '💧', 'Electric': '⚡',
                'Grass': '🌿', 'Ice': '❄️', 'Fighting': '👊', 'Poison': '☠️',
                'Ground': '🌍', 'Flying': '🌪️', 'Psychic': '🔮', 'Bug': '🐛',
                'Rock': '🪨', 'Ghost': '👻', 'Dragon': '🐉', 'Dark': '🌑',
                'Steel': '⚙️', 'Fairy': '🧚'
            }
            types = pokemon.get('type', [])
            symbols = [type_symbols.get(t, '❓') for t in types]
            display_parts.append(''.join(symbols))
        elif option == 'catch_rate':
            catch_rate = pokemon_utils.get_pokemon_info(pokemon['id']).get('capture_rate', 255)
            display_parts.append(f"Catch: {catch_rate}")
        elif option == 'hp_points':
            hp = pokemon.get('calculated_stats', {}).get('HP', 0)
            display_parts.append(f"HP: {hp}")
        elif option == 'attack_points':
            attack = pokemon.get('calculated_stats', {}).get('Attack', 0)
            display_parts.append(f"ATK: {attack}")
        elif option == 'defense_points':
            defense = pokemon.get('calculated_stats', {}).get('Defense', 0)
            display_parts.append(f"DEF: {defense}")
        elif option == 'sp_attack_points':
            sp_attack = pokemon.get('calculated_stats', {}).get('Sp. Attack', 0)
            display_parts.append(f"SP.ATK: {sp_attack}")
        elif option == 'sp_defense_points':
            sp_defense = pokemon.get('calculated_stats', {}).get('Sp. Defense', 0)
            display_parts.append(f"SP.DEF: {sp_defense}")
        elif option == 'speed_points':
            speed = pokemon.get('calculated_stats', {}).get('Speed', 0)
            display_parts.append(f"SPD: {speed}")
        elif option == 'total_stats_points':
            total = sum(pokemon.get('calculated_stats', {}).values())
            display_parts.append(f"Total: {total}")
    
    # Fixed: Use space instead of " - " for numbering
    if show_numbering and index is not None:
        # Join the first part (number) with space, then rest with " - "
        return f"{display_parts[0]} {' - '.join(display_parts[1:])}"
    else:
        return ' - '.join(display_parts)

@router.message(Command("mypokemons"))
async def mypokemon_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Batch async operations for better performance
    import asyncio
    
    # Run validation and preferences fetching concurrently
    validation_task = asyncio.create_task(
        check_starter_package(user_id, message.from_user.username, message.from_user.first_name)
    )
    preferences_task = asyncio.create_task(get_user_preferences(user_id))
    
    # Wait for validation first (preferences might fail if user doesn't exist)
    is_valid, result = await validation_task
    
    if not is_valid:
        # Reply to the user's command message
        await message.reply(result, parse_mode="HTML")
        return
    
    user = result  # result contains user data if valid
    
    if not user or 'pokemon' not in user or not user['pokemon']:
        # Reply to the user's command message
        await message.reply("You don't have any Pokémon yet! Use /hunt to catch some.", parse_mode="HTML")
        return
    
    # Get preferences (now can safely await)
    preferences = await preferences_task
    
    # Sort Pokemon based on preferences
    sorted_pokemon = sort_pokemon(user['pokemon'], preferences['sort_by'], preferences['sort_direction'])
    
    # Show first page (reply to user's command)
    await show_pokemon_page(message, sorted_pokemon, 0, user_id, is_reply=True)

async def show_pokemon_page(message_or_callback, pokemon_list, page, user_id, is_reply=False):
    POKEMON_PER_PAGE = 20
    total_pages = (len(pokemon_list) + POKEMON_PER_PAGE - 1) // POKEMON_PER_PAGE
    
    start_index = page * POKEMON_PER_PAGE
    end_index = min(start_index + POKEMON_PER_PAGE, len(pokemon_list))
    
    # Get user preferences (await added)
    preferences = await get_user_preferences(user_id)
    
    # Build Pokemon list text
    pokemon_text = f"<b><i>Your Pokémon Collection :</i></b>\n"
    pokemon_text += f"<b>Total</b>: {len(pokemon_list)} Pokémon\n"
    pokemon_text += f"<b>Page:</b> {page + 1}/{total_pages}\n\n"
    
    for i in range(start_index, end_index):
        pokemon = pokemon_list[i]
        pokemon_display = format_pokemon_display(
            pokemon, 
            preferences['display_options'], 
            preferences['show_numbering'], 
            i + 1
        )
        pokemon_text += f"{pokemon_display}\n"
    
    # Build pagination keyboard (simplified - only Previous/Next buttons)
    keyboard_rows = []
    
    if total_pages > 1:
        nav_buttons = []
        
        # Previous button
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="◀️ Previous", 
                    callback_data=f"pokemon_page_{page - 1}_{user_id}"
                )
            )
        
        # Next button
        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="Next ▶️", 
                    callback_data=f"pokemon_page_{page + 1}_{user_id}"
                )
            )
        
        if nav_buttons:  # Only add row if there are buttons
            keyboard_rows.append(nav_buttons)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    if isinstance(message_or_callback, types.Message):
        if is_reply:
            # Reply to the user's command message
            await message_or_callback.reply(pokemon_text, reply_markup=keyboard, parse_mode="HTML")
        else:
            # Send as regular message
            await message_or_callback.answer(pokemon_text, reply_markup=keyboard, parse_mode="HTML")
    else:
        # Edit the callback query message
        await message_or_callback.message.edit_text(pokemon_text, reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(F.data.startswith("pokemon_page_"))
async def handle_pokemon_pagination(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    
    data_parts = callback_query.data.split("_")
    if len(data_parts) < 4:
        await callback_query.answer("Invalid page data!", show_alert=True)
        return
    
    page = int(data_parts[2])
    button_user_id = int(data_parts[3])
    
    # Check if user is authorized to interact with this button
    if user_id != button_user_id:
        await callback_query.answer("❌ You can only interact with your own Pokémon list!", show_alert=True)
        return
    
    # Check if user has claimed starter package
    is_valid, result = await check_starter_package(user_id, callback_query.from_user.username, callback_query.from_user.first_name)
    if not is_valid:
        await callback_query.answer(result, show_alert=True)
        return
    
    user = result  # result contains user data if valid
    
    if not user or 'pokemon' not in user or not user['pokemon']:
        await callback_query.answer("❌ You don't have any Pokémon!", show_alert=True)
        return
    
    # Get user preferences and sort Pokemon (await added)
    preferences = await get_user_preferences(user_id)
    sorted_pokemon = sort_pokemon(user['pokemon'], preferences['sort_by'], preferences['sort_direction'])
    
    await show_pokemon_page(callback_query, sorted_pokemon, page, user_id)
    await callback_query.answer()

@router.callback_query(F.data == "page_info")
async def page_info_callback(callback_query: CallbackQuery):
    await callback_query.answer("Page information", show_alert=False)