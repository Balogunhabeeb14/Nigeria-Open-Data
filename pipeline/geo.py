"""Nigeria's states: one list of codes and names for every source to share.

Sources spell states differently ("AKWA-IBOM", "Nassarawa", "F.C.T"). Mapping
them all to ISO 3166-2 codes is what lets data from different publishers be
joined, compared and, later, mapped.
"""
from __future__ import annotations

import re

# ISO 3166-2:NG code → name as shown on the site
STATES: dict[str, str] = {
    "NG-AB": "Abia", "NG-AD": "Adamawa", "NG-AK": "Akwa Ibom", "NG-AN": "Anambra",
    "NG-BA": "Bauchi", "NG-BY": "Bayelsa", "NG-BE": "Benue", "NG-BO": "Borno",
    "NG-CR": "Cross River", "NG-DE": "Delta", "NG-EB": "Ebonyi", "NG-ED": "Edo",
    "NG-EK": "Ekiti", "NG-EN": "Enugu", "NG-FC": "Federal Capital Territory",
    "NG-GO": "Gombe", "NG-IM": "Imo", "NG-JI": "Jigawa", "NG-KD": "Kaduna",
    "NG-KN": "Kano", "NG-KT": "Katsina", "NG-KE": "Kebbi", "NG-KO": "Kogi",
    "NG-KW": "Kwara", "NG-LA": "Lagos", "NG-NA": "Nasarawa", "NG-NI": "Niger",
    "NG-OG": "Ogun", "NG-ON": "Ondo", "NG-OS": "Osun", "NG-OY": "Oyo",
    "NG-PL": "Plateau", "NG-RI": "Rivers", "NG-SO": "Sokoto", "NG-TA": "Taraba",
    "NG-YO": "Yobe", "NG-ZA": "Zamfara",
}

# Other spellings seen in source documents → code
_ALIASES: dict[str, str] = {
    "akwaibom": "NG-AK", "crossriver": "NG-CR", "crossrivers": "NG-CR",
    "nassarawa": "NG-NA", "fct": "NG-FC", "fctabuja": "NG-FC", "abuja": "NG-FC",
    "federalcapitalterritory": "NG-FC", "abujafct": "NG-FC", "fcta": "NG-FC",
}


def _key(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower().replace("state", ""))


_BY_KEY: dict[str, str] = {**{_key(name): code for code, name in STATES.items()}, **_ALIASES}


def state_code(name: str) -> str | None:
    """'AKWA-IBOM' → 'NG-AK', 'F.C.T' → 'NG-FC'. None if it is not a state."""
    return _BY_KEY.get(_key(name or ""))


# Longest first, so 'CROSS RIVER' is tried before a shorter name could match.
STATE_SPELLINGS: list[tuple[str, str]] = sorted(
    (
        [(name, code) for code, name in STATES.items()]
        + [("Akwa-Ibom", "NG-AK"), ("Akwa/Ibom", "NG-AK"), ("A/Ibom", "NG-AK"),
           ("Cross-River", "NG-CR"), ("Cross Rivers", "NG-CR"), ("C/River", "NG-CR"),
           ("Nassarawa", "NG-NA"), ("F.C.T", "NG-FC"), ("FCT", "NG-FC"), ("Abuja", "NG-FC")]
    ),
    key=lambda pair: -len(pair[0]),
)
