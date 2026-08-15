import re
import os

base_dir = r"d:\antigravity\virtuole-platform"
static_dir = os.path.join(base_dir, "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

style_css_path = os.path.join(static_dir, "style.css")

def extract_and_replace(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    style_blocks = re.findall(r'<style>(.*?)</style>', content, re.DOTALL)
    if not style_blocks:
        return ""
    
    combined_css = "\n".join(style_blocks)
    
    # Replace the FIRST style block with the link tag, remove subsequent ones
    def replacer(match):
        if not hasattr(replacer, 'first'):
            replacer.first = True
            if 'theme.html' in filepath:
                # for theme.html, just add the link
                return '<link rel="stylesheet" href="/static/style.css">'
            else:
                return ''
        return ''
    
    new_content = re.sub(r'<style>.*?</style>', replacer, content, flags=re.DOTALL)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
        
    return combined_css

css_parts = []
# theme.html has the base CSS, extract it first
css_parts.append("/* ====== THEME CSS ====== */\n" + extract_and_replace(os.path.join(base_dir, "templates", "theme.html")))

# then extract from others
for filename in os.listdir(os.path.join(base_dir, "templates")):
    if filename.endswith('.html') and filename != 'theme.html':
        filepath = os.path.join(base_dir, "templates", filename)
        extracted = extract_and_replace(filepath)
        if extracted:
            css_parts.append(f"/* ====== {filename} ====== */\n" + extracted)

with open(style_css_path, 'w', encoding='utf-8') as f:
    f.write("\n".join(css_parts))
    
print("CSS extraction complete.")
