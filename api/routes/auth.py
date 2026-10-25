
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from api.config import supabase, limiter, supabase_admin, SUPABASE_URL, SUPABASE_KEY
from api.utils.email import send_system_email, send_ambassador_email
import random, string, uuid, json
from datetime import datetime, timedelta
from api.utils.notifications import send_notification

auth_bp = Blueprint('auth', __name__)



def fix_gdrive_url(url):
    if not url: return url
    if "drive.google.com/file/d/" in url:
        try:
            file_id = url.split("/d/")[1].split("/")[0]
            return f"https://lh3.googleusercontent.com/d/{file_id}"
        except:
            return url
    return url

@auth_bp.route('/', methods=['GET', 'POST'])
def home():
    programs = []
    offered_programs_grouped = {}
    if supabase:
        programs = supabase.table('programs').select('*').eq('is_active', True).execute().data
        for p in programs:
            p['image_url'] = fix_gdrive_url(p.get('image_url'))
            cat = p.get('category') or 'General'
            if cat not in offered_programs_grouped:
                offered_programs_grouped[cat] = []
            offered_programs_grouped[cat].append(p)
    return render_template('index.html', offered_programs=offered_programs_grouped)

@auth_bp.route('/register', methods=['POST'])
@auth_bp.route('/api/register', methods=['POST'])
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
                send_notification('admin', None, 'promo_used', f"Conversion Logged: Code {promo_used}", f"A new student has registered using promo code {promo_used}.")
            send_system_email(email, "Welcome to Virtuole", f"Hello {full_name},\nYour public identity ID is {public_id}. Please log in to your dashboard to view offered programs and begin your internship.")
            send_notification('intern', auth_user.user.id, 'signup', 'Welcome to Virtuole', f"Hello {full_name}, your public identity ID is {public_id}. Start exploring programs!")
            return redirect(url_for('auth.login', message="Account created successfully. Please login."))
        # sign_up returned no user (e.g. confirmation pending / duplicate email)
        return render_template('login.html', error="We could not create your account. This email may already be registered — try logging in instead.")
    except Exception as e:
        return render_template('login.html', error=str(e))

@auth_bp.route('/login', methods=['GET', 'POST'])
@auth_bp.route('/api/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    message = request.args.get('message')
    error = request.args.get('error')
    supabase_url = SUPABASE_URL or "https://fkrxuptprlhfedlyanzf.supabase.co"
    supabase_key = SUPABASE_KEY or ""

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        try:
            # 1. Authorize via Supabase
            auth_response = supabase.auth.sign_in_with_password({"email": email, "password": password})
            
            # 2. Grab profile from Database
            user_data_response = supabase.table('users').select('*').eq('email', email).execute()
            if not user_data_response.data:
                return render_template('login.html', error="Profile data missing in the database.", supabase_url=supabase_url, supabase_key=supabase_key)
            
            user_data = user_data_response.data[0]
            
            # 3. Establish strict session data
            session.permanent = True
            session['user_id'] = user_data['id']
            session['email'] = user_data['email']
            session['name'] = user_data['full_name']
            session['public_id'] = user_data['public_id']
            
            # 4. Normalize the role string to completely eliminate redirect loop issues
            user_role = str(user_data.get('role', 'intern')).strip().lower()
            if email.strip().lower() == "admin@virtuole.in":
                user_role = "admin"
            session['role'] = user_role
            
            # Force Flask to instantly save the session
            session.modified = True 
            
            # 5. Smart Routing based on normalized role
            if user_role == 'admin': 
                return redirect(url_for('dashboard.dashboard_admin'))
            elif user_role == 'mentor': 
                return redirect(url_for('dashboard.dashboard_mentor'))
            elif user_role == 'ambassador': 
                return redirect(url_for('dashboard.dashboard_ambassador'))
            else: 
                return redirect(url_for('dashboard.dashboard_intern'))
                
        except Exception as e:
            error_str = str(e)
            if "Invalid login credentials" in error_str or "AuthApiError" in error_str:
                return render_template('login.html', error="Incorrect email or password.", supabase_url=supabase_url, supabase_key=supabase_key)
            return render_template('login.html', error=f"Login Error: {error_str}", supabase_url=supabase_url, supabase_key=supabase_key)
            
    return render_template('login.html', message=message, error=error, supabase_url=supabase_url, supabase_key=supabase_key)

@auth_bp.route('/login/oauth/<provider>')
def oauth_login(provider):
    provider = provider.lower().strip()
    if provider not in ['google', 'github']:
        return redirect(url_for('auth.login', error="Unsupported login provider."))

    client_redirect = request.args.get('redirect_to')
    if client_redirect and client_redirect.startswith(('http://', 'https://')):
        callback_url = client_redirect
    else:
        req_host = request.headers.get('X-Forwarded-Host') or request.host
        proto = 'https' if (request.headers.get('X-Forwarded-Proto') == 'https' or request.is_secure) else 'http'
        callback_url = f"{proto}://{req_host}/auth/callback"

    base_url = (SUPABASE_URL or "https://fkrxuptprlhfedlyanzf.supabase.co").rstrip('/')
    oauth_url = f"{base_url}/auth/v1/authorize?provider={provider}&redirect_to={callback_url}"
    return redirect(oauth_url)

@auth_bp.route('/auth/callback')
def auth_callback():
    error = request.args.get('error_description') or request.args.get('error')
    if error:
        return redirect(url_for('auth.login', error=f"Sign in canceled or failed: {error}"))

    supabase_url = SUPABASE_URL or "https://fkrxuptprlhfedlyanzf.supabase.co"
    supabase_key = SUPABASE_KEY or ""
    return render_template('auth_callback.html', supabase_url=supabase_url, supabase_key=supabase_key)

@auth_bp.route('/api/auth/oauth-session', methods=['POST'])
@limiter.limit("20 per minute")
def oauth_session():
    data = request.get_json(silent=True) or {}
    access_token = data.get('access_token')
    auth_code = data.get('code')
    promo_code = (data.get('promo_code') or '').strip().upper()

    if not access_token and not auth_code:
        return jsonify({"success": False, "error": "Access token or auth code is required."}), 400

    if not supabase:
        return jsonify({"success": False, "error": "Database service is temporarily unavailable."}), 503

    try:
        sb_user = None

        # 1. If code was returned (PKCE flow), exchange it for session
        if not access_token and auth_code:
            try:
                ex_res = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
                if ex_res and ex_res.session:
                    access_token = ex_res.session.access_token
                if ex_res and ex_res.user:
                    sb_user = ex_res.user
            except Exception as ce:
                print(f"Code exchange exception: {ce}")

        # 2. Cryptographically verify the access token using Supabase Auth
        if not sb_user and access_token:
            user_response = supabase.auth.get_user(access_token)
            if user_response and user_response.user:
                sb_user = user_response.user

        if not sb_user:
            return jsonify({"success": False, "error": "Invalid or expired authentication session."}), 401

        sb_user = user_response.user
        email = sb_user.email
        if not email:
            return jsonify({"success": False, "error": "Could not retrieve email from account."}), 400

        user_metadata = sb_user.user_metadata or {}
        full_name = (
            user_metadata.get('full_name') or 
            user_metadata.get('name') or 
            user_metadata.get('user_name') or 
            email.split('@')[0]
        ).strip()

        # Check if user already exists in public users table
        user_data_response = supabase.table('users').select('*').eq('email', email).execute()

        if user_data_response.data and len(user_data_response.data) > 0:
            user_data = user_data_response.data[0]
        else:
            # New user registration via OAuth
            public_id = f"VT-2026-{random.randint(1000, 9999)}"
            new_user = {
                "id": sb_user.id,
                "full_name": full_name,
                "email": email,
                "public_id": public_id,
                "role": "intern"
            }
            insert_res = supabase.table('users').insert(new_user).execute()
            user_data = insert_res.data[0] if insert_res.data else new_user

            if promo_code:
                try:
                    send_notification(
                        'admin', None, 'promo_used',
                        f"Conversion Logged: Code {promo_code}",
                        f"A new student ({full_name}) registered via OAuth using promo code {promo_code}."
                    )
                except Exception as pe:
                    print(f"OAuth Promo Notification Error: {pe}")

            try:
                send_system_email(
                    email,
                    "Welcome to Virtuole",
                    f"Hello {full_name},\nYour public identity ID is {public_id}. Please log in to your dashboard to view offered programs and begin your internship."
                )
            except Exception as ee:
                print(f"OAuth Welcome Email Error: {ee}")

            try:
                send_notification(
                    'intern', sb_user.id, 'signup',
                    'Welcome to Virtuole',
                    f"Hello {full_name}, your public identity ID is {public_id}. Start exploring programs!"
                )
            except Exception as ne:
                print(f"OAuth Welcome Notification Error: {ne}")

        # Establish Flask session
        session.permanent = True
        session['user_id'] = user_data['id']
        session['email'] = user_data['email']
        session['name'] = user_data.get('full_name', full_name)
        session['public_id'] = user_data.get('public_id')

        user_role = str(user_data.get('role', 'intern')).strip().lower()
        if email.strip().lower() == "admin@virtuole.in":
            user_role = "admin"
        session['role'] = user_role
        session.modified = True

        # Role-based dashboard redirect
        if user_role == 'admin':
            redirect_url = url_for('dashboard.dashboard_admin')
        elif user_role == 'mentor':
            redirect_url = url_for('dashboard.dashboard_mentor')
        elif user_role == 'ambassador':
            redirect_url = url_for('dashboard.dashboard_ambassador')
        else:
            redirect_url = url_for('dashboard.dashboard_intern')

        return jsonify({
            "success": True,
            "redirect_url": redirect_url
        })

    except Exception as e:
        print(f"OAuth Session Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 400

@auth_bp.route('/logout')
@auth_bp.route('/api/logout')
def logout():
    session.clear()
    from flask import make_response
    response = make_response(redirect('/login'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.delete_cookie('virtuole_session', path='/')
    response.delete_cookie('session', path='/')
    return response

@auth_bp.route('/forgot-password', methods=['POST'])
@auth_bp.route('/api/forgot-password', methods=['POST'])
@limiter.limit("3 per minute")
def forgot_password():
    email = request.form.get('email')
    try:
        if supabase_admin:
            try:
                link_data = supabase_admin.auth.admin.generate_link(
                    {"type": "recovery", "email": email, "options": {"redirect_to": "https://www.virtuole.in/reset-password"}}
                )
                reset_url = link_data.properties.action_link
                
                html_content = f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 5px;">
                    <h2 style="color: #333;">Password Reset Request</h2>
                    <p style="color: #555;">Hello,</p>
                    <p style="color: #555;">We received a request to reset your password. Click the button below to choose a new one:</p>
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{reset_url}" style="background-color: #007bff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold;">Reset Password</a>
                    </div>
                    <p style="color: #555; font-size: 0.9em;">Or copy and paste this link into your browser:<br>
                    <a href="{reset_url}">{reset_url}</a></p>
                    <p style="color: #777; font-size: 0.8em; margin-top: 30px;">If you didn't request a password reset, you can safely ignore this email.</p>
                </div>
                """
                send_system_email(email, "Reset Your Password - Virtuole", html_content, is_html=True)
            except Exception as e:
                print(f"Generate link failed (user might not exist): {e}")
                pass
        else:
            supabase.auth.reset_password_for_email(
                email, 
                options={"redirect_to": "https://www.virtuole.in/reset-password"}
            )
        return redirect(url_for('auth.login', message="If an account exists, a password reset link has been sent to your email!"))
    except Exception as e:
        return render_template('login.html', error=str(e))

@auth_bp.route('/reset-password')
def reset_password_page():
    return render_template('reset_password.html')

@auth_bp.route('/update-password', methods=['POST'])
@auth_bp.route('/api/update-password', methods=['POST'])
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
        return redirect(url_for('auth.login', message="Password updated successfully! Please log in."))
    except Exception as e:
        return render_template('reset_password.html', error=str(e))

