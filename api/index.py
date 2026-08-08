import os
import random
import string
import json
import base64
import hashlib
import requests
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, make_response, send_from_directory
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from supabase import create_client, Client
from werkzeug.middleware.proxy_fix import ProxyFix

# Load environment variables
load_dotenv()

# =====================================================================
# 1. SERVER CONFIGURATION & SECURITY
# =====================================================================
base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
template_dir = os.path.join(base_dir, 'templates')

app = Flask(__name__, template_folder=template_dir)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "virtuole-secure-master-key-2026")

# CRITICAL FIX: Trust Vercel's reverse proxy to keep cookies alive over HTTPS
# Note: x_prefix is intentionally set to 0 — Vercel's edge rewrites can set
# X-Forwarded-Prefix to /api/index.py which corrupts Flask's URL routing.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=0)

# Vercel Path Fix: Vercel's edge rewrites send PATH_INFO=/api/index.py to the
# serverless function instead of the original URL. This middleware corrects it.
class _VercelFix:
    def __init__(self, wsgi):
        self.wsgi = wsgi
    def __call__(self, environ, start_response):
        import urllib.parse
        path = environ.get('PATH_INFO', '/')
        if path == '/api/index.py' or path == '/api/index':
            qs = environ.get('QUERY_STRING', '')
            params = urllib.parse.parse_qs(qs)
            
            if '__vercel_path' in params:
                # Set PATH_INFO to the original path, and remove __vercel_path from QUERY_STRING
                environ['PATH_INFO'] = '/' + params['__vercel_path'][0]
                
                # Reconstruct QUERY_STRING without our internal parameter
                new_params = {k: v for k, v in params.items() if k != '__vercel_path'}
                environ['QUERY_STRING'] = urllib.parse.urlencode(new_params, doseq=True)
            else:
                environ['PATH_INFO'] = '/'
                
        script = environ.get('SCRIPT_NAME', '')
        if script and '/api/index' in script:
            environ['SCRIPT_NAME'] = ''
        return self.wsgi(environ, start_response)
app.wsgi_app = _VercelFix(app.wsgi_app)


# Basic, bulletproof session handling (Removed strict domain to prevent lockouts)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = True  # Allows cookies to stick on Vercel's HTTPS
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

CORS(app)

# Vercel Cache Killer to prevent the "reload logout" bug
@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

def get_real_client_ip():
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.remote_addr

limiter = Limiter(
    key_func=get_real_client_ip, 
    app=app,
    storage_uri="memory://",
    default_limits=["200 per day", "50 per hour"]
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None

# =====================================================================
# 2. HTML TEMPLATES (Offer Letters & Certificates)
# =====================================================================

def get_offer_letter_template(name, date, program_title, track_level, enroll_id, project_details):
    return f"""
    <html><body style="font-family: Helvetica, Arial, sans-serif; padding: 20px; color: #111827;">
        <div style="text-align: center; border-bottom: 2px solid #38b2ac; padding-bottom: 20px; margin-bottom: 40px;">
            <h1 style="color: #1a365d; margin: 0; letter-spacing: 3px; font-size: 38px;">VIRTU<span style="color: #38b2ac;">OLE</span></h1>
            <p style="color: #4a5568; font-weight: bold; font-size: 14px; margin: 8px 0 4px 0;">Registered MSME, Government of India</p>
            <p style="color: #6b7280; font-size: 12px; margin: 0;">Contact: support@virtuole.in | Web: www.virtuole.in</p>
        </div>
        <h2 style="color: #38b2ac;">Official Internship Offer Letter</h2>
        
        <table style="width: 100%; margin-bottom: 30px; font-size: 14px; border: none;">
            <tr>
                <td style="padding: 5px 0; border: none;"><strong>Date:</strong> {date}</td>
                <td style="text-align: right; border: none;"><strong>Tracking ID:</strong> {enroll_id}</td>
            </tr>
            <tr>
                <td style="padding: 5px 0; border: none;"><strong>To:</strong> {name}</td>
                <td style="border: none;"></td>
            </tr>
        </table>
        
        <p>Dear {name},</p>
        <p>We are thrilled to officially offer you a Virtual Internship position at Virtuole. You are enrolled in the <strong>{program_title}</strong> program at the <strong>{track_level}</strong> level.</p>
        <p><strong>Project Overview & Mandate:</strong> {project_details}</p>
        <p>Your mandate is to complete the assigned project requirements within a 30-day window.</p>
        <p>Virtuole operates strictly on a merit-based evaluation framework. Your final credentials, including your eligibility for the Founder's Letter of Recommendation, will be determined entirely by the structural quality, algorithmic efficiency, and originality of your final code submission.</p>
        <br><br><br>
        
        <table style="width: 100%; margin-top: 50px; border: none;">
            <tr>
                <td style="width: 60%; vertical-align: bottom; border: none;">
                    <img src="https://fkrxuptprlhfedlyanzf.supabase.co/storage/v1/object/public/public-assets/vishal_signature.png" style="height: 55px; width: 150px;" alt="Vishal Kumar Signature"><br>
                    <hr style="width: 220px; text-align: left; margin-left: 0; border: none; border-top: 1px solid #111827;">
                    <p style="margin-top: 5px; font-size: 14px;"><strong>Vishal Kumar</strong><br>Founder & Proprietor, Virtuole<br>support@virtuole.in</p>
                </td>
                <td style="width: 40%; text-align: right; vertical-align: bottom; border: none;">
                    <div style="display: inline-block; width: 140px; padding: 10px; border: 3px double #e53e3e; color: #e53e3e; text-align: center;">
                        <span style="font-weight: bold; font-size: 16px; letter-spacing: 1px;">VIRTUOLE</span><br>
                        <span style="font-size: 10px; font-weight: bold;">VIRTUAL INTERNSHIP</span><br>
                        <span style="font-size: 9px; font-weight: bold;">UDYAM-BR-06-0064801</span>
                    </div>
                </td>
            </tr>
        </table>
    </body></html>
    """

def get_certificate_template(name, date, program_title, track_level, enroll_id, score):
    return f"""
    <html><body style="font-family: Helvetica, Arial, sans-serif; padding: 30px; border: 8px solid #1a365d; text-align: center; max-width: 900px; margin: auto;">
        <h1 style="color: #1a365d; margin: 0; letter-spacing: 4px; font-size: 32px;">VIRTUOLE</h1>
        <p style="color: #4a5568; font-size: 12px; margin: 5px 0 0 0;">MSME Reg. No: UDYAM-BR-06-0064801 | support@virtuole.in</p>
        
        <h1 style="color: #ecc94b; font-size: 38px; margin-top: 30px; text-transform: uppercase;">Certificate of Completion</h1>
        <p style="font-size: 16px; color: #4a5568; margin-top: 20px;">This official document certifies that</p>
        
        <h2 style="font-size: 36px; color: #1a365d; border-bottom: 2px solid #cbd5e0; display: inline-block; padding-bottom: 5px; margin: 10px 0;">{name}</h2>
        
        <p style="font-size: 16px; color: #4a5568; margin: 20px 0;">has successfully completed the Virtual Internship Program, demonstrating proficiency in:</p>
        <h3 style="color: #38b2ac; font-size: 24px; margin: 10px 0;">{program_title} (Track: {track_level})</h3>
        
        <div style="background: #f7fafc; border: 1px solid #e2e8f0; padding: 10px; margin: 20px 100px;">
            <p style="margin: 0; font-weight: bold; color: #2d3748; font-size: 16px;">Final Evaluation Score: <span style="color: #38b2ac;">{score}%</span></p>
        </div>
        
        <p style="font-size: 12px; color: #718096; margin-top: 30px;">Credential ID: {enroll_id} &nbsp;|&nbsp; Date of Issue: {date}</p>
        
        <table style="width: 100%; margin-top: 40px; border: none;">
            <tr>
                <td style="width: 50%; text-align: center; vertical-align: bottom; border: none;">
                    <div style="display: inline-block; width: 120px; padding: 10px; border: 2px solid #38b2ac; color: #38b2ac; text-align: center;">
                        <span style="font-weight: bold; font-size: 14px;">VIRTUOLE</span><br>
                        <span style="font-size: 9px;">VERIFIED CREDENTIAL</span><br>
                        <span style="font-size: 8px;">UDYAM-BR-06-0064801</span>
                    </div>
                </td>
                <td style="width: 50%; text-align: center; vertical-align: bottom; border: none;">
                    <img src="https://fkrxuptprlhfedlyanzf.supabase.co/storage/v1/object/public/public-assets/vishal_signature.png" style="height: 55px; width: 150px;" alt="Vishal Kumar Signature"><br>
                    <hr style="width: 200px; text-align: center; border: none; border-top: 1px solid #111827; margin: auto;">
                    <p style="margin-top: 5px; font-size: 14px;"><strong>Vishal Kumar</strong><br>Founder & Proprietor, Virtuole</p>
                </td>
            </tr>
        </table>
        <br><p style="color: gray; font-size: 10px; border-top: 1px solid #eee; padding-top: 10px;">To save this certificate, press Ctrl+P (Windows) or Cmd+P (Mac) and select "Save as PDF". Ensure "Background graphics" is enabled.</p>
    </body></html>
    """

def get_lor_template(name, date, program_title, track_level, enroll_id, project_details):
    return f"""
    <html><body style="font-family: Helvetica, Arial, sans-serif; padding: 30px; color: #111827; line-height: 1.5; max-width: 800px; margin: auto;">
        <div style="text-align: right; border-bottom: 2px solid #ecc94b; padding-bottom: 15px; margin-bottom: 30px;">
            <h1 style="color: #1a365d; margin: 0; letter-spacing: 3px; font-size: 28px;">VIRTU<span style="color: #ecc94b;">OLE</span></h1>
            <p style="color: #4a5568; font-weight: bold; font-size: 12px; margin: 5px 0 2px 0;">Registered MSME, Government of India</p>
            <p style="color: #6b7280; font-size: 11px; margin: 0 0 2px 0;">UDYAM-BR-06-0064801</p>
            <p style="color: #6b7280; font-size: 11px; margin: 0;">support@virtuole.in | www.virtuole.in</p>
        </div>
        
        <h2 style="color: #1a365d; text-align: center; margin-bottom: 30px; font-size: 22px; letter-spacing: 1px;">LETTER OF RECOMMENDATION</h2>
        
        <table style="width: 100%; margin-bottom: 20px; font-size: 13px; border: none;">
            <tr>
                <td style="padding: 3px 0; border: none;"><strong>Date:</strong> {date}</td>
                <td style="text-align: right; border: none;"><strong>Credential ID:</strong> {enroll_id}</td>
            </tr>
        </table>
        
        <p><strong>To Whom It May Concern,</strong></p>
        <p>It is with immense pride that I write this letter to highly recommend <strong>{name}</strong>. During their tenure in the Virtuole Virtual Internship Program, {name} undertook the highly rigorous <strong>{program_title}</strong> program at the <strong>{track_level}</strong> level.</p>
        <p><strong>Project Focus:</strong> {project_details}</p>
        <p>At Virtuole, our evaluation matrix is notoriously strict, designed to simulate real-world production environments. {name} not only met our expectations but exceeded them, achieving a flawless <strong>100% Elite Score</strong>. This indicates an exceptional grasp of algorithmic efficiency, edge-case handling, and scalable software architecture principles.</p>
        <p>Individuals who demonstrate this level of technical acumen, dedication, and problem-solving ability are rare. I have absolutely no doubt that {name} will be a highly valuable asset to any engineering team, corporate division, or academic institution they choose to join.</p>
        <p>This credential is tied to our official MSME registry and can be verified by contacting our administrative team at <strong>support@virtuole.in</strong>.</p>
        <br><br>
        
        <table style="width: 100%; margin-top: 30px; border: none;">
            <tr>
                <td style="width: 60%; vertical-align: bottom; border: none;">
                    <img src="https://fkrxuptprlhfedlyanzf.supabase.co/storage/v1/object/public/public-assets/vishal_signature.png" style="height: 55px; width: 150px;" alt="Vishal Kumar Signature"><br>
                    <hr style="width: 220px; text-align: left; margin-left: 0; border: none; border-top: 1px solid #111827;">
                    <p style="margin-top: 5px; font-size: 13px;"><strong>Vishal Kumar</strong><br>Founder & Proprietor, Virtuole<br>support@virtuole.in</p>
                </td>
                <td style="width: 40%; text-align: right; vertical-align: bottom; border: none;">
                    <div style="display: inline-block; width: 130px; padding: 10px; border: 3px double #ecc94b; color: #d4af37; text-align: center;">
                        <span style="font-weight: bold; font-size: 14px;">VIRTUOLE</span><br>
                        <span style="font-size: 9px; font-weight: bold;">ELITE MERIT AWARD</span><br>
                        <span style="font-size: 8px; color: #111827;">UDYAM-BR-06-0064801</span>
                    </div>
                </td>
            </tr>
        </table>
    </body></html>
    """

def get_ambassador_certificate_template(name, date, tier_name, points, amb_id):
    return f"""
    <html><body style="font-family: Helvetica, Arial, sans-serif; padding: 30px; border: 8px solid #9f7aea; text-align: center; background-color: #faf5ff; max-width: 900px; margin: auto;">
        <h1 style="color: #1a365d; margin: 0; letter-spacing: 4px; font-size: 28px;">VIRTU<span style="color: #9f7aea;">OLE</span></h1>
        <p style="color: #4a5568; font-size: 12px; margin: 5px 0 0 0;">MSME Reg. No: UDYAM-BR-06-0064801 | ambassador@virtuole.in</p>
        
        <h2 style="color: #1a365d; margin-top: 25px; letter-spacing: 2px; font-size: 20px;">GTM AMBASSADOR PROGRAM</h2>
        <h1 style="color: #805ad5; font-size: 38px; margin-top: 15px; text-transform: uppercase;">Certificate of Achievement</h1>
        
        <p style="font-size: 16px; color: #4a5568; margin-top: 20px;">This official document certifies that</p>
        <h2 style="font-size: 36px; color: #1a365d; border-bottom: 2px solid #805ad5; display: inline-block; padding-bottom: 5px; margin: 10px 0;">{name}</h2>
        <p style="font-size: 16px; color: #4a5568; margin-top: 15px;">has successfully achieved the highly esteemed rank of</p>
        
        <div style="background: #1a202c; display: inline-block; padding: 10px 30px; margin: 15px 0;">
            <h3 style="color: #ecc94b; font-size: 24px; margin: 0;">{tier_name.upper()}</h3>
        </div>
        
        <p style="font-size: 14px; color: #4a5568; margin-top: 15px; padding: 0 50px;">Accumulating a total of <strong>{points} Merit Points</strong> through exceptional community leadership and technical advocacy.</p>
        <p style="font-size: 12px; color: #718096; margin-top: 25px;">Ambassador ID: {amb_id} &nbsp;|&nbsp; Date of Issue: {date}</p>
        
        <table style="width: 100%; margin-top: 30px; border: none;">
            <tr>
                <td style="width: 50%; text-align: center; vertical-align: bottom; border: none;">
                    <div style="display: inline-block; width: 120px; padding: 10px; border: 2px dashed #805ad5; color: #805ad5; text-align: center;">
                        <span style="font-weight: bold; font-size: 14px;">VIRTUOLE</span><br>
                        <span style="font-size: 9px;">GTM OFFICIAL RANK</span><br>
                        <span style="font-size: 8px;">UDYAM-BR-06-0064801</span>
                    </div>
                </td>
                <td style="width: 50%; text-align: center; vertical-align: bottom; border: none;">
                    <img src="https://fkrxuptprlhfedlyanzf.supabase.co/storage/v1/object/public/public-assets/vishal_signature.png" style="height: 55px; width: 150px;" alt="Vishal Kumar Signature"><br>
                    <hr style="width: 200px; text-align: center; border: none; border-top: 1px solid #111827; margin: auto;">
                    <p style="margin-top: 5px; font-size: 14px;"><strong>Vishal Kumar</strong><br>Founder & Proprietor, Virtuole</p>
                </td>
            </tr>
        </table>
        <br><p style="color: gray; font-size: 10px; border-top: 1px solid #eee; padding-top: 10px;">To save this certificate, press Ctrl+P (Windows) or Cmd+P (Mac) and select "Save as PDF". Ensure "Background graphics" is enabled.</p>
    </body></html>
    """

# =====================================================================
# 3. EMAIL INFRASTRUCTURE
# =====================================================================

def send_system_email(to_email, subject, body_content, is_html=False):
    msg = MIMEMultipart()
    msg['From'] = f"Virtuole Services <{os.getenv('AWS_SMTP_USER')}>"
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.add_header('reply-to', 'support@virtuole.in')
    
    if is_html:
        msg.attach(MIMEText(body_content, 'html'))
    else:
        msg.attach(MIMEText(body_content, 'plain'))
        
    try:
        with smtplib.SMTP(os.getenv("AWS_SMTP_SERVER"), int(os.getenv("AWS_SMTP_PORT", 587))) as server:
            server.starttls()
            server.login(os.getenv("AWS_SMTP_USER"), os.getenv("AWS_SMTP_PASS"))
            server.send_message(msg)
    except Exception as e:
        print(f"AWS SES Delivery Exception: {e}")

def send_ambassador_email(to_email, subject, body_content):
    msg = MIMEMultipart()
    msg['From'] = f"Virtuole Ambassador Program <ambassador@virtuole.in>"
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.add_header('reply-to', 'ambassador@virtuole.in')
    msg.attach(MIMEText(body_content, 'plain'))
    try:
        with smtplib.SMTP('smtp.zoho.in', 587) as server:
            server.starttls()
            server.login('ambassador@virtuole.in', os.getenv("ZOHO_AMBASSADOR_PASS"))
            server.send_message(msg)
    except Exception as e:
        print(f"Zoho Delivery Exception: {e}")

# =====================================================================
# 4. SYSTEM MAINTENANCE CRON
# =====================================================================

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
            send_system_email(row['email'], "Virtuole Ambassador Program: Term Completed", f"Hello {row['full_name']},\n\nYour 1-year term as a Virtuole Ambassador has officially concluded. Your account has now been seamlessly transitioned back to a standard Intern profile.")
            
        return jsonify({"status": "Maintenance execution completed successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =====================================================================
# 5. AUTHENTICATION & GATEWAYS (FIXED LOGIN)
# =====================================================================

@app.route('/')
def home():
    programs = []
    if supabase:
        programs = supabase.table('programs').select('*').eq('is_active', True).execute().data
    return render_template('index.html', offered_programs=programs)

@app.route('/register', methods=['POST'])
@app.route('/api/register', methods=['POST'])
@limiter.limit("5 per minute")
def register():
    full_name = request.form.get('full_name')
    email = request.form.get('email')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')
    promo_used = request.form.get('promo_code')
    
    if not full_name or not email or not password:
        return render_template('login.html', error="Please fill in your name, email and password.")

    if password != confirm_password:
        return render_template('login.html', error="Passwords do not match. Please try again.")

    if not supabase:
        return render_template('login.html', error="Registration is temporarily unavailable. Please try again later.")

    public_id = f"VT-2026-{random.randint(1000, 9999)}"

    try:
        auth_user = supabase.auth.sign_up({"email": email, "password": password})
        if auth_user and auth_user.user:
            supabase.table('users').insert({
                "id": auth_user.user.id, "full_name": full_name, "email": email, "public_id": public_id, "role": "intern"
            }).execute()
            if promo_used:
                send_ambassador_email("ambassador@virtuole.in", f"Conversion Logged: Code {promo_used}", f"A new student has registered using promo code {promo_used}.")
            send_system_email(email, "Welcome to Virtuole", f"Hello {full_name},\nYour public identity ID is {public_id}. Please log in to your dashboard to view offered programs and begin your internship.")
            return redirect(url_for('login', message="Account created successfully. Please login."))
        # sign_up returned no user (e.g. confirmation pending / duplicate email)
        return render_template('login.html', error="We could not create your account. This email may already be registered — try logging in instead.")
    except Exception as e:
        return render_template('login.html', error=str(e))

@app.route('/login', methods=['GET', 'POST'])
@app.route('/api/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    message = request.args.get('message')

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        try:
            # 1. Authorize via Supabase
            auth_response = supabase.auth.sign_in_with_password({"email": email, "password": password})
            
            # 2. Grab profile from Database
            user_data_response = supabase.table('users').select('*').eq('email', email).execute()
            if not user_data_response.data:
                return render_template('login.html', error="Profile data missing in the database.")
            
            user_data = user_data_response.data[0]
            
            # 3. Establish strict session data
            session.permanent = True
            session['user_id'] = user_data['id']
            session['email'] = user_data['email']
            session['name'] = user_data['full_name']
            session['public_id'] = user_data['public_id']
            
            # 4. Normalize the role string to completely eliminate redirect loop issues
            user_role = str(user_data.get('role', 'intern')).strip().lower()
            session['role'] = user_role
            
            # Force Flask to instantly save the session
            session.modified = True 
            
            # 5. Smart Routing based on normalized role
            if user_role == 'admin' or email == "admin@virtuole.in": 
                return redirect(url_for('dashboard_admin'))
            elif user_role == 'mentor': 
                return redirect(url_for('dashboard_mentor'))
            elif user_role == 'ambassador': 
                return redirect(url_for('dashboard_ambassador'))
            else: 
                return redirect(url_for('dashboard_intern'))
                
        except Exception as e:
            error_str = str(e)
            if "Invalid login credentials" in error_str or "AuthApiError" in error_str:
                return render_template('login.html', error="Incorrect email or password.")
            return render_template('login.html', error=f"Login Error: {error_str}")
            
    return render_template('login.html', message=message)

@app.route('/logout')
@app.route('/api/logout')
def logout():
    session.clear()
    from flask import make_response
    response = make_response(redirect('/login'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response

@app.route('/forgot-password', methods=['POST'])
@app.route('/api/forgot-password', methods=['POST'])
@limiter.limit("3 per minute")
def forgot_password():
    email = request.form.get('email')
    try:
        supabase.auth.reset_password_for_email(
            email, 
            options={"redirect_to": "https://www.virtuole.in/reset-password"}
        )
        return redirect(url_for('login', message="If an account exists, a password reset link has been sent to your email!"))
    except Exception as e:
        return render_template('login.html', error=str(e))

@app.route('/reset-password')
def reset_password_page():
    return render_template('reset_password.html')

@app.route('/update-password', methods=['POST'])
@app.route('/api/update-password', methods=['POST'])
def update_password():
    new_password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')
    access_token = request.form.get('access_token')
    refresh_token = request.form.get('refresh_token')

    if new_password != confirm_password:
        return render_template('reset_password.html', error="Passwords do not match. Try again.")
    if not access_token or not refresh_token:
        return render_template('reset_password.html', error="Invalid reset session context.")

    try:
        supabase.auth.set_session(access_token, refresh_token)
        supabase.auth.update_user({"password": new_password})
        supabase.auth.sign_out()
        return redirect(url_for('login', message="Password updated successfully! Please log in."))
    except Exception as e:
        return render_template('reset_password.html', error=str(e))

# =====================================================================
# 6. GTM PROMO CODE & PHONEPE GATEWAY
# =====================================================================

@app.route('/validate-promo', methods=['POST'])
@app.route('/api/validate-promo', methods=['POST'])
def validate_promo():
    data = request.get_json()
    promo_code = data.get('promo_code', '').upper()
    ambassador = supabase.table('users').select('id').eq('promo_code', promo_code).eq('role', 'ambassador').execute().data
    if ambassador:
        return jsonify({"valid": True, "discount_percent": 10})
    return jsonify({"valid": False, "error": "Invalid or expired code."}), 400

@app.route('/create-payment', methods=['POST'])
@app.route('/api/create-payment', methods=['POST'])
@limiter.limit("3 per minute")
def create_phonepe_payment():
    if not session.get('email'): 
        return jsonify({"error": "Unauthorized"}), 401
    
    if request.is_json:
        data = request.get_json()
        is_ajax = True
    else:
        data = request.form
        is_ajax = False
        
    enrollment_id = data.get('enrollment_id')
    promo_code = data.get('promo_code', '').upper()
    
    enroll_info = supabase.table('enrollments').select('track_level, programs(price_beginner, price_intermediate, price_expert)').eq('enrollment_id', enrollment_id).execute().data[0]
    track = enroll_info['track_level']
    base_price = enroll_info['programs'][f'price_{track}']
    
    final_price = base_price
    applied_promo = None
    if promo_code:
        is_valid = supabase.table('users').select('id').eq('promo_code', promo_code).eq('role', 'ambassador').execute().data
        if is_valid:
            final_price = int(base_price * 0.9)
            applied_promo = promo_code

    transaction_id = f"VT-TXN-{random.randint(100000, 999999)}"
    amount_in_paise = int(final_price * 100) 
    safe_merchant_user_id = session.get('public_id', 'VIRT-USER')
    
    payload = {
        "merchantId": os.getenv("PHONEPE_MERCHANT_ID"),
        "merchantTransactionId": transaction_id,
        "merchantUserId": safe_merchant_user_id,
        "amount": amount_in_paise,
        "redirectUrl": "https://www.virtuole.in/dashboard-intern", 
        "redirectMode": "REDIRECT",
        "callbackUrl": "https://www.virtuole.in/api/phonepe-webhook", 
        "paymentInstrument": {"type": "PAY_PAGE"}
    }
    
    base64_payload = base64.b64encode(json.dumps(payload).encode('utf-8')).decode('utf-8')
    checksum = hashlib.sha256((base64_payload + "/pg/v1/pay" + os.getenv("PHONEPE_SALT_KEY")).encode('utf-8')).hexdigest() + "###" + os.getenv("PHONEPE_SALT_INDEX")
    headers = {"Content-Type": "application/json", "X-VERIFY": checksum}
    
    try:
        response = requests.post("https://api-preprod.phonepe.com/apis/pg-sandbox/pg/v1/pay", json={"request": base64_payload}, headers=headers)
        response_data = response.json()
        
        if response_data.get('success'):
            supabase.table('submissions').insert({"enrollment_id": enrollment_id, "code_link": data.get('code_link'), "defense_link": data.get('defense_link')}).execute()
            supabase.table('payments').insert({"user_id": session['user_id'], "transaction_id": transaction_id, "amount": amount_in_paise, "status": "pending", "applied_promo": applied_promo}).execute()
            
            payment_url = response_data['data']['instrumentResponse']['redirectInfo']['url']
            if is_ajax:
                return jsonify({"payment_url": payment_url})
            else:
                return redirect(payment_url)
                
        if is_ajax:
            return jsonify({"error": response_data.get('message', 'Gateway Error')}), 400
        else:
            return "Gateway Error encountered.", 400
            
    except Exception as e:
        if is_ajax:
            return jsonify({"error": str(e)}), 500
        else:
            return f"Server Error: {str(e)}", 500

@app.route('/phonepe-webhook', methods=['POST'])
@app.route('/api/phonepe-webhook', methods=['POST'])
def phonepe_webhook():
    decoded_response = json.loads(base64.b64decode(request.json.get('response')).decode('utf-8'))
    if decoded_response['code'] == 'PAYMENT_SUCCESS':
        transaction_id = decoded_response['data']['merchantTransactionId']
        supabase.table('payments').update({"status": "paid"}).eq('transaction_id', transaction_id).execute()
    return jsonify({"status": "received"}), 200

# =====================================================================
# 7. INTERN ACTIONS
# =====================================================================

@app.route('/enroll', methods=['POST'])
@app.route('/api/enroll', methods=['POST'])
def api_enroll():
    if str(session.get('role', '')).lower() != 'intern': return redirect('/login')
    program_id = request.form.get('program_id')
    track_level = request.form.get('track_level')
    enrollment_id = f"VT-E-{random.randint(100000, 999999)}"
    
    existing = supabase.table('enrollments').select('id').eq('user_id', session['user_id']).eq('program_id', program_id).eq('track_level', track_level).in_('status', ['active', 'submitted']).execute().data
    if existing:
        return redirect(url_for('dashboard_intern'))
        
    supabase.table('enrollments').insert({
        "enrollment_id": enrollment_id, "user_id": session['user_id'], "program_id": program_id,
        "track_level": track_level, "college_name": request.form.get('college_name'),
        "course_name": request.form.get('course_name'), "session_year": request.form.get('session_year'),
        "status": "active"
    }).execute()
    
    prog = supabase.table('programs').select('*').eq('id', program_id).execute().data[0]
    html_offer = get_offer_letter_template(session['name'], datetime.utcnow().strftime("%B %d, %Y"), prog['title'], track_level.title(), enrollment_id, prog['short_description'])
    
    send_system_email(session['email'], "Official Internship Offer Letter - Virtuole", html_offer, is_html=True)
    return redirect(url_for('dashboard_intern'))

@app.route('/submit-project', methods=['POST'])
@app.route('/api/submit-project', methods=['POST'])
def api_submit_project():
    enrollment_id = request.form.get('enrollment_id')
    supabase.table('submissions').insert({"enrollment_id": enrollment_id, "code_link": request.form.get('code_link'), "defense_link": request.form.get('defense_link')}).execute()
    supabase.table('enrollments').update({"status": "submitted"}).eq('enrollment_id', enrollment_id).execute()
    send_system_email(session['email'], "Submission Received", f"Your architecture for {enrollment_id} has entered evaluation.")
    return redirect(url_for('dashboard_intern'))

# =====================================================================
# 8. MENTOR GRADING 
# =====================================================================

@app.route('/grade-submission', methods=['POST'])
@app.route('/api/grade-submission', methods=['POST'])
def grade_submission():
    if str(session.get('role', '')).lower() != 'mentor': return redirect('/login')
    sub_id = request.form.get('submission_id')
    enrollment_id = request.form.get('enrollment_id')
    score = int(request.form.get('score'))
    feedback = request.form.get('feedback', 'No specific feedback.')
    
    enroll_data = supabase.table('enrollments').select('*, programs(title, short_description)').eq('enrollment_id', enrollment_id).execute().data[0]
    student = supabase.table('users').select('email', 'full_name').eq('id', enroll_data['user_id']).execute().data[0]
    
    if score >= 80:
        db_updates = {"score": score, "certificate_url": f"https://www.virtuole.in/verify-credential?credential_id={enrollment_id}", "evaluated_at": datetime.utcnow().isoformat()}
        if score == 100:
            db_updates["lor_url"] = f"https://www.virtuole.in/verify-credential?credential_id={enrollment_id}"
            body_msg = f"Congratulations {student['full_name']}! You can view your Certificate and Elite LoR here: https://www.virtuole.in/verify-credential?credential_id={enrollment_id}"
        else:
            body_msg = f"Congratulations {student['full_name']}! You can view your Certificate here: https://www.virtuole.in/verify-credential?credential_id={enrollment_id}"
            
        supabase.table('submissions').update(db_updates).eq('id', sub_id).execute()
        supabase.table('enrollments').update({"status": "graded"}).eq('enrollment_id', enrollment_id).execute()
        send_system_email(student['email'], "Certification Passed - Virtuole", body_msg)
    else:
        supabase.table('submissions').delete().eq('id', sub_id).execute() 
        supabase.table('enrollments').update({"status": "failed", "created_at": datetime.utcnow().isoformat()}).eq('enrollment_id', enrollment_id).execute()
        failure_email_body = f"Dear {student['full_name']},\n\nYour submission scored {score}%. Feedback: \"{feedback}\"\nYou have 24 hours to resubmit."
        send_system_email(student['email'], "ACTION REQUIRED: Submission Failed", failure_email_body)
    return redirect(url_for('dashboard_mentor'))

@app.route('/evaluate-task', methods=['POST'])
@app.route('/api/evaluate-task', methods=['POST'])
def evaluate_task():
    if str(session.get('role', '')).lower() != 'mentor': return redirect('/login')
    claim_id = request.form.get('claim_id')
    action = request.form.get('action') 
    claim_data = supabase.table('ambassador_claims').select('ambassador_id, users(email, full_name)').eq('id', claim_id).execute().data[0]
    
    if action == 'approve':
        pts = int(request.form.get('point_value'))
        supabase.table('ambassador_claims').update({"status": "approved"}).eq('id', claim_id).execute()
        curr_pts = supabase.table('users').select('total_points').eq('id', claim_data['ambassador_id']).execute().data[0]['total_points'] or 0
        supabase.table('users').update({"total_points": curr_pts + pts}).eq('id', claim_data['ambassador_id']).execute()
        send_ambassador_email(claim_data['users']['email'], "Task Approved!", f"Great job! +{pts} Points added.")
    elif action == 'reject':
        supabase.table('ambassador_claims').update({"status": "rejected"}).eq('id', claim_id).execute()
        send_ambassador_email(claim_data['users']['email'], "Task Proof Rejected", "Your task proof could not be verified.")
    return redirect(url_for('dashboard_mentor'))

# =====================================================================
# 9. ADMIN ACTIONS (With Soft Delete)
# =====================================================================

@app.route('/admin/add-program', methods=['POST'])
@app.route('/api/admin/add-program', methods=['POST'])
def add_program():
    if str(session.get('role', '')).lower() != 'admin': return redirect('/login')
    supabase.table('programs').insert({
        "title": request.form.get('title'), "short_description": request.form.get('short_description'), "specs_beginner": request.form.get('specs_beginner'),
        "specs_intermediate": request.form.get('specs_intermediate'), "specs_expert": request.form.get('specs_expert'),
        "price_beginner": int(request.form.get('price_beginner')), "price_intermediate": int(request.form.get('price_intermediate')),
        "price_expert": int(request.form.get('price_expert')), "is_active": True
    }).execute()
    return redirect(url_for('dashboard_admin', tab='programs'))

@app.route('/admin/delete-program', methods=['POST'])
@app.route('/api/admin/delete-program', methods=['POST'])
def delete_program():
    if str(session.get('role', '')).lower() != 'admin': return redirect('/login')
    # Soft Delete: Preserves student data history
    supabase.table('programs').update({"is_active": False}).eq('id', request.form.get('program_id')).execute()
    return redirect(url_for('dashboard_admin', tab='programs'))

@app.route('/admin/add-task', methods=['POST'])
@app.route('/api/admin/add-task', methods=['POST'])
def add_task():
    if str(session.get('role', '')).lower() != 'admin': return redirect('/login')
    max_completions = int(request.form.get('max_completions', 1) or 1)
    supabase.table('ambassador_tasks').insert({"title": request.form.get('title'), "description": request.form.get('description'), "point_value": int(request.form.get('point_value')), "is_active": True, "max_completions": max_completions}).execute()
    return redirect(url_for('dashboard_admin', tab='tasks'))

@app.route('/admin/delete-task', methods=['POST'])
@app.route('/api/admin/delete-task', methods=['POST'])
def delete_task():
    if str(session.get('role', '')).lower() != 'admin': return redirect('/login')
    supabase.table('ambassador_tasks').delete().eq('id', request.form.get('task_id')).execute()
    return redirect(url_for('dashboard_admin', tab='tasks'))

@app.route('/admin/mark-swag-sent', methods=['POST'])
@app.route('/api/admin/mark-swag-sent', methods=['POST'])
def mark_swag_sent():
    if str(session.get('role', '')).lower() != 'admin': return redirect('/login')
    ambassador_id = request.form.get('ambassador_id')
    swag_tier = request.form.get('swag_tier', '')
    amb = supabase.table('users').select('email', 'full_name').eq('id', ambassador_id).execute().data
    if amb:
        user = amb[0]
        # Best-effort ledger flag; silently ignored if the column isn't in the schema.
        try:
            supabase.table('users').update({"swag_dispatched": True}).eq('id', ambassador_id).execute()
        except Exception:
            pass
        send_ambassador_email(
            user['email'],
            "Your Virtuole Ambassador Swag Has Shipped!",
            f"Hi {user['full_name']},\n\nGreat news — your Tier {swag_tier} Ambassador swag kit has been dispatched. Courier tracking details will follow shortly.\n\nThank you for representing Virtuole.\n\n— The Virtuole Ambassador Team"
        )
    return redirect(url_for('dashboard_admin', tab='swag'))

@app.route('/admin/update-role', methods=['POST'])
@app.route('/api/admin/update-role', methods=['POST'])
def update_role():
    if str(session.get('role', '')).lower() != 'admin': return redirect('/login')
    user_id = request.form.get('user_id')
    new_role = request.form.get('new_role')
    user = supabase.table('users').select('email', 'full_name').eq('id', user_id).execute().data[0]
    update_data = {'role': new_role}
    
    if new_role == 'ambassador':
        update_data['public_id'] = f"AMB-2026-{random.randint(100, 999)}"
        update_data['promo_code'] = f"AMB{''.join(random.choices(string.ascii_uppercase, k=4))}"
        update_data['ambassador_expiry'] = (datetime.utcnow() + timedelta(days=365)).isoformat()
        send_ambassador_email(user['email'], "Welcome Status", f"Promoted to Ambassador. Code: {update_data['promo_code']}.")
    elif new_role == 'mentor':
        send_system_email(user['email'], "Promotion Status", "Promoted to Mentor status.")
    elif new_role == 'admin':
        send_system_email(user['email'], "Clearance Status", "Granted Admin access clearance.")
        
    supabase.table('users').update(update_data).eq('id', user_id).execute()
    return redirect(url_for('dashboard_admin', tab='users'))

# =====================================================================
# 10. AMBASSADOR ACTIONS
# =====================================================================

@app.route('/claim-points', methods=['POST'])
@app.route('/api/claim-points', methods=['POST'])
def claim_points():
    if str(session.get('role', '')).lower() != 'ambassador': return redirect('/login')
    task_id = request.form.get('task_id')
    
    task_data = supabase.table('ambassador_tasks').select('max_completions').eq('id', task_id).execute().data
    if task_data:
        max_c = task_data[0].get('max_completions', 1)
        existing = len(supabase.table('ambassador_claims').select('id').eq('ambassador_id', session['user_id']).eq('task_id', task_id).in_('status', ['pending', 'approved']).execute().data)
        if existing >= max_c:
            return redirect(url_for('dashboard_ambassador'))

    supabase.table('ambassador_claims').insert({
        "ambassador_id": session['user_id'], "task_id": task_id,
        "proof_link": request.form.get('proof_link'), "notes": request.form.get('notes')
    }).execute()
    return redirect(url_for('dashboard_ambassador'))

@app.route('/update-address', methods=['POST'])
@app.route('/api/update-address', methods=['POST'])
def update_address():
    if str(session.get('role', '')).lower() != 'ambassador': return redirect('/login')
    supabase.table('users').update({"shipping_address": request.form.get('shipping_address')}).eq('id', session['user_id']).execute()
    return redirect(url_for('dashboard_ambassador'))

# =====================================================================
# 11. DASHBOARD RENDERS
# =====================================================================

@app.route('/dashboard-intern')
def dashboard_intern():
    if str(session.get('role', '')).lower() != 'intern': return redirect('/login')
    u_id = session['user_id']
    active_enrolls = supabase.table('enrollments').select('*, programs(*)').eq('user_id', u_id).eq('status', 'active').execute().data
    active_projects = [{'program_title': e['programs']['title'], 'description': e['programs']['short_description'], 'track_level': e['track_level'], 'enrollment_id': e['enrollment_id'], 'specs_link': e['programs'].get(f"specs_{e['track_level']}", '#'), 'amount_due': e['programs'].get(f"price_{e['track_level']}", 0)} for e in active_enrolls]
    offered = supabase.table('programs').select('*').eq('is_active', True).execute().data
    
    completed_projects = []
    graded_enrolls = supabase.table('enrollments').select('*, programs(title)').eq('user_id', u_id).in_('status', ['graded', 'submitted']).execute().data
    for e in graded_enrolls:
        sub = supabase.table('submissions').select('*').eq('enrollment_id', e['enrollment_id']).execute().data
        if sub:
            s = sub[0]
            completed_projects.append({'score': s.get('score'), 'program_title': e['programs']['title'], 'track_level': e['track_level'], 'enrollment_id': e['enrollment_id'], 'evaluated_date': s.get('evaluated_at', '').split('T')[0] if s.get('evaluated_at') else 'Pending', 'certificate_url': s.get('certificate_url'), 'lor_url': s.get('lor_url')})

    return render_template('dashboard_intern.html', user_name=session.get('name'), active_projects=active_projects, offered_programs=offered, completed_projects=completed_projects)

@app.route('/dashboard-mentor')
def dashboard_mentor():
    if str(session.get('role', '')).lower() != 'mentor': return redirect('/login')
    pend_subs = supabase.table('submissions').select('*').is_('score', 'null').execute().data
    graded_subs = supabase.table('submissions').select('*').not_.is_('score', 'null').execute().data
    claims = supabase.table('ambassador_claims').select('id, proof_link, notes, ambassador_id, users(full_name, email), ambassador_tasks(title, point_value)').eq('status', 'pending').execute().data
    pending_claims = [{"id": c['id'], "ambassador_id": c['ambassador_id'], "ambassador_name": c['users']['full_name'], "ambassador_email": c['users']['email'], "task_title": c['ambassador_tasks']['title'], "point_value": c['ambassador_tasks']['point_value'], "proof_link": c['proof_link'], "notes": c['notes']} for c in claims]
    analytics = build_mentor_analytics(pend_subs, graded_subs, len(pending_claims))
    return render_template('dashboard_mentor.html', user_name=session.get('name'), pending_submissions=pend_subs, graded_submissions=graded_subs, pending_claims=pending_claims, analytics=analytics)


def build_mentor_analytics(pending_subs, graded_subs, pending_claims_count):
    """Chart.js-ready series for the mentor dashboard: grading throughput over
    the last 14 days plus a pass/fail score-band split. Defensive so a missing
    field degrades to zeros rather than 500-ing."""
    now = datetime.utcnow()
    day_keys = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(13, -1, -1)]
    day_labels = [(now - timedelta(days=i)).strftime("%b %d") for i in range(13, -1, -1)]
    graded_by_day = {k: 0 for k in day_keys}
    bands = {"90-100": 0, "80-89": 0, "60-79": 0, "<60": 0}

    for s in (graded_subs or []):
        try:
            key = (s.get('evaluated_at') or s.get('created_at') or '')[:10]
            if key in graded_by_day:
                graded_by_day[key] += 1
            sc = s.get('score')
            if sc is None:
                continue
            if sc >= 90:   bands["90-100"] += 1
            elif sc >= 80: bands["80-89"] += 1
            elif sc >= 60: bands["60-79"] += 1
            else:          bands["<60"] += 1
        except Exception:
            continue

    return {
        "throughput_labels": day_labels,
        "throughput_values": [graded_by_day[k] for k in day_keys],
        "band_labels": list(bands.keys()),
        "band_values": list(bands.values()),
        "queue_labels": ["Pending Reviews", "Graded", "GTM Claims"],
        "queue_values": [len(pending_subs or []), len(graded_subs or []), pending_claims_count],
    }

@app.route('/dashboard-admin')
def dashboard_admin():
    if str(session.get('role', '')).lower() != 'admin': return redirect('/login')
    active_tab = request.args.get('tab', 'overview')
    timeframe = request.args.get('timeframe', 'all')

    # Optional time window for the telemetry stat cards.
    now = datetime.utcnow()
    cutoffs = {
        '1day': now - timedelta(days=1),
        '1week': now - timedelta(weeks=1),
        '1month': now - timedelta(days=30),
    }
    cutoff = cutoffs.get(timeframe)

    def _window(query):
        # Apply the created_at window when a timeframe is selected.
        return query.gte('created_at', cutoff.isoformat()) if cutoff else query

    try:
        earnings = sum([p['amount'] / 100 for p in _window(supabase.table('payments').select('amount').eq('status', 'paid')).execute().data])
        enrolled = len(_window(supabase.table('enrollments').select('id')).execute().data)
        certified = len(_window(supabase.table('submissions').select('id').gte('score', 80)).execute().data)
        pend_grading = len(_window(supabase.table('submissions').select('id').is_('score', 'null')).execute().data)
    except Exception:
        # Fall back to all-time totals if a table has no created_at column.
        earnings = sum([p['amount'] / 100 for p in supabase.table('payments').select('amount').eq('status', 'paid').execute().data])
        enrolled = len(supabase.table('enrollments').select('id').execute().data)
        certified = len(supabase.table('submissions').select('id').gte('score', 80).execute().data)
        pend_grading = len(supabase.table('submissions').select('id').is_('score', 'null').execute().data)

    progs = supabase.table('programs').select('*').execute().data
    tasks = supabase.table('ambassador_tasks').select('*').execute().data
    users = supabase.table('users').select('*').execute().data

    # -----------------------------------------------------------------
    # GRAPHICAL ANALYTICS DATA (Chart.js-ready, JSON-serializable)
    # Built defensively so a missing column never breaks the dashboard.
    # -----------------------------------------------------------------
    analytics = build_admin_analytics(progs, users)

    return render_template('dashboard_admin.html', user_name=session.get('name'), total_earnings=round(earnings, 2), total_enrolled=enrolled, total_certified=certified, pending_grading=pend_grading, offered_programs=progs, all_tasks=tasks, user_directory=users, tier3_ambassadors=[u for u in users if u['role'] == 'ambassador' and 1500 <= (u['total_points'] or 0) < 3000], tier4_ambassadors=[u for u in users if u['role'] == 'ambassador' and (u['total_points'] or 0) >= 3000], active_tab=active_tab, current_filter=timeframe, analytics=analytics)


def build_admin_analytics(programs, users):
    """Aggregate live Supabase data into Chart.js-ready series for the admin
    Platform Analytics tab. Every block is wrapped so an absent table/column
    degrades to empty data instead of 500-ing the whole dashboard."""
    empty = {
        "revenue_labels": [], "revenue_values": [],
        "enroll_labels": [], "enroll_values": [],
        "role_labels": [], "role_values": [],
        "outcome_labels": ["Certified (≥80)", "Failed (<80)", "Pending"], "outcome_values": [0, 0, 0],
        "program_labels": [], "program_values": [],
    }
    if not supabase:
        return empty

    now = datetime.utcnow()

    # ---- 30-day daily buckets for revenue + enrollments (line/area) ----
    day_keys = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29, -1, -1)]
    day_labels = [(now - timedelta(days=i)).strftime("%b %d") for i in range(29, -1, -1)]
    revenue_by_day = {k: 0.0 for k in day_keys}
    enroll_by_day = {k: 0 for k in day_keys}

    try:
        thirty_days_ago = (now - timedelta(days=30)).isoformat()
        paid = supabase.table('payments').select('amount, created_at').eq('status', 'paid').gte('created_at', thirty_days_ago).execute().data
        for p in paid:
            key = (p.get('created_at') or '')[:10]
            if key in revenue_by_day:
                revenue_by_day[key] += (p.get('amount') or 0) / 100.0
    except Exception:
        pass

    try:
        thirty_days_ago = (now - timedelta(days=30)).isoformat()
        enrolls = supabase.table('enrollments').select('created_at, program_id').gte('created_at', thirty_days_ago).execute().data
        for e in enrolls:
            key = (e.get('created_at') or '')[:10]
            if key in enroll_by_day:
                enroll_by_day[key] += 1
    except Exception:
        pass

    # ---- Role distribution (doughnut) ----
    role_counts = {}
    for u in (users or []):
        role = str(u.get('role') or 'intern').strip().lower()
        role_counts[role] = role_counts.get(role, 0) + 1
    role_labels = [r.title() for r in role_counts.keys()]
    role_values = list(role_counts.values())

    # ---- Certification outcomes (bar) ----
    certified = failed = pending = 0
    try:
        subs = supabase.table('submissions').select('score').execute().data
        for s in subs:
            score = s.get('score')
            if score is None:
                pending += 1
            elif score >= 80:
                certified += 1
            else:
                failed += 1
    except Exception:
        pass

    # ---- Program popularity: enrollments per program (horizontal bar) ----
    prog_titles = {p['id']: p.get('title', 'Untitled') for p in (programs or [])}
    prog_counts = {p['id']: 0 for p in (programs or [])}
    try:
        all_enrolls = supabase.table('enrollments').select('program_id').execute().data
        for e in all_enrolls:
            pid = e.get('program_id')
            if pid in prog_counts:
                prog_counts[pid] += 1
    except Exception:
        pass
    ranked = sorted(prog_counts.items(), key=lambda kv: kv[1], reverse=True)[:8]

    # ---- Cumulative growth: running totals of enrollments + revenue ----
    # Baseline = everything before the 30-day window, so the trend starts from
    # the true platform total rather than zero.
    base_enroll = 0
    base_revenue = 0.0
    try:
        thirty_days_ago = (now - timedelta(days=30)).isoformat()
        base_enroll = len(supabase.table('enrollments').select('id').lt('created_at', thirty_days_ago).execute().data)
        base_paid = supabase.table('payments').select('amount').eq('status', 'paid').lt('created_at', thirty_days_ago).execute().data
        base_revenue = sum([(p.get('amount') or 0) / 100.0 for p in base_paid])
    except Exception:
        pass
    cum_enroll, cum_revenue = [], []
    run_e, run_r = base_enroll, base_revenue
    for k in day_keys:
        run_e += enroll_by_day[k]
        run_r += revenue_by_day[k]
        cum_enroll.append(run_e)
        cum_revenue.append(round(run_r, 2))

    return {
        "revenue_labels": day_labels,
        "revenue_values": [round(revenue_by_day[k], 2) for k in day_keys],
        "enroll_labels": day_labels,
        "enroll_values": [enroll_by_day[k] for k in day_keys],
        "role_labels": role_labels,
        "role_values": role_values,
        "outcome_labels": ["Certified (≥80)", "Failed (<80)", "Pending"],
        "outcome_values": [certified, failed, pending],
        "program_labels": [prog_titles.get(pid, 'Untitled') for pid, _ in ranked],
        "program_values": [cnt for _, cnt in ranked],
        "growth_labels": day_labels,
        "growth_enroll": cum_enroll,
        "growth_revenue": cum_revenue,
    }

@app.route('/dashboard-ambassador')
def dashboard_ambassador():
    if str(session.get('role', '')).lower() != 'ambassador': return redirect('/login')
    u = supabase.table('users').select('*').eq('id', session['user_id']).execute().data[0]
    pts = u['total_points'] or 0
    tier_name = "Star Ambassador" if pts >= 3000 else "Community Lead" if pts >= 1500 else "Campus Advocate" if pts >= 500 else "Kickstart"
    refs = len(supabase.table('payments').select('id').eq('applied_promo', u['promo_code']).eq('status', 'paid').execute().data)
    tasks = supabase.table('ambassador_tasks').select('*').eq('is_active', True).execute().data
    
    claims = supabase.table('ambassador_claims').select('task_id').eq('ambassador_id', session['user_id']).in_('status', ['pending', 'approved']).execute().data
    task_claims = {}
    for c in claims:
        task_claims[c['task_id']] = task_claims.get(c['task_id'], 0) + 1

    analytics = build_ambassador_analytics(u, pts, refs)
    return render_template('dashboard_ambassador.html', ambassador_name=session.get('name'), valid_until_date=u['ambassador_expiry'].split('T')[0] if u.get('ambassador_expiry') else 'N/A', total_points=pts, current_tier_name=tier_name, total_referrals=refs, promo_code=u['promo_code'], amb_id=u['public_id'], available_tasks=tasks, task_claims=task_claims, shipping_address=u['shipping_address'], analytics=analytics)


def build_ambassador_analytics(user, points, referrals):
    """Chart.js-ready series for the ambassador dashboard: tier-progress gauge,
    a cumulative points-earned trend from approved claims, and a referrals
    breakdown. Defensive so missing claim history degrades to a flat line."""
    tiers = [("Kickstart", 0), ("Campus Advocate", 500), ("Community Lead", 1500), ("Star Ambassador", 3000)]
    # next-tier progress (points toward the next threshold above current)
    next_threshold = next((t for _, t in tiers if t > points), 3000)
    prev_threshold = max([t for _, t in tiers if t <= points] or [0])
    span = max(next_threshold - prev_threshold, 1)
    tier_progress = min(round((points - prev_threshold) / span * 100), 100)

    now = datetime.utcnow()
    week_keys = [(now - timedelta(weeks=i)).strftime("%Y-%W") for i in range(7, -1, -1)]
    week_labels = [(now - timedelta(weeks=i)).strftime("%b %d") for i in range(7, -1, -1)]
    earned_by_week = {k: 0 for k in week_keys}
    try:
        if supabase and user.get('id'):
            claims = supabase.table('ambassador_claims').select('created_at, status, ambassador_tasks(point_value)') \
                .eq('ambassador_id', user['id']).eq('status', 'approved').execute().data
            for c in (claims or []):
                created = c.get('created_at') or ''
                try:
                    wk = datetime.fromisoformat(created.replace('Z', '')).strftime("%Y-%W") if created else None
                except Exception:
                    wk = None
                if wk in earned_by_week:
                    earned_by_week[wk] += ((c.get('ambassador_tasks') or {}).get('point_value') or 0)
    except Exception:
        pass
    # cumulative trend
    cumulative, running = [], 0
    for k in week_keys:
        running += earned_by_week[k]
        cumulative.append(running)

    return {
        "tier_progress": tier_progress,
        "tier_next_name": next((n for n, t in tiers if t > points), "Star Ambassador"),
        "tier_points_to_next": max(next_threshold - points, 0),
        "trend_labels": week_labels,
        "trend_values": cumulative,
        "breakdown_labels": ["Points Earned", "Referrals"],
        "breakdown_values": [points, referrals],
    }

# =====================================================================
# 12. PUBLIC & RENDERING PATHS (Including Offer Letters)
# =====================================================================

@app.route('/download_cert/<tier>')
def download_cert(tier):
    if str(session.get('role', '')).lower() != 'ambassador': return redirect('/login')
    u = supabase.table('users').select('*').eq('id', session['user_id']).execute().data[0]
    pts = u['total_points'] or 0
    tier_name = "Kickstart" if tier == 'kickstart' else "Campus Advocate" if tier == 'advocate' and pts >= 500 else "Community Lead" if tier == 'lead' and pts >= 1500 else "Star Ambassador" if tier == 'star' and pts >= 3000 else None
    if not tier_name: return "Insufficient Points", 403
    return get_ambassador_certificate_template(u['full_name'], datetime.utcnow().strftime("%B %d, %Y"), tier_name, pts, u['public_id'])

@app.route('/download_lor/<type>')
def download_lor(type):
    if str(session.get('role', '')).lower() != 'ambassador': return redirect('/login')
    u = supabase.table('users').select('*').eq('id', session['user_id']).execute().data[0]
    if type == 'devrel' and (u['total_points'] or 0) >= 1500:
        return get_lor_template(u['full_name'], datetime.utcnow().strftime("%B %d, %Y"), "GTM Ambassador Program", "Community Lead", u['public_id'], "Community Leadership and Advocacy.")
    return "Insufficient Points", 403

@app.route('/download_offer/<enrollment_id>')
def download_offer(enrollment_id):
    if str(session.get('role', '')).lower() != 'intern': return redirect('/login')
    enroll_data = supabase.table('enrollments').select('*, programs(*), users(full_name)').eq('enrollment_id', enrollment_id).eq('user_id', session['user_id']).execute().data
    if not enroll_data: return "Invalid Assignment Context", 403
        
    e = enroll_data[0]
    raw_date = e['created_at'].split('T')[0] if e.get('created_at') else datetime.utcnow().strftime("%Y-%m-%d")
    html_content = get_offer_letter_template(e['users']['full_name'], raw_date, e['programs']['title'], e['track_level'].title(), enrollment_id, e['programs']['short_description'])
    
    # Auto-Print dialog script
    return html_content + "<script>window.onload = function() { setTimeout(function(){ window.print(); }, 500); }</script>"

@app.route('/contact')
def contact_page():
    return render_template('contact.html')

@app.route('/feedback')
def feedback_page():
    return render_template('feedback.html')

@app.route('/submit-feedback', methods=['POST'])
def submit_feedback():
    name = request.form.get('name')
    email = request.form.get('email')
    subject = request.form.get('subject')
    message = request.form.get('message')
    
    # Logs the feedback to your Vercel console
    print(f"NEW FEEDBACK: {name} | {email} | {subject} | {message}")
    
    return render_template('feedback.html', message="Thank you! Your feedback has been successfully submitted.")

@app.route('/subscribe', methods=['POST'])
def subscribe_newsletter():
    email = request.form.get('email')
    print(f"NEW SUBSCRIBER: {email}")
    return redirect(url_for('home'))

@app.route('/terms')
def terms_page(): return render_template('terms.html')
@app.route('/refund')
def refund_page(): return render_template('refund.html')
@app.route('/privacy')
def privacy_page(): return render_template('privacy.html')
@app.route('/cookies')
def cookies_page(): return render_template('cookies.html')
@app.route('/verify.html')
def verify_page_redirect(): return render_template('verify.html')
@app.route('/offer-letter')
def offer_letter_page(): return render_template('offer.html')

@app.route('/blog')
def blog():return render_template('blog.html')

@app.route('/view-offer', methods=['GET'])
def view_public_offer():
    enrollment_id = request.args.get('enrollment_id')
    if not enrollment_id: return render_template('offer.html')
    try:
        enroll_data = supabase.table('enrollments').select('*, programs(*), users(full_name)').eq('enrollment_id', enrollment_id).execute().data
        if not enroll_data: return render_template('offer.html', error=True)
        e = enroll_data[0]
        raw_date = e['created_at'].split('T')[0] if e.get('created_at') else datetime.utcnow().strftime("%Y-%m-%d")
        html_content = get_offer_letter_template(e['users']['full_name'], raw_date, e['programs']['title'], e['track_level'].title(), enrollment_id, e['programs']['short_description'])
        return html_content + "<script>window.onload = function() { setTimeout(function(){ window.print(); }, 500); }</script>"
    except:
        return render_template('offer.html', error=True)

@app.route('/verify-credential', methods=['GET'])
def verify_credential():
    credential_id = request.args.get('credential_id')
    if not credential_id: return render_template('verify.html')
    try:
        enroll_query = supabase.table('enrollments').select('*, programs(title), users(full_name)').eq('enrollment_id', credential_id).eq('status', 'graded').execute()
        if not enroll_query.data: return render_template('verify.html', error=True)
        sub_query = supabase.table('submissions').select('*').eq('enrollment_id', credential_id).execute()
        return render_template('verify.html', verified_data={
            "student_name": enroll_query.data[0]['users']['full_name'],
            "program_title": enroll_query.data[0]['programs']['title'],
            "track_level": enroll_query.data[0]['track_level'],
            "score": sub_query.data[0]['score'],
            "enrollment_id": credential_id,
            "evaluated_date": sub_query.data[0]['evaluated_at'].split('T')[0] if sub_query.data[0].get('evaluated_at') else "N/A"
        })
    except:
        return render_template('verify.html', error=True)

@app.route('/apply-ambassador', methods=['GET', 'POST'])
@app.route('/api/apply-ambassador', methods=['GET', 'POST'])
def apply_ambassador():
    if request.method == 'GET':
        return render_template('applyambass.html')

    name = request.form.get('name')
    email = request.form.get('email')
    college = request.form.get('college')
    motivation = request.form.get('motivation', '')

    if not name or not email:
        return render_template('applyambass.html', error="Please provide your name and email.")

    # Fold college into motivation so the detail is preserved without assuming
    # a dedicated column exists in the ambassador_applications table.
    if college:
        motivation = f"College: {college}\n\n{motivation}"

    try:
        supabase.table('ambassador_applications').insert({
            "name": name, "email": email, "motivation": motivation, "status": "pending"
        }).execute()
    except Exception as e:
        return render_template('applyambass.html', error=f"Submission failed: {e}")

    return render_template('applyambass.html', submitted=True)

@app.route('/static/logo.png')
def serve_logo():
    return send_from_directory('templates', 'logo.png')

if __name__ == '__main__':
    app.run(debug=True, port=5000)