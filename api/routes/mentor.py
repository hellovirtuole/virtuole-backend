
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from api.config import supabase, limiter
from api.utils.email import send_system_email, send_ambassador_email
import random, string, uuid, json
from datetime import datetime, timedelta
from api.utils.notifications import send_notification
from api.utils.batch import calculate_next_start_date, parse_track_duration

mentor_bp = Blueprint('mentor', __name__)



@mentor_bp.route('/grade-submission', methods=['POST'])
@mentor_bp.route('/api/grade-submission', methods=['POST'])
def grade_submission():
    if str(session.get('role', '')).lower() != 'mentor': return redirect('/login')
    sub_id = request.form.get('submission_id')
    enrollment_id = request.form.get('enrollment_id')
    score = int(request.form.get('score'))
    feedback = request.form.get('feedback', 'No specific feedback.')
    action_type = request.form.get('action_type', 'stage') # 'stage' (save marks) or 'release' (approve & send)
    
    enroll_data = supabase.table('enrollments').select('*, programs(title, short_description)').eq('enrollment_id', enrollment_id).execute().data[0]
    student = supabase.table('users').select('email', 'full_name').eq('id', enroll_data['user_id']).execute().data[0]
    
    if score >= 80:
        if action_type == 'stage':
            # Save marks without releasing certificate or sending completion email yet
            db_updates = {
                "score": score,
                "evaluated_at": datetime.utcnow().isoformat()
            }
            supabase.table('submissions').update(db_updates).eq('id', sub_id).execute()
            send_notification('mentor', session['user_id'], 'staged_evaluation', 'Marks Staged', f"Marks ({score}%) saved for {student['full_name']} ({enrollment_id}). Awaiting deadline release.")
            return redirect(url_for('dashboard.dashboard_mentor', tab='queue', staged=1))

        # Action is 'release' -> Issue credentials & email student immediately
        db_updates = {
            "score": score, 
            "certificate_url": f"https://www.virtuole.in/verify-credential?credential_id={enrollment_id}", 
            "evaluated_at": datetime.utcnow().isoformat()
        }
        if score == 100:
            db_updates["lor_url"] = f"https://www.virtuole.in/verify-credential?credential_id={enrollment_id}"
            body_msg = f"Congratulations {student['full_name']}! You can view your Certificate and Elite LoR here: https://www.virtuole.in/verify-credential?credential_id={enrollment_id}"
        else:
            body_msg = f"Congratulations {student['full_name']}! You can view your Certificate here: https://www.virtuole.in/verify-credential?credential_id={enrollment_id}"
            
        supabase.table('submissions').update(db_updates).eq('id', sub_id).execute()
        supabase.table('enrollments').update({"status": "graded"}).eq('enrollment_id', enrollment_id).execute()
        try:
            send_system_email(student['email'], "Certification Passed - Virtuole", body_msg)
        except Exception as mail_err:
            print(f"Error emailing student: {mail_err}")
        
        send_notification('intern', enroll_data['user_id'], 'certification', 'Certified', f"Congratulations! You passed {enroll_data['programs']['title']} with a score of {score}.")
        send_notification('mentor', session['user_id'], 'certification', 'Intern Certified', f"You have certified {student['full_name']} for {enroll_data['programs']['title']}.")
        return redirect(url_for('dashboard.dashboard_mentor', tab='queue', released=1))
    else:
        # Check if they are already in 'resubmit' status (this was their second try)
        if enroll_data.get('status') == 'resubmit':
            # They failed their second attempt. Record failure reason.
            supabase.table('enrollments').update({"status": "failed"}).eq('enrollment_id', enrollment_id).execute()
            supabase.table('submissions').update({
                "score": score,
                "certificate_url": f"failed:{feedback}",
                "evaluated_at": datetime.utcnow().isoformat()
            }).eq('id', sub_id).execute()
            
            failure_email_body = f"Dear {student['full_name']},\n\nYour resubmission scored {score}%. Feedback: \"{feedback}\"\nUnfortunately, this means you did not secure the passing grade of 80% and the credential cannot be issued."
            try:
                send_system_email(student['email'], "Certification Failed", failure_email_body)
            except:
                pass
        else:
            # First failure. Give them 24 hours to resubmit.
            supabase.table('enrollments').update({
                "status": "resubmit", 
                "created_at": datetime.utcnow().isoformat() # Start 24h countdown
            }).eq('enrollment_id', enrollment_id).execute()
            
            # Delete old submission to allow inserting a new one
            supabase.table('submissions').delete().eq('id', sub_id).execute() 
            
            failure_email_body = f"Dear {student['full_name']},\n\nYour submission scored {score}%. Feedback: \"{feedback}\"\nYou have exactly 24 hours to resubmit your project in your dashboard."
            try:
                send_system_email(student['email'], "ACTION REQUIRED: Submission Failed", failure_email_body)
            except:
                pass
            send_notification('intern', enroll_data['user_id'], 'resubmit', 'Resubmission Required', f"Your submission for {enroll_data['programs']['title']} scored {score}/100. Resubmit within 24h.")
            
        return redirect(url_for('dashboard.dashboard_mentor', tab='queue'))


@mentor_bp.route('/release-submission', methods=['POST'])
@mentor_bp.route('/api/release-submission', methods=['POST'])
def release_submission():
    if str(session.get('role', '')).lower() != 'mentor':
        if request.is_json: return jsonify({"success": False, "error": "Unauthorized"}), 401
        return redirect('/login')

    data = request.get_json(silent=True) if request.is_json else request.form
    sub_id = data.get('submission_id')
    enrollment_id = data.get('enrollment_id')

    if not sub_id or not enrollment_id:
        if request.is_json: return jsonify({"success": False, "error": "Missing parameters"}), 400
        return redirect(url_for('dashboard.dashboard_mentor', tab='queue'))

    sub_res = supabase.table('submissions').select('*').eq('id', sub_id).execute().data
    if not sub_res:
        if request.is_json: return jsonify({"success": False, "error": "Submission not found"}), 404
        return redirect(url_for('dashboard.dashboard_mentor', tab='queue'))

    sub = sub_res[0]
    score = sub.get('score')
    if score is None:
        if request.is_json: return jsonify({"success": False, "error": "Submission has not been evaluated yet"}), 400
        return redirect(url_for('dashboard.dashboard_mentor', tab='queue'))

    enroll_data = supabase.table('enrollments').select('*, programs(title, short_description)').eq('enrollment_id', enrollment_id).execute().data[0]
    student = supabase.table('users').select('email', 'full_name').eq('id', enroll_data['user_id']).execute().data[0]

    db_updates = {
        "certificate_url": f"https://www.virtuole.in/verify-credential?credential_id={enrollment_id}",
        "evaluated_at": datetime.utcnow().isoformat()
    }
    if score == 100:
        db_updates["lor_url"] = f"https://www.virtuole.in/verify-credential?credential_id={enrollment_id}"
        body_msg = f"Congratulations {student['full_name']}! You can view your Certificate and Elite LoR here: https://www.virtuole.in/verify-credential?credential_id={enrollment_id}"
    else:
        body_msg = f"Congratulations {student['full_name']}! You can view your Certificate here: https://www.virtuole.in/verify-credential?credential_id={enrollment_id}"

    supabase.table('submissions').update(db_updates).eq('id', sub_id).execute()
    supabase.table('enrollments').update({"status": "graded"}).eq('enrollment_id', enrollment_id).execute()
    try:
        send_system_email(student['email'], "Certification Passed - Virtuole", body_msg)
    except Exception as e:
        print(f"Error emailing release certificate to {student['email']}: {e}")

    send_notification('intern', enroll_data['user_id'], 'certification', 'Certified', f"Congratulations! You passed {enroll_data['programs']['title']} with a score of {score}.")
    send_notification('mentor', session['user_id'], 'certification', 'Intern Certified', f"You have certified {student['full_name']} for {enroll_data['programs']['title']}.")

    if request.is_json:
        return jsonify({"success": True, "message": f"Successfully released credentials to {student['full_name']}."})

    return redirect(url_for('dashboard.dashboard_mentor', tab='queue', released=1))


@mentor_bp.route('/batch-release-submissions', methods=['POST'])
@mentor_bp.route('/api/batch-release-submissions', methods=['POST'])
def batch_release_submissions():
    if str(session.get('role', '')).lower() != 'mentor':
        if request.is_json: return jsonify({"success": False, "error": "Unauthorized"}), 401
        return redirect('/login')

    data = request.get_json(silent=True) if request.is_json else request.form
    sub_ids = data.get('submission_ids')
    if isinstance(sub_ids, str):
        sub_ids = [s.strip() for s in sub_ids.split(',') if s.strip()]
    elif not isinstance(sub_ids, list):
        sub_ids = []

    now = datetime.utcnow()
    if not sub_ids:
        all_subs = supabase.table('submissions').select('id, enrollment_id, score, certificate_url, enrollments(created_at, track_level)').gte('score', 80).execute().data or []
        ready_ids = []
        for s in all_subs:
            cert = s.get('certificate_url') or ''
            if cert.startswith('https://') or cert.startswith('failed:'):
                continue
            e = s.get('enrollments') or {}
            raw_start = e.get('created_at')
            try:
                start_dt = datetime.fromisoformat(raw_start.replace('Z', '+00:00')).replace(tzinfo=None) if raw_start else now
            except:
                start_dt = now
            duration_days, _ = parse_track_duration(e.get('track_level'))
            end_dt = start_dt + timedelta(days=duration_days)
            if now >= end_dt:
                ready_ids.append(s['id'])
        sub_ids = ready_ids

    released_count = 0
    for sid in sub_ids:
        try:
            sub_res = supabase.table('submissions').select('*').eq('id', sid).execute().data
            if not sub_res: continue
            sub = sub_res[0]
            cert = sub.get('certificate_url') or ''
            if cert.startswith('https://') or cert.startswith('failed:'): continue
            score = sub.get('score')
            if score is None or score < 80: continue

            enrollment_id = sub['enrollment_id']
            enroll_data = supabase.table('enrollments').select('*, programs(title, short_description)').eq('enrollment_id', enrollment_id).execute().data[0]
            student = supabase.table('users').select('email', 'full_name').eq('id', enroll_data['user_id']).execute().data[0]

            db_updates = {
                "certificate_url": f"https://www.virtuole.in/verify-credential?credential_id={enrollment_id}",
                "evaluated_at": now.isoformat()
            }
            if score == 100:
                db_updates["lor_url"] = f"https://www.virtuole.in/verify-credential?credential_id={enrollment_id}"
                body_msg = f"Congratulations {student['full_name']}! You can view your Certificate and Elite LoR here: https://www.virtuole.in/verify-credential?credential_id={enrollment_id}"
            else:
                body_msg = f"Congratulations {student['full_name']}! You can view your Certificate here: https://www.virtuole.in/verify-credential?credential_id={enrollment_id}"

            supabase.table('submissions').update(db_updates).eq('id', sid).execute()
            supabase.table('enrollments').update({"status": "graded"}).eq('enrollment_id', enrollment_id).execute()
            try:
                send_system_email(student['email'], "Certification Passed - Virtuole", body_msg)
            except:
                pass
            send_notification('intern', enroll_data['user_id'], 'certification', 'Certified', f"Congratulations! You passed {enroll_data['programs']['title']} with a score of {score}.")
            released_count += 1
        except Exception as inner_e:
            print(f"Error in batch release for sub {sid}: {inner_e}")

    if request.is_json:
        return jsonify({"success": True, "count": released_count, "message": f"Successfully approved and released {released_count} certificate(s)!"})

    return redirect(url_for('dashboard.dashboard_mentor', tab='queue', released_batch=released_count))


@mentor_bp.route('/evaluate-task', methods=['POST'])
@mentor_bp.route('/api/evaluate-task', methods=['POST'])
def evaluate_task():
    if str(session.get('role', '')).lower() != 'mentor': return redirect('/login')
    claim_id = request.form.get('claim_id')
    action = request.form.get('action') 
    claim_data = supabase.table('ambassador_claims').select('ambassador_id, users(email, full_name)').eq('id', claim_id).execute().data[0]
    
    if action == 'approve':
        pts = int(request.form.get('point_value'))
        supabase.table('ambassador_claims').update({"status": "approved"}).eq('id', claim_id).execute()
        curr_pts = supabase.table('users').select('total_points').eq('id', claim_data['ambassador_id']).execute().data[0]['total_points'] or 0
        supabase.table('users').update({"total_points": curr_pts + pts}).eq('id', claim_data['ambassador_id']).execute()
        send_notification('ambassador', claim_data['ambassador_id'], 'points_added', 'Task Approved!', f"Great job! +{pts} Points added.")
    elif action == 'reject':
        supabase.table('ambassador_claims').update({"status": "rejected"}).eq('id', claim_id).execute()
        send_notification('ambassador', claim_data['ambassador_id'], 'task_rejected', 'Task Proof Rejected', "Your task proof could not be verified.")
    return redirect(url_for('dashboard.dashboard_mentor'))


def _process_single_enrollment_acceptance(e, mentor_user_id):
    enrollment_id = e.get('enrollment_id')
    student = e.get('users') or {}
    if not student and e.get('user_id'):
        try:
            u_res = supabase.table('users').select('*').eq('id', e['user_id']).execute()
            if u_res and u_res.data:
                student = u_res.data[0]
        except Exception:
            pass

    prog = e.get('programs') or {}
    if not prog and e.get('program_id'):
        try:
            clean_pid = int(e['program_id']) if str(e['program_id']).isdigit() else e['program_id']
            p_res = supabase.table('programs').select('*').eq('id', clean_pid).execute()
            if p_res and p_res.data:
                prog = p_res.data[0]
            else:
                p_res = supabase.table('programs').select('*').eq('id', str(e['program_id'])).execute()
                if p_res and p_res.data:
                    prog = p_res.data[0]
        except Exception:
            pass

    if not prog:
        prog = {"title": "Virtual Architecture Internship", "short_description": "Virtual Architecture Internship Mandate"}

    now = datetime.utcnow()
    # Batch date calculation: upcoming 1st, 10th, or 20th
    start_dt = calculate_next_start_date(now)
    duration_days, track_display = parse_track_duration(e.get('track_level'))
    end_dt = start_dt + timedelta(days=duration_days)

    start_date_str = start_dt.strftime("%B %d, %Y")
    end_date_str = end_dt.strftime("%B %d, %Y")
    issue_date_str = now.strftime("%B %d, %Y")

    # Update enrollment status to active and start timestamp
    update_payload = {
        "status": "active",
        "created_at": start_dt.isoformat()
    }
    try:
        supabase.table('enrollments').update({**update_payload, "start_date": start_dt.isoformat()}).eq('enrollment_id', enrollment_id).execute()
    except Exception:
        supabase.table('enrollments').update(update_payload).eq('enrollment_id', enrollment_id).execute()

    # Generate official offer letter
    html_offer = render_template(
        'docs/offer_letter.html',
        name=student.get('full_name', 'Intern'),
        date=start_date_str,
        issue_date=issue_date_str,
        program_title=prog.get('title', 'Virtual Architecture Program'),
        track_level=track_display,
        duration=track_display,
        enroll_id=enrollment_id,
        project_details=prog.get('short_description', 'Virtual Architecture Internship'),
        duration_days=duration_days,
        end_date=end_date_str
    )

    # Email offer letter to the intern
    if student.get('email'):
        try:
            send_system_email(student['email'], f"Official Internship Offer Letter - Virtuole ({prog.get('title')})", html_offer, is_html=True)
        except Exception as mail_err:
            print(f"Error sending offer email to {student.get('email')}: {mail_err}")

    # In-app notifications
    try:
        send_notification('intern', e.get('user_id'), 'enrollment_accepted', 'Enrollment Approved!', f"Your application for {prog.get('title')} has been accepted by your mentor! Your batch starts on {start_date_str}. Official offer letter has been emailed to you.")
        if mentor_user_id:
            send_notification('mentor', mentor_user_id, 'enrollment_accepted', 'Request Approved', f"You accepted {student.get('full_name', 'Intern')} for {prog.get('title')}. Batch start: {start_date_str}.")
    except Exception as notif_err:
        print(f"Error sending notifications for {enrollment_id}: {notif_err}")

    return True


@mentor_bp.route('/accept-enrollment', methods=['POST'])
@mentor_bp.route('/api/accept-enrollment', methods=['POST'])
def accept_enrollment():
    if str(session.get('role', '')).lower() != 'mentor':
        return redirect('/login')

    enrollment_id = request.form.get('enrollment_id')
    if not enrollment_id:
        return redirect(url_for('dashboard.dashboard_mentor'))

    enroll_record = None
    try:
        enroll_query = supabase.table('enrollments').select('*, programs(*), users(*)').eq('enrollment_id', enrollment_id).execute()
        if enroll_query and enroll_query.data:
            enroll_record = enroll_query.data[0]
    except Exception:
        pass

    if not enroll_record:
        try:
            enroll_query = supabase.table('enrollments').select('*').eq('enrollment_id', enrollment_id).execute()
            if enroll_query and enroll_query.data:
                enroll_record = enroll_query.data[0]
        except Exception:
            pass

    if not enroll_record:
        return redirect(url_for('dashboard.dashboard_mentor'))

    _process_single_enrollment_acceptance(enroll_record, session.get('user_id'))
    return redirect(url_for('dashboard.dashboard_mentor', tab='enrollments', batch_success=1))


@mentor_bp.route('/batch-accept-enrollments', methods=['POST'])
@mentor_bp.route('/api/batch-accept-enrollments', methods=['POST'])
def batch_accept_enrollments():
    if str(session.get('role', '')).lower() != 'mentor':
        if request.is_json:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return redirect('/login')

    data = request.get_json(silent=True) if request.is_json else request.form
    all_pending = False
    id_list = []

    if data:
        all_pending = str(data.get('all_pending', '')).lower() in ['true', '1', 'yes']
        raw_ids = data.get('enrollment_ids')
        if isinstance(raw_ids, list):
            id_list = [str(x).strip() for x in raw_ids if str(x).strip()]
        elif isinstance(raw_ids, str):
            id_list = [x.strip() for x in raw_ids.split(',') if x.strip()]

    mentor_user_id = session.get('user_id')
    processed_count = 0

    records = []
    if all_pending:
        try:
            pending_query = supabase.table('enrollments').select('*, programs(*), users(*)').eq('status', 'pending').execute()
            records = pending_query.data or []
        except Exception:
            try:
                pending_query = supabase.table('enrollments').select('*').eq('status', 'pending').execute()
                records = pending_query.data or []
            except Exception:
                records = []
    elif id_list:
        try:
            records_query = supabase.table('enrollments').select('*, programs(*), users(*)').in_('enrollment_id', id_list).execute()
            records = records_query.data or []
        except Exception:
            try:
                records_query = supabase.table('enrollments').select('*').in_('enrollment_id', id_list).execute()
                records = records_query.data or []
            except Exception:
                records = []
    else:
        if request.is_json:
            return jsonify({"success": False, "error": "No enrollments specified."}), 400
        return redirect(url_for('dashboard.dashboard_mentor', tab='enrollments'))

    for record in records:
        try:
            _process_single_enrollment_acceptance(record, mentor_user_id)
            processed_count += 1
        except Exception as e:
            print(f"Error in batch processing enrollment {record.get('enrollment_id')}: {e}")

    if request.is_json:
        return jsonify({
            "success": True,
            "count": processed_count,
            "message": f"Successfully approved {processed_count} intern enrollment request(s)."
        })

    return redirect(url_for('dashboard.dashboard_mentor', tab='enrollments', batch_success=processed_count))


@mentor_bp.route('/batch-evaluate-tasks', methods=['POST'])
@mentor_bp.route('/api/batch-evaluate-tasks', methods=['POST'])
def batch_evaluate_tasks():
    if str(session.get('role', '')).lower() != 'mentor':
        if request.is_json:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return redirect('/login')

    data = request.get_json(silent=True) if request.is_json else request.form
    action = data.get('action', 'approve')
    all_pending = str(data.get('all_pending', '')).lower() in ['true', '1', 'yes']
    claim_ids = data.get('claim_ids')
    if isinstance(claim_ids, str):
        claim_ids = [x.strip() for x in claim_ids.split(',') if x.strip()]
    elif not isinstance(claim_ids, list):
        claim_ids = []

    if all_pending:
        claims_query = supabase.table('ambassador_claims').select('id, ambassador_id, point_value, users(email, full_name)').eq('status', 'pending').execute()
        claims = claims_query.data or []
    elif claim_ids:
        claims_query = supabase.table('ambassador_claims').select('id, ambassador_id, point_value, users(email, full_name)').in_('id', claim_ids).execute()
        claims = claims_query.data or []
    else:
        if request.is_json:
            return jsonify({"success": False, "error": "No claims specified."}), 400
        return redirect(url_for('dashboard.dashboard_mentor', tab='gtm'))

    updated_count = 0
    for c in claims:
        cid = c['id']
        amb_id = c['ambassador_id']
        pts = int(c.get('point_value') or 0)
        try:
            if action == 'approve':
                supabase.table('ambassador_claims').update({"status": "approved"}).eq('id', cid).execute()
                u_res = supabase.table('users').select('total_points').eq('id', amb_id).execute()
                curr_pts = (u_res.data[0]['total_points'] if u_res.data else 0) or 0
                supabase.table('users').update({"total_points": curr_pts + pts}).eq('id', amb_id).execute()
                send_notification('ambassador', amb_id, 'points_added', 'Task Approved!', f"Great job! +{pts} Points added.")
            else:
                supabase.table('ambassador_claims').update({"status": "rejected"}).eq('id', cid).execute()
                send_notification('ambassador', amb_id, 'task_rejected', 'Task Proof Rejected', "Your task proof could not be verified.")
            updated_count += 1
        except Exception as e:
            print(f"Error updating claim {cid}: {e}")

    if request.is_json:
        return jsonify({"success": True, "count": updated_count})

    return redirect(url_for('dashboard.dashboard_mentor', tab='gtm', claims_updated=updated_count))



@mentor_bp.route('/reject-enrollment', methods=['POST'])
@mentor_bp.route('/api/reject-enrollment', methods=['POST'])
def reject_enrollment():
    if str(session.get('role', '')).lower() != 'mentor':
        return redirect('/login')

    enrollment_id = request.form.get('enrollment_id')
    reason = request.form.get('reason', 'Application did not meet batch criteria at this time.')
    if not enrollment_id:
        return redirect(url_for('dashboard.dashboard_mentor'))

    enroll_query = supabase.table('enrollments').select('*, programs(title), users(email, full_name)').eq('enrollment_id', enrollment_id).execute()
    if not enroll_query.data:
        return redirect(url_for('dashboard.dashboard_mentor'))

    e = enroll_query.data[0]
    student = e.get('users') or {}
    prog = e.get('programs') or {}

    supabase.table('enrollments').update({"status": "rejected"}).eq('enrollment_id', enrollment_id).execute()

    if student.get('email'):
        rejection_msg = f"Dear {student.get('full_name', 'Applicant')},\n\nThank you for your interest in Virtuole.\n\nYour application for {prog.get('title', 'the internship program')} has been reviewed by our mentorship team, and could not be approved at this time.\n\nMentor Feedback: {reason}\n\nYou are welcome to explore and apply to other programs or future batches on the platform.\n\nBest regards,\nVirtuole Mentorship Team"
        send_system_email(student['email'], "Application Status Update - Virtuole", rejection_msg)

    send_notification('intern', e.get('user_id'), 'enrollment_rejected', 'Application Update', f"Your enrollment request for {prog.get('title')} was not approved.")
    return redirect(url_for('dashboard.dashboard_mentor'))
