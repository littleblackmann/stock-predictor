"""Shared Taipei clock and completed-session rules for prediction and scoring."""
from datetime import datetime, time, timedelta, timezone

TAIPEI = timezone(timedelta(hours=8))
# Allow the daily feed to settle after the regular close.
FINAL_DATA_TIME = time(15, 0)


def taipei_now():
    return datetime.now(TAIPEI)


def completed_history(df, now=None):
    now = now or taipei_now()
    now = now.replace(tzinfo=TAIPEI) if now.tzinfo is None else now.astimezone(TAIPEI)
    result = df.copy()
    if result.index.tz is not None:
        result.index = result.index.tz_convert(TAIPEI).tz_localize(None)
    result = result.loc[result.index.date <= now.date()]
    if now.time() < FINAL_DATA_TIME:
        result = result.loc[result.index.date < now.date()]
    return result.sort_index()


def target_session(data_date, horizon, calendar):
    target = data_date
    for _ in range(horizon):
        target = calendar.next_trading_day_after(target)
    return target
