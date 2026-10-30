from dataclasses import replace
from datetime import date, timedelta
import pytest
from backtester.features import VWAP, FeatureEngine
from backtester.sessions import SessionCalendar, local_at
from conftest import make_bar, day_bars


def test_vwap_math_and_zero_volume():
    vwap=VWAP("close")
    assert vwap.update(make_bar(volume=0)) is None
    assert vwap.update(make_bar(close=10, opening=10, volume=2)) == 10
    assert vwap.update(make_bar(close=20, opening=20, volume=3)) == 16
    assert vwap.update(make_bar(close=1000, opening=1000, volume=0)) == 16


@pytest.mark.parametrize("basis,expected", [("typical",104/3),("close",34),("ohlc4",134/4)])
def test_price_basis(basis, expected):
    bar=make_bar(opening=30, high=40, low=30, close=34)
    assert VWAP(basis).update(bar) == pytest.approx(expected)


def test_session_reset_and_week_carry():
    engine=FeatureEngine(SessionCalendar(),basis="close")
    first=make_bar("2026-01-04T18:00",opening=100,volume=2)
    second=make_bar("2026-01-05T18:00",opening=110,volume=2)
    engine.update(first)
    values=engine.update(second)
    assert values['session_vwap'] == 110
    assert values['weekly_vwap'] == 105
    assert not values['weekly_vwap_complete']  # Missing previous session bars.
    values=engine.update(make_bar("2026-01-11T18:00",opening=120))
    assert values['weekly_vwap'] == 120


def test_complete_rth_previous_levels_and_overnight():
    calendar=SessionCalendar()
    engine=FeatureEngine(calendar,basis="close")
    monday=day_bars()
    for bar in monday:
        engine.update(bar)
    values=engine.update(make_bar("2026-01-05T18:00",opening=110))
    assert values['PDH'] == 101
    assert values['PDL'] == 99
    assert values['PDC'] == 100
    assert values['previous_day_complete']
    assert values['ONH'] == 111
    assert values['ONL'] == 109
    assert values['Session_Open'] == 110


def test_partial_previous_rth_does_not_claim_complete_levels():
    engine=FeatureEngine(SessionCalendar())
    engine.update(make_bar())
    values=engine.update(make_bar("2026-01-05T18:00"))
    assert values['PDH'] is None
    assert not values['previous_day_complete']


def test_overnight_levels_freeze_at_rth_and_vwap_buckets():
    calendar=SessionCalendar()
    engine=FeatureEngine(calendar,basis='close')
    bars=day_bars()
    for bar in bars:
        if calendar.classify(bar.timestamp).session == 'RTH':
            value=engine.update(replace(bar,open=200,high=201,low=199,close=200))
            break
        engine.update(bar)
    assert value['ONH'] == 101
    assert value['ONL'] == 99
    assert value['overnight_vwap'] == 100
    assert value['rth_vwap'] == 200
    assert value['RTH_Open'] == 200


def test_initial_balance_not_final_until_window_complete():
    engine=FeatureEngine(SessionCalendar(),ib_minutes=60)
    for i in range(59):
        values=engine.update(make_bar(local_at(date(2026,1,5),'09:30')+timedelta(minutes=i)))
        assert values['IBH'] is None
    values=engine.update(make_bar('2026-01-05T10:29',opening=105))
    assert values['IBH'] == 106
    assert values['IBL'] == 99
    assert values['ib_complete']
    values=engine.update(make_bar('2026-01-05T10:30',opening=200))
    assert values['IBH'] == 106


def test_missing_ib_bar_never_claims_full_initial_balance():
    engine=FeatureEngine(SessionCalendar(),ib_minutes=5)
    for i in [0,1,3,4,5]:
        values=engine.update(make_bar(local_at(date(2026,1,5),'09:30')+timedelta(minutes=i)))
    assert values['IBH'] is None
    assert values['day_gap']


def test_atr_and_snapshot_immutability():
    engine=FeatureEngine(SessionCalendar(),atr_period=2)
    first=engine.update(make_bar(opening=100))
    second=engine.update(make_bar('2026-01-05T09:31',opening=104))
    assert first['ATR'] is None
    assert second['ATR'] == 3.5
    with pytest.raises(TypeError):
        first['ATR']=100


def test_future_data_does_not_change_any_earlier_feature():
    bars=day_bars(minutes=5)
    original=FeatureEngine(SessionCalendar())
    changed=FeatureEngine(SessionCalendar())
    earlier=[dict(original.update(b)) for b in bars[:200]]
    same=[dict(changed.update(b)) for b in bars[:200]]
    for b in bars[200:]:
        original.update(b)
        changed.update(replace(b,open=900,high=901,low=899,close=900,volume=100000))
    assert earlier == same
    assert earlier[-1]['weekly_vwap'] == 100
