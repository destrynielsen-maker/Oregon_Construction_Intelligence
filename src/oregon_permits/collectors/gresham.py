from __future__ import annotations

from datetime import date, datetime, timedelta
import copy
import re
import time

import requests

from .base import CollectionResult, new_session
from ..models import Permit


class GreshamCollector:
    name = "Gresham"
    freshness_days = 10
    lookback_days = 45
    page_size = 100
    max_pages = 20

    base_url = "https://greshamor-energovweb.tylerhost.net/apps/SelfService/"
    criteria_url = base_url + "api/energov/search/criteria"
    search_url = base_url + "api/energov/search/search"
    source_url = base_url

    tenant_headers = {
        "tenantId": "1",
        "tenantName": "GreshamOrProd",
        "Tyler-TenantUrl": "GreshamOrProd",
        "Tyler-Tenant-Culture": "en-US",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
    }

    new_types = {
        "residential new construction": "residential",
        "multi-family new construction": "residential",
        "commercial new construction": "commercial",
    }
    permit_number_re = re.compile(r"^[A-Z0-9-]{6,40}$", re.I)

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; OregonConstructionIntelligence/0.1; public-permit-research)",
            "Referer": self.base_url,
        })

        home = session.get(self.base_url, timeout=60)
        home.raise_for_status()

        criteria = session.get(self.criteria_url, headers=self.tenant_headers, timeout=60)
        criteria.raise_for_status()
        payload = criteria.json()
        template = payload.get("Result") if isinstance(payload, dict) else None
        if not isinstance(template, dict) or not isinstance(template.get("PermitCriteria"), dict):
            raise RuntimeError("Gresham EnerGov criteria schema changed")

        today = date.today()
        cutoff = today - timedelta(days=self.lookback_days)
        permits: dict[str, Permit] = {}
        saw_usable_page = False

        for page_number in range(1, self.max_pages + 1):
            body = self._search_body(template, page_number)
            result = self._post_search(session, body)
            rows = result.get("EntityResults")
            if not isinstance(rows, list):
                raise RuntimeError("Gresham EnerGov search schema changed: EntityResults missing")
            if not rows:
                saw_usable_page = True
                break
            saw_usable_page = True

            nonfuture_dates: list[date] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if row.get("ModuleName") != 2:
                    raise RuntimeError("Gresham EnerGov permit filter leaked a non-permit record")

                issued = self._date(row.get("IssueDate"))
                if issued:
                    issued_date = date.fromisoformat(issued)
                    if issued_date <= today:
                        nonfuture_dates.append(issued_date)

                permit = self._permit(row, cutoff, today)
                if permit:
                    permits[permit.key] = permit

            # EnerGov's IssueDateFrom/To criteria do not reliably constrain the result set.
            # We therefore page newest-first and stop only after an entire page of usable
            # issue dates is older than our rolling cutoff. Future-dated bad records are ignored.
            if nonfuture_dates and max(nonfuture_dates) < cutoff:
                break
            if len(rows) < self.page_size:
                break

        if not saw_usable_page:
            raise RuntimeError("Gresham EnerGov returned no usable permit pages")

        return CollectionResult(
            self.name,
            list(permits.values()),
            self.source_url,
            "Official City of Gresham Tyler EnerGov public permit search; permit module only, "
            "newest-first with a locally enforced rolling 45-day issue-date cutoff; future issue dates are ignored",
        )

    @classmethod
    def _search_body(cls, template: dict, page_number: int) -> dict:
        body = copy.deepcopy(template)
        body["SearchModule"] = 1
        body["FilterModule"] = 2
        body["PageNumber"] = page_number
        body["PageSize"] = cls.page_size
        body["Keyword"] = ""
        body["ExactMatch"] = False
        body["SortBy"] = "IssueDate"
        body["SortAscending"] = False
        permit = body["PermitCriteria"]
        permit["PageNumber"] = page_number
        permit["PageSize"] = cls.page_size
        permit["SortBy"] = "IssueDate"
        permit["SortAscending"] = False
        # Retain these as hints for portals that honor them, but never trust them for correctness.
        permit["IssueDateFrom"] = None
        permit["IssueDateTo"] = None
        return body

    @classmethod
    def _post_search(cls, session: requests.Session, body: dict) -> dict:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = session.post(cls.search_url, headers=cls.tenant_headers, json=body, timeout=120)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(f"retryable status {response.status_code}", response=response)
                response.raise_for_status()
                payload = response.json()
                result = payload.get("Result") if isinstance(payload, dict) else None
                if not isinstance(result, dict):
                    raise RuntimeError("Gresham EnerGov search returned no Result object")
                return result
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(attempt + 1)
        raise RuntimeError(f"Gresham EnerGov search failed after retries: {last_error}")

    @classmethod
    def _permit(cls, row: dict, cutoff: date, today: date) -> Permit | None:
        number = cls._text(row.get("CaseNumber"))
        case_type = cls._text(row.get("CaseType"))
        workclass = cls._text(row.get("CaseWorkclass"))
        status = cls._text(row.get("CaseStatus"))
        issued = cls._date(row.get("IssueDate"))

        if not number or not cls.permit_number_re.match(number) or not issued:
            return None
        issued_date = date.fromisoformat(issued)
        if issued_date > today or issued_date < cutoff:
            return None
        if status.lower() not in {"issued", "closed"}:
            return None
        if workclass.lower() != "new construction":
            return None

        report_kind = cls.new_types.get(case_type.lower())
        if not report_kind:
            return None

        description = cls._text(row.get("Description"))
        project = cls._text(row.get("ProjectName"))
        address = cls._text(row.get("AddressDisplay"))
        parcel = cls._text(row.get("MainParcel"))
        case_id = cls._text(row.get("CaseId"))
        source_url = f"{cls.base_url}#/permit/{case_id}" if case_id else cls.base_url

        return Permit(
            state="OR",
            jurisdiction="Gresham",
            permit_number=number,
            issued_date=issued,
            permit_type=f"{case_type} / {workclass}",
            building_use=case_type,
            project_name=project or description or None,
            address=address,
            units=None,
            valuation=None,
            contractor=None,
            owner=None,
            status=status,
            source_name="City of Gresham Tyler EnerGov Self Service",
            source_url=source_url,
            raw={
                "report_kind": report_kind,
                "work_proposed": workclass,
                "type_of_use": case_type,
                "description": description,
                "source_new_construction_subtype": True,
                "source_building_family_authoritative": True,
                "source_issue_date_authoritative": True,
                "application_date": cls._date(row.get("ApplyDate")),
                "case_id": case_id,
                "case_type_id": cls._text(row.get("CaseTypeId")),
                "case_workclass_id": cls._text(row.get("CaseWorkclassId")),
                "case_status_id": cls._text(row.get("CaseStatusId")),
                "main_parcel": parcel,
                "module_name": row.get("ModuleName"),
            },
        )

    @staticmethod
    def _text(value) -> str:
        return str(value or "").strip()

    @staticmethod
    def _date(value) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            return None
