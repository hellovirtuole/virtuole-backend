import os
from supabase import create_client, Client
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask import request

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None

def get_real_client_ip():
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.remote_addr

limiter = Limiter(
    key_func=get_real_client_ip, 
    storage_uri="memory://",
    default_limits=["200 per day", "50 per hour"]
)
