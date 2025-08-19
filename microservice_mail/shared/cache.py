import time
import json
import logging
from typing import Any, Dict, Optional, Tuple
from pathlib import Path
import threading

class SimpleCache:
    """Simple in-memory cache with TTL (Time To Live) support."""
    
    def __init__(self, default_ttl: int = 300):  # 5 minutes default
        self.cache: Dict[str, Dict] = {}
        self.default_ttl = default_ttl
        self._lock = threading.Lock()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        with self._lock:
            if key not in self.cache:
                return None
            
            entry = self.cache[key]
            if time.time() > entry['expires_at']:
                del self.cache[key]
                return None
            
            logging.debug(f"Cache hit for key: {key}")
            return entry['value']
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache with TTL."""
        if ttl is None:
            ttl = self.default_ttl
        
        with self._lock:
            self.cache[key] = {
                'value': value,
                'expires_at': time.time() + ttl,
                'created_at': time.time()
            }
            logging.debug(f"Cache set for key: {key}, TTL: {ttl}s")
    
    def delete(self, key: str) -> bool:
        """Delete key from cache."""
        with self._lock:
            if key in self.cache:
                del self.cache[key]
                logging.debug(f"Cache deleted for key: {key}")
                return True
            return False
    
    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self.cache.clear()
            logging.debug("Cache cleared")
    
    def cleanup_expired(self) -> int:
        """Remove expired entries and return count removed."""
        current_time = time.time()
        expired_keys = []
        
        with self._lock:
            for key, entry in self.cache.items():
                if current_time > entry['expires_at']:
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self.cache[key]
        
        if expired_keys:
            logging.debug(f"Removed {len(expired_keys)} expired cache entries")
        
        return len(expired_keys)
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            current_time = time.time()
            active_entries = sum(1 for entry in self.cache.values() 
                               if current_time <= entry['expires_at'])
            expired_entries = len(self.cache) - active_entries
            
            return {
                'total_entries': len(self.cache),
                'active_entries': active_entries,
                'expired_entries': expired_entries
            }


class FileCache:
    """File-based cache for persistent storage."""
    
    def __init__(self, cache_dir: str = "cache", default_ttl: int = 300):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.default_ttl = default_ttl
    
    def _get_cache_file(self, key: str) -> Path:
        """Get cache file path for key."""
        # Hash key to avoid filesystem issues
        import hashlib
        key_hash = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.json"
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from file cache if not expired."""
        cache_file = self._get_cache_file(key)
        
        if not cache_file.exists():
            return None
        
        try:
            with open(cache_file, 'r') as f:
                entry = json.load(f)
            
            if time.time() > entry['expires_at']:
                cache_file.unlink()  # Delete expired file
                return None
            
            logging.debug(f"File cache hit for key: {key}")
            return entry['value']
            
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logging.warning(f"Error reading cache file for key {key}: {e}")
            if cache_file.exists():
                cache_file.unlink()
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in file cache with TTL."""
        if ttl is None:
            ttl = self.default_ttl
        
        cache_file = self._get_cache_file(key)
        
        entry = {
            'value': value,
            'expires_at': time.time() + ttl,
            'created_at': time.time(),
            'key': key  # Store original key for debugging
        }
        
        try:
            with open(cache_file, 'w') as f:
                json.dump(entry, f)
            logging.debug(f"File cache set for key: {key}, TTL: {ttl}s")
        except OSError as e:
            logging.error(f"Error writing cache file for key {key}: {e}")


# Global cache instances
memory_cache = SimpleCache(default_ttl=300)  # 5 minutes
file_cache = FileCache(default_ttl=1800)     # 30 minutes


def get_drive_files_cache_key(folder_id: str, required_files: list) -> str:
    """Generate cache key for Google Drive file searches."""
    files_str = ','.join(sorted(required_files))
    return f"drive_files:{folder_id}:{hash(files_str)}"


def cache_drive_search(func):
    """Decorator to cache Google Drive search results."""
    def wrapper(self, required_files: list, share_email: str = None):
        # Generate cache key
        cache_key = get_drive_files_cache_key(self.folder_id, required_files)
        
        # Try to get from cache first
        cached_result = memory_cache.get(cache_key)
        if cached_result is not None:
            logging.info(f"Using cached Google Drive search results for {len(required_files)} files")
            return cached_result
        
        # If not in memory cache, try file cache
        cached_result = file_cache.get(cache_key)
        if cached_result is not None:
            logging.info(f"Using file cached Google Drive search results for {len(required_files)} files")
            # Promote to memory cache
            memory_cache.set(cache_key, cached_result, 300)
            return cached_result
        
        # Cache miss - execute the actual function
        logging.info(f"Cache miss - performing Google Drive search for {len(required_files)} files")
        result = func(self, required_files, share_email)
        
        # Cache the result
        memory_cache.set(cache_key, result, 300)    # 5 minutes in memory
        file_cache.set(cache_key, result, 1800)     # 30 minutes on disk
        
        return result
    
    return wrapper