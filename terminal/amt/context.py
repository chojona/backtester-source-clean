from .tpo import initial_balance


def profile_context(samples, cutoff, value, previous_value, ib_minutes):
    bars = [bar for sample in samples for bar in sample.bars]
    high = max((bar.high for bar in bars), default=None)
    low = min((bar.low for bar in bars), default=None)
    close = bars[-1].close if bars else None
    overlap = migration = width = None
    if value:
        width = value['vah_tick'] - value['val_tick'] + 1
        if previous_value:
            common = max(0, min(value['vah_tick'], previous_value['vah_tick'])
                         - max(value['val_tick'], previous_value['val_tick']) + 1)
            overlap = common / (previous_value['vah_tick'] - previous_value['val_tick'] + 1)
            migration = value['poc']['low_tick'] - previous_value['poc']['low_tick']

    extensions = []
    for sample in samples:
        balance = initial_balance(sample, cutoff, ib_minutes)
        after = [bar for bar in sample.bars if bar.time >= balance['end']]
        extensions.append({'initial_balance': balance,
                           'above_ticks': max(0, max(b.high for b in after) - balance['high_tick'])
                           if balance['complete'] and after else None,
                           'below_ticks': max(0, balance['low_tick'] - min(b.low for b in after))
                           if balance['complete'] and after else None})
    return {'value': value, 'value_width_ticks': width, 'previous_value_overlap': overlap,
            'poc_migration_ticks': migration, 'initial_balance_extension': extensions,
            'observed_range': {'low_tick': low, 'high_tick': high, 'last_close_tick': close,
                               'last_close_location': (close - low) / (high - low)
                               if bars and high > low else None}}
