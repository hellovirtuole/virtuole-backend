import os
import json
import base64
import hashlib
import requests
from datetime import datetime
from api.config import supabase
from api.utils.email import send_system_email
from api.utils.notifications import send_notification

def get_phonepe_config():
    """
    Returns PhonePe credentials and dynamic API endpoints based on PHONEPE_ENV ('production' vs 'sandbox').
    """
    env = os.getenv("PHONEPE_ENV", "sandbox").strip().lower()
    merchant_id = os.getenv("PHONEPE_MERCHANT_ID", "PGTESTPAYUAT")
    salt_key = os.getenv("PHONEPE_SALT_KEY", "099eb0cd-02cf-4e2a-8aca-3e6c6aff0399")
    salt_index = str(os.getenv("PHONEPE_SALT_INDEX", "1")).strip()

    if env in ["production", "prod", "live"]:
        base_url = "https://api.phonepe.com/apis/hermes"
    else:
        base_url = "https://api-preprod.phonepe.com/apis/pg-sandbox"

    return {
        "env": env,
        "merchant_id": merchant_id,
        "salt_key": salt_key,
        "salt_index": salt_index,
        "base_url": base_url,
        "pay_url": f"{base_url}/pg/v1/pay",
        "status_url": lambda mid, tid: f"{base_url}/pg/v1/status/{mid}/{tid}"
    }

def create_phonepe_pay_order(merchant_txn_id, merchant_user_id, amount_in_paise, redirect_url, callback_url):
    """
    Constructs payload, calculates SHA256 checksum, and initiates PhonePe payment request.
    """
    cfg = get_phonepe_config()
    payload = {
        "merchantId": cfg["merchant_id"],
        "merchantTransactionId": merchant_txn_id,
        "merchantUserId": str(merchant_user_id or "VIRT-USER"),
        "amount": int(amount_in_paise),
        "redirectUrl": redirect_url,
        "redirectMode": "REDIRECT",
        "callbackUrl": callback_url,
        "paymentInstrument": {"type": "PAY_PAGE"}
    }

    base64_payload = base64.b64encode(json.dumps(payload).encode('utf-8')).decode('utf-8')
    checksum_str = base64_payload + "/pg/v1/pay" + cfg["salt_key"]
    checksum = hashlib.sha256(checksum_str.encode('utf-8')).hexdigest() + "###" + cfg["salt_index"]
    headers = {
        "Content-Type": "application/json",
        "X-VERIFY": checksum
    }

    try:
        resp = requests.post(cfg["pay_url"], json={"request": base64_payload}, headers=headers, timeout=15)
        resp_data = resp.json()
        if resp_data.get("success"):
            payment_url = resp_data['data']['instrumentResponse']['redirectInfo']['url']
            return True, payment_url, resp_data
        else:
            return False, resp_data.get("message", "PhonePe Gateway rejected transaction."), resp_data
    except Exception as e:
        return False, str(e), None

def verify_phonepe_webhook_checksum(raw_response_b64, received_checksum):
    """
    Validates PhonePe X-VERIFY signature to prevent unauthorized webhook spoofing.
    """
    if not received_checksum:
        return False
    cfg = get_phonepe_config()
    checksum_str = raw_response_b64 + cfg["salt_key"]
    expected_checksum = hashlib.sha256(checksum_str.encode('utf-8')).hexdigest() + "###" + cfg["salt_index"]
    return expected_checksum == received_checksum

def check_phonepe_status(merchant_txn_id):
    """
    Live Status Query: Calls PhonePe Check Status API (/pg/v1/status/{merchantId}/{merchantTransactionId})
    Protects against dropped webhooks or users closing the window.
    """
    cfg = get_phonepe_config()
    mid = cfg["merchant_id"]
    api_path = f"/pg/v1/status/{mid}/{merchant_txn_id}"
    url = cfg["status_url"](mid, merchant_txn_id)

    checksum_str = api_path + cfg["salt_key"]
    checksum = hashlib.sha256(checksum_str.encode('utf-8')).hexdigest() + "###" + cfg["salt_index"]
    headers = {
        "Content-Type": "application/json",
        "X-VERIFY": checksum,
        "X-MERCHANT-ID": mid
    }

    try:
        resp = requests.get(url, headers=headers, timeout=12)
        resp_data = resp.json()
        code = resp_data.get("code")
        is_success = (code == "PAYMENT_SUCCESS")
        return {
            "success": is_success,
            "code": code,
            "message": resp_data.get("message"),
            "data": resp_data.get("data"),
            "raw": resp_data
        }
    except Exception as e:
        return {
            "success": False,
            "code": "REQUEST_FAILED",
            "message": str(e),
            "data": None
        }

def fulfill_payment_success(merchant_txn_id):
    """
    Marks payment as 'paid', generates invoice, dispatches receipt email and notifications.
    Idempotent: will not duplicate invoice if already paid.
    """
    if not supabase:
        return False

    pay_query = supabase.table('payments').select('*').eq('transaction_id', merchant_txn_id).execute()
    if not pay_query.data:
        return False

    p = pay_query.data[0]
    if p.get('status') == 'paid':
        return True # Already fulfilled

    # Update to paid
    supabase.table('payments').update({"status": "paid"}).eq('transaction_id', merchant_txn_id).execute()

    user_id = p.get('user_id')
    amount = (p.get('amount') or 0) / 100.0
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
            <p style="color: #cbd5e1; font-size: 15px; margin: 0 0 20px 0;">Dear {full_name}, your transaction has been successfully confirmed by PhonePe.</p>
            
            <table style="width: 100%; border-collapse: collapse; margin-top: 15px; background: rgba(255,255,255,0.02); border-radius: 8px; overflow: hidden; border: 1px solid #334155;">
                <tr style="border-bottom: 1px solid #334155;">
                    <td style="padding: 12px 16px; color: #94a3b8; font-size: 14px;"><strong>Transaction ID:</strong></td>
                    <td style="padding: 12px 16px; text-align: right; color: #60a5fa; font-family: monospace; font-size: 14px;">{merchant_txn_id}</td>
                </tr>
                <tr style="border-bottom: 1px solid #334155;">
                    <td style="padding: 12px 16px; color: #94a3b8; font-size: 14px;"><strong>Amount Paid:</strong></td>
                    <td style="padding: 12px 16px; text-align: right; color: #34d399; font-weight: bold; font-size: 16px;">INR {amount:.2f}</td>
                </tr>
                <tr>
                    <td style="padding: 12px 16px; color: #94a3b8; font-size: 14px;"><strong>Payment Gateway:</strong></td>
                    <td style="padding: 12px 16px; text-align: right; color: #e2e8f0; font-size: 14px;">PhonePe Unified Checkout</td>
                </tr>
            </table>

            <div style="text-align: center; margin-top: 30px;">
                <a href="https://www.virtuole.in/dashboard-intern" style="background: linear-gradient(135deg, #10b981, #059669); color: white; padding: 12px 28px; border-radius: 50px; text-decoration: none; font-weight: 700; font-size: 14px; display: inline-block;">Access Intern Workspace &rarr;</a>
            </div>

            <div style="margin-top: 36px; border-top: 1px solid #334155; padding-top: 18px; font-size: 12px; color: #64748b; text-align: center;">
                Virtuole Education Technologies &bull; Govt of India Registered MSME<br>
                Official Support: contact@virtuole.in &bull; Begusarai, Bihar
            </div>
        </div>
        """
        try:
            send_system_email(email, f"Payment Receipt: {merchant_txn_id} - Virtuole", invoice_html, is_html=True)
        except Exception as e:
            print(f"Error sending invoice email for {merchant_txn_id}: {e}")

        try:
            send_notification('intern', user_id, 'payment_success', 'Payment Successful!', f"Your payment of INR {amount:.2f} (Txn: {merchant_txn_id}) was successfully processed.")
        except Exception as e:
            print(f"Error sending payment notification for {merchant_txn_id}: {e}")

    return True
