import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional

from .config import LoggingConfig


class LoggerSetup:
    """Centralized logging configuration for all microservices."""
    
    @staticmethod
    def setup_logger(
        name: str,
        config: LoggingConfig,
        log_file: Optional[str] = None,
        console: bool = True
    ) -> logging.Logger:
        """
        Setup a logger with both file and console handlers.
        
        Args:
            name: Logger name (usually __name__)
            config: LoggingConfig instance
            log_file: Optional specific log file name (defaults to {name}.log)
            console: Whether to add console handler
        
        Returns:
            Configured logger instance
        """
        logger = logging.getLogger(name)
        
        # Prevent duplicate handlers
        if logger.handlers:
            return logger
            
        logger.setLevel(getattr(logging, config.log_level.upper()))
        
        # Create formatter
        formatter = logging.Formatter(config.log_format)
        
        # File handler
        if log_file is None:
            log_file = f"{name.replace('.', '_')}.log"
            
        log_path = Path(config.log_dir) / log_file
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, config.log_level.upper()))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        # Console handler
        if console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(getattr(logging, config.log_level.upper()))
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
        
        return logger
    
    @staticmethod
    def setup_flask_logging(app, config: LoggingConfig, service_name: str):
        """Setup Flask application logging."""
        # Remove default Flask handlers
        for handler in app.logger.handlers[:]:
            app.logger.removeHandler(handler)
        
        # Setup custom logger for Flask
        logger = LoggerSetup.setup_logger(
            f"flask.{service_name}",
            config,
            f"{service_name}.log"
        )
        
        # Set Flask app logger
        app.logger = logger
        app.logger.setLevel(getattr(logging, config.log_level.upper()))
        
        return logger