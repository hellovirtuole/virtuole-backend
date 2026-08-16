
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from api.config import supabase, limiter
from api.utils.email import send_system_email, send_ambassador_email
import random, string, uuid, json
from datetime import datetime, timedelta

intern_bp = Blueprint('intern', __name__)



@intern_bp.route('/validate-promo', methods=['POST'])
@intern_bp.route('/api/validate-promo', methods=['POST'])
def validate_promo():
    data = request.get_json()
    promo_code = data.get('promo_code', '').upper()
    ambassador = supabase.table('users').select('id').eq('promo_code', promo_code).eq('role', 'ambassador').execute().data
    coupon = supabase.table('users').select('id, total_points, ambassador_expiry, coupon_usage_limit, coupon_user_limit, coupon_allowed_level').eq('promo_code', promo_code).eq('role', 'coupon').execute().data
    
    if ambassador:
        return jsonify({"valid": True, "discount_percent": 10})
    elif coupon:
        c_data = coupon[0]
        if c_data.get('ambassador_expiry'):
            try:
                expiry = datetime.fromisoformat(c_data['ambassador_expiry'])
                if datetime.utcnow() > expiry.replace(tzinfo=None):
                    return jsonify({"valid": False, "error": "This coupon has expired."}), 400
            except ValueError:
                pass
                
        # Validate track level
        enrollment_id = data.get('enrollment_id')
        if enrollment_id and c_data.get('coupon_allowed_level'):
            enroll = supabase.table('enrollments').select('track_level').eq('enrollment_id', enrollment_id).execute().data
            if enroll and enroll[0]['track_level'].lower() != c_data['coupon_allowed_level'].lower():
                return jsonify({"valid": False, "error": f"This coupon is only valid for {c_data['coupon_allowed_level']} tracks."}), 400
                
        # Validate total usage limit
        if c_data.get('coupon_usage_limit') is not None:
            c_payments = supabase.table('payments').select('id').eq('applied_promo', promo_code).eq('status', 'paid').execute().data
            if len(c_payments) >= c_data['coupon_usage_limit']:
                return jsonify({"valid": False, "error": "This coupon has reached its maximum global usage limit."}), 400
                
        # Validate per-user limit
        if c_data.get('coupon_user_limit') is not None:
            user_id = session.get('user_id')
            if user_id:
                u_payments = supabase.table('payments').select('id').eq('applied_promo', promo_code).eq('status', 'paid').eq('user_id', user_id).execute().data
                if len(u_payments) >= c_data['coupon_user_limit']:
                    return jsonify({"valid": False, "error": "You have reached your personal usage limit for this coupon."}), 400
                    
        return jsonify({"valid": True, "discount_percent": c_data.get('total_points', 0)})
        
    return jsonify({"valid": False, "error": "Invalid or expired code."}), 400

@intern_bp.route('/create-payment', methods=['POST'])
@intern_bp.route('/api/create-payment', methods=['POST'])
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
        is_ambassador = supabase.table('users').select('id').eq('promo_code', promo_code).eq('role', 'ambassador').execute().data
        is_coupon = supabase.table('users').select('id, total_points, ambassador_expiry').eq('promo_code', promo_code).eq('role', 'coupon').execute().data
        
        if is_ambassador:
            final_price = int(base_price * 0.9)
            applied_promo = promo_code
        elif is_coupon:
            c_data = is_coupon[0]
            is_expired = False
            if c_data.get('ambassador_expiry'):
                try:
                    expiry = datetime.fromisoformat(c_data['ambassador_expiry'])
                    if datetime.utcnow() > expiry.replace(tzinfo=None):
                        is_expired = True
                except ValueError:
                    pass
            
            if not is_expired:
                discount_percent = c_data.get('total_points', 0)
                final_price = int(base_price * ((100 - discount_percent) / 100))
                applied_promo = promo_code

    transaction_id = f"VT-TXN-{random.randint(100000, 999999)}"
    amount_in_paise = int(final_price * 100) 
    safe_merchant_user_id = session.get('public_id', 'VIRT-USER')
    
    if amount_in_paise == 0:
        # 100% discount applied! Skip PhonePe integration.
        supabase.table('submissions').insert({"enrollment_id": enrollment_id, "code_link": data.get('code_link'), "defense_link": data.get('defense_link')}).execute()
        supabase.table('payments').insert({"user_id": session['user_id'], "transaction_id": transaction_id, "amount": 0, "status": "paid", "applied_promo": applied_promo}).execute()
        
        if is_ajax:
            return jsonify({"payment_url": "/dashboard-intern"})
        return redirect("/dashboard-intern")
    
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

@intern_bp.route('/phonepe-webhook', methods=['POST'])
@intern_bp.route('/api/phonepe-webhook', methods=['POST'])
def phonepe_webhook():
    decoded_response = json.loads(base64.b64decode(request.json.get('response')).decode('utf-8'))
    if decoded_response['code'] == 'PAYMENT_SUCCESS':
        transaction_id = decoded_response['data']['merchantTransactionId']
        supabase.table('payments').update({"status": "paid"}).eq('transaction_id', transaction_id).execute()
    return jsonify({"status": "received"}), 200




@intern_bp.route('/enroll', methods=['POST'])
@intern_bp.route('/api/enroll', methods=['POST'])
def api_enroll():
    if str(session.get('role', '')).lower() not in ['intern', 'intern + ambassador']: return redirect('/login')
    program_id = request.form.get('program_id')
    track_level = request.form.get('track_level')
    enrollment_id = f"VT-E-{random.randint(100000, 999999)}"
    
    existing = supabase.table('enrollments').select('id').eq('user_id', session['user_id']).eq('program_id', program_id).eq('track_level', track_level).in_('status', ['active', 'submitted']).execute().data
    if existing:
        return redirect(url_for('dashboard.dashboard_intern'))
        
    supabase.table('enrollments').insert({
        "enrollment_id": enrollment_id, "user_id": session['user_id'], "program_id": program_id,
        "track_level": track_level, "status": "active"
    }).execute()
    
    prog = supabase.table('programs').select('*').eq('id', program_id).execute().data[0]
    
    duration_days = 90 if track_level.lower() == 'expert' else 30
    end_date = (datetime.utcnow() + timedelta(days=duration_days)).strftime("%B %d, %Y")
    
    html_offer = render_template('docs/offer_letter.html', name=session['name'], date=datetime.utcnow().strftime("%B %d, %Y"), program_title=prog['title'], track_level=track_level.title(), enroll_id=enrollment_id, project_details=prog['short_description'], duration_days=duration_days, end_date=end_date)
    
    send_system_email(session['email'], "Official Internship Offer Letter - Virtuole", html_offer, is_html=True)
    return redirect(url_for('dashboard.dashboard_intern'))


@intern_bp.route('/submit-project', methods=['POST'])
@intern_bp.route('/api/submit-project', methods=['POST'])
def api_submit_project():
    enrollment_id = request.form.get('enrollment_id')
    
    # Check if enrollment is valid and not expired before accepting submission
    enroll_data = supabase.table('enrollments').select('*').eq('enrollment_id', enrollment_id).in_('status', ['active', 'resubmit']).execute().data
    if not enroll_data:
        return "Enrollment not found or already submitted.", 403
        
    e = enroll_data[0]
    now = datetime.utcnow()
    try:
        start_dt = datetime.fromisoformat(e['created_at'].replace('Z', '+00:00')) if e.get('created_at') else now
    except:
        start_dt = now
    
    start_dt = start_dt.replace(tzinfo=None)
    
    if e['status'] == 'resubmit':
        duration_days = 1
    else:
        duration_days = 90 if e.get('track_level', '').lower() == 'expert' else 30
        
    end_dt = start_dt + timedelta(days=duration_days)
    
    if now > end_dt:
        if e['status'] == 'active':
            supabase.table('enrollments').delete().eq('id', e['id']).execute()
        elif e['status'] == 'resubmit':
            supabase.table('enrollments').update({"status": "failed"}).eq('id', e['id']).execute()
            supabase.table('submissions').insert({
                "enrollment_id": e['enrollment_id'], 
                "score": 0, 
                "certificate_url": "failed:Missed 24-hour resubmission deadline.",
                "evaluated_at": now.isoformat()
            }).execute()
        return "Your submission window has expired. The enrollment has been closed.", 403
    
    supabase.table('submissions').insert({"enrollment_id": enrollment_id, "code_link": request.form.get('code_link'), "defense_link": request.form.get('defense_link')}).execute()
    supabase.table('enrollments').update({"status": "submitted"}).eq('enrollment_id', enrollment_id).execute()
    send_system_email(session['email'], "Submission Received", f"Your architecture for {enrollment_id} has entered evaluation.")
    return redirect(url_for('dashboard.dashboard_intern'))


def parse_shipping_address(addr_str):
    if not addr_str: return {}
    if isinstance(addr_str, dict): return addr_str
    try:
        return json.loads(addr_str)
    except Exception:
        return {"name": "", "addr1": addr_str, "addr2": "", "city": "", "state": "", "pin": "", "phone": ""}


@intern_bp.route('/update-profile-intern', methods=['POST'])
@intern_bp.route('/api/update-profile-intern', methods=['POST'])
def update_profile_intern():
    if str(session.get('role', '')).lower() not in ['intern', 'intern + ambassador']:
        return redirect('/login')

    try:
        full_name = request.form.get('full_name', '').strip()
        gender = request.form.get('gender', '').strip()
        phone = request.form.get('phone', '').strip()
        city = request.form.get('city', '').strip()
        state = request.form.get('state', '').strip()
        college_name = request.form.get('college_name', '').strip()
        course_name = request.form.get('course_name', '').strip()
        session_year = request.form.get('session_year', '').strip()

        # Build profile details as a plain dict
        # profile_details column is jsonb — Supabase client sends dicts directly
        profile_data = {
            "gender": gender,
            "phone": phone,
            "city": city,
            "state": state,
            "college_name": college_name,
            "course_name": course_name,
            "session_year": session_year,
        }

        # Build update payload
        update_payload = {
            "profile_details": profile_data,
            "shipping_address": json.dumps(profile_data),
        }
        if full_name:
            update_payload["full_name"] = full_name

        supabase.table('users').update(update_payload).eq('id', session['user_id']).execute()

        # Keep session name in sync
        if full_name:
            session['name'] = full_name

        return redirect(url_for('dashboard.dashboard_intern', active_tab='profile'))

    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"Error updating intern profile: {error_detail}")
        return f"<h1>Profile Update Error</h1><pre>{error_detail}</pre><br><a href='/dashboard-intern?active_tab=profile'>Go back to Dashboard</a>", 500

