from datetime import datetime, timedelta

DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def _time(value):
    try:
        h, m = (int(x) for x in str(value).split(":"))
    except ValueError:
        raise ValueError(f"Hora inválida: {value}. Usa HH:MM.") from None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Hora inválida: {value}. Usa HH:MM.")
    return h, m


def validate(s):
    if not isinstance(s, dict) or len(s) != 1:
        raise ValueError("Elige una sola forma de repetir la rutina.")
    (kind, value), = s.items()
    if kind == "every_hours":
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 168:
            raise ValueError("Las horas deben ser un número entre 1 y 168.")
        return {"every_hours": value}
    if kind == "daily":
        h, m = _time(value)
        return {"daily": f"{h:02d}:{m:02d}"}
    if kind == "weekly":
        days = sorted(set(value.get("days") or [])) if isinstance(value, dict) else []
        if not days or any(not isinstance(d, int) or not 0 <= d <= 6 for d in days):
            raise ValueError("Elige al menos un día de la semana.")
        h, m = _time(value.get("time"))
        return {"weekly": {"days": days, "time": f"{h:02d}:{m:02d}"}}
    raise ValueError(f"Forma de repetición desconocida: {kind}.")


def next_run(s, after):
    s = validate(s)
    if "every_hours" in s:
        return after + timedelta(hours=s["every_hours"])
    if "daily" in s:
        h, m = _time(s["daily"])
        candidate = after.replace(hour=h, minute=m, second=0, microsecond=0)
        return candidate if candidate > after else candidate + timedelta(days=1)
    h, m = _time(s["weekly"]["time"])
    for offset in range(8):
        day = after + timedelta(days=offset)
        candidate = day.replace(hour=h, minute=m, second=0, microsecond=0)
        if day.weekday() in s["weekly"]["days"] and candidate > after:
            return candidate
    raise AssertionError("unreachable: a weekly schedule always fires within 8 days")


def _join(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " y " + names[-1]


def describe(s):
    s = validate(s)
    if "every_hours" in s:
        n = s["every_hours"]
        return "Cada hora" if n == 1 else f"Cada {n} horas"
    if "daily" in s:
        return f"Todos los días {s['daily']}"
    return f"{_join([DAYS[d] for d in s['weekly']['days']])} {s['weekly']['time']}"
