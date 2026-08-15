
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from api.config import supabase, limiter
from api.utils.email import send_system_email, send_ambassador_email
import random, string, uuid, json
from datetime import datetime, timedelta

auth_bp = Blueprint('auth', __name__)



@auth_bp.route('/', methods=['GET', 'POST'])
def home():
    programs = []
    if supabase:
        programs = supabase.table('programs').select('*').eq('is_active', True).execute().data
    return render_template('index.html', offered_programs=programs)

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
                send_ambassador_email("ambassador@virtuole.in", f"Conversion Logged: Code {promo_used}", f"A new student has registered using promo code {promo_used}.")
            send_system_email(email, "Welcome to Virtuole", f"Hello {full_name},\nYour public identity ID is {public_id}. Please log in to your dashboard to view offered programs and begin your internship.")
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
                return render_template('login.html', error="Incorrect email or password.")
            return render_template('login.html', error=f"Login Error: {error_str}")
            
    return render_template('login.html', message=message)

@auth_bp.route('/logout')
@auth_bp.route('/api/logout')
def logout():
    session.clear()
    from flask import make_response
    response = make_response(redirect('/login'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response

@auth_bp.route('/forgot-password', methods=['POST'])
@auth_bp.route('/api/forgot-password', methods=['POST'])
@limiter.limit("3 per minute")
def forgot_password():
    email = request.form.get('email')
    try:
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

