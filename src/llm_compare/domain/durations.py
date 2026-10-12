"""How long something took, written for a person: `0.4 s`, `38 s`, `4m 12s`, `1h 03m 05s`."""


def _short(seconds: float) -> str:
    tenths = round(seconds, 1)
    return f"{tenths:.0f} s" if tenths == int(tenths) else f"{tenths:.1f} s"


def format_duration(seconds: float | None) -> str:
    """`n/a` for None; a span under a minute keeps one decimal when it has one."""
    if seconds is None:
        return "n/a"
    seconds = max(seconds, 0.0)
    if round(seconds, 1) < 60:
        return _short(seconds)
    whole = round(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}h {minutes:02d}m {secs:02d}s" if hours else f"{minutes}m {secs:02d}s"
