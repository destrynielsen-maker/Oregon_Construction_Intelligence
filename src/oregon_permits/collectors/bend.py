from __future__ import annotations

from datetime import datetime, timezone
import re

import requests

from .base import CollectionResult, new_session
from ..models import Permit


class BendCollector:
    name = "Bend"
    freshness_days = 10
    result_limit = 2000
    table_url = "https://services5.arcgis.com/JisFYcK2mIVg9ueP/arcgis/rest/services/Permits_and_Contractors_Table/FeatureServer/0"
    poly_url = "https://services5.arcgis.com/JisFYcK2mIVg9ueP/ArcGIS/rest/services/Permit_Applications_Poly/FeatureServer/0"
    source_url = table_url
    application_number_re = re.compile(r"^[A-Za-z0-9-]{6,40}$")

    table_fields = ",".join((
        "ApplicationNumber", "StatusDesc", "ApplicationType", "BuildingUse", "ApplicationDate",
        "PermitTypeCode", "PermitTypeDescription", "PermitIssueDate", "SQFT", "ProjectValuation",
        "ZoningDesc", "Description", "Address", "Owner", "TAXLOT", "ContractorName",
        "GeneralContractorName", "OBJECTID",
    ))
    poly_fields = ",".join((
        "ApplicationNumber", "IssueDate", "SQFT", "Units", "ProjectValuation", "TypeDesc",
        "UseDesc", "BuildingCategory", "Owner", "CensusStructureDesc", "Address", "OBJECTID",
    ))

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        table = self._query(
            session,
            self.table_url,
            "PermitIssueDate IS NOT NULL AND PermitTypeCode = 'BLDG' AND ApplicationType LIKE 'New Construction%'",
            self.table_fields,
            "PermitIssueDate DESC",
            "Permits and Contractors Table",
            {"ApplicationNumber", "PermitIssueDate", "ApplicationType", "PermitTypeCode", "BuildingUse", "Description", "Address"},
        )
        poly = self._query(
            session,
            self.poly_url,
            "IssueDate IS NOT NULL AND TypeDesc LIKE 'New Construction%'",
            self.poly_fields,
            "IssueDate DESC",
            "Permit Applications Poly",
            {"ApplicationNumber", "IssueDate", "TypeDesc", "UseDesc", "Units"},
        )
        poly_by_number = {
            str((f.get("attributes") or {}).get("ApplicationNumber") or "").strip(): (f.get("attributes") or {})
            for f in poly
            if str((f.get("attributes") or {}).get("ApplicationNumber") or "").strip()
        }

        permits: dict[str, Permit] = {}
        for feature in table:
            attrs = feature.get("attributes") or {}
            number = str(attrs.get("ApplicationNumber") or "").strip()
            permit = self._permit(attrs, poly_by_number.get(number) or {})
            if permit:
                permits[permit.key] = permit

        if not permits:
            raise RuntimeError("Bend open-data tables returned zero usable issued new-construction building permits")
        return CollectionResult(
            self.name,
            list(permits.values()),
            self.source_url,
            "Official City of Bend nightly open-data tables; issued new-construction building applications",
        )

    @classmethod
    def _query(
        cls,
        session: requests.Session,
        layer_url: str,
        where: str,
        fields: str,
        order_by: str,
        source_name: str,
        required: set[str],
    ) -> list[dict]:
        response = session.get(
            f"{layer_url}/query",
            params={
                "where": where,
                "outFields": fields,
                "returnGeometry": "false",
                "orderByFields": order_by,
                "resultRecordCount": cls.result_limit,
                "resultOffset": 0,
                "f": "json",
            },
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Bend {source_name} response is not a JSON object")
        if payload.get("error"):
            raise RuntimeError(f"Bend {source_name} ArcGIS error: {payload['error']}")
        features = payload.get("features")
        if not isinstance(features, list) or not features:
            raise RuntimeError(f"Bend {source_name} returned no features")
        keys: set[str] = set()
        for feature in features[:25]:
            attrs = feature.get("attributes") if isinstance(feature, dict) else None
            if isinstance(attrs, dict):
                keys.update(attrs.keys())
        missing = sorted(required - keys)
        if missing:
            raise RuntimeError(f"Bend {source_name} schema check failed; missing {missing}")
        return features

    @classmethod
    def _permit(cls, row: dict, poly: dict) -> Permit | None:
        number = str(row.get("ApplicationNumber") or "").strip()
        issued = cls._date(row.get("PermitIssueDate") or poly.get("IssueDate"))
        if not number or not issued or not cls.application_number_re.match(number):
            return None

        application_type = cls._text(row.get("ApplicationType") or poly.get("TypeDesc"))
        building_use = cls._text(row.get("BuildingUse") or poly.get("UseDesc") or poly.get("CensusStructureDesc"))
        description = cls._text(row.get("Description"))
        address = cls._text(row.get("Address") or poly.get("Address"))
        if address and "BEND" not in address.upper():
            address = f"{address}, Bend, OR"
        owner = cls._text(row.get("Owner") or poly.get("Owner")) or None
        general_contractor = cls._text(row.get("GeneralContractorName"))
        contractor = general_contractor or cls._text(row.get("ContractorName")) or None
        valuation = cls._positive_float(row.get("ProjectValuation")) or cls._positive_float(poly.get("ProjectValuation"))
        units = cls._positive_int(poly.get("Units"))
        sqft = cls._positive_float(row.get("SQFT")) or cls._positive_float(poly.get("SQFT"))
        category = cls._text(poly.get("BuildingCategory"))
        report_kind = "commercial" if category.lower() in {"non-residential", "commercial"} else "residential" if "residential" in category.lower() else ""

        return Permit(
            state="OR",
            jurisdiction="Bend",
            permit_number=number,
            issued_date=issued,
            permit_type=" / ".join(x for x in (application_type, cls._text(row.get("PermitTypeDescription"))) if x),
            building_use=building_use or None,
            project_name=description or None,
            address=address,
            units=units,
            valuation=valuation,
            contractor=contractor,
            owner=owner,
            status=cls._text(row.get("StatusDesc")) or "Issued",
            source_name="City of Bend Open Data — Permits and Contractors",
            source_url=cls.table_url,
            raw={
                "report_kind": report_kind,
                "work_proposed": application_type,
                "type_of_use": building_use,
                "description": description,
                "application_date": cls._date(row.get("ApplicationDate")),
                "permit_type_code": cls._text(row.get("PermitTypeCode")),
                "building_category": category,
                "census_structure": cls._text(poly.get("CensusStructureDesc")),
                "total_sqft": sqft,
                "zoning": cls._text(row.get("ZoningDesc")),
                "taxlot": cls._text(row.get("TAXLOT")),
                "contractor_reported": cls._text(row.get("ContractorName")),
                "general_contractor_reported": general_contractor,
                "table_object_id": row.get("OBJECTID"),
                "poly_object_id": poly.get("OBJECTID"),
            },
        )

    @staticmethod
    def _text(value) -> str:
        return str(value or "").strip()

    @staticmethod
    def _date(value) -> str | None:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).date().isoformat()
            except (OverflowError, OSError, ValueError):
                return None
        text = str(value).strip()[:10]
        try:
            return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None

    @staticmethod
    def _positive_int(value) -> int | None:
        try:
            number = int(float(value))
            return number if number > 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _positive_float(value) -> float | None:
        try:
            number = float(value)
            return number if number > 0 else None
        except (TypeError, ValueError):
            return None
