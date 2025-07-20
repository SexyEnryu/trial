import json, os
import random
from typing import Dict, List, Optional, Tuple, Any
import uuid
import re

class PokemonUtils:
    def __init__(self):
        """Initialize Pokemon utilities with data loading"""
        self.poke_data = self.load_json('poke.json')
        self.poke_moves = self.load_json('assets/variable.jsons/pokeMoves.json')
        self.regions = self.load_json('assets/variable.jsons/regionInfo.json')
        self.tm_data = self.load_json('tmhm.json')
        self.gym_leaders = self.load_json('gym_leaders.json')
        self.move_info = self.load_json('move_info.json')

        print(f"DEBUG: Loaded {len(self.poke_data)} Pokemon from poke.json")
        print(f"DEBUG: Loaded {len(self.regions)} regions from regionInfo.json")
        print(f"DEBUG: Available regions: {list(self.regions.keys())}")
        print(f"DEBUG: Loaded {len(self.tm_data)} TMs from tmhm.json")
        print(f"DEBUG: Loaded {len(self.move_info)} moves from moveInfo.json")
        
        # Create lookup dictionary for faster access
        self.pokemon_lookup = {pokemon['id']: pokemon for pokemon in self.poke_data}
        self.pokemon_name_lookup = {pokemon['name'].lower(): pokemon for pokemon in self.poke_data}
        
        # Create move lookup dictionary with normalized names for faster access
        self.move_lookup = {}
        for move_name, move_data in self.move_info.items():
            # Add multiple variants for move lookup
            normalized_name = self.normalize_move_name(move_name)
            self.move_lookup[normalized_name] = move_data
            self.move_lookup[move_name] = move_data
            self.move_lookup[move_name.lower()] = move_data
        
        # Pokemon types for TM filtering
        self.pokemon_types = [
            'Normal', 'Fire', 'Water', 'Electric', 'Grass', 'Ice',
            'Fighting', 'Poison', 'Ground', 'Flying', 'Psychic', 'Bug',
            'Rock', 'Ghost', 'Dragon', 'Dark', 'Steel', 'Fairy'
        ]
        
        # Pokemon natures with stat modifiers
        self.natures = {
            'Hardy': {'increase': None, 'decrease': None},
            'Lonely': {'increase': 'Attack', 'decrease': 'Defense'},
            'Brave': {'increase': 'Attack', 'decrease': 'Speed'},
            'Adamant': {'increase': 'Attack', 'decrease': 'Sp. Attack'},
            'Naughty': {'increase': 'Attack', 'decrease': 'Sp. Defense'},
            'Bold': {'increase': 'Defense', 'decrease': 'Attack'},
            'Docile': {'increase': None, 'decrease': None},
            'Relaxed': {'increase': 'Defense', 'decrease': 'Speed'},
            'Impish': {'increase': 'Defense', 'decrease': 'Sp. Attack'},
            'Lax': {'increase': 'Defense', 'decrease': 'Sp. Defense'},
            'Timid': {'increase': 'Speed', 'decrease': 'Attack'},
            'Hasty': {'increase': 'Speed', 'decrease': 'Defense'},
            'Serious': {'increase': None, 'decrease': None},
            'Jolly': {'increase': 'Speed', 'decrease': 'Sp. Attack'},
            'Naive': {'increase': 'Speed', 'decrease': 'Sp. Defense'},
            'Modest': {'increase': 'Sp. Attack', 'decrease': 'Attack'},
            'Mild': {'increase': 'Sp. Attack', 'decrease': 'Defense'},
            'Quiet': {'increase': 'Sp. Attack', 'decrease': 'Speed'},
            'Bashful': {'increase': None, 'decrease': None},
            'Rash': {'increase': 'Sp. Attack', 'decrease': 'Sp. Defense'},
            'Calm': {'increase': 'Sp. Defense', 'decrease': 'Attack'},
            'Gentle': {'increase': 'Sp. Defense', 'decrease': 'Defense'},
            'Sassy': {'increase': 'Sp. Defense', 'decrease': 'Speed'},
            'Careful': {'increase': 'Sp. Defense', 'decrease': 'Sp. Attack'},
            'Quirky': {'increase': None, 'decrease': None}
        }
        
        # Pokemon weight categories for Heavy Ball calculations
        self.weight_categories = {
            'very_light': (0, 25),      # 0-25 kg
            'light': (25, 50),          # 25-50 kg
            'medium': (50, 100),        # 50-100 kg
            'heavy': (100, 200),        # 100-200 kg
            'very_heavy': (200, 1000),  # 200+ kg
        }
        
    def load_json(self, file_path: str) -> Dict:
        """Load JSON file and return data"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"File not found: {file_path}")
            return {}
        except json.JSONDecodeError as e:
            print(f"JSON decode error in {file_path}: {e}")
            return {}
        except Exception as e:
            print(f"Error loading {file_path}: {e}")
            return {}
    
    def get_random_kanto_pokemon(self) -> Tuple[int, Dict]:
        """Get a random Kanto Pokemon with its data"""
        kanto_pokemon = self.regions.get('1', [])
        if not kanto_pokemon:
            # Fallback to first 151 Pokemon if regions.json is not available
            kanto_pokemon = list(range(1, 152))
        
        # If region data contains names, use them; otherwise use IDs
        if kanto_pokemon and isinstance(kanto_pokemon[0], str):
            pokemon_name = random.choice(kanto_pokemon)
            pokemon_data = self.pokemon_name_lookup.get(pokemon_name.lower())
        else:
            pokemon_id = random.choice(kanto_pokemon)
            pokemon_data = self.pokemon_lookup.get(pokemon_id)
        
        if not pokemon_data:
            # Fallback to first Pokemon (Bulbasaur)
            pokemon_data = self.poke_data[0] if self.poke_data else {}
        
        return pokemon_data.get('id', 1), pokemon_data
    
    def get_random_region_pokemon(self, region_name: str) -> Tuple[int, Dict]:
        """Get a random Pokemon from a specific region with its data"""
        # Map region names to region numbers
        region_mapping = {
            "Kanto": "1",
            "Johto": "2", 
            "Hoenn": "3",
            "Sinnoh": "4",
            "Unova": "5",
            "Kalos": "6",
            "Alola": "7",
            "Galar": "8",
            "Paldea": "9"
        }
        
        region_number = region_mapping.get(region_name, "1")  # Default to Kanto if region not found
        region_pokemon = self.regions.get(region_number, [])
        
        print(f"DEBUG: Region '{region_name}' maps to number '{region_number}'")
        print(f"DEBUG: Found {len(region_pokemon)} Pokemon for region {region_number}")
        
        if not region_pokemon:
            print(f"DEBUG: No Pokemon found for region {region_number}, falling back to Kanto")
            # Fallback to Kanto Pokemon if region data is not available
            region_pokemon = self.regions.get('1', [])
            if not region_pokemon:
                print(f"DEBUG: No Kanto Pokemon found either, using ID range 1-151")
                # Final fallback to first 151 Pokemon
                region_pokemon = list(range(1, 152))
        
        # If region data contains names, use them; otherwise use IDs
        if region_pokemon and isinstance(region_pokemon[0], str):
            pokemon_name = random.choice(region_pokemon)
            print(f"DEBUG: Selected Pokemon name: {pokemon_name}")
            pokemon_data = self.pokemon_name_lookup.get(pokemon_name.lower())
            print(f"DEBUG: Found Pokemon data: {pokemon_data is not None}")
        else:
            pokemon_id = random.choice(region_pokemon)
            print(f"DEBUG: Selected Pokemon ID: {pokemon_id}")
            pokemon_data = self.pokemon_lookup.get(pokemon_id)
            print(f"DEBUG: Found Pokemon data: {pokemon_data is not None}")
        
        if not pokemon_data:
            print(f"DEBUG: No Pokemon data found, using fallback Bulbasaur")
            # Fallback to first Pokemon (Bulbasaur)
            pokemon_data = self.poke_data[0] if self.poke_data else {}
        
        pokemon_id = pokemon_data.get('id', 1)
        print(f"DEBUG: Final Pokemon ID: {pokemon_id}, Name: {pokemon_data.get('name', 'Unknown')}")
        
        return pokemon_id, pokemon_data
    
    def test_region_data(self, region_name: str):
        """Test function to debug region data loading"""
        region_mapping = {
            "Kanto": "1",
            "Johto": "2", 
            "Hoenn": "3",
            "Sinnoh": "4",
            "Unova": "5",
            "Kalos": "6",
            "Alola": "7",
            "Galar": "8",
            "Paldea": "9"
        }
        
        region_number = region_mapping.get(region_name, "1")
        region_pokemon = self.regions.get(region_number, [])
        
        print(f"TEST: Region '{region_name}' -> '{region_number}' -> {len(region_pokemon)} Pokemon")
        if region_pokemon:
            print(f"TEST: First 5 Pokemon in {region_name}: {region_pokemon[:5]}")
        
        return region_pokemon
    
    def get_pokemon_by_id(self, pokemon_id: int) -> Optional[Dict]:
        """Get Pokemon data by ID"""
        return self.pokemon_lookup.get(pokemon_id)
    
    def get_pokemon_by_name(self, name: str) -> Optional[Dict]:
        """Get Pokemon data by name"""
        return self.pokemon_name_lookup.get(name.lower())
    
    def generate_boosted_iv(self, boost=7, cap=31):
        base = random.randint(0, cap)
        return min(base + boost, cap)

    def generate_random_ivs(self) -> Dict[str, int]:
        """Generate boosted IVs for all stats (0-31, with boost)"""
        return {
            'HP': self.generate_boosted_iv(),
            'Attack': self.generate_boosted_iv(),
            'Defense': self.generate_boosted_iv(),
            'Sp. Attack': self.generate_boosted_iv(),
            'Sp. Defense': self.generate_boosted_iv(),
            'Speed': self.generate_boosted_iv()
        }
    
    def get_random_nature(self) -> str:
        """Get a random nature"""
        return random.choice(list(self.natures.keys()))
    
    def get_moves_for_level(self, pokemon_id: int, level: int) -> List[Dict]:
        """Get all moves a Pokemon can learn at or below a certain level"""
        # Special case for Kyurem (all forms) - use specialMoves/kyurem.json
        pokemon_data = self.get_pokemon_by_id(pokemon_id)
        pokemon_name = pokemon_data.get('name', '').lower() if pokemon_data else ''
        
        if 'kyurem' in pokemon_name:
            return self.get_kyurem_special_moves(level)
        
        if not self.poke_moves or not isinstance(self.poke_moves, list):
            return self.get_fallback_moves(pokemon_id, level)
        
        # Convert Pokemon ID to array index (1-based to 0-based)
        pokemon_index = pokemon_id - 1
        
        # Check if the pokemon_index is valid
        if pokemon_index < 0 or pokemon_index >= len(self.poke_moves):
            return self.get_fallback_moves(pokemon_id, level)
        
        # Get the moves array for this specific Pokemon
        pokemon_moves = self.poke_moves[pokemon_index]
        
        # Check if pokemon_moves is a list
        if not isinstance(pokemon_moves, list):
            return self.get_fallback_moves(pokemon_id, level)
        
        # Filter moves that can be learned by level-up at or below the current level
        valid_moves = []
        for move_data in pokemon_moves:
            if not isinstance(move_data, dict):
                continue
            
            method = move_data.get('method')
            level_learned = move_data.get('level_learned_at', 0)
            
            # Include level-up moves that can be learned at current level or below
            if method == 'level-up' and level_learned <= level and level_learned > 0:
                valid_moves.append(move_data)
        
        # Sort by level learned and remove duplicates (keep latest version)
        valid_moves.sort(key=lambda x: x.get('level_learned_at', 0))
        
        # Remove duplicates, keeping the latest learned version
        unique_moves = {}
        for move in valid_moves:
            move_name = move.get('move')
            if move_name:
                unique_moves[move_name] = move
        
        final_moves = list(unique_moves.values())
        
        # If no moves found, return fallback moves
        if not final_moves:
            return self.get_fallback_moves(pokemon_id, level)
        
        # Normalize: ensure each move dict has a 'name' key
        for move in final_moves:
            if 'name' not in move and 'move' in move:
                move['name'] = PokemonUtils.normalize_move_name(move['move'])
        return final_moves
    
    def get_kyurem_special_moves(self, level: int) -> List[Dict]:
        """Get special moves for Kyurem from specialMoves/kyurem.json, filtered to damaging moves only"""
        try:
            # Load Kyurem's special moves
            with open('specialMoves/kyurem.json', 'r', encoding='utf-8') as f:
                kyurem_moves = json.load(f)
            
            # Load damaging moves for filtering
            with open('damaging_moves.json', 'r', encoding='utf-8') as f:
                damaging_moves = json.load(f)
            
            # Create a set of normalized damaging move names for comparison
            normalized_damaging_moves = set()
            for move_name in damaging_moves.keys():
                normalized_name = self.normalize_move_name(move_name)
                normalized_damaging_moves.add(normalized_name)
            
            # Filter moves that can be learned by level-up at or below the current level
            valid_moves = []
            for move_data in kyurem_moves:
                if not isinstance(move_data, dict):
                    continue
                
                method = move_data.get('method')
                level_learned = move_data.get('level_learned_at', 0)
                move_name = move_data.get('move', '')
                
                # Include level-up moves that can be learned at current level or below
                if method == 'level-up' and level_learned <= level and level_learned > 0:
                    # Check if it's a damaging move
                    normalized_move_name = self.normalize_move_name(move_name)
                    if normalized_move_name in normalized_damaging_moves:
                        valid_moves.append(move_data)
            
            # Sort by level learned and remove duplicates
            valid_moves.sort(key=lambda x: x.get('level_learned_at', 0))
            
            # Remove duplicates, keeping the latest learned version
            unique_moves = {}
            for move in valid_moves:
                move_name = move.get('move')
                if move_name:
                    unique_moves[move_name] = move
            
            final_moves = list(unique_moves.values())
            
            # Normalize: ensure each move dict has a 'name' key
            for move in final_moves:
                if 'name' not in move and 'move' in move:
                    move['name'] = self.normalize_move_name(move['move'])
            
            return final_moves if final_moves else self.get_fallback_moves(646, level)  # 646 is Kyurem's ID
            
        except Exception as e:
            print(f"Error loading Kyurem special moves: {e}")
            return self.get_fallback_moves(646, level)
    
    def get_fallback_moves(self, pokemon_id: int, level: int) -> List[Dict]:
        """Get fallback moves when no moves are found in the data"""
        # Common starting moves for different Pokemon
        fallback_moves = [
            {"move": "tackle", "level_learned_at": 1, "method": "level-up"},
            {"move": "growl", "level_learned_at": 1, "method": "level-up"}
        ]
        
        # Add specific moves based on Pokemon ID
        if pokemon_id == 1:  # Bulbasaur
            fallback_moves = [
                {"move": "tackle", "level_learned_at": 1, "method": "level-up"},
                {"move": "growl", "level_learned_at": 3, "method": "level-up"},
                {"move": "vine-whip", "level_learned_at": 7, "method": "level-up"},
                {"move": "poison-powder", "level_learned_at": 9, "method": "level-up"}
            ]
        elif pokemon_id == 4:  # Charmander
            fallback_moves = [
                {"move": "scratch", "level_learned_at": 1, "method": "level-up"},
                {"move": "growl", "level_learned_at": 1, "method": "level-up"},
                {"move": "ember", "level_learned_at": 7, "method": "level-up"},
                {"move": "smokescreen", "level_learned_at": 10, "method": "level-up"}
            ]
        elif pokemon_id == 7:  # Squirtle
            fallback_moves = [
                {"move": "tackle", "level_learned_at": 1, "method": "level-up"},
                {"move": "tail-whip", "level_learned_at": 1, "method": "level-up"},
                {"move": "water-gun", "level_learned_at": 7, "method": "level-up"},
                {"move": "withdraw", "level_learned_at": 10, "method": "level-up"}
            ]
        elif pokemon_id == 25:  # Pikachu
            fallback_moves = [
                {"move": "thunder-shock", "level_learned_at": 1, "method": "level-up"},
                {"move": "growl", "level_learned_at": 1, "method": "level-up"},
                {"move": "tail-whip", "level_learned_at": 6, "method": "level-up"},
                {"move": "quick-attack", "level_learned_at": 8, "method": "level-up"}
            ]
        
        # Filter by level
        valid_fallback = [move for move in fallback_moves if move['level_learned_at'] <= level]
        
        # Enhance fallback moves with complete information
        enhanced_fallback = []
        for move in valid_fallback:
            enhanced_move = self.enhance_move_with_info(move)
            enhanced_fallback.append(enhanced_move)
        
        return enhanced_fallback
    
    def get_ev_yield(self, pokemon_id: int) -> Dict[str, int]:
        """Get EV yield for a Pokemon from evYield.json"""
        try:
            with open('assets/variable.jsons/evYield.json', 'r') as f:
                ev_data = json.load(f)
            return ev_data.get(str(pokemon_id), {})
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def get_pokemon_info(self, pokemon_id: int) -> Dict:
        """Get Pokemon info - now returns the entire Pokemon data from poke.json"""
        return self.get_pokemon_by_id(pokemon_id) or {}
    
    def get_pokemon_weight(self, pokemon_id: int) -> float:
        """Get Pokemon weight in kg (for Heavy Ball calculations)"""
        pokemon_data = self.get_pokemon_by_id(pokemon_id)
        if pokemon_data:
            return pokemon_data.get('weight', 6.9)
        return 6.9
    
    def calculate_catch_rate(self, pokemon_id: int, pokemon_level: int, pokeball_modifier: float) -> float:
        """Calculate catch rate based on Pokemon, level, and pokeball (basic version)"""
        pokemon_data = self.get_pokemon_by_id(pokemon_id)
        base_catch_rate = pokemon_data.get('capture_rate', 255) if pokemon_data else 255
        
        # Base catch rate formula (simplified)
        level_modifier = max(0.1, 1 - (pokemon_level / 100) * 0.5)
        final_rate = (base_catch_rate * pokeball_modifier * level_modifier) / 255
        
        return min(1.0, final_rate)
    
    def calculate_enhanced_catch_rate(self, pokemon: Dict, pokeball_data: Dict, activity_type: Optional[str] = None) -> float:
        """Calculate enhanced catch rate with special pokeball effects"""
        pokemon_id = pokemon['id']
        pokemon_level = pokemon['level']
        pokemon_types = [t.lower() for t in pokemon.get('types', [])]
        
        pokemon_data = self.get_pokemon_by_id(pokemon_id)
        base_catch_rate = pokemon_data.get('capture_rate', 255) if pokemon_data else 255
        
        level_modifier = max(0.1, 1 - (pokemon_level / 100) * 0.5)
        pokeball_modifier = self.get_pokeball_modifier(pokemon, pokeball_data)
        
        # Apply 5x multiplier for hunt and fishing activities
        activity_multiplier = 5.0 if activity_type in ['hunt', 'fishing'] else 1.0
        
        final_rate = (base_catch_rate * pokeball_modifier * level_modifier * activity_multiplier) / 255
        return min(1.0, final_rate)
    
    def get_pokeball_modifier(self, pokemon: Dict, pokeball_data: Dict) -> float:
        """Get pokeball modifier based on special conditions"""
        pokeball_name = pokeball_data['name']
        pokemon_types = pokemon.get('types', [])
        pokemon_level = pokemon['level']
        pokemon_id = pokemon['id']
        
        # Handle special pokeball effects
        if pokeball_name == "Master":
            return 999.0
        elif pokeball_name == "Regular":
            return 1.0
        elif pokeball_name == "Great":
            return 1.5
        elif pokeball_name == "Ultra":
            return 2.0
        elif pokeball_name == "Repeat":
            return 3.0
        elif pokeball_name == "Nest":
            if pokemon_level <= 20:
                return 3.0
            elif pokemon_level <= 40:
                return 2.0
            else:
                return 1.0
        elif pokeball_name == "Dusk":
            if "dark" in pokemon_types:
                return 3.5
            else:
                return 1.0
        elif pokeball_name == "Quick":
            return 2.5
        elif pokeball_name == "Net":
            if "bug" in pokemon_types or "water" in pokemon_types:
                return 3.0
            else:
                return 1.0
        elif pokeball_name == "Lure":
            if "water" in pokemon_types:
                return 3.0
            else:
                return 1.0
        elif pokeball_name == "Moon":
            if "fairy" in pokemon_types:
                return 4.0
            else:
                return 1.0
        elif pokeball_name == "Heavy":
            weight = self.get_pokemon_weight(pokemon_id)
            if weight >= 200:
                return 8.0
            elif weight >= 100:
                return 4.0
            elif weight >= 50:
                return 2.0
            else:
                return 1.0
        elif pokeball_name == "Fast":
            base_stats = pokemon.get('base_stats', {})
            base_speed = base_stats.get('speed', 0)
            if base_speed >= 100:
                return 4.0
            else:
                return 1.0
        elif pokeball_name == "Sport":
            if "bug" in pokemon_types:
                return 4.0
            else:
                return 1.0
        else:
            return 1.0
    
    def calculate_stats(self, pokemon_data: Dict, level: int, ivs: Dict[str, int], evs: Dict[str, int], nature: str) -> Dict[str, int]:
        """Calculate actual stats based on base stats, IVs, EVs, level, and nature"""
        base_stats = pokemon_data.get('base_stats', {})
        calculated_stats = {}
        
        nature_data = self.natures.get(nature, {'increase': None, 'decrease': None})
        
        # Map new stat names to old stat names for compatibility
        stat_mapping = {
            'HP': 'hp',
            'Attack': 'atk',
            'Defense': 'def',
            'Sp. Attack': 'spa',
            'Sp. Defense': 'spd',
            'Speed': 'speed'
        }
        
        for stat, base_key in stat_mapping.items():
            base = base_stats.get(base_key, 1)
            iv = ivs.get(stat, 0)
            ev = evs.get(stat, 0)
            
            if stat == 'HP':
                calculated_stats[stat] = int(((2 * base + iv + ev/4) * level / 100) + level + 10)
            else:
                stat_value = int(((2 * base + iv + ev/4) * level / 100) + 5)
                
                # Apply nature modifier
                if nature_data['increase'] == stat:
                    stat_value = int(stat_value * 1.1)
                elif nature_data['decrease'] == stat:
                    stat_value = int(stat_value * 0.9)
                
                calculated_stats[stat] = stat_value
        
        return calculated_stats
    
    def create_pokemon(self, pokemon_id: int, level: int) -> Dict:
        """Create a complete Pokemon object with all stats and moves"""
        # Get Pokemon data from poke.json
        pokemon_data = self.get_pokemon_by_id(pokemon_id)
        
        if not pokemon_data:
            raise ValueError(f"Pokemon with ID {pokemon_id} not found")
        
        # Generate random attributes
        ivs = self.generate_random_ivs()
        evs = {stat: 0 for stat in ['HP', 'Attack', 'Defense', 'Sp. Attack', 'Sp. Defense', 'Speed']}
        nature = self.get_random_nature()
        
        # Calculate actual stats
        calculated_stats = self.calculate_stats(pokemon_data, level, ivs, evs, nature)
        
        # Get moves and enhance them with complete information
        moves = self.get_moves_for_level(pokemon_id, level)
        
        # Ensure we have at least some moves
        if not moves:
            moves = [{"move": "tackle", "level_learned_at": 1, "method": "level-up"}]
        
        # Enhance each move with complete information from moveInfo.json
        enhanced_moves = []
        for move in moves:
            enhanced_move = self.enhance_move_with_info(move)
            enhanced_moves.append(enhanced_move)
        
        moves = enhanced_moves
        
        # Create complete Pokemon object
        pokemon = {
            'id': pokemon_id,
            'uuid': str(uuid.uuid4()),
            'name': pokemon_data.get('name', 'Unknown'),
            'level': level,
            'types': pokemon_data.get('types', []),
            'base_stats': pokemon_data.get('base_stats', {}),
            'calculated_stats': calculated_stats,
            'ivs': ivs,
            'evs': evs,
            'nature': nature,
            'moves': moves,
            'species': pokemon_data.get('name', ''),
            'description': pokemon_data.get('description', ''),
            'image': f"assets/images/{pokemon_id}.png",  # Default image path, should be updated based on shiny status
            'evolution': pokemon_data.get('evolution', {}),
            'hp': calculated_stats.get('HP', 1),
            'max_hp': calculated_stats.get('HP', 1),
            'status': None,
            'experience': 0,
            'captured_with': None,
            'caught_date': None,
            'trainer_id': None,
            'capture_rate': pokemon_data.get('capture_rate', 255),
            'base_happiness': pokemon_data.get('base_happiness', 50),
            'gender_rate': pokemon_data.get('gender_rate', 1),
            'growth_rate': pokemon_data.get('growth_rate', {}),
            'is_legendary': pokemon_data.get('is_legendary', False),
            'is_mythical': pokemon_data.get('is_mythical', False),
            'wild_range': pokemon_data.get('wild_range', {'min': 1, 'max': 50}),
        }
        
        return pokemon
    
    def format_pokemon_display(self, pokemon: Dict) -> str:
        """Format Pokemon for display in Discord embed"""
        type_str = '/'.join(pokemon.get('types', []))
        stats = pokemon.get('calculated_stats', {})
        
        stats_str = '\n'.join([
            f"❤️ HP: {stats.get('HP', 0)}",
            f"⚔️ Attack: {stats.get('Attack', 0)}",
            f"🛡️ Defense: {stats.get('Defense', 0)}",
            f"✨ Sp. Attack: {stats.get('Sp. Attack', 0)}",
            f"🛡️ Sp. Defense: {stats.get('Sp. Defense', 0)}",
            f"🏃 Speed: {stats.get('Speed', 0)}"
        ])
        
        moves_list = pokemon.get('moves', [])
        moves_str = ', '.join([move.get('move', 'Unknown').replace('-', ' ').title() for move in moves_list[:4]])
        
        return f"""
**{pokemon['name'].title()}** | Level {pokemon['level']}
Type: {type_str.title()}
Nature: {pokemon['nature']}

**Stats:**
{stats_str}

**Moves:**
{moves_str}
        """

    @staticmethod
    def normalize_move_name(move_name: str) -> str:
        """Normalize move name to a consistent format"""
        return move_name.replace(' ', '-').lower()

    def enhance_move_with_info(self, move: Dict) -> Dict:
        """Enhance a move dictionary with complete information from moveInfo.json"""
        move_name = move.get('move', move.get('name', ''))
        if not move_name:
            return move
        
        # Try to find move info using various name variants
        move_info = None
        name_variants = [
            move_name,
            move_name.title(),
            move_name.lower(),
            move_name.replace('-', ' '),
            move_name.replace(' ', '-'),
            move_name.replace('_', ' '),
            move_name.replace('_', '-'),
            self.normalize_move_name(move_name),
            move_name.replace('-', ' ').title(),
            move_name.lower().replace(' ', '-')
        ]
        
        for variant in name_variants:
            if variant in self.move_lookup:
                move_info = self.move_lookup[variant]
                break
        
        if move_info:
            # Enhance the move with complete information
            enhanced_move = move.copy()
            enhanced_move.update({
                'name': move_info.get('name', move_name),
                'type': move_info.get('type', 'Normal'),
                'category': move_info.get('category', 'Physical'),
                'power': move_info.get('power', 0),
                'accuracy': move_info.get('accuracy', 100),
                'pp': move_info.get('pp', 1),
                'effect': move_info.get('effect', '')
            })
            # Keep the original move name if it exists
            if 'move' not in enhanced_move:
                enhanced_move['move'] = move_name
            return enhanced_move
        else:
            # If no move info found, add default values
            enhanced_move = move.copy()
            enhanced_move.update({
                'name': move_name,
                'type': 'Normal',
                'category': 'Physical',
                'power': 0,
                'accuracy': 100,
                'pp': 1,
                'effect': 'No information available.'
            })
            if 'move' not in enhanced_move:
                enhanced_move['move'] = move_name
            return enhanced_move

    # TM-related functions
    def get_tm_data(self) -> Dict:
        """Get all TM data"""
        return self.tm_data
    
    def get_tm_by_id(self, tm_id: str) -> Optional[Dict]:
        """Get TM data by ID (e.g., 'tm1', 'tm2')"""
        return self.tm_data.get(tm_id)
    
    def get_tms_by_type(self, pokemon_type: str) -> List[Tuple[str, Dict]]:
        """Get all TMs of a specific type"""
        tms_of_type = []
        for tm_id, tm_data in self.tm_data.items():
            if tm_data.get('type') == pokemon_type:
                tms_of_type.append((tm_id, tm_data))
        return tms_of_type
    
    def calculate_tm_price(self, tm_data: Dict) -> int:
        """Calculate TM price based on power with higher pricing"""
        power = tm_data.get('power', 0)
        
        # Base price calculation with increased prices
        if power is None or power == 0:
            # Status moves or moves with no power
            base_price = 2500
        else:
            # Price is proportional to power with higher multiplier
            # Formula: (power * 25) + 1000, with minimum 2500
            base_price = max(2500, (power * 25) + 1000)
        
        return base_price
    
    def get_tm_types(self) -> List[str]:
        """Get all available Pokemon types"""
        return self.pokemon_types.copy()
    
    def get_tm_info_display(self, tm_id: str, tm_data: Dict) -> str:
        """Get formatted TM info for display"""
        tm_number = tm_id.replace('tm', '')
        name = tm_data.get('name', 'Unknown')
        type_name = tm_data.get('type', 'Unknown')
        category = tm_data.get('category', 'Unknown')
        power = tm_data.get('power', 0)
        accuracy = tm_data.get('accuracy', 0)
        price = self.calculate_tm_price(tm_data)
        
        power_str = str(power) if power and power > 0 else "—"
        accuracy_str = f"{accuracy}%" if accuracy else "—"
        
        return f"<b>TM{tm_number} - {name}</b>\n<b>Type:</b> {type_name} | <b>Category:</b> {category}\n<b>Power:</b> {power_str} | <b>Accuracy:</b> {accuracy_str}\n<b>Price:</b> {price} 💵"
    
    def get_paginated_tms_by_type(self, pokemon_type: str, page: int = 0, per_page: int = 10) -> Tuple[List[Tuple[str, Dict]], int, int]:
        """Get paginated TMs of a specific type"""
        all_tms = self.get_tms_by_type(pokemon_type)
        total_tms = len(all_tms)
        total_pages = (total_tms - 1) // per_page + 1 if total_tms > 0 else 1
        
        start_idx = page * per_page
        end_idx = start_idx + per_page
        
        paginated_tms = all_tms[start_idx:end_idx]
        
        return paginated_tms, total_pages, total_tms
    
    def get_pokemon_that_can_learn_tm(self, tm_id: str) -> List[Dict]:
        """Get list of Pokemon that can learn a specific TM"""
        if not self.poke_moves or not isinstance(self.poke_moves, list):
            return []
        
        # Get the TM move name
        tm_data = self.get_tm_by_id(tm_id)
        if not tm_data:
            return []
        
        tm_move_name = PokemonUtils.normalize_move_name(tm_data.get('name', ''))
        compatible_pokemon = []
        
        # Check all Pokemon
        for pokemon_id in range(1, len(self.poke_moves) + 1):
            pokemon_index = pokemon_id - 1
            
            if pokemon_index < 0 or pokemon_index >= len(self.poke_moves):
                continue
            
            pokemon_moves = self.poke_moves[pokemon_index]
            
            if not isinstance(pokemon_moves, list):
                continue
            
            # Check if this Pokemon can learn the TM move via machine method
            can_learn = False
            for move_data in pokemon_moves:
                if not isinstance(move_data, dict):
                    continue
                
                method = move_data.get('method')
                move_name = move_data.get('move')
                
                if method == 'machine' and move_name:
                    normalized_move_name = PokemonUtils.normalize_move_name(move_name)
                    if normalized_move_name == tm_move_name:
                        can_learn = True
                        break
            
            if can_learn:
                # Get Pokemon data
                pokemon_data = self.get_pokemon_by_id(pokemon_id)
                if pokemon_data:
                    compatible_pokemon.append({
                        'id': pokemon_id,
                        'name': pokemon_data.get('name', f'Pokemon {pokemon_id}'),
                        'types': pokemon_data.get('types', [])
                    })
        
        return compatible_pokemon
    
    def get_user_pokemon_that_can_learn_tm(self, tm_id: str, user_pokemon: List[Dict]) -> List[Dict]:
        """Get user's Pokemon that can learn a specific TM"""
        compatible_pokemon_ids = {poke['id'] for poke in self.get_pokemon_that_can_learn_tm(tm_id)}
        
        user_compatible = []
        for pokemon in user_pokemon:
            if pokemon.get('id') in compatible_pokemon_ids:
                user_compatible.append(pokemon)
        
        return user_compatible

    def update_pokemon_image_path(self, pokemon: Dict) -> None:
        """Update Pokemon image path based on shiny status"""
        pokemon_id = pokemon.get('id')
        is_shiny = pokemon.get('is_shiny', False)
        
        if not pokemon_id:
            return
        
        if is_shiny:
            pokemon['image'] = f"shiny_pokemon/{pokemon_id}.png"
        else:
            pokemon['image'] = f"assets/images/{pokemon_id}.png"

    def is_legendary_or_mythical(self, pokemon_id: int) -> bool:
        """Check if a Pokemon is legendary or mythical."""
        pokemon_data = self.get_pokemon_by_id(pokemon_id)
        if not pokemon_data:
            return False
        return pokemon_data.get('is_legendary', False) or pokemon_data.get('is_mythical', False)

    def validate_gym_team(self, team: List[Dict]) -> Tuple[bool, str]:
        """Validate a user's team for gym battle rules."""
        if not team:
            return False, "Your team is empty!"

        for pokemon in team:
            if self.is_legendary_or_mythical(pokemon['id']):
                return False, f"{pokemon['name']} is a legendary/mythical Pokémon and is not allowed."
        
        return True, "Team is valid."

    def get_gym_leader_team(self, leader_name: str) -> Optional[List[Dict]]:
        """Get a gym leader's team by name."""
        leader_data = self.gym_leaders.get(leader_name.lower())
        if not leader_data:
            return None

        team_data = leader_data.get("team", [])
        full_team = []
        for poke_info in team_data:
            pokemon = self.create_pokemon(
                pokemon_id=poke_info["id"],
                level=poke_info["level"]
            )
            if pokemon:
                full_team.append(pokemon)

        return full_team

# Global instance for easy access
pokemon_utils = PokemonUtils()