
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from api.config import supabase, limiter
from api.utils.email import send_system_email, send_ambassador_email
import random, string, uuid, json, os
from datetime import datetime, timedelta
from api.routes.ambassador import parse_shipping_address
from api.utils.batch import calculate_next_start_date, parse_track_duration
from api.utils.submissions import parse_submission_deliverables

dashboard_bp = Blueprint('dashboard', __name__)

def fix_gdrive_url(url):
    if not url: return url
    if "drive.google.com/file/d/" in url:
        try:
            file_id = url.split("/d/")[1].split("/")[0]
            return f"https://lh3.googleusercontent.com/d/{file_id}"
        except:
            return url
    return url

@dashboard_bp.route('/dashboard-intern')
def dashboard_intern():
    try:
        user_role = str(session.get('role', '')).lower()
        if user_role not in ['intern', 'intern + ambassador']: return redirect('/login')

        # Auto-reconcile PhonePe status if returning from payment redirect
        return_txn_id = request.args.get('txn_id')
        if return_txn_id:
            try:
                from api.utils.phonepe import check_phonepe_status, fulfill_payment_success
                st = check_phonepe_status(return_txn_id)
                if st.get("success"):
                    fulfill_payment_success(return_txn_id)
            except Exception as pe_err:
                print(f"Auto-sync on return error for txn {return_txn_id}: {pe_err}")
    
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
        now = datetime.utcnow()

        active_enrolls = []
        try:
            active_enrolls = supabase.table('enrollments').select('*, programs(*)').eq('user_id', u_id).in_('status', ['active', 'resubmit']).execute().data or []
        except Exception:
            try:
                active_enrolls = supabase.table('enrollments').select('*').eq('user_id', u_id).in_('status', ['active', 'resubmit']).execute().data or []
            except Exception:
                active_enrolls = []

        pending_enrolls = []
        try:
            pending_enrolls = supabase.table('enrollments').select('*, programs(*)').eq('user_id', u_id).eq('status', 'pending').order('created_at', desc=True).execute().data or []
        except Exception:
            try:
                pending_enrolls = supabase.table('enrollments').select('*').eq('user_id', u_id).eq('status', 'pending').order('created_at', desc=True).execute().data or []
            except Exception:
                try:
                    pending_enrolls = supabase.table('enrollments').select('*').eq('user_id', u_id).eq('status', 'pending').execute().data or []
                except Exception:
                    pending_enrolls = []

        active_projects = []
        next_batch_date = calculate_next_start_date(now)
        next_batch_date_str = next_batch_date.strftime("%B %d, %Y")

        pending_projects = []
        for pe in pending_enrolls:
            p = pe.get('programs') or {}
            if not p and pe.get('program_id'):
                try:
                    clean_pid = int(pe['program_id']) if str(pe['program_id']).isdigit() else pe['program_id']
                    p_res = supabase.table('programs').select('*').eq('id', clean_pid).execute()
                    if p_res and p_res.data:
                        p = p_res.data[0]
                    else:
                        p_res = supabase.table('programs').select('*').eq('id', str(pe['program_id'])).execute()
                        if p_res and p_res.data:
                            p = p_res.data[0]
                except Exception:
                    pass
            _, track_display = parse_track_duration(pe.get('track_level'))
            pending_projects.append({
                'program_title': p.get('title', 'Architecture Internship'),
                'description': p.get('short_description', 'Virtual Architecture Internship Mandate'),
                'track_level': track_display,
                'enrollment_id': pe['enrollment_id'],
                'status': 'pending',
                'projected_start_date': next_batch_date_str
            })

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

        for e in active_enrolls:
            raw_start = e.get('start_date') or e.get('created_at')
            try:
                start_dt = datetime.fromisoformat(raw_start.replace('Z', '+00:00')) if raw_start else now
            except:
                start_dt = now

            # Ensure naive datetime for math
            start_dt = start_dt.replace(tzinfo=None)
            duration_days, track_display = parse_track_duration(e.get('track_level'))

            if e['status'] == 'resubmit':
                duration_days = 1

            end_dt = start_dt + timedelta(days=duration_days)
            is_started = (now >= start_dt)
            days_until_start = max(0, (start_dt - now).days)
            start_date_str = start_dt.strftime("%B %d, %Y")
            end_date_str = end_dt.strftime("%B %d, %Y")

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

            prog = e.get('programs') or {}
            if not prog and e.get('program_id'):
                try:
                    p_res = supabase.table('programs').select('*').eq('id', e['program_id']).execute()
                    if p_res and p_res.data:
                        prog = p_res.data[0]
                except Exception:
                    pass

            track = e.get('track_level', '').lower()
            if track.startswith('custom_'):
                specs_link = prog.get('custom_specs', '#')
                amount_due = prog.get('custom_price', 0)
            elif track.isdigit():
                tracks_json = prog.get('tracks') or []
                matched = next((t for t in tracks_json if str(t.get('months')) == track), None)
                if matched:
                    specs_link = matched.get('specs', '#')
                    amount_due = matched.get('price', 0)
                else:
                    specs_link = '#'
                    amount_due = 0
            else:
                specs_link = prog.get(f"specs_{track}", '#')
                amount_due = prog.get(f"price_{track}", 0)

            active_projects.append({
                'program_title': prog.get('title', 'Architecture Internship'), 
                'description': prog.get('short_description', ''), 
                'track_level': track_display, 
                'enrollment_id': e['enrollment_id'], 
                'specs_link': specs_link, 
                'amount_due': amount_due,
                'status': e['status'],
                'remaining_days': remaining_days,
                'remaining_hours': remaining_hours,
                'duration_days': duration_days,
                'is_started': is_started,
                'days_until_start': days_until_start,
                'start_date_str': start_date_str,
                'end_date_str': end_date_str
            })
        offered = supabase.table('programs').select('*').eq('is_active', True).execute().data
        offered_programs_grouped = {}
        for p in offered:
            p['image_url'] = fix_gdrive_url(p.get('image_url'))
            if not p.get('tracks'):
                fallback = []
                if p.get('offer_1m'): fallback.append({'months': 1, 'price': p.get('price_beginner', 0), 'specs': p.get('specs_beginner', '')})
                if p.get('offer_2m'): fallback.append({'months': 2, 'price': p.get('price_intermediate', 0), 'specs': p.get('specs_intermediate', '')})
                if p.get('offer_3m'): fallback.append({'months': 3, 'price': p.get('price_expert', 0), 'specs': p.get('specs_expert', '')})
                p['tracks'] = fallback

            cat = p.get('category') or 'General'
            if cat not in offered_programs_grouped:
                offered_programs_grouped[cat] = []
            offered_programs_grouped[cat].append(p)
    
        completed_projects = []
        graded_enrolls = supabase.table('enrollments').select('*, programs(title)').eq('user_id', u_id).in_('status', ['graded', 'submitted', 'certified', 'completed', 'graduated']).execute().data
        for e in graded_enrolls:
            track = e.get('track_level', '').lower()
            if track.startswith('custom_'):
                try: months = int(track.split('_')[1])
                except: months = 1
                track_display = f"{months} Months" if months > 1 else "1 Month"
            elif track.isdigit():
                months = int(track)
                track_display = f"{months} Months" if months > 1 else "1 Month"
            else:
                track_display = {'beginner': '1 Month', 'intermediate': '2 Months', 'expert': '3 Months'}.get(track, e.get('track_level', '').title())

            sub = supabase.table('submissions').select('*').eq('enrollment_id', e['enrollment_id']).execute().data
            if sub:
                s = sub[0]
                completed_projects.append({'score': s.get('score'), 'program_title': e['programs']['title'], 'track_level': track_display, 'enrollment_id': e['enrollment_id'], 'evaluated_date': s.get('evaluated_at', '').split('T')[0] if s.get('evaluated_at') else 'Pending', 'certificate_url': s.get('certificate_url'), 'lor_url': s.get('lor_url')})
            else:
                completed_projects.append({'score': e.get('final_score', 100), 'program_title': e['programs']['title'], 'track_level': track_display, 'enrollment_id': e['enrollment_id'], 'evaluated_date': e.get('updated_at', '').split('T')[0] if e.get('updated_at') else 'Pending', 'certificate_url': None, 'lor_url': None})

        # Determine the default active tab: Explore if no active programs, otherwise Workspace.
        requested_tab = request.args.get('active_tab')
        default_tab = requested_tab if requested_tab else ('workspace' if (active_projects or pending_projects) else 'explore')

        _all = supabase.table('system_notifications').select('*').order('created_at', desc=True).limit(2000).execute()
        sys_notifs = []
        for n in (_all.data or []):
            import json
            meta = n.get('metadata')
            if isinstance(meta, str):
                try: meta = json.loads(meta)
                except: meta = {}
            if not meta: meta = {}
            if str(meta.get('target_user_id')) == str(u_id):
                sys_notifs.append(n)
            if len(sys_notifs) >= 30: break

        return render_template('dashboard_intern.html', user_name=session.get('name'), active_projects=active_projects, pending_projects=pending_projects, offered_programs=offered_programs_grouped, completed_projects=completed_projects, ambassador_active=ambassador_active, active_tab=default_tab, user_profile=user_profile, profile_details=profile_details, sys_notifs=sys_notifs)
    except Exception as e:
        import traceback
        return f"<h1>Internal Server Error inside dashboard_intern</h1><pre>{traceback.format_exc()}</pre>", 500


@dashboard_bp.route('/dashboard-mentor')
def dashboard_mentor():
    if str(session.get('role', '')).lower() != 'mentor': return redirect('/login')
    now = datetime.utcnow()
    next_batch_date = calculate_next_start_date(now)
    next_batch_date_str = next_batch_date.strftime("%B %d, %Y")

    # Fetch pending enrollment requests
    pend_enrolls_raw = []
    try:
        pend_enrolls_raw = supabase.table('enrollments').select('*, programs(title, short_description), users(full_name, email, promo_code)').eq('status', 'pending').order('created_at', desc=True).execute().data or []
    except Exception:
        try:
            pend_enrolls_raw = supabase.table('enrollments').select('*').eq('status', 'pending').order('created_at', desc=True).execute().data or []
        except Exception:
            pend_enrolls_raw = []

    pending_enrollments = []
    for pe in pend_enrolls_raw:
        duration_days, track_display = parse_track_duration(pe.get('track_level'))
        u = pe.get('users') or {}
        p = pe.get('programs') or {}

        # Fallback if users relation was not joined
        if not u and pe.get('user_id'):
            try:
                u_res = supabase.table('users').select('full_name, email, promo_code').eq('id', pe['user_id']).execute()
                if u_res and u_res.data:
                    u = u_res.data[0]
            except Exception:
                pass

        # Fallback if programs relation was not joined
        if not p and pe.get('program_id'):
            try:
                clean_pid = int(pe['program_id']) if str(pe['program_id']).isdigit() else pe['program_id']
                p_res = supabase.table('programs').select('title, short_description').eq('id', clean_pid).execute()
                if p_res and p_res.data:
                    p = p_res.data[0]
                else:
                    p_res = supabase.table('programs').select('title, short_description').eq('id', str(pe['program_id'])).execute()
                    if p_res and p_res.data:
                        p = p_res.data[0]
            except Exception:
                pass

        req_dt_str = 'Recent'
        if pe.get('created_at'):
            try:
                req_dt = datetime.fromisoformat(pe['created_at'].replace('Z', '+00:00'))
                req_dt_str = req_dt.strftime("%b %d, %Y")
            except Exception:
                pass

        pending_enrollments.append({
            "id": pe.get('id'),
            "enrollment_id": pe.get('enrollment_id'),
            "student_name": u.get('full_name', 'Student Intern'),
            "student_email": u.get('email', 'N/A'),
            "program_title": p.get('title', 'Architecture Program'),
            "track_display": track_display,
            "duration_days": duration_days,
            "requested_at": req_dt_str,
            "projected_start": next_batch_date_str,
            "college_name": pe.get('college_name', ''),
            "course_name": pe.get('course_name', '')
        })

    # Fetch all submissions with enrollment, program, and user details
    all_subs_raw = supabase.table('submissions').select(
        '*, enrollments(created_at, track_level, status, programs(title), users(full_name, email))'
    ).order('created_at', desc=True).execute().data or []

    ready_to_release_subs = []
    active_cohort_subs = []
    graded_subs = []

    for sub in all_subs_raw:
        parsed_projects = parse_submission_deliverables(sub.get('code_link'), sub.get('defense_link'))
        sub['projects_list'] = parsed_projects
        sub['project_count'] = len(parsed_projects)
        sub['primary_code_link'] = parsed_projects[0]['code_link'] if parsed_projects else (sub.get('code_link') or '')
        sub['primary_defense_link'] = parsed_projects[0]['defense_link'] if parsed_projects else (sub.get('defense_link') or '')

        cert = sub.get('certificate_url') or ''
        e = sub.get('enrollments') or {}
        e_status = e.get('status', '')

        # Check if already officially completed/graded & released
        if cert.startswith('https://') or cert.startswith('failed:') or e_status in ['graded', 'failed']:
            graded_subs.append(sub)
            continue

        # Sub is in review queue (either un-graded or pre-graded / staged)
        raw_start = e.get('created_at')
        try:
            start_dt = datetime.fromisoformat(raw_start.replace('Z', '+00:00')).replace(tzinfo=None) if raw_start else now
        except:
            start_dt = now

        track = (e.get('track_level') or '').lower()
        duration_days = 90 if track == 'expert' else (60 if track == 'intermediate' else 30)
        end_dt = start_dt + timedelta(days=duration_days)

        u = e.get('users') or {}
        p = e.get('programs') or {}
        sub['student_name'] = u.get('full_name', 'Student Intern')
        sub['student_email'] = u.get('email', 'N/A')
        sub['program_title'] = p.get('title', 'Architecture Program')
        sub['track_title'] = (e.get('track_level') or 'Standard').capitalize()
        sub['end_date_str'] = end_dt.strftime('%d %b %Y')
        sub['start_date_str'] = start_dt.strftime('%d %b %Y')
        sub['is_pre_graded'] = (sub.get('score') is not None)
        sub['days_left'] = max(0, (end_dt - now).days)
        sub['days_overdue'] = max(0, (now - end_dt).days)

        if now >= end_dt:
            ready_to_release_subs.append(sub)
        else:
            active_cohort_subs.append(sub)

    pending_subs = active_cohort_subs + ready_to_release_subs

    claims = supabase.table('ambassador_claims').select('id, proof_link, notes, ambassador_id, users(full_name, email), ambassador_tasks(title, point_value)').eq('status', 'pending').execute().data
    pending_claims = [{"id": c['id'], "ambassador_id": c['ambassador_id'], "ambassador_name": c['users']['full_name'], "ambassador_email": c['users']['email'], "task_title": c['ambassador_tasks']['title'], "point_value": c['ambassador_tasks']['point_value'], "proof_link": c['proof_link'], "notes": c['notes']} for c in (claims or [])]
    analytics = build_mentor_analytics(pending_subs, graded_subs, len(pending_claims))

    u_id = session.get('user_id')
    _all = supabase.table('system_notifications').select('*').order('created_at', desc=True).limit(2000).execute()
    sys_notifs = []
    for n in (_all.data or []):
        import json
        meta = n.get('metadata')
        if isinstance(meta, str):
            try: meta = json.loads(meta)
            except: meta = {}
        if not meta: meta = {}
        if str(meta.get('target_user_id')) == str(u_id):
            sys_notifs.append(n)
        if len(sys_notifs) >= 30: break

    return render_template('dashboard_mentor.html', user_name=session.get('name'), 
                           pending_enrollments=pending_enrollments,
                           next_batch_date_str=next_batch_date_str,
                           pending_submissions=pending_subs, 
                           ready_to_release_subs=ready_to_release_subs,
                           active_cohort_subs=active_cohort_subs,
                           overdue_subs=ready_to_release_subs,
                           early_subs=active_cohort_subs,
                           graded_submissions=graded_subs, 
                           pending_claims=pending_claims, 
                           analytics=analytics, 
                           sys_notifs=sys_notifs)


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

    def _in_cutoff(item):
        if not cutoff: return True
        ca = item.get('created_at')
        if not ca: return False
        try:
            dt = datetime.fromisoformat(str(ca).replace('Z', '+00:00')).replace(tzinfo=None)
            return dt >= cutoff
        except Exception:
            return False

    progs = []
    tasks = []
    users = []
    if supabase:
        try:
            progs = supabase.table('programs').select('*').execute().data or []
            for p in progs:
                p['image_url'] = fix_gdrive_url(p.get('image_url'))
        except Exception as e:
            print(f"Error fetching programs: {e}")
            progs = []
        try:
            tasks = supabase.table('ambassador_tasks').select('*').execute().data or []
        except Exception as e:
            print(f"Error fetching tasks: {e}")
            tasks = []
        try:
            users = supabase.table('users').select('*').execute().data or []
        except Exception as e:
            print(f"Error fetching users: {e}")
            users = []

    try:
        all_payments = supabase.table('payments').select('*').execute().data or [] if supabase else []
    except Exception as e:
        print(f"Error fetching payments: {e}")
        all_payments = []

    paid_payments = [
        p for p in all_payments
        if str(p.get('status', '')).strip().lower() in ['paid', 'success', 'completed']
    ]

    try:
        enrollments = supabase.table('enrollments').select('*').execute().data or [] if supabase else []
    except Exception as e:
        print(f"Error fetching enrollments: {e}")
        enrollments = []

    try:
        submissions = supabase.table('submissions').select('*').execute().data or [] if supabase else []
    except Exception as e:
        print(f"Error fetching submissions: {e}")
        submissions = []

    filtered_paid = [p for p in paid_payments if _in_cutoff(p)]
    filtered_enrolls = [e for e in enrollments if _in_cutoff(e)]
    filtered_subs = [s for s in submissions if _in_cutoff(s)]

    earnings = sum([(p.get('amount') or 0) / 100.0 for p in filtered_paid])
    enrolled = len(filtered_enrolls)
    certified = len([s for s in filtered_subs if (s.get('score') or 0) >= 80])
    pend_grading = len([s for s in filtered_subs if s.get('score') is None])

    # Calculate coupon statistics
    coupons = [u for u in users if u.get('role') == 'coupon']
    for c in coupons:
        c_code = (c.get('promo_code') or '').strip().upper()
        c_payments = [p for p in paid_payments if (p.get('applied_promo') or '').strip().upper() == c_code]
        c['usage_count'] = len(c_payments)
        c['revenue_generated'] = sum([(p.get('amount') or 0) / 100.0 for p in c_payments])
        
        referred = []
        for p in c_payments:
            user_match = next((u for u in users if u.get('id') == p.get('user_id')), None)
            if user_match:
                s_details = parse_shipping_address(user_match.get('shipping_address', ''))
                referred.append({
                    "name": user_match.get('full_name') or 'Unknown',
                    "email": user_match.get('email') or 'Unknown',
                    "date": (p.get('created_at') or '')[:10],
                    "college": s_details.get('college_name') or 'Unknown'
                })
        c['referred_users'] = referred
        
    # Calculate ambassador statistics
    all_ambassadors = [u for u in users if str(u.get('role', '')).lower() in ['ambassador', 'intern + ambassador']]
    for a in all_ambassadors:
        a_code = (a.get('promo_code') or '').strip().upper()
        a_payments = [p for p in paid_payments if (p.get('applied_promo') or '').strip().upper() == a_code]
        a['referral_count'] = len(a_payments)
        a_s_details = parse_shipping_address(a.get('shipping_address', ''))
        a['college_name'] = a.get('college_name') or a_s_details.get('college_name') or 'N/A'
        
        referred = []
        for p in a_payments:
            user_match = next((u for u in users if u.get('id') == p.get('user_id')), None)
            if user_match:
                s_details = parse_shipping_address(user_match.get('shipping_address', ''))
                referred.append({
                    "name": user_match.get('full_name') or 'Unknown',
                    "email": user_match.get('email') or 'Unknown',
                    "date": (p.get('created_at') or '')[:10],
                    "college": s_details.get('college_name') or 'Unknown'
                })
        a['referred_users'] = referred
        
    # -----------------------------------------------------------------
    # GRAPHICAL ANALYTICS DATA (Chart.js-ready, JSON-serializable)
    # Built defensively so a missing column never breaks the dashboard.
    # -----------------------------------------------------------------
    analytics = build_admin_analytics(
        progs, users, 
        paid_payments=paid_payments, 
        enrollments=enrollments, 
        coupons=coupons, 
        all_ambassadors=all_ambassadors, 
        submissions=submissions
    )

    # Fetch Dynamic Tiers
    ambassador_tiers = []
    if supabase:
        try:
            amb_tiers_resp = supabase.table('ambassador_tiers').select('*').order('points_required', desc=True).execute()
            ambassador_tiers = amb_tiers_resp.data or []
        except Exception as e:
            print(f"Error fetching tiers: {e}")
            ambassador_tiers = []
    if not ambassador_tiers:
        ambassador_tiers = [
            {"id": 0, "tier_level": 4, "name": "Star Ambassador", "points_required": 3000, "give_certificate": True, "give_lor": True, "benefits_text": "Elite Swag Kit (Mechanical Keyboard & Desk Mat)\nDirect Paid Internship Offer at Virtuole HQ"},
            {"id": 0, "tier_level": 3, "name": "Community Lead", "points_required": 1500, "give_certificate": False, "give_lor": False, "benefits_text": "Premium Virtuole Developer Hoodie"},
            {"id": 0, "tier_level": 2, "name": "Campus Advocate", "points_required": 500, "give_certificate": False, "give_lor": False, "benefits_text": "Exclusive Virtuole Tech Graphic T-Shirt"},
            {"id": 0, "tier_level": 1, "name": "Kickstart", "points_required": 0, "give_certificate": False, "give_lor": False, "benefits_text": "Virtuole branded Lanyard and Die-Cut Stickers"}
        ]
    
    # Fetch subscribers
    subscribers = []
    if supabase:
        try:
            subscribers = supabase.table('subscribers').select('*').order('created_at', desc=True).execute().data or []
        except Exception:
            subscribers = []
        
    prog_dict = {p.get('id'): p for p in progs if p.get('id')}
    advanced_users = []
    
    for u in users:
        s_details = parse_shipping_address(u.get('shipping_address', ''))
        u_enrolls = [e for e in enrollments if e.get('user_id') == u.get('id')]
        
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
                d["program"] = prog_dict.get(e.get('program_id'), {}).get('title', 'Unknown')
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
            dt = datetime.fromisoformat(str(date_str).replace('Z', '+00:00'))
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
            dt = datetime.fromisoformat(str(date_str).replace('Z', '+00:00'))
            user = next((x for x in users if x.get('id') == e.get('user_id')), None)
            u_name = user['full_name'] if user and user.get('full_name') else 'A user'
            prog_title = prog_dict.get(e.get('program_id'), {}).get('title', 'a program')
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
    for u in users:
        s_details = parse_shipping_address(u.get('shipping_address', ''))
        st = s_details.get('state')
        if st and str(st).strip() and str(st).strip().lower() != 'unknown':
            state_counts[st] = state_counts.get(st, 0) + 1
    top_states = sorted(state_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    seven_days_ago = now - timedelta(days=7)
    recent_revenue = 0.0
    for p in paid_payments:
        ca = p.get('created_at')
        if not ca: continue
        try:
            dt = datetime.fromisoformat(str(ca).replace('Z', '+00:00')).replace(tzinfo=None)
            if dt >= seven_days_ago:
                recent_revenue += (p.get('amount') or 0) / 100.0
        except Exception:
            pass
    projected_revenue = (recent_revenue / 7.0) * 30.0 if recent_revenue else 0.0

    sys_notifs = []
    if supabase:
        try:
            result = supabase.table('system_notifications').select('*').order('created_at', desc=True).limit(20).execute()
            sys_notifs = result.data or []
        except BaseException:
            sys_notifs = []

    # Fetch data from Google Sheets webhook
    import requests as _requests
    sheet_webhook_url = os.environ.get('GOOGLE_SHEET_WEBHOOK')
    sheet_feedback = []
    sheet_ambassadors = []
    sheet_webhook_set = bool(sheet_webhook_url)
    if sheet_webhook_url:
        try:
            resp = _requests.get(sheet_webhook_url + '?action=read', timeout=5)
            sheet_data = resp.json()
            raw_feedback = sheet_data.get('feedback', []) or []
            raw_ambassadors = sheet_data.get('ambassadors', []) or []
            for r in raw_feedback:
                if isinstance(r, (list, tuple)) and len(r) >= 5:
                    sheet_feedback.append(list(r[:5]))
                elif isinstance(r, dict):
                    sheet_feedback.append([
                        r.get('date', ''), r.get('name', ''), r.get('email', ''),
                        r.get('subject', ''), r.get('message', '')
                    ])
            for r in raw_ambassadors:
                if isinstance(r, (list, tuple)) and len(r) >= 5:
                    sheet_ambassadors.append(list(r[:5]))
                elif isinstance(r, dict):
                    sheet_ambassadors.append([
                        r.get('date', ''), r.get('name', ''), r.get('email', ''),
                        r.get('college', ''), r.get('motivation', '')
                    ])
        except BaseException as e:
            print(f"Sheet fetch error: {e}")

    # Fallback to Supabase system_notifications if sheet data is empty
    if not sheet_feedback and supabase:
        try:
            fb_notifs = supabase.table('system_notifications').select('*').eq('type', 'feedback').order('created_at', desc=True).limit(50).execute().data or []
            for n in fb_notifs:
                meta = n.get('metadata') or {}
                dt_str = (n.get('created_at') or '')[:10]
                sheet_feedback.append([
                    dt_str,
                    meta.get('name') or n.get('title', '').replace('New Feedback: ', ''),
                    meta.get('email') or '',
                    meta.get('subject') or n.get('title', ''),
                    meta.get('message') or n.get('description', '')
                ])
        except Exception as e:
            print(f"Fallback feedback fetch error: {e}")

    if not sheet_ambassadors and supabase:
        try:
            amb_notifs = supabase.table('system_notifications').select('*').eq('type', 'ambassador').order('created_at', desc=True).limit(50).execute().data or []
            for n in amb_notifs:
                meta = n.get('metadata') or {}
                dt_str = (n.get('created_at') or '')[:10]
                sheet_ambassadors.append([
                    dt_str,
                    meta.get('name') or n.get('title', '').replace('New Ambassador Application: ', ''),
                    meta.get('email') or '',
                    meta.get('college') or n.get('description', '').replace('College: ', ''),
                    meta.get('motivation') or ''
                ])
        except Exception as e:
            print(f"Fallback ambassador fetch error: {e}")

    # Fetch recent transactions for PhonePe live status & reconciliation hub
    recent_transactions = []
    if supabase:
        try:
            tx_resp = supabase.table('payments').select('*').order('created_at', desc=True).limit(30).execute()
            raw_txs = tx_resp.data or []
        except Exception:
            try:
                tx_resp = supabase.table('payments').select('*').limit(30).execute()
                raw_txs = tx_resp.data or []
            except Exception:
                raw_txs = []
        user_map = {u.get('id'): u for u in users if u.get('id')}
        for t in raw_txs:
            u_info = user_map.get(t.get('user_id'), {})
            t['user_name'] = u_info.get('full_name', 'Student')
            t['user_email'] = u_info.get('email', '')
        recent_transactions = raw_txs

    return render_template('dashboard_admin.html', user_name=session.get('name'), total_earnings=round(earnings, 2), total_enrolled=enrolled, total_certified=certified, pending_grading=pend_grading, offered_programs=progs, all_tasks=tasks, user_directory=users, coupons=coupons, all_ambassadors=all_ambassadors, grouped_ambassadors=grouped_ambassadors, ambassador_tiers=ambassador_tiers_asc, active_tab=active_tab, current_filter=timeframe, analytics=analytics, subscribers=subscribers, advanced_users=advanced_users, activity_feed=activity_feed, top_ambassadors=top_ambassadors, top_states=top_states, projected_revenue=round(projected_revenue, 2), sys_notifs=sys_notifs, sheet_feedback=sheet_feedback, sheet_ambassadors=sheet_ambassadors, sheet_webhook_set=sheet_webhook_set, recent_transactions=recent_transactions)



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


def build_admin_analytics(programs, users, paid_payments=None, enrollments=None, coupons=None, all_ambassadors=None, submissions=None):
    """Aggregate live Supabase data into Chart.js-ready series for the admin
    Platform Analytics tab. Every block is wrapped so an absent table/column
    degrades gracefully."""
    now = datetime.utcnow()

    # ---- 30-day daily buckets for revenue + enrollments (line/area) ----
    day_keys = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29, -1, -1)]
    day_labels = [(now - timedelta(days=i)).strftime("%b %d") for i in range(29, -1, -1)]
    revenue_by_day = {k: 0.0 for k in day_keys}
    enroll_by_day = {k: 0 for k in day_keys}

    if paid_payments is None:
        if supabase:
            try:
                raw_paid = supabase.table('payments').select('amount, created_at, status, applied_promo').execute().data or []
                paid_payments = [p for p in raw_paid if str(p.get('status', '')).strip().lower() in ['paid', 'success', 'completed']]
            except Exception:
                paid_payments = []
        else:
            paid_payments = []

    for p in (paid_payments or []):
        key = str(p.get('created_at') or '')[:10]
        if key in revenue_by_day:
            revenue_by_day[key] += (p.get('amount') or 0) / 100.0

    if enrollments is None:
        if supabase:
            try:
                enrollments = supabase.table('enrollments').select('id, created_at, program_id').execute().data or []
            except Exception:
                enrollments = []
        else:
            enrollments = []

    for e in (enrollments or []):
        key = str(e.get('created_at') or '')[:10]
        if key in enroll_by_day:
            enroll_by_day[key] += 1

    # ---- Role distribution (doughnut) ----
    role_counts = {}
    for u in (users or []):
        role = str(u.get('role') or 'intern').strip().lower()
        role_counts[role] = role_counts.get(role, 0) + 1
    role_labels = [r.title() for r in role_counts.keys()]
    role_values = list(role_counts.values())

    # ---- Certification outcomes (bar) ----
    certified = failed = pending = 0
    if submissions is None:
        if supabase:
            try:
                submissions = supabase.table('submissions').select('score').execute().data or []
            except Exception:
                submissions = []
        else:
            submissions = []

    for s in submissions:
        score = s.get('score')
        if score is None:
            pending += 1
        elif score >= 80:
            certified += 1
        else:
            failed += 1

    # ---- Program popularity: enrollments per program (horizontal bar) ----
    prog_titles = {p['id']: p.get('title', 'Untitled') for p in (programs or [])}
    prog_counts = {p['id']: 0 for p in (programs or [])}
    for e in enrollments:
        pid = e.get('program_id')
        if pid in prog_counts:
            prog_counts[pid] += 1
    ranked = sorted(prog_counts.items(), key=lambda kv: kv[1], reverse=True)[:8]

    # ---- Cumulative growth: running totals of enrollments + revenue ----
    oldest_30d_key = day_keys[0]
    base_enroll = sum([1 for e in enrollments if str(e.get('created_at') or '')[:10] < oldest_30d_key])
    base_revenue = sum([(p.get('amount') or 0) / 100.0 for p in paid_payments if str(p.get('created_at') or '')[:10] < oldest_30d_key])

    cum_enroll, cum_revenue = [], []
    run_e, run_r = base_enroll, base_revenue
    for k in day_keys:
        run_e += enroll_by_day[k]
        run_r += revenue_by_day[k]
        cum_enroll.append(run_e)
        cum_revenue.append(round(run_r, 2))

    # ---- Coupon ROI Tracker ----
    promo_revenue = {}
    for c in (coupons or []):
        code = (c.get('promo_code') or '').strip().upper()
        if code:
            promo_revenue[code] = round(float(c.get('revenue_generated') or 0.0), 2)

    for a in (all_ambassadors or []):
        code = (a.get('promo_code') or '').strip().upper()
        if code:
            a_rev = sum([(p.get('amount') or 0) / 100.0 for p in paid_payments if (p.get('applied_promo') or '').strip().upper() == code])
            if a_rev > 0 or code not in promo_revenue:
                promo_revenue[code] = max(promo_revenue.get(code, 0.0), round(a_rev, 2))

    for p in paid_payments:
        code = (p.get('applied_promo') or '').strip().upper()
        if code and code not in promo_revenue:
            p_rev = sum([(px.get('amount') or 0) / 100.0 for px in paid_payments if (px.get('applied_promo') or '').strip().upper() == code])
            promo_revenue[code] = round(p_rev, 2)

    sorted_promos = sorted(promo_revenue.items(), key=lambda kv: kv[1], reverse=True)[:15]
    coupon_labels = [kv[0] for kv in sorted_promos]
    coupon_values = [kv[1] for kv in sorted_promos]

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
        "coupon_labels": coupon_labels,
        "coupon_values": coupon_values,
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
    
    _all = supabase.table('system_notifications').select('*').order('created_at', desc=True).limit(2000).execute()
    sys_notifs = []
    for n in (_all.data or []):
        import json
        meta = n.get('metadata')
        if isinstance(meta, str):
            try: meta = json.loads(meta)
            except: meta = {}
        if not meta: meta = {}
        if str(meta.get('target_user_id')) == str(session.get('user_id')):
            sys_notifs.append(n)
        if len(sys_notifs) >= 30: break

    return render_template('dashboard_ambassador.html', ambassador_name=session.get('name'), valid_until_date=u['ambassador_expiry'].split('T')[0] if u.get('ambassador_expiry') else 'N/A', total_points=pts, current_tier_name=tier_name, total_referrals=refs, promo_code=u.get('promo_code', 'Pending'), amb_id=u.get('public_id', 'Pending'), available_tasks=tasks, task_claims=task_claims, shipping_details=shipping_details, analytics=analytics, can_switch_intern=(user_role == 'intern + ambassador'), ambassador_tiers=ambassador_tiers, active_tab=requested_tab, sys_notifs=sys_notifs)


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

@dashboard_bp.route('/delete-notification/<notif_id>', methods=['POST'])
@dashboard_bp.route('/api/delete-notification/<notif_id>', methods=['POST'])
def delete_notification(notif_id):
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    try:
        user_role = str(session.get('role', '')).lower()
        
        if user_role == 'admin':
            # Admin can delete any notification
            supabase.table('system_notifications').delete().eq('id', notif_id).execute()
            return jsonify({"success": True})
        else:
            # User can only delete their own notifications
            notif = supabase.table('system_notifications').select('metadata').eq('id', notif_id).execute().data
            if not notif:
                return jsonify({"success": False, "error": "Notification not found"}), 404
                
            metadata = notif[0].get('metadata', {})
            if str(metadata.get('target_user_id')) != str(session.get('user_id')):
                return jsonify({"success": False, "error": "Unauthorized to delete this notification"}), 403
                
            supabase.table('system_notifications').delete().eq('id', notif_id).execute()
            return jsonify({"success": True})
            
    except Exception as e:
        print(f"Error deleting notification: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
