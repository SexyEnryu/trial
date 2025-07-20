import json
import random
import math

# Removed pokedex.json loading and all functions that use pokedex

natures = [
    "Hardy",
    "Lonely",
    "Brave",
    "Adamant",
    "Naughty",
    "Bold",
    "Docile",
    "Relaxed",
    "Impish",
    "Lax",
    "Timid",
    "Hasty",
    "Serious",
    "Jolly",
    "Naive",
    "Modest",
    "Mild",
    "Quiet",
    "Bashful",
    "Rash",
    "Calm",
    "Gentle",
    "Sassy",
    "Careful",
    "Quirky"
]

def randomNature():
    return random.choice(natures)

def pbar(percentage):
    total_width = 10
    filled_width = round((percentage / 100) * total_width)
    # Always show at least 1 filled block if HP > 0
    if percentage > 0 and filled_width == 0:
        filled_width = 1
    filled = '█'
    unfilled = '▒'
    return filled * filled_width + unfilled * (total_width - filled_width)

def calculate_total_hp(base_hp, iv, ev, level):
    return int((((2 * base_hp + iv + (ev // 4)) * level) / 100) + level + 10)

def random_move(poke_id, level):
    with open('./assets/variableJsons/pokeMoves.json', encoding='utf-8') as f:
        moves = json.load(f)[poke_id - 1]
    move_names = [move['move'] for move in moves if move['level_learned_at'] <= level]
    return random.sample(move_names, min(4, len(move_names)))

def calculate_total_stat(iv, ev, base, level, nature, stat, natures_dict):
    final_stat = (((2 * base) + iv + (ev / 4)) * level) / 100 + 5
    nature_stat = natures_dict[nature]
    if stat in ['Attack', 'Defense', 'Sp. Attack', 'Sp. Defense', 'Speed']:
        if nature_stat['increase'] == stat:
            final_stat *= 1.1
            return {'stat': math.floor(final_stat), 'operation': '+'}
        elif nature_stat['decrease'] == stat:
            final_stat *= 0.9
            return {'stat': math.floor(final_stat), 'operation': '-'}
    return {'stat': math.floor(final_stat), 'operation': None}

def user_level_calc(exp):
    level = 0
    power = 0
    while exp >= (3 ** power) * 30:
        power += 1
    if power <= 9:
        level = power + 1
    else:
        level = ((power - 9) // 3) + 10
    next_level_exp = (3 ** power) * 30
    remaining_exp = next_level_exp - exp
    return level, remaining_exp

def calculate_escape_chance(fleeing_pokemon_speed, opposing_pokemon_speed):
    return ((fleeing_pokemon_speed * 32) / (opposing_pokemon_speed + 30) + 30)

def damage_calculator(move_id, attacker, defender, moves, calculate_total_stat_func, damages_path='./assets/variableJsons/damages.json'):
    with open(damages_path, 'r', encoding='utf-8') as f:
        type_effectiveness = json.load(f)
    move_info = next((move for move in moves if move['id'] == move_id), None)
    if not move_info:
        raise ValueError("Move not found")
    if move_info['isPhysical']:
        attack = calculate_total_stat_func(
            attacker['ivs']['atk'], attacker['evs']['atk'], attacker['base']['Attack'],
            attacker['level'], attacker['nature'], 'Attack'
        )['stat']
        defence = calculate_total_stat_func(
            defender['ivs']['def'], defender['evs']['def'], defender['base']['Defense'],
            defender['level'], defender['nature'], 'Defense'
        )['stat']
    else:
        attack = calculate_total_stat_func(
            attacker['ivs']['spa'], attacker['evs']['spa'], attacker['base']['Sp. Attack'],
            attacker['level'], attacker['nature'], 'Sp. Atk'
        )['stat']
        defence = calculate_total_stat_func(
            defender['ivs']['spd'], defender['evs']['spd'], defender['base']['Sp. Defense'],
            defender['level'], defender['nature'], 'Sp. Def'
        )['stat']
    move_accuracy = move_info['accuracy']
    move_power = move_info['power']
    accuracy = random.randint(1, 100)
    miss = move_accuracy < accuracy
    critical = random.randint(1, 24)
    rand_factor = random.randint(85, 100) / 100.0
    multiplier_crit = 1.5 if critical == 24 else 1
    effectiveness = 1
    for defender_type in defender['type']:
        effectiveness *= type_effectiveness[move_info['type'].lower()][defender_type.lower()]
    damage = ((((((2 * attacker['level']) / 5) + 2) * move_power * (attack / defence)) + 2) / 50) * multiplier_crit * rand_factor * effectiveness
    immunity = effectiveness == 0
    critical_trf = multiplier_crit == 1.5
    return {
        'isMissed': miss,
        'damage': damage,
        'effectiveness': effectiveness,
        'immunity': immunity,
        'critical': critical_trf
    }

def catch_rate(poke_info, ball, is_caught_before, battle, user_current_poke, weight, registered_pokemons, get_base_stat_func):
    current_hp = poke_info['currentHp']
    total_hp = poke_info['hp']
    data = poke_info[str(poke_info['pokedexID'])]
    pokemon_catch_rate = data['capture_rate']
    catch_rate = 1
    ball = ball.lower()
    if ball == 'repeat':
        catch_rate = 3 if is_caught_before else 1
    elif ball == 'nest':
        catch_rate = 100 - poke_info['level'] / 14
    elif ball == 'master':
        catch_rate = 255
    elif ball == 'great':
        catch_rate = 1.5
    elif ball == 'ultra':
        catch_rate = 2
    elif ball == 'dusk':
        if 'dark' in poke_info['types']:
            catch_rate = 4.5
    elif ball == 'quick':
        if battle['turns'] == 1:
            catch_rate = 5
    elif ball == 'net':
        if 'bug' in poke_info['types'] or 'water' in poke_info['types']:
            catch_rate = 3
    elif ball == 'level':
        catch_rate = user_current_poke['level'] / poke_info['level']
        if catch_rate > 8:
            catch_rate = 8
    elif ball == 'lure':
        catch_rate = 1
    elif ball == 'moon':
        if 'fairy' in poke_info['types']:
            catch_rate = 3
    elif ball == 'heavy':
        catch_rate = 1  # To be fixed for weight system
    elif ball == 'fast':
        catch_rate = 4 if get_base_stat_func(poke_info['id'], 'speed') >= 100 else 1
    elif ball == 'sport':
        if 'bug' in poke_info['types']:
            catch_rate = 4
    catch_rate_modifier = 1
    if 0 < registered_pokemons < 30:
        catch_rate_modifier = 0.4
    elif 30 < registered_pokemons < 100:
        catch_rate_modifier = 0.6
    elif 100 < registered_pokemons < 300:
        catch_rate_modifier = 0.8
    b = int(((((3 * total_hp) - (2 * current_hp)) * pokemon_catch_rate * catch_rate) / (3 * total_hp)) * catch_rate_modifier)
    return b

def calculateEscapeChance(fleeingPokemonSpeed, opposingPokemonSpeed):
        return ((fleeingPokemonSpeed * 32) / (opposingPokemonSpeed + 30) + 30)

