from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
import json
import datetime
import logging
import sys
import os
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
import uvicorn

# Load environment variables from .env file
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

# Add shared module to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.config import AppConfig

app = FastAPI()

# Pydantic models for request validation
class UpdateStatusRequest(BaseModel):
    order_ids: List[str]
    status_id: Optional[str] = None

class OrderService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.url = config.baselinker.api_url
        self.token = config.baselinker.token
        self.headers = {'X-BLToken': self.token}
        self.pending_status_id = config.baselinker.pending_status_id
        self.processed_status_id = config.baselinker.processed_status_id
        
    def get_timestamp_for_days_ago(self, days: int) -> int:
        target_date = datetime.datetime.today() - datetime.timedelta(days=days)
        date_string = target_date.strftime('%d/%m/%Y')
        date_obj = datetime.datetime.strptime(date_string, '%d/%m/%Y')
        return int(date_obj.timestamp())
    
    def is_payment_valid(self, order: Dict[str, Any]) -> bool:
        payment_done = order.get('payment_done', 0)
        payment_method_cod = order.get('payment_method_cod', 0)
        return payment_done != 0 or (payment_done == 0 and payment_method_cod == 1)
    
    def check_for_new_orders(self, days_ago: int = 3) -> bool:
        unix_timestamp = self.get_timestamp_for_days_ago(days_ago)
        data = {
            "token": self.token,
            'method': 'getOrders',
            'parameters': json.dumps({
                "date_from": unix_timestamp, 
                "get_unconfirmed_orders": False,
                "status_id": "219626"
            })
        }
        
        response = requests.post(self.url, headers=self.headers, data=data)
        parsed_data = json.loads(response.text)
        orders = parsed_data.get('orders', [])
        
        if not orders:
            return False
        
        valid_orders = [order for order in orders if self.is_payment_valid(order)]
        return bool(valid_orders)
    
    def get_order_details(self, days_ago: int = 3) -> Dict[str, Any]:
        unix_timestamp = self.get_timestamp_for_days_ago(days_ago)
        data = {
            "token": self.token,
            'method': 'getOrders',
            'parameters': json.dumps({
                "date_from": unix_timestamp, 
                "get_unconfirmed_orders": False,
                "status_id": "219626"
            })
        }
        
        response = requests.post(self.url, headers=self.headers, data=data)
        parsed_data = json.loads(response.text)
        orders = parsed_data['orders']
        
        valid_orders = [order for order in orders if self.is_payment_valid(order)]
        
        output = {'files': [], 'quantities': {}, 'order_ids': []}
        
        if not valid_orders:
            return output
        
        for order in valid_orders:
            order_id = order['order_id']
            products = order['products']
            output['order_ids'].append(str(order_id))
            
            for product in products:
                if 'Skarpety' in product.get('name', ''):
                    continue
                sku = product['sku']
                filename = f"{sku}.pdf".lower()
                output['files'].append(filename)
                output['quantities'][filename] = product['quantity']
        
        return output
    
    def update_order_status(self, order_ids: List[str], new_status_id: str = None) -> bool:
        if new_status_id is None:
            new_status_id = self.processed_status_id
        try:
            for order_id_str in order_ids:
                order_id_int = int(order_id_str)
                data = {
                    "token": self.token,
                    'method': 'setOrderStatus',
                    'parameters': json.dumps({
                        "order_id": order_id_int, 
                        "status_id": new_status_id
                    })
                }
                response = requests.post(self.url, headers=self.headers, data=data)
                logging.info(f"Updated status for order {order_id_int}")
            return True
        except Exception as e:
            logging.error(f"Error updating order status: {e}")
            return False

# Initialize configuration and order service
config = AppConfig.from_env()
order_service = OrderService(config)

@app.get('/health')
def health_check():
    return {"status": "healthy", "service": "order-service"}

@app.get('/orders/check')
def check_orders(days_ago: int = 3):
    has_new_orders = order_service.check_for_new_orders(days_ago)
    return {"has_new_orders": has_new_orders}

@app.get('/orders/details')
def get_orders(days_ago: int = 3):
    order_details = order_service.get_order_details(days_ago)
    return order_details

@app.post('/orders/status')
def update_status(request_data: UpdateStatusRequest):
    new_status = request_data.status_id or config.baselinker.processed_status_id
    
    success = order_service.update_order_status(request_data.order_ids, new_status)
    return {"success": success}

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
        
    logging.info("Starting order service...")
    uvicorn.run(
        "app:app",
        host='0.0.0.0', 
        port=5001, 
        reload=True,
        log_level="info" if not config.environment.debug else "debug"
    )
