import random
import json
from typing import Dict, Any, Tuple
import os

# Get the absolute path of the directory containing this file
_current_dir = os.path.dirname(os.path.abspath(__file__))

# Load type effectiveness and move data using absolute paths
with open(os.path.join(_current_dir, 'assets', 'variable.jsons', 'damages.json'), 'r') as f:
    TYPE_CHART = json.load(f)
with open(os.path.join(_current_dir, 'damaging_moves.json'), 'r') as f:
    MOVES = json.load(f)
with open(os.path.join(_current_dir, 'poke.json'), 'r') as f:
    POKEDEX = json.load(f)

# --- Battle Logic Functions ---

# Canonical move name lookup for robust matching
CANONICAL_MOVE_LOOKUP = {}
def canonicalize_move_name(name: str) -> str:
    return name.lower().replace('-', '').replace(' ', '')
for key in MOVES.keys():
    CANONICAL_MOVE_LOOKUP[canonicalize_move_name(key)] = key

def normalize_move_name(move_name: str) -> str:
    """
    Normalize move names to match keys in MOVES dict using canonical lookup.
    """
    if not isinstance(move_name, str):
        return ''
    canon = canonicalize_move_name(move_name)
    return CANONICAL_MOVE_LOOKUP.get(canon, move_name)

def get_turn_order(poke1: Dict, poke2: Dict) -> Tuple[int, int]:
    spd1 = poke1.get('calculated_stats', {}).get('Speed', 0)
    spd2 = poke2.get('calculated_stats', {}).get('Speed', 0)
    if spd1 > spd2:
        return (0, 1)
    elif spd2 > spd1:
        return (1, 0)
    else:
        return (random.choice([(0, 1), (1, 0)]))

def get_type_list(poke: Dict) -> list:
    # Try to get types from poke dict, fallback to POKEDEX
    # Add robust error handling to prevent intermittent failures
    try:
        if not isinstance(poke, dict):
            print(f"[DEBUG] get_type_list: Invalid poke type: {type(poke)}")
            return ['normal']
        
        name = poke.get('name', 'Unknown')
        print(f"[DEBUG] get_type_list: {name} -> ", end='')
        
        types = []
        
        # First priority: check if poke has 'types' field (for transformed Pokemon like Arceus with plates)
        if 'types' in poke and poke['types']:
            types = poke['types']
        # Second priority: check if poke has 'type' field (legacy)
        elif 'type' in poke and poke['type']:
            types = poke['type']
        else:
            # Fallback to POKEDEX lookup (POKEDEX is a list, not a dict)
            name_lower = name.lower()
            for pokemon_data in POKEDEX:
                if isinstance(pokemon_data, dict) and pokemon_data.get('name', '').lower() == name_lower:
                    types = pokemon_data.get('types', [])
                    break
            
            if not types:
                types = ['normal']  # Default fallback
        
        # Ensure types is a list and contains valid strings
        if not isinstance(types, list):
            types = [types] if types else ['normal']
        
        # Filter out any non-string types and ensure lowercase
        result = []
        for t in types:
            if isinstance(t, str) and t.strip():
                result.append(t.lower().strip())
        
        if not result:
            result = ['normal']
        
        print(f"{result}")
        return result
        
    except Exception as e:
        print(f"[ERROR] get_type_list: Exception occurred: {e}")
        print(f"[ERROR] get_type_list: Fallback to normal type")
        return ['normal']

def get_type_effectiveness(move_type: str, defender_types: list, defender_name: str = '', attacker=None, move=None, defender=None) -> Tuple[float, str]:
    # Defensive: if move_type is a list, use the first element
    if isinstance(move_type, list):
        move_type = move_type[0] if move_type else 'normal'
    move_type = move_type.lower()  # Ensure lowercase for lookup
    defender_types = [t.lower() for t in defender_types]  # Ensure lowercase
    # --- ADDED DEBUG ---
    print(f"[DEBUG] (IMMUNITY CHECK) Attacker: {getattr(attacker, 'get', lambda x: None)('name') if attacker else None}, Move: {getattr(move, 'get', lambda x: None)('name') if move else None}, Move type: {move_type}, Defender: {getattr(defender, 'get', lambda x: None)('name') if defender else defender_name}, Defender types: {defender_types}")
    # --- END ADDED DEBUG ---
    multiplier = 1.0
    effectiveness_msg = ''
    for dtype in defender_types:
        eff = TYPE_CHART.get(move_type, {}).get(dtype, 1.0)
        print(f"[DEBUG] {move_type} vs {dtype}: {eff}")
        if eff == 0:
            multiplier = 0
            break
        multiplier *= eff
    print(f"[DEBUG] Final multiplier: {multiplier}")
    if multiplier == 0:
        # --- ADDED DEBUG ---
        print(f"[DEBUG] (IMMUNITY TRIGGERED) {move_type} vs {defender_types} (Defender: {getattr(defender, 'get', lambda x: None)('name') if defender else defender_name})")
        # --- END ADDED DEBUG ---
        if defender_name:
            effectiveness_msg = f"It doesn't affect {defender_name.title()}!"
        else:
            effectiveness_msg = "It doesn't affect the opponent!"
    elif multiplier < 1:
        effectiveness_msg = "It's not very effective."
    elif multiplier > 1:
        effectiveness_msg = "It's super effective!"
    # No message for 1x effectiveness
    print(f"[DEBUG] Effectiveness message: '{effectiveness_msg}'")
    return multiplier, effectiveness_msg

def is_crit() -> bool:
    return random.randint(1, 16) == 1

def get_damage_variance() -> float:
    return random.uniform(0.85, 1.0)

def calculate_damage(attacker: Dict, defender: Dict, move: Dict) -> Tuple[int, bool, float, str]:
    
    # Get stats with better fallback handling
    level = attacker.get('level', 50)
    atk_stat = attacker.get('calculated_stats', {}).get('Attack', attacker.get('stats', {}).get('attack', 50))
    # Fix: Use correct key for special-attack in stats fallback
    sp_atk_stat = attacker.get('calculated_stats', {}).get('Sp. Atk', attacker.get('stats', {}).get('special-attack', 50))
    def_stat = defender.get('calculated_stats', {}).get('Defense', defender.get('stats', {}).get('defense', 50))
    # Fix: Use correct key for special-defense in stats fallback  
    sp_def_stat = defender.get('calculated_stats', {}).get('Sp. Def', defender.get('stats', {}).get('special-defense', 50))
    
    print(f"[DEBUG] calculate_damage: Attacker level={level}, stats: Atk={atk_stat}, SpAtk={sp_atk_stat}")
    print(f"[DEBUG] calculate_damage: Defender stats: Def={def_stat}, SpDef={sp_def_stat}")
    
    move_name = move.get('name')
    if not isinstance(move_name, str):
        return 1, False, 1.0, ''
    
    # Use robust normalization for move lookup
    move_key = normalize_move_name(move_name)
    move_data = MOVES.get(move_key)
    
    if not move_data:
        # Try alternative lookups for move data
        alternatives = [
            move_name,
            move_name.title(),
            move_name.lower(),
            move_name.replace('-', ' '),
            move_name.replace(' ', '-'),
            move_name.replace('_', ' '),
            move_name.replace('_', '-'),
        ]
        
        for alt_name in alternatives:
            alt_key = normalize_move_name(alt_name)
            if alt_key in MOVES:
                move_data = MOVES[alt_key]
                break
        
        if not move_data:
            print(f"[DEBUG] Move '{move_name}' not found - using Tackle fallback")
            # Use a proper fallback move instead of returning 1 damage
            move_data = {
                'name': 'Tackle',
                'type': 'normal',
                'category': 'physical',
                'power': 40,
                'accuracy': 100,
                'pp': 35,
                'effect': 'Fallback move when original move not found in database'
            }
    
    power = move_data.get('power', 50)
    accuracy = move_data.get('accuracy', 100)
    if accuracy is None:
        accuracy = 100
    
    # If power is None or 0, it might be a status move, give it minimal damage
    if power is None or power == 0:
        power = 10
    
    print(f"[DEBUG] calculate_damage: Move power={power}, accuracy={accuracy}")
    
    # Check if the move has a custom type (e.g., from Arceus plate transformation)
    # Prioritize the Pokemon's move type over the global database type
    move_type = move.get('type', move_data.get('type', 'normal'))
    if isinstance(move_type, list):
        move_type = move_type[0] if move_type else 'normal'
    category = move_data.get('category', 'physical')
    
    print(f"[DEBUG] calculate_damage: Move type={move_type}, category={category}")
    
    # Accuracy check
    if random.randint(1, 100) > accuracy:
        return 0, False, 1.0, ''  # Missed
    
    # STAB
    attacker_types = get_type_list(attacker)
    stab = 1.5 if move_type.lower() in [t.lower() for t in attacker_types] else 1.0
    print(f"[DEBUG] calculate_damage: Attacker types={attacker_types}, STAB={stab}")
    
    # Type effectiveness
    defender_types = get_type_list(defender)
    defender_name = defender.get('name') or ''
    type_mult, eff_msg = get_type_effectiveness(move_type, defender_types, defender_name, attacker, move, defender)
    print(f"[DEBUG] calculate_damage: Defender types={defender_types}, type_mult={type_mult}")
    
    # Crit
    crit = is_crit()
    crit_mult = 1.5 if crit else 1.0
    print(f"[DEBUG] calculate_damage: Crit={crit}, crit_mult={crit_mult}")
    
    # Damage variance
    variance = get_damage_variance()
    print(f"[DEBUG] calculate_damage: Variance={variance}")
    
    # Stat selection with validation
    if category.lower() == 'special':
        atk = max(1, sp_atk_stat)  # Ensure minimum of 1
        defense = max(1, sp_def_stat)
    else:
        atk = max(1, atk_stat)
        defense = max(1, def_stat)
    
    print(f"[DEBUG] calculate_damage: Using stats - Atk={atk}, Def={defense}")
    
    # Calculate damage using the standard Pokemon damage formula
    # Ensure all divisions are floating point
    base_damage = (((2.0 * float(level) / 5.0 + 2.0) * float(power) * float(atk) / float(defense)) / 50.0) + 2.0
    print(f"[DEBUG] calculate_damage: Base damage={base_damage}")
    
    # Apply modifiers
    final_damage = int(base_damage * stab * type_mult * crit_mult * variance)
    print(f"[DEBUG] calculate_damage: Final damage before min check={final_damage}")
    
    # Ensure minimum damage of 1 if the attack hits, but only if not immune
    if type_mult > 0:
        final_damage = max(1, final_damage)
    
    print(f"[DEBUG] calculate_damage: Final damage after min check={final_damage}")
    
    return final_damage, crit, type_mult, eff_msg

def apply_move(attacker: Dict, defender: Dict, move: Dict) -> Dict:
    move_name = move.get('name')
    if not isinstance(move_name, str):
        print(f"[DEBUG] apply_move: Invalid move_name type: {type(move_name)}, value: {move_name}")
        return {"damage": 0, "missed": True}
    # Use robust normalization to match keys in MOVES
    move_key = normalize_move_name(move_name)
    move_data = MOVES.get(move_key)
    # Debug info for move lookup
    print(f"DEBUG apply_move: move_name='{move_name}', move_key='{move_key}', found={move_data is not None}")
    if not move_data:
        # Try alternative variants
        alt_names = [
            move_name.title(),
            move_name.lower(),
            move_name.replace('-', ' '),
            move_name.replace(' ', '-'),
            move_name.replace('_', ' '),
            move_name.replace('_', '-'),
        ]
        for alt in alt_names:
            if alt in MOVES:
                move_data = MOVES[alt]
                print(f"[DEBUG] apply_move: Found move using alt name '{alt}'")
                break
    if not move_data:
        print(f"[WARNING] apply_move: Move '{move_name}' not found in MOVES! Available keys sample: {list(MOVES.keys())[:10]}")
        return {"damage": 0, "missed": True}
    else:
        print(f"  move_data: {move_data}")

    # Accuracy check
    accuracy = move_data.get('accuracy', 100)
    if accuracy is None:
        accuracy = 100
    accuracy_roll = random.randint(1, 100)
    print(f"[DEBUG] apply_move: Accuracy check - move_accuracy={accuracy}, roll={accuracy_roll}")
    if accuracy_roll > accuracy:
        print(f"[DEBUG] apply_move: Move missed due to accuracy!")
        return {"damage": 0, "missed": True}
    
    print(f"[DEBUG] apply_move: Move hit, calculating damage...")
    damage, crit, type_mult, eff_msg = calculate_damage(attacker, defender, move)
    
    result = {
        "damage": damage,
        "crit": crit,
        "effectiveness": eff_msg if eff_msg else None,
        "missed": False
    }
    
    print(f"[DEBUG] apply_move: Final result = {result}")
    return result

def check_faint(pokemon: Dict) -> bool:
    return pokemon.get('hp', 0) <= 0 

# Utility: Print the type chart for debugging

def print_type_chart():
    import pprint
    pprint.pprint(TYPE_CHART) 