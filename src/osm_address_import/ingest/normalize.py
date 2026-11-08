"""Conservative comparison keys; original strings remain in staged output."""

import re


DIRECTIONS = {
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
    "NORTHEAST": "NE", "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW",
}
SUFFIXES = {
    "STREET": "ST", "ROAD": "RD", "AVENUE": "AVE", "BOULEVARD": "BLVD",
    "DRIVE": "DR", "LANE": "LN", "COURT": "CT", "PLACE": "PL",
    "TERRACE": "TER", "CIRCLE": "CIR", "PARKWAY": "PKWY", "HIGHWAY": "HWY",
}
UNIT_TYPES = {"APARTMENT": "APT", "SUITE": "STE", "UNIT": "UNIT"}
ASCII_UPPER = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def compact(value: str) -> str:
    """Fold ASCII case and whitespace only; retain punctuation and leading zeros."""
    return " ".join(value.split()).translate(ASCII_UPPER)


def normalize_row(row: dict[str, str]) -> dict[str, str]:
    house = compact(row["house_number"])
    street = compact(row["street_name"])
    locality = compact(row["locality"])
    if not house or not street or not locality:
        raise ValueError("SOURCE_INCOMPLETE")
    if not re.fullmatch(r"[0-9][0-9A-Z /-]*", house):
        raise ValueError("INVALID_HOUSE_NUMBER")

    unit_type = compact(row.get("unit_type", ""))
    unit_id = compact(row.get("unit_id", ""))
    if bool(unit_type) != bool(unit_id):
        raise ValueError("UNIT_INCOMPLETE")
    postcode = compact(row.get("postcode", ""))
    if postcode and not re.fullmatch(r"[0-9]{5}(?:-[0-9]{4})?", postcode):
        raise ValueError("INVALID_POSTCODE")

    pre = compact(row.get("pre_directional", ""))
    post = compact(row.get("post_directional", ""))
    suffix = compact(row.get("street_suffix", ""))
    return {
        "house_number": house,
        "pre_directional": DIRECTIONS.get(pre, pre),
        "street_name": street,
        "street_suffix": SUFFIXES.get(suffix, suffix),
        "post_directional": DIRECTIONS.get(post, post),
        "unit_type": UNIT_TYPES.get(unit_type, unit_type),
        "unit_id": unit_id,
        "locality": locality,
        "state": compact(row["state"]),
        "county_id": compact(row["county_id"]),
        "postcode": postcode,
    }


def address_key(normalized: dict[str, str]) -> tuple[str, ...]:
    """Postcode and coordinates are compared as evidence, not identity."""
    return tuple(normalized[key] for key in (
        "state", "county_id", "locality", "house_number", "pre_directional",
        "street_name", "street_suffix", "post_directional", "unit_type", "unit_id",
    ))
