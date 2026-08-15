import os
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

load_dotenv()

base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
template_dir = os.path.join(base_dir, 'templates')

app = Flask(__name__, template_folder=template_dir, static_folder=os.path.join(base_dir, 'static'))
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
                    new_params = {k: v for k, v in params.items() if k != '__vercel_path'}
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

from api.config import limiter
limiter.init_app(app)

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory(os.path.join(base_dir, 'static'), filename)

# Cron Maintenance route


@app.route('/cron/maintenance', methods=['GET', 'POST'])
@app.route('/api/cron/maintenance', methods=['GET', 'POST'])
def run_maintenance():
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {os.getenv('CRON_SECRET_KEY')}":
        return jsonify({"error": "Unauthorized"}), 401
    
    if not supabase: return jsonify({"error": "No database"}), 500
    
    try:
        now = datetime.utcnow()
        thirty_days_ago = (now - timedelta(days=30)).isoformat()
        supabase.table('enrollments').update({"status": "expired"}).eq('status', 'active').lt('created_at', thirty_days_ago).execute()

        twenty_four_hours_ago = (now - timedelta(hours=24)).isoformat()
        expired_fails = supabase.table('enrollments').select('id', 'user_id').eq('status', 'failed').lt('created_at', twenty_four_hours_ago).execute()
        for row in expired_fails.data:
            supabase.table('enrollments').update({"status": "expired"}).eq('id', row['id']).execute()

        seven_days_ago = (now - timedelta(days=7)).isoformat()
        reminders = supabase.table('enrollments').select('id', 'user_id').eq('status', 'active').gt('created_at', seven_days_ago).execute()
        for row in reminders.data:
            user = supabase.table('users').select('email', 'full_name').eq('id', row['user_id']).execute().data[0]
            send_system_email(user['email'], "Virtuole Internship: Pending Submission Reminder", f"Hello {user['full_name']},\n\nDon't forget to submit your architecture. You have a 30-day window from enrollment to qualify for credentials.")

        expired_ambassadors = supabase.table('users').select('id', 'email', 'full_name').eq('role', 'ambassador').lt('ambassador_expiry', now.isoformat()).execute()
        for row in expired_ambassadors.data:
            supabase.table('users').update({"role": "intern", "promo_code": None, "ambassador_expiry": None}).eq('id', row['id']).execute()
            send_ambassador_email(row['email'], "Virtuole Ambassador Program: Term Completed", f"Hello {row['full_name']},\n\nYour 1-year term as a Virtuole Ambassador has officially concluded. Your account has now been seamlessly transitioned back to a standard Intern profile.")
            
        # Process Email Queue (Brevo Limits)
        pending_emails = supabase.table('email_queue').select('*').eq('status', 'pending').order('created_at').execute()
        
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        try:
            sent_today = supabase.table('email_queue').select('id').eq('status', 'sent').gte('sent_at', today_midnight).execute()
            daily_count = len(sent_today.data) if sent_today.data else 0
        except Exception:
            daily_count = 0
            
        allowance = 300 - daily_count
        
        if allowance > 0 and pending_emails.data:
            for i, email_record in enumerate(pending_emails.data):
                if i >= allowance:
                    break
                    
                msg = MIMEMultipart()
                msg['From'] = f"Virtuole Support <{os.getenv('BREVO_SMTP_USER', 'support@virtuole.in')}>"
                msg['To'] = email_record['recipient']
                msg['Subject'] = email_record['subject']
                msg.add_header('reply-to', 'support@virtuole.in')
                
                if email_record['is_html']:
                    msg.attach(MIMEText(email_record['body_content'], 'html'))
                else:
                    msg.attach(MIMEText(email_record['body_content'], 'plain'))
                    
                try:
                    with smtplib.SMTP("smtp-relay.brevo.com", 587) as server:
                        server.starttls()
                        server.login(os.getenv("BREVO_SMTP_USER"), os.getenv("BREVO_SMTP_PASS"))
                        server.send_message(msg)
                    
                    # Delete the pending record from queue
                    try:
                        supabase.table('email_queue').delete().eq('id', email_record['id']).execute()
                    except Exception as inner_e:
                        print(f"Failed to delete pending email: {inner_e}")
                    
                    # Insert a new 'sent' record for tracking daily limits
                    try:
                        supabase.table('email_queue').insert({
                            "recipient": email_record['recipient'],
                            "subject": email_record['subject'],
                            "body_content": email_record['body_content'],
                            "is_html": email_record['is_html'],
                            "status": "sent",
                            "sent_at": datetime.utcnow().isoformat()
                        }).execute()
                    except Exception as inner_e:
                        print(f"Failed to insert sent email to queue: {inner_e}")
                    
                except Exception as e:
                    print(f"Brevo Queue Delivery Exception: {e}")

        return jsonify({"status": "Maintenance execution completed successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500



if __name__ == '__main__':
    app.run(debug=True, port=5000)
