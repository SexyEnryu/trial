import json

# Cache for poke.json data
_poke_json_cache = None

def get_pokemon_growth_rate(pokemon_id):
    """Fetches the growth rate for a given Pokémon ID from poke.json."""
    global _poke_json_cache
    if _poke_json_cache is None:
        try:
            with open('poke.json', 'r', encoding='utf-8') as f:
                _poke_json_cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # Fallback to an empty list if file is missing or corrupt
            _poke_json_cache = []

    for p in _poke_json_cache:
        if p.get('id') == pokemon_id:
            gr = p.get('growth_rate', 'Medium Fast')
            # The value can be a string or a dict {"name": "Medium Fast", ...}
            if isinstance(gr, dict):
                gr = gr.get('name', 'Medium Fast')
            if not isinstance(gr, str):
                gr = 'Medium Fast'
            return gr.replace(" ", "").lower()
    return 'mediumfast' # Default growth rate

def get_exp_for_level(level: int, growth_rate: str = 'mediumfast') -> int:
    """Calculates the total experience required to reach a specific level based on growth rate."""
    if level <= 1:
        return 0

    g = growth_rate.lower().replace(" ", "")

    if g == 'slow':
        return (5 * level ** 3) // 4
    elif g == 'fast':
        return (4 * level ** 3) // 5
    elif g == 'mediumslow':
        return int((1.2 * level ** 3) - (15 * level ** 2) + (100 * level) - 140)
    elif g == 'erratic':
        if level <= 50:
            return (level ** 3 * (100 - level)) // 50
        elif level <= 68:
            return (level ** 3 * (150 - level)) // 100
        elif level <= 98:
            return (level ** 3 * ((1911 - 10 * level) // 3)) // 500
        else: # level <= 100
            return (level ** 3 * (160 - level)) // 100
    elif g == 'fluctuating':
        if level <= 15:
            return level ** 3 * (((level + 1) // 3) + 24) // 50
        elif level <= 36:
            return level ** 3 * (level + 14) // 50
        else: # level <= 100
            return level ** 3 * ((level // 2) + 32) // 50
    else:  # Default to 'Medium Fast'
        return level ** 3

def create_exp_bar(current_exp: int, level: int, growth_rate: str) -> (str, int):
    """Creates a text-based EXP bar and calculates EXP to next level."""
    if level >= 100:
        return "██████████", 0

    exp_for_current_level = get_exp_for_level(level, growth_rate)
    exp_for_next_level = get_exp_for_level(level + 1, growth_rate)

    total_exp_in_level = exp_for_next_level - exp_for_current_level
    current_exp_in_level = current_exp - exp_for_current_level

    if total_exp_in_level == 0:
        progress_percentage = 100
    else:
        progress_percentage = (current_exp_in_level / total_exp_in_level) * 100

    filled_blocks = int(progress_percentage / 10)
    empty_blocks = 10 - filled_blocks

    bar = '█' * filled_blocks + '▒' * empty_blocks
    
    exp_to_next_lv = exp_for_next_level - current_exp
    return bar, exp_to_next_lv
