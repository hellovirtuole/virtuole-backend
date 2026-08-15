
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from api.config import supabase, limiter
from api.utils.email import send_system_email, send_ambassador_email
import random, string, uuid, json
from datetime import datetime, timedelta

public_bp = Blueprint('public', __name__)



@public_bp.route('/download_cert')
def download_cert():
    if str(session.get('role', '')).lower() not in ['ambassador', 'intern + ambassador']: return redirect('/login')
    
    tier_id = request.args.get('tier_id')
    u = supabase.table('users').select('*').eq('id', session['user_id']).execute().data[0]
    pts = u['total_points'] or 0
    
    tier = supabase.table('ambassador_tiers').select('*').eq('id', tier_id).execute().data
    if not tier: return "Tier not found", 404
    tier = tier[0]
    
    if pts < tier['points_required']: return "Insufficient Points", 403
    if not tier['give_certificate']: return "Tier does not provide a certificate", 403
    
    return render_template('docs/ambassador_certificate.html', name=u['full_name'], date=datetime.utcnow().strftime("%B %d, %Y"), tier_name=tier['name'], points=pts, amb_id=u['public_id'])

@public_bp.route('/download_lor/<type>')
def download_lor(type):
    if str(session.get('role', '')).lower() not in ['ambassador', 'intern + ambassador']: return redirect('/login')
    u = supabase.table('users').select('*').eq('id', session['user_id']).execute().data[0]
    pts = u['total_points'] or 0
    
    # Check if any of the user's qualified tiers give an LOR
    tiers = supabase.table('ambassador_tiers').select('*').execute().data
    qualifies = False
    for t in (tiers or []):
        if pts >= t['points_required'] and t['give_lor']:
            qualifies = True
            break
            
    if type == 'devrel' and qualifies:
        return render_template('docs/lor.html', name=u['full_name'], date=datetime.utcnow().strftime("%B %d, %Y"), program_title="GTM Ambassador Program", track_level="Community Lead", enroll_id=u['public_id'], project_details="Community Leadership and Advocacy.")
        
    return "Insufficient Points or Tier does not provide an LOR", 403

@public_bp.route('/download_cert_intern/<enrollment_id>')
def download_cert_intern(enrollment_id):
    enroll_data = supabase.table('enrollments').select('*, programs(*), users(full_name)').eq('enrollment_id', enrollment_id).execute().data
    if not enroll_data: return "Invalid Credential", 404
    e = enroll_data[0]
    
    sub = supabase.table('submissions').select('*').eq('enrollment_id', enrollment_id).execute().data
    if not sub or not sub[0].get('score') or sub[0]['score'] < 80:
        return "Not Eligible for Certificate", 403
        
    s = sub[0]
    date_str = s.get('evaluated_at', e['created_at']).split('T')[0]
    return render_template('docs/certificate.html', name=e['users']['full_name'], date=date_str, program_title=e['programs']['title'], track_level=e['track_level'].title(), enroll_id=enrollment_id, score=s['score'])

@public_bp.route('/download_offer/<enrollment_id>')
def download_offer(enrollment_id):
    if str(session.get('role', '')).lower() not in ['intern', 'intern + ambassador']: return redirect('/login')
    enroll_data = supabase.table('enrollments').select('*, programs(*), users(full_name)').eq('enrollment_id', enrollment_id).eq('user_id', session['user_id']).execute().data
    if not enroll_data: return "Invalid Assignment Context", 403
        
    e = enroll_data[0]
    try:
        start_dt = datetime.fromisoformat(e['created_at'].replace('Z', '+00:00')) if e.get('created_at') else datetime.utcnow()
    except:
        start_dt = datetime.utcnow()
        
    duration_days = 90 if e.get('track_level', '').lower() == 'expert' else 30
    end_dt = start_dt + timedelta(days=duration_days)
    
    raw_date = start_dt.strftime("%B %d, %Y")
    end_date = end_dt.strftime("%B %d, %Y")
    
    html_content = render_template('docs/offer_letter.html', name=e['users']['full_name'], date=raw_date, program_title=e['programs']['title'], track_level=e['track_level'].title(), enroll_id=enrollment_id, project_details=e['programs']['short_description'], duration_days=duration_days, end_date=end_date)
    
    # Auto-Print dialog script
    return html_content + "<script>window.onload = function() { setTimeout(function(){ window.print(); }, 500); }</script>"

@public_bp.route('/contact')
def contact_page():
    return render_template('contact.html')

@public_bp.route('/feedback')
def feedback_page():
    return render_template('feedback.html')

@public_bp.route('/submit-feedback', methods=['POST'])
def submit_feedback():
    name = request.form.get('name')
    email = request.form.get('email')
    subject = request.form.get('subject')
    message = request.form.get('message')
    
    # Logs the feedback to your Vercel console
    print(f"NEW FEEDBACK: {name} | {email} | {subject} | {message}")
    
    return render_template('feedback.html', message="Thank you! Your feedback has been successfully submitted.")

@public_bp.route('/subscribe', methods=['POST'])
def subscribe_newsletter():
    email = request.form.get('email')
    try:
        supabase.table('subscribers').insert({"email": email}).execute()
    except Exception:
        pass
    return redirect(url_for('home'))

@public_bp.route('/terms')
def terms_page(): return render_template('terms.html')
@public_bp.route('/refund')
def refund_page(): return render_template('refund.html')
@public_bp.route('/privacy')
def privacy_page(): return render_template('privacy.html')
@public_bp.route('/cookies')
def cookies_page(): return render_template('cookies.html')
@public_bp.route('/verify.html')
def verify_page_redirect(): return render_template('verify.html')
@public_bp.route('/offer-letter')
def offer_letter_page(): return render_template('offer.html')

@public_bp.route('/blog')
def blog():return render_template('blog.html')

@public_bp.route('/view-offer', methods=['GET'])
def view_public_offer():
    enrollment_id = request.args.get('enrollment_id')
    if not enrollment_id: return render_template('offer.html')
    try:
        enroll_data = supabase.table('enrollments').select('*, programs(*), users(full_name)').eq('enrollment_id', enrollment_id).execute().data
        if not enroll_data: return render_template('offer.html', error=True)
        e = enroll_data[0]
        try:
            start_dt = datetime.fromisoformat(e['created_at'].replace('Z', '+00:00')) if e.get('created_at') else datetime.utcnow()
        except:
            start_dt = datetime.utcnow()
            
        duration_days = 90 if e.get('track_level', '').lower() == 'expert' else 30
        end_dt = start_dt + timedelta(days=duration_days)
        
        raw_date = start_dt.strftime("%B %d, %Y")
        end_date = end_dt.strftime("%B %d, %Y")
        
        html_content = render_template('docs/offer_letter.html', name=e['users']['full_name'], date=raw_date, program_title=e['programs']['title'], track_level=e['track_level'].title(), enroll_id=enrollment_id, project_details=e['programs']['short_description'], duration_days=duration_days, end_date=end_date)
        return html_content + "<script>window.onload = function() { setTimeout(function(){ window.print(); }, 500); }</script>"
    except:
        return render_template('offer.html', error=True)

@public_bp.route('/verify-credential', methods=['GET'])
def verify_credential():
    credential_id = request.args.get('credential_id')
    if not credential_id: return render_template('verify.html')
    try:
        enroll_query = supabase.table('enrollments').select('*, programs(title), users(full_name)').eq('enrollment_id', credential_id).execute()
        if not enroll_query.data: return render_template('verify.html', error=True)
        
        e = enroll_query.data[0]
        
        if e['status'] == 'failed':
            sub_query = supabase.table('submissions').select('*').eq('enrollment_id', credential_id).order('evaluated_at', desc=True).limit(1).execute()
            if sub_query.data and sub_query.data[0].get('certificate_url', '').startswith('failed:'):
                reason = sub_query.data[0]['certificate_url'].replace('failed:', '')
            else:
                reason = "Failed to secure 80% passing grade."
            return render_template('verify.html', failed=True, reason=reason)
            
        if e['status'] != 'graded':
            return render_template('verify.html', error=True)
            
        sub_query = supabase.table('submissions').select('*').eq('enrollment_id', credential_id).execute()
        return render_template('verify.html', verified_data={
            "student_name": e['users']['full_name'],
            "program_title": e['programs']['title'],
            "track_level": e['track_level'],
            "score": sub_query.data[0]['score'],
            "enrollment_id": credential_id,
            "evaluated_date": sub_query.data[0]['evaluated_at'].split('T')[0] if sub_query.data[0].get('evaluated_at') else "N/A"
        })
    except:
        return render_template('verify.html', error=True)

@public_bp.route('/apply-ambassador', methods=['GET', 'POST'])
@public_bp.route('/api/apply-ambassador', methods=['GET', 'POST'])
def apply_ambassador():
    if request.method == 'GET':
        return render_template('applyambass.html')

    name = request.form.get('name')
    email = request.form.get('email')
    college = request.form.get('college')
    motivation = request.form.get('motivation', '')

    if not name or not email:
        return render_template('applyambass.html', error="Please provide your name and email.")

    # Fold college into motivation so the detail is preserved without assuming
    # a dedicated column exists in the ambassador_applications table.
    if college:
        motivation = f"College: {college}\n\n{motivation}"

    try:
        supabase.table('ambassador_applications').insert({
            "name": name, "email": email, "motivation": motivation, "status": "pending"
        }).execute()
    except Exception as e:
        return render_template('applyambass.html', error=f"Submission failed: {e}")

    return render_template('applyambass.html', submitted=True)

@public_bp.route('/static/logo.png')
def serve_logo():
    return send_from_directory('templates', 'logo.png')

@public_bp.route('/credential/<enroll_id>')
def view_credential(enroll_id):
    try:
        response = supabase.table('enrollments').select('*, users(full_name), programs(title)').eq('enrollment_id', enroll_id).execute()
        if not response.data:
            return "Credential not found.", 404
            
        enroll_data = response.data[0]
        if enroll_data.get('status') not in ['certified', 'completed'] and not enroll_data.get('final_score'):
            return "Credential not yet certified.", 403
            
        submission = supabase.table('submissions').select('code_link').eq('enrollment_id', enroll_id).execute()
        repo_link = submission.data[0]['code_link'] if submission.data else None
        
        credential = {
            'id': enroll_data['enrollment_id'],
            'intern_name': enroll_data['users']['full_name'],
            'program_title': enroll_data['programs']['title'],
            'track_level': enroll_data['track_level'],
            'score': enroll_data.get('final_score', '100'),
            'updated_at': enroll_data.get('updated_at', datetime.utcnow().isoformat()),
            'repo_link': repo_link
        }
        return render_template('credential.html', credential=credential)
    except Exception as e:
        return f"Error loading credential: {str(e)}", 500

@public_bp.route('/credential/user/<public_id>')
def view_credential_by_user(public_id):
    try:
        if public_id == 'test_preview':
            credential = {
                'id': 'VT-E-SAMPLE123',
                'intern_name': 'Test Intern Profile',
                'program_title': 'Advanced Software Engineering',
                'track_level': 'elite',
                'score': '100',
                'updated_at': datetime.utcnow().isoformat(),
                'repo_link': 'https://github.com/virtuole/sample-repo'
            }
            return render_template('credential.html', credential=credential)
            
        user_res = supabase.table('users').select('id, full_name').eq('public_id', public_id).execute()
        if not user_res.data:
            return "User not found.", 404
        
        user_id = user_res.data[0]['id']
        
        response = supabase.table('enrollments').select('*, programs(title)').eq('user_id', user_id).in_('status', ['certified', 'completed']).order('updated_at', desc=True).limit(1).execute()
        
        if not response.data:
            return "No certified credentials found for this user.", 404
            
        enroll_data = response.data[0]
        enroll_id = enroll_data['enrollment_id']
            
        submission = supabase.table('submissions').select('code_link').eq('enrollment_id', enroll_id).execute()
        repo_link = submission.data[0]['code_link'] if submission.data else None
        
        credential = {
            'id': enroll_data['enrollment_id'],
            'intern_name': user_res.data[0]['full_name'],
            'program_title': enroll_data['programs']['title'],
            'track_level': enroll_data['track_level'],
            'score': enroll_data.get('final_score', '100'),
            'updated_at': enroll_data.get('updated_at', datetime.utcnow().isoformat()),
            'repo_link': repo_link
        }
        return render_template('credential.html', credential=credential)
    except Exception as e:
        return f"Error loading credential: {str(e)}", 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
