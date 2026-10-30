import csv,json,subprocess,sys
from dataclasses import asdict
from pathlib import Path
from conftest import make_bar,day_bars


def write_csv(path,bars):
    with path.open('w',newline='') as f:
        writer=csv.writer(f)
        writer.writerow(['timestamp','open','high','low','close','volume','contract','symbol'])
        for b in bars:
            writer.writerow([b.timestamp.isoformat(),b.open,b.high,b.low,b.close,b.volume,b.contract,b.symbol])


def command(*args):
    return subprocess.run([sys.executable,'-m','backtester',*map(str,args)],capture_output=True,text=True)


def test_cli_validate_run_report_reproducibility(tmp_path):
    path=tmp_path/'data.csv'
    write_csv(path,[make_bar(),make_bar('2026-01-05T09:31')])
    validation=command('validate-data',path,'--symbol','ES')
    assert validation.returncode==0,validation.stderr
    assert json.loads(validation.stdout)['rows']==2
    output=tmp_path/'results'
    args=('run','--strategy','weekly-vwap-reaction-v1','--symbol','ES','--data',path,'--output',output)
    one=command(*args)
    assert one.returncode==0,one.stderr
    first=next(output.iterdir())
    metadata=json.loads((first/'metadata.json').read_text())
    assert metadata['data_sha256']
    assert metadata['code']['sha256']
    assert metadata['execution_costs']['slippage_ticks']==1
    assert metadata['calendar']['template']=='equity'
    report=command('report',first.name,'--output',output)
    assert report.returncode==0,report.stderr
    assert json.loads(report.stdout)['total_trades']==0
    two=command(*args)
    assert two.returncode==0,two.stderr
    second=next(p for p in output.iterdir() if p!=first)
    assert (first/'features.json').read_bytes()==(second/'features.json').read_bytes()
    assert (first/'summary.json').read_bytes()==(second/'summary.json').read_bytes()


def test_cli_missing_bars_requires_explicit_opt_in(tmp_path):
    path=tmp_path/'data.csv'
    write_csv(path,[make_bar(),make_bar('2026-01-05T09:33')])
    output=tmp_path/'results'
    args=('run','--symbol','ES','--data',path,'--output',output)
    assert command(*args).returncode!=0
    accepted=command(*args,'--allow-missing')
    assert accepted.returncode==0,accepted.stderr


def test_unknown_config_keys_fail(tmp_path):
    path=tmp_path/'data.csv'
    write_csv(path,[make_bar()])
    config=tmp_path/'config.json'
    config.write_text('{"commision_typo":2}')
    result=command('validate-data',path,'--symbol','ES','--config',config)
    assert result.returncode!=0
    assert 'Unknown config' in result.stderr
