
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from api.config import supabase, limiter
from api.utils.email import send_system_email, send_ambassador_email
import random, string, uuid, json
from datetime import datetime, timedelta

mentor_bp = Blueprint('mentor', __name__)



@mentor_bp.route('/cron/maintenance', methods=['GET', 'POST'])
@mentor_bp.route('/api/cron/maintenance', methods=['GET', 'POST'])
def run_maintenance():
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {os.getenv('CRON_SECRET_KEY')}":
        return jsonify({"error": "Unauthorized"}), 401
    
    if not supabase: return jsonify({"error": "No database"}), 500
    
    try:
        now = datetime.utcnow()
        thirty_days_ago = (now - timedelta(days=30)).isoformat()
        supabase.table('enrollments').update({"status": "expired"}).eq('status', 'active').lt('created_at', thirty_days_ago).execute()

        twenty_four_hours_ago = (now - timedelta(hours=24)).isoformat()
        expired_fails = supabase.table('enrollments').select('id', 'user_id').eq('status', 'failed').lt('created_at', twenty_four_hours_ago).execute()
        for row in expired_fails.data:
            supabase.table('enrollments').update({"status": "expired"}).eq('id', row['id']).execute()

        seven_days_ago = (now - timedelta(days=7)).isoformat()
        reminders = supabase.table('enrollments').select('id', 'user_id').eq('status', 'active').gt('created_at', seven_days_ago).execute()
        for row in reminders.data:
            user = supabase.table('users').select('email', 'full_name').eq('id', row['user_id']).execute().data[0]
            send_system_email(user['email'], "Virtuole Internship: Pending Submission Reminder", f"Hello {user['full_name']},\n\nDon't forget to submit your architecture. You have a 30-day window from enrollment to qualify for credentials.")

        expired_ambassadors = supabase.table('users').select('id', 'email', 'full_name').eq('role', 'ambassador').lt('ambassador_expiry', now.isoformat()).execute()
        for row in expired_ambassadors.data:
            supabase.table('users').update({"role": "intern", "promo_code": None, "ambassador_expiry": None}).eq('id', row['id']).execute()
            send_ambassador_email(row['email'], "Virtuole Ambassador Program: Term Completed", f"Hello {row['full_name']},\n\nYour 1-year term as a Virtuole Ambassador has officially concluded. Your account has now been seamlessly transitioned back to a standard Intern profile.")
            
        # Process Email Queue (Brevo Limits)
        pending_emails = supabase.table('email_queue').select('*').eq('status', 'pending').order('created_at').execute()
        
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        try:
            sent_today = supabase.table('email_queue').select('id').eq('status', 'sent').gte('sent_at', today_midnight).execute()
            daily_count = len(sent_today.data) if sent_today.data else 0
        except Exception:
            daily_count = 0
            
        allowance = 300 - daily_count
        
        if allowance > 0 and pending_emails.data:
            for i, email_record in enumerate(pending_emails.data):
                if i >= allowance:
                    break
                    
                msg = MIMEMultipart()
                msg['From'] = f"Virtuole Support <{os.getenv('BREVO_SMTP_USER', 'support@virtuole.in')}>"
                msg['To'] = email_record['recipient']
                msg['Subject'] = email_record['subject']
                msg.add_header('reply-to', 'support@virtuole.in')
                
                if email_record['is_html']:
                    msg.attach(MIMEText(email_record['body_content'], 'html'))
                else:
                    msg.attach(MIMEText(email_record['body_content'], 'plain'))
                    
                try:
                    with smtplib.SMTP("smtp-relay.brevo.com", 587) as server:
                        server.starttls()
                        server.login(os.getenv("BREVO_SMTP_USER"), os.getenv("BREVO_SMTP_PASS"))
                        server.send_message(msg)
                    
                    # Delete the pending record from queue
                    try:
                        supabase.table('email_queue').delete().eq('id', email_record['id']).execute()
                    except Exception as inner_e:
                        print(f"Failed to delete pending email: {inner_e}")
                    
                    # Insert a new 'sent' record for tracking daily limits
                    try:
                        supabase.table('email_queue').insert({
                            "recipient": email_record['recipient'],
                            "subject": email_record['subject'],
                            "body_content": email_record['body_content'],
                            "is_html": email_record['is_html'],
                            "status": "sent",
                            "sent_at": datetime.utcnow().isoformat()
                        }).execute()
                    except Exception as inner_e:
                        print(f"Failed to insert sent email to queue: {inner_e}")
                    
                except Exception as e:
                    print(f"Brevo Queue Delivery Exception: {e}")

        return jsonify({"status": "Maintenance execution completed successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

