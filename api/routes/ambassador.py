
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from api.config import supabase, limiter
from api.utils.email import send_system_email, send_ambassador_email
import random, string, uuid, json
from datetime import datetime, timedelta

ambassador_bp = Blueprint('ambassador', __name__)



@ambassador_bp.route('/claim-points', methods=['POST'])
@ambassador_bp.route('/api/claim-points', methods=['POST'])
def claim_points():
    if str(session.get('role', '')).lower() not in ['ambassador', 'intern + ambassador']: return redirect('/login')
    task_id = request.form.get('task_id')
    
    task_data = supabase.table('ambassador_tasks').select('max_completions').eq('id', task_id).execute().data
    if task_data:
        max_c = task_data[0].get('max_completions', 1)
        existing = len(supabase.table('ambassador_claims').select('id').eq('ambassador_id', session['user_id']).eq('task_id', task_id).in_('status', ['pending', 'approved']).execute().data)
        if existing >= max_c:
            return redirect(url_for('dashboard.dashboard_ambassador'))

    supabase.table('ambassador_claims').insert({
        "ambassador_id": session['user_id'], "task_id": task_id,
        "proof_link": request.form.get('proof_link'), "notes": request.form.get('notes')
    }).execute()
    return redirect(url_for('dashboard.dashboard_ambassador'))

import json

def parse_shipping_address(addr_str):
    if not addr_str: return {}
    try:
        return json.loads(addr_str)
    except Exception:
        return {"name": "", "addr1": addr_str, "addr2": "", "city": "", "state": "", "pin": "", "phone": ""}

@ambassador_bp.route('/api/update-address', methods=['POST'])
def update_address():
    if str(session.get('role', '')).lower() not in ['ambassador', 'intern + ambassador']: return redirect('/login')
    
    addr_data = {
        "name": request.form.get('addr_name', ''),
        "addr1": request.form.get('addr_line1', ''),
        "addr2": request.form.get('addr_line2', ''),
        "city": request.form.get('addr_city', ''),
        "state": request.form.get('addr_state', ''),
        "pin": request.form.get('addr_pin', ''),
        "phone": request.form.get('addr_phone', '')
    }
    supabase.table('users').update({"shipping_address": json.dumps(addr_data)}).eq('id', session['user_id']).execute()
    return redirect(url_for('dashboard.dashboard_ambassador', active_tab='profile'))

@ambassador_bp.route('/api/update-profile-intern', methods=['POST'])
def update_profile_intern():
    if str(session.get('role', '')).lower() not in ['intern', 'intern + ambassador']: return redirect('/login')
    
    full_name = request.form.get('full_name')
    
    # Load existing shipping details to preserve address info if they have it
    u_data = supabase.table('users').select('shipping_address').eq('id', session['user_id']).execute().data
    existing_shipping = parse_shipping_address(u_data[0].get('shipping_address', '')) if u_data else {}
    
    # Update academic/personal details
    existing_shipping['gender'] = request.form.get('gender', '')
    existing_shipping['phone'] = request.form.get('phone', '')
    existing_shipping['city'] = request.form.get('city', '')
    existing_shipping['state'] = request.form.get('state', '')
    existing_shipping['college_name'] = request.form.get('college_name', '')
    existing_shipping['course_name'] = request.form.get('course_name', '')
    existing_shipping['session_year'] = request.form.get('session_year', '')
    
    update_payload = {"shipping_address": json.dumps(existing_shipping)}
    if full_name:
        update_payload["full_name"] = full_name
        
    supabase.table('users').update(update_payload).eq('id', session['user_id']).execute()
    
    # Update session name just in case
    if full_name:
        session['name'] = full_name
        
    return redirect(url_for('dashboard.dashboard_intern', active_tab='profile'))

