import os
import glob

paths = glob.glob('api/routes/*.py') + glob.glob('templates/*.html')

mappings = {
    "url_for('home'": "url_for('auth.home'",
    "url_for('login'": "url_for('auth.login'",
    "url_for('dashboard_admin'": "url_for('dashboard.dashboard_admin'",
    "url_for('dashboard_mentor'": "url_for('dashboard.dashboard_mentor'",
    "url_for('dashboard_intern'": "url_for('dashboard.dashboard_intern'",
    "url_for('dashboard_ambassador'": "url_for('dashboard.dashboard_ambassador'",
    "url_for('download_cert'": "url_for('public.download_cert'",
    "url_for('download_lor'": "url_for('public.download_lor'"
}

for p in paths:
    with open(p, 'r', encoding='utf-8') as f:
        content = f.read()
    
    modified = False
    for old, new in mappings.items():
        if old in content:
            content = content.replace(old, new)
            modified = True
            
    if modified:
        with open(p, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated {p}")
