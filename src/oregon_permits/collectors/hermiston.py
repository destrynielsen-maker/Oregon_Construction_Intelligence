"""City of Hermiston public issued-structural report collector."""
from __future__ import annotations

import calendar
import hashlib
from datetime import date, datetime
from io import BytesIO
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from pypdf import PdfReader

from .base import CollectionResult, new_session
from ..models import Permit


class HermistonCollector:
    name = "Hermiston"
    source_url = "https://www.hermiston.gov/commdev/page/issued-structural-permits-permits-archive"
    freshness_days = 45  # Monthly reports, not a daily feed.
    months_to_read = 2
    month_names = {n.casefold(): i for i, n in enumerate(calendar.month_name) if i}
    date_re = r"\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})(?!\d)"
    number_re = re.compile(r"^407-\d{2}-\d{6}-DWL$", re.I)
    permit_re = re.compile(r"^ *Permit:\s*([A-Z0-9-]+) *$", re.M | re.I)

    @staticmethod
    def _official_url(page, href, path_prefix):
        candidate = urljoin(page, href)
        parsed = urlparse(candidate)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "www.hermiston.gov"
            or not parsed.path.startswith(path_prefix)
            or parsed.query or parsed.fragment
        ):
            return None
        return candidate

    def _get(self, session, url, path_prefix):
        res = session.get(url, timeout=30, allow_redirects=False)
        res.raise_for_status()
        if res.status_code != 200 or not self._official_url(url, res.url, path_prefix):
            raise RuntimeError("Unexpected Hermiston response or destination")
        return res

    def _reports(self, session, today):
        page_path = "/commdev/page/"
        files_path = "/sites/default/files/fileattachments/community_development/page/"
        archive = self._get(session, self.source_url, page_path)
        years = {}
        for tag in BeautifulSoup(archive.text, "html.parser").select("a[href]"):
            label = tag.get_text(strip=True)
            if label not in (str(today.year), str(today.year - 1)):
                continue
            url = self._official_url(self.source_url, tag["href"], page_path)
            if url:
                years[int(label)] = url
        if not years:
            raise RuntimeError("Hermiston issued structural archive has no recent year pages")
        reports = {}
        for year, url in sorted(years.items(), reverse=True):
            page = self._get(session, url, page_path)
            soup = BeautifulSoup(page.text, "html.parser")
            for tag in soup.select(".related_files a[href]"):
                match = re.fullmatch(r"([A-Za-z]+) (\d{4})", tag.get_text(strip=True))
                if not match:
                    continue
                month = self.month_names.get(match[1].casefold())
                pdf = self._official_url(url, tag["href"], files_path)
                if not month or int(match[2]) != year or not pdf or not pdf.endswith(".pdf"):
                    continue
                ref = date(year, month, 1)
                if ref > today:
                    continue
                if ref in reports and reports[ref] != pdf:
                    raise RuntimeError("Ambiguous duplicate monthly Hermiston report")
                reports[ref] = pdf
            if len(reports) >= self.months_to_read:
                break
        if len(reports)<self.months_to_read:
            raise RuntimeError("Fewer than two official Hermiston structural report PDFs found")
        return sorted(reports.items(), reverse=True)[:self.months_to_read]

    @staticmethod
    def _date(value):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%m/%d/%Y" if len(value.rsplit("/",1)[-1]) == 4 else "%m/%d/%y").date()
        except ValueError:
            return None

    def _parse(self, content, url, month, today):
        if not content.startswith(b"%PDF-") or len(content) > 2_000_000:
            raise RuntimeError("Unexpected Hermiston structural report content")
        pdf = PdfReader(BytesIO(content))
        if not 1 <= len(pdf.pages) <= 100:
            raise RuntimeError("Unexpected Hermiston structural report page count")
        pages = [p.extract_text(extraction_mode="layout") for p in pdf.pages]
        first = pages[0]
        date_span = re.search(fr"({self.date_re}) 00:00:00\s+(?:-|through)\s+({self.date_re}) 23:59:59", first, re.I)
        expected_end = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
        if (
            "Structural Permits Issued" not in first
            or "CITY OF HERMISTON BUILDING DEPARTMENT" not in first.upper()
            or not date_span
            or self._date(date_span[1]) != month
            or self._date(date_span[2]) != expected_end
        ):
            raise RuntimeError("Hermiston report title, city, or month could not be verified")
        found = []
        newest_source_date = None
        for page_num, page in enumerate(pages, 1):
            pieces = self.permit_re.split(page)
            markers = re.findall(r"^ *Permit:", page, re.M | re.I)
            if len(markers) != (len(pieces) - 1) // 2:
                raise RuntimeError("Hermiston report has an unrecognized permit layout")
            for number, block in zip(pieces[1::2], pieces[2::2]):
                issued_match = re.search(fr"Date Issued:\s*({self.date_re})", block, re.I)
                issued = self._date(issued_match[1] if issued_match else "")
                if not issued or not month <= issued <= min(today, expected_end):
                    raise RuntimeError("Hermiston report contains a missing, out-of-month, or future issue date")
                newest_source_date = max(newest_source_date or issued, issued)
                if not self.number_re.fullmatch(number):
                    continue
                kind = re.search(r"Type of Work:[ \t]*(.*?)\s{2,}Category of Construction:[ \t]*(.*?)\s{2,}Sq Footage:", block, re.I)
                if not kind:
                    raise RuntimeError("Hermiston dwelling record lacks work-type or category fields")
                if [v.strip().casefold() for v in kind.groups()] != ["new", "single family dwelling"]:
                    continue
                address = re.search(r"Site Addr:[ \t]*(.*?)\s{2,}Valuation:", block, re.I)
                desc = re.search(r"Work Desc:[ \t]*([^\n]+)", block, re.I)
                if not address or not address[1].strip() or not desc:
                    raise RuntimeError("Hermiston dwelling record lacks address or description")
                # Do not confuse a primary dwelling with a detached or accessory-only permit.
                if not re.search(r"\b(?:SFD|SFR|single[- ]family|single family dwelling|new home|new residence)\b", desc[1], re.I):
                    continue
                value = re.search(r"Valuation:[ \t]*\$([\d,.]+)", block, re.I)
                # CCB is a license listing, not a confirmed role. Deliberately do not
                # assign a contractor or publish contractor contact/address lines.
                ccb_listed = bool(re.search(r"^ *CCB\s+\d+\s*:", block, re.M | re.I))
                found.append(Permit(
                    state="OR", jurisdiction=self.name, permit_number=number.upper(),
                    issued_date=issued.isoformat(), permit_type="Residential Structural - Dwelling",
                    building_use="Single Family Dwelling", address=address[1].strip(),
                    project_name=desc[1].strip(), units=1,
                    valuation=float(value[1].replace(",", "")) if value else None,
                    status="Issued", source_name="City of Hermiston Building Department",
                    source_url=f"{url}#page={page_num}",
                    raw={
                        "work_proposed": "New", "type_of_use": "Single Family Dwelling",
                        "report_kind": "residential", "source_building_family_authoritative": True,
                        "source_new_construction_subtype": True, "source_issued_validated": True,
                        "ccb_entry_present": ccb_listed, "contractor_role": "unverified",
                        "report_sha256":hashlib.sha256(content).hexdigest(),
                        "report_period_start":month.isoformat(), "report_period_end":expected_end.isoformat(),
                        "source_page":page_num,
                    },
                ))
        if newest_source_date is None:
            raise RuntimeError("Hermiston report yielded no dated permit blocks")
        return found, newest_source_date

    def collect(self, session=None, today=None):
        session = session or new_session()
        today = today or date.today()
        reports = self._reports(session, today)
        existing = {}
        freshest = None
        for month, url in reports:
            r = self._get(session, url, "/sites/default/files/fileattachments/community_development/page/")
            permits, last_source_date = self._parse(r.content, url, month, today)
            freshest = max(freshest or last_source_date, last_source_date)
            for permit in permits:
                older = existing.get(permit.key)
                if older and (older.issued_date != permit.issued_date or older.address != permit.address):
                    raise RuntimeError("Conflicting Hermiston permit identity across reports")
                existing.setdefault(permit.key, permit)
        return CollectionResult(
            self.name, list(existing.values()), self.source_url,
            f"Hermiston official monthly collection; {len(reports)} monthly issued structural PDF(s), "
            f"latest permit of any type {freshest}; qualifying new primary single-family "
            "dwelling permits only. Trade, alter/remodel, accessory, multifamily and "
            "commercial records not ingested; CCB listings are not confirmed contractor roles.",
        )
