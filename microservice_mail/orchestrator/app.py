from flask import Flask, jsonify
import requests
import logging
import sys
import os
from typing import Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from shared.config import AppConfig
from shared.models import OrderData, FileData, ServiceResponse
from shared.logging_config import LoggerSetup

app = Flask(__name__)

class OrderOrchestrator:
    def __init__(self, config: AppConfig):
        self.config = config
        self.setup_logging()
        
    def setup_logging(self):
        self.logger = LoggerSetup.setup_logger(
            'orchestrator',
            self.config.logging,
            'orchestrator.log'
        )
    
    def check_service_health(self, service_url: str) -> bool:
        try:
            response = requests.get(f"{service_url}/health", timeout=5)
            return response.status_code == 200
        except Exception as e:
            self.logger.error(f"Health check failed for {service_url}: {e}")
            return False
    
    def check_for_new_orders(self, days_ago: int = 3) -> bool:
        try:
            response = requests.get(
                f"{self.config.services.order_service_url}/orders/check",
                params={"days_ago": days_ago}
            )
            if response.status_code == 200:
                return response.json().get("has_new_orders", False)
            return False
        except Exception as e:
            self.logger.error(f"Error checking for new orders: {e}")
            return False
    
    def get_order_details(self, days_ago: int = 3) -> OrderData:
        try:
            response = requests.get(
                f"{self.config.services.order_service_url}/orders/details",
                params={"days_ago": days_ago}
            )
            if response.status_code == 200:
                data = response.json()
                return OrderData(
                    order_ids=data.get('order_ids', []),
                    files=data.get('files', []),
                    quantities=data.get('quantities', {})
                )
            return OrderData([], [], {})
        except Exception as e:
            self.logger.error(f"Error getting order details: {e}")
            return OrderData([], [], {})
    
    def check_files_availability(self, required_files: list) -> FileData:
        try:
            response = requests.post(
                f"{self.config.services.file_service_url}/files/check",
                json={
                    "required_files": required_files,
                    "share_email": self.config.google_drive.share_email
                }
            )
            if response.status_code == 200:
                data = response.json()
                return FileData(
                    available_files=data.get('available_files', {}),
                    missing_files=data.get('missing_files', []),
                    total_found=data.get('total_found', 0)
                )
            return FileData({}, [], 0)
        except Exception as e:
            self.logger.error(f"Error checking file availability: {e}")
            return FileData({}, [], 0)
    
    def send_print_order_email(self, order_data: OrderData, file_data: FileData) -> bool:
        try:
            response = requests.post(
                f"{self.config.services.email_service_url}/email/print-order",
                json={
                    "files_data": {
                        "quantities": order_data.quantities,
                        "order_ids": order_data.order_ids
                    },
                    "available_files": file_data.available_files,
                    "to_email": self.config.email.print_email
                }
            )
            return response.status_code == 200 and response.json().get("success", False)
        except Exception as e:
            self.logger.error(f"Error sending print order email: {e}")
            return False
    
    def send_missing_files_email(self, order_data: OrderData, missing_files: list) -> bool:
        try:
            response = requests.post(
                f"{self.config.services.email_service_url}/email/missing-files",
                json={
                    "order_ids": order_data.order_ids,
                    "missing_files": missing_files,
                    "quantities": order_data.quantities,
                    "to_email": self.config.email.admin_email
                }
            )
            return response.status_code == 200 and response.json().get("success", False)
        except Exception as e:
            self.logger.error(f"Error sending missing files email: {e}")
            return False
    
    def update_order_status(self, order_ids: list) -> bool:
        try:
            response = requests.post(
                f"{self.config.services.order_service_url}/orders/status",
                json={
                    "order_ids": order_ids,
                    "status_id": self.config.baselinker.processed_status_id
                }
            )
            return response.status_code == 200 and response.json().get("success", False)
        except Exception as e:
            self.logger.error(f"Error updating order status: {e}")
            return False
    
    def process_orders(self) -> Dict[str, Any]:
        try:
            # Check if services are healthy
            services = {
                "order-service": self.config.services.order_service_url,
                "file-service": self.config.services.file_service_url,
                "email-service": self.config.services.email_service_url
            }
            
            for service_name, service_url in services.items():
                if not self.check_service_health(service_url):
                    self.logger.error(f"{service_name} is not healthy")
                    return {"success": False, "error": f"{service_name} is not available"}
            
            # Check for new orders
            if not self.check_for_new_orders():
                self.logger.info("No new orders found that meet payment criteria")
                return {"success": True, "message": "No new orders to process"}
            
            self.logger.info("New valid orders found, processing...")
            
            # Get order details
            order_data = self.get_order_details()
            if not order_data.order_ids:
                self.logger.info("No orders met payment criteria after detailed processing")
                return {"success": True, "message": "No valid orders after processing"}
            
            # Check file availability
            file_data = self.check_files_availability(order_data.files)
            
            results = {
                "orders_processed": len(order_data.order_ids),
                "files_found": file_data.total_found,
                "missing_files": len(file_data.missing_files),
                "emails_sent": 0
            }
            
            # Send print order email if files are available
            if file_data.available_files:
                self.logger.info(f"Found {file_data.total_found} files to process for {len(order_data.order_ids)} valid orders")
                if self.send_print_order_email(order_data, file_data):
                    self.logger.info("Print order email sent successfully")
                    results["emails_sent"] += 1
            
            # Send missing files email if any files are missing
            if file_data.missing_files:
                self.logger.warning(f"Missing files found: {file_data.missing_files}")
                if self.send_missing_files_email(order_data, file_data.missing_files):
                    self.logger.info("Missing files notification sent")
                    results["emails_sent"] += 1
            
            # Update order status
            if self.update_order_status(order_data.order_ids):
                self.logger.info(f"Updated status for {len(order_data.order_ids)} orders")
            
            return {"success": True, "results": results}
            
        except Exception as e:
            self.logger.error(f"Error processing orders: {e}")
            return {"success": False, "error": str(e)}

config = AppConfig.from_env()
orchestrator = OrderOrchestrator(config)

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "service": "orchestrator"})

@app.route('/process', methods=['POST'])
def process_orders():
    result = orchestrator.process_orders()
    status_code = 200 if result["success"] else 500
    return jsonify(result), status_code

@app.route('/services/health', methods=['GET'])
def check_all_services():
    services = {
        "order-service": config.services.order_service_url,
        "file-service": config.services.file_service_url,
        "email-service": config.services.email_service_url
    }
    
    health_status = {}
    for service_name, service_url in services.items():
        health_status[service_name] = orchestrator.check_service_health(service_url)
    
    all_healthy = all(health_status.values())
    return jsonify({
        "overall_health": "healthy" if all_healthy else "unhealthy",
        "services": health_status
    })

if __name__ == '__main__':
    try:
        # Setup Flask application logging
        LoggerSetup.setup_flask_logging(app, config.logging, 'orchestrator')
        
        orchestrator.logger.info("Starting order orchestrator service...")
        app.run(
            host='0.0.0.0', 
            port=config.services.orchestrator_port, 
            debug=config.environment.debug
        )
    except Exception as e:
        if 'orchestrator' in locals():
            orchestrator.logger.error(f"Critical error in orchestrator: {e}")
        else:
            print(f"Critical error in orchestrator: {e}")
        sys.exit(1)