"""Untrusted creator release intent. No publication, payment or hosting authority."""
from datetime import datetime


def default_release_plan():
    return dict(destination="both", access="PUBLIC", websiteAt=None, launcherAt=None, serverAt=None)


def validate_release_plan(value):
    if not isinstance(value, dict) or set(value) != set(default_release_plan()):
        raise ValueError("Некорректный план выпуска")
    if value["destination"] not in ("website", "launcher", "both") or value["access"] not in ("PUBLIC", "PAID", "PRIVATE"):
        raise ValueError("Некорректная площадка или доступ")
    for key in ("websiteAt", "launcherAt", "serverAt"):
        date = value[key]
        if date is not None:
            if not isinstance(date, str) or len(date) != 24:
                raise ValueError("Укажите дату UTC с точностью до минуты")
            try:
                parsed = datetime.strptime(date, "%Y-%m-%dT%H:%M:00.000Z")
            except ValueError as error:
                raise ValueError("Некорректная дата выпуска") from error
            if not 2000 <= parsed.year <= 2099 or parsed.strftime("%Y-%m-%dT%H:%M:00.000Z") != date:
                raise ValueError("Некорректная дата выпуска")
    if (value["destination"] == "website" and value["launcherAt"] is not None
            or value["destination"] == "launcher" and value["websiteAt"] is not None):
        raise ValueError("Дата задана для невыбранной площадки")
    return dict(value)
