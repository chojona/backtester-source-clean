from dataclasses import replace
from datetime import datetime, timedelta, date
import csv
import pytest
from backtester.data import Bar, CSVProvider, validate
from backtester.sessions import SessionCalendar, local_at, UTC, NY
from conftest import make_bar, day_bars


@pytest.mark.parametrize("change", [dict(volume=-1), dict(high=99), dict(low=101), dict(close=float("nan")), dict(open_interest=-1)])
def test_bad_bar(change):
    with pytest.raises(ValueError):
        replace(make_bar(), **change)


def test_naive_timestamp_rejected():
    with pytest.raises(ValueError):
        replace(make_bar(), timestamp=datetime(2026, 1, 5, 9, 30))


def test_duplicate_and_ordering():
    first = make_bar()
    second = replace(first, timestamp=first.timestamp + timedelta(minutes=1))
    for bars in ([first, first], [second, first]):
        with pytest.raises(ValueError):
            validate(bars, SessionCalendar())


def test_parallel_contract_bars_are_not_duplicates():
    bars = [make_bar(), make_bar(contract="ESH27")]
    assert validate(bars, SessionCalendar()).rows == 2


def test_missing_bars_counted_without_interpolation():
    first = make_bar()
    second = replace(first, timestamp=first.timestamp + timedelta(minutes=3))
    report = validate([first, second], SessionCalendar())
    assert report.missing_intervals[0]["count"] == 2


def test_breaks_not_missing():
    calendar = SessionCalendar()
    bars = [make_bar("2026-01-05T16:14"), make_bar("2026-01-05T16:30")]
    assert not validate(bars, calendar).missing_intervals
    with pytest.raises(ValueError):
        validate([make_bar("2026-01-05T16:15")], calendar)


def test_bar_crossing_rth_rejected():
    with pytest.raises(ValueError):
        validate([make_bar("2026-01-05T09:29", minutes=5)], SessionCalendar())


@pytest.mark.parametrize("day,hour", [(date(2026,3,6), 14), (date(2026,3,9), 13), (date(2026,10,30),13), (date(2026,11,2),14)])
def test_dst_rth(day, hour):
    stamp = local_at(day, "09:30")
    info = SessionCalendar().classify(stamp)
    assert stamp.hour == hour
    assert info.session == "RTH"
    assert info.trading_date == day


def test_sunday_evening_maps_to_monday():
    info = SessionCalendar().classify(local_at(date(2026, 1, 4), "18:00"))
    assert info.trading_date == date(2026,1,5)
    assert info.minutes_from_session_open == 0
    assert info.minutes_to_session_close == 1380
    assert info.week == "2026-01-05"


@pytest.mark.parametrize("stamp", ["2026-01-05T17:00", "2026-01-05T17:59", "2026-01-09T18:00", "2026-01-10T12:00", "2026-01-04T17:59"])
def test_market_closed(stamp):
    assert SessionCalendar().classify(datetime.fromisoformat(stamp).replace(tzinfo=NY)) is None


def test_gold_specific_window():
    calendar = SessionCalendar("gold")
    info = calendar.classify(local_at(date(2026,1,5), "08:20"))
    assert info.session == "RTH"
    assert calendar.classify(local_at(date(2026,1,5), "13:30")).session == "POST_RTH"
    assert calendar.classify(local_at(date(2026,1,5), "16:20")) is not None


def test_holiday_and_early_close_override():
    calendar = SessionCalendar(overrides={"2026-01-05": {"closed": True},
                                         "2026-01-06": {"eth_close": "13:00", "rth_close": "13:00"}})
    assert calendar.classify(local_at(date(2026,1,5), "09:30")) is None
    assert calendar.classify(local_at(date(2026,1,6), "12:59")) is not None
    assert calendar.classify(local_at(date(2026,1,6), "13:00")) is None


@pytest.mark.parametrize("interval", [1,5])
def test_csv_ingests_real_intraday(tmp_path, interval):
    path=tmp_path/'bars.csv'
    path.write_text('timestamp,open,high,low,close,volume,contract,symbol,trade_count,bid_volume,ask_volume,open_interest\n'
                    '2026-01-05T14:30:00Z,100,102,99,101,10,ESZ26,ES,5,4,6,100\n')
    bars, report=CSVProvider(path,"ES",SessionCalendar(),interval).load()
    assert bars[0].timestamp.tzinfo == UTC
    assert bars[0].duration == timedelta(minutes=interval)
    assert bars[0].open_interest == 100


def test_csv_requires_dated_contract(tmp_path):
    path=tmp_path/'bars.csv'
    path.write_text('timestamp,open,high,low,close,volume\n2026-01-05T14:30Z,100,102,99,101,10\n')
    with pytest.raises(ValueError, match="Dated contract"):
        CSVProvider(path,"ES",SessionCalendar()).load()


def test_daily_csv_cannot_be_used_as_intraday(tmp_path):
    path=tmp_path/'daily.csv'
    path.write_text('date,open,close\n2026-01-05,100,101\n')
    with pytest.raises(ValueError, match="CSV requires"):
        CSVProvider(path,"ES",SessionCalendar()).load()


def test_off_tick_and_contract_root_validation():
    report=validate([make_bar(opening=100.1)],SessionCalendar())
    assert report.off_tick_prices == 1
    with pytest.raises(ValueError):
        replace(make_bar(), contract="NQZ26")


def test_misaligned_bar_timestamp_rejected():
    with pytest.raises(ValueError,match='aligned'):
        validate([make_bar('2026-01-05T09:30:30')],SessionCalendar())


def test_dated_extra_halt_and_unknown_override_rejected():
    calendar=SessionCalendar(overrides={'2026-01-05':{'breaks':[['12:00','12:15']]}})
    assert calendar.classify(local_at(date(2026,1,5),'12:05')) is None
    assert calendar.classify(local_at(date(2026,1,5),'12:15')) is not None
    with pytest.raises(ValueError,match='unsupported fields'):
        SessionCalendar(overrides={'2026-01-05':{'clsoed':True}})
