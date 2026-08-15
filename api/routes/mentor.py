
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from api.config import supabase, limiter
from api.utils.email import send_system_email, send_ambassador_email
import random, string, uuid, json
from datetime import datetime, timedelta

mentor_bp = Blueprint('mentor', __name__)



@mentor_bp.route('/grade-submission', methods=['POST'])
@mentor_bp.route('/api/grade-submission', methods=['POST'])
def grade_submission():
    if str(session.get('role', '')).lower() != 'mentor': return redirect('/login')
    sub_id = request.form.get('submission_id')
    enrollment_id = request.form.get('enrollment_id')
    score = int(request.form.get('score'))
    feedback = request.form.get('feedback', 'No specific feedback.')
    
    enroll_data = supabase.table('enrollments').select('*, programs(title, short_description)').eq('enrollment_id', enrollment_id).execute().data[0]
    student = supabase.table('users').select('email', 'full_name').eq('id', enroll_data['user_id']).execute().data[0]
    
    if score >= 80:
        db_updates = {"score": score, "certificate_url": f"https://www.virtuole.in/verify-credential?credential_id={enrollment_id}", "evaluated_at": datetime.utcnow().isoformat()}
        if score == 100:
            db_updates["lor_url"] = f"https://www.virtuole.in/verify-credential?credential_id={enrollment_id}"
            body_msg = f"Congratulations {student['full_name']}! You can view your Certificate and Elite LoR here: https://www.virtuole.in/verify-credential?credential_id={enrollment_id}"
        else:
            body_msg = f"Congratulations {student['full_name']}! You can view your Certificate here: https://www.virtuole.in/verify-credential?credential_id={enrollment_id}"
            
        supabase.table('submissions').update(db_updates).eq('id', sub_id).execute()
        supabase.table('enrollments').update({"status": "graded"}).eq('enrollment_id', enrollment_id).execute()
        send_system_email(student['email'], "Certification Passed - Virtuole", body_msg)
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
            send_system_email(student['email'], "Certification Failed", failure_email_body)
        else:
            # First failure. Give them 24 hours to resubmit.
            supabase.table('enrollments').update({
                "status": "resubmit", 
                "created_at": datetime.utcnow().isoformat() # Start 24h countdown
            }).eq('enrollment_id', enrollment_id).execute()
            
            # Delete old submission to allow inserting a new one
            supabase.table('submissions').delete().eq('id', sub_id).execute() 
            
            failure_email_body = f"Dear {student['full_name']},\n\nYour submission scored {score}%. Feedback: \"{feedback}\"\nYou have exactly 24 hours to resubmit your project in your dashboard."
            send_system_email(student['email'], "ACTION REQUIRED: Submission Failed", failure_email_body)
            
    return redirect(url_for('dashboard.dashboard_mentor'))

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
        send_ambassador_email(claim_data['users']['email'], "Task Approved!", f"Great job! +{pts} Points added.")
    elif action == 'reject':
        supabase.table('ambassador_claims').update({"status": "rejected"}).eq('id', claim_id).execute()
        send_ambassador_email(claim_data['users']['email'], "Task Proof Rejected", "Your task proof could not be verified.")
    return redirect(url_for('dashboard.dashboard_mentor'))

