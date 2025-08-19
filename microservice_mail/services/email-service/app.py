from flask import Flask, request, jsonify
import smtplib
from email.mime.text import MIMEText
import logging
import sys
import os
from typing import Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

# Add shared module to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.config import AppConfig
from shared.utils import retry_on_failure, validate_request_data, format_error_response, format_success_response, validate_email

app = Flask(__name__)

class EmailService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.gmail_user = config.email.gmail_user
        self.gmail_password = config.email.gmail_password
        self.smtp_server = config.email.smtp_server
        self.smtp_port = config.email.smtp_port
    
    @retry_on_failure(max_retries=3, delay=1.0)
    def send_email(self, to_email: str, subject: str, body: str) -> Dict[str, Any]:
        # Validate email address
        if not validate_email(to_email):
            raise ValueError(f"Invalid email address: {to_email}")
        
        # Validate inputs
        if not subject or not body:
            raise ValueError("Subject and body cannot be empty")
        
        try:
            msg = MIMEText(body.encode('utf-8'), 'plain', 'utf-8')
            msg['Subject'] = subject
            msg['From'] = self.gmail_user
            msg['To'] = to_email
            
            server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
            server.login(self.gmail_user, self.gmail_password)
            server.send_message(msg)
            server.close()
            
            logging.info(f'Email sent successfully to {to_email}')
            return {"success": True, "message": f"Email sent to {to_email}"}
            
        except smtplib.SMTPAuthenticationError as e:
            logging.error(f"SMTP authentication failed: {e}")
            raise Exception("Email authentication failed. Check credentials.")
        except smtplib.SMTPRecipientsRefused as e:
            logging.error(f"SMTP recipients refused: {e}")
            raise Exception(f"Email recipient refused: {to_email}")
        except smtplib.SMTPException as e:
            logging.error(f"SMTP error: {e}")
            raise Exception(f"Email sending failed: {str(e)}")
        except Exception as e:
            logging.error(f"Unexpected error sending email: {e}")
            raise
    
    def create_print_order_email(self, files_data: Dict[str, Any], available_files: Dict[str, Any]) -> str:
        email_body = "Dzień dobry,\n\nPrzesyłam pliki do druku:\n\n"
        
        for filename, quantity in files_data.get('quantities', {}).items():
            if filename.lower() in available_files:
                file_info = available_files[filename.lower()]
                format_info = self.get_format_info(filename)
                email_body += f"{filename} -- {quantity} szt. {format_info}\n"
                email_body += f"Link: {file_info['webViewLink']}\n\n"
        
        email_body += "\nPozdrawiam"
        return email_body
    
    def create_missing_files_email(self, order_ids: list, missing_files: list, quantities: Dict[str, int]) -> str:
        email_body = f"Brakujące pliki dla zamówień: {', '.join(order_ids)}\n\n"
        
        for filename in missing_files:
            quantity = quantities.get(filename, 'N/A')
            email_body += f"{filename} -- {quantity} szt.\n"
        
        return email_body
    
    def get_format_info(self, filename: str) -> str:
        filename_lower = filename.lower()
        
        if filename_lower.endswith('_b2') or '_b2' in filename_lower:
            return "format 50 x 70 cm"
        elif filename_lower.endswith('_45'):
            return "format 40x50 cm"
        elif '_a3' in filename_lower:
            return "format 30x40 cm"
        else:
            return ""

# Initialize configuration and email service
config = AppConfig.from_env()
email_service = EmailService(config)

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "service": "email-service"})

@app.route('/email/send', methods=['POST'])
@validate_request_data(['to_email', 'subject', 'body'])
def send_email():
    try:
        data = request.get_json()
        result = email_service.send_email(
            data['to_email'],
            data['subject'],
            data['body']
        )
        return jsonify(format_success_response(result)), 200
    except ValueError as e:
        return jsonify(format_error_response(str(e), "VALIDATION_ERROR")), 400
    except Exception as e:
        return jsonify(format_error_response(str(e), "EMAIL_SEND_ERROR")), 500

@app.route('/email/print-order', methods=['POST'])
@validate_request_data(['files_data', 'available_files'], ['to_email', 'subject'])
def send_print_order_email():
    try:
        data = request.get_json()
        files_data = data['files_data']
        available_files = data['available_files']
        to_email = data.get('to_email', config.email.print_email)
        subject = data.get('subject', 'Plakaty do druku')
        
        email_body = email_service.create_print_order_email(files_data, available_files)
        result = email_service.send_email(to_email, subject, email_body)
        
        return jsonify(format_success_response({
            "email_sent": result,
            "email_body": email_body,
            "recipient": to_email
        })), 200
    except ValueError as e:
        return jsonify(format_error_response(str(e), "VALIDATION_ERROR")), 400
    except Exception as e:
        return jsonify(format_error_response(str(e), "PRINT_ORDER_EMAIL_ERROR")), 500

@app.route('/email/missing-files', methods=['POST'])
@validate_request_data(['order_ids', 'missing_files', 'quantities'], ['to_email', 'subject'])
def send_missing_files_email():
    try:
        data = request.get_json()
        order_ids = data['order_ids']
        missing_files = data['missing_files']
        quantities = data['quantities']
        to_email = data.get('to_email', config.email.admin_email)
        subject = data.get('subject', 'BRAK PLIKÓW - Plakaty')
        
        if not order_ids or not missing_files:
            raise ValueError("Order IDs and missing files cannot be empty")
        
        email_body = email_service.create_missing_files_email(order_ids, missing_files, quantities)
        result = email_service.send_email(to_email, subject, email_body)
        
        return jsonify(format_success_response({
            "email_sent": result,
            "email_body": email_body,
            "recipient": to_email,
            "missing_files_count": len(missing_files)
        })), 200
    except ValueError as e:
        return jsonify(format_error_response(str(e), "VALIDATION_ERROR")), 400
    except Exception as e:
        return jsonify(format_error_response(str(e), "MISSING_FILES_EMAIL_ERROR")), 500

if __name__ == '__main__':
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, config.logging.log_level),
        format=config.logging.log_format
    )
    
    # Validate configuration
    if not config.validate():
        logging.error("Configuration validation failed. Exiting.")
        sys.exit(1)
        
    logging.info("Starting email service...")
    app.run(host='0.0.0.0', port=5003, debug=config.environment.debug)