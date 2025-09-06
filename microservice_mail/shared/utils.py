import functools
import time
import logging
from typing import Any, Callable, Dict, Optional, TypeVar, Union
from fastapi import HTTPException, Request
from pydantic import BaseModel
import requests

T = TypeVar('T')

def retry_on_failure(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """
    Retry decorator for functions that might fail temporarily.
    
    Args:
        max_retries: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        backoff: Multiplier for delay after each retry
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt == max_retries:
                        break
                    
                    logging.warning(f"Attempt {attempt + 1}/{max_retries + 1} failed for {func.__name__}: {e}")
                    time.sleep(current_delay)
                    current_delay *= backoff
            
            logging.error(f"All retry attempts failed for {func.__name__}: {last_exception}")
            raise last_exception
            
        return wrapper
    return decorator


def validate_request_data(required_fields: list, optional_fields: list = None):
    """
    FastAPI/Pydantic compatible request data validator.
    This function is now mainly for legacy compatibility.
    In FastAPI, use Pydantic models for validation instead.
    
    Args:
        required_fields: List of field names that must be present
        optional_fields: List of field names that are optional
    """
    def validate_data(data: dict) -> dict:
        if not data:
            raise HTTPException(
                status_code=400, 
                detail="Request body cannot be empty"
            )
        
        # Check required fields
        missing_fields = [field for field in required_fields if field not in data or data[field] is None]
        if missing_fields:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required fields: {', '.join(missing_fields)}"
            )
        
        # Check for unexpected fields if optional_fields is provided
        if optional_fields is not None:
            all_allowed = set(required_fields + optional_fields)
            unexpected_fields = [field for field in data.keys() if field not in all_allowed]
            if unexpected_fields:
                logging.warning(f"Unexpected fields in request: {', '.join(unexpected_fields)}")
        
        return data
    
    return validate_data


def safe_request(url: str, method: str = 'GET', timeout: int = 30, **kwargs) -> Optional[requests.Response]:
    """
    Make a safe HTTP request with proper error handling and logging.
    
    Args:
        url: The URL to request
        method: HTTP method (GET, POST, etc.)
        timeout: Request timeout in seconds
        **kwargs: Additional arguments for requests
    
    Returns:
        Response object or None if request failed
    """
    try:
        response = requests.request(method, url, timeout=timeout, **kwargs)
        response.raise_for_status()
        return response
    except requests.exceptions.Timeout:
        logging.error(f"Request to {url} timed out after {timeout} seconds")
        return None
    except requests.exceptions.ConnectionError:
        logging.error(f"Connection error when requesting {url}")
        return None
    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP error {e.response.status_code} when requesting {url}: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error when requesting {url}: {e}")
        return None


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename by removing or replacing unsafe characters.
    
    Args:
        filename: Original filename
        
    Returns:
        Sanitized filename
    """
    import re
    # Remove or replace unsafe characters
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove control characters
    filename = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', filename)
    # Limit length
    if len(filename) > 255:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        filename = name[:255-len(ext)-1] + '.' + ext if ext else name[:255]
    
    return filename


def validate_email(email: str) -> bool:
    """
    Validate email address format.
    
    Args:
        email: Email address to validate
        
    Returns:
        True if email is valid, False otherwise
    """
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


class HealthChecker:
    """Utility class for health checks."""
    
    @staticmethod
    def check_service(url: str, service_name: str) -> Dict[str, Any]:
        """
        Check the health of a service.
        
        Args:
            url: Service URL
            service_name: Name of the service
            
        Returns:
            Dictionary with health check results
        """
        try:
            response = safe_request(f"{url}/health", timeout=5)
            if response and response.status_code == 200:
                return {
                    "service": service_name,
                    "status": "healthy",
                    "response_time": response.elapsed.total_seconds()
                }
            else:
                return {
                    "service": service_name,
                    "status": "unhealthy",
                    "error": "Health check failed or returned non-200 status"
                }
        except Exception as e:
            return {
                "service": service_name,
                "status": "unhealthy",
                "error": str(e)
            }
    
    @staticmethod
    def check_all_services(services: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
        """
        Check the health of multiple services.
        
        Args:
            services: Dictionary mapping service names to URLs
            
        Returns:
            Dictionary with health check results for all services
        """
        results = {}
        for name, url in services.items():
            results[name] = HealthChecker.check_service(url, name)
        return results


def format_error_response(message: str, error_code: str = None, details: Dict = None) -> Dict[str, Any]:
    """
    Format a standardized error response.
    
    Args:
        message: Error message
        error_code: Optional error code
        details: Optional additional details
        
    Returns:
        Formatted error response
    """
    response = {
        "success": False,
        "error": message,
        "timestamp": time.time()
    }
    
    if error_code:
        response["error_code"] = error_code
        
    if details:
        response["details"] = details
        
    return response


def format_success_response(data: Any = None, message: str = None) -> Dict[str, Any]:
    """
    Format a standardized success response.
    
    Args:
        data: Response data
        message: Optional success message
        
    Returns:
        Formatted success response
    """
    response = {
        "success": True,
        "timestamp": time.time()
    }
    
    if data is not None:
        response["data"] = data
        
    if message:
        response["message"] = message
        
    return response
