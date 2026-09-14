import os
path = 'd:/antigravity/virtuole-platform/templates/dashboard_nav.html'
with open(path, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

content = content.replace('~', '&#9776;')
content = content.replace('~?,?', '&#9728;')
content = content.replace('o ', '&#10005;')
content = content.replace('dY""', '&#128276;')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
