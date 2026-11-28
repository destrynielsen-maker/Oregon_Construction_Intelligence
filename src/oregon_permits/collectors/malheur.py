"""Issued primary structural permits from Malheur County's public monthly reports."""
from __future__ import annotations

import calendar
from datetime import date, datetime
import hashlib
from html.parser import HTMLParser
from io import BytesIO
import re
from urllib.parse import urljoin, urlsplit

from pypdf import PdfReader
from requests import Session

from .base import CollectionResult
from ..models import Permit


ISSUED_REPORT = re.compile(r"Permits Issued Details? ([A-Za-z]+) (\d{4})", re.I)
MONTHS = {name.casefold(): number for number, name in enumerate(calendar.month_name) if name}
ISSUE_ROW = re.compile(
    r"^([A-Z0-9-]+)[ \t]+Issued:[ \t]*(\d{1,2}/\d{1,2}/\d{2,4})[ \t]+"
    r"Fees:[ \t]*\$[\d,.]+[ \t]+Valuation:[ \t]*\$([\d,.]+)[ \t]*$", re.M
)
RECORD_NUMBER = re.compile(r"541-\d{2}-\d{6}-[A-Z]+(?:-\d+)?")
PRIMARY_NUMBER = re.compile(r"541-\d{2}-\d{6}-STR")
REPORT_PERIOD = re.compile(r"^(\d{1,2}/\d{1,2}/\d{4}) through (\d{1,2}/\d{1,2}/\d{4})$", re.M)
PRIMARY_USES = {
    "single family dwelling": ("residential", 1),
    "two family dwelling": ("residential", 2),
    "multi-family dwelling": ("residential", None),
    "multifamily dwelling": ("residential", None),
    "commercial": ("commercial", None),
}
NON_PRIMARY = re.compile(
    r"\b(?:accessory dwelling|ADU|detached garage|detached carport|"
    r"generator foundation|foundation only|manufactured (?:home|dwelling)|"
    r"remodel|renovation|tenant improvement|change of occupancy|demolition)\b",
    re.I,
)


class _ReportLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.href = None
        self.label = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.label = []

    def handle_data(self, data):
        if self.href:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            self.links.append((" ".join("".join(self.label).split()), self.href))
            self.href = None


class MalheurCollector:
    name = "Malheur County"
    source_url = "https://bldgmalheurco.org/news-updates/"
    freshness_days = 45
    months_to_read = 2
    max_bytes = 2_000_000

    @staticmethod
    def _report_url(href):
        url = urljoin(MalheurCollector.source_url, href)
        parsed = urlsplit(url)
        if (
            parsed.scheme == "https" and parsed.netloc == "bldgmalheurco.org"
            and re.fullmatch(r"/wp-content/uploads/\d{4}/\d{2}/[^/]+\.pdf", parsed.path, re.I)
            and not parsed.query and not parsed.fragment
        ):
            return url
        return None

    def _get(self, session, url):
        body = bytearray()
        with session.get(url, timeout=(8, 20), allow_redirects=False, stream=True) as response:
            response.raise_for_status()
            if response.status_code != 200 or response.url != url:
                raise RuntimeError("Unexpected Malheur source response or redirect")
            for chunk in response.iter_content(chunk_size=65536):
                if len(body) + len(chunk) > self.max_bytes:
                    raise RuntimeError("Malheur source exceeds input size limit")
                body.extend(chunk)
        return bytes(body)

    def _reports(self, html, today):
        index = _ReportLinks()
        index.feed(html.decode("utf-8", errors="replace"))
        index.close()
        reports = {}
        for label, href in index.links:
            match = ISSUED_REPORT.fullmatch(label)
            if not match:
                continue
            month = MONTHS.get(match[1].casefold())
            if not month:
                continue
            period = date(int(match[2]), month, 1)
            if period >= today.replace(day=1):
                continue
            reports.setdefault(period, set()).add(href)
        selected = []
        for period in sorted(reports, reverse=True)[:self.months_to_read]:
            urls = {self._report_url(href) for href in reports[period]}
            if None in urls:
                raise RuntimeError("Malheur issued report points outside its official PDF archive")
            if len(urls) != 1:
                raise RuntimeError("Multiple Malheur reports claim the same month")
            selected.append((period, urls.pop()))
        if len(selected) != self.months_to_read or len({url for _, url in selected}) != self.months_to_read:
            raise RuntimeError("Distinct Malheur issued PDF reports are missing")
        return selected

    @staticmethod
    def _date(value):
        fmt = "%m/%d/%Y" if len(value.rsplit("/", 1)[-1]) == 4 else "%m/%d/%y"
        return datetime.strptime(value, fmt).date()

    def _parse(self, content, url, start):
        if not content.startswith(b"%PDF-") or len(content) > self.max_bytes:
            raise RuntimeError("Invalid Malheur issued report bytes")
        pdf = PdfReader(BytesIO(content))
        if not 1 <= len(pdf.pages) <= 100:
            raise RuntimeError("Unexpected Malheur issued report page count")
        pages = [page.extract_text() for page in pdf.pages]
        end = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
        period = REPORT_PERIOD.search(pages[0])
        if (
            not re.search(r"^MALHEUR COUNTY BUILDING DEPARTMENT$", pages[0], re.M)
            or not re.search(r"^Permits Issued$", pages[0], re.M)
            or not re.search(r"^Record Types Selected:[ \t]*-All-$", pages[0], re.M)
            or not period or tuple(map(self._date, period.groups())) != (start, end)
        ):
            raise RuntimeError("Malheur report authority, issuance label, or month could not be verified")

        count = re.findall(r"^\s*(\d+) permits issued[ \t]+\$", pages[-1], re.M | re.I)
        if len(count) != 1:
            raise RuntimeError("Malheur report grand total is missing or ambiguous")
        digest = hashlib.sha256(content).hexdigest()
        numbers = set()
        permits = []
        latest_issue = None
        for page_number, text in enumerate(pages, 1):
            rows = list(ISSUE_ROW.finditer(text))
            for index, match in enumerate(rows):
                number, printed_date, value = match.groups()
                issued = self._date(printed_date)
                if not RECORD_NUMBER.fullmatch(number) or number in numbers or not start <= issued <= end:
                    raise RuntimeError("Unexpected Malheur issuer, duplicate record, or out-of-month issue date")
                numbers.add(number)
                latest_issue = max(latest_issue or issued, issued)
                if not PRIMARY_NUMBER.fullmatch(number):
                    continue
                block_end = rows[index + 1].start() if index + 1 < len(rows) else len(text)
                block = text[match.end():block_end]
                permit = self._primary_permit(number, issued, value, block, url, page_number, digest, start, end)
                if permit:
                    permits.append(permit)
        if len(numbers) != int(count[0]):
            raise RuntimeError("Malheur permit rows do not reconcile to the printed grand total")
        return permits, len(numbers), latest_issue

    def _primary_permit(self, number, issued, value, block, url, page, digest, start, end):
        kind = re.search(r"^Category of Construction:[ \t]*(.*?)[ \t]*Type of Work:[ \t]*(.*)$", block, re.M)
        if not kind:
            raise RuntimeError("Malheur primary structural permit lacks work and category labels")
        use, work = (part.strip() for part in kind.groups())
        category = PRIMARY_USES.get(use.casefold())
        if work.casefold() != "new" or not category:
            return None
        address = re.search(r"^(.+?)[ \t]+[A-Z0-9-]+Address:[ \t]*Parcel:[ \t]*$", block, re.M)
        description = re.search(r"^Work Description:[ \t]*(\S[^\n]*)", block, re.M)
        if not address or not description:
            raise RuntimeError("Malheur new primary permit lacks site address or work description")
        if NON_PRIMARY.search(description[1]):
            return None
        report_kind, units = category
        return Permit(
            state="OR", jurisdiction=self.name, permit_number=number,
            issued_date=issued.isoformat(), permit_type=f"{report_kind.title()} Structural",
            building_use=use, project_name=description[1].strip(), address=address[1].strip(),
            units=units, valuation=float(value.replace(",", "")), status="Issued",
            source_name="Malheur County Building Department", source_url=f"{url}#page={page}",
            raw={
                "work_proposed": "New", "type_of_use": use, "report_kind": report_kind,
                "source_building_family_authoritative": True, "source_new_construction_subtype": True,
                "source_issued_validated": True, "issuing_agency_code": "541",
                "report_sha256": digest, "report_period_start": start.isoformat(),
                "report_period_end": end.isoformat(), "source_page": page,
            },
        )

    def collect(self, session=None, today=None):
        today = today or date.today()
        if session is None:
            with Session() as public_session:
                public_session.headers["User-Agent"] = "OregonConstructionIntelligence/0.1 (+public-permit-research)"
                return self.collect(public_session, today)
        reports = self._reports(self._get(session, self.source_url), today)
        permits = {}
        inspected = 0
        latest_issue = None
        for month, url in reports:
            rows, total, latest = self._parse(self._get(session, url), url, month)
            inspected += total
            if latest:
                latest_issue = max(latest_issue or latest, latest)
            for permit in rows:
                if permit.key in permits:
                    raise RuntimeError("Malheur structural permit is repeated across monthly reports")
                permits[permit.key] = permit
        return CollectionResult(
            self.name,
            sorted(permits.values(), key=lambda p: (p.issued_date, p.permit_number), reverse=True),
            self.source_url,
            f"{len(reports)} completed monthly PDFs; {inspected} issued rows reconciled to printed totals. "
            f"Latest issue across report types: {latest_issue or 'none'}. "
            "Primary new structural permits for Malheur issuer 541 only. Ontario issuer 653 is separate. "
            "Licensed professional entries do not establish a contractor role.",
        )
