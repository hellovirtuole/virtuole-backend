
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from api.config import supabase, limiter
from api.utils.email import send_system_email, send_ambassador_email
import random, string, uuid, json
from datetime import datetime, timedelta

intern_bp = Blueprint('intern', __name__)



def send_system_email(to_email, subject, body_content, is_html=False):
    if not supabase: return
    now = datetime.utcnow()
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    
    # Check current sent count
    try:
        sent_today = supabase.table('email_queue').select('id').eq('status', 'sent').gte('sent_at', today_midnight).execute()
        daily_count = len(sent_today.data) if sent_today.data else 0
    except Exception as e:
        print(f"Failed to fetch daily count: {e}")
        daily_count = 0
        
    if daily_count < 300:
        msg = MIMEMultipart()
        msg['From'] = f"Virtuole Services <{os.getenv('BREVO_SMTP_USER', 'service@virtuole.in')}>"
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.add_header('reply-to', 'support@virtuole.in')
        
        if is_html:
            msg.attach(MIMEText(body_content, 'html'))
        else:
            msg.attach(MIMEText(body_content, 'plain'))
            
        try:
            with smtplib.SMTP("smtp-relay.brevo.com", 587) as server:
                server.starttls()
                server.login(os.getenv("BREVO_SMTP_USER"), os.getenv("BREVO_SMTP_PASS"))
                server.send_message(msg)
            
            try:
                supabase.table('email_queue').insert({
                    "recipient": to_email,
                    "subject": subject,
                    "body_content": body_content,
                    "is_html": is_html,
                    "status": "sent",
                    "sent_at": now.isoformat()
                }).execute()
            except Exception as inner_e:
                print(f"Failed to insert sent email to queue: {inner_e}")
        except Exception as e:
            print(f"Brevo Delivery Exception: {e}")
            try:
                supabase.table('email_queue').insert({
                    "recipient": to_email,
                    "subject": subject,
                    "body_content": body_content,
                    "is_html": is_html,
                    "status": "pending"
                }).execute()
            except Exception as inner_e:
                print(f"Failed to queue pending email: {inner_e}")
    else:
        # Queue for next day
        try:
            supabase.table('email_queue').insert({
                "recipient": to_email,
                "subject": subject,
                "body_content": body_content,
                "is_html": is_html,
                "status": "pending"
            }).execute()
        except Exception as e:
            print(f"Failed to queue pending email: {e}")

def send_ambassador_email(to_email, subject, body_content):
    msg = MIMEMultipart()
    msg['From'] = f"Virtuole Ambassador Program <ambassador@virtuole.in>"
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.add_header('reply-to', 'ambassador@virtuole.in')
    msg.attach(MIMEText(body_content, 'plain'))
    try:
        with smtplib.SMTP('smtp.zoho.in', 587) as server:
            server.starttls()
            server.login('ambassador@virtuole.in', os.getenv("ZOHO_AMBASSADOR_PASS"))
            server.send_message(msg)
    except Exception as e:
        print(f"Zoho Delivery Exception: {e}")



# 4. SYSTEM MAINTENANCE CRON
