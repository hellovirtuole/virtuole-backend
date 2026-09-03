
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from api.config import supabase, limiter
from api.utils.email import send_system_email, send_ambassador_email
import random, string, uuid, json
from datetime import datetime, timedelta

admin_bp = Blueprint('admin', __name__)



def fix_gdrive_url(url):
    if not url: return url
    if "drive.google.com/file/d/" in url:
        try:
            file_id = url.split("/d/")[1].split("/")[0]
            return f"https://drive.google.com/uc?export=view&id={file_id}"
        except:
            return url
    return url

@admin_bp.route('/admin/add-program', methods=['POST'])
@admin_bp.route('/api/admin/add-program', methods=['POST'])
def add_program():
    if str(session.get('role', '')).lower() != 'admin': return redirect('/login')
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
    if str(session.get('role', '')).lower() != 'admin': return redirect('/login')
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
    if str(session.get('role', '')).lower() != 'admin': return redirect('/login')
    # Soft Delete: Preserves student data history
    supabase.table('programs').update({"is_active": False}).eq('id', request.form.get('program_id')).execute()
    return redirect(url_for('dashboard.dashboard_admin', tab='programs'))

@admin_bp.route('/admin/add-task', methods=['POST'])
@admin_bp.route('/api/admin/add-task', methods=['POST'])
def add_task():
    if str(session.get('role', '')).lower() != 'admin': return redirect('/login')
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
    if str(session.get('role', '')).lower() != 'admin': return redirect('/login')
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
    if str(session.get('role', '')).lower() != 'admin': return redirect('/login')
    supabase.table('ambassador_tasks').delete().eq('id', request.form.get('task_id')).execute()
    return redirect(url_for('dashboard.dashboard_admin', tab='tasks'))

@admin_bp.route('/admin/mark-swag-sent', methods=['POST'])
@admin_bp.route('/api/admin/mark-swag-sent', methods=['POST'])
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
    return redirect(url_for('dashboard.dashboard_admin', tab='swag'))

@admin_bp.route('/admin/update-role', methods=['POST'])
@admin_bp.route('/api/admin/update-role', methods=['POST'])
def update_role():
    if str(session.get('role', '')).lower() != 'admin': return redirect('/login')
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

