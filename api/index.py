import os
import random
import string
import json
import base64
import hashlib
import requests
import smtplib
from io import BytesIO
from xhtml2pdf import pisa
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, make_response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from supabase import create_client, Client

# Load secure environment configurations
load_dotenv()
app = Flask(__name__, template_folder='../templates')
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
CORS(app)

# Protect system endpoints from API brute-forcing/spam
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"]
)

# Core Relational Database Client Connection
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# =====================================================================
# 1. PDF GENERATOR & HTML TEMPLATES (Vercel-Compatible xhtml2pdf)
# =====================================================================

def generate_pdf_from_html(html_string, orientation='Portrait'):
    """Converts a raw HTML string into a PDF byte array using pure Python."""
    if orientation.lower() == 'landscape':
        page_css = "<style>@page { size: a4 landscape; margin: 1cm; }</style>"
    else:
        page_css = "<style>@page { size: a4 portrait; margin: 1cm; }</style>"
    
    full_html = page_css + html_string
    result = BytesIO()
    
    pisa_status = pisa.CreatePDF(full_html, dest=result)
    
    if pisa_status.err:
        print(f"PDF Generation Error: {pisa_status.err}")
        return None
        
    return result.getvalue()

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
    <html><body style="font-family: Helvetica, Arial, sans-serif; padding: 30px; border: 8px solid #1a365d; text-align: center;">
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
                    <hr style="width: 200px; text-align: center; border: none; border-top: 1px solid #111827;">
                    <p style="margin-top: 5px; font-size: 14px;"><strong>Vishal Kumar</strong><br>Founder & Proprietor, Virtuole</p>
                </td>
            </tr>
        </table>
    </body></html>
    """

def get_lor_template(name, date, program_title, track_level, enroll_id, project_details):
    return f"""
    <html><body style="font-family: Helvetica, Arial, sans-serif; padding: 30px; color: #111827; line-height: 1.5;">
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
    <html><body style="font-family: Helvetica, Arial, sans-serif; padding: 30px; border: 8px solid #9f7aea; text-align: center; background-color: #faf5ff;">
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
                    <hr style="width: 200px; text-align: center; border: none; border-top: 1px solid #111827;">
                    <p style="margin-top: 5px; font-size: 14px;"><strong>Vishal Kumar</strong><br>Founder & Proprietor, Virtuole</p>
                </td>
            </tr>
        </table>
    </body></html>
    """

# =====================================================================
# 2. DUAL-RAIL EMAIL INFRASTRUCTURE
# =====================================================================

def send_system_email(to_email, subject, body_content, pdf_attachment=None, pdf_filename="document.pdf"):
    """Intern Channel: Outbound via AWS SES (service@virtuole.in). Replies routed to Zoho."""
    msg = MIMEMultipart()
    msg['From'] = f"Virtuole Services <{os.getenv('AWS_SMTP_USER')}>"
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.add_header('reply-to', 'support@virtuole.in')
    msg.attach(MIMEText(body_content, 'plain'))
    if pdf_attachment:
        part = MIMEApplication(pdf_attachment, Name=pdf_filename)
        part['Content-Disposition'] = f'attachment; filename="{pdf_filename}"'
        msg.attach(part)
    try:
        with smtplib.SMTP(os.getenv("AWS_SMTP_SERVER"), int(os.getenv("AWS_SMTP_PORT"))) as server:
            server.starttls()
            server.login(os.getenv("AWS_SMTP_USER"), os.getenv("AWS_SMTP_PASS"))
            server.send_message(msg)
    except Exception as e:
        print(f"AWS SES Delivery Exception: {e}")

def send_ambassador_email(to_email, subject, body_content):
    """Ambassador Channel: Direct outbound and inbound via Zoho (ambassador@virtuole.in)."""
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
# 3. VERCEL SERVERLESS CRON ROUTE (Replaces APScheduler)
# =====================================================================

def automated_system_maintenance():
    """Core logic for purging and updating database status."""
    now = datetime.utcnow()
    
    # 1. Purge Enrollments older than 30 days without submission
    thirty_days_ago = (now - timedelta(days=30)).isoformat()
    supabase.table('enrollments').delete().eq('status', 'active').lt('created_at', thirty_days_ago).execute()

    # 2. Purge Failed Submissions older than 24 hours (No resubmission)
    twenty_four_hours_ago = (now - timedelta(hours=24)).isoformat()
    expired_fails = supabase.table('enrollments').select('id', 'user_id').eq('status', 'failed').lt('created_at', twenty_four_hours_ago).execute()
    for row in expired_fails.data:
        supabase.table('enrollments').delete().eq('id', row['id']).execute()

    # 3. Smart Reminders (Active enrolled, not submitted, past 7 days)
    seven_days_ago = (now - timedelta(days=7)).isoformat()
    reminders = supabase.table('enrollments').select('id', 'user_id').eq('status', 'active').gt('created_at', seven_days_ago).execute()
    for row in reminders.data:
        user = supabase.table('users').select('email', 'full_name').eq('id', row['user_id']).execute().data[0]
        send_system_email(
            user['email'], 
            "Virtuole Internship: Pending Submission Reminder", 
            f"Hello {user['full_name']},\n\nDon't forget to submit your architecture. You have a 30-day window from enrollment to qualify for credentials."
        )

    # 4. Ambassador Expiry (Demote to Intern after 1 year)
    expired_ambassadors = supabase.table('users').select('id', 'email', 'full_name').eq('role', 'ambassador').lt('ambassador_expiry', now.isoformat()).execute()
    for row in expired_ambassadors.data:
        supabase.table('users').update({
            "role": "intern",
            "promo_code": None,
            "ambassador_expiry": None
        }).eq('id', row['id']).execute()
        
        send_system_email(
            row['email'], 
            "Virtuole Ambassador Program: Term Completed", 
            f"Hello {row['full_name']},\n\nYour 1-year term as a Virtuole Ambassador has officially concluded. We thank you for your incredible service and advocacy! Your account has now been seamlessly transitioned back to a standard Intern profile."
        )

@app.route('/api/cron/maintenance', methods=['GET', 'POST'])
def run_maintenance():
    """Endpoint triggered by Vercel's Cron engine."""
    auth_header = request.headers.get('Authorization')
    # Validate the request came from Vercel using the secure key
    if auth_header != f"Bearer {os.getenv('CRON_SECRET_KEY')}":
        return jsonify({"error": "Unauthorized"}), 401
        
    try:
        automated_system_maintenance()
        return jsonify({"status": "Maintenance execution completed successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =====================================================================
# 4. AUTHENTICATION & REGISTRATION GATEWAYS
# =====================================================================

@app.route('/')
def home():
    programs = supabase.table('programs').select('*').eq('is_active', True).execute().data
    return render_template('index.html', offered_programs=programs)

@app.route('/api/register', methods=['POST'])
@limiter.limit("5 per minute")
def register():
    full_name = request.form.get('full_name')
    email = request.form.get('email')
    password = request.form.get('password')
    promo_used = request.form.get('promo_code')
    
    public_id = f"VT-2026-{random.randint(1000, 9999)}"
    
    try:
        auth_user = supabase.auth.sign_up({"email": email, "password": password})
        if auth_user:
            supabase.table('users').insert({
                "id": auth_user.user.id,
                "full_name": full_name,
                "email": email,
                "public_id": public_id,
                "role": "intern"
            }).execute()
            
            if promo_used:
                send_ambassador_email("ambassador@virtuole.in", f"Conversion Logged: Code {promo_used}", f"A new student has registered using promo code {promo_used}.")
                
            send_system_email(email, "Welcome to Virtuole", f"Hello {full_name},\nYour public identity ID is {public_id}. Please log in to your dashboard to view offered programs and begin your internship.")
            return redirect(url_for('login', message="Account created successfully."))
    except Exception as e:
        return render_template('login.html', error=str(e))

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        login_type = request.form.get('login_type') 
        
        try:
            supabase.auth.sign_in_with_password({"email": email, "password": password})
            user_data = supabase.table('users').select('*').eq('email', email).execute().data[0]
            
            if login_type == 'staff' and user_data['role'] == 'intern':
                return render_template('login.html', error="unauthorized")
                
            session['user_id'] = user_data['id']
            session['email'] = user_data['email']
            session['name'] = user_data['full_name']
            session['role'] = user_data['role']
            session['public_id'] = user_data['public_id']
            
            # Master RBAC Routing
            if session.get('role') == 'admin' and email == "admin@virtuole.in": 
                return redirect(url_for('dashboard_admin'))
            elif user_data['role'] == 'mentor': 
                return redirect(url_for('dashboard_mentor'))
            elif user_data['role'] == 'ambassador': 
                return redirect('/dashboard-ambassador')
            else: 
                return redirect(url_for('dashboard_intern'))
                
        except Exception:
            return render_template('login.html', error="unregistered")
            
    return render_template('login.html')

# =====================================================================
# 5. GTM PROMO CODE & PHONEPE SECURE GATEWAY
# =====================================================================

@app.route('/api/validate-promo', methods=['POST'])
def validate_promo():
    data = request.get_json()
    promo_code = data.get('promo_code', '').upper()
    ambassador = supabase.table('users').select('id').eq('promo_code', promo_code).eq('role', 'ambassador').execute().data
    if ambassador:
        return jsonify({"valid": True, "discount_percent": 10})
    return jsonify({"valid": False, "error": "Invalid or expired GTM promo code."}), 400

@app.route('/api/create-payment', methods=['POST'])
@limiter.limit("3 per minute")
def create_phonepe_payment():
    if not session.get('email'): return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json()
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
            final_price = int(base_price * 0.9)  # 10% Discount applied
            applied_promo = promo_code

    transaction_id = f"VT-TXN-{random.randint(100000, 999999)}"
    amount_in_paise = final_price * 100 

    payload = {
        "merchantId": os.getenv("PHONEPE_MERCHANT_ID"),
        "merchantTransactionId": transaction_id,
        "merchantUserId": session['email'],
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
            return jsonify({"payment_url": response_data['data']['instrumentResponse']['redirectInfo']['url']})
        return jsonify({"error": "Gateway Error"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/phonepe-webhook', methods=['POST'])
def phonepe_webhook():
    decoded_response = json.loads(base64.b64decode(request.json.get('response')).decode('utf-8'))
    if decoded_response['code'] == 'PAYMENT_SUCCESS':
        transaction_id = decoded_response['data']['merchantTransactionId']
        supabase.table('payments').update({"status": "paid"}).eq('transaction_id', transaction_id).execute()
    return jsonify({"status": "received"}), 200


# =====================================================================
# 6. INTERN ACTIONS (ENROLL & SUBMIT)
# =====================================================================

@app.route('/api/enroll', methods=['POST'])
def api_enroll():
    if session.get('role') != 'intern': return redirect('/login')
    
    program_id = request.form.get('program_id')
    track_level = request.form.get('track_level')
    enrollment_id = f"VT-E-{random.randint(100000, 999999)}"
    
    supabase.table('enrollments').insert({
        "enrollment_id": enrollment_id,
        "user_id": session['user_id'],
        "program_id": program_id,
        "track_level": track_level,
        "college_name": request.form.get('college_name'),
        "course_name": request.form.get('course_name'),
        "session_year": request.form.get('session_year')
    }).execute()
    
    prog = supabase.table('programs').select('*').eq('id', program_id).execute().data[0]
    program_title = prog['title']
    project_details = prog['short_description']
    today_date = datetime.utcnow().strftime("%B %d, %Y")

    # Generate Portrait Offer Letter
    html_offer = get_offer_letter_template(session['name'], today_date, program_title, track_level.title(), enrollment_id, project_details)
    pdf_offer = generate_pdf_from_html(html_offer, orientation='Portrait')

    send_system_email(
        session['email'], "Official Internship Offer Letter - Virtuole", 
        f"Congratulations {session['name']}, you are officially enrolled. Your tracking ID is {enrollment_id}. Find your Offer Letter attached.",
        pdf_attachment=pdf_offer, pdf_filename=f"Offer_Letter_{enrollment_id}.pdf"
    )
    return redirect(url_for('dashboard_intern'))

@app.route('/api/submit-project', methods=['POST'])
def api_submit_project():
    enrollment_id = request.form.get('enrollment_id')
    
    supabase.table('submissions').insert({
        "enrollment_id": enrollment_id,
        "code_link": request.form.get('code_link'),
        "defense_link": request.form.get('defense_link')
    }).execute()
    
    supabase.table('enrollments').update({"status": "submitted"}).eq('enrollment_id', enrollment_id).execute()
    
    send_system_email(session['email'], "Submission Received", f"Your architecture for {enrollment_id} has entered the Mentor grading matrix.")
    return redirect(url_for('dashboard_intern'))

# =====================================================================
# 7. MENTOR GRADING & AMBASSADOR TASK APPROVALS
# =====================================================================

@app.route('/api/grade-submission', methods=['POST'])
def grade_submission():
    if session.get('role') != 'mentor': return redirect('/login')
    
    sub_id = request.form.get('submission_id')
    enrollment_id = request.form.get('enrollment_id')
    score = int(request.form.get('score'))
    feedback = request.form.get('feedback', 'No specific feedback provided.')
    
    enroll_data = supabase.table('enrollments').select('*, programs(title, short_description)').eq('enrollment_id', enrollment_id).execute().data[0]
    student = supabase.table('users').select('email', 'full_name').eq('id', enroll_data['user_id']).execute().data[0]
    program_title = enroll_data['programs']['title']
    project_details = enroll_data['programs']['short_description']
    today_date = datetime.utcnow().strftime("%B %d, %Y")
    
    if score >= 80:
        # Generate Landscape Certificate
        html_cert = get_certificate_template(student['full_name'], today_date, program_title, enroll_data['track_level'].title(), enrollment_id, score)
        pdf_cert = generate_pdf_from_html(html_cert, orientation='Landscape')
        db_updates = {"score": score, "certificate_url": f"https://virtuole.in/verify/{enrollment_id}", "evaluated_at": datetime.utcnow().isoformat()}
        
        if score == 100:
            # Generate Portrait LoR
            html_lor = get_lor_template(student['full_name'], today_date, program_title, enroll_data['track_level'].title(), enrollment_id, project_details)
            pdf_lor = generate_pdf_from_html(html_lor, orientation='Portrait')
            
            db_updates["lor_url"] = f"https://virtuole.in/verify/{enrollment_id}/lor"
            body_msg = f"{student['full_name']}, flawless defense. Attached are your official Certificate of Completion AND your Elite Founder's Letter of Recommendation."
            subj = "Elite LoR Unlocked - Virtuole"
            
            msg = MIMEMultipart()
            msg['From'] = f"Virtuole Services <{os.getenv('AWS_SMTP_USER')}>"
            msg['To'] = student['email']
            msg['Subject'] = subj
            msg.add_header('reply-to', 'support@virtuole.in')
            msg.attach(MIMEText(body_msg, 'plain'))
            
            part_cert = MIMEApplication(pdf_cert, Name=f"Certificate_{enrollment_id}.pdf")
            part_cert['Content-Disposition'] = f'attachment; filename="Certificate_{enrollment_id}.pdf"'
            msg.attach(part_cert)
            
            part_lor = MIMEApplication(pdf_lor, Name=f"LoR_{enrollment_id}.pdf")
            part_lor['Content-Disposition'] = f'attachment; filename="LoR_{enrollment_id}.pdf"'
            msg.attach(part_lor)
            
            with smtplib.SMTP(os.getenv("AWS_SMTP_SERVER"), int(os.getenv("AWS_SMTP_PORT"))) as server:
                server.starttls()
                server.login(os.getenv("AWS_SMTP_USER"), os.getenv("AWS_SMTP_PASS"))
                server.send_message(msg)
                
            supabase.table('submissions').update(db_updates).eq('id', sub_id).execute()
            supabase.table('enrollments').update({"status": "graded"}).eq('enrollment_id', enrollment_id).execute()
            
        else:
            body_msg = f"{student['full_name']}, you passed with a {score}%. Your official MSME certificate is attached."
            supabase.table('submissions').update(db_updates).eq('id', sub_id).execute()
            supabase.table('enrollments').update({"status": "graded"}).eq('enrollment_id', enrollment_id).execute()
            send_system_email(student['email'], "Certification Passed - Virtuole", body_msg, pdf_attachment=pdf_cert, pdf_filename=f"Certificate_{enrollment_id}.pdf")
    else:
        # Failure logic: 24h resubmit window
        supabase.table('submissions').delete().eq('id', sub_id).execute() 
        supabase.table('enrollments').update({"status": "failed", "created_at": datetime.utcnow().isoformat()}).eq('enrollment_id', enrollment_id).execute()
        
        failure_email_body = f"""Dear {student['full_name']},

Your submission scored {score}%, failing the 80% certification threshold. 
MENTOR FEEDBACK: "{feedback}"
You have exactly 24 hours to correct these flaws and resubmit via your dashboard.
Resubmit: https://www.virtuole.in/dashboard-intern

The Virtuole Evaluation Team"""
        send_system_email(student['email'], "ACTION REQUIRED: Submission Failed - 24H Resubmit Window", failure_email_body)
        
    return redirect(url_for('dashboard_mentor'))

@app.route('/api/evaluate-task', methods=['POST'])
def evaluate_task():
    if session.get('role') != 'mentor': return redirect('/login')
    claim_id = request.form.get('claim_id')
    action = request.form.get('action') 
    claim_data = supabase.table('ambassador_claims').select('ambassador_id, users(email, full_name)').eq('id', claim_id).execute().data[0]
    amb_email, amb_name, amb_id = claim_data['users']['email'], claim_data['users']['full_name'], claim_data['ambassador_id']

    if action == 'approve':
        pts = int(request.form.get('point_value'))
        supabase.table('ambassador_claims').update({"status": "approved"}).eq('id', claim_id).execute()
        curr_pts = supabase.table('users').select('total_points').eq('id', amb_id).execute().data[0]['total_points'] or 0
        supabase.table('users').update({"total_points": curr_pts + pts}).eq('id', amb_id).execute()
        send_ambassador_email(amb_email, "Task Approved: Merit Points Awarded!", f"Great job {amb_name}! +{pts} Points added.")
    elif action == 'reject':
        supabase.table('ambassador_claims').update({"status": "rejected"}).eq('id', claim_id).execute()
        send_ambassador_email(amb_email, "Task Proof Rejected", f"Hi {amb_name},\nYour task proof could not be verified. No points awarded.")
    return redirect(url_for('dashboard_mentor'))


# =====================================================================
# 8. ADMIN ACTIONS
# =====================================================================

@app.route('/admin/add-program', methods=['POST'])
def add_program():
    if session.get('role') != 'admin': return redirect('/login')
    supabase.table('programs').insert({
        "title": request.form.get('title'),
        "short_description": request.form.get('short_description'),
        "specs_beginner": request.form.get('specs_beginner'),
        "specs_intermediate": request.form.get('specs_intermediate'),
        "specs_expert": request.form.get('specs_expert'),
        "price_beginner": int(request.form.get('price_beginner')),
        "price_intermediate": int(request.form.get('price_intermediate')),
        "price_expert": int(request.form.get('price_expert')),
        "is_active": True
    }).execute()
    return redirect(url_for('dashboard_admin'))

@app.route('/admin/delete-program', methods=['POST'])
def delete_program():
    if session.get('role') != 'admin': return redirect('/login')
    supabase.table('programs').delete().eq('id', request.form.get('program_id')).execute()
    return redirect(url_for('dashboard_admin'))

@app.route('/admin/add-task', methods=['POST'])
def add_task():
    if session.get('role') != 'admin': return redirect('/login')
    supabase.table('ambassador_tasks').insert({"title": request.form.get('title'), "description": request.form.get('description'), "point_value": int(request.form.get('point_value')), "is_active": True}).execute()
    return redirect(url_for('dashboard_admin'))

@app.route('/admin/delete-task', methods=['POST'])
def delete_task():
    if session.get('role') != 'admin': return redirect('/login')
    supabase.table('ambassador_tasks').delete().eq('id', request.form.get('task_id')).execute()
    return redirect(url_for('dashboard_admin'))

@app.route('/admin/update-role', methods=['POST'])
def update_role():
    if session.get('role') != 'admin': return redirect('/login')
    user_id = request.form.get('user_id')
    new_role = request.form.get('new_role')
    user = supabase.table('users').select('email', 'full_name').eq('id', user_id).execute().data[0]
    update_data = {'role': new_role}
    
    if new_role == 'ambassador':
        update_data['public_id'] = f"AMB-2026-{random.randint(100, 999)}"
        update_data['promo_code'] = f"AMB{''.join(random.choices(string.ascii_uppercase, k=4))}"
        update_data['ambassador_expiry'] = (datetime.utcnow() + timedelta(days=365)).isoformat()
        send_ambassador_email(user['email'], "Welcome to the Ambassador Program", f"Hi {user['full_name']},\nYou have been promoted to Ambassador. Your promo code is {update_data['promo_code']}.")
        
    supabase.table('users').update(update_data).eq('id', user_id).execute()
    return redirect(url_for('dashboard_admin'))

@app.route('/admin/mark-swag-sent', methods=['POST'])
def mark_swag_sent():
    if session.get('role') != 'admin': return redirect('/login')
    # Can add relational logic for shipped tracking IDs later
    return redirect(url_for('dashboard_admin'))


# =====================================================================
# 9. AMBASSADOR ACTIONS
# =====================================================================

@app.route('/api/claim-points', methods=['POST'])
def claim_points():
    if session.get('role') != 'ambassador': return redirect('/login')
    supabase.table('ambassador_claims').insert({
        "ambassador_id": session['user_id'],
        "task_id": request.form.get('task_id'),
        "proof_link": request.form.get('proof_link'),
        "notes": request.form.get('notes')
    }).execute()
    send_ambassador_email("ambassador@virtuole.in", "New Point Claim Submitted", f"Ambassador {session['name']} has submitted proof for task evaluation.")
    return redirect(url_for('dashboard_ambassador'))

@app.route('/api/update-address', methods=['POST'])
def update_address():
    if session.get('role') != 'ambassador': return redirect('/login')
    shipping_address = request.form.get('shipping_address')
    supabase.table('users').update({"shipping_address": shipping_address}).eq('id', session['user_id']).execute()
    return redirect(url_for('dashboard_ambassador'))


# =====================================================================
# 10. DASHBOARD RENDER ROUTING
# =====================================================================

@app.route('/dashboard-intern')
def dashboard_intern():
    if session.get('role') == 'intern':
        u_id = session['user_id']
        active_enrolls = supabase.table('enrollments').select('*, programs(*)').eq('user_id', u_id).eq('status', 'active').execute().data
        active_projects = []
        for e in active_enrolls:
            prog = e['programs']
            track = e['track_level']
            active_projects.append({
                'program_title': prog['title'], 'description': prog['short_description'], 'track_level': track, 'enrollment_id': e['enrollment_id'],
                'specs_link': prog.get(f'specs_{track}', '#'), 'amount_due': prog.get(f'price_{track}', 0)
            })
        
        offered = supabase.table('programs').select('*').eq('is_active', True).execute().data
        
        completed_projects = []
        graded_enrolls = supabase.table('enrollments').select('*, programs(title)').eq('user_id', u_id).in_('status', ['graded', 'submitted']).execute().data
        for e in graded_enrolls:
            sub = supabase.table('submissions').select('*').eq('enrollment_id', e['enrollment_id']).execute().data
            if sub:
                s = sub[0]
                completed_projects.append({'score': s.get('score'), 'program_title': e['programs']['title'], 'track_level': e['track_level'], 'enrollment_id': e['enrollment_id'], 'evaluated_date': s.get('evaluated_at', '').split('T')[0] if s.get('evaluated_at') else 'Pending', 'certificate_url': s.get('certificate_url'), 'lor_url': s.get('lor_url')})

        return render_template('dashboard_intern.html', user_name=session.get('name'), active_projects=active_projects, offered_programs=offered, completed_projects=completed_projects)
    return redirect(url_for('login'))

@app.route('/dashboard-mentor')
def dashboard_mentor():
    if session.get('role') == 'mentor':
        pend_subs = supabase.table('submissions').select('*').is_('score', 'null').execute().data
        graded_subs = supabase.table('submissions').select('*').not_.is_('score', 'null').execute().data
        claims_query = supabase.table('ambassador_claims').select('id, proof_link, notes, ambassador_id, users(full_name, email), ambassador_tasks(title, point_value)').eq('status', 'pending').execute().data
        pending_claims = [{"id": c['id'], "ambassador_id": c['ambassador_id'], "ambassador_name": c['users']['full_name'], "ambassador_email": c['users']['email'], "task_title": c['ambassador_tasks']['title'], "point_value": c['ambassador_tasks']['point_value'], "proof_link": c['proof_link'], "notes": c['notes']} for c in claims_query]
        return render_template('dashboard_mentor.html', user_name=session.get('name'), pending_submissions=pend_subs, graded_submissions=graded_subs, pending_claims=pending_claims)
    return redirect(url_for('login'))

@app.route('/dashboard-admin')
def dashboard_admin():
    if session.get('role') == 'admin' and session.get('email') == "admin@virtuole.in":
        earnings = sum([p['amount']/100 for p in supabase.table('payments').select('amount').eq('status', 'paid').execute().data])
        enrolled = len(supabase.table('enrollments').select('id').execute().data)
        certified = len(supabase.table('submissions').select('id').gte('score', 80).execute().data)
        pend_grading = len(supabase.table('submissions').select('id').is_('score', 'null').execute().data)
        progs = supabase.table('programs').select('*').execute().data
        tasks = supabase.table('ambassador_tasks').select('*').execute().data
        users = supabase.table('users').select('*').execute().data
        tier3 = [u for u in users if u['role'] == 'ambassador' and u['total_points'] >= 1500 and u['total_points'] < 3000]
        tier4 = [u for u in users if u['role'] == 'ambassador' and u['total_points'] >= 3000]
        return render_template('dashboard_admin.html', user_name=session.get('name'), total_earnings=earnings, total_enrolled=enrolled, total_certified=certified, pending_grading=pend_grading, offered_programs=progs, all_tasks=tasks, user_directory=users, tier3_ambassadors=tier3, tier4_ambassadors=tier4)
    return redirect(url_for('login'))

@app.route('/dashboard-ambassador')
def dashboard_ambassador():
    if session.get('role') == 'ambassador':
        u = supabase.table('users').select('*').eq('id', session['user_id']).execute().data[0]
        pts = u['total_points'] or 0
        tier_name = "Kickstart"
        if pts >= 3000: tier_name = "Star Ambassador"
        elif pts >= 1500: tier_name = "Community Lead"
        elif pts >= 500: tier_name = "Campus Advocate"
        refs = len(supabase.table('payments').select('id').eq('applied_promo', u['promo_code']).eq('status', 'paid').execute().data)
        tasks = supabase.table('ambassador_tasks').select('*').eq('is_active', True).execute().data

        return render_template('dashboard_ambassador.html', 
            ambassador_name=session.get('name'), 
            valid_until_date=u['ambassador_expiry'].split('T')[0] if u.get('ambassador_expiry') else 'N/A', 
            total_points=pts, 
            current_tier_name=tier_name, 
            total_referrals=refs, 
            promo_code=u['promo_code'], 
            amb_id=u['public_id'], 
            available_tasks=tasks,
            shipping_address=u['shipping_address']
        )
    return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# =====================================================================
# 11. AMBASSADOR REWARDS & CERTIFICATE DOWNLOADS
# =====================================================================

@app.route('/download_cert/<tier>')
def download_cert(tier):
    if session.get('role') != 'ambassador': 
        return redirect('/login')
    
    u = supabase.table('users').select('*').eq('id', session['user_id']).execute().data[0]
    pts = u['total_points'] or 0
    
    tier_name = ""
    if tier == 'kickstart': 
        tier_name = "Kickstart"
    elif tier == 'advocate' and pts >= 500: 
        tier_name = "Campus Advocate"
    elif tier == 'lead' and pts >= 1500: 
        tier_name = "Community Lead"
    elif tier == 'star' and pts >= 3000: 
        tier_name = "Star Ambassador"
    else:
        return "Unauthorized or Insufficient Points for this Tier", 403

    today_date = datetime.utcnow().strftime("%B %d, %Y")
    html_cert = get_ambassador_certificate_template(u['full_name'], today_date, tier_name, pts, u['public_id'])
    pdf_cert = generate_pdf_from_html(html_cert, orientation='Landscape')
    
    response = make_response(pdf_cert)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename="Virtuole_{tier_name}_Certificate.pdf"'
    return response

@app.route('/download_lor/<type>')
def download_lor(type):
    if session.get('role') != 'ambassador': 
        return redirect('/login')
    
    u = supabase.table('users').select('*').eq('id', session['user_id']).execute().data[0]
    pts = u['total_points'] or 0
    
    if type == 'devrel' and pts >= 1500:
        today_date = datetime.utcnow().strftime("%B %d, %Y")
        project_details = "Community Leadership, Developer Relations (DevRel), and Technical Advocacy for the Virtuole MSME platform."
        
        html_lor = get_lor_template(u['full_name'], today_date, "GTM Ambassador Program", "Community Lead", u['public_id'], project_details)
        pdf_lor = generate_pdf_from_html(html_lor, orientation='Portrait')
        
        response = make_response(pdf_lor)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = 'attachment; filename="Virtuole_DevRel_LoR.pdf"'
        return response
    else:
        return "Unauthorized or Insufficient Points", 403

# =====================================================================
# 12. PUBLIC CREDENTIAL VERIFICATION & APPLICATION
# =====================================================================

@app.route('/verify.html')
def verify_page():
    return render_template('verify.html')

@app.route('/terms')
def terms_page():
    return render_template('terms.html')

@app.route('/refund')
def refund_page():
    return render_template('refund.html')

@app.route('/privacy')
def privacy_page():
    return render_template('privacy.html')

@app.route('/verify-credential', methods=['GET'])
def verify_credential():
    credential_id = request.args.get('credential_id')
    if not credential_id:
        return render_template('verify.html')
        
    try:
        enroll_query = supabase.table('enrollments').select('*, programs(title), users(full_name)').eq('enrollment_id', credential_id).eq('status', 'graded').execute()
        if not enroll_query.data: return render_template('verify.html', error=True)
            
        enroll_data = enroll_query.data[0]
        sub_query = supabase.table('submissions').select('*').eq('enrollment_id', credential_id).execute()
        if not sub_query.data: return render_template('verify.html', error=True)
            
        sub_data = sub_query.data[0]
        verified_data = {
            "student_name": enroll_data['users']['full_name'],
            "program_title": enroll_data['programs']['title'],
            "track_level": enroll_data['track_level'],
            "score": sub_data['score'],
            "enrollment_id": credential_id,
            "evaluated_date": sub_data['evaluated_at'].split('T')[0] if sub_data.get('evaluated_at') else "N/A",
            "certificate_url": sub_data.get('certificate_url'),
            "lor_url": sub_data.get('lor_url')
        }
        return render_template('verify.html', verified_data=verified_data)
    except Exception as e:
        print(f"Verification Error: {e}")
        return render_template('verify.html', error=True)
    
@app.route('/apply-ambassador')
def apply_ambassador_page():
    return render_template('applyambass.html')

@app.route('/api/apply-ambassador', methods=['POST'])
def apply_ambassador():
    name = request.form.get('name')
    email = request.form.get('email')
    motivation = request.form.get('motivation')

    supabase.table('ambassador_applications').insert({
        "name": name, "email": email, "motivation": motivation, "status": "pending_round_2"
    }).execute()

    subject = "Virtuole Ambassador Program: Round 2 Application"
    body = f"""Dear {name},\n\nThank you for applying to the Virtuole Ambassador Program. We have reviewed your initial interest.\n\nTo proceed to the second round of selection, please complete the mandatory GTM task assessment via this Google Form:\n[INSERT YOUR GOOGLE FORM LINK HERE]\n\nUpon completion, our team will review your responses and reach out regarding your tier allocation.\n\nRegards,\nThe Virtuole Ambassador Team"""
    send_ambassador_email(email, subject, body)

    return "Application submitted! Check your email for the Round 2 link."

if __name__ == '__main__':
    app.run(debug=True, port=5000)
