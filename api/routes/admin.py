
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from api.config import supabase, limiter
from api.utils.email import send_system_email, send_ambassador_email
import random, string, uuid, json, re
from datetime import datetime, timedelta

admin_bp = Blueprint('admin', __name__)



def fix_gdrive_url(url):
    if not url: return url
    url_str = str(url).strip()
    match = re.search(r'/(?:file/)?d/([a-zA-Z0-9_-]+)', url_str)
    if not match: match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url_str)
    if match:
        file_id = match.group(1)
        return f"https://drive.google.com/thumbnail?id={file_id}&sz=w1000"
    return url_str

def is_admin_session():
    role = str(session.get('role', '')).lower()
    email = str(session.get('email', '')).lower()
    if email == 'admin@virtuole.in' or role == 'admin':
        if role != 'admin':
            session['role'] = 'admin'
        session.permanent = True
        session.modified = True
        return True

    # Database fallback if user_id in session
    u_id = session.get('user_id')
    if u_id and supabase:
        try:
            u_check = supabase.table('users').select('role, email').eq('id', u_id).execute().data
            if u_check:
                db_role = str(u_check[0].get('role', '')).lower()
                db_email = str(u_check[0].get('email', '')).lower()
                if db_role == 'admin' or db_email == 'admin@virtuole.in':
                    session['role'] = 'admin'
                    session['email'] = db_email
                    session.permanent = True
                    session.modified = True
                    return True
        except Exception:
            pass
    return False

@admin_bp.route('/admin/add-program', methods=['POST'])
@admin_bp.route('/api/admin/add-program', methods=['POST'])
def add_program():
    if not is_admin_session(): return redirect('/login')
    t_months = request.form.getlist('track_months[]')
    t_prices = request.form.getlist('track_price[]')
    t_specs = request.form.getlist('track_specs[]')
    
    tracks = []
    for m, p, s in zip(t_months, t_prices, t_specs):
        if m and p and s:
            tracks.append({"months": int(m), "price": int(p), "specs": s})

    # For legacy fallback so it doesn't crash old code expecting integers
    fallback_price = int(t_prices[0]) if t_prices else 0
    fallback_specs = t_specs[0] if t_specs else ''
            
    supabase.table('programs').insert({
        "title": request.form.get('title'), "short_description": request.form.get('short_description'), 
        "specs_beginner": fallback_specs, "specs_intermediate": fallback_specs, "specs_expert": fallback_specs,
        "price_beginner": fallback_price, "price_intermediate": fallback_price, "price_expert": fallback_price,
        "is_active": True, "image_url": fix_gdrive_url(request.form.get('image_url', '')),
        "offer_1m": False, "offer_2m": False, "offer_3m": False,
        "allow_custom_timeline": request.form.get('allow_custom_timeline') == 'on',
        "custom_min_months": int(request.form.get('custom_min_months', 1) or 1),
        "max_custom_months": int(request.form.get('max_custom_months', 12) or 12),
        "custom_price": int(request.form.get('custom_price', 0) or 0),
        "custom_specs": request.form.get('custom_specs', ''),
        "category": request.form.get('category', 'General'),
        "badge_text": request.form.get('badge_text', ''),
        "tracks": tracks
    }).execute()
    return redirect(url_for('dashboard.dashboard_admin', tab='programs'))

@admin_bp.route('/admin/edit-program', methods=['POST'])
@admin_bp.route('/api/admin/edit-program', methods=['POST'])
def edit_program():
    if not is_admin_session(): return redirect('/login')
    program_id = request.form.get('program_id')
    t_months = request.form.getlist('track_months[]')
    t_prices = request.form.getlist('track_price[]')
    t_specs = request.form.getlist('track_specs[]')
    
    tracks = []
    for m, p, s in zip(t_months, t_prices, t_specs):
        if m and p and s:
            tracks.append({"months": int(m), "price": int(p), "specs": s})
            
    supabase.table('programs').update({
        "title": request.form.get('title'), "short_description": request.form.get('short_description'), 
        "image_url": fix_gdrive_url(request.form.get('image_url', '')),
        "allow_custom_timeline": request.form.get('allow_custom_timeline') == 'on',
        "custom_min_months": int(request.form.get('custom_min_months', 1) or 1),
        "max_custom_months": int(request.form.get('max_custom_months', 12) or 12),
        "custom_price": int(request.form.get('custom_price', 0) or 0),
        "custom_specs": request.form.get('custom_specs', ''),
        "category": request.form.get('category', 'General'),
        "badge_text": request.form.get('badge_text', ''),
        "tracks": tracks
    }).eq('id', program_id).execute()
    return redirect(url_for('dashboard.dashboard_admin', tab='programs'))

@admin_bp.route('/admin/delete-program', methods=['POST'])
@admin_bp.route('/api/admin/delete-program', methods=['POST'])
def delete_program():
    if not is_admin_session(): return redirect('/login')
    # Soft Delete: Preserves student data history
    supabase.table('programs').update({"is_active": False}).eq('id', request.form.get('program_id')).execute()
    return redirect(url_for('dashboard.dashboard_admin', tab='programs'))

@admin_bp.route('/admin/reactivate-program', methods=['POST'])
@admin_bp.route('/api/admin/reactivate-program', methods=['POST'])
def reactivate_program():
    if not is_admin_session(): return redirect('/login')
    supabase.table('programs').update({"is_active": True}).eq('id', request.form.get('program_id')).execute()
    return redirect(url_for('dashboard.dashboard_admin', tab='programs'))

@admin_bp.route('/admin/add-task', methods=['POST'])
@admin_bp.route('/api/admin/add-task', methods=['POST'])
def add_task():
    if not is_admin_session(): return redirect('/login')
    max_completions = int(request.form.get('max_completions', 1) or 1)
    supabase.table('ambassador_tasks').insert({
        "title": request.form.get('title'), 
        "description": request.form.get('description'), 
        "point_value": int(request.form.get('point_value')), 
        "is_active": True, 
        "max_completions": max_completions,
        "badge_text": request.form.get('badge_text', '')
    }).execute()
    return redirect(url_for('dashboard.dashboard_admin', tab='tasks'))

@admin_bp.route('/admin/edit-task', methods=['POST'])
@admin_bp.route('/api/admin/edit-task', methods=['POST'])
def edit_task():
    if not is_admin_session(): return redirect('/login')
    task_id = request.form.get('task_id')
    max_completions = int(request.form.get('max_completions', 1) or 1)
    supabase.table('ambassador_tasks').update({
        "title": request.form.get('title'),
        "description": request.form.get('description'),
        "point_value": int(request.form.get('point_value')),
        "max_completions": max_completions,
        "badge_text": request.form.get('badge_text', '')
    }).eq('id', task_id).execute()
    return redirect(url_for('dashboard.dashboard_admin', tab='tasks'))
@admin_bp.route('/admin/delete-task', methods=['POST'])
@admin_bp.route('/api/admin/delete-task', methods=['POST'])
def delete_task():
    if not is_admin_session(): return redirect('/login')
    supabase.table('ambassador_tasks').delete().eq('id', request.form.get('task_id')).execute()
    return redirect(url_for('dashboard.dashboard_admin', tab='tasks'))

@admin_bp.route('/admin/mark-swag-sent', methods=['POST'])
@admin_bp.route('/api/admin/mark-swag-sent', methods=['POST'])
def mark_swag_sent():
    if not is_admin_session(): return redirect('/login')
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
    return redirect(url_for('dashboard.dashboard_admin', tab='swag'))

@admin_bp.route('/admin/update-role', methods=['POST'])
@admin_bp.route('/api/admin/update-role', methods=['POST'])
def update_role():
    if not is_admin_session(): return redirect('/login')
    user_id = request.form.get('user_id')
    new_role = request.form.get('new_role')
    user = supabase.table('users').select('email', 'full_name').eq('id', user_id).execute().data[0]
    update_data = {'role': new_role}
    
    if new_role in ['ambassador', 'intern + ambassador']:
        existing = supabase.table('users').select('promo_code').eq('id', user_id).execute().data[0]
        if not existing.get('promo_code'):
            update_data['public_id'] = f"AMB-2026-{random.randint(100, 999)}"
            update_data['promo_code'] = f"AMB{''.join(random.choices(string.ascii_uppercase, k=4))}"
            update_data['ambassador_expiry'] = (datetime.utcnow() + timedelta(days=365)).isoformat()
            send_ambassador_email(user['email'], "Welcome Status", f"Promoted to Ambassador. Code: {update_data['promo_code']}.")
    elif new_role == 'mentor':
        send_system_email(user['email'], "Promotion Status", "Promoted to Mentor status.")
    elif new_role == 'admin':
        send_system_email(user['email'], "Clearance Status", "Granted Admin access clearance.")
        
    try:
        supabase.table('users').update(update_data).eq('id', user_id).execute()
    except Exception as e:
        print(f"ERROR IN UPDATE ROLE: {e}")
        return f"Database Error: {e}", 500
    return redirect(url_for('dashboard.dashboard_admin', tab='users'))


@admin_bp.route('/admin/push-notification', methods=['POST'])
@admin_bp.route('/api/admin/push-notification', methods=['POST'])
def admin_push_notification():
    try:
        if not is_admin_session():
            return jsonify({"success": False, "error": "Unauthorized"}), 401

        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"success": False, "error": "Invalid JSON payload."}), 400

        target_groups = data.get('target_groups', ['all'])
        notif_type = data.get('type', 'announcement')
        title = data.get('title', '')
        description = data.get('description', '')
        image_url = data.get('image_url')
        send_email = bool(data.get('send_email', False))

        if not title or not description:
            return jsonify({"success": False, "error": "Title and message are required."}), 400

        # Determine which users to target (include email and full_name for email broadcast)
        if 'all' in target_groups:
            users_res = supabase.table('users').select('id, role, email, full_name').neq('role', 'coupon').execute()
            users = users_res.data if users_res else []
        else:
            seen_ids = set()
            users = []
            all_users_res = supabase.table('users').select('id, role, email, full_name').execute()
            all_users = all_users_res.data if all_users_res else []
            for u in all_users:
                role = str(u.get('role', '')).lower()
                for group in target_groups:
                    if group.lower() in role and u['id'] not in seen_ids:
                        users.append(u)
                        seen_ids.add(u['id'])

        # Send in-app notification to each targeted user
        sent_count = 0
        email_count = 0
        errors = []

        # Prepare HTML email if email dispatch is requested
        email_html = ""
        if send_email:
            img_snippet = f'<div style="margin:20px 0; text-align:center;"><img src="{image_url}" alt="Banner" style="max-width:100%; border-radius:8px; border:1px solid #334155;"></div>' if image_url else ''
            email_html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #0f172a; color: #f8fafc; border-radius: 14px; padding: 32px; border: 1px solid #334155;">
                <div style="text-align: center; margin-bottom: 24px;">
                    <img src="https://www.virtuole.in/static/logo.png" alt="Virtuole" style="height: 42px;">
                </div>
                <div style="background: rgba(59, 130, 246, 0.12); border-left: 4px solid #3b82f6; padding: 12px 18px; border-radius: 6px; margin-bottom: 22px;">
                    <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 1.2px; color: #60a5fa; font-weight: 800;">Official Virtuole Broadcast</span>
                </div>
                <h2 style="color: #ffffff; margin: 0 0 14px 0; font-size: 20px;">{title}</h2>
                <div style="color: #cbd5e1; font-size: 15px; line-height: 1.65; white-space: pre-wrap; margin-bottom: 24px;">{description}</div>
                {img_snippet}
                <div style="text-align: center; margin-top: 28px;">
                    <a href="https://www.virtuole.in/login" style="background: linear-gradient(135deg, #3b82f6, #8b5cf6); color: #ffffff; padding: 12px 30px; border-radius: 50px; text-decoration: none; font-weight: 700; font-size: 14px; display: inline-block;">Access Your Portal &rarr;</a>
                </div>
                <div style="margin-top: 36px; border-top: 1px solid #334155; padding-top: 20px; font-size: 12px; color: #64748b; text-align: center;">
                    Virtuole Education Technologies &bull; Govt of India Registered MSME<br>
                    Begusarai, Bihar &bull; Official Portal: <a href="https://www.virtuole.in" style="color:#60a5fa; text-decoration:none;">www.virtuole.in</a>
                </div>
            </div>
            """

        for user in users:
            try:
                metadata = {
                    'target_groups': target_groups,
                    'sent_by': 'admin'
                }
                if image_url:
                    metadata['image_url'] = image_url
                metadata['target_user_id'] = str(user['id'])
                metadata['target_role'] = str(user.get('role', '')).lower()

                supabase.table('system_notifications').insert({
                    "type": notif_type,
                    "title": title,
                    "description": description,
                    "metadata": metadata
                }).execute()
                sent_count += 1
            except Exception as inner_e:
                errors.append(str(inner_e))
                if sent_count == 0 and 'relation' in str(inner_e).lower():
                    return jsonify({
                        "success": False,
                        "error": "The system_notifications table does not exist. Please create it in Supabase first."
                    }), 500

            # Optional email dispatch
            if send_email and user.get('email'):
                try:
                    send_system_email(user['email'], f"[Virtuole Announcement] {title}", email_html, is_html=True)
                    email_count += 1
                except Exception as mail_err:
                    print(f"Failed to email broadcast to {user.get('email')}: {mail_err}")

        if sent_count == 0 and errors:
            return jsonify({"success": False, "error": f"Failed to send to any user. Database error: {errors[0]}"}), 500

        msg = f"Notification delivered to {sent_count} user account(s)."
        if send_email:
            msg += f" Dispatched {email_count} email announcement(s)."
        if errors:
            msg += f" ({len(errors)} failed)"

        return jsonify({"success": True, "message": msg, "sent_count": sent_count, "email_count": email_count})

    except Exception as e:
        import traceback
        print(f"Push notification error: {traceback.format_exc()}")
        return jsonify({"success": False, "error": str(e)}), 500


@admin_bp.route('/admin/bulk-update-roles', methods=['POST'])
@admin_bp.route('/api/admin/bulk-update-roles', methods=['POST'])
def admin_bulk_update_roles():
    if not is_admin_session():
        if request.is_json:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return redirect('/login')

    data = request.get_json(silent=True) if request.is_json else request.form
    new_role = data.get('new_role')
    user_ids = data.get('user_ids')

    if isinstance(user_ids, str):
        user_ids = [x.strip() for x in user_ids.split(',') if x.strip()]
    elif not isinstance(user_ids, list):
        user_ids = []

    if not new_role or not user_ids:
        if request.is_json:
            return jsonify({"success": False, "error": "Role and users are required."}), 400
        return redirect(url_for('dashboard.dashboard_admin', tab='directory'))

    allowed_roles = ['intern', 'ambassador', 'intern + ambassador', 'mentor', 'admin']
    if new_role not in allowed_roles:
        if request.is_json:
            return jsonify({"success": False, "error": "Invalid role specified."}), 400
        return redirect(url_for('dashboard.dashboard_admin', tab='directory'))

    updated_count = 0
    for uid in user_ids:
        try:
            supabase.table('users').update({"role": new_role}).eq('id', uid).execute()
            updated_count += 1
        except Exception as e:
            print(f"Error bulk updating role for user {uid}: {e}")

    if request.is_json:
        return jsonify({
            "success": True,
            "count": updated_count,
            "message": f"Successfully updated {updated_count} user(s) to '{new_role}'."
        })

    return redirect(url_for('dashboard.dashboard_admin', tab='directory', bulk_updated=updated_count))


@admin_bp.route('/admin/sync-phonepe-transaction', methods=['POST'])
@admin_bp.route('/api/admin/sync-phonepe-transaction', methods=['POST'])
def admin_sync_phonepe_transaction():
    if not is_admin_session():
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.get_json(silent=True) if request.is_json else request.form
    if not data:
        data = request.args
    transaction_id = (data.get('transaction_id') or '').strip()

    if not transaction_id:
        return jsonify({"success": False, "error": "Transaction ID or Razorpay Payment ID is required."}), 400

    from api.utils.razorpay import fetch_razorpay_payment, fulfill_payment_success as fulfill_rzp
    from api.utils.phonepe import check_phonepe_status, fulfill_payment_success as fulfill_pe

    # 1. Try Razorpay verification if starts with pay_ or order_
    if transaction_id.startswith('pay_') or transaction_id.startswith('order_'):
        rzp_res = fetch_razorpay_payment(transaction_id)
        if rzp_res.get("success"):
            fulfill_rzp(transaction_id, payment_id=transaction_id)
            return jsonify({
                "success": True,
                "status": "paid",
                "message": f"Razorpay confirmed transaction '{transaction_id}'. Marked as PAID and receipt dispatched!",
                "data": rzp_res.get("data")
            })

    # 2. Check PhonePe status
    status_res = check_phonepe_status(transaction_id)
    if status_res.get("success"):
        fulfill_pe(transaction_id)
        return jsonify({
            "success": True,
            "status": "paid",
            "message": f"Payment confirmed for transaction '{transaction_id}'. Marked as PAID and receipt dispatched!",
            "data": status_res.get("data")
        })

    code = status_res.get("code") or "UNKNOWN"
    msg = status_res.get("message") or "Gateway reported status not completed."

    if code in ['PAYMENT_ERROR', 'PAYMENT_DECLINED']:
        try:
            supabase.table('payments').update({
                "status": "failed",
                "updated_at": datetime.utcnow().isoformat()
            }).eq('transaction_id', transaction_id).execute()
        except Exception:
            pass

    return jsonify({
        "success": False,
        "status": code,
        "message": f"Gateway response: {code} - {msg}",
        "data": status_res.get("data")
    })



