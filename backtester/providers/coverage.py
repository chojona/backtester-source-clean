from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib,json
from ..sessions import SessionCalendar,NY


@dataclass(frozen=True)
class CoverageAssessment:
    state: str                 # PROVIDER_AVAILABLE or UNKNOWN
    evidence: str


class ProviderCoverage:
    def __init__(self, start, end, conditions, completed=False):
        self.start,self.end,self.completed=start,end,completed
        self.days={row['date']:row['condition'] for row in conditions}

    def at(self, timestamp, duration=timedelta(minutes=1)):
        if not self.completed or timestamp < self.start or timestamp+duration > self.end:
            return CoverageAssessment('UNKNOWN','Request incomplete or interval outside successfully downloaded range')
        first=timestamp.astimezone(timezone.utc).date().isoformat()
        last=(timestamp+duration-timedelta(microseconds=1)).astimezone(timezone.utc).date().isoformat()
        if all(self.days.get(day)=='available' for day in {first,last}):
            return CoverageAssessment('PROVIDER_AVAILABLE','Complete untruncated stream + provider daily condition=available; minute completeness is inferred, not independently proven')
        return CoverageAssessment('UNKNOWN','Provider day is degraded, pending, missing, or has no condition metadata')


# This source export carries no retained calendar evidence or historical pins.
# Empty registries reject strict trust until separately reviewed local evidence exists.
PINNED_DATED_CALENDAR_SHA256 = {}
PINNED_HISTORY_CALENDAR_SHA256 = {}
SUPPORTED_CME_REGIMES = {'R2_2012_EXTENSION', 'R3_2015_CLOSE_CHANGE', 'R4_NO_AFTERNOON_PAUSE'}


class DatedSessionCalendar(SessionCalendar):
    """A bounded explicit schedule; never derives exchange closures from empty data."""
    def __init__(self, document, source_path=None):
        allowed={'version','product','timezone','dates','source_urls','reviewed_at','status','source_files','notes'}
        if set(document)-allowed:
            raise ValueError('Unknown dated calendar fields')
        if document.get('product')!='NQ' or document.get('timezone')!='America/New_York':
            raise ValueError('Calendar must explicitly cover NQ in America/New_York')
        if not document.get('source_urls') or not document.get('version') or not document.get('dates'):
            raise ValueError('Calendar requires sources, version and explicit dates')
        self.document=document
        self.source_path=source_path
        self._trusted_anchor=None
        super().__init__(template='equity',breaks=[],overrides=document['dates'],
                         source='Dated NQ calendar '+document['version']+'; '+document.get('status','unverified'))

    def trusted_anchor(self):
        """Reviewed, hash-pinned anchor for strict use, or None.

        Re-verifies the calendar file hash against the pinned set and every
        ``source_files`` hash on each call, so replacing a file after load
        fails closed. Calendars built from caller dictionaries have no
        anchor and are never authoritative for Tier A.
        """
        anchor=getattr(self,'_trusted_anchor',None)
        if not anchor or not self.source_path:
            return None
        try:
            path=Path(self.source_path)
            file_sha=hashlib.sha256(path.read_bytes()).hexdigest()
            if anchor.get('kind')=='dated_calendar_file':
                if PINNED_DATED_CALENDAR_SHA256.get(file_sha)!=self.document.get('version') \
                        or file_sha!=anchor.get('file_sha256'):
                    return None
                if not self.document.get('reviewed_at') or 'review' not in str(self.document.get('status','')).lower():
                    return None
                if not self.document.get('source_files'):
                    return None
                for item in self.document['source_files']:
                    source=(path.parent/item['path']).resolve()
                    if not source.is_relative_to(path.parent.resolve()) \
                            or hashlib.sha256(source.read_bytes()).hexdigest()!=item['sha256']:
                        return None
            elif anchor.get('kind')=='history_calendar_file':
                if PINNED_HISTORY_CALENDAR_SHA256.get(file_sha)!=anchor.get('history_version') \
                        or file_sha!=anchor.get('file_sha256'):
                    return None
            else:
                return None
        except Exception:
            return None
        result=dict(anchor)
        result['document_sha256']=self.provenance()['document_sha256']
        return result

    @classmethod
    def from_history_document(cls, document, first, last):
        """Bridge nq-history evidence into this loadable schema (QUA-28/M2).

        Only trading dates covered by REVIEWED_REGULAR date evidence and by
        a regime whose open/close/pause rules this schema can express are
        converted (R2/R3/R4). Pre-2012 R1 date-assignment rules (QUA-29/M3),
        holiday-unresolved windows, and any unreviewed weekday fail closed:
        no exception or session is invented from regime prose.
        """
        from datetime import date as _date
        if document.get('version') != 'nq-history-v3.0.0' or document.get('timezone') != 'America/New_York':
            raise ValueError('Unsupported historical calendar evidence schema')
        first, last = _date.fromisoformat(str(first)), _date.fromisoformat(str(last))
        scope = document.get('scope', {})
        if first.isoformat() < scope.get('first_trading_date', '') or last.isoformat() > scope.get('last_trading_date', ''):
            raise ValueError('Historical calendar range outside evidenced scope')
        reviewed = []
        for entry in document.get('date_evidence', []):
            if entry.get('state') == 'REVIEWED_REGULAR':
                reviewed.append((_date.fromisoformat(entry['first']), _date.fromisoformat(entry['last'])))
        regimes = document.get('regimes', [])
        dates, day = {}, first
        while day <= last:
            if day.weekday() < 5:
                if not any(a <= day <= b for a, b in reviewed):
                    raise ValueError(f'No reviewed regular calendar evidence for {day}; fail closed')
                regime = next((r for r in regimes if r['first'] <= day.isoformat() <= r['last']), None)
                if regime is None or regime['id'] not in SUPPORTED_CME_REGIMES:
                    raise ValueError(f"Unsupported calendar regime for {day}; fail closed")
                override = {'eth_close': regime['close_et'], 'breaks': []}
                if regime.get('pause_et'):
                    start, end = regime['pause_et'].split('-')
                    override['breaks'] = [[start, end]]
                dates[day.isoformat()] = override
            day += timedelta(days=1)
        if not dates:
            raise ValueError('Historical calendar range contains no trading dates')
        converted = dict(version=f"{document['version']}+dated-bridge-v1", product='NQ',
                         timezone='America/New_York', dates=dates,
                         source_urls=['calendars/nq-history-v3.json'],
                         status=document.get('status', 'unverified'))
        return cls(converted)

    @classmethod
    def from_history_file(cls, path, first, last):
        raw=Path(path).read_bytes()
        calendar=cls.from_history_document(json.loads(raw), first, last)
        file_sha=hashlib.sha256(raw).hexdigest()
        if PINNED_HISTORY_CALENDAR_SHA256.get(file_sha)=='nq-history-v3.0.0':
            calendar.source_path=str(Path(path).resolve())
            calendar._trusted_anchor=dict(kind='history_calendar_file', file_sha256=file_sha,
                                          history_version='nq-history-v3.0.0')
        return calendar

    @classmethod
    def from_file(cls,path):
        raw=Path(path).read_bytes()
        document=json.loads(raw)
        for item in document.get('source_files',[]):
            source=(Path(path).parent/item['path']).resolve()
            if not source.is_relative_to(Path(path).parent.resolve()) or hashlib.sha256(source.read_bytes()).hexdigest()!=item['sha256']:
                raise ValueError('Calendar source file hash mismatch')
        calendar=cls(document,str(Path(path).resolve()))
        file_sha=hashlib.sha256(raw).hexdigest()
        if PINNED_DATED_CALENDAR_SHA256.get(file_sha)==document.get('version'):
            calendar._trusted_anchor=dict(kind='dated_calendar_file', file_sha256=file_sha)
        return calendar

    def classify(self,timestamp):
        if timestamp.tzinfo is None:
            raise ValueError('Timezone-aware timestamp required')
        local=timestamp.astimezone(NY)
        day=local.date()+timedelta(days=1) if local.hour>=18 else local.date()
        # Weekends are closed by the explicit exchange convention, but weekday exceptions must exist.
        if day.weekday()<5 and day.isoformat() not in self.document['dates']:
            raise ValueError('Dated calendar does not cover trading date '+day.isoformat())
        return super().classify(timestamp)

    def verify_range(self,start,end):
        probe=start
        while probe<end:
            self.classify(probe)
            probe+=timedelta(minutes=1)

    def provenance(self):
        payload=json.dumps(self.document,sort_keys=True,separators=(',',':')).encode()
        return dict(document=self.document,document_sha256=hashlib.sha256(payload).hexdigest(),source_path=self.source_path)
