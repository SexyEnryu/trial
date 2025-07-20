from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import asyncio
import difflib
from database import get_or_create_user, get_user_pokemon, release_pokemon
from handlers.stats import create_info_page, check_starter_package, verify_callback_user

router = Router()

class ReleaseStates(StatesGroup):
    confirming_release = State()
    selecting_pokemon = State()

@router.message(Command("release"))
async def release_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    is_valid, result = await check_starter_package(user_id, message.from_user.username or "", message.from_user.first_name or "")
    if not is_valid:
        await message.reply(str(result), parse_mode="HTML")
        return
    user = result
    if not message.text:
        await message.reply("❌ Please specify a Pokémon name!\n\nUsage: <code>/release &lt;pokemon_name&gt;</code>", parse_mode="HTML")
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if not args:
        await message.reply("❌ Please specify a Pokémon name!\n\nUsage: <code>/release &lt;pokemon_name&gt;</code>", parse_mode="HTML")
        return
    pokemon_name = " ".join(args).lower()
    user_pokemon = await get_user_pokemon(user_id)
    if not user_pokemon:
        await message.reply("❌ You don't have any Pokémon yet! Use <code>/hunt</code> to catch some first.", parse_mode="HTML")
        return
    matching_pokemon = [p for p in user_pokemon if p.get('name', '').lower() == pokemon_name]
    if not matching_pokemon:
        user_names = list({p.get('name', '').title() for p in user_pokemon})
        closest = difflib.get_close_matches(pokemon_name.title(), user_names, n=1, cutoff=0.6)
        if closest:
            suggested = closest[0]
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Yes", callback_data=f"release_suggested_yes_{suggested}_{user_id}"),
                        InlineKeyboardButton(text="No", callback_data=f"release_suggested_no_{user_id}")
                    ]
                ]
            )
            await message.reply(
                f"❌ You don't have any <b>{pokemon_name.title()}</b> in your collection!\nDid you mean: <b>{suggested}</b>?",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await state.set_state(ReleaseStates.confirming_release)
            await state.update_data(original_name=pokemon_name)
            return
        else:
            await message.reply(f"❌ You don't have any <b>{pokemon_name.title()}</b> in your collection!", parse_mode="HTML")
            return
    if len(matching_pokemon) == 1:
        await show_release_confirmation(message, matching_pokemon[0], user_pokemon.index(matching_pokemon[0]), state, user_id)
        return
    # Multiple Pokémon selection
    await show_pokemon_selection(message, matching_pokemon, state, user_id, user_pokemon)

async def show_pokemon_selection(message, pokemon_list, state, user_id, user_pokemon):
    pokemon_name = pokemon_list[0]['name']
    text = f"🔍 You have <b>{len(pokemon_list)}</b> {pokemon_name}:\n\n"
    keyboard_rows = []
    current_row = []
    for i, pokemon in enumerate(pokemon_list, 1):
        idx = user_pokemon.index(pokemon)
        text += f"{i}) <b>{pokemon['name']}</b> - Lv.{pokemon['level']}\n"
        button = InlineKeyboardButton(
            text=str(i),
            callback_data=f"release_select_{idx}_{user_id}"
        )
        current_row.append(button)
        if len(current_row) == 5:
            keyboard_rows.append(current_row)
            current_row = []
    if current_row:
        keyboard_rows.append(current_row)
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await message.reply(text, reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(ReleaseStates.selecting_pokemon)
    await state.update_data(pokemon_list=pokemon_list)

async def show_release_confirmation(message_or_callback, pokemon, idx, state, user_id, edit=False):
    text, _ = create_info_page(pokemon, user_id)
    text += f"\n\n<b>Are you sure you want to release this Pokémon?</b>"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Yes, release", callback_data=f"release_confirm_yes_{idx}_{user_id}"),
                InlineKeyboardButton(text="❌ No", callback_data=f"release_confirm_no_{user_id}")
            ]
        ]
    )
    if edit and hasattr(message_or_callback, 'edit_text'):
        await message_or_callback.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await message_or_callback.reply(text, reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(ReleaseStates.confirming_release)
    await state.update_data(release_idx=idx, release_pokemon=pokemon)

@router.callback_query(F.data.startswith("release_select_"))
async def handle_release_select(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    data_parts = callback_query.data.split("_")
    if len(data_parts) < 4 or data_parts[-1] != str(user_id):
        await callback_query.answer("❌ You can only interact with your own menu!", show_alert=True)
        return
    idx = int(data_parts[2])
    user_pokemon = await get_user_pokemon(user_id)
    if not (0 <= idx < len(user_pokemon)):
        await callback_query.answer("❌ Invalid Pokémon selection!", show_alert=True)
        return
    await show_release_confirmation(callback_query.message, user_pokemon[idx], idx, state, user_id, edit=True)
    await callback_query.answer()

@router.callback_query(F.data.startswith("release_suggested_yes_"))
async def handle_release_suggested_yes(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    data_parts = callback_query.data.split("_")
    if data_parts[-1] != str(user_id):
        await callback_query.answer("❌ You can only interact with your own menu!", show_alert=True)
        return
    suggested = "_".join(data_parts[3:-1])
    user_pokemon = await get_user_pokemon(user_id)
    matching_pokemon = [p for p in user_pokemon if p.get('name', '').lower() == suggested.lower()]
    if not matching_pokemon:
        await callback_query.answer("You don't have this Pokémon!", show_alert=True)
        return
    if len(matching_pokemon) == 1:
        await show_release_confirmation(callback_query.message, matching_pokemon[0], user_pokemon.index(matching_pokemon[0]), state, user_id, edit=True)
    else:
        await show_pokemon_selection(callback_query.message, matching_pokemon, state, user_id, user_pokemon)
    await callback_query.answer()

@router.callback_query(F.data.startswith("release_suggested_no_"))
async def handle_release_suggested_no(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    if not verify_callback_user(callback_query.data, user_id):
        await callback_query.answer("❌ You can only interact with your own menu!", show_alert=True)
        return
    await callback_query.answer("Cancelled.", show_alert=True)
    if hasattr(callback_query, 'message'):
        await callback_query.message.edit_reply_markup(reply_markup=None)

@router.callback_query(F.data.startswith("release_confirm_yes_"))
async def handle_release_confirm_yes(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    data_parts = callback_query.data.split("_")
    if data_parts[-1] != str(user_id):
        await callback_query.answer("❌ You can only interact with your own menu!", show_alert=True)
        return
    idx = int(data_parts[3])
    success, msg = await release_pokemon(user_id, idx)
    if success:
        await callback_query.message.edit_text(f"✅ {msg}", parse_mode="HTML")
    else:
        await callback_query.answer(msg, show_alert=True)

@router.callback_query(F.data.startswith("release_confirm_no_"))
async def handle_release_confirm_no(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    if not verify_callback_user(callback_query.data, user_id):
        await callback_query.answer("❌ You can only interact with your own menu!", show_alert=True)
        return
    await callback_query.answer("Cancelled.", show_alert=True)
    if hasattr(callback_query, 'message'):
        await callback_query.message.edit_reply_markup(reply_markup=None) 