from __future__ import annotations

from datetime import date, timedelta
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .base import CollectionResult, new_session
from ..models import Permit


class HillsboroCollector:
    name = "Hillsboro"
    freshness_days = 14
    window_days = 21
    windows = 3
    max_pages = 20

    aca_base = "https://aca-prod.accela.com/HILLSBORO/"
    search_url = urljoin(aca_base, "Cap/CapHome.aspx?TabName=Building&module=Building")
    source_url = search_url
    inspection_base = "https://inspections.hillsboro-oregon.gov/"
    inspection_search_url = urljoin(inspection_base, "permits/search_submit")

    permit_number_re = re.compile(r"^(?:STR|CMB)\d{2}-\d{4,6}$", re.I)
    structural_re = re.compile(r"\b(?:Residential|Commercial)\s+Structural\s+Permit\b", re.I)
    new_subtype_re = re.compile(r"^New\b", re.I)
    issued_statuses = {
        "issued", "inspection phase", "closed - complete", "active", "finaled", "complete"
    }

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; OregonConstructionIntelligence/0.1; public-permit-research)"
        })

        rows: dict[str, dict] = {}
        today = date.today()
        successful_windows = 0
        for offset in range(self.windows):
            end = today - timedelta(days=offset * self.window_days)
            start = end - timedelta(days=self.window_days)
            window_rows = self._search_window(session, start, end)
            if window_rows is not None:
                successful_windows += 1
                for row in window_rows:
                    if self.structural_re.search(row.get("record_type") or ""):
                        rows[row["permit_number"]] = row

        if successful_windows == 0:
            raise RuntimeError("Hillsboro OpenHillsboro search failed for every recent date window")

        permits: dict[str, Permit] = {}
        for number, row in rows.items():
            detail = self._detail(session, row["source_url"])
            subtype = detail.get("subtype") or ""
            if not self.new_subtype_re.search(subtype):
                continue

            issued_validated = False
            if (row.get("status") or "").strip().lower() in self.issued_statuses:
                issued_validated = self._validate_issued(number)

            permit = self._permit(row, detail, issued_validated, today)
            if permit:
                permits[permit.key] = permit

        return CollectionResult(
            self.name,
            list(permits.values()),
            self.source_url,
            "Official OpenHillsboro structural permit search/detail plus City inspection-system issuance validation; "
            "issued date is first observed issued when the public systems do not expose the exact issue timestamp",
        )

    def _search_window(self, session: requests.Session, start: date, end: date) -> list[dict] | None:
        # Accela occasionally returns an empty shell on an otherwise valid request. Retry with a fresh
        # initial form up to three times, but treat a genuine rendered empty result as a successful window.
        last_error: Exception | None = None
        for _ in range(3):
            try:
                response = session.get(self.search_url, timeout=90)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                payload = self._successful_controls(soup)
                payload.update({
                    "__EVENTTARGET": "ctl00$PlaceHolderMain$btnNewSearch",
                    "__EVENTARGUMENT": "",
                    "ctl00$PlaceHolderMain$generalSearchForm$txtGSStartDate": self._form_date(start),
                    "ctl00$PlaceHolderMain$generalSearchForm$txtGSEndDate": self._form_date(end),
                    "ctl00$PlaceHolderMain$generalSearchForm$txtGSStartDate_ext_ClientState": "",
                    "ctl00$PlaceHolderMain$generalSearchForm$txtGSEndDate_ext_ClientState": "",
                    "ctl00$PlaceHolderMain$generalSearchForm$ddlGSPermitType": "",
                })
                posted = session.post(
                    self.search_url,
                    data=payload,
                    headers={"Referer": self.search_url, "Origin": "https://aca-prod.accela.com"},
                    timeout=120,
                )
                posted.raise_for_status()
                soup = BeautifulSoup(posted.text, "html.parser")
                self._guard_aca_page(soup, "search results")

                result_table = soup.find("table", id="ctl00_PlaceHolderMain_dgvPermitList_gdvPermitList")
                plain = " ".join(soup.stripped_strings)
                if not result_table:
                    if re.search(r"(?:no records|no results|0 record)", plain, re.I):
                        return []
                    last_error = RuntimeError("Hillsboro Accela search response did not contain a result grid")
                    continue

                rows: list[dict] = []
                for _page in range(self.max_pages):
                    rows.extend(self._parse_result_rows(soup))
                    next_link = next(
                        (a for a in soup.find_all("a", href=True) if " ".join(a.stripped_strings) == "Next >"),
                        None,
                    )
                    if not next_link:
                        break
                    match = re.search(r"__doPostBack\('([^']+)'", next_link.get("href", ""))
                    if not match:
                        raise RuntimeError("Hillsboro Accela pagination schema changed")
                    page_payload = self._successful_controls(soup)
                    page_payload["__EVENTTARGET"] = match.group(1)
                    page_payload["__EVENTARGUMENT"] = ""
                    page_response = session.post(
                        self.search_url,
                        data=page_payload,
                        headers={"Referer": self.search_url, "Origin": "https://aca-prod.accela.com"},
                        timeout=120,
                    )
                    page_response.raise_for_status()
                    soup = BeautifulSoup(page_response.text, "html.parser")
                    self._guard_aca_page(soup, "paginated search results")
                return rows
            except Exception as exc:
                last_error = exc
        if last_error:
            return None
        return None

    @classmethod
    def _successful_controls(cls, soup: BeautifulSoup) -> dict[str, str]:
        form = soup.find("form", id="aspnetForm")
        if not form:
            raise RuntimeError("Hillsboro Accela aspnetForm not found")
        payload: dict[str, str] = {}
        for element in form.find_all("input"):
            name = element.get("name")
            kind = (element.get("type") or "text").lower()
            if not name or kind in {"submit", "button", "image", "file"}:
                continue
            if kind in {"checkbox", "radio"} and not element.has_attr("checked"):
                continue
            payload[name] = element.get("value", "")
        for element in form.find_all("textarea"):
            if element.get("name"):
                payload[element["name"]] = element.get_text()
        for element in form.find_all("select"):
            name = element.get("name")
            if not name:
                continue
            chosen = element.find("option", selected=True) or element.find("option")
            payload[name] = chosen.get("value", "") if chosen else ""
        return payload

    @classmethod
    def _parse_result_rows(cls, soup: BeautifulSoup) -> list[dict]:
        table = soup.find("table", id="ctl00_PlaceHolderMain_dgvPermitList_gdvPermitList")
        if not table:
            return []
        rows: list[dict] = []
        for tr in table.find_all("tr"):
            link = tr.find("a", id=re.compile(r"_hlPermitNumber$"))
            if not link:
                continue

            def value(suffix: str) -> str:
                node = tr.find(id=re.compile(re.escape(suffix) + r"$"))
                return " ".join(node.stripped_strings).strip() if node else ""

            number = " ".join(link.stripped_strings).strip()
            if not cls.permit_number_re.match(number):
                continue
            source_url = urljoin(cls.search_url, link.get("href", ""))
            cls._guard_url(source_url, "aca-prod.accela.com")
            rows.append({
                "application_date": cls._date_text(value("_lblUpdatedTime")),
                "permit_number": number,
                "record_type": value("_lblType"),
                "description": value("_lblDescription"),
                "project_name": value("_lblProjectName"),
                "status": value("_lblStatus"),
                "expiration_date": cls._date_text(value("_lblExpirationDate")),
                "address": value("_lblPermitAddress"),
                "source_url": source_url,
            })
        return rows

    def _detail(self, session: requests.Session, source_url: str) -> dict:
        self._guard_url(source_url, "aca-prod.accela.com")
        response = session.get(source_url, headers={"Referer": self.search_url}, timeout=90)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        self._guard_aca_page(soup, "permit detail")
        if not soup.find(string=re.compile(r"General Project Information", re.I)):
            raise RuntimeError("Hillsboro permit detail missing General Project Information")
        text = " ".join(soup.stripped_strings)

        subtype = self._capture(text, r"Subtype:\s*(.+?)(?=\s+(?:New Building Area:|Total Existing Building Area:|Building Height|Work in the Right of Way\?|Was there an existing structure|Does your project include|Parcel Information|Phased Project Information|Application Information Table))")
        new_area = self._number(self._capture(text, r"New Building Area:\s*([\d,.]+)"))
        stories = self._positive_int(self._capture(text, r"Building Height \(Stories\):\s*([\d.]+)"))
        parcel = self._capture(text, r"Parcel Number:\s*([^*]+)")
        contractor = self._capture(text, r"Licensed Professional:\s*(.+?)(?=\s+(?:Business Phone:|Project Description:))")
        project = self._capture(text, r"Project Description:\s*(.+?)(?=\s+Owner:\s*\*)")

        occupancy = self._capture(text, r"(?:NEW CONSTRUCTION OCCUPANCY|ADDITION/ALTERATION OCCUPANCY)\s+Occupancy:\s*([^\s]+)")
        use = self._capture(text, r"(?:Proposed Use|Use):\s*(.+?)(?=\s+Area Square Footage:)")
        sqft = self._number(self._capture(text, r"Area Square Footage:\s*([\d,.]+)")) or new_area
        construction = self._capture(text, r"Type of Construction:\s*(.+?)(?=\s+Parcel Information)")
        units = self._positive_int(self._capture(text, r"(?:Number of Units|Dwelling Units|Units):\s*(\d+)"))
        job_value = self._money(self._capture(text, r"Job Value\s+\$?([\d,]+(?:\.\d+)?)"))

        return {
            "subtype": subtype,
            "new_building_area": new_area,
            "stories": stories,
            "parcel": parcel,
            "contractor": contractor,
            "project_description": project,
            "occupancy": occupancy,
            "use": use,
            "sqft": sqft,
            "construction_type": construction,
            "units": units,
            "valuation": job_value,
        }

    def _validate_issued(self, permit_number: str) -> bool:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; OregonConstructionIntelligence/0.1; public-permit-research)"
        })
        home = session.get(self.inspection_base, timeout=60)
        home.raise_for_status()
        soup = BeautifulSoup(home.text, "html.parser")
        token_node = soup.find("input", {"name": "_token"})
        csrf_node = soup.find("meta", {"name": "csrf-token"})
        if not token_node or not token_node.get("value"):
            raise RuntimeError("Hillsboro inspection system search token missing")
        headers = {
            "Referer": self.inspection_base,
            "Origin": "https://inspections.hillsboro-oregon.gov",
            "X-Requested-With": "XMLHttpRequest",
        }
        if csrf_node and csrf_node.get("content"):
            headers["X-CSRF-TOKEN"] = csrf_node["content"]
        response = session.post(
            self.inspection_search_url,
            data={"_token": token_node["value"], "permit_number": permit_number, "address": ""},
            headers=headers,
            timeout=60,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Hillsboro inspection permit search did not return JSON") from exc
        if payload.get("status") != "success":
            return False
        redirect = ((payload.get("data") or {}).get("redirect_url") or "").strip()
        if not redirect:
            return False
        self._guard_url(redirect, "inspections.hillsboro-oregon.gov")
        return True

    @classmethod
    def _permit(cls, row: dict, detail: dict, issued_validated: bool, observed_on: date) -> Permit | None:
        number = row.get("permit_number") or ""
        if not cls.permit_number_re.match(number):
            return None
        record_type = row.get("record_type") or ""
        kind = "commercial" if "Commercial" in record_type else "residential" if "Residential" in record_type else ""
        subtype = detail.get("subtype") or ""
        if not cls.new_subtype_re.search(subtype):
            return None
        description = detail.get("project_description") or row.get("description") or ""
        use = detail.get("use") or detail.get("occupancy") or subtype
        issued_date = observed_on.isoformat() if issued_validated else ""
        return Permit(
            state="OR",
            jurisdiction="Hillsboro",
            permit_number=number,
            issued_date=issued_date,
            permit_type=" / ".join(x for x in (record_type, subtype) if x),
            building_use=use or None,
            project_name=row.get("project_name") or description or None,
            address=row.get("address") or "",
            units=detail.get("units"),
            valuation=detail.get("valuation"),
            contractor=detail.get("contractor") or None,
            owner=None,
            status=row.get("status") or None,
            source_name="OpenHillsboro Accela Citizen Access + Hillsboro Inspection Scheduler",
            source_url=row.get("source_url") or cls.search_url,
            raw={
                "report_kind": kind,
                "work_proposed": subtype,
                "type_of_use": use,
                "description": description,
                "source_new_construction_subtype": True,
                "source_building_family_authoritative": True,
                "requires_issued_validation": True,
                "source_issued_validated": issued_validated,
                "issued_date_basis": "first_observed_issued" if issued_validated else None,
                "application_date": row.get("application_date"),
                "accela_status": row.get("status"),
                "expiration_date": row.get("expiration_date"),
                "subtype": subtype,
                "new_building_area": detail.get("new_building_area"),
                "total_sqft": detail.get("sqft"),
                "stories": detail.get("stories"),
                "occupancy_group": detail.get("occupancy"),
                "construction_type": detail.get("construction_type"),
                "parcel": detail.get("parcel"),
                "issue_validation_source": cls.inspection_base,
            },
        )

    @staticmethod
    def _guard_aca_page(soup: BeautifulSoup, label: str) -> None:
        form = soup.find("form", id="aspnetForm")
        action = (form.get("action") if form else "") or ""
        text = " ".join(soup.stripped_strings)
        if "Login.aspx" in action or ("Register Now" in text and "General Search" not in text and "Record" not in text):
            raise RuntimeError(f"Hillsboro Accela {label} returned a login shell")

    @staticmethod
    def _guard_url(url: str, expected_host: str) -> None:
        host = (urlparse(url).hostname or "").lower()
        if host != expected_host:
            raise RuntimeError(f"Hillsboro source identity check failed: unexpected host {host}")

    @staticmethod
    def _form_date(value: date) -> str:
        return f"{value.month:02d}/{value.day:02d}/{value.year}"

    @staticmethod
    def _date_text(value: str) -> str | None:
        value = (value or "").strip()
        if not value:
            return None
        for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
            try:
                from datetime import datetime
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    @staticmethod
    def _capture(text: str, pattern: str) -> str | None:
        match = re.search(pattern, text, re.I | re.S)
        return re.sub(r"\s+", " ", match.group(1)).strip() if match else None

    @staticmethod
    def _number(value: str | None) -> float | None:
        if value is None:
            return None
        try:
            number = float(str(value).replace(",", ""))
            return number if number > 0 else None
        except ValueError:
            return None

    @classmethod
    def _money(cls, value: str | None) -> float | None:
        return cls._number(value.replace("$", "") if value else value)

    @staticmethod
    def _positive_int(value) -> int | None:
        try:
            number = int(float(value))
            return number if number > 0 else None
        except (TypeError, ValueError):
            return None
