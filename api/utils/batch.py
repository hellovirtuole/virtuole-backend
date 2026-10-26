from datetime import datetime, timedelta

def calculate_next_start_date(base_dt=None):
    """
    Calculates the upcoming batch start date among day 1, 10, or 20 of the month:
    - If base date day is 1 to 9: returns the 10th of the current month.
    - If base date day is 10 to 19: returns the 20th of the current month.
    - If base date day is >= 20: returns the 1st of the next month.
    """
    if base_dt is None:
        base_dt = datetime.utcnow()
    
    year = base_dt.year
    month = base_dt.month
    day = base_dt.day

    if day < 10:
        return datetime(year, month, 10, 0, 0, 0)
    elif day < 20:
        return datetime(year, month, 20, 0, 0, 0)
    else:
        if month == 12:
            return datetime(year + 1, 1, 1, 0, 0, 0)
        else:
            return datetime(year, month + 1, 1, 0, 0, 0)

def parse_track_duration(track_level):
    """
    Normalizes track_level into (duration_days, track_display_string).
    Handles 'custom_X', numeric months (e.g. '1', '2', '3'), and classic tracks
    ('beginner', 'intermediate', 'expert').
    """
    track = str(track_level or '').lower()
    if track.startswith('custom_'):
        try:
            months = int(track.split('_')[1])
        except Exception:
            months = 1
        duration_days = months * 30
        track_display = f"{months} Months" if months > 1 else "1 Month"
    elif track.isdigit():
        months = int(track)
        duration_days = months * 30
        track_display = f"{months} Months" if months > 1 else "1 Month"
    else:
        duration_days = 90 if track == 'expert' else (60 if track == 'intermediate' else 30)
        track_display_map = {'beginner': '1 Month', 'intermediate': '2 Months', 'expert': '3 Months'}
        track_display = track_display_map.get(track, track.title() if track else '1 Month')
    return duration_days, track_display


def resolve_track_price_and_specs(prog, track_level):
    """
    Resolves the exact price (INR integer) and specifications URL for any track level
    across all format versions (tracks JSON array, custom timeline, or legacy price columns).
    Guarantees a non-zero valid fee.
    """
    if not prog or not isinstance(prog, dict):
        return 999, '#'

    raw_track = str(track_level or '').strip().lower()
    
    # 1. Parse months
    months = 1
    if raw_track.startswith('custom_'):
        try: months = int(raw_track.split('_')[1])
        except Exception: months = 1
    elif raw_track.isdigit():
        try: months = int(raw_track)
        except Exception: months = 1
    elif 'expert' in raw_track or '3' in raw_track:
        months = 3
    elif 'intermediate' in raw_track or '2' in raw_track:
        months = 2
    else:
        months = 1

    price = 0
    specs = '#'

    # 2. Match in tracks JSON array
    tracks_json = prog.get('tracks') or []
    if isinstance(tracks_json, str):
        try:
            import json
            tracks_json = json.loads(tracks_json)
        except Exception:
            tracks_json = []

    if tracks_json and isinstance(tracks_json, list):
        matched = next((t for t in tracks_json if isinstance(t, dict) and str(t.get('months')) == str(months)), None)
        if matched and isinstance(matched, dict):
            price = matched.get('price') or 0
            specs = matched.get('specs') or '#'

    # 3. Check custom timeline
    if not price and raw_track.startswith('custom_'):
        price = prog.get('custom_price') or 0
        specs = prog.get('custom_specs') or '#'

    # 4. Fallback to beginner / intermediate / expert columns
    if not price:
        if months == 1:
            price = prog.get('price_beginner') or prog.get('price_1') or 0
            specs = prog.get('specs_beginner') or prog.get('specs_1') or '#'
        elif months == 2:
            price = prog.get('price_intermediate') or prog.get('price_2') or 0
            specs = prog.get('specs_intermediate') or prog.get('specs_2') or '#'
        elif months == 3:
            price = prog.get('price_expert') or prog.get('price_3') or 0
            specs = prog.get('specs_expert') or prog.get('specs_3') or '#'

    # 5. Direct column match
    if not price:
        price = prog.get(f'price_{raw_track}') or 0
        specs = prog.get(f'specs_{raw_track}') or '#'

    # 6. Fallback if still 0
    if not price:
        price = (
            prog.get('price_beginner')
            or prog.get('price_intermediate')
            or prog.get('price_expert')
            or prog.get('custom_price')
            or 999
        )
    if specs == '#' or not specs:
        specs = (
            prog.get('specs_beginner')
            or prog.get('specs_intermediate')
            or prog.get('specs_expert')
            or prog.get('custom_specs')
            or '#'
        )

    try:
        price = int(price)
    except Exception:
        price = 999

    return price, specs
