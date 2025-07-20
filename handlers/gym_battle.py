from aiogram import Router, types
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import (
    get_or_create_user, get_user_team, update_user_pokedollars, 
    update_user_gym_progress, get_user_gym_progress
)
from pokemon_utils import pokemon_utils
from gym_leaders import KANTO
from ai_logic import AIBattle
from battle_logic import apply_move, check_faint # Assuming battle_logic.py exists and is accessible
import copy
import random

router = Router()

# In-memory gym battle state
gym_battles = {}

def get_leader_data(region, leader_name):
    region_data = []
    if region.upper() == "KANTO":
        region_data = KANTO
    for leader in region_data:
        if leader["leader"].lower() == leader_name.lower():
            return copy.deepcopy(leader)
    return None

def create_battle_keyboard(battle_state):
    active_poke = battle_state['player_active_pokemon']
    moves = active_poke.get('moves', [])
    buttons = [InlineKeyboardButton(text=move['name'], callback_data=f"gym_move_{move['name']}") for move in moves]
    keyboard = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    keyboard.append([
        InlineKeyboardButton(text="Switch", callback_data="gym_switch"),
        InlineKeyboardButton(text="Forfeit", callback_data="gym_forfeit")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def build_switch_keyboard(battle_state):
    buttons = []
    for i, poke in enumerate(battle_state['player_team']):
        if poke['hp'] > 0:
            buttons.append(InlineKeyboardButton(text=poke['name'], callback_data=f"gym_switch_{i}"))
    keyboard = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@router.callback_query(lambda c: c.data.startswith('confirm_gym_'))
async def confirm_gym_challenge(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    leader_name = callback_query.data.split('_')[2]
    user = await get_or_create_user(user_id, callback_query.from_user.username, callback_query.from_user.first_name)

    fee = 500
    if user.get('pokedollars', 0) < fee:
        await callback_query.answer(f"You don't have enough money! You need {fee} Pokédollars.", show_alert=True)
        return

    user_team = await get_user_team(user_id)
    is_valid, message = pokemon_utils.validate_gym_team(user_team)
    if not is_valid:
        await callback_query.answer(message, show_alert=True)
        return

    # Process user's team moves into the required dictionary format
    for pokemon in user_team:
        processed_moves = []
        for move in pokemon.get('moves', []) :
            if isinstance(move, str):
                processed_moves.append({'name': move})
            else:
                processed_moves.append(move) # Already in dict format
        pokemon['moves'] = processed_moves

    await update_user_pokedollars(user_id, -fee)
    leader_data = get_leader_data("Kanto", leader_name)

    battle_id = f"gym_{user_id}"
    gym_battles[battle_id] = {
        "user_id": user_id,
        "leader_name": leader_name.capitalize(),
        "player_team": user_team,
        "ai_team": leader_data["team"],
        "player_active_pokemon": user_team[0],
        "ai_active_pokemon": leader_data["team"][0],
        "turn": "player",
        "message_id": callback_query.message.message_id,
        "chat_id": callback_query.message.chat.id,
        "battle_log": []
    }

    battle_state = gym_battles[battle_id]
    player_poke = battle_state['player_active_pokemon']['name']
    ai_poke = battle_state['ai_active_pokemon']['name']
    text = f"You sent out {player_poke}!\nGym Leader {leader_name.capitalize()} sent out {ai_poke}!\n\nWhat will you do?"
    keyboard = create_battle_keyboard(battle_state)
    await callback_query.message.edit_text(text, reply_markup=keyboard)
    await callback_query.answer()

@router.callback_query(lambda c: c.data.startswith('gym_switch_'))
async def gym_battle_switch_pokemon(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    battle_id = f"gym_{user_id}"
    battle_state = gym_battles.get(battle_id)

    if not battle_state:
        await callback_query.answer("This battle has expired.", show_alert=True)
        return

    switch_index = int(callback_query.data.split('_')[2])
    new_pokemon = battle_state['player_team'][switch_index]

    if new_pokemon['hp'] <= 0:
        await callback_query.answer("You can't switch to a fainted Pokémon!", show_alert=True)
        return

    battle_state['player_active_pokemon'] = new_pokemon
    battle_state['turn'] = 'player' # Player's turn after switching

    text = f"You sent out {new_pokemon['name']}!\n\nWhat will you do?"
    keyboard = create_battle_keyboard(battle_state)
    await callback_query.message.edit_text(text, reply_markup=keyboard)
    await callback_query.answer()


@router.callback_query(lambda c: c.data == 'gym_forfeit')
async def gym_forfeit(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    battle_id = f"gym_{user_id}"
    if battle_id in gym_battles:
        del gym_battles[battle_id]
        await callback_query.message.edit_text("You have forfeited the match.")
        await callback_query.answer("Battle ended.")
    else:
        await callback_query.answer("No active battle to forfeit.", show_alert=True)

@router.callback_query(lambda c: c.data == 'gym_switch')
async def voluntary_switch_prompt(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    battle_id = f"gym_{user_id}"
    battle_state = gym_battles.get(battle_id)
    if not battle_state:
        await callback_query.answer("This battle has expired.", show_alert=True)
        return

    # Build keyboard with a different callback for voluntary switching
    buttons = []
    for i, poke in enumerate(battle_state['player_team']):
        if poke['hp'] > 0 and poke != battle_state['player_active_pokemon']:
            buttons.append(InlineKeyboardButton(text=poke['name'], callback_data=f"gym_vswitch_{i}"))
    keyboard = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    await callback_query.message.edit_text("Choose a Pokémon to switch to.", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback_query.answer()

@router.callback_query(lambda c: c.data.startswith('gym_vswitch_'))
async def gym_voluntary_switch_action(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    battle_id = f"gym_{user_id}"
    battle_state = gym_battles.get(battle_id)
    if not battle_state:
        await callback_query.answer("This battle has expired.", show_alert=True)
        return

    switch_index = int(callback_query.data.split('_')[2])
    new_pokemon = battle_state['player_team'][switch_index]
    battle_state['player_active_pokemon'] = new_pokemon

    battle_log = [f"You withdrew your Pokémon and sent out {new_pokemon['name']}!"]
    
    # AI gets to attack immediately after a voluntary switch
    await execute_ai_turn(callback_query, battle_state, battle_log)

@router.callback_query(lambda c: c.data.startswith('gym_move_'))
async def process_gym_turn(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    battle_id = f"gym_{user_id}"
    battle_state = gym_battles.get(battle_id)

    if not battle_state or battle_state['turn'] != 'player':
        await callback_query.answer("It's not your turn or the battle is over.", show_alert=True)
        return

    # Player's Turn
    player_poke = battle_state['player_active_pokemon']
    ai_poke = battle_state['ai_active_pokemon']
    move_name = callback_query.data.split('_')[2]
    move = next((m for m in player_poke['moves'] if m['name'] == move_name), None)
    
    battle_log = []

    # Player attacks AI
    result = apply_move(player_poke, ai_poke, move)
    damage = result.get('damage', 0)
    ai_poke['hp'] = max(0, ai_poke['hp'] - damage)
    battle_log.append(f"You used {move_name}! It dealt {damage} damage.")

    if check_faint(ai_poke):
        battle_log.append(f"{ai_poke['name']} fainted!")
        # Check for win
        if not any(p['hp'] > 0 for p in battle_state['ai_team']):
            leader_index = KANTO.index(next(l for l in KANTO if l['leader'] == battle_state['leader_name']))
            await update_user_gym_progress(user_id, "kanto", leader_index)
            await callback_query.message.edit_text(f"You defeated Gym Leader {battle_state['leader_name']}!")
            del gym_battles[battle_id]
            return
        else: # AI needs to switch
            next_ai_poke = next(p for p in battle_state['ai_team'] if p['hp'] > 0)
            battle_state['ai_active_pokemon'] = next_ai_poke
            battle_log.append(f"Gym Leader sent out {next_ai_poke['name']}!")
            # Player's turn again
            text = "\n".join(battle_log) + "\n\nWhat will you do?"
            await callback_query.message.edit_text(text, reply_markup=create_battle_keyboard(battle_state))
            return

    # AI's Turn
    await execute_ai_turn(callback_query, battle_state, battle_log)

async def execute_ai_turn(callback_query, battle_state, battle_log):
    player_poke = battle_state['player_active_pokemon']
    ai_poke = battle_state['ai_active_pokemon']
    battle_id = f"gym_{callback_query.from_user.id}"

    ai_battle = AIBattle(battle_state['ai_team'], battle_state['player_team'], ai_poke, player_poke)
    ai_action = ai_battle.decide_action()
    ai_move_name = ai_action['details']
    ai_move = next((m for m in ai_poke['moves'] if m['name'] == ai_move_name), None)

    result = apply_move(ai_poke, player_poke, ai_move)
    damage = result.get('damage', 0)
    player_poke['hp'] = max(0, player_poke['hp'] - damage)
    battle_log.append(f"Foe's {ai_poke['name']} used {ai_move_name}! It dealt {damage} damage.")

    if check_faint(player_poke):
        battle_log.append(f"Your {player_poke['name']} fainted!")
        if not any(p['hp'] > 0 for p in battle_state['player_team']):
            await callback_query.message.edit_text("All your Pokémon have fainted. You lose!")
            del gym_battles[battle_id]
            return
        else:
            battle_log.append("You must switch to your next Pokémon.")
            text = "\n".join(battle_log)
            keyboard = build_switch_keyboard(battle_state)
            await callback_query.message.edit_text(text, reply_markup=keyboard)
            return

    text = "\n".join(battle_log) + "\n\nWhat will you do?"
    await callback_query.message.edit_text(text, reply_markup=create_battle_keyboard(battle_state))
    await callback_query.answer()
