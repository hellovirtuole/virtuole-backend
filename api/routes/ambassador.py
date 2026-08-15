
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
    if isinstance(addr_str, dict): return addr_str
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

