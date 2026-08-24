from __future__ import annotations
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
import xml.etree.ElementTree as ET
from .models import Permit

def _write(title: str, site: str, permits: list[Permit], out: Path) -> None:
    rss=ET.Element("rss",{"version":"2.0"}); channel=ET.SubElement(rss,"channel")
    ET.SubElement(channel,"title").text=title
    ET.SubElement(channel,"link").text=site
    ET.SubElement(channel,"description").text="Oregon new-construction permit intelligence"
    for p in sorted(permits,key=lambda x:(x.issued_date or "",x.score),reverse=True)[:250]:
        item=ET.SubElement(channel,"item")
        ET.SubElement(item,"guid",{"isPermaLink":"false"}).text=p.key
        ET.SubElement(item,"title").text=f"[{p.jurisdiction}] {p.project_name or p.address or p.permit_number}"
        ET.SubElement(item,"link").text=p.source_url or site
        ET.SubElement(item,"description").text="\n".join([
            f"Category: {p.classification}",f"Score: {p.score}",f"Permit: {p.permit_number}",
            f"Issued: {p.issued_date}",f"Address: {p.address}",f"Contractor: {p.contractor or ''}",
            f"Valuation: {p.valuation or ''}",f"Units: {p.units or ''}"
        ])
        try:
            ET.SubElement(item,"pubDate").text=format_datetime(datetime.fromisoformat(p.issued_date).replace(tzinfo=timezone.utc))
        except ValueError:
            pass
    out.parent.mkdir(parents=True,exist_ok=True)
    tree=ET.ElementTree(rss); ET.indent(tree,space="  "); tree.write(out,encoding="utf-8",xml_declaration=True)

def write_all_feeds(out: Path, permits: list[Permit], site: str) -> None:
    q=[p for p in permits if p.qualifies]
    _write("Oregon New Construction",site,q,out/"new-construction.xml")
    _write("Oregon Single Family",site,[p for p in q if p.classification=="SINGLE_FAMILY"],out/"single-family.xml")
    _write("Oregon Multifamily",site,[p for p in q if p.classification=="MULTIFAMILY"],out/"multifamily.xml")
    _write("Oregon Commercial",site,[p for p in q if p.classification=="COMMERCIAL"],out/"commercial.xml")
    _write("Oregon Top Opportunities",site,[p for p in q if p.score>=30],out/"top-opportunities.xml")
