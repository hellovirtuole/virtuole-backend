import re
import json

def parse_submission_deliverables(code_link_raw, defense_link_raw=None):
    """
    Parses raw code_link and defense_link strings into a structured list of project deliverables:
    [
        {
            'num': 1,
            'title': 'Project 1 Title',
            'code_link': 'https://github.com/...',
            'defense_link': 'https://docs.google.com/...'
        },
        ...
    ]
    Supports:
    - Single URL string (backwards-compatible default)
    - Multi-line labeled format: 'Project 1 (Title): https://...'
    - JSON array format
    """
    if not code_link_raw:
        return []

    code_raw = str(code_link_raw).strip()
    defense_raw = str(defense_link_raw or '').strip()

    # Attempt JSON parsing first if wrapped as JSON array
    if (code_raw.startswith('[') and code_raw.endswith(']')) or (code_raw.startswith('{') and code_raw.endswith('}')):
        try:
            data = json.loads(code_raw)
            if isinstance(data, list):
                parsed = []
                for idx, item in enumerate(data, start=1):
                    if isinstance(item, dict):
                        parsed.append({
                            'num': item.get('num') or idx,
                            'title': item.get('title') or f"Project {idx}",
                            'code_link': item.get('code_link') or item.get('code') or '',
                            'defense_link': item.get('defense_link') or item.get('defense') or ''
                        })
                if parsed:
                    return parsed
        except Exception:
            pass

    code_lines = [line.strip() for line in code_raw.splitlines() if line.strip()]
    defense_lines = [line.strip() for line in defense_raw.splitlines() if line.strip()]

    # Index labeled defense links by project number or keep in order
    defense_map = {}
    defense_list = []
    for d_line in defense_lines:
        m = re.match(r'^(?:Project\s*(\d+)(?:\s*\((.*?)\))?:\s*)?(https?://\S+)', d_line, re.IGNORECASE)
        if m and m.group(1):
            defense_map[int(m.group(1))] = m.group(3)
        elif m:
            defense_list.append(m.group(3))
        else:
            defense_list.append(d_line)

    projects = []
    for idx, c_line in enumerate(code_lines, start=1):
        m = re.match(r'^(?:Project\s*(\d+)(?:\s*\((.*?)\))?:\s*)?(https?://\S+)', c_line, re.IGNORECASE)
        if m:
            p_num = int(m.group(1)) if m.group(1) else idx
            p_title = (m.group(2) or '').strip()
            c_url = m.group(3)
        else:
            p_num = idx
            p_title = ''
            c_url = c_line

        d_url = defense_map.get(p_num)
        if not d_url and idx - 1 < len(defense_list):
            d_url = defense_list[idx - 1]

        projects.append({
            'num': p_num,
            'title': p_title or f"Project {p_num}",
            'code_link': c_url,
            'defense_link': d_url or ''
        })

    return projects
