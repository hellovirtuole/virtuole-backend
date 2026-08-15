import re
import os

base_dir = r"d:\antigravity\virtuole-platform"
api_dir = os.path.join(base_dir, "api")
os.makedirs(os.path.join(api_dir, 'routes'), exist_ok=True)
index_py_path = os.path.join(api_dir, "index.py")

with open(index_py_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Define section boundaries based on the headers in index.py
sections = re.split(r'# =====================================================================', content)

# sections[0] is the top imports and setup
# sections[1] is 1. SERVER CONFIGURATION & SECURITY
# sections[2] is 2. HTML TEMPLATES (Offer Letters & Certificates)
# sections[3] is 3. EMAIL INFRASTRUCTURE
# sections[4] is 4. SYSTEM MAINTENANCE CRON
# sections[5] is 5. AUTHENTICATION & GATEWAYS (FIXED LOGIN)
# sections[6] is 6. INTERN ACTIONS (Payment & Forms)
# sections[7] is 7. INTERN WORKSPACE ACTIONS
# sections[8] is 8. MENTOR GRADING
# sections[9] is 9. ADMIN ACTIONS (With Soft Delete)
# sections[10] is 10. AMBASSADOR ACTIONS
# sections[11] is 11. DASHBOARD RENDERS
# sections[12] is 12. PUBLIC & RENDERING PATHS (Including Offer Letters)

# We will generate the blueprints and refactor index.py
blueprint_imports = """
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from api.config import supabase, limiter
from api.utils.email import send_system_email, send_ambassador_email
import random, string, uuid, json
from datetime import datetime, timedelta
"""

def write_bp(name, parts, file_path):
    # Find all route decorators and prefix with bp
    bp_code = blueprint_imports + f"\n{name}_bp = Blueprint('{name}', __name__)\n"
    for part in parts:
        # replace @app.route with @{name}_bp.route
        part = re.sub(r'@app\.route', f'@{name}_bp.route', part)
        bp_code += "\n" + part
        

    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(bp_code)


write_bp('auth', [sections[8]], os.path.join(api_dir, 'routes', 'auth.py'))
write_bp('intern', [sections[10], sections[12]], os.path.join(api_dir, 'routes', 'intern.py'))
write_bp('mentor', [sections[14]], os.path.join(api_dir, 'routes', 'mentor.py'))
write_bp('admin', [sections[16]], os.path.join(api_dir, 'routes', 'admin.py'))
write_bp('ambassador', [sections[18]], os.path.join(api_dir, 'routes', 'ambassador.py'))
write_bp('dashboard', [sections[20]], os.path.join(api_dir, 'routes', 'dashboard.py'))
write_bp('public', [sections[22]], os.path.join(api_dir, 'routes', 'public.py'))

# Now reconstruct index.py
new_index = f"""import os
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

load_dotenv()

base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
template_dir = os.path.join(base_dir, 'templates')

app = Flask(__name__, template_folder=template_dir)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "virtuole-secure-master-key-2026")

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=0)

class _VercelFix:
    def __init__(self, wsgi):
        self.wsgi = wsgi
    def __call__(self, environ, start_response):
        import urllib.parse
        original_path = environ.get('HTTP_X_INVOKE_PATH') or environ.get('HTTP_X_NOW_ROUTE_MATCHES')
        if not original_path and 'REQUEST_URI' in environ:
            original_path = environ['REQUEST_URI'].split('?')[0]
            
        if original_path and original_path not in ['/api/index.py', '/api/index']:
            environ['PATH_INFO'] = original_path
        else:
            path = environ.get('PATH_INFO', '/')
            if path == '/api/index.py' or path == '/api/index':
                qs = environ.get('QUERY_STRING', '')
                params = urllib.parse.parse_qs(qs, keep_blank_values=True)
                if '__vercel_path' in params:
                    vp = params['__vercel_path'][0]
                    if vp in ['api/index.py', 'api/index']:
                        environ['PATH_INFO'] = '/'
                    else:
                        environ['PATH_INFO'] = '/' + vp
                    new_params = {{k: v for k, v in params.items() if k != '__vercel_path'}}
                    environ['QUERY_STRING'] = urllib.parse.urlencode(new_params, doseq=True)
                
        script = environ.get('SCRIPT_NAME', '')
        if script and '/api/index' in script:
            environ['SCRIPT_NAME'] = ''
        return self.wsgi(environ, start_response)

app.wsgi_app = _VercelFix(app.wsgi_app)

app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = __import__('datetime').timedelta(days=30)
CORS(app)

@app.route('/favicon.ico')
@app.route('/favicon.png')
def favicon():
    return '', 204

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

# Register Blueprints
from api.routes.auth import auth_bp
from api.routes.intern import intern_bp
from api.routes.mentor import mentor_bp
from api.routes.admin import admin_bp
from api.routes.ambassador import ambassador_bp
from api.routes.dashboard import dashboard_bp
from api.routes.public import public_bp

app.register_blueprint(auth_bp)
app.register_blueprint(intern_bp)
app.register_blueprint(mentor_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(ambassador_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(public_bp)

# Cron Maintenance route
{sections[6].replace('@app.route', '@app.route')}

if __name__ == '__main__':
    app.run(debug=True, port=5000)
"""

with open(index_py_path, 'w', encoding='utf-8') as f:
    f.write(new_index)

print("Modularization complete!")
