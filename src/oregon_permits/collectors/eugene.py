from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from urllib.parse import quote, urlparse

import requests
import xlrd

from .base import CollectionResult, new_session
from ..models import Permit


class EugeneCollector:
    name = "Eugene"
    freshness_days = 10
    lookback_days = 45
    base_url = "https://pdd.eugene-or.gov"
    form_url = f"{base_url}/BuildingPermits/PermitReports"
    report_url = f"{base_url}/BuildingPermits/IssuedBuilding"
    source_url = form_url
    export_sheet = "BuildingPermitsIssuedExport"
    permit_number_re = re.compile(r"^\d{2}-\d{4,5}-\d{2}$")
    token_re = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', re.I)
    accessory_re = re.compile(r"\b(shed|detached garage|accessory garage|carport|patio cover)\b", re.I)
    required_headers = {
        "Issued Date", "Log Number", "Application Type", "Permit Type", "Work Involved",
        "Address", "Owner", "Contractor", "Dwellings", "Existing Use", "Proposed Use",
        "Div. Value", "Project",
    }

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        form = session.get(self.form_url, timeout=45)
        form.raise_for_status()
        token = self._token(form.text)

        today = date.today()
        start = today - timedelta(days=self.lookback_days)
        payload = {
            "__RequestVerificationToken": token,
            "issued.FromDate": self._form_date(start),
            "issued.ToDate": self._form_date(today),
            "issued.ApplicationType": "A",
            "issued.ValueOfWork": "0",
            "issued.PermitType": "B",
            "issued.Neighborhood": "",
            "issued.FormatForExport": "True",
        }
        response = session.post(self.report_url, data=payload, timeout=90)
        response.raise_for_status()
        permits = self._parse_export(response.content)
        if not permits:
            raise RuntimeError("Eugene issued-building export returned zero usable permits")
        return CollectionResult(
            self.name,
            permits,
            self.source_url,
            f"Official City of Eugene issued building permit Excel export; rolling {self.lookback_days}-day window",
        )

    @classmethod
    def _token(cls, html: str) -> str:
        match = cls.token_re.search(html or "")
        if not match:
            raise RuntimeError("Eugene permit report anti-forgery token not found")
        return match.group(1)

    @classmethod
    def _parse_export(cls, content: bytes) -> list[Permit]:
        if not content or not content.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
            raise RuntimeError("Eugene issued-building export is not an Excel workbook")
        try:
            book = xlrd.open_workbook(file_contents=content)
        except Exception as exc:
            raise RuntimeError(f"Eugene issued-building workbook could not be opened: {exc}") from exc
        if cls.export_sheet not in book.sheet_names():
            raise RuntimeError(f"Eugene workbook missing expected sheet {cls.export_sheet}")
        sheet = book.sheet_by_name(cls.export_sheet)
        if sheet.nrows < 2:
            raise RuntimeError("Eugene issued-building workbook contains no permit rows")

        headers = [str(sheet.cell_value(0, col)).strip() for col in range(sheet.ncols)]
        missing = sorted(cls.required_headers - set(headers))
        if missing:
            raise RuntimeError(f"Eugene issued-building schema check failed; missing {missing}")

        permits: dict[str, Permit] = {}
        for row_index in range(1, sheet.nrows):
            row = {headers[col]: sheet.cell_value(row_index, col) for col in range(sheet.ncols)}
            permit = cls._permit(row, book.datemode)
            if permit:
                permits[permit.key] = permit
        return list(permits.values())

    @classmethod
    def _permit(cls, row: dict, datemode: int = 0) -> Permit | None:
        number = cls._text(row.get("Log Number"))
        issued = cls._date(row.get("Issued Date"), datemode)
        if not number or not issued or not cls.permit_number_re.match(number):
            return None

        application = cls._text(row.get("Application Type"))
        work = cls._text(row.get("Work Involved"))
        existing_use = cls._text(row.get("Existing Use"))
        proposed_use = cls._text(row.get("Proposed Use"))
        project = cls._text(row.get("Project"))
        owner = cls._text(row.get("Owner")) or None
        contractor_raw = cls._text(row.get("Contractor"))
        contractor = contractor_raw if contractor_raw and contractor_raw.lower() != "owner" else None
        units = cls._positive_int(row.get("Dwellings"))
        valuation = cls._money(row.get("Div. Value"))
        address = cls._text(row.get("Address"))
        if address and not re.search(r"\bOR\b", address, re.I):
            address = f"{address}, Eugene, OR"

        accessory = bool(
            application.lower() == "residential"
            and work.lower() == "new building"
            and cls.accessory_re.search(project or "")
        )
        detail = f"{cls.base_url}/BuildingPermits/PermitReport?expand=True&log={quote(number)}&pdf=False"
        host = (urlparse(detail).hostname or "").lower()
        if host != "pdd.eugene-or.gov":
            raise RuntimeError(f"Eugene source identity check failed: foreign permit host {host}")

        return Permit(
            state="OR",
            jurisdiction="Eugene",
            permit_number=number,
            issued_date=issued,
            permit_type=" / ".join(x for x in (application, "Building", work) if x),
            building_use=proposed_use or existing_use or application or None,
            project_name=project or None,
            address=address,
            units=units,
            valuation=valuation,
            contractor=contractor,
            owner=owner,
            status="Issued",
            source_name="City of Eugene Planning & Development Issued Building Permits",
            source_url=detail,
            raw={
                "report_kind": application.lower(),
                "work_proposed": work,
                "work_involved": work,
                "type_of_use": proposed_use or existing_use,
                "description": project,
                "source_accessory_structure": accessory,
                "existing_use": existing_use,
                "proposed_use": proposed_use,
                "owner_address": cls._text(row.get("Owner Address")),
                "contractor_reported": contractor_raw,
                "map_taxlot": cls._text(row.get("Map/Taxlot")),
                "occupancy_group": cls._text(row.get("Occup. Group")),
                "zoning_district": cls._text(row.get("Zoning District")),
                "permit_fees": cls._money(row.get("Permit Fees")),
                "special_conditions": cls._text(row.get("Special Conditions")),
            },
        )

    @staticmethod
    def _text(value) -> str:
        if value is None:
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()

    @staticmethod
    def _form_date(value: date) -> str:
        return f"{value.month}/{value.day}/{value.year}"

    @staticmethod
    def _date(value, datemode: int = 0) -> str | None:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            try:
                return xlrd.xldate_as_datetime(value, datemode).date().isoformat()
            except (ValueError, OverflowError):
                return None
        text = str(value).strip()
        for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    @staticmethod
    def _positive_int(value) -> int | None:
        try:
            number = int(float(value))
            return number if number > 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _money(value) -> float | None:
        text = str(value or "").strip().replace("$", "").replace(",", "")
        try:
            number = float(text)
            return number if number > 0 else None
        except ValueError:
            return None
