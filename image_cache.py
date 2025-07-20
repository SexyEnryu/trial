import os
import threading
from functools import lru_cache
from typing import Optional, Dict, List, Tuple
from aiogram.types import FSInputFile
import weakref
import time


class ImageCache:
    """
    Centralized image caching system for Pokemon images.
    
    Features:
    - LRU caching with configurable size limits
    - Thread-safe operations
    - Support for different image types (normal, shiny, mega, z-crystals, mega stones)
    - Automatic fallback path handling
    - Cache statistics and management
    """
    
    def __init__(self, max_cache_size: int = 800):  # Increased cache size
        self.max_cache_size = max_cache_size
        self._cache: Dict[str, FSInputFile] = {}
        self._cache_times: Dict[str, float] = {}
        self._lock = threading.RLock()
        self._file_exists_cache: Dict[str, bool] = {}  # Cache file existence checks
        self._stats = {
            'hits': 0,
            'misses': 0,
            'cache_size': 0,
            'evictions': 0
        }
        
        # Image path templates for different types
        self.image_paths = {
            'normal': [
                "assets/images/{pokemon_id}.png",
            ],
            'shiny': [
                "assets/images/shiny_pokemon/{pokemon_id}.png",
                "assets/shiny_pokemon/{pokemon_id}.png",
                "shiny_pokemon/{pokemon_id}.png"
            ],
            'mega': [
                "mega_images/{filename}",
                "imagesx/{filename}"
            ],
            'mega_shiny': [
                "mega_images_shiny/{filename}",
                "mega_images/{filename}",
                "imagesx/{filename}"
            ],
            'z_crystal': [
                "z_crystals/{filename}"
            ],
            'mega_stone': [
                "mega_stones/{filename}"
            ],
            'plate': [
                "plates/{filename}"
            ],
            'arceus_normal': [
                "arceus_forms/{filename}",
                "assets/images/493.png"  # fallback to normal Arceus
            ],
            'arceus_shiny': [
                "shiny_arcues/{filename}",
                "shiny_pokemon/493.png"  # fallback to shiny Arceus
            ]
        }
    
    def _get_cache_key(self, image_path: str) -> str:
        """Generate a unique cache key for the image path."""
        return f"img:{image_path}"
    
    def _evict_oldest(self) -> None:
        """Evict the oldest cached item if cache is full."""
        if len(self._cache) >= self.max_cache_size:
            # Find the oldest item
            oldest_key = min(self._cache_times.keys(), key=lambda k: self._cache_times[k])
            del self._cache[oldest_key]
            del self._cache_times[oldest_key]
            self._stats['evictions'] += 1
    
    def _update_stats(self, hit: bool) -> None:
        """Update cache statistics."""
        if hit:
            self._stats['hits'] += 1
        else:
            self._stats['misses'] += 1
        self._stats['cache_size'] = len(self._cache)
    
    def get_cached_image(self, image_path: str) -> Optional[FSInputFile]:
        """
        Get a cached FSInputFile for the given image path.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            FSInputFile object if found in cache and file exists, None otherwise
        """
        if not image_path or not os.path.exists(image_path):
            return None
            
        cache_key = self._get_cache_key(image_path)
        
        with self._lock:
            if cache_key in self._cache:
                self._update_stats(True)
                self._cache_times[cache_key] = time.time()  # Update access time
                return self._cache[cache_key]
            
            # Cache miss - create new FSInputFile
            try:
                fs_input = FSInputFile(image_path)
                
                # Evict oldest if cache is full
                self._evict_oldest()
                
                # Add to cache
                self._cache[cache_key] = fs_input
                self._cache_times[cache_key] = time.time()
                
                self._update_stats(False)
                return fs_input
                
            except Exception as e:
                print(f"[ImageCache] Error creating FSInputFile for {image_path}: {e}")
                self._update_stats(False)
                return None
    
    def get_pokemon_image(self, pokemon_id: int, is_shiny: bool = False) -> Optional[FSInputFile]:
        """
        Get a cached Pokemon image with automatic fallback handling.
        
        Args:
            pokemon_id: Pokemon ID
            is_shiny: Whether to get shiny version
            
        Returns:
            FSInputFile object if image found, None otherwise
        """
        # Check cache key first to avoid file system calls
        cache_key_base = f"pokemon_{pokemon_id}_{'shiny' if is_shiny else 'normal'}"
        
        with self._lock:
            # Quick cache lookup for known working path
            for existing_key in self._cache.keys():
                if existing_key.startswith(f"img:assets/images/{'shiny_pokemon/' if is_shiny else ''}{pokemon_id}.png"):
                    self._cache_times[existing_key] = time.time()
                    return self._cache[existing_key]
        
        # Not in cache, check file system
        image_type = 'shiny' if is_shiny else 'normal'
        paths = self.image_paths[image_type]
        
        for path_template in paths:
            image_path = path_template.format(pokemon_id=pokemon_id)
            if os.path.exists(image_path):
                return self.get_cached_image(image_path)
        
        return None
    
    def get_mega_image(self, mega_form: str, is_shiny: bool = False) -> Optional[FSInputFile]:
        """
        Get a cached Mega Evolution image.
        
        Args:
            mega_form: Name of the mega form
            is_shiny: Whether to get shiny version
            
        Returns:
            FSInputFile object if image found, None otherwise
        """
        # Convert mega form name to filename
        filename = mega_form.lower().replace(' ', '_').replace('-', '_') + '.png'
        if is_shiny:
            filename = filename.replace('.png', '_shiny.png')
        
        image_type = 'mega_shiny' if is_shiny else 'mega'
        paths = self.image_paths[image_type]
        
        for path_template in paths:
            image_path = path_template.format(filename=filename)
            if os.path.exists(image_path):
                return self.get_cached_image(image_path)
        
        return None
    
    def get_z_crystal_image(self, z_crystal_name: str) -> Optional[FSInputFile]:
        """
        Get a cached Z-Crystal image.
        
        Args:
            z_crystal_name: Name of the Z-Crystal
            
        Returns:
            FSInputFile object if image found, None otherwise
        """
        filename = f"{z_crystal_name}.png"
        paths = self.image_paths['z_crystal']
        
        for path_template in paths:
            image_path = path_template.format(filename=filename)
            if os.path.exists(image_path):
                return self.get_cached_image(image_path)
        
        return None
    
    def get_mega_stone_image(self, stone_name: str) -> Optional[FSInputFile]:
        """
        Get a cached Mega Stone image.
        
        Args:
            stone_name: Name of the mega stone
            
        Returns:
            FSInputFile object if image found, None otherwise
        """
        filename = f"{stone_name}.png"
        paths = self.image_paths['mega_stone']
        
        for path_template in paths:
            image_path = path_template.format(filename=filename)
            if os.path.exists(image_path):
                return self.get_cached_image(image_path)
        
        return None
    
    def get_plate_image(self, plate_name: str) -> Optional[FSInputFile]:
        """
        Get a cached Plate image.
        
        Args:
            plate_name: Name of the plate
            
        Returns:
            FSInputFile object if image found, None otherwise
        """
        filename = f"{plate_name}.png"
        paths = self.image_paths['plate']
        
        for path_template in paths:
            image_path = path_template.format(filename=filename)
            if os.path.exists(image_path):
                return self.get_cached_image(image_path)
        
        return None
    
    def get_arceus_form_image(self, pokemon_type: str, is_shiny: bool = False) -> Optional[FSInputFile]:
        """
        Get a cached Arceus form image.
        
        Args:
            pokemon_type: Type of Arceus form (e.g., 'fire', 'water', 'electric')
            is_shiny: Whether to get shiny version
            
        Returns:
            FSInputFile object if image found, None otherwise
        """
        filename = f"arceus_{pokemon_type.lower()}.png"
        image_type = 'arceus_shiny' if is_shiny else 'arceus_normal'
        paths = self.image_paths[image_type]
        
        for path_template in paths:
            image_path = path_template.format(filename=filename)
            if os.path.exists(image_path):
                return self.get_cached_image(image_path)
        
        return None
    
    def get_image_path(self, pokemon_id: int, is_shiny: bool = False) -> str:
        """
        Get the first existing image path for a Pokemon.
        
        Args:
            pokemon_id: Pokemon ID
            is_shiny: Whether to get shiny version
            
        Returns:
            Path to the image file if found, empty string otherwise
        """
        image_type = 'shiny' if is_shiny else 'normal'
        paths = self.image_paths[image_type]
        
        for path_template in paths:
            image_path = path_template.format(pokemon_id=pokemon_id)
            if os.path.exists(image_path):
                return image_path
        
        return ""
    
    def clear_cache(self) -> None:
        """Clear all cached images."""
        with self._lock:
            self._cache.clear()
            self._cache_times.clear()
            self._stats['cache_size'] = 0
    
    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        with self._lock:
            stats = self._stats.copy()
            stats['cache_size'] = len(self._cache)
            if stats['hits'] + stats['misses'] > 0:
                stats['hit_rate'] = round(stats['hits'] / (stats['hits'] + stats['misses']) * 100, 2)
            else:
                stats['hit_rate'] = 0.0
            return stats
    
    def preload_pokemon_images(self, pokemon_ids: List[int], include_shiny: bool = True) -> None:
        """
        Preload images for multiple Pokemon to warm up the cache.
        
        Args:
            pokemon_ids: List of Pokemon IDs to preload
            include_shiny: Whether to also preload shiny versions
        """
        for pokemon_id in pokemon_ids:
            # Preload normal image
            self.get_pokemon_image(pokemon_id, False)
            
            # Preload shiny image if requested
            if include_shiny:
                self.get_pokemon_image(pokemon_id, True)
    
    def remove_from_cache(self, image_path: str) -> bool:
        """
        Remove a specific image from cache.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            True if item was removed, False if not found
        """
        cache_key = self._get_cache_key(image_path)
        
        with self._lock:
            if cache_key in self._cache:
                del self._cache[cache_key]
                del self._cache_times[cache_key]
                self._stats['cache_size'] = len(self._cache)
                return True
            return False


# Global image cache instance
_image_cache = ImageCache(max_cache_size=500)

# Public API functions
def get_cached_pokemon_image(pokemon_id: int, is_shiny: bool = False) -> Optional[FSInputFile]:
    """Get a cached Pokemon image."""
    return _image_cache.get_pokemon_image(pokemon_id, is_shiny)

def get_cached_mega_image(mega_form: str, is_shiny: bool = False) -> Optional[FSInputFile]:
    """Get a cached Mega Evolution image."""
    return _image_cache.get_mega_image(mega_form, is_shiny)

def get_cached_z_crystal_image(z_crystal_name: str) -> Optional[FSInputFile]:
    """Get a cached Z-Crystal image."""
    return _image_cache.get_z_crystal_image(z_crystal_name)

def get_cached_mega_stone_image(stone_name: str) -> Optional[FSInputFile]:
    """Get a cached Mega Stone image."""
    return _image_cache.get_mega_stone_image(stone_name)

def get_cached_plate_image(plate_name: str) -> Optional[FSInputFile]:
    """Get a cached Plate image."""
    return _image_cache.get_plate_image(plate_name)

def get_cached_arceus_form_image(pokemon_type: str, is_shiny: bool = False) -> Optional[FSInputFile]:
    """Get a cached Arceus form image."""
    return _image_cache.get_arceus_form_image(pokemon_type, is_shiny)

def get_cached_image(image_path: str) -> Optional[FSInputFile]:
    """Get a cached image by path."""
    return _image_cache.get_cached_image(image_path)

def get_pokemon_image_path(pokemon_id: int, is_shiny: bool = False) -> str:
    """Get the path to a Pokemon image."""
    return _image_cache.get_image_path(pokemon_id, is_shiny)

def clear_image_cache() -> None:
    """Clear all cached images."""
    _image_cache.clear_cache()

def get_cache_stats() -> Dict[str, int]:
    """Get image cache statistics."""
    return _image_cache.get_stats()

def preload_pokemon_images(pokemon_ids: List[int], include_shiny: bool = True) -> None:
    """Preload images for multiple Pokemon."""
    _image_cache.preload_pokemon_images(pokemon_ids, include_shiny)

def set_cache_size(size: int) -> None:
    """Set the maximum cache size."""
    _image_cache.max_cache_size = size 