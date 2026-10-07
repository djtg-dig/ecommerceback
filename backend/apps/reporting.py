"""Shared reporting-period validation for compact business projections."""

from datetime import date, timedelta

from django.utils import timezone
from rest_framework.exceptions import ValidationError


def resolve_reporting_period(query_params):
    """Return the inclusive reporting dates accepted by Dashboard-style endpoints."""
    today = timezone.localdate()
    period = query_params.get("period", "today")
    date_from = query_params.get("date_from")
    date_to = query_params.get("date_to")
    if bool(date_from) != bool(date_to) or ((date_from or date_to) and "period" in query_params):
        raise ValidationError("Use either period or date_from/date_to.")
    if date_from:
        try:
            start = date.fromisoformat(date_from)
            end = date.fromisoformat(date_to)
        except ValueError:
            raise ValidationError("Dates must use YYYY-MM-DD.")
        if start > end:
            raise ValidationError("date_from must not exceed date_to.")
        return start, end
    if period == "today":
        return today, today
    if period == "last_7_days":
        return today - timedelta(days=6), today
    if period == "last_30_days":
        return today - timedelta(days=29), today
    raise ValidationError({"period": "Invalid period."})
