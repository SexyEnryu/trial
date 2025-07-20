from typing import Dict, List, Optional, Tuple, Any
import random
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from battle_logic import get_turn_order, apply_move, check_faint, calculate_damage, get_type_list, get_type_effectiveness
from ai_logic import AIGymLeader
from database import get_user_balance, update_user_balance, update_user_pokemon_collection, get_or_create_user
from pokemon_utils import PokemonUtils
from assets.functions import pbar, calculate_total_stat, calculate_total_hp

class GymBattle:
    def __init__(self, user_id: int, gym_leader: str, gym_team: List[Dict], user_team: List[Dict], message: types.Message):
        self.user_id = user_id
        self.gym_leader = gym_leader
        self.ai_team = gym_team
        self.user_team = user_team
        self.ai_active_pokemon = self.ai_team[0]
        self.player_active_pokemon = self.user_team[0]
        self.ai = AIGymLeader(self.ai_team, self.user_team, self.ai_active_pokemon, self.player_active_pokemon)
        self.battle_log = []
        self.entry_fee = 500
        self.allowed_switches = 10
        self.used_switches = 0
        self.battle_state = "selecting"  # selecting, battling, ended
        self.message = message
        
    async def can_start_battle(self, user_id: int) -> Tuple[bool, str]:
        """Check if user can start the battle"""
        # Check balance
        balance = await get_user_balance(user_id)
        if balance < self.entry_fee:
            return False, f"You need {self.entry_fee} Pokedollars to challenge this gym!"
            
        # Get user's current team from database
        user_data = await get_or_create_user(user_id, '', '')
        user_team = user_data.get('team', [])
        if not user_team or len(user_team) < 1:
            return False, "You don't have any Pokémon in your team!"
            
        # Check each Pokémon
        for poke in user_team:
            if self.is_legendary_or_mythical(poke):
                return False, f"{poke['name']} is a legendary/mythical Pokémon and is banned!"
                
            if self.has_banned_type(poke):
                return False, f"{poke['name']} has a type that's super effective against {self.gym_type} and is banned!"
                
        return True, ""
        
    def is_legendary_or_mythical(self, pokemon: Dict) -> bool:
        """Check if a Pokémon is legendary or mythical"""
        # This should be implemented based on your Pokémon data
        legendary_list = ["Mewtwo", "Mew", "Lugia", "Ho-Oh", "Celebi", 
                         "Kyogre", "Groudon", "Rayquaza", "Jirachi", 
                         "Dialga", "Palkia", "Giratina", "Arceus"]
        return pokemon.get('name') in legendary_list
        
    def has_banned_type(self, pokemon: Dict) -> bool:
        """Check if Pokémon has a type that's super effective against the gym type"""
        type_effectiveness = {
            'Rock': ['Fighting', 'Ground', 'Steel', 'Water', 'Grass'],
            'Water': ['Electric', 'Grass'],
            'Electric': ['Ground'],
            'Grass': ['Fire', 'Ice', 'Poison', 'Flying', 'Bug'],
            'Fire': ['Water', 'Ground', 'Rock'],
            'Flying': ['Electric', 'Ice', 'Rock'],
            'Ground': ['Water', 'Grass', 'Ice'],
            'Psychic': ['Bug', 'Ghost', 'Dark'],
            'Ghost': ['Ghost', 'Dark'],
            'Dragon': ['Ice', 'Dragon', 'Fairy'],
            'Dark': ['Fighting', 'Bug', 'Fairy'],
            'Steel': ['Fire', 'Fighting', 'Ground'],
            'Fairy': ['Poison', 'Steel'],
            'Normal': ['Fighting'],
            'Fighting': ['Flying', 'Psychic', 'Fairy'],
            'Poison': ['Ground', 'Psychic'],
            'Bug': ['Fire', 'Flying', 'Rock'],
            'Ice': ['Fire', 'Fighting', 'Rock', 'Steel']
        }
        
        for poke_type in get_type_list(pokemon):
            if poke_type in type_effectiveness.get(self.gym_type, []):
                return True
        return False
        
    async def start_battle(self, message: types.Message) -> bool:
        """Start the gym battle"""
        self.message = message
        # Get user's current team from database
        user_data = await get_or_create_user(self.user_id, '', '')
        user_team = user_data.get('team', [])
        if not user_team or len(user_team) < 1:
            await message.answer("You don't have any Pokémon in your team!")
            return False
            
        # Validate team
        can_start, reason = await self.can_start_battle(self.user_id)
        if not can_start:
            await message.answer(reason)
            return False
            
        # Deduct entry fee
        await update_user_balance(self.user_id, -self.entry_fee)
        
        # Initialize battle state
        self.user_team = user_team
        self.user_active = 0
        self.battle_state = "selecting"
        self.battle_log = []
        
        # Show team selection
        await self.show_team_selection()
        return True
        
    async def show_team_selection(self):
        """Show team selection interface"""
        buttons = []
        
        for i, poke in enumerate(self.user_team):
            hp_percent = (poke.get('hp', 0) / poke.get('max_hp', 1)) * 100
            status = ""
            if check_faint(poke):
                status = "💀"
            buttons.append(
                InlineKeyboardButton(
                    text=f"{i+1}. {poke['name']} {status}",
                    callback_data=f"gym_select_{i}"
                )
            )
            
        # Create keyboard with buttons in rows of 3
        keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons[i:i + 3] for i in range(0, len(buttons), 3)])
        await self.message.answer(
            f"<b>Gym Leader {self.gym_leader} Challenge</b>\n"
            f"<i>Select your lead Pokémon:</i>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
    async def handle_selection(self, index: int):
        """Handle Pokémon selection"""
        if index < 0 or index >= len(self.user_team):
            return
            
        self.user_active = index
        self.battle_state = "battling"
        await self.update_battle_ui()
        
    async def update_battle_ui(self):
        """Update the battle interface"""
        user_poke = self.user_team[self.user_active]
        ai_poke = self.ai.current_pokemon
        
        # Build battle message
        message_text = (
            f"<b>Gym Leader {self.gym_leader}</b>\n"
            f"{ai_poke['name']} Lv.{ai_poke.get('level', 50)} "
            f"HP: {pbar(ai_poke.get('hp', 0), ai_poke.get('max_hp', 1))}\n\n"
            f"<b>Your {user_poke['name']}</b> Lv.{user_poke.get('level', 50)}\n"
            f"HP: {pbar(user_poke.get('hp', 0), user_poke.get('max_hp', 1))}\n\n"
            "What will you do?"
        )
        
        # Build action buttons
        keyboard = InlineKeyboardMarkup(row_width=2)
        
        # Add moves
        moves = user_poke.get('moves', [])[:4]  # First 4 moves
        move_buttons = []
        for i, move in enumerate(moves):
            move_buttons.append(
                InlineKeyboardButton(
                    text=move,
                    callback_data=f"gym_move_{i}"
                )
            )
        
        # Add switch button if allowed
        switch_button = [
            InlineKeyboardButton(
                text=f"Switch ({self.allowed_switches - self.used_switches} left)",
                callback_data="gym_switch"
            )
        ]
        
        # Add give up button
        give_up_button = [
            InlineKeyboardButton(
                text="Give Up",
                callback_data="gym_giveup"
            )
        ]
        
        # Add buttons to keyboard
        keyboard.add(*move_buttons)
        keyboard.add(*switch_button)
        keyboard.add(*give_up_button)
        
        # Send or update message
        if not hasattr(self, 'battle_message'):
            self.battle_message = await self.message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await self.battle_message.edit_text(message_text, reply_markup=keyboard, parse_mode="HTML")
    
    async def handle_move(self, move_index: int):
        """Handle move selection"""
        if self.battle_state != "battling":
            return
            
        user_poke = self.user_team[self.user_active]
        ai_poke = self.ai.current_pokemon
        
        # Get move
        moves = user_poke.get('moves', [])
        if move_index >= len(moves):
            return
            
        move_name = moves[move_index]
        
        # AI chooses action
        ai_action, ai_data = self.ai.choose_action(user_poke)
        
        # Determine turn order
        user_first = True  # Simplified - should use speed stat
        
        # Execute turns
        if user_first:
            # User's turn
            damage = await self.use_move(user_poke, ai_poke, move_name)
            await self.message.answer(f"{user_poke['name']} used {move_name}!")
            if damage > 0:
                await self.message.answer(f"It dealt {damage} damage!")
                
            # Check if AI's Pokémon fainted
            if check_faint(ai_poke):
                await self.message.answer(f"{ai_poke['name']} fainted!")
                # AI switches Pokémon
                await self.ai_switch_pokemon()
            
            # AI's turn if battle still ongoing
            if not await self.check_battle_end():
                if ai_action == 'mega':
                    await self.handle_ai_mega()
                elif ai_action == 'zmove':
                    await self.handle_ai_zmove(ai_data['move'])
                elif ai_action == 'switch':
                    await self.ai_switch_pokemon(ai_data['pokemon_index'])
                else:  # Regular move
                    ai_move = ai_data if isinstance(ai_data, str) else ai_data.get('move', 'Tackle')
                    damage = await self.use_ai_move(ai_poke, user_poke, ai_move)
                    await self.message.answer(f"{ai_poke['name']} used {ai_move}!")
                    if damage > 0:
                        await self.message.answer(f"It dealt {damage} damage!")
        
        # Update UI
        await self.update_battle_ui()
    
    async def handle_switch(self):
        """Handle Pokémon switch"""
        if self.used_switches >= self.allowed_switches:
            await self.message.answer("No more switches left!")
            return
            
        self.used_switches += 1
        self.battle_state = "switching"
        await self.show_switch_menu()
    
    async def show_switch_menu(self):
        """Show switch Pokémon menu"""
        keyboard = InlineKeyboardMarkup(row_width=2)
        buttons = []
        
        for i, poke in enumerate(self.user_team):
            if i == self.user_active:
                continue
                
            hp_percent = (poke.get('hp', 0) / poke.get('max_hp', 1)) * 100
            status = "💀" if check_faint(poke) else f"{hp_percent:.0f}%"
            buttons.append(
                InlineKeyboardButton(
                    text=f"{poke['name']} ({status})",
                    callback_data=f"gym_switchto_{i}"
                )
            )
            
        keyboard.add(*buttons)
        keyboard.add(InlineKeyboardButton(text="Back", callback_data="gym_back_to_battle"))
        
        await self.battle_message.edit_text(
            "Select a Pokémon to switch to:",
            reply_markup=keyboard
        )
    
    async def handle_switch_to(self, index: int):
        """Handle switching to a specific Pokémon"""
        if index < 0 or index >= len(self.user_team) or index == self.user_active:
            return
            
        old_poke = self.user_team[self.user_active]['name']
        self.user_active = index
        new_poke = self.user_team[self.user_active]['name']
        
        await self.message.answer(f"You switched to {new_poke}!")
        self.battle_state = "battling"
        await self.update_battle_ui()
    
    async def handle_give_up(self):
        """Handle giving up the battle"""
        self.battle_state = "ended"
        await self.message.answer("You gave up the battle!")
        # Clean up
        if hasattr(self, 'battle_message'):
            try:
                await self.battle_message.delete()
            except:
                pass
    
    async def use_move(self, attacker: Dict, defender: Dict, move_name: str) -> int:
        """Use a move and return damage dealt"""
        # Simplified damage calculation
        # In a real implementation, use the battle_logic module
        damage = random.randint(20, 40)
        defender['hp'] = max(0, defender.get('hp', 0) - damage)
        return damage
    
    async def use_ai_move(self, attacker: Dict, defender: Dict, move_name: str) -> int:
        """AI uses a move and returns damage dealt"""
        # Similar to use_move but for AI
        damage = random.randint(20, 40)
        defender['hp'] = max(0, defender.get('hp', 0) - damage)
        return damage
    
    async def handle_ai_mega(self):
        """Handle AI mega evolution"""
        ai_poke = self.ai.current_pokemon
        self.ai.record_mega_evolution()
        await self.message.answer(f"{ai_poke['name']} mega evolved!")
    
    async def handle_ai_zmove(self, move_name: str):
        """Handle AI using a Z-move"""
        ai_poke = self.ai.current_pokemon
        self.ai.record_z_move(move_name)
        damage = random.randint(50, 100)  # Z-moves are stronger
        user_poke = self.user_team[self.user_active]
        user_poke['hp'] = max(0, user_poke.get('hp', 0) - damage)
        await self.message.answer(f"{ai_poke['name']} used a Z-Move!")
        await self.message.answer(f"It dealt {damage} damage!")
    
    async def ai_switch_pokemon(self, index: int = None):
        """AI switches Pokémon"""
        if index is None:
            # Find first non-fainted Pokémon
            for i, poke in enumerate(self.ai.team):
                if not check_faint(poke) and i != self.ai.current_pokemon_index:
                    index = i
                    break
                    
        if index is not None:
            old_poke = self.ai.current_pokemon['name']
            self.ai.switch_to(index)
            new_poke = self.ai.current_pokemon['name']
            await self.message.answer(f"{self.gym_leader} sent out {new_poke}!")
    
    async def check_battle_end(self) -> bool:
        """Check if battle has ended and handle results"""
        # Check if user's team is defeated
        if all(check_faint(poke) for poke in self.user_team):
            await self.message.answer("All your Pokémon fainted! You lost the battle.")
            self.battle_state = "ended"
            return True
            
        # Check if AI's team is defeated
        if all(check_faint(poke) for poke in self.ai.team):
            reward = 1000  # Base reward
            await update_user_balance(self.user_id, reward)
            await self.message.answer(
                f"You defeated {self.gym_leader}!\n"
                f"You earned {reward} Pokedollars!"
            )
            self.battle_state = "ended"
            return True
            
        return False
