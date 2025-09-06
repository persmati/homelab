from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from google.oauth2 import service_account
from googleapiclient.discovery import build
import logging
import sys
import os
from typing import Dict, List, Tuple, Optional
from dotenv import load_dotenv
import uvicorn

# Load environment variables from .env file
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

# Add shared module to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.config import AppConfig
from shared.cache import cache_drive_search

app = FastAPI()

# Pydantic models for request validation
class CheckFilesRequest(BaseModel):
    required_files: List[str]
    share_email: Optional[str] = None

class FileService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.scopes = config.google_drive.scopes
        self.service_account_file = config.google_drive.service_account_file
        self.folder_id = config.google_drive.folder_id
        
    def create_drive_service(self):
        service_account_file = self.service_account_file
        
        # If path is relative, make it absolute from project root
        if not os.path.isabs(service_account_file):
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(current_dir))
            service_account_file = os.path.join(project_root, service_account_file)
        
        credentials = service_account.Credentials.from_service_account_file(
            service_account_file,
            scopes=self.scopes
        )
        return build('drive', 'v3', credentials=credentials)
    
    def share_file_with_viewer(self, service, file_id: str, email: str) -> bool:
        try:
            user_permission = {
                'type': 'user',
                'role': 'reader',
                'emailAddress': email
            }
            
            service.permissions().create(
                fileId=file_id,
                body=user_permission,
                sendNotificationEmail=False
            ).execute()
            
            return True
        except Exception as e:
            logging.error(f"Error sharing file: {e}")
            return False
    
    @cache_drive_search
    def get_drive_files(self, required_files: List[str], share_email: str = None) -> Tuple[Dict, List]:
        if share_email is None:
            share_email = self.config.google_drive.share_email
            
        service = self.create_drive_service()
        
        try:
            # Build search query for specific files to reduce API calls
            required_files_lower = [f.lower() for f in required_files]
            
            # Create a query that searches for specific files only
            file_queries = []
            for file_name in required_files_lower:
                # Remove .pdf extension if present for search
                base_name = file_name.replace('.pdf', '') if file_name.endswith('.pdf') else file_name
                file_queries.append(f"name contains '{base_name}'")
            
            # Combine queries with OR operator and limit to parent folder
            search_query = f"'{self.folder_id}' in parents and ({' or '.join(file_queries)})"
            
            logging.info(f"Optimized search query: {search_query}")
            
            # Single API call with targeted search
            results = service.files().list(
                q=search_query,
                pageSize=1000,  # Should be more than enough for specific files
                fields="files(id, name, webViewLink)"
            ).execute()
            
            found_files = results.get('files', [])
            logging.info(f"Found {len(found_files)} files matching search criteria")
            
            # Create lookup dictionary
            available_files = {}
            found_file_names = set()
            
            for file in found_files:
                file_name_lower = file['name'].lower()
                available_files[file_name_lower] = file
                found_file_names.add(file_name_lower)
                
                # Also check for .pdf extension matches
                if not file_name_lower.endswith('.pdf'):
                    pdf_name = f"{file_name_lower}.pdf"
                    if pdf_name in required_files_lower:
                        available_files[pdf_name] = file
                        found_file_names.add(pdf_name)
            
            # Share only the found files (much faster)
            for file in found_files:
                self.share_file_with_viewer(service, file['id'], share_email)
            
            # Determine missing files
            missing_files = [name for name in required_files if name.lower() not in found_file_names]
            
            logging.info(f"Available files: {len(available_files)}, Missing files: {len(missing_files)}")
            
            return available_files, missing_files
            
        except Exception as e:
            logging.error(f"Error accessing Drive: {e}")
            return {}, []
    
    def get_format_info(self, filename: str) -> str:
        filename_lower = filename.lower()
        
        if filename_lower.endswith('_b2') or '_b2' in filename_lower:
            return "format 50 x 70 cm"
        elif filename_lower.endswith('45'):
            return "format 40x50 cm"
        elif '_a3' in filename_lower:
            return "format 30x40 cm"
        else:
            return ""

# Initialize configuration and file service
config = AppConfig.from_env()
file_service = FileService(config)

@app.get('/health')
def health_check():
    return {"status": "healthy", "service": "file-service"}

@app.post('/files/check')
def check_files(request_data: CheckFilesRequest):
    share_email = request_data.share_email or config.google_drive.share_email
    
    available_files, missing_files = file_service.get_drive_files(request_data.required_files, share_email)
    
    return {
        "available_files": available_files,
        "missing_files": missing_files,
        "total_found": len(available_files)
    }

@app.get('/files/format')
def get_format(filename: str = ''):
    format_info = file_service.get_format_info(filename)
    return {"filename": filename, "format_info": format_info}

@app.post('/files/cache/clear')
def clear_cache():
    """Clear the Google Drive file cache."""
    try:
        from shared.cache import memory_cache, file_cache
        
        memory_cache.clear()
        # Clear file cache directory
        import shutil
        cache_dir = file_cache.cache_dir
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            cache_dir.mkdir(exist_ok=True)
        
        return {"success": True, "message": "Cache cleared successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})

@app.get('/files/cache/stats')
def cache_stats():
    """Get cache statistics."""
    try:
        from shared.cache import memory_cache
        stats = memory_cache.stats()
        return {"success": True, "cache_stats": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})

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
        
    logging.info("Starting file service...")
    uvicorn.run(
        "app:app",
        host='0.0.0.0', 
        port=5002, 
        reload=True,
        log_level="info" if not config.environment.debug else "debug"
    )
