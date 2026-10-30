import os
import hmac
import hashlib
import requests
from datetime import datetime
from api.config import supabase
from api.utils.email import send_system_email
from api.utils.notifications import send_notification

def get_razorpay_config():
    """
    Returns Razorpay credentials and configuration from environment variables.
    """
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip()
    env = os.getenv("RAZORPAY_ENV", "test").strip().lower()

    return {
        "key_id": key_id,
        "key_secret": key_secret,
        "webhook_secret": webhook_secret,
        "env": env,
        "base_url": "https://api.razorpay.com/v1"
    }

def create_razorpay_order(merchant_txn_id, amount_in_paise, user_name="Student Intern", user_email="", notes=None):
    """
    Creates an official Razorpay Order via Razorpay Orders API (/v1/orders).
    Amount must be an integer in paise (e.g. INR 499 = 49900 paise).
    """
    cfg = get_razorpay_config()
    if not cfg["key_id"] or not cfg["key_secret"]:
        return False, "Razorpay API Keys (RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET) are not configured.", None

    order_payload = {
        "amount": int(amount_in_paise),
        "currency": "INR",
        "receipt": str(merchant_txn_id)[:40],
        "notes": {
            "transaction_id": str(merchant_txn_id),
            "user_name": str(user_name)[:40],
            "user_email": str(user_email)[:40],
            **(notes or {})
        }
    }

    try:
        url = f"{cfg['base_url']}/orders"
        resp = requests.post(
            url,
            auth=(cfg["key_id"], cfg["key_secret"]),
            json=order_payload,
            timeout=15
        )
        resp_data = resp.json()

        if resp.status_code in [200, 201] and resp_data.get("id"):
            return True, resp_data.get("id"), resp_data
        else:
            err_msg = resp_data.get("error", {}).get("description") or resp_data.get("message") or f"Razorpay HTTP {resp.status_code}"
            return False, err_msg, resp_data

    except Exception as e:
        return False, str(e), None

def verify_razorpay_payment_signature(razorpay_order_id, razorpay_payment_id, razorpay_signature):
    """
    Verifies the HMAC SHA256 payment signature returned by Razorpay Checkout.
    Signature = HMAC_SHA256(order_id + '|' + payment_id, key_secret)
    """
    cfg = get_razorpay_config()
    secret = cfg["key_secret"]
    if not secret:
        print("[RAZORPAY SECURITY ERROR] Cannot verify signature: RAZORPAY_KEY_SECRET is missing.")
        return False

    try:
        message = f"{razorpay_order_id}|{razorpay_payment_id}".encode('utf-8')
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            message,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected_signature, razorpay_signature)
    except Exception as e:
        print(f"[RAZORPAY ERROR] Signature verification failed with exception: {e}")
        return False

def verify_razorpay_webhook_signature(raw_body_bytes, received_signature):
    """
    Verifies Razorpay Webhook signature against RAZORPAY_WEBHOOK_SECRET.
    """
    cfg = get_razorpay_config()
    secret = cfg["webhook_secret"] or cfg["key_secret"]
    if not secret or not received_signature:
        return False

    try:
        expected = hmac.new(
            secret.encode('utf-8'),
            raw_body_bytes,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, received_signature)
    except Exception as e:
        print(f"[RAZORPAY WEBHOOK ERROR] Verification error: {e}")
        return False

def fetch_razorpay_payment(payment_id):
    """
    Fetches live payment status from Razorpay: GET /v1/payments/{payment_id}
    """
    cfg = get_razorpay_config()
    if not cfg["key_id"] or not cfg["key_secret"]:
        return {"success": False, "error": "Keys not configured"}

    try:
        url = f"{cfg['base_url']}/payments/{payment_id}"
        resp = requests.get(url, auth=(cfg["key_id"], cfg["key_secret"]), timeout=12)
        data = resp.json()
        if resp.status_code == 200:
            status = data.get("status")
            return {
                "success": status in ["captured", "authorized"],
                "status": status,
                "data": data
            }
        return {"success": False, "status": "FAILED", "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}

def fetch_razorpay_payment_by_txn_id(merchant_txn_id):
    """
    Finds a payment in Razorpay by searching recent payments for notes.transaction_id.
    """
    cfg = get_razorpay_config()
    if not cfg["key_id"] or not cfg["key_secret"]:
        return {"success": False, "error": "Keys not configured"}

    try:
        url = f"{cfg['base_url']}/payments?count=50"
        resp = requests.get(url, auth=(cfg["key_id"], cfg["key_secret"]), timeout=15)
        if resp.status_code == 200:
            items = resp.json().get('items', [])
            for item in items:
                notes = item.get('notes') or {}
                if notes.get('transaction_id') == str(merchant_txn_id) or str(merchant_txn_id) in str(item):
                    status = item.get('status')
                    return {
                        "success": status in ["captured", "authorized"],
                        "status": status,
                        "payment_id": item.get('id'),
                        "notes": notes,
                        "data": item
                    }
        return {"success": False, "error": f"Transaction {merchant_txn_id} not found in recent Razorpay payments"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def fulfill_payment_success(merchant_txn_id, payment_id=None, method="Razorpay Checkout", extra_data=None):
    """
    MASTER IDEMPOTENT FULFILLMENT:
    Guarantees that ANY confirmed Razorpay transaction:
    1. Idempotently marks payment as 'paid' in payments table.
    2. Identifies the enrollment_id & real student owner.
    3. Officializes the project in submissions table.
    4. Sets enrollments.status = 'submitted'.
    5. Dispatches notifications & official invoice email.
    """
    if not supabase:
        return False

    pay_query = supabase.table('payments').select('*').eq('transaction_id', merchant_txn_id).execute()
    if not pay_query.data and payment_id:
        pay_query = supabase.table('payments').select('*').eq('transaction_id', payment_id).execute()

    if not pay_query.data:
        # Create payment record if it doesn't exist yet
        try:
            ins = supabase.table('payments').insert({
                "transaction_id": merchant_txn_id,
                "amount": 0,
                "status": "paid",
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            p = ins.data[0] if ins.data else {"id": None, "user_id": None, "amount": 0}
        except Exception:
            return False
    else:
        p = pay_query.data[0]

    already_paid = (p.get('status') == 'paid')

    # Update payment to paid if not already
    if not already_paid:
        update_data = {
            "status": "paid"
        }
        supabase.table('payments').update(update_data).eq('id', p['id']).execute()

    user_id = p.get('user_id')
    amount = (p.get('amount') or 0) / 100.0

    # 1. Resolve enrollment_id, code_link, and defense_link from all possible sources
    extra = extra_data or {}
    enrollment_id = extra.get('enrollment_id')
    code_link = extra.get('code_link')
    defense_link = extra.get('defense_link') or ''

    # 2. Check live Razorpay notes if missing details
    rzp_info = None
    if not enrollment_id or not code_link:
        if payment_id:
            rzp_info = fetch_razorpay_payment(payment_id)
        if not (rzp_info and rzp_info.get("success")):
            rzp_info = fetch_razorpay_payment_by_txn_id(merchant_txn_id)
        if rzp_info and rzp_info.get("success"):
            notes = rzp_info.get("notes") or {}
            enrollment_id = enrollment_id or notes.get('enrollment_id')
            code_link = code_link or notes.get('code_link')
            defense_link = defense_link or notes.get('defense_link') or ''
            if not user_id:
                user_id = notes.get('user_id')

    # 3. Check Flask session cache if available
    try:
        from flask import session
        cached = session.get(f'pending_sub_{merchant_txn_id}') or {}
        enrollment_id = enrollment_id or cached.get('enrollment_id')
        code_link = code_link or cached.get('code_link')
        defense_link = defense_link or cached.get('defense_link') or ''
        if not user_id:
            user_id = session.get('user_id')
    except Exception:
        pass

    # 4. Fallback lookup if enrollment_id still not found
    if not enrollment_id and user_id:
        try:
            user_enrolls = supabase.table('enrollments').select('enrollment_id').eq('user_id', user_id).in_('status', ['active', 'resubmit', 'submitted']).order('created_at', desc=True).limit(1).execute().data
            if user_enrolls:
                enrollment_id = user_enrolls[0].get('enrollment_id')
        except Exception:
            pass

    if not code_link:
        code_link = 'https://github.com/submission'

    # 5. NOW AND FOREVER: Fulfill submission and enrollment status
    if enrollment_id:
        try:
            # Resolve actual student user_id from enrollment
            enroll_row = supabase.table('enrollments').select('user_id').eq('enrollment_id', enrollment_id).execute().data
            student_uid = enroll_row[0].get('user_id') if enroll_row else user_id
            
            if student_uid and p.get('id'):
                supabase.table('payments').update({"user_id": student_uid}).eq('id', p['id']).execute()
                user_id = student_uid

            # Insert or update submission
            exist_sub = supabase.table('submissions').select('id').eq('enrollment_id', enrollment_id).execute().data
            if exist_sub:
                supabase.table('submissions').update({
                    "code_link": code_link,
                    "defense_link": defense_link
                }).eq('id', exist_sub[0]['id']).execute()
            else:
                supabase.table('submissions').insert({
                    "enrollment_id": enrollment_id,
                    "code_link": code_link,
                    "defense_link": defense_link
                }).execute()

            # Mark enrollment status as submitted
            supabase.table('enrollments').update({"status": "submitted"}).eq('enrollment_id', enrollment_id).execute()

            # Dispatch student and mentor notifications
            if student_uid:
                try:
                    send_notification('intern', student_uid, 'submission', 'Project Submitted', f'Your architecture for {enrollment_id} has entered evaluation.')
                except Exception:
                    pass
            try:
                send_notification('mentor', None, 'new_submission', 'New Project Submission', f'A new project for {enrollment_id} has been submitted for evaluation.')
            except Exception:
                pass

            # Clean session cache
            try:
                from flask import session
                session.pop(f'pending_sub_{merchant_txn_id}', None)
                session.modified = True
            except Exception:
                pass
        except Exception as sub_err:
            print(f"[FULFILL ERROR] Error saving submission for {enrollment_id}: {sub_err}")

    # 6. Send invoice receipt email if not already sent
    if not already_paid and user_id:
        try:
            u_query = supabase.table('users').select('email, full_name').eq('id', user_id).execute()
            if u_query.data:
                user = u_query.data[0]
                email = user.get('email')
                full_name = user.get('full_name', 'Student Intern')

                invoice_html = f"""
                <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #0f172a; color: #f8fafc; border-radius: 14px; padding: 32px; border: 1px solid #334155;">
                    <div style="text-align: center; margin-bottom: 24px;">
                        <img src="https://www.virtuole.in/static/logo.png" alt="Virtuole" style="height: 40px;">
                    </div>
                    <div style="background: rgba(16, 185, 129, 0.12); border-left: 4px solid #10b981; padding: 12px 18px; border-radius: 6px; margin-bottom: 22px;">
                        <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 1.2px; color: #34d399; font-weight: 800;">Official Payment Receipt</span>
                    </div>
                    <h2 style="color: #ffffff; margin: 0 0 10px 0;">Payment Confirmation</h2>
                    <p style="color: #cbd5e1; font-size: 15px; margin: 0 0 20px 0;">Dear {full_name}, your transaction has been successfully confirmed via Razorpay.</p>
                    
                    <table style="width: 100%; border-collapse: collapse; margin-top: 15px; background: rgba(255,255,255,0.02); border-radius: 8px; overflow: hidden; border: 1px solid #334155;">
                        <tr style="border-bottom: 1px solid #334155;">
                            <td style="padding: 12px 16px; color: #94a3b8; font-size: 14px;"><strong>Transaction ID:</strong></td>
                            <td style="padding: 12px 16px; text-align: right; color: #60a5fa; font-family: monospace; font-size: 14px;">{merchant_txn_id}</td>
                        </tr>
                        {f'<tr style="border-bottom: 1px solid #334155;"><td style="padding: 12px 16px; color: #94a3b8; font-size: 14px;"><strong>Payment Reference:</strong></td><td style="padding: 12px 16px; text-align: right; color: #93c5fd; font-family: monospace; font-size: 13px;">{payment_id}</td></tr>' if payment_id else ''}
                        <tr style="border-bottom: 1px solid #334155;">
                            <td style="padding: 12px 16px; color: #94a3b8; font-size: 14px;"><strong>Amount Paid:</strong></td>
                            <td style="padding: 12px 16px; text-align: right; color: #34d399; font-weight: bold; font-size: 16px;">INR {amount:.2f}</td>
                        </tr>
                        <tr>
                            <td style="padding: 12px 16px; color: #94a3b8; font-size: 14px;"><strong>Payment Gateway:</strong></td>
                            <td style="padding: 12px 16px; text-align: right; color: #e2e8f0; font-size: 14px;">Razorpay Secure Checkout</td>
                        </tr>
                    </table>

                    <div style="text-align: center; margin-top: 30px;">
                        <a href="https://www.virtuole.in/dashboard-intern" style="background: linear-gradient(135deg, #10b981, #059669); color: white; padding: 12px 28px; border-radius: 50px; text-decoration: none; font-weight: 700; font-size: 14px; display: inline-block;">Access Intern Workspace &rarr;</a>
                    </div>

                    <div style="margin-top: 36px; border-top: 1px solid #334155; padding-top: 18px; font-size: 12px; color: #64748b; text-align: center;">
                        Virtuole Education Technologies &bull; Govt of India Registered MSME (UDYAM-BR-06-0064801)<br>
                        Official Support: support@virtuole.in &bull; Patna, Bihar
                    </div>
                </div>
                """
                send_system_email(email, f"Payment Receipt: {merchant_txn_id} - Virtuole", invoice_html, is_html=True)
                send_notification('intern', user_id, 'payment_success', 'Payment Successful!', f"Your payment of INR {amount:.2f} (Txn: {merchant_txn_id}) was successfully processed via Razorpay.")
        except Exception as e:
            print(f"Error sending email/notification for {merchant_txn_id}: {e}")

    return True
