
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from api.config import supabase, limiter
from api.utils.email import send_system_email, send_ambassador_email
import random, string, uuid, json
from datetime import datetime, timedelta
from api.routes.ambassador import parse_shipping_address

dashboard_bp = Blueprint('dashboard', __name__)



@dashboard_bp.route('/dashboard-intern')
def dashboard_intern():
    try:
        user_role = str(session.get('role', '')).lower()
        if user_role not in ['intern', 'intern + ambassador']: return redirect('/login')
    
        ambassador_active = False
        if user_role == 'intern + ambassador':
            u = supabase.table('users').select('ambassador_expiry').eq('id', session['user_id']).execute().data
            if u and u[0].get('ambassador_expiry'):
                try:
                    expiry = datetime.fromisoformat(u[0]['ambassador_expiry'])
                    if datetime.utcnow() <= expiry.replace(tzinfo=None):
                        ambassador_active = True
                except ValueError:
                    pass
                
        u_id = session['user_id']
        active_enrolls = supabase.table('enrollments').select('*, programs(*)').eq('user_id', u_id).in_('status', ['active', 'resubmit']).execute().data
        active_projects = []
    
        # Fetch full user profile for the profile tab
        u_data = supabase.table('users').select('*').eq('id', u_id).execute().data
        user_profile = u_data[0] if u_data else {}
    
        # profile_details is a jsonb column — Supabase returns it as a dict directly
        profile_details = user_profile.get('profile_details') or {}
        if not isinstance(profile_details, dict):
            # Safety fallback: if it's somehow a string, try to parse it
            try:
                profile_details = json.loads(profile_details)
            except Exception:
                profile_details = {}
    
        # Auto-fill academic details from first enrollment if missing in profile
        if not profile_details.get('college_name'):
            try:
                first_enroll = supabase.table('enrollments').select('college_name, course_name, session_year').eq('user_id', u_id).order('created_at', desc=False).limit(1).execute().data
                if first_enroll:
                    profile_details['college_name'] = first_enroll[0].get('college_name', '')
                    profile_details['course_name'] = first_enroll[0].get('course_name', '')
                    profile_details['session_year'] = first_enroll[0].get('session_year', '')
            except Exception:
                pass
    
        now = datetime.utcnow()
        for e in active_enrolls:
            try:
                start_dt = datetime.fromisoformat(e['created_at'].replace('Z', '+00:00')) if e.get('created_at') else now
            except:
                start_dt = now
        
            # Ensure naive datetime for math
            start_dt = start_dt.replace(tzinfo=None)
        
            if e['status'] == 'resubmit':
                duration_days = 1
            else:
                duration_days = 90 if e.get('track_level', '').lower() == 'expert' else 30
            
            end_dt = start_dt + timedelta(days=duration_days)
        
            if now > end_dt:
                if e['status'] == 'active':
                    # Auto-delete expired enrollment
                    supabase.table('enrollments').delete().eq('id', e['id']).execute()
                elif e['status'] == 'resubmit':
                    # Mark as failed permanently
                    supabase.table('enrollments').update({"status": "failed"}).eq('id', e['id']).execute()
                    supabase.table('submissions').insert({
                        "enrollment_id": e['enrollment_id'], 
                        "score": 0, 
                        "certificate_url": "failed:Missed 24-hour resubmission deadline.",
                        "evaluated_at": now.isoformat()
                    }).execute()
                continue
            
            remaining_days = max(0, (end_dt - now).days)
            remaining_hours = max(0, int((end_dt - now).total_seconds() / 3600))
        
            active_projects.append({
                'program_title': e['programs']['title'], 
                'description': e['programs']['short_description'], 
                'track_level': e['track_level'], 
                'enrollment_id': e['enrollment_id'], 
                'specs_link': e['programs'].get(f"specs_{e['track_level']}", '#'), 
                'amount_due': e['programs'].get(f"price_{e['track_level']}", 0),
                'status': e['status'],
                'remaining_days': remaining_days,
                'remaining_hours': remaining_hours,
                'duration_days': duration_days
            })
        offered = supabase.table('programs').select('*').eq('is_active', True).execute().data
    
        completed_projects = []
        graded_enrolls = supabase.table('enrollments').select('*, programs(title)').eq('user_id', u_id).in_('status', ['graded', 'submitted', 'certified', 'completed', 'graduated']).execute().data
        for e in graded_enrolls:
            sub = supabase.table('submissions').select('*').eq('enrollment_id', e['enrollment_id']).execute().data
            if sub:
                s = sub[0]
                completed_projects.append({'score': s.get('score'), 'program_title': e['programs']['title'], 'track_level': e['track_level'], 'enrollment_id': e['enrollment_id'], 'evaluated_date': s.get('evaluated_at', '').split('T')[0] if s.get('evaluated_at') else 'Pending', 'certificate_url': s.get('certificate_url'), 'lor_url': s.get('lor_url')})
            else:
                completed_projects.append({'score': e.get('final_score', 100), 'program_title': e['programs']['title'], 'track_level': e['track_level'], 'enrollment_id': e['enrollment_id'], 'evaluated_date': e.get('updated_at', '').split('T')[0] if e.get('updated_at') else 'Pending', 'certificate_url': None, 'lor_url': None})

        # Determine the default active tab: Explore if no active programs, otherwise Workspace.
        requested_tab = request.args.get('active_tab')
        default_tab = requested_tab if requested_tab else ('workspace' if active_projects else 'explore')

        return render_template('dashboard_intern.html', user_name=session.get('name'), active_projects=active_projects, offered_programs=offered, completed_projects=completed_projects, ambassador_active=ambassador_active, active_tab=default_tab, user_profile=user_profile, profile_details=profile_details)
    except Exception as e:
        import traceback
        return f"<h1>Internal Server Error inside dashboard_intern</h1><pre>{traceback.format_exc()}</pre>", 500


@dashboard_bp.route('/dashboard-mentor')
def dashboard_mentor():
    if str(session.get('role', '')).lower() != 'mentor': return redirect('/login')
    pend_subs_raw = supabase.table('submissions').select('*, enrollments(created_at, track_level)').is_('score', 'null').execute().data
    graded_subs = supabase.table('submissions').select('*').not_.is_('score', 'null').execute().data
    claims = supabase.table('ambassador_claims').select('id, proof_link, notes, ambassador_id, users(full_name, email), ambassador_tasks(title, point_value)').eq('status', 'pending').execute().data
    pending_claims = [{"id": c['id'], "ambassador_id": c['ambassador_id'], "ambassador_name": c['users']['full_name'], "ambassador_email": c['users']['email'], "task_title": c['ambassador_tasks']['title'], "point_value": c['ambassador_tasks']['point_value'], "proof_link": c['proof_link'], "notes": c['notes']} for c in claims]
    analytics = build_mentor_analytics(pend_subs_raw, graded_subs, len(pending_claims))
    
    overdue_subs = []
    early_subs = []
    now = datetime.utcnow()
    for sub in (pend_subs_raw or []):
        e = sub.get('enrollments') or {}
        try:
            start_dt = datetime.fromisoformat(e.get('created_at', '').replace('Z', '+00:00')) if e.get('created_at') else now
        except:
            start_dt = now
            
        start_dt = start_dt.replace(tzinfo=None)
        duration_days = 90 if e.get('track_level', '').lower() == 'expert' else 30
        end_dt = start_dt + timedelta(days=duration_days)
        
        if now > end_dt:
            overdue_subs.append(sub)
        else:
            early_subs.append(sub)

    return render_template('dashboard_mentor.html', user_name=session.get('name'), 
                           pending_submissions=pend_subs_raw, 
                           overdue_subs=overdue_subs, early_subs=early_subs,
                           graded_submissions=graded_subs, pending_claims=pending_claims, analytics=analytics)


def build_mentor_analytics(pending_subs, graded_subs, pending_claims_count):
    """Chart.js-ready series for the mentor dashboard: grading throughput over
    the last 14 days plus a pass/fail score-band split. Defensive so a missing
    field degrades to zeros rather than 500-ing."""
    now = datetime.utcnow()
    day_keys = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(13, -1, -1)]
    day_labels = [(now - timedelta(days=i)).strftime("%b %d") for i in range(13, -1, -1)]
    graded_by_day = {k: 0 for k in day_keys}
    bands = {"90-100": 0, "80-89": 0, "60-79": 0, "<60": 0}

    for s in (graded_subs or []):
        try:
            key = (s.get('evaluated_at') or s.get('created_at') or '')[:10]
            if key in graded_by_day:
                graded_by_day[key] += 1
            sc = s.get('score')
            if sc is None:
                continue
            if sc >= 90:   bands["90-100"] += 1
            elif sc >= 80: bands["80-89"] += 1
            elif sc >= 60: bands["60-79"] += 1
            else:          bands["<60"] += 1
        except Exception:
            continue

    return {
        "throughput_labels": day_labels,
        "throughput_values": [graded_by_day[k] for k in day_keys],
        "band_labels": list(bands.keys()),
        "band_values": list(bands.values()),
        "queue_labels": ["Pending Reviews", "Graded", "GTM Claims"],
        "queue_values": [len(pending_subs or []), len(graded_subs or []), pending_claims_count],
    }

@dashboard_bp.route('/dashboard-admin')
def dashboard_admin():
    if str(session.get('role', '')).lower() != 'admin': return redirect('/login')
    active_tab = request.args.get('tab', 'overview')
    timeframe = request.args.get('timeframe', 'all')

    # Optional time window for the telemetry stat cards.
    now = datetime.utcnow()
    cutoffs = {
        '1day': now - timedelta(days=1),
        '1week': now - timedelta(weeks=1),
        '1month': now - timedelta(days=30),
    }
    cutoff = cutoffs.get(timeframe)

    def _window(query):
        # Apply the created_at window when a timeframe is selected.
        return query.gte('created_at', cutoff.isoformat()) if cutoff else query

    try:
        earnings = sum([p['amount'] / 100 for p in _window(supabase.table('payments').select('amount').eq('status', 'paid')).execute().data])
        enrolled = len(_window(supabase.table('enrollments').select('id')).execute().data)
        certified = len(_window(supabase.table('submissions').select('id').gte('score', 80)).execute().data)
        pend_grading = len(_window(supabase.table('submissions').select('id').is_('score', 'null')).execute().data)
    except Exception:
        # Fall back to all-time totals if a table has no created_at column.
        earnings = sum([p['amount'] / 100 for p in supabase.table('payments').select('amount').eq('status', 'paid').execute().data])
        enrolled = len(supabase.table('enrollments').select('id').execute().data)
        certified = len(supabase.table('submissions').select('id').gte('score', 80).execute().data)
        pend_grading = len(supabase.table('submissions').select('id').is_('score', 'null').execute().data)

    progs = supabase.table('programs').select('*').execute().data
    tasks = supabase.table('ambassador_tasks').select('*').execute().data
    users = supabase.table('users').select('*').execute().data

    # Calculate coupon statistics
    coupons = [u for u in users if u['role'] == 'coupon']
    all_payments = supabase.table('payments').select('amount, applied_promo, user_id, created_at').eq('status', 'paid').execute().data
    
    for c in coupons:
        c_payments = [p for p in all_payments if p.get('applied_promo') == c['promo_code']]
        c['usage_count'] = len(c_payments)
        c['revenue_generated'] = sum([p['amount']/100 for p in c_payments])
        
        referred = []
        for p in c_payments:
            user_match = next((u for u in users if u['id'] == p.get('user_id')), None)
            if user_match:
                s_details = parse_shipping_address(user_match.get('shipping_address', ''))
                referred.append({
                    "name": user_match.get('full_name') or 'Unknown',
                    "email": user_match.get('email') or 'Unknown',
                    "date": p.get('created_at', '').split('T')[0] if p.get('created_at') else '',
                    "college": s_details.get('college_name') or 'Unknown'
                })
        c['referred_users'] = referred
        
    # Calculate ambassador statistics
    all_ambassadors = [u for u in users if str(u.get('role', '')).lower() in ['ambassador', 'intern + ambassador']]
    for a in all_ambassadors:
        a_payments = [p for p in all_payments if p.get('applied_promo') == a['promo_code']]
        a['referral_count'] = len(a_payments)
        
        referred = []
        for p in a_payments:
            user_match = next((u for u in users if u['id'] == p.get('user_id')), None)
            if user_match:
                s_details = parse_shipping_address(user_match.get('shipping_address', ''))
                referred.append({
                    "name": user_match.get('full_name') or 'Unknown',
                    "email": user_match.get('email') or 'Unknown',
                    "date": p.get('created_at', '').split('T')[0] if p.get('created_at') else '',
                    "college": s_details.get('college_name') or 'Unknown'
                })
        a['referred_users'] = referred
        
    # -----------------------------------------------------------------
    # GRAPHICAL ANALYTICS DATA (Chart.js-ready, JSON-serializable)
    # Built defensively so a missing column never breaks the dashboard.
    # -----------------------------------------------------------------
    analytics = build_admin_analytics(progs, users)

    # Fetch Dynamic Tiers
    amb_tiers_resp = supabase.table('ambassador_tiers').select('*').order('points_required', desc=True).execute()
    ambassador_tiers = amb_tiers_resp.data if amb_tiers_resp and amb_tiers_resp.data else [
        {"id": 0, "tier_level": 4, "name": "Star Ambassador", "points_required": 3000, "give_certificate": True, "give_lor": True, "benefits_text": "Elite Swag Kit (Mechanical Keyboard & Desk Mat)\nDirect Paid Internship Offer at Virtuole HQ"},
        {"id": 0, "tier_level": 3, "name": "Community Lead", "points_required": 1500, "give_certificate": False, "give_lor": False, "benefits_text": "Premium Virtuole Developer Hoodie"},
        {"id": 0, "tier_level": 2, "name": "Campus Advocate", "points_required": 500, "give_certificate": False, "give_lor": False, "benefits_text": "Exclusive Virtuole Tech Graphic T-Shirt"},
        {"id": 0, "tier_level": 1, "name": "Kickstart", "points_required": 0, "give_certificate": False, "give_lor": False, "benefits_text": "Virtuole branded Lanyard and Die-Cut Stickers"}
    ]
    
    # Fetch subscribers
    try:
        subscribers = supabase.table('subscribers').select('*').order('created_at', desc=True).execute().data
    except Exception:
        subscribers = []
        
    try:
        enrollments = supabase.table('enrollments').select('*').execute().data
    except Exception:
        enrollments = []
        
    prog_dict = {p['id']: p for p in progs}
    advanced_users = []
    
    for u in users:
        s_details = parse_shipping_address(u.get('shipping_address', ''))
        u_enrolls = [e for e in enrollments if e['user_id'] == u['id']]
        
        base_data = {
            "name": u.get('full_name') or '',
            "email": u.get('email') or '',
            "role": u.get('role') or '',
            "state": s_details.get('state') or '',
            "city": s_details.get('city') or '',
            "gender": s_details.get('gender') or '',
            "college": s_details.get('college_name') or '',
            "course": s_details.get('course_name') or '',
            "phone": s_details.get('phone') or ''
        }
        
        if not u_enrolls:
            d = base_data.copy()
            d["program"] = "None"
            d["track"] = "None"
            advanced_users.append(d)
        else:
            for e in u_enrolls:
                d = base_data.copy()
                d["program"] = prog_dict.get(e['program_id'], {}).get('title', 'Unknown')
                d["track"] = str(e.get('track_level', ''))
                advanced_users.append(d)

    grouped_ambassadors = [{"tier": t, "ambassadors": []} for t in ambassador_tiers]
    for a in all_ambassadors:
        pts = a.get('total_points') or 0
        for group in grouped_ambassadors:
            if pts >= group['tier']['points_required']:
                group['ambassadors'].append(a)
                break
            
    # Reverse ambassador_tiers for the template (so lowest tier is first in the settings form, but grouped_ambassadors is highest first)
    ambassador_tiers_asc = sorted(ambassador_tiers, key=lambda x: x['points_required'])

    activity_feed = []
    for u in users:
        date_str = u.get('created_at')
        if not date_str: continue
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            activity_feed.append({
                "type": "signup",
                "title": "New User Registration",
                "description": f"{u.get('full_name')} ({u.get('email')}) joined the platform.",
                "timestamp": dt.strftime('%b %d, %Y %I:%M %p'),
                "date_obj": dt
            })
        except: pass
        
    for e in enrollments:
        date_str = e.get('created_at')
        if not date_str: continue
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            user = next((x for x in users if x['id'] == e['user_id']), None)
            u_name = user['full_name'] if user else 'A user'
            prog_title = prog_dict.get(e['program_id'], {}).get('title', 'a program')
            activity_feed.append({
                "type": "enrollment",
                "title": "New Enrollment",
                "description": f"{u_name} enrolled in {prog_title}.",
                "timestamp": dt.strftime('%b %d, %Y %I:%M %p'),
                "date_obj": dt
            })
        except: pass
        
    activity_feed.sort(key=lambda x: x['date_obj'], reverse=True)
    activity_feed = activity_feed[:15]

    top_ambassadors = sorted(all_ambassadors, key=lambda x: x.get('total_points') or 0, reverse=True)[:10]

    state_counts = {}
    for u in advanced_users:
        st = u.get('state')
        if st and str(st).strip() and str(st).strip().lower() != 'unknown':
            state_counts[st] = state_counts.get(st, 0) + 1
    top_states = sorted(state_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    projected_revenue = 0
    try:
        seven_days_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        recent_payments = supabase.table('payments').select('amount').eq('status', 'paid').gte('created_at', seven_days_ago).execute().data
        if recent_payments:
            recent_revenue = sum([p['amount'] / 100 for p in recent_payments])
            projected_revenue = (recent_revenue / 7) * 30
    except Exception:
        pass

    return render_template('dashboard_admin.html', user_name=session.get('name'), total_earnings=round(earnings, 2), total_enrolled=enrolled, total_certified=certified, pending_grading=pend_grading, offered_programs=progs, all_tasks=tasks, user_directory=users, coupons=coupons, all_ambassadors=all_ambassadors, grouped_ambassadors=grouped_ambassadors, ambassador_tiers=ambassador_tiers_asc, active_tab=active_tab, current_filter=timeframe, analytics=analytics, subscribers=subscribers, advanced_users=advanced_users, activity_feed=activity_feed, top_ambassadors=top_ambassadors, top_states=top_states, projected_revenue=round(projected_revenue, 2))


@dashboard_bp.route('/admin/tiers', methods=['POST'])
@dashboard_bp.route('/api/admin/tiers', methods=['POST'])
def save_ambassador_tiers():
    if str(session.get('role', '')).lower() != 'admin': return redirect('/login')
    if not supabase: return "Database Error", 500
    
    tier_levels = request.form.getlist('tier_level[]')
    names = request.form.getlist('name[]')
    points_reqs = request.form.getlist('points_required[]')
    give_cert_indexes = request.form.getlist('give_certificate[]')
    give_lor_indexes = request.form.getlist('give_lor[]')
    benefits_texts = request.form.getlist('benefits_text[]')
    
    existing = supabase.table('ambassador_tiers').select('id').execute().data
    for row in (existing or []):
        supabase.table('ambassador_tiers').delete().eq('id', row['id']).execute()
    
    inserts = []
    for i in range(len(tier_levels)):
        inserts.append({
            "tier_level": int(tier_levels[i] or 0),
            "name": names[i],
            "points_required": int(points_reqs[i] or 0),
            "give_certificate": str(i) in give_cert_indexes,
            "give_lor": str(i) in give_lor_indexes,
            "benefits_text": benefits_texts[i] if i < len(benefits_texts) else ""
        })
        
    if inserts:
        supabase.table('ambassador_tiers').insert(inserts).execute()
        
    return redirect(url_for('dashboard.dashboard_admin', tab='tiers', message="Ambassador tiers updated successfully."))


@dashboard_bp.route('/admin/create-coupon', methods=['POST'])
@dashboard_bp.route('/api/admin/create-coupon', methods=['POST'])
def api_admin_create_coupon():
    if str(session.get('role', '')).lower() != 'admin': return redirect('/login')
    
    coupon_name = request.form.get('coupon_name')
    promo_code = request.form.get('promo_code', '').upper()
    try:
        discount_percent = int(request.form.get('discount_percent', 0) or 0)
    except ValueError:
        discount_percent = 0
        
    validity = request.form.get('validity', 'manual')
    
    expiry_date = None
    if validity != 'manual':
        days = 0
        if validity == 'custom':
            try:
                days = int(request.form.get('custom_days', 0) or 0)
            except ValueError:
                days = 0
        else:
            try:
                days = int(validity)
            except ValueError:
                days = 0
                
        if days > 0:
            expiry_date = (datetime.utcnow() + timedelta(days=days)).isoformat()
    
    # Parse new limits
    try:
        usage_limit = int(request.form.get('usage_limit', '') or 0)
        if usage_limit == 0: usage_limit = None
    except ValueError:
        usage_limit = None
        
    try:
        user_limit = int(request.form.get('user_limit', '') or 0)
        if user_limit == 0: user_limit = None
    except ValueError:
        user_limit = None
        
    allowed_level = request.form.get('allowed_level', '').strip()
    if not allowed_level:
        allowed_level = None
        
    # Check if promo_code already exists
    existing = supabase.table('users').select('id').eq('promo_code', promo_code).execute().data
    if existing:
        return "Promo code already exists", 400
        
    random_email = f"coupon_{promo_code.lower()}_{random.randint(1000, 9999)}@virtuole.system"
    supabase.table('users').insert({
        "id": str(uuid.uuid4()),
          "full_name": coupon_name,
        "email": random_email,
        "role": "coupon",
        "promo_code": promo_code,
        "total_points": discount_percent,
        "public_id": f"COUPON-{promo_code}",
        "ambassador_expiry": expiry_date,
        "coupon_usage_limit": usage_limit,
        "coupon_user_limit": user_limit,
        "coupon_allowed_level": allowed_level
    }).execute()
    
    return redirect(url_for('dashboard.dashboard_admin', tab='coupons'))

@dashboard_bp.route('/admin/delete-coupon', methods=['POST'])
@dashboard_bp.route('/api/admin/delete-coupon', methods=['POST'])
def api_admin_delete_coupon():
    if str(session.get('role', '')).lower() != 'admin': return redirect('/login')
    
    promo_code = request.form.get('promo_code')
    if promo_code:
        supabase.table('users').delete().eq('promo_code', promo_code).eq('role', 'coupon').execute()
        
    return redirect(url_for('dashboard.dashboard_admin', tab='coupons'))


def build_admin_analytics(programs, users):
    """Aggregate live Supabase data into Chart.js-ready series for the admin
    Platform Analytics tab. Every block is wrapped so an absent table/column
    degrades to empty data instead of 500-ing the whole dashboard."""
    empty = {
        "revenue_labels": [], "revenue_values": [],
        "enroll_labels": [], "enroll_values": [],
        "role_labels": [], "role_values": [],
        "outcome_labels": ["Certified (≥80)", "Failed (<80)", "Pending"], "outcome_values": [0, 0, 0],
        "program_labels": [], "program_values": [],
    }
    if not supabase:
        return empty

    now = datetime.utcnow()

    # ---- 30-day daily buckets for revenue + enrollments (line/area) ----
    day_keys = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29, -1, -1)]
    day_labels = [(now - timedelta(days=i)).strftime("%b %d") for i in range(29, -1, -1)]
    revenue_by_day = {k: 0.0 for k in day_keys}
    enroll_by_day = {k: 0 for k in day_keys}

    try:
        thirty_days_ago = (now - timedelta(days=30)).isoformat()
        paid = supabase.table('payments').select('amount, created_at').eq('status', 'paid').gte('created_at', thirty_days_ago).execute().data
        for p in paid:
            key = (p.get('created_at') or '')[:10]
            if key in revenue_by_day:
                revenue_by_day[key] += (p.get('amount') or 0) / 100.0
    except Exception:
        pass

    try:
        thirty_days_ago = (now - timedelta(days=30)).isoformat()
        enrolls = supabase.table('enrollments').select('created_at, program_id').gte('created_at', thirty_days_ago).execute().data
        for e in enrolls:
            key = (e.get('created_at') or '')[:10]
            if key in enroll_by_day:
                enroll_by_day[key] += 1
    except Exception:
        pass

    # ---- Role distribution (doughnut) ----
    role_counts = {}
    for u in (users or []):
        role = str(u.get('role') or 'intern').strip().lower()
        role_counts[role] = role_counts.get(role, 0) + 1
    role_labels = [r.title() for r in role_counts.keys()]
    role_values = list(role_counts.values())

    # ---- Certification outcomes (bar) ----
    certified = failed = pending = 0
    try:
        subs = supabase.table('submissions').select('score').execute().data
        for s in subs:
            score = s.get('score')
            if score is None:
                pending += 1
            elif score >= 80:
                certified += 1
            else:
                failed += 1
    except Exception:
        pass

    # ---- Program popularity: enrollments per program (horizontal bar) ----
    prog_titles = {p['id']: p.get('title', 'Untitled') for p in (programs or [])}
    prog_counts = {p['id']: 0 for p in (programs or [])}
    try:
        all_enrolls = supabase.table('enrollments').select('program_id').execute().data
        for e in all_enrolls:
            pid = e.get('program_id')
            if pid in prog_counts:
                prog_counts[pid] += 1
    except Exception:
        pass
    ranked = sorted(prog_counts.items(), key=lambda kv: kv[1], reverse=True)[:8]

    # ---- Cumulative growth: running totals of enrollments + revenue ----
    # Baseline = everything before the 30-day window, so the trend starts from
    # the true platform total rather than zero.
    base_enroll = 0
    base_revenue = 0.0
    try:
        thirty_days_ago = (now - timedelta(days=30)).isoformat()
        base_enroll = len(supabase.table('enrollments').select('id').lt('created_at', thirty_days_ago).execute().data)
        base_paid = supabase.table('payments').select('amount').eq('status', 'paid').lt('created_at', thirty_days_ago).execute().data
        base_revenue = sum([(p.get('amount') or 0) / 100.0 for p in base_paid])
    except Exception:
        pass
    cum_enroll, cum_revenue = [], []
    run_e, run_r = base_enroll, base_revenue
    for k in day_keys:
        run_e += enroll_by_day[k]
        run_r += revenue_by_day[k]
        cum_enroll.append(run_e)
        cum_revenue.append(round(run_r, 2))

    return {
        "revenue_labels": day_labels,
        "revenue_values": [round(revenue_by_day[k], 2) for k in day_keys],
        "enroll_labels": day_labels,
        "enroll_values": [enroll_by_day[k] for k in day_keys],
        "role_labels": role_labels,
        "role_values": role_values,
        "outcome_labels": ["Certified (≥80)", "Failed (<80)", "Pending"],
        "outcome_values": [certified, failed, pending],
        "program_labels": [prog_titles.get(pid, 'Untitled') for pid, _ in ranked],
        "program_values": [cnt for _, cnt in ranked],
        "growth_labels": day_labels,
        "growth_enroll": cum_enroll,
        "growth_revenue": cum_revenue,
    }

@dashboard_bp.route('/dashboard-ambassador')
def dashboard_ambassador():
    user_role = str(session.get('role', '')).lower()
    if user_role not in ['ambassador', 'intern + ambassador']: return redirect('/login')
    
    u = supabase.table('users').select('*').eq('id', session['user_id']).execute().data[0]
    
    if user_role == 'intern + ambassador':
        if u.get('ambassador_expiry'):
            try:
                expiry = datetime.fromisoformat(u['ambassador_expiry'])
                if datetime.utcnow() > expiry.replace(tzinfo=None):
                    return redirect('/dashboard-intern') # Expired dual roles get kicked back to intern
            except ValueError:
                pass
                
    pts = u.get('total_points') or 0
    
    # Fetch Dynamic Tiers
    amb_tiers_resp = supabase.table('ambassador_tiers').select('*').order('points_required', desc=False).execute()
    ambassador_tiers = amb_tiers_resp.data if amb_tiers_resp and amb_tiers_resp.data else [
        {"id": 0, "tier_level": 1, "name": "Kickstart", "points_required": 0, "give_certificate": False, "give_lor": False, "benefits_text": "Virtuole branded Lanyard and Die-Cut Stickers"},
        {"id": 0, "tier_level": 2, "name": "Campus Advocate", "points_required": 500, "give_certificate": False, "give_lor": False, "benefits_text": "Exclusive Virtuole Tech Graphic T-Shirt"},
        {"id": 0, "tier_level": 3, "name": "Community Lead", "points_required": 1500, "give_certificate": False, "give_lor": False, "benefits_text": "Premium Virtuole Developer Hoodie"},
        {"id": 0, "tier_level": 4, "name": "Star Ambassador", "points_required": 3000, "give_certificate": True, "give_lor": True, "benefits_text": "Elite Swag Kit (Mechanical Keyboard & Desk Mat)\nDirect Paid Internship Offer at Virtuole HQ"}
    ]
    
    shipping_details = parse_shipping_address(u.get('shipping_address', ''))
    
    tier_name = ambassador_tiers[0]['name']
    for t in ambassador_tiers:
        if pts >= t['points_required']:
            tier_name = t['name']
            
    refs = len(supabase.table('payments').select('id').eq('applied_promo', u['promo_code']).eq('status', 'paid').execute().data) if u.get('promo_code') else 0
    tasks = supabase.table('ambassador_tasks').select('*').eq('is_active', True).execute().data
    
    claims = supabase.table('ambassador_claims').select('task_id').eq('ambassador_id', session['user_id']).in_('status', ['pending', 'approved']).execute().data
    task_claims = {}
    for c in claims:
        task_claims[c['task_id']] = task_claims.get(c['task_id'], 0) + 1

    analytics = build_ambassador_analytics(u, pts, refs, ambassador_tiers)
    
    requested_tab = request.args.get('active_tab')
    
    return render_template('dashboard_ambassador.html', ambassador_name=session.get('name'), valid_until_date=u['ambassador_expiry'].split('T')[0] if u.get('ambassador_expiry') else 'N/A', total_points=pts, current_tier_name=tier_name, total_referrals=refs, promo_code=u.get('promo_code', 'Pending'), amb_id=u.get('public_id', 'Pending'), available_tasks=tasks, task_claims=task_claims, shipping_details=shipping_details, analytics=analytics, can_switch_intern=(user_role == 'intern + ambassador'), ambassador_tiers=ambassador_tiers, active_tab=requested_tab)


def build_ambassador_analytics(user, points, referrals, ambassador_tiers):
    """Chart.js-ready series for the ambassador dashboard: tier-progress gauge,
    a cumulative points-earned trend from approved claims, and a referrals
    breakdown. Defensive so missing claim history degrades to a flat line."""
    tiers = [(t['name'], t['points_required']) for t in sorted(ambassador_tiers, key=lambda x: x['points_required'])]
    # next-tier progress (points toward the next threshold above current)
    max_pts = tiers[-1][1] if tiers else 3000
    next_threshold = next((t for _, t in tiers if t > points), max_pts)
    prev_threshold = max([t for _, t in tiers if t <= points] or [0])
    span = max(next_threshold - prev_threshold, 1)
    tier_progress = min(round((points - prev_threshold) / span * 100), 100)

    now = datetime.utcnow()
    week_keys = [(now - timedelta(weeks=i)).strftime("%Y-%W") for i in range(7, -1, -1)]
    week_labels = [(now - timedelta(weeks=i)).strftime("%b %d") for i in range(7, -1, -1)]
    earned_by_week = {k: 0 for k in week_keys}
    try:
        if supabase and user.get('id'):
            claims = supabase.table('ambassador_claims').select('created_at, status, ambassador_tasks(point_value)') \
                .eq('ambassador_id', user['id']).eq('status', 'approved').execute().data
            for c in (claims or []):
                created = c.get('created_at') or ''
                try:
                    wk = datetime.fromisoformat(created.replace('Z', '')).strftime("%Y-%W") if created else None
                except Exception:
                    wk = None
                if wk in earned_by_week:
                    earned_by_week[wk] += ((c.get('ambassador_tasks') or {}).get('point_value') or 0)
    except Exception:
        pass
    # cumulative trend
    cumulative, running = [], 0
    for k in week_keys:
        running += earned_by_week[k]
        cumulative.append(running)

    return {
        "tier_progress": tier_progress,
        "tier_next_name": next((n for n, t in tiers if t > points), "Star Ambassador"),
        "tier_points_to_next": max(next_threshold - points, 0),
        "trend_labels": week_labels,
        "trend_values": cumulative,
        "breakdown_labels": ["Points Earned", "Referrals"],
        "breakdown_values": [points, referrals],
    }

