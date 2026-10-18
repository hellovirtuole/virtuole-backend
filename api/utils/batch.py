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
