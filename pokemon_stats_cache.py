"""
Pokemon stat caching system to improve performance by avoiding repeated calculations
"""

import hashlib
import threading
from typing import Dict, Any, Optional
from functools import lru_cache


class PokemonStatsCache:
    """Cache for calculated Pokemon stats to avoid repeated computations"""
    
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._access_order: list = []
        self._lock = threading.RLock()
        
    def _generate_cache_key(self, pokemon: Dict[str, Any]) -> str:
        """Generate a unique cache key for a Pokemon's stat configuration"""
        # Include relevant stat calculation inputs
        key_data = {
            'id': pokemon.get('id'),
            'level': pokemon.get('level'),
            'ivs': pokemon.get('ivs', {}),
            'evs': pokemon.get('evs', {}),
            'nature': pokemon.get('nature'),
            'mega': pokemon.get('mega_form'),
        }
        
        # Create a deterministic hash
        key_str = str(sorted(key_data.items()))
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _evict_oldest(self):
        """Remove the oldest entry if cache is full"""
        if len(self._cache) >= self.max_size and self._access_order:
            oldest_key = self._access_order.pop(0)
            self._cache.pop(oldest_key, None)
    
    def get_stats(self, pokemon: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get cached calculated stats for a Pokemon"""
        cache_key = self._generate_cache_key(pokemon)
        
        with self._lock:
            if cache_key in self._cache:
                # Move to end (most recently used)
                if cache_key in self._access_order:
                    self._access_order.remove(cache_key)
                self._access_order.append(cache_key)
                return self._cache[cache_key].copy()
            
        return None
    
    def set_stats(self, pokemon: Dict[str, Any], calculated_stats: Dict[str, Any]) -> None:
        """Cache calculated stats for a Pokemon"""
        cache_key = self._generate_cache_key(pokemon)
        
        with self._lock:
            # Evict oldest if needed
            self._evict_oldest()
            
            # Store stats
            self._cache[cache_key] = calculated_stats.copy()
            
            # Update access order
            if cache_key in self._access_order:
                self._access_order.remove(cache_key)
            self._access_order.append(cache_key)
    
    def clear(self) -> None:
        """Clear all cached stats"""
        with self._lock:
            self._cache.clear()
            self._access_order.clear()
    
    def get_stats_info(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            return {
                'cached_pokemon': len(self._cache),
                'max_size': self.max_size,
                'hit_rate': 'N/A'  # Could implement if needed
            }


# Global stats cache instance
pokemon_stats_cache = PokemonStatsCache()


def get_cached_pokemon_stats(pokemon: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Get cached Pokemon stats if available"""
    return pokemon_stats_cache.get_stats(pokemon)


def cache_pokemon_stats(pokemon: Dict[str, Any], calculated_stats: Dict[str, Any]) -> None:
    """Cache calculated Pokemon stats"""
    pokemon_stats_cache.set_stats(pokemon, calculated_stats)


@lru_cache(maxsize=500)
def get_cached_base_stats(pokemon_id: int) -> Dict[str, Any]:
    """Get cached base stats for a Pokemon ID"""
    from config import get_pokemon_data
    pokemon_data = get_pokemon_data()
    
    # Find Pokemon by ID
    if isinstance(pokemon_data, list):
        for poke in pokemon_data:
            if poke.get('id') == pokemon_id:
                return poke.get('base_stats', {})
    elif isinstance(pokemon_data, dict):
        poke = pokemon_data.get(str(pokemon_id))
        if poke:
            return poke.get('base_stats', {})
    
    return {}


def clear_all_stat_caches():
    """Clear all stat caches"""
    pokemon_stats_cache.clear()
    get_cached_base_stats.cache_clear() 