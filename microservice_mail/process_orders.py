#!/usr/bin/env python3
"""
Manual order processing trigger
Quick way to process orders without curl
"""

import requests
import json
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Setup paths and environment
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load environment
env_file = project_root / '.env'
if env_file.exists():
    load_dotenv(env_file)

from shared.config import AppConfig

def main():
    try:
        config = AppConfig.from_env()
        orchestrator_url = f"http://localhost:{config.services.orchestrator_port}"
        
        print("🔍 Processing orders...")
        print(f"📊 Orchestrator URL: {orchestrator_url}")
        print()
        
        # Check health first
        try:
            health_response = requests.get(f"{orchestrator_url}/services/health", timeout=10)
            if health_response.status_code == 200:
                health_data = health_response.json()
                services_health = health_data.get('services', {})
                
                print("🩺 Service Health Check:")
                for service, healthy in services_health.items():
                    status = "✅ Healthy" if healthy else "❌ Unhealthy"
                    print(f"  {service}: {status}")
                print()
                
                if not all(services_health.values()):
                    print("⚠️  Some services are unhealthy. Processing may fail.")
                    print()
            else:
                print("⚠️  Could not check service health")
                print()
        except:
            print("⚠️  Could not connect to orchestrator for health check")
            print()
        
        # Process orders
        print("🚀 Starting order processing...")
        
        response = requests.post(f"{orchestrator_url}/process", timeout=120)
        
        if response.status_code == 200:
            result = response.json()
            
            print("✅ Order processing completed!")
            print()
            
            if result.get("success"):
                print("📊 Results:")
                results = result.get("results", {})
                
                if results:
                    print(f"  📦 Orders processed: {results.get('orders_processed', 0)}")
                    print(f"  📁 Files found: {results.get('files_found', 0)}")
                    print(f"  ❌ Missing files: {results.get('missing_files', 0)}")
                    print(f"  📧 Emails sent: {results.get('emails_sent', 0)}")
                else:
                    print("  " + result.get("message", "No specific results"))
            else:
                print("❌ Processing failed:")
                print(f"  Error: {result.get('error', 'Unknown error')}")
                return 1
                
        else:
            print(f"❌ Request failed with status {response.status_code}")
            print(f"Response: {response.text}")
            return 1
            
    except requests.exceptions.Timeout:
        print("❌ Request timed out (processing took too long)")
        return 1
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to orchestrator")
        print("Make sure all services are running:")
        print("  docker-compose up -d")
        print("  OR")
        print("  python run_local.py orchestrator")
        return 1
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())