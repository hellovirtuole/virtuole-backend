
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from api.config import supabase, limiter
from api.utils.email import send_system_email, send_ambassador_email
import random, string, uuid, json, os, base64, hashlib, requests
from datetime import datetime, timedelta
from api.utils.notifications import send_notification
from api.utils.batch import parse_track_duration, calculate_next_start_date
from api.utils.phonepe import (
    create_phonepe_pay_order, 
    verify_phonepe_webhook_checksum, 
    check_phonepe_status, 
    fulfill_payment_success
)

intern_bp = Blueprint('intern', __name__)



@intern_bp.route('/validate-promo', methods=['POST'])
@intern_bp.route('/api/validate-promo', methods=['POST'])
def validate_promo():
    data = request.get_json()
    promo_code = data.get('promo_code', '').upper()
    user_data = supabase.table('users').select('id, role, total_points, ambassador_expiry, coupon_usage_limit, coupon_user_limit, coupon_allowed_level').eq('promo_code', promo_code).execute().data
    
    if not user_data:
        return jsonify({"valid": False, "error": "Invalid or expired code."}), 400
        
    c_data = user_data[0]
    user_role = str(c_data.get('role', '')).lower()
    
    if 'ambassador' in user_role:
        return jsonify({"valid": True, "discount_percent": 10})
    elif 'coupon' in user_role:
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
        user_data = supabase.table('users').select('id, role, total_points, ambassador_expiry').eq('promo_code', promo_code).execute().data
        
        if user_data:
            c_data = user_data[0]
            user_role = str(c_data.get('role', '')).lower()
            
            if 'ambassador' in user_role:
                final_price = int(base_price * 0.9)
                applied_promo = promo_code
            elif 'coupon' in user_role:
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
        
        invoice_html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #2b3481;">Payment Receipt</h2>
            <p>Dear {session.get('name', 'Intern')},</p>
            <p>Your payment for the internship program has been successfully processed.</p>
            <table style="width: 100%; border-collapse: collapse; margin-top: 20px;">
                <tr style="border-bottom: 1px solid #ddd;">
                    <td style="padding: 10px 0;"><strong>Transaction ID:</strong></td>
                    <td style="padding: 10px 0; text-align: right;">{transaction_id}</td>
                </tr>
                <tr style="border-bottom: 1px solid #ddd;">
                    <td style="padding: 10px 0;"><strong>Amount Paid:</strong></td>
                    <td style="padding: 10px 0; text-align: right;">INR 0.00 (100% Discount)</td>
                </tr>
            </table>
            <p style="margin-top: 20px;">Thank you for choosing Virtuole. We are excited to have you on board!</p>
        </div>
        """
        send_system_email(session['email'], "Payment Invoice - Virtuole", invoice_html, is_html=True)
        
        if is_ajax:
            return jsonify({"payment_url": "/dashboard-intern"})
        return redirect("/dashboard-intern")
    
    # Secure Redirect URL with txn_id for auto-reconciliation on return
    redirect_url = f"https://www.virtuole.in/dashboard-intern?txn_id={transaction_id}"
    callback_url = "https://www.virtuole.in/api/phonepe-webhook"

    success, payment_url_or_err, _ = create_phonepe_pay_order(
        merchant_txn_id=transaction_id,
        merchant_user_id=safe_merchant_user_id,
        amount_in_paise=amount_in_paise,
        redirect_url=redirect_url,
        callback_url=callback_url
    )

    if success:
        # Save submission and pending payment record
        supabase.table('submissions').insert({
            "enrollment_id": enrollment_id, 
            "code_link": data.get('code_link'), 
            "defense_link": data.get('defense_link')
        }).execute()
        supabase.table('payments').insert({
            "user_id": session['user_id'], 
            "transaction_id": transaction_id, 
            "amount": amount_in_paise, 
            "status": "pending", 
            "applied_promo": applied_promo
        }).execute()

        if is_ajax:
            return jsonify({"payment_url": payment_url_or_err})
        else:
            return redirect(payment_url_or_err)

    if is_ajax:
        return jsonify({"error": payment_url_or_err or "PhonePe Gateway Error"}), 400
    else:
        return f"Gateway Error encountered: {payment_url_or_err}", 400


@intern_bp.route('/phonepe-webhook', methods=['POST'])
@intern_bp.route('/api/phonepe-webhook', methods=['POST'])
def phonepe_webhook():
    payload_json = request.get_json(silent=True) or {}
    raw_response_b64 = payload_json.get('response')
    received_checksum = request.headers.get('X-VERIFY', '')

    if not raw_response_b64:
        return jsonify({"error": "Missing response payload"}), 400

    # Strict signature verification to prevent spoofing
    if not verify_phonepe_webhook_checksum(raw_response_b64, received_checksum):
        print(f"[SECURITY ALERT] Invalid PhonePe webhook signature from {request.remote_addr}. Checksum mismatch.")
        return jsonify({"error": "Invalid signature"}), 401

    try:
        decoded_response = json.loads(base64.b64decode(raw_response_b64).decode('utf-8'))
        code = decoded_response.get('code')
        transaction_id = decoded_response.get('data', {}).get('merchantTransactionId')

        if code == 'PAYMENT_SUCCESS' and transaction_id:
            fulfill_payment_success(transaction_id)
            return jsonify({"status": "received", "result": "PAYMENT_SUCCESS"}), 200
        elif transaction_id:
            # Update to failed if declined
            supabase.table('payments').update({
                "status": "failed", 
                "updated_at": datetime.utcnow().isoformat()
            }).eq('transaction_id', transaction_id).execute()
            return jsonify({"status": "received", "result": code}), 200

    except Exception as e:
        print(f"Error parsing PhonePe webhook: {e}")
        return jsonify({"error": "Processing error"}), 500

    return jsonify({"status": "received"}), 200


@intern_bp.route('/api/verify-payment/<transaction_id>', methods=['GET'])
def verify_payment_status_endpoint(transaction_id):
    """
    On-demand status verification endpoint: Queries PhonePe Check Status API live
    and fulfills payment if confirmed.
    """
    if not session.get('user_id'):
        return jsonify({"error": "Unauthorized"}), 401

    status_res = check_phonepe_status(transaction_id)
    if status_res.get("success"):
        fulfill_payment_success(transaction_id)
        return jsonify({"status": "paid", "message": "Transaction verified and completed successfully!"})
    
    return jsonify({
        "status": status_res.get("code", "PENDING"),
        "message": status_res.get("message", "Payment is still processing.")
    })





@intern_bp.route('/enroll', methods=['GET', 'POST'])
@intern_bp.route('/api/enroll', methods=['GET', 'POST'])
def api_enroll():
    if request.method == 'GET':
        return redirect(url_for('dashboard.dashboard_intern'))

    user_role = str(session.get('role', '')).lower()
    if user_role not in ['intern', 'intern + ambassador']: 
        return redirect('/login')

    user_id = session.get('user_id')
    if not user_id:
        return redirect('/login')

    try:
        program_id = request.form.get('program_id')
        track_level = request.form.get('track_level')
        college_name = (request.form.get('college_name') or '').strip()
        course_name = (request.form.get('course_name') or '').strip()
        session_year = (request.form.get('session_year') or '').strip()

        if not program_id:
            print("api_enroll: missing program_id")
            return redirect(url_for('dashboard.dashboard_intern'))

        if not track_level:
            track_level = "1"

        if track_level == 'custom':
            custom_months = request.form.get('custom_months', 1)
            track_level = f"custom_{custom_months}"

        enrollment_id = f"VT-E-{random.randint(100000, 999999)}"

        clean_prog_id = int(program_id) if str(program_id).isdigit() else program_id

        now = datetime.utcnow()
        duration_days, track_display = parse_track_duration(track_level)
        start_dt = now
        end_dt = start_dt + timedelta(days=duration_days)
        start_date_str = start_dt.strftime("%B %d, %Y")
        end_date_str = end_dt.strftime("%B %d, %Y")
        issue_date_str = now.strftime("%B %d, %Y")

        # Fetch program details first for offer letter & notification
        prog = None
        try:
            p_res = supabase.table('programs').select('*').eq('id', clean_prog_id).execute()
            if p_res and p_res.data:
                prog = p_res.data[0]
            else:
                p_res = supabase.table('programs').select('*').eq('id', str(program_id)).execute()
                if p_res and p_res.data:
                    prog = p_res.data[0]
        except Exception as p_err:
            print(f"api_enroll: program query warning: {p_err}")

        if not prog:
            prog = {"title": "Virtual Internship Program", "short_description": "Virtual Internship Mandate"}

        next_batch_dt = calculate_next_start_date(now)
        start_dt = next_batch_dt
        start_date_str = start_dt.strftime("%B %d, %Y")

        # Check if already enrolled or requested for this program
        existing = []
        try:
            ex_res = supabase.table('enrollments').select('id, enrollment_id, status, track_level').eq('user_id', user_id).eq('program_id', clean_prog_id).execute()
            existing = ex_res.data if ex_res and ex_res.data else []
        except Exception:
            existing = []

        if not existing:
            try:
                ex_res = supabase.table('enrollments').select('id, enrollment_id, status, track_level').eq('user_id', user_id).eq('program_id', str(program_id)).execute()
                existing = ex_res.data if ex_res and ex_res.data else []
            except Exception:
                existing = []

        has_pending = any(ex.get('status') == 'pending' for ex in existing)
        if has_pending:
            return redirect(url_for('dashboard.dashboard_intern', active_tab='workspace'))

        re_applied = False
        if existing:
            # If user has an existing record that is active/resubmit but not yet submitted for grading,
            # allow them to re-request mentor review so it moves to pending status
            for ex in existing:
                if ex.get('status') in ['active', 'resubmit']:
                    has_submission = False
                    try:
                        sub_res = supabase.table('submissions').select('id').eq('enrollment_id', ex['enrollment_id']).execute()
                        has_submission = bool(sub_res and sub_res.data)
                    except Exception:
                        has_submission = False

                    if not has_submission:
                        target_eid = ex.get('enrollment_id')
                        enrollment_id = target_eid or enrollment_id
                        try:
                            supabase.table('enrollments').update({
                                'status': 'pending',
                                'track_level': track_level
                            }).eq('enrollment_id', target_eid).execute()
                            re_applied = True
                        except Exception as up_err:
                            print(f"api_enroll: error updating by enrollment_id: {up_err}")
                            if ex.get('id'):
                                try:
                                    supabase.table('enrollments').update({
                                        'status': 'pending',
                                        'track_level': track_level
                                    }).eq('id', ex['id']).execute()
                                    re_applied = True
                                except Exception as up_err2:
                                    print(f"api_enroll: error updating by id: {up_err2}")

                        try:
                            supabase.table('enrollments').update({
                                'start_date': start_dt.isoformat()
                            }).eq('enrollment_id', enrollment_id).execute()
                        except Exception:
                            pass

            if not re_applied and any(ex.get('status') in ['submitted', 'graded', 'certified', 'completed'] for ex in existing):
                return redirect(url_for('dashboard.dashboard_intern', active_tab='workspace'))

        if not existing or (not re_applied and not any(ex.get('status') == 'pending' for ex in existing)):
            # Prepare base payload guaranteed to match standard enrollments table schema (no start_date in base)
            base_payload = {
                "enrollment_id": enrollment_id,
                "user_id": user_id,
                "program_id": clean_prog_id,
                "track_level": track_level,
                "status": "pending"
            }

            full_payload = dict(base_payload)
            if college_name: full_payload["college_name"] = college_name
            if course_name: full_payload["course_name"] = course_name
            if session_year: full_payload["session_year"] = session_year

            # Try inserting full payload; if schema columns don't exist in Supabase, fallback cleanly
            try:
                supabase.table('enrollments').insert(full_payload).execute()
            except Exception as full_err:
                print(f"api_enroll: insert full_payload failed ({full_err}), falling back to base_payload...")
                try:
                    supabase.table('enrollments').insert(base_payload).execute()
                except Exception as base_err:
                    print(f"api_enroll: insert base_payload failed with int id ({base_err}), trying string id...")
                    try:
                        alt_payload = dict(base_payload)
                        alt_payload["program_id"] = str(program_id)
                        supabase.table('enrollments').insert(alt_payload).execute()
                    except Exception as alt_err:
                        print(f"api_enroll: insert alt_payload failed: {alt_err}")
                        raise alt_err

            # Safely attempt to set start_date if column exists in the table
            try:
                supabase.table('enrollments').update({'start_date': start_dt.isoformat()}).eq('enrollment_id', enrollment_id).execute()
            except Exception:
                pass

        # Sync academic details to users.profile_details
        if college_name or course_name or session_year:
            try:
                u_res = supabase.table('users').select('profile_details').eq('id', user_id).execute()
                if u_res and u_res.data:
                    curr_pd = u_res.data[0].get('profile_details') or {}
                    if isinstance(curr_pd, str):
                        try: curr_pd = json.loads(curr_pd)
                        except: curr_pd = {}
                    updated = False
                    if college_name and not curr_pd.get('college_name'):
                        curr_pd['college_name'] = college_name; updated = True
                    if course_name and not curr_pd.get('course_name'):
                        curr_pd['course_name'] = course_name; updated = True
                    if session_year and not curr_pd.get('session_year'):
                        curr_pd['session_year'] = session_year; updated = True
                    if updated:
                        supabase.table('users').update({'profile_details': curr_pd}).eq('id', user_id).execute()
            except Exception as prof_err:
                print(f"api_enroll: profile details sync warning: {prof_err}")

        # Send in-app notification to intern and mentors
        try:
            send_notification('intern', user_id, 'enrollment_request', 'Enrollment Request Submitted', f'Your application for {prog["title"]} ({track_display}) has been sent for mentor approval.')
            send_notification('mentor', None, 'new_enrollment_request', 'New Enrollment Request', f'{session.get("name", "An intern")} requested enrollment in {prog["title"]} (ID: {enrollment_id}).')
        except Exception as notif_err:
            print(f"api_enroll: notification warning: {notif_err}")

        # Send confirmation email to applicant that request is under review
        try:
            next_batch = calculate_next_start_date(datetime.utcnow()).strftime("%B %d, %Y")
            req_email_html = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #1e293b;">
                <h2 style="color: #2563eb;">Enrollment Request Received</h2>
                <p>Dear {session.get('name', 'Intern')},</p>
                <p>Thank you for applying to the <strong>{prog['title']}</strong> program ({track_display}) at Virtuole.</p>
                <div style="background: #f1f5f9; padding: 15px; border-radius: 8px; margin: 20px 0;">
                    <p style="margin: 0 0 8px;"><strong>Enrollment Tracking ID:</strong> {enrollment_id}</p>
                    <p style="margin: 0 0 8px;"><strong>Status:</strong> Under Mentor Review</p>
                    <p style="margin: 0;"><strong>Projected Batch Start:</strong> {next_batch}</p>
                </div>
                <p>Our mentorship team is currently reviewing your application. As soon as a mentor accepts your request, your official Internship Offer Letter will be generated with your confirmed start date and emailed to you directly.</p>
                <p style="margin-top: 30px; font-size: 13px; color: #64748b;">Virtuole Engineering Platform | support@virtuole.in</p>
            </div>
            """
            if session.get('email'):
                send_system_email(session['email'], f"Enrollment Request Under Review - {prog['title']}", req_email_html, is_html=True)
        except Exception as email_err:
            print(f"api_enroll: email warning: {email_err}")

        return redirect(url_for('dashboard.dashboard_intern', active_tab='workspace'))

    except Exception as fatal_e:
        import traceback
        traceback.print_exc()
        print(f"api_enroll fatal error caught: {fatal_e}")
        return redirect(url_for('dashboard.dashboard_intern', active_tab='workspace'))


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
        track = e.get('track_level', '').lower()
        if track.startswith('custom_'):
            try: months = int(track.split('_')[1])
            except: months = 1
            duration_days = months * 30
        elif track.isdigit():
            months = int(track)
            duration_days = months * 30
        else:
            duration_days = 90 if track == 'expert' else (60 if track == 'intermediate' else 30)
        
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
    send_notification('intern', session['user_id'], 'submission', 'Project Submitted', f'Your project for {enrollment_id} has entered evaluation.')
    send_notification('mentor', None, 'new_submission', 'New Project Submission', f'A new project for {enrollment_id} has been submitted for evaluation.')
    send_system_email(session['email'], "Submission Received", f"Your architecture for {enrollment_id} has entered evaluation.")
    return redirect(url_for('dashboard.dashboard_intern'))


def parse_shipping_address(addr_str):
    if not addr_str: return {}
    if isinstance(addr_str, dict): return addr_str
    try:
        return json.loads(addr_str)
    except Exception:
        return {"name": "", "addr1": addr_str, "addr2": "", "city": "", "state": "", "pin": "", "phone": ""}


@intern_bp.route('/update-profile-intern', methods=['GET', 'POST'])
@intern_bp.route('/api/update-profile-intern', methods=['GET', 'POST'])
def update_profile_intern():
    if request.method == 'GET':
        return redirect(url_for('dashboard.dashboard_intern', active_tab='profile'))

    role_check = str(session.get('role', '')).lower()
    if role_check not in ['intern', 'intern + ambassador']:
        return redirect('/login')

    try:
        full_name = request.form.get('full_name', '').strip()
        profile_data = {
            "gender": request.form.get('gender', '').strip(),
            "phone": request.form.get('phone', '').strip(),
            "city": request.form.get('city', '').strip(),
            "state": request.form.get('state', '').strip(),
            "college_name": request.form.get('college_name', '').strip(),
            "course_name": request.form.get('course_name', '').strip(),
            "session_year": request.form.get('session_year', '').strip(),
        }

        update_payload = {
            "profile_details": profile_data,
            "shipping_address": json.dumps(profile_data),
        }
        if full_name:
            update_payload["full_name"] = full_name

        supabase.table('users').update(update_payload).eq('id', session['user_id']).execute()

        if full_name:
            session['name'] = full_name

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        import traceback
        return jsonify({"status": "error", "message": str(e)}), 500



