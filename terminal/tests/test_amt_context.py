from datetime import date, timedelta

from terminal.amt.context import profile_context
from terminal.amt.model import Bar, session_bounds
from terminal.amt.source import Sample, scope_dates
from terminal.tests.test_amt_profile import amt_client  # noqa: F401


def test_trading_date_scope_calendar_boundaries():
    day = date(2026, 3, 2)
    assert scope_dates('week', day, None, None) == (day, day)
    assert scope_dates('prior_week', day, None, None) == (date(2026, 2, 23), date(2026, 3, 1))
    assert scope_dates('month', day, None, None) == (date(2026, 3, 1), day)
    assert scope_dates('prior_month', date(2024, 3, 1), None, None) == (date(2024, 2, 1), date(2024, 2, 29))


def test_descriptive_features_use_inclusive_value_and_complete_ib():
    day = date(2026, 3, 13)
    start, _ = session_bounds(day, 'RTH')
    bars = [Bar(start, 2, 8, 6, 1), Bar(start + timedelta(minutes=1), 0, 10, 5, 1)]
    current = {'val_tick': 4, 'vah_tick': 7, 'poc': {'low_tick': 6}}
    previous = {'val_tick': 2, 'vah_tick': 5, 'poc': {'low_tick': 3}}
    data = profile_context([Sample(day, bars, {}, None, 1380)], start + timedelta(minutes=2), current, previous, 1)
    assert data['value_width_ticks'] == 4
    assert data['previous_value_overlap'] == .5
    assert data['poc_migration_ticks'] == 3
    assert data['observed_range']['last_close_location'] == .5
    assert data['initial_balance_extension'][0]['above_ticks'] == 2
    assert data['initial_balance_extension'][0]['below_ticks'] == 2


def test_context_reports_missing_prior_instead_of_promoting_partial_fixture(amt_client):
    params = dict(contract='NQM26', session='2026-03-19', scope='week', display='RTH')
    response = amt_client.get('/api/amt/context', params=params)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['context']['value_width_ticks'] > 0
    assert data['context']['poc_migration_ticks'] is None
    assert data['coverage']['contributing_sessions'] == ['2026-03-17', '2026-03-19']
    assert data['coverage']['all_declared_sessions_complete'] is False
    assert any(s['status'] == 'excluded' for s in data['coverage']['sessions'])


def test_capability_does_not_claim_trade_level_or_execution(amt_client):
    data = amt_client.get('/api/amt/capabilities').json()
    assert data['profile_methods'] == ['hlc3', 'uniform']
    assert data['trade_exact'] is data['execution_eligible'] is data['replay']['adjusted'] is False


def test_gap_and_roll_lineage_exclude_unelapsed_details(amt_client):
    params = dict(contract='NQ1! Raw', session='2026-03-16', replay=True, as_of='2026-03-16T13:33:30Z')
    response = amt_client.get('/api/amt/profile', params=params)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['profile']['total_volume'] == 0
    assert data['coverage']['sessions'][0]['status'] == 'developing'
    quality = data['coverage']['quality']
    assert quality['intervals'][0]['end_exclusive_utc'] == '2026-03-16T13:33:30+00:00'
    assert quality['unresolved_roll_ids'] == []
    assert 'overlap' not in quality['rolls'][0]
