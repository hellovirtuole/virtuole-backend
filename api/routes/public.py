
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from api.config import supabase, limiter
from api.utils.email import send_system_email, send_ambassador_email
import random, string, uuid, json
from datetime import datetime, timedelta

public_bp = Blueprint('public', __name__)



@public_bp.route('/validate-promo', methods=['POST'])
@public_bp.route('/api/validate-promo', methods=['POST'])
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

@public_bp.route('/create-payment', methods=['POST'])
@public_bp.route('/api/create-payment', methods=['POST'])
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

@public_bp.route('/phonepe-webhook', methods=['POST'])
@public_bp.route('/api/phonepe-webhook', methods=['POST'])
def phonepe_webhook():
    decoded_response = json.loads(base64.b64decode(request.json.get('response')).decode('utf-8'))
    if decoded_response['code'] == 'PAYMENT_SUCCESS':
        transaction_id = decoded_response['data']['merchantTransactionId']
        supabase.table('payments').update({"status": "paid"}).eq('transaction_id', transaction_id).execute()
    return jsonify({"status": "received"}), 200

@public_bp.route('/credential/<enroll_id>')
def view_credential(enroll_id):
    try:
        response = supabase.table('enrollments').select('*, users(full_name), programs(title)').eq('enrollment_id', enroll_id).execute()
        if not response.data:
            return "Credential not found.", 404
            
        enroll_data = response.data[0]
        if enroll_data.get('status') not in ['certified', 'completed'] and not enroll_data.get('final_score'):
            return "Credential not yet certified.", 403
            
        submission = supabase.table('submissions').select('code_link').eq('enrollment_id', enroll_id).execute()
        repo_link = submission.data[0]['code_link'] if submission.data else None
        
        credential = {
            'id': enroll_data['enrollment_id'],
            'intern_name': enroll_data['users']['full_name'],
            'program_title': enroll_data['programs']['title'],
            'track_level': enroll_data['track_level'],
            'score': enroll_data.get('final_score', '100'),
            'updated_at': enroll_data.get('updated_at', datetime.utcnow().isoformat()),
            'repo_link': repo_link
        }
        return render_template('credential.html', credential=credential)
    except Exception as e:
        return f"Error loading credential: {str(e)}", 500

@public_bp.route('/credential/user/<public_id>')
def view_credential_by_user(public_id):
    try:
        if public_id == 'test_preview':
            credential = {
                'id': 'VT-E-SAMPLE123',
                'intern_name': 'Test Intern Profile',
                'program_title': 'Advanced Software Engineering',
                'track_level': 'elite',
                'score': '100',
                'updated_at': datetime.utcnow().isoformat(),
                'repo_link': 'https://github.com/virtuole/sample-repo'
            }
            return render_template('credential.html', credential=credential)
            
        user_res = supabase.table('users').select('id, full_name').eq('public_id', public_id).execute()
        if not user_res.data:
            return "User not found.", 404
        
        user_id = user_res.data[0]['id']
        
        response = supabase.table('enrollments').select('*, programs(title)').eq('user_id', user_id).in_('status', ['certified', 'completed']).order('updated_at', desc=True).limit(1).execute()
        
        if not response.data:
            return "No certified credentials found for this user.", 404
            
        enroll_data = response.data[0]
        enroll_id = enroll_data['enrollment_id']
            
        submission = supabase.table('submissions').select('code_link').eq('enrollment_id', enroll_id).execute()
        repo_link = submission.data[0]['code_link'] if submission.data else None
        
        credential = {
            'id': enroll_data['enrollment_id'],
            'intern_name': user_res.data[0]['full_name'],
            'program_title': enroll_data['programs']['title'],
            'track_level': enroll_data['track_level'],
            'score': enroll_data.get('final_score', '100'),
            'updated_at': enroll_data.get('updated_at', datetime.utcnow().isoformat()),
            'repo_link': repo_link
        }
        return render_template('credential.html', credential=credential)
    except Exception as e:
        return f"Error loading credential: {str(e)}", 500
