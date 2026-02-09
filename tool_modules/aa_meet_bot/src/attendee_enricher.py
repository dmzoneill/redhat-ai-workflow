"""
Attendee Enricher - Fetch additional data for meeting attendees.

Data sources:
1. app-interface YAML files - GitHub username, team, role, Slack ID
2. Slack API - Profile photos, display names
3. (Future) GitHub API - Avatars, repos

Photo caching: ~/.cache/aa-workflow/photos/
"""

import asyncio
import hashlib
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import yaml

if TYPE_CHECKING:
    from .attendee_service import EnrichedAttendee

logger = logging.getLogger(__name__)

# Photo cache directory
PHOTO_CACHE_DIR = Path.home() / ".cache" / "aa-workflow" / "photos"


def _get_app_interface_path() -> Optional[Path]:
    """Get app-interface path from config.json."""
    try:
        from server.utils import load_config

        config = load_config()
        path_str = config.get("repositories", {}).get("app-interface", {}).get("path")
        if path_str:
            path = Path(path_str).expanduser()
            if path.exists():
                return path
            logger.warning(f"app-interface path does not exist: {path}")
    except Exception as e:
        logger.debug(f"Failed to get app-interface path: {e}")
    return None


class AppInterfaceScanner:
    """
    Scans and indexes app-interface team YAML files.

    Provides fast lookups by email or name.
    """

    def __init__(self, app_interface_path: Optional[Path] = None):
        self._path = app_interface_path or _get_app_interface_path()
        self._index_by_email: dict[str, dict] = {}
        self._index_by_name: dict[str, dict] = {}
        self._index_by_github: dict[str, dict] = {}
        self._scanned = False

    def scan(self) -> int:
        """
        Scan app-interface for user data.

        Returns:
            Number of users indexed.
        """
        if not self._path:
            logger.warning("No app-interface path configured")
            return 0

        teams_dir = self._path / "data" / "services" / "teams"
        if not teams_dir.exists():
            # Try alternative paths
            alt_paths = [
                self._path / "data" / "teams",
                self._path / "teams",
            ]
            for alt in alt_paths:
                if alt.exists():
                    teams_dir = alt
                    break
            else:
                logger.warning(f"Teams directory not found in {self._path}")
                return 0

        count = 0

        # Scan all YAML files in teams directory
        for yaml_file in teams_dir.rglob("*.yaml"):
            try:
                count += self._scan_file(yaml_file)
            except Exception as e:
                logger.debug(f"Error scanning {yaml_file}: {e}")

        # Also scan users directory if it exists
        users_dir = self._path / "data" / "users"
        if users_dir.exists():
            for yaml_file in users_dir.rglob("*.yaml"):
                try:
                    count += self._scan_file(yaml_file)
                except Exception as e:
                    logger.debug(f"Error scanning {yaml_file}: {e}")

        self._scanned = True
        logger.info(f"Indexed {count} users from app-interface")
        return count

    def _scan_file(self, yaml_file: Path) -> int:
        """Scan a single YAML file for user data."""
        count = 0

        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
        except Exception as e:
            logger.debug(f"Failed to parse {yaml_file}: {e}")
            return 0

        if not data:
            return 0

        # Handle different YAML structures
        users = []

        if isinstance(data, list):
            users = data
        elif isinstance(data, dict):
            # Check for common keys
            if "users" in data:
                users = data["users"]
            elif "members" in data:
                users = data["members"]
            elif "team" in data and isinstance(data["team"], dict):
                if "members" in data["team"]:
                    users = data["team"]["members"]
            # Single user file
            elif "name" in data or "email" in data:
                users = [data]

        for user in users:
            if not isinstance(user, dict):
                continue

            # Extract user info
            user_data = {
                "name": user.get("name")
                or user.get("displayName")
                or user.get("full_name"),
                "email": user.get("email") or user.get("redhat_email"),
                "github_username": user.get("github_username") or user.get("github"),
                "slack_id": user.get("slack_id") or user.get("slack"),
                "team": user.get("team") or user.get("org_unit"),
                "role": user.get("role") or user.get("title"),
            }

            # Clean up None values
            user_data = {k: v for k, v in user_data.items() if v}

            if not user_data.get("name") and not user_data.get("email"):
                continue

            # Index by email
            if user_data.get("email"):
                email_lower = user_data["email"].lower()
                self._index_by_email[email_lower] = user_data

            # Index by name (normalized)
            if user_data.get("name"):
                name_key = self._normalize_name(user_data["name"])
                self._index_by_name[name_key] = user_data

            # Index by GitHub username
            if user_data.get("github_username"):
                gh_lower = user_data["github_username"].lower()
                self._index_by_github[gh_lower] = user_data

            count += 1

        return count

    def _normalize_name(self, name: str) -> str:
        """Normalize a name for matching."""
        # Lowercase, remove extra whitespace, remove common suffixes
        name = name.lower().strip()
        name = re.sub(r"\s+", " ", name)
        # Remove common suffixes like "(Red Hat)" or "[contractor]"
        name = re.sub(r"\s*[\(\[].*?[\)\]]", "", name)
        return name

    def lookup_by_email(self, email: str) -> Optional[dict]:
        """Find user by email address."""
        if not self._scanned:
            self.scan()
        return self._index_by_email.get(email.lower())

    def lookup_by_name(self, name: str, threshold: float = 0.8) -> Optional[dict]:
        """
        Find user by name with fuzzy matching.

        Args:
            name: Name to search for
            threshold: Minimum similarity ratio (0-1)

        Returns:
            User data dict or None
        """
        if not self._scanned:
            self.scan()

        name_key = self._normalize_name(name)

        # Exact match first
        if name_key in self._index_by_name:
            return self._index_by_name[name_key]

        # Fuzzy match
        best_match = None
        best_ratio = 0.0

        for indexed_name, user_data in self._index_by_name.items():
            ratio = SequenceMatcher(None, name_key, indexed_name).ratio()
            if ratio > best_ratio and ratio >= threshold:
                best_ratio = ratio
                best_match = user_data

        return best_match

    def lookup_by_github(self, github_username: str) -> Optional[dict]:
        """Find user by GitHub username."""
        if not self._scanned:
            self.scan()
        return self._index_by_github.get(github_username.lower())


class SlackPhotoFetcher:
    """
    Fetches and caches Slack profile photos.

    Photos are cached to ~/.cache/aa-workflow/photos/
    """

    def __init__(self):
        self._cache_dir = PHOTO_CACHE_DIR
        self._slack_client = None

    async def initialize(self) -> bool:
        """Initialize Slack client."""
        try:
            # Try to import and use existing Slack client
            from tool_modules.aa_slack.src.slack_client import get_slack_client

            self._slack_client = await get_slack_client()

            # Ensure cache directory exists
            self._cache_dir.mkdir(parents=True, exist_ok=True)

            return True
        except ImportError:
            logger.debug("Slack client not available")
            return False
        except Exception as e:
            logger.debug(f"Failed to initialize Slack client: {e}")
            return False

    async def fetch_photo(self, slack_id: str, size: int = 192) -> Optional[Path]:
        """
        Fetch and cache a user's Slack profile photo.

        Args:
            slack_id: Slack user ID (e.g., "U12345678")
            size: Desired image size (will use closest available)

        Returns:
            Path to cached photo, or None if unavailable.
        """
        if not slack_id:
            return None

        # Check cache first
        cache_path = self._cache_dir / f"{slack_id}.jpg"
        if cache_path.exists():
            return cache_path

        if not self._slack_client:
            return None

        try:
            # Get user info from Slack
            response = await self._slack_client.users_info(user=slack_id)

            if not response.get("ok"):
                logger.debug(f"Slack API error for {slack_id}: {response.get('error')}")
                return None

            user = response.get("user", {})
            profile = user.get("profile", {})

            # Get the best available image URL
            # Slack provides: image_24, image_32, image_48, image_72, image_192, image_512
            image_url = None
            for img_size in [192, 512, 72, 48]:
                url = profile.get(f"image_{img_size}")
                if url and not url.endswith("default"):
                    image_url = url
                    break

            if not image_url:
                logger.debug(f"No profile image for {slack_id}")
                return None

            # Download the image
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    if resp.status == 200:
                        image_data = await resp.read()

                        # Save to cache
                        cache_path.write_bytes(image_data)
                        logger.debug(f"Cached photo for {slack_id}: {cache_path}")
                        return cache_path
                    else:
                        logger.debug(f"Failed to download photo: {resp.status}")
                        return None

        except Exception as e:
            logger.debug(f"Failed to fetch Slack photo for {slack_id}: {e}")
            return None

    async def fetch_photo_by_email(self, email: str) -> Optional[Path]:
        """
        Fetch profile photo by email address.

        Args:
            email: User's email address

        Returns:
            Path to cached photo, or None if unavailable.
        """
        if not email or not self._slack_client:
            return None

        # Check cache by email hash
        email_hash = hashlib.md5(email.lower().encode()).hexdigest()[:12]
        cache_path = self._cache_dir / f"email_{email_hash}.jpg"
        if cache_path.exists():
            return cache_path

        try:
            # Look up user by email
            response = await self._slack_client.users_lookupByEmail(email=email)

            if not response.get("ok"):
                return None

            user = response.get("user", {})
            slack_id = user.get("id")

            if slack_id:
                # Fetch by ID (will use ID-based cache)
                photo_path = await self.fetch_photo(slack_id)

                # Also create email-based symlink for faster future lookups
                if photo_path and photo_path.exists():
                    try:
                        cache_path.symlink_to(photo_path)
                    except Exception:
                        pass

                return photo_path

        except Exception as e:
            logger.debug(f"Failed to lookup Slack user by email {email}: {e}")

        return None


class AttendeeEnricher:
    """
    Enriches attendee data from multiple sources.
    """

    def __init__(self):
        self._app_interface = AppInterfaceScanner()
        self._slack_photos = SlackPhotoFetcher()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize data sources."""
        # Scan app-interface in background
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._app_interface.scan)

        # Initialize Slack client
        await self._slack_photos.initialize()

        self._initialized = True

    async def enrich(self, attendee: "EnrichedAttendee") -> "EnrichedAttendee":
        """
        Enrich an attendee with data from all sources.

        Args:
            attendee: EnrichedAttendee to enrich

        Returns:
            The same attendee object with additional data filled in.
        """

        # Try to find in app-interface
        user_data = None

        if attendee.email:
            user_data = self._app_interface.lookup_by_email(attendee.email)

        if not user_data and attendee.name:
            user_data = self._app_interface.lookup_by_name(attendee.name)

        if user_data:
            # Fill in missing fields
            if not attendee.email and user_data.get("email"):
                attendee.email = user_data["email"]
            if not attendee.github_username:
                attendee.github_username = user_data.get("github_username")
            if not attendee.slack_id:
                attendee.slack_id = user_data.get("slack_id")
            if not attendee.team:
                attendee.team = user_data.get("team")
            if not attendee.role:
                attendee.role = user_data.get("role")
            if user_data.get("name"):
                attendee.display_name = user_data["name"]

        # Fetch Slack photo
        photo_path = None

        if attendee.slack_id:
            photo_path = await self._slack_photos.fetch_photo(attendee.slack_id)
        elif attendee.email:
            photo_path = await self._slack_photos.fetch_photo_by_email(attendee.email)

        if photo_path:
            attendee.photo_path = str(photo_path)

        return attendee

    def lookup_user(self, name: str = None, email: str = None) -> Optional[dict]:
        """
        Look up a user in app-interface.

        Args:
            name: User's display name
            email: User's email address

        Returns:
            User data dict or None
        """
        if email:
            result = self._app_interface.lookup_by_email(email)
            if result:
                return result

        if name:
            return self._app_interface.lookup_by_name(name)

        return None
