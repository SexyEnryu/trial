from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database import get_or_create_user, get_user_inventory, get_user_tms
from config import POKEBALLS, FISHING_RODS, BERRIES, VITAMINS, MISC_ITEMS
from pokemon_utils import pokemon_utils
from utils.start_check import require_started_user, prevent_non_started_interaction

router = Router()

@router.message(Command("myinventory"))
async def inventory_command(message: types.Message):
    """Show user inventory - Main page by default"""
    # This command is allowed without starting the bot
    user_id = message.from_user.id
    user = await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)
    inventory = await get_user_inventory(user_id)
    
    # Create keyboard with navigation buttons (include user_id for validation)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Pokeballs", callback_data=f"inventory_pokeballs_{user_id}"),
            InlineKeyboardButton(text="Fishing Rods", callback_data=f"inventory_fishingrods_{user_id}")
        ],
        [
            InlineKeyboardButton(text="Training Items", callback_data=f"inventory_training_{user_id}"),
            InlineKeyboardButton(text="TMs", callback_data=f"inventory_tms_{user_id}")
        ],
        [
            InlineKeyboardButton(text="Mega Stones", callback_data=f"inventory_megastones_{user_id}"),
            InlineKeyboardButton(text="Z-Crystals", callback_data=f"inventory_zcrystals_{user_id}")
        ],
        [
            InlineKeyboardButton(text="Plates", callback_data=f"inventory_plates_{user_id}")
        ]
    ])
    
    # Show main inventory page
    text = f"<u><b>Your Inventory:</b></u>\n\n💵 <b>PokeDollars:</b> {user['pokedollars']}\n"
    rare_candy_count = inventory.get("rare-candy", 0)
    if rare_candy_count > 0:
        text += f"🍬 <b>Rare Candy:</b> {rare_candy_count}\n"
    await message.reply(text, reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(lambda c: c.data.startswith("inventory_"))
@prevent_non_started_interaction()
async def inventory_callback(callback_query: CallbackQuery):
    """Handle inventory page navigation"""
    user_id = callback_query.from_user.id
    
    # Parse callback data to get page and original user_id
    callback_parts = callback_query.data.split("_")
    page = callback_parts[1]
    
    # Check if user_id is included in callback_data for validation
    if len(callback_parts) > 2:
        original_user_id = int(callback_parts[2])
        if original_user_id != user_id:
            await callback_query.answer("This is not your inventory!", show_alert=True)
            return
    
    user = await get_or_create_user(user_id, callback_query.from_user.username, callback_query.from_user.first_name)
    inventory = await get_user_inventory(user_id)
    
    if page == "main":
        # Main page - show navigation buttons
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Pokeballs", callback_data=f"inventory_pokeballs_{user_id}"),
                InlineKeyboardButton(text="Fishing Rods", callback_data=f"inventory_fishingrods_{user_id}")
            ],
            [
                InlineKeyboardButton(text="Training Items", callback_data=f"inventory_training_{user_id}"),
                InlineKeyboardButton(text="TMs", callback_data=f"inventory_tms_{user_id}")
            ],
            [
                InlineKeyboardButton(text="Mega Stones", callback_data=f"inventory_megastones_{user_id}"),
                InlineKeyboardButton(text="Z-Crystals", callback_data=f"inventory_zcrystals_{user_id}")
            ],
            [
                InlineKeyboardButton(text="Plates", callback_data=f"inventory_plates_{user_id}")
            ]
        ])
        
        text = f"""<u><b>Your Inventory:</b></u>\n\n💵 <b>PokeDollars:</b> {user['pokedollars']}\n"""
        rare_candy_count = inventory.get("rare-candy", 0)
        if rare_candy_count > 0:
            text += f"🍬 <b>Rare Candy:</b> {rare_candy_count}\n"
        
    elif page == "pokeballs":
        # Pokeballs page - show back button
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Back to Main", callback_data=f"inventory_main_{user_id}")]
        ])
        
        text = f"""<u><b>Pokeball Collection:</b></u>

"""
        
        # Add pokeball counts for all types
        has_pokeballs = False
        
        # If POKEBALLS config exists, use it to maintain order
        if 'POKEBALLS' in globals() and POKEBALLS:
            for pokeball in POKEBALLS:
                name = pokeball["name"]
                count = user['pokeballs'].get(name, 0)
                
                if count > 0:
                    text += f"<b>{name} Ball:</b> {count}\n"
                    has_pokeballs = True
        else:
            # Fallback: iterate through user's pokeballs directly
            for pokeball_name, count in user['pokeballs'].items():
                if count > 0:
                    text += f"<b>{pokeball_name} Ball:</b> {count}\n"
                    has_pokeballs = True
        
        # Show empty message if no pokeballs
        if not has_pokeballs:
            text += "No Pokeballs in inventory!"
    
    elif page == "fishingrods":
        # Fishing Rods page - show back button
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Back to Main", callback_data=f"inventory_main_{user_id}")]
        ])
        
        text = f"""<u><b>Fishing Rod Collection:</b></u>

"""
        
        # Add fishing rod collection - numbered format
        has_rods = False
        user_rods = user.get('fishing_rods', {})
        rod_count = 1
        
        # If FISHING_RODS config exists, use it to maintain order and show all rods
        if 'FISHING_RODS' in globals() and FISHING_RODS:
            for rod in FISHING_RODS:
                name = rod["name"]
                if name in user_rods and user_rods[name]:
                    text += f"{rod_count}) {name}\n"
                    has_rods = True
                    rod_count += 1
        else:
            # Fallback: iterate through user's fishing rods directly
            for rod_name, owned in user_rods.items():
                if owned:
                    text += f"{rod_count}) {rod_name}\n"
                    has_rods = True
                    rod_count += 1
        
        # Show empty message if no fishing rods
        if not has_rods:
            text += "No Fishing Rods in inventory!"
    
    elif page == "training":
        # Training Items page - show back button
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Back to Main", callback_data=f"inventory_main_{user_id}")]
        ])
        text = f"""<u><b>Training Items Collection:</b></u>\n\n"""
        # Get user's unified inventory
        inventory = await get_user_inventory(user_id)
        # Add berries section
        text += "<b>Berries:</b>\n"
        has_berries = False
        for berry in BERRIES:
            name = berry["name"]
            count = inventory.get(name, 0)
            if count > 0:
                text += f"<b><u>{name}:</u></b> {count}\n"
                has_berries = True
        if not has_berries:
            text += "No Berries in inventory!\n"
        text += "\n"
        # Add vitamins section
        text += "<b>Vitamins:</b>\n"
        has_vitamins = False
        for vitamin in VITAMINS:
            name = vitamin["name"]
            count = inventory.get(name, 0)
            if count > 0:
                text += f"<b><u>{name}:</u></b> {count}\n"
                has_vitamins = True
        if not has_vitamins:
            text += "No Vitamins in inventory!"
    
    elif page == "tms":
        # TM/HM page - show back button and pagination if needed
        keyboard_rows = [[InlineKeyboardButton(text="Back to Main", callback_data=f"inventory_main_{user_id}")]]
        
        user_tms = await get_user_tms(user_id)
        
        # Pagination logic
        tms_per_page = 15
        page_num = 0
        if len(callback_parts) > 3:
            try:
                page_num = int(callback_parts[3])
            except Exception:
                page_num = 0
        
        # Get TM data and sort by TM number
        tm_list = []
        for tm_id, quantity in user_tms.items():
            if quantity > 0:
                tm_data = pokemon_utils.get_tm_by_id(tm_id)
                if tm_data:
                    tm_number = int(tm_id.replace('tm', ''))
                    tm_list.append((tm_number, tm_id, tm_data, quantity))
        
        # Sort by TM number
        tm_list.sort(key=lambda x: x[0])
        
        total_tms = len(tm_list)
        total_pages = (total_tms - 1) // tms_per_page + 1 if total_tms > 0 else 1
        start = page_num * tms_per_page
        end = start + tms_per_page
        tms_to_show = tm_list[start:end]
        
        text = f"<u><b>TMs Collection:</b></u>\n\n"
        
        if not tm_list:
            text += "No TMs in your inventory!"
        else:
            for tm_number, tm_id, tm_data, quantity in tms_to_show:
                name = tm_data.get('name', 'Unknown')
                type_name = tm_data.get('type', 'Unknown')
                text += f"<b>TM{tm_number} - {name}</b> ({type_name}) x{quantity}\n"
            
            # Pagination buttons if needed
            if total_tms > tms_per_page:
                nav_row = []
                if page_num > 0:
                    nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"inventory_tms_{user_id}_{page_num-1}"))
                if end < total_tms:
                    nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"inventory_tms_{user_id}_{page_num+1}"))
                if nav_row:
                    keyboard_rows.insert(0, nav_row)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()
        return
    
    elif page == "megastones":
        # Mega Stones page - show back button and pagination if needed
        keyboard_rows = [[InlineKeyboardButton(text="Back to Main", callback_data=f"inventory_main_{user_id}")]]
        from database import get_user_mega_stones
        mega_stones = await get_user_mega_stones(user_id)
        # Display name mapping for orbs and stones
        STONE_DISPLAY_NAMES = {
            'redorb': 'Red Orb',
            'blueorb': 'Blue Orb',
            'jadeorb': 'Jade Orb',
            'rusted_sword': 'Rusted Sword',
            'rusted_shield': 'Rusted Shield',
            'black_core': 'Black Core',
            'white_core': 'White Core',
        }
        # Pagination logic
        stones_per_page = 20
        # Get page number from callback data if present
        page_num = 0
        if len(callback_parts) > 3:
            try:
                page_num = int(callback_parts[3])
            except Exception:
                page_num = 0
        total_stones = len(mega_stones)
        total_pages = (total_stones - 1) // stones_per_page + 1 if total_stones > 0 else 1
        start = page_num * stones_per_page
        end = start + stones_per_page
        stones_to_show = mega_stones[start:end]
        text = f"<u><b>Mega Stones Collection:</b></u>\n\n"
        if not mega_stones:
            text += "No Mega Stones In Your Inventory."
        else:
            for stone in stones_to_show:
                display_name = STONE_DISPLAY_NAMES.get(stone.lower(), stone.title())
                text += f"• <b>{display_name}</b>\n"
            # Pagination buttons if needed
            if total_stones > stones_per_page:
                nav_row = []
                if page_num > 0:
                    nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"inventory_megastones_{user_id}_{page_num-1}"))
                if end < total_stones:
                    nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"inventory_megastones_{user_id}_{page_num+1}"))
                if nav_row:
                    keyboard_rows.insert(0, nav_row)
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()
        return
    
    elif page == "zcrystals":
        # Z-Crystals page - show back button, no pagination
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Back to Main", callback_data=f"inventory_main_{user_id}")]
        ])
        from database import get_user_z_crystals
        z_crystals = await get_user_z_crystals(user_id)
        # Mapping for display names
        Z_DISPLAY_NAMES = {
            'firiumz': 'Firium Z', 'wateriumz': 'Waterium Z', 'grassiumz': 'Grassium Z', 'electriumz': 'Electrium Z',
            'psychiumz': 'Psychium Z', 'rockiumz': 'Rockium Z', 'snorliumz': 'Snorlium Z', 'steeliumz': 'Steelium Z',
            'tapuniumz': 'Tapunium Z', 'mimikiumz': 'Mimikium Z', 'normaliumz': 'Normalium Z', 'pikaniumz': 'Pikanium Z',
            'pikashuniumz': 'Pikashunium Z', 'poisoniumz': 'Poisonium Z', 'primariumz': 'Primarium Z', 'kommoniumz': 'Kommonium Z',
            'lycaniumz': 'Lycanium Z', 'marshadiumz': 'Marshadium Z', 'mewniumz': 'Mewnium Z', 'groundiumz': 'Groundium Z',
            'iciumz': 'Icium Z', 'inciniumz': 'Incinium Z', 'fightiniumz': 'Fightinium Z', 'flyiniumz': 'Flyinium Z',
            'ghostiumz': 'Ghostium Z', 'dragoniumz': 'Dragonium Z', 'eeviumz': 'Eevium Z', 'fairiumz': 'Fairium Z',
            'darkiniumz': 'Darkinium Z', 'aloraichiumz': 'Aloraichium Z', 'buginiumz': 'Buginium Z', 'decidiumz': 'Decidium Z'
        }
        text = f"<u><b>Z-Crystals Collection:</b></u>\n\n"
        if not z_crystals:
            text += "No Z-Crystals In Your Inventory."
        else:
            for crystal in z_crystals:
                display_name = Z_DISPLAY_NAMES.get(crystal.lower(), crystal.title())
                text += f"• <b>{display_name}</b>\n"
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()
        return
    
    elif page == "plates":
        # Plates page - show back button, no pagination
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Back to Main", callback_data=f"inventory_main_{user_id}")]
        ])
        from database import get_user_plates
        plates = await get_user_plates(user_id)
        # Mapping for display names (from plate.json)
        PLATE_DISPLAY_NAMES = {
            'flame-plate': 'Flame Plate', 'splash-plate': 'Splash Plate', 'zap-plate': 'Zap Plate',
            'meadow-plate': 'Meadow Plate', 'icicle-plate': 'Icicle Plate', 'fist-plate': 'Fist Plate',
            'toxic-plate': 'Toxic Plate', 'earth-plate': 'Earth Plate', 'sky-plate': 'Sky Plate',
            'mind-plate': 'Mind Plate', 'insect-plate': 'Insect Plate', 'stone-plate': 'Stone Plate',
            'spooky-plate': 'Spooky Plate', 'draco-plate': 'Draco Plate', 'dread-plate': 'Dread Plate',
            'iron-plate': 'Iron Plate', 'pixie-plate': 'Pixie Plate'
        }
        
        # Plate to type mapping for type display
        PLATE_TO_TYPE = {
            # Hyphenated format (display names)
            'flame-plate': 'Fire', 'splash-plate': 'Water', 'zap-plate': 'Electric',
            'meadow-plate': 'Grass', 'icicle-plate': 'Ice', 'fist-plate': 'Fighting',
            'toxic-plate': 'Poison', 'earth-plate': 'Ground', 'sky-plate': 'Flying',
            'mind-plate': 'Psychic', 'insect-plate': 'Bug', 'stone-plate': 'Rock',
            'spooky-plate': 'Ghost', 'draco-plate': 'Dragon', 'dread-plate': 'Dark',
            'iron-plate': 'Steel', 'pixie-plate': 'Fairy',
            # File name format (no hyphens) - actual stored names  
            'flameplate': 'Fire', 'splashplate': 'Water', 'zapplate': 'Electric',
            'meadowplate': 'Grass', 'icicleplate': 'Ice', 'fistplate': 'Fighting',
            'toxicplate': 'Poison', 'earthplate': 'Ground', 'skyplate': 'Flying',
            'mindplate': 'Psychic', 'insectplate': 'Bug', 'stoneplate': 'Rock',
            'spookyplate': 'Ghost', 'dracoplate': 'Dragon', 'dreadplate': 'Dark',
            'ironplate': 'Steel', 'pixieplate': 'Fairy'
        }
        
        text = f"<u><b>Plates Collection:</b></u>\n\n"
        if not plates:
            text += "No Plates In Your Inventory."
        else:
            for plate in plates:
                display_name = PLATE_DISPLAY_NAMES.get(plate.lower(), plate.title())
                plate_type = PLATE_TO_TYPE.get(plate.lower(), 'Unknown')
                text += f"• <b>{display_name} [{plate_type}]</b>\n"
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()
        return
    
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()