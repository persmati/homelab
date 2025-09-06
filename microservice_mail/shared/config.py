import os
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List
from pathlib import Path

def get_env_bool(key: str, default: bool = False) -> bool:
    """Convert environment variable to boolean."""
    value = os.getenv(key, str(default)).lower()
    return value in ('true', '1', 'yes', 'on')

def get_env_int(key: str, default: int = 0) -> int:
    """Convert environment variable to integer."""
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default

def get_env_list(key: str, default: List[str] = None, separator: str = ',') -> List[str]:
    """Convert environment variable to list."""
    if default is None:
        default = []
    value = os.getenv(key)
    if value:
        return [item.strip() for item in value.split(separator)]
    return default

@dataclass
class BaseLinkerConfig:
    api_url: str = field(default_factory=lambda: os.getenv('BASELINKER_API_URL', 'https://api.baselinker.com/connector.php'))
    token: str = field(default_factory=lambda: os.getenv('BASELINKER_TOKEN', ''))
    pending_status_id: str = field(default_factory=lambda: os.getenv('BASELINKER_PENDING_STATUS_ID', '219626'))
    processed_status_id: str = field(default_factory=lambda: os.getenv('BASELINKER_PROCESSED_STATUS_ID', '342638'))

    def __post_init__(self):
        if not self.token:
            raise ValueError("BASELINKER_TOKEN environment variable is required")

@dataclass
class GoogleDriveConfig:
    service_account_file: str = field(default_factory=lambda: os.getenv('GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE', 'drive-gmail_service.json'))
    scopes: List[str] = field(default_factory=lambda: get_env_list('GOOGLE_DRIVE_SCOPES', ['https://www.googleapis.com/auth/drive']))
    folder_id: str = field(default_factory=lambda: os.getenv('GOOGLE_DRIVE_FOLDER_ID', ''))
    share_email: str = field(default_factory=lambda: os.getenv('GOOGLE_DRIVE_SHARE_EMAIL', ''))

    def __post_init__(self):
        if not self.folder_id:
            raise ValueError("GOOGLE_DRIVE_FOLDER_ID environment variable is required")
        if not self.share_email:
            raise ValueError("GOOGLE_DRIVE_SHARE_EMAIL environment variable is required")

@dataclass
class EmailConfig:
    smtp_server: str = field(default_factory=lambda: os.getenv('EMAIL_SMTP_SERVER', 'smtp.gmail.com'))
    smtp_port: int = field(default_factory=lambda: get_env_int('EMAIL_SMTP_PORT', 465))
    gmail_user: str = field(default_factory=lambda: os.getenv('EMAIL_GMAIL_USER', ''))
    gmail_password: str = field(default_factory=lambda: os.getenv('EMAIL_GMAIL_PASSWORD', ''))
    print_email: str = field(default_factory=lambda: os.getenv('EMAIL_PRINT_EMAIL', ''))
    admin_email: str = field(default_factory=lambda: os.getenv('EMAIL_ADMIN_EMAIL', ''))
    recipient_email: str = field(default_factory=lambda: os.getenv('RECIPIENT_EMAIL', ''))

    def __post_init__(self):
        if not self.gmail_user:
            raise ValueError("EMAIL_GMAIL_USER environment variable is required")
        if not self.gmail_password:
            raise ValueError("EMAIL_GMAIL_PASSWORD environment variable is required")
        if not self.print_email:
            raise ValueError("EMAIL_PRINT_EMAIL environment variable is required")
        if not self.admin_email:
            raise ValueError("EMAIL_ADMIN_EMAIL environment variable is required")

@dataclass
class ServiceConfig:
    order_service_url: str = field(default_factory=lambda: os.getenv('ORDER_SERVICE_URL', 'http://localhost:5001'))
    file_service_url: str = field(default_factory=lambda: os.getenv('FILE_SERVICE_URL', 'http://localhost:5002'))
    email_service_url: str = field(default_factory=lambda: os.getenv('EMAIL_SERVICE_URL', 'http://localhost:5003'))
    orchestrator_port: int = field(default_factory=lambda: get_env_int('ORCHESTRATOR_PORT', 5000))

@dataclass
class LoggingConfig:
    log_dir: str = field(default_factory=lambda: os.getenv('LOG_DIR', '/var/log/microservice_mail'))
    log_level: str = field(default_factory=lambda: os.getenv('LOG_LEVEL', 'INFO'))
    log_format: str = field(default_factory=lambda: os.getenv('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

    def __post_init__(self):
        # Ensure log directory exists
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)
        
        # Validate log level
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if self.log_level.upper() not in valid_levels:
            raise ValueError(f"LOG_LEVEL must be one of: {', '.join(valid_levels)}")

@dataclass
class AppEnvironment:
    environment: str = field(default_factory=lambda: os.getenv('ENVIRONMENT', 'development'))
    debug: bool = field(default_factory=lambda: get_env_bool('DEBUG', True))

    def __post_init__(self):
        valid_environments = ['development', 'staging', 'production']
        if self.environment not in valid_environments:
            raise ValueError(f"ENVIRONMENT must be one of: {', '.join(valid_environments)}")
        
        # In production, debug should be False
        if self.environment == 'production' and self.debug:
            logging.warning("DEBUG is enabled in production environment. Consider setting DEBUG=false")

class AppConfig:
    """Main application configuration class that aggregates all config sections."""
    
    def __init__(self):
        self.baselinker = BaseLinkerConfig()
        self.google_drive = GoogleDriveConfig()
        self.email = EmailConfig()
        self.services = ServiceConfig()
        self.logging = LoggingConfig()
        self.environment = AppEnvironment()
    
    @classmethod
    def from_env(cls):
        """Create configuration from environment variables."""
        try:
            config = cls()
            logging.info(f"Configuration loaded for environment: {config.environment.environment}")
            return config
        except ValueError as e:
            logging.error(f"Configuration error: {e}")
            raise
        except Exception as e:
            logging.error(f"Unexpected error loading configuration: {e}")
            raise
    
    def validate(self) -> bool:
        """Validate the configuration."""
        try:
            # Check if required files exist
            service_account_file = self.google_drive.service_account_file
            
            # If path is relative, make it absolute from project root
            if not os.path.isabs(service_account_file):
                # Get the project root (parent of shared directory)
                current_dir = os.path.dirname(os.path.abspath(__file__))
                project_root = os.path.dirname(current_dir)
                service_account_file = os.path.join(project_root, service_account_file)
            
            if not os.path.exists(service_account_file):
                raise ValueError(f"Google Drive service account file not found: {service_account_file}")
            
            logging.info("Configuration validation passed")
            return True
        except Exception as e:
            logging.error(f"Configuration validation failed: {e}")
            return False