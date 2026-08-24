from __future__ import annotations
from datetime import datetime
from urllib.parse import urlparse
import re
import requests
from bs4 import BeautifulSoup
from .base import CollectionResult, new_session
from ..models import Permit

class PortlandCollector:
    name = "Portland"
    freshness_days = 10
    base_url = "https://www.portlandmaps.com/reports/index.cfm"
    source_url = "https://www.portlandmaps.com/reports/index.cfm?action=rs-issued"
    report_actions = (
        ("rs-issued", "Residential Issued Building Permits Report", "residential"),
        ("co-issued", "Commercial Issued Building Permits Report", "commercial"),
    )
    max_pages = 25

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        all_permits: dict[str, Permit] = {}

        # PortlandMaps' native issued-report pages are the stable public surface.
        # Do not send date-filter form parameters here: in production those can
        # return a valid report shell with zero rows. Persistent repository
        # history accumulates records across the six-hour polling cadence.
        for action, expected_heading, report_kind in self.report_actions:
            seen_pages: set[tuple[str, ...]] = set()
            for page in range(1, self.max_pages + 1):
                params = {"action": action, "page": page}
                response = session.get(self.base_url, params=params, timeout=90)
                response.raise_for_status()
                parsed = self.parse_page(response.text, expected_heading, report_kind)
                if not parsed:
                    break
                sig = tuple(p.permit_number for p in parsed[:5])
                if sig in seen_pages:
                    break
                seen_pages.add(sig)
                for p in parsed:
                    all_permits[p.key] = p

        if not all_permits:
            raise RuntimeError("PortlandMaps issued-permit reports parsed with zero usable permit rows")
        return CollectionResult(
            self.name, list(all_permits.values()), self.source_url,
            "Official PortlandMaps current residential/commercial issued-building-permit reports; persistent history retained between runs"
        )

    @classmethod
    def parse_page(cls, html: str, expected_heading: str, report_kind: str) -> list[Permit]:
        soup = BeautifulSoup(html, "html.parser")
        page_text = " ".join(soup.stripped_strings)
        if expected_heading.lower() not in page_text.lower():
            raise RuntimeError(f"Portland source identity check failed: missing heading {expected_heading!r}")

        target = None
        headers: list[str] = []
        for table in soup.find_all("table"):
            row = table.find("tr")
            if not row:
                continue
            candidate = [cls._norm(c.get_text(" ", strip=True)) for c in row.find_all(["th","td"])]
            if "CASE NUMBER" in candidate and "DATE ISSUED" in candidate and "ADDRESS" in candidate:
                target = table
                headers = candidate
                break
        if target is None:
            if re.search(r"\b0\s+Records\b", page_text, re.I):
                return []
            raise RuntimeError("Portland report table schema not found")

        permits: list[Permit] = []
        for tr in target.find_all("tr")[1:]:
            cells = tr.find_all("td")
            if not cells:
                continue
            values = [c.get_text(" ", strip=True) for c in cells]
            if len(values) < len(headers):
                values += [""] * (len(headers)-len(values))
            row = dict(zip(headers, values))
            number = row.get("CASE NUMBER","").strip()
            issued = cls._date(row.get("DATE ISSUED"))
            if not number or not issued:
                continue
            link = ""
            first_link = cells[0].find("a", href=True) if cells else None
            if first_link:
                link = str(first_link.get("href") or "").strip()
                if link.startswith("/"):
                    link = "https://www.portlandmaps.com" + link
            if link:
                host = (urlparse(link).hostname or "").lower()
                if host != "portlandmaps.com" and not host.endswith(".portlandmaps.com"):
                    raise RuntimeError(f"Portland source identity check failed: foreign permit host {host}")
            else:
                ivr = row.get("IVR NUMBER","").strip()
                if ivr:
                    link = f"https://www.portlandmaps.com/detail/permit/{ivr}_did/"
                else:
                    link = cls.source_url

            desc = row.get("DESCRIPTION OF WORK","").strip()
            work = row.get("WORK PROPOSED","").strip()
            use = row.get("TYPE OF USE","").strip()
            units = cls._units(desc, use)

            permits.append(Permit(
                state="OR",
                jurisdiction="Portland",
                permit_number=number,
                issued_date=issued,
                permit_type=f"{report_kind.title()} / {work}".strip(" /"),
                building_use=use or None,
                project_name=desc or None,
                address=row.get("ADDRESS","").strip(),
                units=units,
                valuation=cls._float(row.get("VALUATION")),
                contractor=row.get("CONTRACTOR","").strip() or None,
                owner=row.get("OWNER 1","").strip() or None,
                status=row.get("STATUS","").strip() or None,
                source_name="PortlandMaps Issued Building Permits",
                source_url=link,
                raw={
                    "report_kind": report_kind,
                    "work_proposed": work,
                    "type_of_use": use,
                    "description": desc,
                    "ivr_number": row.get("IVR NUMBER","").strip(),
                    "property_legal_description": row.get("PROPERTY LEGAL DESCRIPTION","").strip(),
                },
            ))
        return permits

    @staticmethod
    def _norm(value: str) -> str:
        return re.sub(r"\s+", " ", value.replace("\xa0"," ")).strip().upper()

    @staticmethod
    def _date(value) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        text = text.split()[0]
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                pass
        return None

    @staticmethod
    def _float(value) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace("$","").replace(",","").strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _units(description: str, use: str) -> int | None:
        text = f"{description} {use}"
        patterns = (
            r"\b(\d{1,4})\s*[- ]?unit(?:s)?\b",
            r"\b(\d{1,4})\s+dwelling\s+units?\b",
        )
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    pass
        if re.search(r"\bduplex|two[- ]family\b", text, re.I):
            return 2
        if re.search(r"\btriplex|three[- ]family\b", text, re.I):
            return 3
        if re.search(r"\bfourplex|four[- ]family\b", text, re.I):
            return 4
        return None
