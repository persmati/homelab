from fastapi import FastAPI, HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
import smtplib
from email.mime.text import MIMEText
import logging
import sys
import os
import time
import uuid
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import uvicorn
from datetime import datetime
import json
import traceback

# Load environment variables from .env file
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

# Add shared module to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.config import AppConfig
from shared.utils import retry_on_failure, format_error_response, format_success_response, validate_email
from shared.logging_config import LoggerSetup

# Initialize configuration first
config = AppConfig.from_env()

# Setup advanced logging
logger = LoggerSetup.setup_logger("email_service", config.logging, "email_service.log")
security_logger = LoggerSetup.setup_logger("email_service.security", config.logging, "email_security.log")
performance_logger = LoggerSetup.setup_logger("email_service.performance", config.logging, "email_performance.log")
audit_logger = LoggerSetup.setup_logger("email_service.audit", config.logging, "email_audit.log")

class LoggingMiddleware(BaseHTTPMiddleware):
    """Advanced logging middleware for request/response tracking and performance monitoring."""
    
    async def dispatch(self, request: Request, call_next):
        # Generate request ID for tracing
        request_id = str(uuid.uuid4())
        start_time = time.time()
        
        # Log incoming request
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        
        logger.info(
            f"Request started",
            extra={
                "request_id": request_id,
                "method": request.method,
                "url": str(request.url),
                "client_ip": client_ip,
                "user_agent": user_agent,
                "timestamp": datetime.now().isoformat()
            }
        )
        
        # Security logging for sensitive endpoints
        if request.url.path.startswith("/email/"):
            security_logger.info(
                f"Email service access",
                extra={
                    "request_id": request_id,
                    "endpoint": request.url.path,
                    "client_ip": client_ip,
                    "user_agent": user_agent,
                    "timestamp": datetime.now().isoformat()
                }
            )
        
        try:
            # Add request_id to request state for use in handlers
            request.state.request_id = request_id
            response = await call_next(request)
            
            # Calculate response time
            process_time = time.time() - start_time
            
            # Log response
            logger.info(
                f"Request completed",
                extra={
                    "request_id": request_id,
                    "status_code": response.status_code,
                    "process_time": f"{process_time:.4f}s",
                    "timestamp": datetime.now().isoformat()
                }
            )
            
            # Performance logging
            performance_logger.info(
                f"Request performance",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "endpoint": request.url.path,
                    "status_code": response.status_code,
                    "process_time": process_time,
                    "timestamp": datetime.now().isoformat()
                }
            )
            
            # Set response headers for tracing
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time"] = f"{process_time:.4f}s"
            
            return response
            
        except Exception as e:
            process_time = time.time() - start_time
            
            logger.error(
                f"Request failed with exception",
                extra={
                    "request_id": request_id,
                    "error": str(e),
                    "process_time": f"{process_time:.4f}s",
                    "traceback": traceback.format_exc(),
                    "timestamp": datetime.now().isoformat()
                }
            )
            raise

app = FastAPI()
app.add_middleware(LoggingMiddleware)

# Pydantic models for request validation
class SendEmailRequest(BaseModel):
    to_email: str
    subject: str
    body: str

class PrintOrderRequest(BaseModel):
    files_data: Dict[str, Any]
    available_files: Dict[str, Any]
    to_email: Optional[str] = None
    subject: Optional[str] = None

class MissingFilesRequest(BaseModel):
    order_ids: list
    missing_files: list
    quantities: Dict[str, int]
    to_email: Optional[str] = None
    subject: Optional[str] = None

class EmailService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.gmail_user = config.email.gmail_user
        self.gmail_password = config.email.gmail_password
        self.smtp_server = config.email.smtp_server
        self.smtp_port = config.email.smtp_port
        self.email_send_count = 0
        
        # Log service initialization
        logger.info(
            "EmailService initialized",
            extra={
                "smtp_server": self.smtp_server,
                "smtp_port": self.smtp_port,
                "gmail_user": self.gmail_user[:5] + "*****" if self.gmail_user else "not_set",
                "timestamp": datetime.now().isoformat()
            }
        )
    
    def _log_email_attempt(self, request_id: str, to_email: str, subject: str, body_length: int):
        """Log email sending attempt with details."""
        audit_logger.info(
            "Email send attempt",
            extra={
                "request_id": request_id,
                "to_email_masked": to_email[:3] + "*****" + to_email[-5:] if len(to_email) > 8 else "****",
                "subject": subject,
                "body_length": body_length,
                "attempt_timestamp": datetime.now().isoformat()
            }
        )
    
    def _log_email_success(self, request_id: str, to_email: str, subject: str, processing_time: float):
        """Log successful email sending."""
        self.email_send_count += 1
        
        audit_logger.info(
            "Email sent successfully",
            extra={
                "request_id": request_id,
                "to_email_masked": to_email[:3] + "*****" + to_email[-5:] if len(to_email) > 8 else "****",
                "subject": subject,
                "processing_time": processing_time,
                "total_emails_sent": self.email_send_count,
                "success_timestamp": datetime.now().isoformat()
            }
        )
        
        performance_logger.info(
            "Email processing performance",
            extra={
                "request_id": request_id,
                "operation": "send_email",
                "processing_time": processing_time,
                "success": True,
                "timestamp": datetime.now().isoformat()
            }
        )
    
    def _log_email_failure(self, request_id: str, to_email: str, subject: str, error: str, error_type: str, processing_time: float):
        """Log email sending failure with detailed error information."""
        security_logger.warning(
            "Email send failure",
            extra={
                "request_id": request_id,
                "to_email_masked": to_email[:3] + "*****" + to_email[-5:] if len(to_email) > 8 else "****",
                "subject": subject,
                "error_type": error_type,
                "error_message": error,
                "processing_time": processing_time,
                "failure_timestamp": datetime.now().isoformat()
            }
        )
    
    @retry_on_failure(max_retries=3, delay=1.0)
    def send_email(self, to_email: str, subject: str, body: str, request_id: str = None) -> Dict[str, Any]:
        start_time = time.time()
        request_id = request_id or str(uuid.uuid4())
        
        logger.info(
            f"Starting email send process",
            extra={
                "request_id": request_id,
                "to_email_domain": to_email.split('@')[1] if '@' in to_email else "unknown",
                "subject_length": len(subject),
                "body_length": len(body),
                "timestamp": datetime.now().isoformat()
            }
        )
        
        # Log the attempt
        self._log_email_attempt(request_id, to_email, subject, len(body))
        
        # Validate email address
        if not validate_email(to_email):
            error_msg = f"Invalid email address: {to_email}"
            processing_time = time.time() - start_time
            self._log_email_failure(request_id, to_email, subject, error_msg, "VALIDATION_ERROR", processing_time)
            raise ValueError(error_msg)
        
        # Validate inputs
        if not subject or not body:
            error_msg = "Subject and body cannot be empty"
            processing_time = time.time() - start_time
            self._log_email_failure(request_id, to_email, subject, error_msg, "VALIDATION_ERROR", processing_time)
            raise ValueError(error_msg)
        
        try:
            logger.debug(
                f"Creating email message",
                extra={
                    "request_id": request_id,
                    "from_email": self.gmail_user,
                    "to_email": to_email,
                    "timestamp": datetime.now().isoformat()
                }
            )
            
            msg = MIMEText(body.encode('utf-8'), 'plain', 'utf-8')
            msg['Subject'] = subject
            msg['From'] = self.gmail_user
            msg['To'] = to_email
            
            logger.debug(
                f"Connecting to SMTP server",
                extra={
                    "request_id": request_id,
                    "smtp_server": self.smtp_server,
                    "smtp_port": self.smtp_port,
                    "timestamp": datetime.now().isoformat()
                }
            )
            
            server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
            server.login(self.gmail_user, self.gmail_password)
            server.send_message(msg)
            server.close()
            
            processing_time = time.time() - start_time
            
            logger.info(
                f'Email sent successfully to {to_email}',
                extra={
                    "request_id": request_id,
                    "processing_time": f"{processing_time:.4f}s",
                    "timestamp": datetime.now().isoformat()
                }
            )
            
            self._log_email_success(request_id, to_email, subject, processing_time)
            
            return {"success": True, "message": f"Email sent to {to_email}", "processing_time": processing_time}
            
        except smtplib.SMTPAuthenticationError as e:
            processing_time = time.time() - start_time
            error_msg = "Email authentication failed. Check credentials."
            self._log_email_failure(request_id, to_email, subject, str(e), "SMTP_AUTH_ERROR", processing_time)
            logger.error(
                f"SMTP authentication failed",
                extra={
                    "request_id": request_id,
                    "error": str(e),
                    "processing_time": f"{processing_time:.4f}s",
                    "timestamp": datetime.now().isoformat()
                }
            )
            raise Exception(error_msg)
        except smtplib.SMTPRecipientsRefused as e:
            processing_time = time.time() - start_time
            error_msg = f"Email recipient refused: {to_email}"
            self._log_email_failure(request_id, to_email, subject, str(e), "SMTP_RECIPIENT_ERROR", processing_time)
            logger.error(
                f"SMTP recipients refused",
                extra={
                    "request_id": request_id,
                    "error": str(e),
                    "processing_time": f"{processing_time:.4f}s",
                    "timestamp": datetime.now().isoformat()
                }
            )
            raise Exception(error_msg)
        except smtplib.SMTPException as e:
            processing_time = time.time() - start_time
            error_msg = f"Email sending failed: {str(e)}"
            self._log_email_failure(request_id, to_email, subject, str(e), "SMTP_ERROR", processing_time)
            logger.error(
                f"SMTP error",
                extra={
                    "request_id": request_id,
                    "error": str(e),
                    "processing_time": f"{processing_time:.4f}s",
                    "timestamp": datetime.now().isoformat()
                }
            )
            raise Exception(error_msg)
        except Exception as e:
            processing_time = time.time() - start_time
            self._log_email_failure(request_id, to_email, subject, str(e), "UNEXPECTED_ERROR", processing_time)
            logger.error(
                f"Unexpected error sending email",
                extra={
                    "request_id": request_id,
                    "error": str(e),
                    "processing_time": f"{processing_time:.4f}s",
                    "traceback": traceback.format_exc(),
                    "timestamp": datetime.now().isoformat()
                }
            )
            raise
    
    def create_print_order_email(self, files_data: Dict[str, Any], available_files: Dict[str, Any], request_id: str = None) -> str:
        request_id = request_id or str(uuid.uuid4())
        
        logger.info(
            "Creating print order email",
            extra={
                "request_id": request_id,
                "file_count": len(files_data.get('quantities', {})),
                "available_files_count": len(available_files),
                "timestamp": datetime.now().isoformat()
            }
        )
        
        email_body = "Dzień dobry,\n\nPrzesyłam pliki do druku:\n\n"
        processed_files = 0
        
        for filename, quantity in files_data.get('quantities', {}).items():
            if filename.lower() in available_files:
                file_info = available_files[filename.lower()]
                format_info = self.get_format_info(filename)
                email_body += f"{filename} -- {quantity} szt. {format_info}\n"
                email_body += f"Link: {file_info['webViewLink']}\n\n"
                processed_files += 1
                
                logger.debug(
                    f"Processed file for print order",
                    extra={
                        "request_id": request_id,
                        "filename": filename,
                        "quantity": quantity,
                        "format_info": format_info,
                        "timestamp": datetime.now().isoformat()
                    }
                )
        
        email_body += "\nPozdrawiam"
        
        audit_logger.info(
            "Print order email created",
            extra={
                "request_id": request_id,
                "processed_files": processed_files,
                "email_body_length": len(email_body),
                "timestamp": datetime.now().isoformat()
            }
        )
        
        return email_body
    
    def create_missing_files_email(self, order_ids: list, missing_files: list, quantities: Dict[str, int], request_id: str = None) -> str:
        request_id = request_id or str(uuid.uuid4())
        
        logger.info(
            "Creating missing files email",
            extra={
                "request_id": request_id,
                "order_count": len(order_ids),
                "missing_files_count": len(missing_files),
                "timestamp": datetime.now().isoformat()
            }
        )
        
        email_body = f"Brakujące pliki dla zamówień: {', '.join(order_ids)}\n\n"
        
        for filename in missing_files:
            quantity = quantities.get(filename, 'N/A')
            email_body += f"{filename} -- {quantity} szt.\n"
            
            logger.debug(
                f"Added missing file to email",
                extra={
                    "request_id": request_id,
                    "filename": filename,
                    "quantity": quantity,
                    "timestamp": datetime.now().isoformat()
                }
            )
        
        audit_logger.info(
            "Missing files email created",
            extra={
                "request_id": request_id,
                "order_ids": order_ids,
                "missing_files_count": len(missing_files),
                "email_body_length": len(email_body),
                "timestamp": datetime.now().isoformat()
            }
        )
        
        return email_body
    
    def get_format_info(self, filename: str) -> str:
        filename_lower = filename.lower()
        
        format_info = ""
        if filename_lower.endswith('_b2') or '_b2' in filename_lower:
            format_info = "format 50 x 70 cm"
        elif filename_lower.endswith('_45'):
            format_info = "format 40x50 cm"
        elif '_a3' in filename_lower:
            format_info = "format 30x40 cm"
        
        logger.debug(
            f"Format info determined",
            extra={
                "filename": filename,
                "format_info": format_info if format_info else "no_specific_format",
                "timestamp": datetime.now().isoformat()
            }
        )
        
        return format_info

# Initialize email service
email_service = EmailService(config)

@app.get('/health')
def health_check(request: Request):
    request_id = getattr(request.state, 'request_id', str(uuid.uuid4()))
    
    logger.info(
        "Health check accessed",
        extra={
            "request_id": request_id,
            "email_service_status": "healthy",
            "total_emails_sent": email_service.email_send_count,
            "timestamp": datetime.now().isoformat()
        }
    )
    
    return {
        "status": "healthy", 
        "service": "email-service",
        "request_id": request_id,
        "total_emails_sent": email_service.email_send_count
    }

@app.post('/email/send')
def send_email(request_data: SendEmailRequest, request: Request):
    request_id = getattr(request.state, 'request_id', str(uuid.uuid4()))
    
    logger.info(
        "Send email endpoint called",
        extra={
            "request_id": request_id,
            "to_email_domain": request_data.to_email.split('@')[1] if '@' in request_data.to_email else "unknown",
            "subject_length": len(request_data.subject),
            "body_length": len(request_data.body),
            "timestamp": datetime.now().isoformat()
        }
    )
    
    try:
        result = email_service.send_email(
            request_data.to_email,
            request_data.subject,
            request_data.body,
            request_id
        )
        
        audit_logger.info(
            "Send email endpoint success",
            extra={
                "request_id": request_id,
                "endpoint": "/email/send",
                "success": True,
                "timestamp": datetime.now().isoformat()
            }
        )
        
        return format_success_response(result)
    except ValueError as e:
        logger.warning(
            f"Validation error in send email endpoint",
            extra={
                "request_id": request_id,
                "error": str(e),
                "error_type": "VALIDATION_ERROR",
                "timestamp": datetime.now().isoformat()
            }
        )
        raise HTTPException(status_code=400, detail=format_error_response(str(e), "VALIDATION_ERROR"))
    except Exception as e:
        logger.error(
            f"Error in send email endpoint",
            extra={
                "request_id": request_id,
                "error": str(e),
                "error_type": "EMAIL_SEND_ERROR",
                "traceback": traceback.format_exc(),
                "timestamp": datetime.now().isoformat()
            }
        )
        raise HTTPException(status_code=500, detail=format_error_response(str(e), "EMAIL_SEND_ERROR"))

@app.post('/email/print-order')
def send_print_order_email(request_data: PrintOrderRequest, request: Request):
    request_id = getattr(request.state, 'request_id', str(uuid.uuid4()))
    
    logger.info(
        "Print order email endpoint called",
        extra={
            "request_id": request_id,
            "files_count": len(request_data.files_data.get('quantities', {})),
            "available_files_count": len(request_data.available_files),
            "has_custom_recipient": request_data.to_email is not None,
            "has_custom_subject": request_data.subject is not None,
            "timestamp": datetime.now().isoformat()
        }
    )
    
    try:
        files_data = request_data.files_data
        available_files = request_data.available_files
        to_email = config.email.recipient_email
        subject = request_data.subject or 'Plakaty do druku'
        
        email_body = email_service.create_print_order_email(files_data, available_files, request_id)
        result = email_service.send_email(to_email, subject, email_body, request_id)
        
        audit_logger.info(
            "Print order email sent successfully",
            extra={
                "request_id": request_id,
                "endpoint": "/email/print-order",
                "recipient": to_email,
                "files_processed": len([f for f in files_data.get('quantities', {}).keys() if f.lower() in available_files]),
                "success": True,
                "timestamp": datetime.now().isoformat()
            }
        )
        
        return format_success_response({
            "email_sent": result,
            "email_body": email_body,
            "recipient": to_email,
            "request_id": request_id
        })
    except ValueError as e:
        logger.warning(
            f"Validation error in print order endpoint",
            extra={
                "request_id": request_id,
                "error": str(e),
                "error_type": "VALIDATION_ERROR",
                "timestamp": datetime.now().isoformat()
            }
        )
        raise HTTPException(status_code=400, detail=format_error_response(str(e), "VALIDATION_ERROR"))
    except Exception as e:
        logger.error(
            f"Error in print order endpoint",
            extra={
                "request_id": request_id,
                "error": str(e),
                "error_type": "PRINT_ORDER_EMAIL_ERROR",
                "traceback": traceback.format_exc(),
                "timestamp": datetime.now().isoformat()
            }
        )
        raise HTTPException(status_code=500, detail=format_error_response(str(e), "PRINT_ORDER_EMAIL_ERROR"))

@app.post('/email/missing-files')
def send_missing_files_email(request_data: MissingFilesRequest, request: Request):
    request_id = getattr(request.state, 'request_id', str(uuid.uuid4()))
    
    logger.info(
        "Missing files email endpoint called",
        extra={
            "request_id": request_id,
            "order_count": len(request_data.order_ids),
            "missing_files_count": len(request_data.missing_files),
            "has_custom_recipient": request_data.to_email is not None,
            "has_custom_subject": request_data.subject is not None,
            "timestamp": datetime.now().isoformat()
        }
    )
    
    try:
        order_ids = request_data.order_ids
        missing_files = request_data.missing_files
        quantities = request_data.quantities
        to_email = config.email.admin_email
        subject = request_data.subject or 'BRAK PLIKÓW - Plakaty'
        
        if not order_ids or not missing_files:
            raise ValueError("Order IDs and missing files cannot be empty")
        
        email_body = email_service.create_missing_files_email(order_ids, missing_files, quantities, request_id)
        result = email_service.send_email(to_email, subject, email_body, request_id)
        
        audit_logger.info(
            "Missing files email sent successfully",
            extra={
                "request_id": request_id,
                "endpoint": "/email/missing-files",
                "recipient": to_email,
                "order_ids": order_ids,
                "missing_files_count": len(missing_files),
                "success": True,
                "timestamp": datetime.now().isoformat()
            }
        )
        
        return format_success_response({
            "email_sent": result,
            "email_body": email_body,
            "recipient": to_email,
            "missing_files_count": len(missing_files),
            "request_id": request_id
        })
    except ValueError as e:
        logger.warning(
            f"Validation error in missing files endpoint",
            extra={
                "request_id": request_id,
                "error": str(e),
                "error_type": "VALIDATION_ERROR",
                "timestamp": datetime.now().isoformat()
            }
        )
        raise HTTPException(status_code=400, detail=format_error_response(str(e), "VALIDATION_ERROR"))
    except Exception as e:
        logger.error(
            f"Error in missing files endpoint",
            extra={
                "request_id": request_id,
                "error": str(e),
                "error_type": "MISSING_FILES_EMAIL_ERROR",
                "traceback": traceback.format_exc(),
                "timestamp": datetime.now().isoformat()
            }
        )
        raise HTTPException(status_code=500, detail=format_error_response(str(e), "MISSING_FILES_EMAIL_ERROR"))

if __name__ == '__main__':
    # Setup advanced logging
    service_logger = LoggerSetup.setup_fastapi_logging(app, config.logging, "email_service")
    
    # Validate configuration
    if not config.validate():
        logger.error("Configuration validation failed. Exiting.")
        sys.exit(1)
    
    logger.info(
        "Starting email service with advanced logging",
        extra={
            "service": "email-service",
            "port": 5003,
            "debug_mode": config.environment.debug,
            "log_level": config.logging.log_level,
            "log_dir": config.logging.log_dir,
            "smtp_server": config.email.smtp_server,
            "startup_timestamp": datetime.now().isoformat()
        }
    )
    
    # Log service configuration (safely)
    logger.info(
        "Email service configuration loaded",
        extra={
            "gmail_user_configured": bool(config.email.gmail_user),
            "gmail_password_configured": bool(config.email.gmail_password),
            "print_email_configured": bool(config.email.print_email),
            "admin_email_configured": bool(config.email.admin_email),
            "recipient_email_configured": bool(config.email.recipient_email),
            "recipient_email": config.email.recipient_email if config.email.recipient_email else "not_set",
            "smtp_server": config.email.smtp_server,
            "smtp_port": config.email.smtp_port,
            "timestamp": datetime.now().isoformat()
        }
    )
    
    try:
        uvicorn.run(
            "app:app",
            host='0.0.0.0', 
            port=5003, 
            reload=True,
            log_level="info" if not config.environment.debug else "debug"
        )
    except Exception as e:
        logger.critical(
            "Failed to start email service",
            extra={
                "error": str(e),
                "traceback": traceback.format_exc(),
                "timestamp": datetime.now().isoformat()
            }
        )
        sys.exit(1)
