# This file will contain the logic for the AI Gym Leader's battle decisions.

import random
from battle_logic import get_type_effectiveness, get_type_list, MOVES, normalize_move_name

class AIGymLeader:
    def __init__(self, ai_team, player_team, ai_active_pokemon, player_active_pokemon):
        self.ai_team = ai_team
        self.player_team = player_team
        self.ai_active_pokemon = ai_active_pokemon
        self.player_active_pokemon = player_active_pokemon

    def decide_action(self):
        """
        The core AI logic. Decides the best move based on type effectiveness.
        """
        best_move = None
        max_effectiveness = -1.0

        player_types = get_type_list(self.player_active_pokemon)

        for move in self.ai_active_pokemon['moves']:
            move_name = move.get('name')
            if not move_name:
                continue

            move_key = normalize_move_name(move_name)
            move_data = MOVES.get(move_key)

            if not move_data or move_data.get('power', 0) == 0:
                continue  # Skip status moves for now

            move_type = move_data.get('type', 'normal')
            
            effectiveness, _ = get_type_effectiveness(move_type, player_types)

            if effectiveness > max_effectiveness:
                max_effectiveness = effectiveness
                best_move = move_name
        
        if best_move is None:
            # Fallback to a random damaging move if no optimal move is found
            damaging_moves = [m['name'] for m in self.ai_active_pokemon['moves'] if MOVES.get(normalize_move_name(m['name']), {}).get('power', 0) > 0]
            if damaging_moves:
                best_move = random.choice(damaging_moves)
            else: # If all else fails, pick any move
                best_move = random.choice(self.ai_active_pokemon['moves'])['name']

        return {"type": "move", "details": best_move}
