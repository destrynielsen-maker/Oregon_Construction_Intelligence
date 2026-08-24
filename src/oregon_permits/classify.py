from __future__ import annotations
import re
from .models import Permit

MULTI = re.compile(
    r"\b(multi[ -]?family|apartment|apartments|condo|minium|townhome|townhouse|"
    r"duplex|triplex|fourplex|two[- ]family|three[- ]family|four[- ]family|"
    r"\d+\s*[- ]?unit(?:s)?|dwelling units?)\b", re.I
)
SINGLE = re.compile(r"\b(single[- ]family|one[- ]family|single family dwelling|detached dwelling)\b", re.I)
COMMERCIAL = re.compile(
    r"\b(commercial|business|mercantile|retail|office|warehouse|storage|factory|industrial|"
    r"institutional|hospital|school|hotel|motel|assembly|utility)\b", re.I
)
EXCLUDE_USE = re.compile(r"\b(garage/carport|accessory dwelling|adu\b|shed\b)", re.I)
DERIVATIVE = re.compile(r"-(?:DFS|REV)-", re.I)

def classify_permit(p: Permit) -> Permit:
    raw = p.raw or {}
    work = str(raw.get("work_proposed") or "")
    use = str(raw.get("type_of_use") or p.building_use or "")
    desc = str(raw.get("description") or p.project_name or "")
    report_kind = str(raw.get("report_kind") or "").lower()
    authoritative_construction = raw.get("source_construction_layer") is True
    text = " ".join([p.permit_type or "", work, use, desc])

    if DERIVATIVE.search(p.permit_number) or EXCLUDE_USE.search(use):
        return _other(p)

    is_new = authoritative_construction or bool(re.search(
        r"\bnew construction\b|construct(?:ion)?\s+new|new\s+(?:single[- ]family|dwelling|building|home|residence)",
        text, re.I
    ))
    if not is_new:
        return _other(p)

    units = int(p.units or 0)
    explicit_multi = bool(MULTI.search(use) or MULTI.search(desc))
    explicit_single = bool(SINGLE.search(use) or SINGLE.search(desc))

    if authoritative_construction and report_kind == "residential":
        if explicit_multi:
            p.classification = "MULTIFAMILY"
        elif explicit_single:
            p.classification = "SINGLE_FAMILY"
        else:
            p.classification = "MULTIFAMILY" if units > 1 else "SINGLE_FAMILY"
    elif authoritative_construction and report_kind == "commercial":
        p.classification = "MULTIFAMILY" if (explicit_multi or units > 1) else "COMMERCIAL"
    elif explicit_multi or units > 1:
        p.classification = "MULTIFAMILY"
    elif explicit_single:
        p.classification = "SINGLE_FAMILY"
    elif report_kind == "commercial" or COMMERCIAL.search(use):
        p.classification = "COMMERCIAL"
    else:
        return _other(p)

    p.qualifies = True
    p.new_construction_confidence = "HIGH"
    score = {"MULTIFAMILY":40, "COMMERCIAL":30, "SINGLE_FAMILY":15}[p.classification]
    value = float(p.valuation or 0)
    if value >= 20_000_000: score += 25
    elif value >= 10_000_000: score += 20
    elif value >= 5_000_000: score += 15
    elif value >= 1_000_000: score += 10
    elif value >= 500_000: score += 5
    if units >= 100: score += 20
    elif units >= 50: score += 15
    elif units >= 20: score += 10
    elif units >= 5: score += 5
    if p.contractor: score += 5
    if p.owner: score += 3
    p.score = min(score,100)
    return p

def _other(p: Permit) -> Permit:
    p.classification="OTHER"
    p.qualifies=False
    p.score=0
    p.new_construction_confidence="LOW"
    return p
