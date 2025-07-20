"""
Performance monitoring system for the Pokemon Bot
"""

import time
import asyncio
from typing import Dict, Any
from config import get_cache_stats
from pokemon_stats_cache import pokemon_stats_cache
from image_cache import ImageCache


class PerformanceMonitor:
    """Monitor bot performance and cache efficiency"""
    
    def __init__(self):
        self.start_time = time.time()
        self.command_count = 0
        self.response_times = []
        
    async def log_command_performance(self, command_name: str, start_time: float, end_time: float):
        """Log command execution time"""
        execution_time = end_time - start_time
        self.response_times.append(execution_time)
        self.command_count += 1
        
        if execution_time > 2.0:  # Log slow commands
            print(f"[PERF] Slow command detected: {command_name} took {execution_time:.2f}s")
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get comprehensive performance statistics"""
        uptime = time.time() - self.start_time
        avg_response_time = sum(self.response_times) / len(self.response_times) if self.response_times else 0
        
        return {
            'uptime_seconds': uptime,
            'total_commands': self.command_count,
            'average_response_time': avg_response_time,
            'cache_stats': {
                'json_cache': get_cache_stats(),
                'pokemon_stats_cache': pokemon_stats_cache.get_stats_info(),
            },
            'recent_slow_commands': len([t for t in self.response_times[-100:] if t > 2.0]),
        }


# Global performance monitor
perf_monitor = PerformanceMonitor()


def performance_decorator(command_name: str):
    """Decorator to monitor command performance"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                end_time = time.time()
                await perf_monitor.log_command_performance(command_name, start_time, end_time)
        return wrapper
    return decorator 