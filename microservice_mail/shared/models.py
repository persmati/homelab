from dataclasses import dataclass
from typing import List, Dict, Any, Optional

@dataclass
class OrderData:
    order_ids: List[str]
    files: List[str]
    quantities: Dict[str, int]

@dataclass
class FileData:
    available_files: Dict[str, Any]
    missing_files: List[str]
    total_found: int

@dataclass
class EmailRequest:
    to_email: str
    subject: str
    body: str

@dataclass
class PrintOrderEmailRequest:
    files_data: OrderData
    available_files: Dict[str, Any]
    to_email: Optional[str] = None
    subject: Optional[str] = None

@dataclass
class MissingFilesEmailRequest:
    order_ids: List[str]
    missing_files: List[str]
    quantities: Dict[str, int]
    to_email: Optional[str] = None
    subject: Optional[str] = None

@dataclass
class ServiceResponse:
    success: bool
    data: Any = None
    error: str = None