from __future__ import annotations
from datetime import datetime, timezone
from urllib.parse import urlparse
import re
import requests
from .base import CollectionResult, new_session
from ..models import Permit

class PortlandCollector:
    name = "Portland"
    freshness_days = 10
    service_url = "https://www.portlandmaps.com/arcgis/rest/services/Public/BDS_Permit/FeatureServer"
    source_url = service_url
    case_number_re = re.compile(r"^\d{2,4}-\d{6}-", re.I)
    layers = (
        (5, "Residential Construction Permit", "residential"),
        (2, "Commercial Construction Permit", "commercial"),
    )
    result_limit = 4000
    out_fields = ",".join((
        "APPLICATION","STATEIDKEY","PERMIT","TYPE","WORK_DESCRIPTION","ISSUED","DESCRIPTION","STATUS","GIS_PROCESS_STATUS",
        "HOUSE","DIRECTION","PROPSTREET","STREETTYPE","CITY","PORTLAND_MAPS_URL","OCCUPANCYGROUP",
        "CONSTRUCTIONTYPE","SUBMITTEDVALUATION","FINALVALUATION","NUMNEWUNITS","TOTALSQFT","NUMBSTORIES",
        "COUNTY","OBJECTID"
    ))

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        permits: dict[str, Permit] = {}
        for layer_id, layer_name, kind in self.layers:
            url = f"{self.service_url}/{layer_id}/query"
            params = {
                "where": "ISSUED IS NOT NULL",
                "outFields": self.out_fields,
                "returnGeometry": "false",
                "orderByFields": "ISSUED DESC",
                "resultRecordCount": self.result_limit,
                "resultOffset": 0,
                "f": "json",
            }
            response = session.get(url, params=params, timeout=90)
            response.raise_for_status()
            payload = response.json()
            features = self._validate_payload(payload, layer_name)
            for feature in features:
                attrs = feature.get("attributes") or {}
                permit = self._permit(attrs, layer_id, layer_name, kind)
                if permit:
                    permits[permit.key] = permit

        if not permits:
            raise RuntimeError("Portland BDS FeatureServer returned zero usable issued construction permits")
        return CollectionResult(
            self.name, list(permits.values()), self.source_url,
            "Official City of Portland BDS Permit FeatureServer construction layers 2 and 5"
        )

    @classmethod
    def _validate_payload(cls, payload, layer_name: str) -> list[dict]:
        if not isinstance(payload, dict):
            raise RuntimeError(f"Portland {layer_name} response is not a JSON object")
        if payload.get("error"):
            raise RuntimeError(f"Portland {layer_name} ArcGIS error: {payload['error']}")
        features = payload.get("features")
        if not isinstance(features, list) or not features:
            raise RuntimeError(f"Portland {layer_name} returned no features")
        keys: set[str] = set()
        for feature in features[:25]:
            attrs = feature.get("attributes") if isinstance(feature, dict) else None
            if isinstance(attrs, dict):
                keys.update(attrs.keys())
        required = {"APPLICATION","ISSUED","GIS_PROCESS_STATUS","PORTLAND_MAPS_URL"}
        missing = sorted(required - keys)
        if missing:
            raise RuntimeError(f"Portland {layer_name} schema check failed; missing {missing}")
        return features

    @classmethod
    def _permit(cls, a: dict, layer_id: int, layer_name: str, kind: str) -> Permit | None:
        number = str(a.get("APPLICATION") or a.get("STATEIDKEY") or "").strip()
        issued = cls._date(a.get("ISSUED"))
        if not number or not issued or not cls.case_number_re.match(number):
            return None
        link = cls._link(a.get("PORTLAND_MAPS_URL")) or f"{cls.service_url}/{layer_id}"
        if link.startswith("/"):
            link = "https://www.portlandmaps.com" + link
        host = (urlparse(link).hostname or "").lower()
        if host != "portlandmaps.com" and not host.endswith(".portlandmaps.com"):
            raise RuntimeError(f"Portland source identity check failed: foreign permit host {host}")

        desc = str(a.get("DESCRIPTION") or "").strip()
        work = str(a.get("WORK_DESCRIPTION") or "").strip()
        permit_type = str(a.get("TYPE") or "").strip()
        occupancy = str(a.get("OCCUPANCYGROUP") or "").strip()
        units = cls._positive_int(a.get("NUMNEWUNITS"))
        value = cls._positive_float(a.get("FINALVALUATION")) or cls._positive_float(a.get("SUBMITTEDVALUATION"))
        address = " ".join(str(a.get(k) or "").strip() for k in ("HOUSE","DIRECTION","PROPSTREET","STREETTYPE") if str(a.get(k) or "").strip())
        city = str(a.get("CITY") or "").strip()
        if city:
            address = f"{address}, {city}, OR" if address else f"{city}, OR"

        return Permit(
            state="OR", jurisdiction="Portland", permit_number=number, issued_date=issued,
            permit_type=" / ".join(x for x in (layer_name, permit_type or work) if x),
            building_use=permit_type or occupancy or None,
            project_name=desc or work or None,
            address=address, units=units, valuation=value,
            status=str(a.get("GIS_PROCESS_STATUS") or a.get("STATUS") or "").strip() or None,
            source_name="City of Portland BDS Permit FeatureServer", source_url=link,
            raw={
                "report_kind": kind,
                "source_construction_layer": True,
                "source_layer_id": layer_id,
                "source_layer_name": layer_name,
                "work_proposed": work,
                "type_of_use": permit_type or occupancy,
                "description": desc,
                "permit_category": a.get("PERMIT"),
                "permit_type_code": permit_type,
                "occupancy_group": occupancy,
                "state_id_key": a.get("STATEIDKEY"),
                "construction_type": a.get("CONSTRUCTIONTYPE"),
                "total_sqft": a.get("TOTALSQFT"),
                "stories": a.get("NUMBSTORIES"),
                "county": a.get("COUNTY"),
                "object_id": a.get("OBJECTID"),
            },
        )

    @staticmethod
    def _link(value) -> str | None:
        value = str(value or "").strip()
        return value or None

    @staticmethod
    def _date(value) -> str | None:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(float(value)/1000, tz=timezone.utc).date().isoformat()
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
