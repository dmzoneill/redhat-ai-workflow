"""Parse Slack user directory + Workday org chart names to build a peer roster.

Cross-references Slack NDJSON export (which has kerberos usernames via email)
against Workday org chart names (which have job titles / grade levels) to produce
an org_roster.json with all resolved peers per engineering level.

Usage:
    python -m services.stats.org_parser            # uses default paths
    python -m services.stats.org_parser --per-level 10  # limit to 10 per level
"""

from __future__ import annotations

import json
import logging
import random
import re
import subprocess
import unicodedata
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

AA_CONFIG_DIR = Path.home() / ".config" / "aa-workflow"
ORG_DIR = AA_CONFIG_DIR / "performance" / "org"
SLACK_FILE = ORG_DIR / "slack_users.json"
ROSTER_FILE = ORG_DIR / "org_roster.json"

PEERS_PER_LEVEL = 0  # 0 = include all resolved peers (no sampling limit)

TITLE_TO_LEVEL: list[tuple[re.Pattern, str]] = [
    (re.compile(r"senior\s+principal\s+software\s+engineer", re.I), "spse"),
    (re.compile(r"senior\s+principal\s+.*engineer", re.I), "spse"),
    (re.compile(r"distinguished\s+engineer", re.I), "de"),
    (re.compile(r"principal\s+software\s+engineer", re.I), "pse"),
    (re.compile(r"principal\s+.*engineer", re.I), "pse"),
    (re.compile(r"senior\s+software\s+engineer", re.I), "sse"),
    (re.compile(r"senior\s+.*engineer", re.I), "sse"),
    (re.compile(r"associate\s+software\s+engineer", re.I), "ase"),
    (re.compile(r"associate\s+.*engineer", re.I), "ase"),
    (re.compile(r"^software\s+engineer", re.I), "se"),
]

MANAGEMENT_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"director",
        r"manager",
        r"chief\s+of\s+staff",
        r"agile.*coach",
        r"agile.*practitioner",
        r"scrum\s+master",
        r"delivery\s+coach",
        r"project\s+manager",
    ]
]

_INLINE_ORG_CHART_NAMES: list[tuple[str, str]] = [
    ("Kevin Myers", "Senior Director, Software Engineering Global"),
    ("Aaron Withrow", "Director, Engineering"),
    ("Chuck Brant", "Director, Engineering"),
    ("Iftikhar Khan", "Director, Engineering"),
    ("Valerie Sroka", "Chief of Staff, Ansible Engineering"),
    ("Matthew Jones", "Distinguished Engineer"),
    ("Naveen Malik", "Senior Principal Software Engineer"),
    ("Ben Thomasson", "Senior Principal Software Engineer"),
    ("James Cammarata", "Manager, Engineering"),
    ("Brian King", "Senior Manager, Engineering"),
    ("John Barker", "Manager, Engineering"),
    ("Michael Barnett", "Manager, Engineering"),
    ("Trishna Guha", "Senior Manager, Engineering"),
    ("Brad Thornton", "Senior Principal Software Engineer - Ansible Networking"),
    ("Tony Fister", "Senior Manager, Engineering"),
    ("Ganesh Nalawade", "Senior Principal Software Engineer"),
    ("Jill Rouleau", "Senior Principal Software Engineer"),
    ("Eric Hodge", "Senior Manager, Engineering"),
    ("Yanis Guenane", "Senior Manager, Engineering"),
    ("Chris Risen", "Agile Delivery Coach"),
    ("Heather Smith", "Enterprise Agile & Leadership Coach"),
    ("Nathan Weatherly", "Manager, Engineering"),
    ("Og Maciel", "Senior Manager, Engineering"),
    ("Zvika Sadeh", "Associate Manager, Site Reliability Engineering"),
    ("Lisa Wojcik", "Manager, Ansible Agility Team"),
    ("Alison Dudiak", "Senior Agile Practitioner"),
    ("Aaron Hetherington", "Principal Software Engineer"),
    ("Abhijeet Kasurde", "Principal Software Engineer"),
    ("Abhinav Anand", "Software Engineer"),
    ("Abhishek Chaudhary", "Associate Software Engineer"),
    ("Adam Knochowski", "Senior Software Engineer"),
    ("Adrià Sala", "Senior Software Engineer"),
    ("Adriana Cruz Gonzalez", "Associate Software Engineer"),
    ("Ajinkya Udgirkar", "Principal Software Engineer"),
    ("Akash Kanni", "Senior Software Engineer"),
    ("Alan Rominger", "Principal Software Engineer"),
    ("Albert Daunis Torras", "Senior Software Engineer"),
    ("Alejandro Izquierdo", "Senior Software Engineer"),
    ("Alex Corey", "Principal Software Engineer"),
    ("Alex Oladele", "Associate Software Engineer"),
    ("Alina Buzachis", "Principal Software Engineer"),
    ("Alison Hart", "Senior Software Engineer"),
    ("Amanda Dwyer", "Senior Software Engineer"),
    ("Ana Carolina Ferreira", "Associate Software Engineer"),
    ("Anand Singla", "Principal Software Engineer"),
    ("Andrea Restle-Lay", "Associate Software Engineer"),
    ("Andrei Klychkov", "Senior Software Engineer"),
    ("Andrew Potozniak", "Associate Software Engineer"),
    ("Ankit Sharma", "Associate Software Engineer"),
    ("Anushka Shukla", "Associate Software Engineer"),
    ("Anwesha Das", "Senior Software Engineer"),
    ("Aparna Karve", "Senior Software Engineer"),
    ("Apurva Kulkarni", "Associate Software Engineer"),
    ("Ashlyn Chapman", "Associate Software Engineer"),
    ("AAYUSH ANAND", "Associate Software Engineer"),
    ("Benjamin Dudas", "Senior Software Engineer"),
    ("Benny Rahmanim", "Senior Software Engineer"),
    ("Bhavik Bhavsar", "Principal Software Engineer"),
    ("Bianca Henderson", "Senior Software Engineer"),
    ("Bill Wei", "Senior Software Engineer"),
    ("BRANDON WHITTINGTON", "Software Engineer"),
    ("Brennan Paciorek", "Senior Software Engineer"),
    ("Brian Coca", "Senior Principal Software Engineer"),
    ("Brian McLaughlin", "Senior Software Engineer"),
    ("Bruno Rocha", "Senior Software Engineer"),
    ("Bruno Sanchez", "Software Engineer"),
    ("Bryan Havenstein", "Software Engineer"),
    ("Carlos Berejnoi Bejarano", "Associate Software Engineer"),
    ("Carey Rogers", "Software Engineer"),
    ("Chetna Agrawal", "Senior Software Engineer"),
    ("Chris Ahl", "Senior Software Engineer"),
    ("Chris Meyers", "Principal Software Engineer"),
    ("Christian Adams", "Senior Software Engineer"),
    ("Christian Huffman", "Senior Software Engineer"),
    ("Christian Torrens", "Software Engineer"),
    ("Chyna Sanders", "Software Engineer"),
    ("Ciaran Shiels", "Software Engineer"),
    ("Dan Leehr", "Software Engineer"),
    ("Daniel Brennand", "Software Engineer"),
    ("Daniel Finca Martínez", "Software Engineer"),
    ("Daniel Rodowicz", "Principal Software Engineer"),
    ("Dave Mulford", "Senior Software Engineer"),
    ("David Hageman", "Principal Software Engineer"),
    ("David O Neill", "Principal Software Engineer"),
    ("David Schmidt", "Senior Software Engineer"),
    ("David Shrewsbury", "Principal Software Engineer"),
    ("Deeksha Kulal", "Associate Software Engineer"),
    ("Demetrius Costa Silva Faria Lima", "Software Engineer"),
    ("Dimitri Savineau", "Senior Software Engineer"),
    ("Dirk Jülich", "Senior Software Engineer"),
    ("Djebran Lezzoum", "Senior Software Engineer"),
    ("Dominique Vernier", "Senior Software Engineer"),
    ("Don Naro", "Senior Software Engineer"),
    ("Doston Toirov", "Software Engineer"),
    ("Elyezer Rezende", "Senior Software Engineer"),
    ("Emily Trombley", "Senior Software Engineer"),
    ("Erik Clarizio", "Software Engineer"),
    ("Fabrizio Asta", "Senior Software Engineer"),
    ("Fran Perea Rodriguez", "Software Engineer"),
    ("Gomathi Selvi Srinivasan", "Principal Software Engineer"),
    ("Goneri Le Bouder", "Principal Software Engineer"),
    ("Hannah DeFazio", "Software Engineer"),
    ("Hao Liu", "Senior Software Engineer"),
    ("Harpreet Kataria", "Senior Software Engineer"),
    ("Helen Bailey", "Software Engineer"),
    ("Hui Song", "Senior Software Engineer"),
    ("Hunter Kepley", "Software Engineer"),
    ("Ingrid Sena", "Senior Software Engineer"),
    ("Jacob Cole", "Senior Software Engineer"),
    ("Jake Jackson", "Principal Software Engineer"),
    ("James Marshall", "Principal Software Engineer"),
    ("James Mighion", "Senior Software Engineer"),
    ("James Wong", "Principal Software Engineer"),
    ("Jeevan S", "Senior Software Engineer"),
    ("Jeff Headley", "Associate Software Engineer"),
    ("Jeff Marmolejos Almonte", "Software Engineer"),
    ("Jeff Needle", "Principal Software Engineer"),
    ("Jessica Mack", "Software Engineer"),
    ("Jessica Serafini Steurer", "Senior Software Engineer"),
    ("Jiri Jerabek", "Senior Software Engineer"),
    ("John Mitchell", "Senior Software Engineer"),
    ("John Westcott", "Principal Software Engineer"),
    ("Jordan Borean", "Senior Software Engineer"),
    ("Julen Landa Alustiza", "Senior Software Engineer"),
    ("Kaio Oliveira", "Software Engineer"),
    ("Kate Case", "Senior Software Engineer"),
    ("Kaushiki Singh", "Associate Software Engineer"),
    ("Keith Grant", "Senior Software Engineer"),
    ("Kersom Moura Oliveira", "Software Engineer"),
    ("Kia Lam", "Senior Software Engineer"),
    ("Kirill Gaevskii", "Senior Software Engineer"),
    ("Komal Desai", "Senior Software Engineer"),
    ("Laura Galis", "Software Engineer"),
    ("Leena Jawale", "Senior Software Engineer"),
    ("Lila Yasin", "Software Engineer"),
    ("Lucas Aoki Heredia", "Associate Software Engineer"),
    ("Lucas Benedito", "Software Engineer"),
    ("Luiz Felipe Fernandes Machado Costa", "Software Engineer"),
    ("Madhu Kanoor", "Principal Software Engineer"),
    ("Maeve Hoffer", "Software Engineer"),
    ("Mandar Kulkarni", "Software Engineer"),
    ("Marliana Lara", "Principal Software Engineer"),
    ("Martin Hradil", "Principal Software Engineer"),
    ("Martin Krizek", "Senior Software Engineer"),
    ("Matt Clay", "Senior Principal Software Engineer"),
    ("Matt Davis", "Senior Principal Software Engineer"),
    ("Matthew Johnson", "Software Engineer"),
    ("Matthew Sandoval", "Senior Software Engineer"),
    ("Mauricio Magnani Jr", "Senior Software Engineer"),
    ("Melissa Kelly", "Software Engineer"),
    ("Michael Abashian", "Principal Software Engineer"),
    ("Michael Anstis", "Principal Software Engineer"),
    ("Mike Graves", "Senior Software Engineer"),
    ("Mike Silmser", "Senior Software Engineer"),
    ("Milan Pospisil", "Senior Software Engineer"),
    ("Nickolos Monk", "Associate Software Engineer"),
    ("Nikhil Bhasin", "Senior Software Engineer"),
    ("Nikole Nguyen", "Senior Software Engineer"),
    ("Nilashish Chakraborty", "Senior Software Engineer"),
    ("Oleksii Baranov", "Senior Software Engineer"),
    ("Or Hochmann", "Senior Software Engineer"),
    ("Pablo Hiroshi Alonso", "Software Engineer"),
    ("Patrick Kingston", "Software Engineer"),
    ("Paul Bohmiller", "Senior Software Engineer"),
    ("Paul Flanagan", "Senior Software Engineer"),
    ("Pavan Jangale", "Software Engineer"),
    ("Pavan Kesava Rao", "Senior Software Engineer"),
    ("Peter Braun", "Principal Software Engineer"),
    ("Pino Toscano", "Principal Software Engineer"),
    ("Piyush Malik", "Associate Software Engineer"),
    ("Pratyush Bhandari", "Senior Software Engineer"),
    ("Qi Wang", "Principal Software Engineer"),
    ("Qian Ding", "Senior Software Engineer"),
    ("Quinton Jones", "Software Engineer"),
    ("Rakesh S", "Associate Software Engineer"),
    ("Ricardo Carrillo Cruz", "Senior Principal Software Engineer"),
    ("Robin Bobbitt", "Senior Principal Software Engineer"),
    ("Rodrigo Toshiaki Horie", "Software Engineer"),
    ("Roger Martinez Palleja", "Senior Software Engineer"),
    ("Rohit Thakur", "Senior Software Engineer"),
    ("Ryan Williams", "Senior Software Engineer"),
    ("Sagar Paul", "Principal Software Engineer"),
    ("Salma Kochay", "Software Engineer"),
    ("Sandeep Shedmake", "Senior Software Engineer"),
    ("Sandra McCann", "Senior Software Engineer"),
    ("Sarah Akus", "Software Engineer"),
    ("Satoe Imaishi", "Principal Software Engineer"),
    ("Seth Foster", "Senior Software Engineer"),
    ("Shaiah Emigh-Doyle", "Software Engineer"),
    ("Shane McDonald", "Senior Principal Software Engineer"),
    ("Sharvari Khedkar", "Senior Software Engineer"),
    ("Shashank Venkat", "Software Engineer"),
    ("Shatakshi Mishra", "Senior Software Engineer"),
    ("Sherin Varughese", "Senior Software Engineer"),
    ("Siddarth Sharma", "Associate Software Engineer"),
    ("Siddharth Rajaraman", "Senior Software Engineer"),
    ("Sloane Hertel", "Senior Principal Software Engineer"),
    ("Song Song Li", "Principal Software Engineer"),
    ("Sorin Sbarnea", "Principal Software Engineer"),
    ("Stevenson Michel", "Software Engineer"),
    ("Sviatoslav Sydorenko", "Senior Software Engineer"),
    ("Takumi Yanagawa", "Software Engineer"),
    ("Tami Takamiya", "Principal Software Engineer"),
    ("Tanwi Geetika", "Software Engineer"),
    ("Thanh Nguyet Vo", "Senior Software Engineer"),
    ("Thomas Tuffin", "Senior Software Engineer"),
    ("Tim Pouyer", "Senior Software Engineer"),
    ("Tomas Znamenacek", "Senior Software Engineer"),
    ("Tomer Shinhar", "Senior Software Engineer"),
    ("Tong He", "Principal Software Engineer"),
    ("Tray Keller", "Software Engineer"),
    ("Truc Duong", "Software Engineer"),
    ("Tsu Phin Hee", "Senior Software Engineer"),
    ("Vidya Nambiar", "Senior Software Engineer"),
    ("Yuval Lahav", "Principal Software Engineer"),
    ("Zack Kayyali", "Senior Software Engineer"),
    ("Zita Pospisil Nemeckova", "Senior Software Engineer"),
    ("sivel .", "Senior Principal Software Engineer"),
]


def _load_org_chart_names() -> list[tuple[str, str]]:
    """Load org chart names from external YAML, falling back to inline list."""
    yaml_path = ORG_DIR / "org_chart.yaml"
    if yaml_path.exists():
        try:
            import yaml

            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or []
            return [(entry["name"], entry.get("title", "")) for entry in data]
        except Exception as e:
            logger.warning("Failed to load org chart YAML: %s, using inline list", e)
    return _INLINE_ORG_CHART_NAMES


ORG_CHART_NAMES = _load_org_chart_names()


def _strip_diacritics(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _normalize_name(name: str) -> str:
    return _strip_diacritics(name).lower().strip()


def classify_title(title: str) -> str | None:
    """Map a job title to an engineering level ID, or None if not an IC engineer."""
    if not title:
        return None
    for pattern in MANAGEMENT_PATTERNS:
        if pattern.search(title):
            return None
    for pattern, level in TITLE_TO_LEVEL:
        if pattern.search(title):
            return level
    return None


def parse_slack_ndjson(path: Path) -> dict[str, dict]:
    """Parse Slack NDJSON export into a lookup keyed by normalized real_name.

    Returns: {normalized_name: {username, email, slack_id, real_name, title, start_date}}
    """
    all_users: list[dict] = []
    with open(path, encoding="utf-8") as f:
        content = f.read()

    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(content):
        while pos < len(content) and content[pos] in " \t\n\r":
            pos += 1
        if pos >= len(content):
            break
        try:
            obj, end_pos = decoder.raw_decode(content, pos)
            if isinstance(obj, dict) and "results" in obj:
                all_users.extend(obj["results"])
            pos = end_pos
        except json.JSONDecodeError:
            pos += 1

    lookup: dict[str, dict] = {}
    for u in all_users:
        if u.get("deleted") or u.get("is_bot"):
            continue
        email = u.get("profile", {}).get("email", "")
        if not email or "@redhat.com" not in email:
            continue

        real_name = u.get("real_name", "").strip()
        if not real_name:
            continue

        email_prefix = email.split("@")[0]
        norm = _normalize_name(real_name)

        lookup[norm] = {
            "username": email_prefix,
            "email": email,
            "slack_id": u.get("id", ""),
            "real_name": real_name,
            "title": u.get("profile", {}).get("title", ""),
            "start_date": u.get("profile", {}).get("start_date", ""),
        }

    return lookup


def cross_reference(
    org_names: list[tuple[str, str]],
    slack_lookup: dict[str, dict],
) -> tuple[list[dict], list[dict]]:
    """Match org chart names to Slack users by name similarity.

    Returns (matched, unmatched) lists.
    """
    matched: list[dict] = []
    unmatched: list[dict] = []

    slack_norm_keys = {k: v for k, v in slack_lookup.items()}

    for full_name, title in org_names:
        level = classify_title(title)
        if level is None:
            continue

        norm = _normalize_name(full_name)
        info = slack_norm_keys.get(norm)

        if not info:
            parts = _normalize_name(full_name).split()
            if len(parts) >= 2:
                first, last = parts[0], parts[-1]
                for sn, si in slack_norm_keys.items():
                    sp = sn.split()
                    if len(sp) >= 2 and sp[0] == first and sp[-1] == last:
                        info = si
                        break

        if info:
            matched.append(
                {
                    "username": info["username"],
                    "name": full_name,
                    "email": info["email"],
                    "slack_id": info["slack_id"],
                    "jira_username": info["username"],
                    "gitlab_username": info["username"],
                    "github_username": info["username"],
                    "git_author": full_name,
                    "level": level,
                    "title": title,
                }
            )
        else:
            unmatched.append(
                {
                    "name": full_name,
                    "title": title,
                    "level": level,
                }
            )

    return matched, unmatched


APP_INTERFACE_DIR = Path.home() / "src" / "app-interface"


def _build_kerberos_name_map() -> dict[str, str]:
    """Build kerberos -> full name lookup from org chart + Slack data."""
    mapping: dict[str, str] = {}
    if not SLACK_FILE.exists():
        return mapping
    try:
        slack = parse_slack_ndjson(SLACK_FILE)
    except Exception as e:
        logger.warning("Parsing Slack NDJSON for kerberos name map: %s", e)
        return mapping

    for full_name, _title in ORG_CHART_NAMES:
        norm = _normalize_name(full_name)
        info = slack.get(norm)
        if not info:
            parts = norm.split()
            if len(parts) >= 2:
                for sn, si in slack.items():
                    sp = sn.split()
                    if len(sp) >= 2 and sp[0] == parts[0] and sp[-1] == parts[-1]:
                        info = si
                        break
        if info:
            mapping[info["username"]] = full_name
    return mapping


def _load_github_orgs() -> list[str]:
    """Load GitHub org list from config.json, falling back to default."""
    try:
        cfg_path = Path(__file__).resolve().parent.parent.parent / "config.json"
        if cfg_path.exists():
            import json as _json

            with open(cfg_path, encoding="utf-8") as f:
                return (
                    _json.load(f).get("performance", {}).get("github_orgs", ["ansible"])
                )
    except Exception as e:
        logger.warning("Failed to load github orgs from config: %s", e)
    return ["ansible"]


GITHUB_ORGS = _load_github_orgs()

_ansible_org_cache: dict[str, dict] | None = None


def _resolve_from_app_interface(kerberos: str) -> str | None:
    """Look up github_username from app-interface user YAML files (local grep)."""
    teams_dir = APP_INTERFACE_DIR / "data" / "teams"
    if not teams_dir.is_dir():
        return None
    try:
        result = subprocess.run(
            ["rg", "-l", f"org_username: {kerberos}", str(teams_dir), "--type", "yaml"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        filepath = result.stdout.strip().split("\n")[0]
        content = Path(filepath).read_text(encoding="utf-8")
        match = re.search(r"github_username:\s*(\S+)", content)
        if match:
            gh = match.group(1)
            if gh and gh != kerberos:
                return gh
    except Exception as e:
        logger.warning("Resolving github_username from app-interface: %s", e)
        pass
    return None


def _load_github_org_members() -> dict[str, dict]:
    """Fetch GitHub org members (login + name) via GraphQL, cached in-process."""
    global _ansible_org_cache
    if _ansible_org_cache is not None:
        return _ansible_org_cache

    profiles: dict[str, dict] = {}
    for org in GITHUB_ORGS:
        members: list[str] = []
        for page in range(1, 10):
            try:
                result = subprocess.run(
                    [
                        "gh",
                        "api",
                        f"/orgs/{org}/members?per_page=100&page={page}",
                        "--jq",
                        ".[].login",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                batch = [
                    line.strip()
                    for line in result.stdout.strip().split("\n")
                    if line.strip()
                ]
                if not batch:
                    break
                members.extend(batch)
                if len(batch) < 100:
                    break
            except Exception as e:
                logger.warning("Fetching GitHub org members via gh api: %s", e)
                break

        for i in range(0, len(members), 50):
            batch = members[i : i + 50]
            fragments = []
            for j, login in enumerate(batch):
                fragments.append(f'  u{j}: user(login: "{login}") {{ login name }}')
            query = "query {\n" + "\n".join(fragments) + "\n}"
            try:
                result = subprocess.run(
                    ["gh", "api", "graphql", "-f", f"query={query}"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    data = json.loads(result.stdout).get("data", {})
                    for user_data in data.values():
                        if user_data and user_data.get("login"):
                            profiles[user_data["login"].lower()] = {
                                "login": user_data["login"],
                                "name": user_data.get("name") or "",
                            }
            except Exception as e:
                logger.warning("Fetching GitHub org member profiles via GraphQL: %s", e)
                pass

        logger.info("GitHub org '%s': fetched %d member profiles", org, len(profiles))

    _ansible_org_cache = profiles
    return profiles


def _resolve_from_github_org(real_name: str) -> str | None:
    """Match a real name against GitHub org member profile names."""
    if not real_name:
        return None
    profiles = _load_github_org_members()
    if not profiles:
        return None

    norm = _strip_diacritics(real_name).lower().strip()
    parts = norm.split()

    for prof in profiles.values():
        pname = prof.get("name", "")
        if not pname:
            continue
        pnorm = _strip_diacritics(pname).lower().strip()
        if pnorm == norm:
            return prof["login"]
        pparts = pnorm.split()
        if len(parts) >= 2 and len(pparts) >= 2:
            if parts[0] == pparts[0] and parts[-1] == pparts[-1]:
                return prof["login"]
    return None


def resolve_github_username(
    kerberos: str,
    email: str,
    real_name: str = "",
) -> str:
    """Resolve actual GitHub username from Kerberos ID and Red Hat email.

    Strategy (ordered by cost):
      1. Grep app-interface user files for github_username (local, ~0.1s)
      2. Match real name against GitHub org member profiles (cached, ~0s)
      3. Check if Kerberos ID is a valid GitHub user (API, ~1s)
      4. Search GitHub commits by @redhat.com email (API, ~5s)
      5. Search ansible org commits by @redhat.com email (API, ~5s)
      6. Fall back to Kerberos ID if nothing works
    """
    ai_result = _resolve_from_app_interface(kerberos)
    if ai_result:
        return ai_result

    org_result = _resolve_from_github_org(real_name)
    if org_result:
        return org_result

    try:
        result = subprocess.run(
            ["gh", "api", f"/users/{kerberos}", "--jq", ".login"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            login = result.stdout.strip()
            if login and "Not Found" not in login:
                return login
    except Exception as e:
        logger.warning("Checking if Kerberos ID is valid GitHub user: %s", e)
        pass

    if email:
        try:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    f"/search/commits?q=author-email:{email}&per_page=1",
                    "--jq",
                    ".items[0].author.login",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                login = result.stdout.strip()
                if login and login != "null":
                    return login
        except Exception as e:
            logger.warning("Searching GitHub commits by author-email: %s", e)
            pass

        for org in GITHUB_ORGS:
            try:
                result = subprocess.run(
                    [
                        "gh",
                        "api",
                        f"/search/commits?q=author-email:{email}+org:{org}&per_page=1",
                        "--jq",
                        ".items[0].author.login",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if result.returncode == 0:
                    login = result.stdout.strip()
                    if login and login != "null":
                        return login
            except Exception as e:
                logger.warning("Searching GitHub commits by author-email in org: %s", e)
                pass

    return kerberos


def resolve_github_usernames(
    peers: dict[str, list[dict]],
    cache_path: Path | None = None,
) -> dict[str, list[dict]]:
    """Resolve GitHub usernames for all peers, using a persistent cache.

    Previously-unresolved entries (where cached value == kerberos) are
    re-checked so that newly available sources (like app-interface) can
    upgrade them.
    """
    cache: dict[str, str] = {}
    if cache_path is None:
        cache_path = ORG_DIR / "github_username_cache.json"
    if cache_path.exists():
        try:
            with open(cache_path, encoding="utf-8") as f:
                cache = json.load(f)
        except Exception as e:
            logger.warning("Loading GitHub username cache: %s", e)
            pass

    kerb_to_name = _build_kerberos_name_map()

    resolved_count = 0
    for _level, peer_list in peers.items():
        for peer in peer_list:
            kerberos = peer["username"]
            cached = cache.get(kerberos)

            if cached and cached != kerberos:
                peer["github_username"] = cached
                resolved_count += 1
                continue

            email = f"{kerberos}@redhat.com"
            real_name = peer.get("git_author") or kerb_to_name.get(kerberos, "")
            gh_user = resolve_github_username(kerberos, email, real_name=real_name)
            cache[kerberos] = gh_user
            peer["github_username"] = gh_user
            if gh_user != kerberos:
                resolved_count += 1
                logger.info("GitHub: %s -> %s", kerberos, gh_user)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)

    logger.info(
        "GitHub username resolution: %d/%d resolved to different handles",
        resolved_count,
        sum(len(pl) for pl in peers.values()),
    )
    return peers


def select_peers(
    matched: list[dict],
    per_level: int = PEERS_PER_LEVEL,
    seed: int = 42,
    exclude_usernames: set[str] | None = None,
) -> dict[str, list[dict]]:
    """Select peers per level from matched engineers.

    When per_level <= 0, all resolved peers are included (no sampling).
    When per_level > 0, randomly sample that many per level.
    """
    exclude = exclude_usernames or set()

    by_level: dict[str, list[dict]] = {}
    for person in matched:
        lvl = person["level"]
        if person["username"] in exclude:
            continue
        by_level.setdefault(lvl, []).append(person)

    rng = random.Random(seed)
    selected: dict[str, list[dict]] = {}
    peer_fields = [
        "username",
        "jira_username",
        "gitlab_username",
        "github_username",
        "git_author",
    ]

    for level in ("ase", "se", "sse", "pse", "spse", "de"):
        pool = by_level.get(level, [])
        if not pool:
            continue
        if per_level <= 0:
            picks = sorted(pool, key=lambda p: p["username"])
        else:
            n = min(per_level, len(pool))
            picks = rng.sample(pool, n)
        selected[level] = [{k: p[k] for k in peer_fields} for p in picks]

    return selected


def build_roster(
    slack_path: Path = SLACK_FILE,
    seed: int = 42,
    per_level: int = PEERS_PER_LEVEL,
    exclude_usernames: set[str] | None = None,
    resolve_github: bool = True,
) -> dict:
    """Build the full org roster from Slack NDJSON and embedded org chart data."""
    slack_lookup = parse_slack_ndjson(slack_path)
    matched, unmatched = cross_reference(ORG_CHART_NAMES, slack_lookup)

    by_level_counts: dict[str, int] = {}
    for p in matched:
        by_level_counts[p["level"]] = by_level_counts.get(p["level"], 0) + 1

    peers = select_peers(
        matched, per_level=per_level, seed=seed, exclude_usernames=exclude_usernames
    )

    if resolve_github:
        peers = resolve_github_usernames(peers)

    total_selected = sum(len(pl) for pl in peers.values())
    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "seed": seed,
        "stats": {
            "total_org_chart": len(ORG_CHART_NAMES),
            "total_resolved": len(matched),
            "total_unresolved": len(unmatched),
            "by_level": by_level_counts,
            "selected_per_level": 0 if per_level <= 0 else per_level,
            "total_selected": total_selected,
        },
        "peers": peers,
        "unresolved": unmatched,
    }


def generate_roster(
    output_path: Path = ROSTER_FILE,
    slack_path: Path = SLACK_FILE,
    seed: int = 42,
    per_level: int = PEERS_PER_LEVEL,
    resolve_github: bool = True,
) -> dict:
    """Generate and write org_roster.json."""
    roster = build_roster(
        slack_path=slack_path,
        seed=seed,
        per_level=per_level,
        resolve_github=resolve_github,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(roster, f, indent=2, ensure_ascii=False)

    return roster


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate org roster from Slack + Workday data"
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for peer selection"
    )
    parser.add_argument(
        "--per-level",
        type=int,
        default=PEERS_PER_LEVEL,
        help="Peers per level (0 = all)",
    )
    parser.add_argument(
        "--slack", type=str, default=str(SLACK_FILE), help="Path to Slack NDJSON"
    )
    parser.add_argument(
        "--output", type=str, default=str(ROSTER_FILE), help="Output path"
    )
    parser.add_argument(
        "--no-github", action="store_true", help="Skip GitHub username resolution"
    )
    args = parser.parse_args()

    roster = generate_roster(
        output_path=Path(args.output),
        slack_path=Path(args.slack),
        seed=args.seed,
        per_level=args.per_level,
        resolve_github=not args.no_github,
    )

    stats = roster["stats"]
    print(
        f"Org roster generated: {stats['total_resolved']}/{stats['total_org_chart']} resolved"
    )
    print(f"Unresolved: {stats['total_unresolved']}")
    print(f"By level: {stats['by_level']}")
    print("Selected peers:")
    for level, peers in roster["peers"].items():
        names = [p["username"] for p in peers]
        print(f"  {level}: {len(peers)} -- {', '.join(names)}")
    print(f"Written to: {args.output}")
