from __future__ import annotations

from datetime import date, timedelta
import re

import requests

from .base import CollectionResult, new_session
from ..models import Permit


class BeavertonCollector:
    name = "Beaverton"
    freshness_days = 10
    lookback_days = 45
    page_size = 20
    max_pages_per_work_type = 12

    base_url = "https://prod.buildinginbeaverton.org/"
    lookup_url = base_url + "lookup-record"
    api_base = base_url + "delegate/civics-api/api/"
    auth_url = api_base + "anonymous/auth"
    applications_url = api_base + "cdr/applications/building"
    source_url = lookup_url

    work_types = ("HouseOrAdu", "NewCon")
    primary_types = {"C", "MF", "R"}
    permit_number_re = re.compile(r"^(?:C|MF|R)\d{4}-\d{5}$", re.I)

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; OregonConstructionIntelligence/0.1; public-permit-research)",
        })

        landing = session.get(self.lookup_url, timeout=45)
        landing.raise_for_status()
        auth = session.get(
            self.auth_url,
            headers={"Referer": self.lookup_url, "Accept": "application/json"},
            timeout=45,
        )
        auth.raise_for_status()
        auth_payload = auth.json()
        if not isinstance(auth_payload, dict) or not auth_payload.get("sessionId"):
            raise RuntimeError("Beaverton CIVICS anonymous authentication schema changed")

        today = self._today()
        cutoff = today - timedelta(days=self.lookback_days)
        permits: dict[str, Permit] = {}
        successful_queries = 0

        for work_type in self.work_types:
            for page_index in range(self.max_pages_per_work_type):
                start = 1 + page_index * self.page_size
                rows = self._query(session, work_type, start)
                successful_queries += 1
                if not rows:
                    break

                nonfuture_dates: list[date] = []
                for row in rows:
                    issued = self._date(row.get("issuedDateTime") if isinstance(row, dict) else None)
                    if issued:
                        issued_date = date.fromisoformat(issued)
                        if issued_date <= today:
                            nonfuture_dates.append(issued_date)
                    permit = self._permit(row, cutoff, today)
                    if permit:
                        permits[permit.key] = permit

                # CIVICS honors WorkType filtering and IssuedDateTime sorting. Stop once
                # an entire page of usable issue dates is older than the local rolling cutoff.
                if nonfuture_dates and max(nonfuture_dates) < cutoff:
                    break
                if len(rows) < self.page_size:
                    break

        if successful_queries == 0:
            raise RuntimeError("Beaverton CIVICS returned no usable building-application queries")

        return CollectionResult(
            self.name,
            list(permits.values()),
            self.source_url,
            "Official City of Beaverton BEPS/Rhythm CIVICS public building applications; anonymous WorkType-filtered "
            "collection sorted by authoritative issuedDateTime with a locally enforced rolling 45-day cutoff",
        )

    @classmethod
    def _query(cls, session: requests.Session, work_type: str, start: int) -> list[dict]:
        response = session.get(
            cls.applications_url,
            params={
                "Page": f"[{{Max:{cls.page_size},Start:{start}}}]",
                "OrderBy": "[{Property:IssuedDateTime,Direction:Desc}]",
                "WorkType": work_type,
            },
            headers={"Referer": cls.lookup_url, "Accept": "application/json, text/plain, */*"},
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Beaverton CIVICS building response is not a JSON object")
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise RuntimeError("Beaverton CIVICS building response schema changed: data list missing")
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError("Beaverton CIVICS building response contains a non-object row")
            if row.get("workType") != work_type:
                raise RuntimeError("Beaverton CIVICS WorkType filter leaked an unexpected record")
        return rows

    @classmethod
    def _permit(cls, row: dict, cutoff: date, today: date) -> Permit | None:
        if not isinstance(row, dict):
            return None

        number = cls._text(row.get("applicationNumber"))
        issued = cls._date(row.get("issuedDateTime"))
        application_type = row.get("applicationType") or {}
        type_code = cls._text(application_type.get("code") if isinstance(application_type, dict) else None).upper()
        type_description = cls._text(application_type.get("description") if isinstance(application_type, dict) else None)
        work_type = cls._text(row.get("workType"))
        work_description = cls._text(row.get("workTypeDescription"))
        occupancy_type = cls._text(row.get("occupancyType"))
        occupancy_description = cls._text(row.get("occupancyTypeDescription"))

        if not number or not issued or not cls.permit_number_re.match(number):
            return None
        if type_code not in cls.primary_types:
            return None

        issued_date = date.fromisoformat(issued)
        if issued_date > today or issued_date < cutoff:
            return None

        if work_type == "HouseOrAdu":
            # CIVICS uses one work-type bucket for new houses and ADUs. Require the
            # authoritative detached-new occupancy code so standalone ADUs are not promoted.
            if type_code != "R" or occupancy_type.lower() != "sfrdetnew":
                return None
        elif work_type == "NewCon":
            pass
        else:
            return None

        report_kind = "commercial" if type_code == "C" else "residential"
        description = cls._text(row.get("comments"))
        project_name = cls._text(row.get("applicationName"))
        address = " ".join(
            x for x in (cls._text(row.get("locationLine1")), cls._text(row.get("locationLine2"))) if x
        )
        building_use = " / ".join(x for x in (type_description, occupancy_description) if x)
        valuation = cls._positive_float(row.get("declaredValuation")) or cls._positive_float(row.get("calculatedValuation"))
        sqft = cls._positive_float(row.get("squareFootage"))
        contractor = cls._contact_name(row.get("applicationContacts"), "contractor")
        owner = cls._contact_name(row.get("applicationContacts"), "owner")
        internal_id = row.get("id")

        return Permit(
            state="OR",
            jurisdiction="Beaverton",
            permit_number=number,
            issued_date=issued,
            permit_type=" / ".join(x for x in (type_description or type_code, work_description or work_type) if x),
            building_use=building_use or None,
            project_name=project_name or description or None,
            address=address,
            units=None,
            valuation=valuation,
            contractor=contractor,
            owner=owner,
            status=cls._text(row.get("statusDescription")) or cls._text(row.get("processState")) or None,
            source_name="City of Beaverton BEPS / Rhythm CIVICS",
            source_url=cls.lookup_url,
            raw={
                "report_kind": report_kind,
                "work_proposed": work_description or work_type,
                "type_of_use": building_use,
                "description": description,
                "source_new_construction_subtype": True,
                "source_building_family_authoritative": True,
                "source_issue_date_authoritative": True,
                "application_type_code": type_code,
                "application_date": cls._date(row.get("applicationDateTime")),
                "issued_datetime": cls._text(row.get("issuedDateTime")),
                "work_type_code": work_type,
                "occupancy_type_code": occupancy_type,
                "occupancy_type_description": occupancy_description,
                "total_sqft": sqft,
                "internal_id": internal_id,
                "common_id": row.get("commonId"),
                "process_state": cls._text(row.get("processState")),
                "status_code": cls._text(row.get("status")),
                "primary_contact_name": cls._text(row.get("primaryContactName")),
            },
        )

    @staticmethod
    def _today() -> date:
        return date.today()

    @staticmethod
    def _text(value) -> str:
        return str(value or "").strip()

    @staticmethod
    def _date(value) -> str | None:
        text = str(value or "").strip()
        if len(text) < 10:
            return None
        candidate = text[:10]
        try:
            parsed = date.fromisoformat(candidate)
        except ValueError:
            return None
        if parsed.year < 1900:
            return None
        return parsed.isoformat()

    @staticmethod
    def _positive_float(value) -> float | None:
        try:
            number = float(value)
            return number if number > 0 else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _contact_name(cls, contacts, capacity_name: str) -> str | None:
        if not isinstance(contacts, list):
            return None
        target = capacity_name.strip().lower()
        for item in contacts:
            if not isinstance(item, dict):
                continue
            capacity = item.get("capacity") or {}
            description = cls._text(capacity.get("description") if isinstance(capacity, dict) else None).lower()
            if description != target:
                continue
            contact = item.get("contact") or {}
            identity = contact.get("identity") if isinstance(contact, dict) else None
            if not isinstance(identity, dict):
                continue
            for key in ("companyName", "businessName", "organizationName", "displayName"):
                value = cls._text(identity.get(key))
                if value:
                    return value
            first = cls._text(identity.get("firstName"))
            last = cls._text(identity.get("lastName"))
            if first and last and first.casefold() == last.casefold():
                return first
            full = " ".join(x for x in (first, last) if x)
            if full:
                return full
        return None
