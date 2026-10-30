"""Offline, auditable charts of raw-contract realized measurements.

Matplotlib is optional (install the charts extra). No plotting dependency is
imported by the engine or scalar estimators. Chart units: 1 bp = 1e-4 log return;
variance in bp² = variance * 1e8; volatility in % = sqrt(variance) * 100.
"""
from collections import OrderedDict
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
import argparse
import html
import json
import math
import shutil

from .cli import objects, read_config, sha256
from .reports import serial
from .rolls import ContinuousSeries, RollConfig
from .sessions import NY
from .volatility import RealizedVolatility, log_return


COLORS = ('#61a7ff', '#f2bd70', '#46c7ac', '#ad9af7', '#ec7e92')
BACKGROUND = '#101722'
FOREGROUND = '#c6d2e2'
UP = '#46c7ac'
DOWN = '#ec7e92'


def prepare_sessions(selected, calendar, threshold=None):
    """Consume causal selected bars, retaining raw prices and immutable prefixes.

    Returns grouped session/contract points. Missing/UNKNOWN returns are null;
    plots never bridge a contract, closure or a missing minute. Session totals
    come directly from the measurement layer, never chart-side estimators.
    """
    stream = RealizedVolatility(calendar, tbpv_squared_threshold=threshold)
    groups = OrderedDict()
    previous = None
    previous_key = None
    for item in selected:
        bar = item.raw
        row = stream.update(bar, as_of=bar.end)
        key = (row.trading_date.isoformat(), bar.contract)
        adjacent = (previous is not None and key == previous_key and
                    previous.end == bar.timestamp and previous.coverage_state != 'UNKNOWN')
        reference = previous.close if adjacent else bar.open
        r = None if bar.coverage_state == 'UNKNOWN' else log_return(reference, bar.close)
        group = groups.setdefault(key, {'date': key[0], 'contract': key[1], 'points': [], 'roll': item.roll, 'source': bar.provider or 'local OHLCV; source unverified'})
        group['session_open'] = calendar.classify(bar.timestamp).open
        if previous is not None and key == previous_key and previous.end != bar.timestamp:
            group['points'].append({'timestamp': previous.end, 'close': None, 'return': None, 'record': None, 'bar': None, 'segment_open': None})
        group['points'].append({'timestamp': bar.end, 'close': bar.close if r is not None else None,
                                'return': r, 'record': row, 'bar': bar,
                                'segment_open': calendar.classify(bar.timestamp).segment_open})
        group['last'] = row
        previous, previous_key = bar, key
    if not groups:
        raise ValueError('No completed bars for charts')
    return list(groups.values())


def _numbers(groups, name, scale=1, root=False):
    values = []
    for group in groups:
        value = getattr(group['last'], name)
        values.append(float('nan') if value is None else (math.sqrt(value) if root else value) * scale)
    return values


def _save(fig, stem):
    fig.savefig(stem.with_suffix('.png'), dpi=145, facecolor=BACKGROUND)
    fig.savefig(stem.with_suffix('.svg'), metadata={'Date': None}, facecolor=BACKGROUND)


def aggregate_ohlcv(points, minutes):
    """Raw OHLCV over complete segment-anchored blocks; never bridge missing bars.

    Returns [open_epoch_ms, open, high, low, close, volume]. A k-minute bar needs
    exactly k consecutive known source minutes. This display aggregation does not
    alter the realized measurements. Rolls are already separated into groups.
    """
    if minutes not in (1, 5, 15):
        raise ValueError('Chart intervals must be 1, 5 or 15 minutes')
    blocks = OrderedDict()
    for point in points:
        bar = point['bar']
        if bar is None or bar.coverage_state == 'UNKNOWN':
            continue
        anchor = point['segment_open']
        offset = int((bar.timestamp - anchor) / timedelta(minutes=1))
        start = anchor + timedelta(minutes=offset // minutes * minutes)
        blocks.setdefault(start, []).append(bar)
    result = []
    for start, bars in blocks.items():
        if len(bars) != minutes or any(b.timestamp != start + timedelta(minutes=i) for i, b in enumerate(bars)):
            continue
        result.append([int(start.timestamp()*1000), bars[0].open, max(b.high for b in bars),
                       min(b.low for b in bars), bars[-1].close, math.fsum(b.volume for b in bars)])
    return result


def aggregate_session_ohlcv(group, minutes):
    """Session-open anchored higher bars, including the scheduled closing tail.

    Only complete sessions qualify. Planned closures are not missing data; raw
    contracts remain separate. A daily bar covers one futures trading session.
    """
    if minutes not in (60, 240, 1440):
        raise ValueError('Higher chart intervals must be 60, 240 or 1440 minutes')
    if not group['last'].session_complete:
        return []
    bars = [p['bar'] for p in group['points'] if p['bar'] is not None]
    if not bars or any(b.coverage_state == 'UNKNOWN' for b in bars):
        return []
    blocks = OrderedDict()
    opened = group['session_open']
    for bar in bars:
        offset = int((bar.timestamp-opened)/timedelta(minutes=1))
        start = opened if minutes == 1440 else opened+timedelta(minutes=offset//minutes*minutes)
        blocks.setdefault(start, []).append(bar)
    return [[int(start.timestamp()*1000), chunk[0].open, max(b.high for b in chunk),
             min(b.low for b in chunk), chunk[-1].close, math.fsum(b.volume for b in chunk)]
            for start, chunk in blocks.items()]


def _chart_payload(groups):
    sessions = []
    for group in groups:
        records = [p for p in group['points'] if p['record'] is not None]
        def value(row, name, scale=1):
            v = getattr(row, name)
            return v*scale if v is not None else None
        series = []
        for point in group['points']:
            row = point['record']
            series.append([int(point['timestamp'].timestamp()*1000),
                           point['return']*1e4 if point['return'] is not None else None,
                           *[value(row, key, 1e8) if row else None for key in
                             ('rv_intraday_to_now', 'rv_rth', 'rv_overnight', 'rv_post_rth')],
                           value(row, 'profile_variance_share', 100) if row else None,
                           value(row, 'observed_rv', 1e8) if row else None])
        rth = [p['bar'] for p in records if p['record'].segment == 'RTH']
        row = group['last']
        sessions.append(dict(date=group['date'], contract=group['contract'],
                             complete=row.session_complete, prefix_complete=row.prefix_complete,
                             missing=row.missing_bars_to_now, unknown=row.unknown_bars,
                             references=row.profile_reference_sessions, series=series,
                             bars={**{str(k):aggregate_ohlcv(group['points'], k) for k in (1,5,15)},
                                   **{str(k):aggregate_session_ohlcv(group,k) for k in (60,240,1440)}},
                             rth=[int(rth[0].timestamp.timestamp()*1000), int(rth[-1].end.timestamp()*1000)] if rth else None))
    return dict(instrument=groups[0]['last'].instrument, sessions=sessions)


def render_charts(groups, output, *, data_hash, calendar_source):
    """Export separate scientific charts and an offline OHLCV chart viewer.

    Output is exclusive. HTML contains only chart panels, axes, legends and chart
    controls. Provenance/coverage remains in measurements.json. Interactive OHLC
    bars use complete 1/5/15m source blocks with synchronized volume underneath.
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from matplotlib.collections import LineCollection
        from matplotlib.ticker import FuncFormatter
    except ImportError as error:
        raise ValueError('Charts require Matplotlib: python -m pip install -e ".[charts]"') from error
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'sessions').mkdir()
    (output / 'overview').mkdir()
    plt.rcParams.update({'font.size':11, 'font.family':'DejaVu Sans', 'svg.fonttype':'none',
                         'figure.facecolor':BACKGROUND, 'axes.facecolor':BACKGROUND,
                         'axes.edgecolor':'#293445', 'axes.labelcolor':FOREGROUND,
                         'text.color':FOREGROUND, 'xtick.color':'#91a0b5', 'ytick.color':'#91a0b5',
                         'axes.spines.top':False, 'axes.spines.right':False,
                         'grid.color':'#263344', 'grid.alpha':.55, 'grid.linewidth':.6,
                         'axes.titlepad':22, 'axes.titlesize':15, 'axes.titleweight':'normal',
                         'legend.frameon':False, 'legend.labelcolor':FOREGROUND})
    complete = [g for g in groups if g['last'].session_complete]
    x = list(range(len(complete)))
    labels = [g['date'][5:]+'\n'+g['contract'] for g in complete]
    specs = [('sampling','Realized volatility by sampling interval','Volatility (%)',
              [('rv_1m','1 minute',COLORS[0]),('rv_5m','5 minutes',COLORS[2]),('rv_15m','15 minutes',COLORS[1])],100,True),
             ('variation','Realized variance and bipower variation','Variance (bp²)',
              [('rv_1m','RV',COLORS[0]),('bpv','BPV',COLORS[3])],1e8,False),
             ('jumps','Jump variation proxy','Variance (bp²)',[('jump','max(RV − BPV, 0)',COLORS[1])],1e8,False),
             ('direction','Positive and negative semivariance','Variance (bp²)',[],1e8,False),
             ('segments','Variation by trading session','Variance (bp²)',[],1e8,False),
             ('quarticity','Realized quarticity','Log return⁴',[('quarticity','RQ',COLORS[3])],1,False),
             ('range','Close-return and range variation','Variance (bp²)',
              [('rv_1m','Close-return RV',COLORS[0]),('realized_range','Parkinson range',COLORS[2])],1e8,False)]
    overview = []
    for name,title,unit,fields,scale,root in specs:
        fig,ax=plt.subplots(figsize=(12,4.2),layout='constrained')
        if name in ('direction','segments'):
            stack = [('rs_positive','Positive',UP),('rs_negative','Negative',DOWN)] if name=='direction' else [
                ('rv_overnight','Overnight',COLORS[3]),('rv_rth','RTH',COLORS[0]),('rv_post_rth','Post-RTH',COLORS[2])]
            bottom=[0.]*len(complete)
            for field,label,color in stack:
                values=_numbers(complete,field,1e8)
                ax.bar(x,values,bottom=bottom,color=color,label=label,width=.52)
                bottom=[a+b if math.isfinite(b) else a for a,b in zip(bottom,values)]
        else:
            for i,(field,label,color) in enumerate(fields):
                values=_numbers(complete,field,scale,root)
                if name=='jumps':
                    ax.bar(x,values,color=color,width=.52,label=label)
                else:
                    ax.plot(x,values,color=color,label=label,marker=('o','s','^')[i],
                            markersize=5,linewidth=2,linestyle=('-','--',':')[i])
        ax.set(title=title,ylabel=unit)
        ax.set_xticks(x,labels,fontsize=9)
        ax.margins(x=.045)
        ax.grid(axis='y')
        ax.set_axisbelow(True)
        ax.legend(loc='upper left',ncols=3,fontsize=10)
        if name=='quarticity':
            ax.ticklabel_format(axis='y',style='sci',scilimits=(0,0))
        if not complete:
            ax.text(.5,.5,'No complete sessions',transform=ax.transAxes,ha='center')
        _save(fig,output/'overview'/name)
        plt.close(fig)
        plot_fields=stack if name in ('direction','segments') else fields
        plotted=[]
        for field,label,color in plot_fields:
            values=_numbers(complete,field,scale,root)
            plotted.append(dict(label=label,color=color,points=[dict(time=g['date'],value=v if math.isfinite(v) else None)
                                                              for g,v in zip(complete,values)]))
        overview.append(dict(id=name,title=title,unit=unit,series=plotted,histogram=name=='jumps'))
    payload=_chart_payload(groups)
    payload["overview"]=overview
    for group,session in zip(groups,payload['sessions']):
        row=group['last']
        stem=output/'sessions'/(group['date']+'-'+group['contract'])
        bars=session['bars']['5'] or session['bars']['1']
        fig,(price,volume)=plt.subplots(2,1,sharex=True,figsize=(13,7),
                                      gridspec_kw={'height_ratios':[4,1]},layout='constrained')
        if bars:
            xs=[mdates.date2num(datetime.fromtimestamp(b[0]/1000,NY)) for b in bars]
            tick_width=(5 if session['bars']['5'] else 1)/1440*.30
            segments=[]; colors=[]
            for t,b in zip(xs,bars):
                _,o,h,l,c,v=b
                color=UP if c>=o else DOWN
                segments.extend([[(t,l),(t,h)],[(t-tick_width,o),(t,o)],[(t,c),(t+tick_width,c)]])
                colors.extend([color]*3)
            price.add_collection(LineCollection(segments,colors=colors,linewidths=.85))
            price.autoscale_view()
            volume.bar(xs,[b[5] for b in bars],width=tick_width*1.7,
                       color=[UP if b[4]>=b[1] else DOWN for b in bars],alpha=.65)
        price.set(title=f"{row.instrument}  /  {group['date']}  /  {group['contract']}  ·  OHLC",ylabel='Price')
        volume.set(ylabel='Volume')
        volume.yaxis.set_major_formatter(FuncFormatter(lambda v,_: f'{v/1000:g}k' if v>=1000 else f'{v:g}'))
        for ax in (price,volume):
            ax.grid(axis='y')
            if session['rth']:
                ax.axvspan(*[mdates.date2num(datetime.fromtimestamp(t/1000,NY)) for t in session['rth']],color=COLORS[0],alpha=.04)
        volume.xaxis.set_major_locator(mdates.HourLocator(interval=3,tz=NY))
        volume.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M',tz=NY))
        volume.set_xlabel('America/New_York')
        _save(fig,stem.with_name(stem.name+'-ohlcv'))
        plt.close(fig)
    template=Path(__file__).with_name('volatility_chart_template.html').read_text()
    encoded=json.dumps(payload,allow_nan=False,separators=(",", ":")).replace("<", chr(92)+"u003c")
    charts=''.join('<section class="chart overview"><div class="chart-header"><h2>'+html.escape(chart['title'])+
        '</h2><div class="legend">'+''.join('<span><i style="background:'+entry['color']+'"></i>'+html.escape(entry['label'])+
        '</span>' for entry in chart['series'])+'</div></div><div id="overview-'+chart['id']+
        '" class="chart-host" role="group" aria-label="'+html.escape(chart['title'])+'"></div><div class="chart-footer">'+
        html.escape(chart['unit'])+'</div></section>' for chart in overview)
    assets=output/'assets'
    assets.mkdir()
    package=Path(__file__).parent
    for name in ('volatility_chart_data.js','volatility_chart_ui.js'):
        shutil.copyfile(package/name,assets/name)
    for path in (package/'vendor').glob('lightweight-charts-*'):
        shutil.copyfile(path,assets/path.name)
    report=template.replace('__CHART_DATA__',encoded).replace('__OVERVIEW_CHARTS__',charts)
    (output/'index.html').write_text(report)
    (output/'measurements.json').write_text(json.dumps(dict(data_sha256=data_hash,calendar_source=calendar_source,
        records=[asdict(g['last']) for g in groups]),default=serial,indent=2,allow_nan=False)+'\n')
    return output/'index.html'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['volatility-charts'])
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--symbol', choices=['NQ','ES','GC'], required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--contract')
    parser.add_argument('--output', type=Path, required=True, help='New local report directory')
    parser.add_argument('--as-of', help='Aware ISO cutoff; exclude bars not yet completed')
    parser.add_argument('--tbpv-squared-threshold', type=float)
    args = parser.parse_args()
    args.interval = 1
    try:
        cutoff = datetime.fromisoformat(args.as_of.replace('Z','+00:00')) if args.as_of else None
        if cutoff and cutoff.tzinfo is None:
            raise ValueError('as-of requires timezone')
        config = read_config(args.config)
        _, calendar, provider = objects(args, config)
        digest = sha256(args.data)
        bars, _ = provider.load()
        if digest != sha256(args.data):
            raise ValueError('Data changed during ingestion')
        bars = tuple(b for b in bars if cutoff is None or b.end <= cutoff)
        if not bars:
            raise ValueError('No completed bars at cutoff')
        selected = ContinuousSeries(calendar, RollConfig(**config.get('roll', {}))).select(bars)
        groups = prepare_sessions(selected, calendar, args.tbpv_squared_threshold)
        report = render_charts(groups, args.output, data_hash=digest, calendar_source=calendar.source)
        print(json.dumps({'report':str(report.resolve()), 'sessions':len(groups),
                          'complete_sessions':sum(g['last'].session_complete for g in groups)},indent=2))
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
