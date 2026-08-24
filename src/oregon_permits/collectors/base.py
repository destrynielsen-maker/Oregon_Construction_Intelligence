from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from ..models import Permit

@dataclass
class CollectionResult:
    source: str
    permits: list[Permit]
    source_url: str
    note: str = ""

class Collector(Protocol):
    name: str
    freshness_days: int
    def collect(self, session: requests.Session | None = None) -> CollectionResult: ...

def new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "OregonConstructionIntelligence/0.1 (+public-permit-research; respectful polling)"})
    retry = Retry(total=3, connect=3, read=3, status=3, backoff_factor=1.0,
                  status_forcelist=(429,500,502,503,504), allowed_methods=frozenset(["GET"]))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session
