"""
Kenya-only filtering, Form 4 (KCSE) job evaluation and location zones
for Gunga Job Radar.

Everything in here is pure logic (no network, no database) so it can be
unit-tested on its own — see tests_kenya_jobs.py.

What lives here
---------------
1. Remote-job gate     -> looks_remote(), REMOTE_ELIGIBILITIES
2. Form 4 evaluation   -> evaluate_form4(), parse_myjobmag_detail()
3. Location zones      -> classify_zone() / ZONE_LABELS

Design notes
------------
* "Form 4 job" here means: a job whose minimum requirement is KCSE /
  Form Four (or lower) and that does NOT ask for any other certificate,
  diploma, degree, licence, trade-test grade or professional
  registration.
* Job ads often don't state their requirements clearly. When the text
  doesn't settle it, the job is kept and marked level="likely" rather
  than silently dropped or silently trusted.
* The KCSE grade filter uses MY_KCSE_GRADE below. A job asking for a
  mean grade ABOVE this is rejected. Change it if your grade changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup


# ============================================================
# 1. REMOTE-JOB GATE
# ============================================================

# Eligibility values (from classify_location in job_radar.py) that
# mean "not a Kenya on-site job". These are dropped at scan time.
REMOTE_ELIGIBILITIES = frozenset({
    "REMOTE-AFRICA",
    "REMOTE-WORLDWIDE",
    "REMOTE-RESTRICTED",
})

_REMOTE_TITLE_LOCATION_RE = re.compile(
    r"\b(remote|work\s+from\s+home|wfh|home[-\s]based|"
    r"telecommut\w*|virtual\s+assistant)\b",
    re.IGNORECASE,
)

# In descriptions the bare word "remote" is too noisy ("remote areas",
# "remote villages"), so only unmistakable phrases count there.
_REMOTE_DESCRIPTION_RE = re.compile(
    r"\b(fully\s+remote|100%\s+remote|remote\s+(?:position|role|job|work|"
    r"opportunity|only)|work\s+from\s+home|work\s+remotely|"
    r"remote[-\s]first|this\s+is\s+a\s+remote|"
    r"work\s+from\s+anywhere|anywhere\s+in\s+the\s+world)\b",
    re.IGNORECASE,
)


def looks_remote(job: dict[str, Any]) -> bool:
    """True when the posting is clearly a remote / work-from-home job."""

    title = str(job.get("title") or "")
    location = str(job.get("location") or "")
    description = str(job.get("description") or "")

    if _REMOTE_TITLE_LOCATION_RE.search(f"{title} {location}"):
        return True

    return bool(_REMOTE_DESCRIPTION_RE.search(description))


# ============================================================
# 2. FORM 4 (KCSE) EVALUATION
# ============================================================

# Evans's KCSE mean grade. Jobs requiring a HIGHER mean grade are
# rejected. Order is best -> worst.
MY_KCSE_GRADE = "C"

KCSE_GRADE_ORDER = [
    "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "E",
]

# Phrases that contain the word "certificate" but do NOT mean an
# extra qualification is required. Stripped before scanning.
_BENIGN_PHRASES = [
    r"kenya\s+certificate\s+of\s+secondary\s+education",
    r"certificate\s+of\s+secondary\s+education",
    r"kcse\s+certificates?",
    r"kcpe\s+certificates?",
    r"(?:first\s+)?school\s+leaving\s+certificates?",
    r"certificates?\s+of\s+good\s+conduct",
    r"good\s+conduct\s+certificates?",
    r"certificates?\s+of\s+(?:good\s+)?(?:conduct|clearance)",
    r"(?:copies|copy|photocopies|scanned)\s+of\s+(?:your\s+|all\s+|"
    r"relevant\s+|academic\s+|original\s+|supporting\s+)*"
    r"(?:certificates?|documents?|testimonials?)",
    r"certificates?\s+(?:and|&)\s+testimonials?",
    r"birth\s+certificates?",
    r"never\s+pay\s+for\s+any[^.]*certificate[^.]*",
]
_BENIGN_RE = re.compile("|".join(_BENIGN_PHRASES), re.IGNORECASE)

# Requirement patterns that disqualify a job from "Form 4 only".
_BLOCKERS: list[tuple[str, re.Pattern[str]]] = [
    (
        "degree required",
        re.compile(
            r"\b(bachelor'?s?|degree|b\.?\s?sc\.?|b\.?\s?com\.?|"
            r"hnd|higher\s+national|masters?|m\.?\s?sc\.?|mba|phd|"
            r"post[-\s]?graduate|university\s+graduate)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "diploma required",
        re.compile(r"\bdiploma\b", re.IGNORECASE),
    ),
    (
        "extra certificate required",
        re.compile(
            r"\b(certificates?|certification|certified|proficiency|"
            r"cpa|acca|cisa|ccna|trade\s+test|artisan|"
            r"craft\s+(?:certificate|level|course)|knec|tvet|nita|kmtc)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "licence required",
        re.compile(
            r"\b(licen[cs]e[sd]?|ntsa|psv|class\s+[a-e]\b|"
            r"driving\s+permit|firearm)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "professional registration required",
        re.compile(
            r"\b(registered\s+(?:with|by)|registration\s+(?:with|by)|"
            r"practicing\s+certificate|practising\s+certificate)\b",
            re.IGNORECASE,
        ),
    ),
]

# A mention is NOT a hard requirement when its sentence says so.
_SOFT_RE = re.compile(
    r"\b(advantage|preferred|desirable|an?\s+asset|added\s+advantage|"
    r"not\s+required|not\s+mandatory|not\s+necessary|optional|"
    r"will\s+be\s+considered|is\s+a\s+plus)\b",
    re.IGNORECASE,
)

# Roles that inherently need a licence, trade grade or professional
# qualification even when the ad's snippet doesn't spell it out.
_ROLE_BLOCK_RE = re.compile(
    r"\b(driver|rider|nurse|clinical\s+officer|pharmac\w*|"
    r"lab(?:oratory)?\s+(?:technician|technologist)|teacher|lecturer|"
    r"accountant|auditor|engineer|technician|electrician|mechanic|"
    r"surveyor|architect|lawyer|advocate|pilot|pharmacist|"
    r"physiotherapist|counsell?or|veterinary)\b",
    re.IGNORECASE,
)

_KCSE_RE = re.compile(
    r"\b(kcse|k\.c\.s\.e|form\s+(?:4|four|iv)|secondary\s+"
    r"(?:school\s+)?(?:certificate|education|level)|kcpe|"
    r"school\s+leaving)\b",
    re.IGNORECASE,
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;:!?])\s+|\n+|•|·|\s[-–—]\s")

_GRADE_RE = re.compile(
    r"\b(?:mean\s+grade|grade\s+of|minimum\s+grade|mean\s+of)\s+"
    r"(?:at\s+least\s+|of\s+)?([A-Ea-e])(?![A-Za-z])\s*"
    r"(\+|-|plus|minus|\(plus\)|\(minus\)|plain|\(plain\))?",
    re.IGNORECASE,
)

_LEVEL_NAMES = [
    "BA/BSc/HND",
    "Diploma",
    "First School Leaving Certificate",
    "KCSE",
    "MBA/MSc/MA",
    "Others",
    "PhD/Fellowship",
    "Postgraduate Diploma",
    "Professional Certificate",
    "Vocational",
]


@dataclass
class Form4Result:
    ok: bool
    level: str = "likely"  # "confirmed" | "likely"
    reasons: list[str] = field(default_factory=list)
    reject_reason: str | None = None


def _normalise_grade(letter: str, modifier: str | None) -> str:
    letter = letter.upper()
    mod = (modifier or "").lower().strip("() ")

    if mod in ("+", "plus"):
        return f"{letter}+"

    if mod in ("-", "minus"):
        return f"{letter}-"

    return letter


def required_kcse_grade(text: str) -> str | None:
    """Strictest KCSE mean grade the ad asks for, or None."""

    best: str | None = None

    for line in _SENTENCE_SPLIT_RE.split(text or ""):

        if not _KCSE_RE.search(line):
            continue

        for match in _GRADE_RE.finditer(line):

            # Listing snippets are stored lower-case, so a bare
            # lower-case letter ("grade of a minimum of ...") is only
            # trusted when it has a modifier or ends the phrase.
            if (
                match.group(1).islower()
                and not match.group(2)
                and line[match.end():match.end() + 1] not in ("", ",", ".", ";", ")")
            ):
                continue

            grade = _normalise_grade(match.group(1), match.group(2))

            if grade not in KCSE_GRADE_ORDER:
                continue

            if (
                best is None
                or KCSE_GRADE_ORDER.index(grade)
                < KCSE_GRADE_ORDER.index(best)
            ):
                best = grade

    return best


def _find_blocker(text: str) -> str | None:
    """First hard extra-qualification requirement found, else None."""

    cleaned = _BENIGN_RE.sub(" ", text or "")

    for line in _SENTENCE_SPLIT_RE.split(cleaned):

        if not line.strip():
            continue

        if _SOFT_RE.search(line):
            continue

        # "KCSE ... or Diploma" style alternatives are not a hard
        # requirement: Form 4 is one accepted route.
        is_alternative = bool(
            _KCSE_RE.search(line)
            and re.search(r"\bor\b", line, re.IGNORECASE)
        )

        for label, pattern in _BLOCKERS:

            if pattern.search(line):

                if is_alternative:
                    continue

                return label

    return None


def evaluate_form4(
    job: dict[str, Any],
    detail: dict[str, Any] | None = None,
) -> Form4Result:
    """Decide whether a job is a true Form 4 (KCSE-minimum) job.

    `detail` is the optional output of parse_myjobmag_detail():
    {"body": str, "qualifications": [..], "experience": str}.
    Without it the decision rests on the listing title + snippet only.
    """

    detail = detail or {}

    title = str(job.get("title") or "")
    snippet = str(job.get("description") or "")
    body = str(detail.get("body") or "")
    qualifications: list[str] = list(detail.get("qualifications") or [])

    text = f"{title}. {snippet}. {body}"

    if _ROLE_BLOCK_RE.search(title):
        return Form4Result(
            ok=False,
            reject_reason="role normally needs a licence or qualification",
        )

    blocker = _find_blocker(text)

    if blocker:
        return Form4Result(ok=False, reject_reason=blocker)

    grade = required_kcse_grade(text)

    if grade and (
        KCSE_GRADE_ORDER.index(grade)
        < KCSE_GRADE_ORDER.index(MY_KCSE_GRADE)
    ):
        return Form4Result(
            ok=False,
            reject_reason=f"KCSE grade {grade} required",
        )

    tag_text = " ".join(qualifications).lower()
    tag_confirms = (
        "kcse" in tag_text or "first school leaving" in tag_text
    )

    confirmed = tag_confirms or bool(_KCSE_RE.search(text))

    reasons = [
        "🎓 Form 4 (KCSE) accepted"
        if confirmed
        else "🎓 Listed as a KCSE-level job (requirements not spelled out)",
        "No extra certificate, diploma or licence asked for",
    ]

    if grade:
        reasons.append(f"KCSE mean grade {grade} or similar")

    experience = str(detail.get("experience") or "").strip()

    if experience:
        reasons.append(f"Experience: {experience}")

    return Form4Result(
        ok=True,
        level="confirmed" if confirmed else "likely",
        reasons=reasons,
    )


def form4_score(result: Form4Result) -> int:
    """Stable, simple score for Form 4 jobs.

    Capped below the 'strong' threshold on purpose: Form 4 jobs are
    shown in their own tab and never trigger Telegram alerts.
    """

    return 70 if result.level == "confirmed" else 55


def parse_myjobmag_detail(html: str) -> dict[str, Any]:
    """Parse a MyJobMag job-detail page.

    Returns {"body": requirements/duties text, "qualifications":
    [education tags], "experience": str}. Any part that can't be found
    comes back empty — callers must cope with that.
    """

    soup = BeautifulSoup(html or "", "html.parser")

    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    text = soup.get_text("\n")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)

    start = text.find("Job Type")

    if start == -1:
        return {"body": "", "qualifications": [], "experience": ""}

    end_candidates = [
        text.find(marker, start)
        for marker in (
            "Method of Application",
            "Check how your CV matches",
            "Apply Now",
        )
    ]
    end_candidates = [i for i in end_candidates if i != -1]
    end = min(end_candidates) if end_candidates else len(text)

    segment = text[start:end]

    qualifications: list[str] = []

    q_match = re.search(
        r"Qualification\s*(.*?)\s*Experience",
        segment,
        re.DOTALL,
    )

    if q_match:
        chunk = q_match.group(1).lower()
        qualifications = [
            name
            for name in _LEVEL_NAMES
            if name.lower() in chunk
        ]

    experience = ""

    e_match = re.search(
        r"Experience\s*\n?\s*([^\n]+)",
        segment,
    )

    if e_match:
        experience = e_match.group(1).strip()

    # Body = everything after the "Job Field" line and its value, so
    # the education tags above can never be mistaken for requirements.
    body = ""

    b_match = re.search(
        r"Job Field[^\n]*\n[^\n]*\n(.*)$",
        segment,
        re.DOTALL,
    )

    if b_match:
        body = re.sub(r"\s+", " ", b_match.group(1)).strip()

    return {
        "body": body,
        "qualifications": qualifications,
        "experience": experience,
    }


# ============================================================
# 3. LOCATION ZONES
# ============================================================
#
# zone_rank is stored on each job so the dashboard can filter and sort
# "nearest first" in the database. Lower = closer to Malindi.
#
#   0  Malindi / Kilifi County
#   1  Rest of the Coast (Mombasa, Kwale, Taita Taveta, Lamu, ...)
#   2  Nairobi & surrounds
#   3  Eldoret / Uasin Gishu
#   4  Narok / Maasai Mara
#   9  Elsewhere in Kenya

ZONE_LABELS = {
    0: "📍 Malindi & Kilifi",
    1: "🌴 Coast",
    2: "🏙 Nairobi area",
    3: "Eldoret",
    4: "Narok & Mara",
    9: "Elsewhere in Kenya",
}

ZONE_KEYWORDS: dict[int, list[str]] = {
    0: [
        "malindi", "watamu", "gede", "kilifi", "mtwapa", "mariakani",
        "kaloleni", "ganze", "magarini", "mnarani", "takaungu",
        "vipingo", "kikambala", "rabai", "kijipwa", "marafa",
    ],
    1: [
        "mombasa", "likoni", "nyali", "bamburi", "changamwe", "kisauni",
        "diani", "ukunda", "kwale", "msambweni", "lunga lunga", "voi",
        "taita", "taveta", "wundanyi", "mwatate", "lamu", "tana river",
        "garsen", "hola", "mazeras", "shimba hills", "kinango",
    ],
    2: [
        "nairobi", "kiambu", "thika", "ruiru", "juja", "kitengela",
        "kajiado", "machakos", "athi river", "ngong", "rongai", "limuru",
        "kikuyu", "karen", "westlands", "lavington", "kileleshwa",
        "upper hill", "upperhill", "industrial area", "embakasi",
        "syokimau", "mlolongo", "ruaka", "kasarani", "gigiri", "runda",
        "kilimani", "parklands", "langata", "south b", "south c",
        "donholm", "buruburu", "eastleigh", "ngara",
    ],
    3: ["eldoret", "uasin gishu", "moi's bridge", "burnt forest"],
    4: [
        "narok", "maasai mara", "masai mara", "talek", "sekenani",
        "ololulunga", "kilgoris", "aitong", "mara north", "mara south",
    ],
}


def _zone_regex(words: list[str]) -> re.Pattern[str]:
    return re.compile(
        r"\b(" + "|".join(re.escape(w) for w in words) + r")\b",
        re.IGNORECASE,
    )


_ZONE_PATTERNS = {
    rank: _zone_regex(words) for rank, words in ZONE_KEYWORDS.items()
}


def _zone_from_text(text: str) -> int | None:
    best: int | None = None

    for rank, pattern in _ZONE_PATTERNS.items():

        if pattern.search(text):

            if best is None or rank < best:
                best = rank

    return best


def classify_zone(
    location: str | None,
    title: str | None = None,
) -> int:
    """Return the zone rank (0 = nearest Malindi ... 9 = elsewhere).

    Looks at the location text first, then the title (ads often put
    the town in the title, e.g. "Cleaner - Lavington"). The company
    description is deliberately NOT scanned: it mentions head offices
    and would mis-place most jobs.
    """

    for text in (location or "", title or ""):

        rank = _zone_from_text(text)

        if rank is not None:
            return rank

    return 9
