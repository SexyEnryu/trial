"""
Global configuration and data caching system for Pokemon Bot
This module provides centralized caching for JSON data to improve performance
"""

import json
import os
import asyncio
from typing import Dict, Any, Optional
from functools import lru_cache
import threading

# Bot Configuration
BOT_TOKEN = "6528069679:AAGPQDm1SDX9QN4JJn1ojn4yQsw3FVmJFck"
MONGO_URI = "mongodb+srv://enryu:LULu4FQ1Ih9wz3tE@clientenryu.vw6z15z.mongodb.net/?retryWrites=true&w=majority&appName=ClientEnryu"

class DataCache:
    """Global data cache for JSON files and computed data"""
    
    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._file_mtimes: Dict[str, float] = {}
        
    def _get_file_mtime(self, filepath: str) -> float:
        """Get file modification time"""
        try:
            return os.path.getmtime(filepath)
        except OSError:
            return 0
    
    def _is_file_modified(self, filepath: str) -> bool:
        """Check if file has been modified since last load"""
        current_mtime = self._get_file_mtime(filepath)
        cached_mtime = self._file_mtimes.get(filepath, 0)
        return current_mtime > cached_mtime
    
    def load_json(self, filepath: str, cache_key: Optional[str] = None) -> Dict[str, Any]:
        """Load JSON file with caching"""
        if cache_key is None:
            cache_key = filepath
            
        with self._lock:
            # Check if we need to reload the file
            if cache_key not in self._cache or self._is_file_modified(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    self._cache[cache_key] = data
                    self._file_mtimes[filepath] = self._get_file_mtime(filepath)
                    print(f"[DataCache] Loaded {filepath} into cache")
                    
                except (FileNotFoundError, json.JSONDecodeError) as e:
                    print(f"[DataCache] Error loading {filepath}: {e}")
                    if cache_key not in self._cache:
                        self._cache[cache_key] = {}
            
            return self._cache[cache_key].copy()  # Return copy to prevent mutation
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get cached data by key"""
        with self._lock:
            return self._cache.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Set cached data"""
        with self._lock:
            self._cache[key] = value
    
    def clear(self) -> None:
        """Clear all cached data"""
        with self._lock:
            self._cache.clear()
            self._file_mtimes.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            return {
                'cached_files': len(self._file_mtimes),
                'cached_objects': len(self._cache),
                'cache_keys': list(self._cache.keys())
            }

# Global cache instance
data_cache = DataCache()

# Cached JSON data accessors
@lru_cache(maxsize=1)
def get_pokemon_data() -> Dict[str, Any]:
    """Get Pokemon data from poke.json with caching"""
    return data_cache.load_json('poke.json', 'pokemon_data')

@lru_cache(maxsize=1)
def get_evolution_data() -> Dict[str, Any]:
    """Get evolution data from evolve.json with caching"""
    return data_cache.load_json('evolve.json', 'evolution_data')

@lru_cache(maxsize=1)
def get_move_info_data() -> Dict[str, Any]:
    """Get move info data from move_info.json with caching"""
    return data_cache.load_json('move_info.json', 'move_info_data')

@lru_cache(maxsize=1)
def get_damaging_moves_data() -> Dict[str, Any]:
    """Get damaging moves data from damaging_moves.json with caching"""
    return data_cache.load_json('damaging_moves.json', 'damaging_moves_data')

@lru_cache(maxsize=1)
def get_gym_leaders_data() -> Dict[str, Any]:
    """Get gym leaders data from gym_leaders.json with caching"""
    return data_cache.load_json('gym_leaders.json', 'gym_leaders_data')

@lru_cache(maxsize=1)
def get_mega_pokemon_stats() -> Dict[str, Any]:
    """Get mega Pokemon stats from mega_pokemon_stats.json with caching"""
    return data_cache.load_json('mega_pokemon_stats.json', 'mega_pokemon_stats')

@lru_cache(maxsize=1)
def get_plate_data() -> Dict[str, Any]:
    """Get plate data from plate.json with caching"""
    return data_cache.load_json('plate.json', 'plate_data')

@lru_cache(maxsize=1)
def get_zmoves_data() -> Dict[str, Any]:
    """Get Z-moves data from zmoves.json with caching"""
    return data_cache.load_json('zmoves.json', 'zmoves_data')

@lru_cache(maxsize=1)
def get_tmhm_data() -> Dict[str, Any]:
    """Get TM/HM data from tmhm.json with caching"""
    return data_cache.load_json('tmhm.json', 'tmhm_data')

# Asset JSON data
@lru_cache(maxsize=1)
def get_damages_data() -> Dict[str, Any]:
    """Get damage data from assets/variable.jsons/damages.json with caching"""
    return data_cache.load_json('assets/variable.jsons/damages.json', 'damages_data')

@lru_cache(maxsize=1)
def get_ev_yield_data() -> Dict[str, Any]:
    """Get EV yield data from assets/variable.jsons/evYield.json with caching"""
    return data_cache.load_json('assets/variable.jsons/evYield.json', 'ev_yield_data')

def clear_all_caches():
    """Clear all caches (useful for development/testing)"""
    data_cache.clear()
    # Clear lru_cache for all functions
    get_pokemon_data.cache_clear()
    get_evolution_data.cache_clear()
    get_move_info_data.cache_clear()
    get_damaging_moves_data.cache_clear()
    get_gym_leaders_data.cache_clear()
    get_mega_pokemon_stats.cache_clear()
    get_plate_data.cache_clear()
    get_zmoves_data.cache_clear()
    get_tmhm_data.cache_clear()
    get_damages_data.cache_clear()
    get_ev_yield_data.cache_clear()

def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics for monitoring"""
    return data_cache.get_stats()

# Configuration constants for handlers
POKEBALLS = [
    {
        "name": "Regular",
        "description": "Standard Poké Ball used to catch Pokémon.",
        "catch_rate": 1,
        "rate": 10
    },
    {
        "name": "Repeat",
        "description": "More effective against Pokémon species that the player has already caught.",
        "catch_rate": 3,
        "rate": 50
    },
    {
        "name": "Nest",
        "description": "More effective against lower-level wild Pokémon.",
        "catch_rate": "Variable, increases with the level of the wild Pokémon.",
        "rate": 50
    },
    {
        "name": "Master",
        "description": "Guarantees the capture of any wild Pokémon without fail.",
        "catch_rate": "Guaranteed capture",
        "rate": 10000
    },
    {
        "name": "Great",
        "description": "Has a higher catch rate than a regular Poké Ball.",
        "catch_rate": 1.5,
        "rate": 25
    },
    {
        "name": "Ultra",
        "description": "Has an even higher catch rate than a Great Ball.",
        "catch_rate": 2,
        "rate": 50
    },
    {
        "name": "Dusk",
        "description": "More effective in capturing Pokémon which are dark types.",
        "catch_rate": "3.5x for dark Pokémon, 1x otherwise.",
        "rate": 75
    },
    {
        "name": "Quick",
        "description": "Has a higher catch rate than Ultra Ball.",
        "catch_rate": "2.5",
        "rate": 80
    },
    {
        "name": "Net",
        "description": "More effective against Bug-type and Water-type Pokémon.",
        "catch_rate": "3x against Bug or Water types.",
        "rate": 75
    },
    {
        "name": "Lure",
        "description": "More effective while fishing.",
        "catch_rate": "3x when used while fishing.",
        "rate": 60
    },
    {
        "name": "Moon",
        "description": "More effective when used on Pokémon that can evolve using moon stone.",
        "catch_rate": "4x if used on Pokémon that are fairy type.",
        "rate": 75
    },
    {
        "name": "Heavy",
        "description": "More effective against heavy Pokémon.",
        "catch_rate": "Variable, up to 8x for very heavy Pokémon.",
        "rate": 75
    },
    {
        "name": "Fast",
        "description": "More effective against fast Pokémon.",
        "catch_rate": "4x against Pokémon with a base Speed of 100 or more.",
        "rate": 80
    },
    {
        "name": "Sport",
        "description": "A special Poké Ball used to catch Bug type Pokémons.",
        "catch_rate": "4x against Bug type pokémons.",
        "rate": 75
    }
]

FISHING_RODS = [
    {
        "name": "Old Rod",
        "description": "A weathered but reliable fishing rod. Perfect for beginners looking to catch common Water-type Pokémon in shallow waters.",
        "fish_rate": 1,
        "rate": 150
    },
    {
        "name": "Good Rod",
        "description": "A sturdy fishing rod with improved line strength. Allows access to a wider variety of Water-type Pokémon in deeper areas.",
        "fish_rate": 1.5,
        "rate": 350
    },
    {
        "name": "Super Rod",
        "description": "A professional-grade fishing rod with advanced features. Significantly increases your chances of encountering rare Water-type Pokémon.",
        "fish_rate": 2.5,
        "rate": 800
    },
    {
        "name": "Ultra Rod",
        "description": "A premium fishing rod crafted from rare materials. Greatly increases the chances of attracting legendary Water-type Pokémon.",
        "fish_rate": 4,
        "rate": 2500
    },
    {
        "name": "Master Rod",
        "description": "The pinnacle of fishing rod technology. Provides the highest catch rates and dramatically increases chances of encountering any rare Water-type Pokémon.",
        "fish_rate": 6,
        "rate": 15000
    },
    {
        "name": "Shiny Rod",
        "description": "A mystical rod that glimmers with an otherworldly light. Significantly increases the chances of encountering shiny Water-type Pokémon.",
        "fish_rate": 3,
        "rate": 8000
    },
    {
        "name": "Deep Sea Rod",
        "description": "Specially designed for extreme depths with reinforced materials. Increases chances of catching rare deep-sea and abyssal Water-type Pokémon.",
        "fish_rate": 5,
        "rate": 3000
    },
    {
        "name": "Crystal Rod",
        "description": "A beautiful rod infused with ice crystals. Increases chances of catching Ice-type Pokémon and Water-types that thrive in frozen environments.",
        "fish_rate": 3.5,
        "rate": 1800
    }
]

BERRIES = [
    {
        "name": "pomeg-berry",
        "effect": "Reduces HP EVs by 5.",
        "rate": "ev-",
        "price": 100
    },
    {
        "name": "kelpsy-berry",
        "effect": "Reduces Attack EVs by 5.",
        "rate": "ev-",
        "price": 100
    },
    {
        "name": "qualot-berry",
        "effect": "Reduces Defense EVs by 5.",
        "rate": "ev-",
        "price": 100
    },
    {
        "name": "hondew-berry",
        "effect": "Reduces Special Attack EVs by 5.",
        "rate": "ev-",
        "price": 100
    },
    {
        "name": "grepa-berry",
        "effect": "Reduces Special Defense EVs by 5.",
        "rate": "ev-",
        "price": 100
    },
    {
        "name": "tamato-berry",
        "effect": "Reduces Speed EVs by 5.",
        "rate": "ev-",
        "price": 100
    },
]

VITAMINS = [   
    {
        "name": "hp-up",
        "effect": "Raises HP EVs by 5.",
        "rate": "ev+",
        "price": 100
    },
    {
        "name": "protein",
        "effect": "Raises Attack EVs by 5.",
        "rate": "ev+",
        "price": 100
    },
    {
        "name": "iron",
        "effect": "Raises Defense EVs by 5.",
        "rate": "ev+",
        "price": 100
    },
    {
        "name": "calcium",
        "effect": "Raises Special Attack EVs by 5.",
        "rate": "ev+",
        "price": 100
    },
    {
        "name": "zinc",
        "effect": "Raises Special Defense EVs by 5.",
        "rate": "ev+",
        "price": 100
    },
    {
        "name": "carbos",
        "effect": "Raises Speed EVs by 5.",
        "rate": "ev+",
        "price": 100
    }
]

MISC_ITEMS = [
    {
        "name": "rare-candy",
        "effect": "Increases Pokémon level by 1.",
        "emoji": "🍬",
        "price": 300
    },
    {
        "name": "mega-bracelet",
        "effect": "Allows Mega Evolution in battles.",
        "emoji": "💠",
        "price": 20000
    },
    {
        "name": "z-ring",
        "effect": "Allows Z-Move usage in battles with Z-Crystals.",
        "emoji": "⚡",
        "price": 50000
    }
]
