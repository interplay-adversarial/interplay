"""Request identity for target traffic: explicit, recorded, never an authorization input.

Every request Interplay sends to an evaluated *target* carries a ``User-Agent``. The
default is the honest, stable ``Interplay-Assessment/1.0`` so a defender can write one
rule for it. An operator may opt in to a browser-like identity from a small versioned
pool, for example to test whether a detection depends on the client label instead of on
behavior. Either way the identity that was actually sent is returned as a record for the
campaign provenance.

Boundaries that do not change:

* The identity is a label. It is never used to decide whether a target may be tested;
  a target that allows or blocks traffic by this label has not authorized anything.
* Only ``User-Agent`` and a fixed, per-entry set of companion headers can be added.
  Protocol headers (``Authorization``, ``Content-Type``, ``Accept-Encoding``, ``Host``,
  cookies) are never configurable here, and the callers apply theirs last.
* The pool holds generic browser families only. It never impersonates a crawler, a
  vendor agent or any named service.
* Selection is deterministic: the same profile always resolves to the same entry, so a
  replayed campaign reproduces its identity.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_USER_AGENT = "Interplay-Assessment/1.0"
DEFAULT_PROFILE_ID = "interplay-default"
BROWSER_POOL_V1 = "browser-ua-pool/1"

# Header names an identity must never set; callers add their own protocol headers last.
RESERVED_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "content-type",
        "content-length",
        "accept-encoding",
        "host",
        "cookie",
        "connection",
        "transfer-encoding",
    }
)

_PROFILE_ID = r"^[a-z0-9][a-z0-9._-]{0,63}$"
_PRINTABLE = re.compile(r"^[\x21-\x7e](?:[\x20-\x7e]*[\x21-\x7e])?$")


class _Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, revalidate_instances="always"
    )


@dataclass(frozen=True)
class BrowserEntry:
    id: str
    family: str
    user_agent: str
    headers: tuple[tuple[str, str], ...]


def _chromium(family, platform, os_token, brand, major="138", edge=False):
    suffix = f" Edg/{major}.0.0.0" if edge else ""
    return BrowserEntry(
        id=f"{family}-{platform}",
        family=family,
        user_agent=(
            f"Mozilla/5.0 ({os_token}) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{major}.0.0.0 Safari/537.36{suffix}"
        ),
        headers=(
            ("Accept-Language", "en-US,en;q=0.9"),
            (
                "sec-ch-ua",
                f'"Not)A;Brand";v="8", "Chromium";v="{major}", "{brand}";v="{major}"',
            ),
            ("sec-ch-ua-mobile", "?0"),
            (
                "sec-ch-ua-platform",
                {"windows": '"Windows"', "macos": '"macOS"'}.get(platform, '"Linux"'),
            ),
        ),
    )


# A frozen snapshot, not a claim to track current browser releases. Refresh by publishing
# a new pool name (``browser-ua-pool/2``); never edit ``/1`` in place, because a campaign
# record names the pool and entry it used.
_POOL_V1: tuple[BrowserEntry, ...] = (
    _chromium("chrome", "windows", "Windows NT 10.0; Win64; x64", "Google Chrome"),
    _chromium("chrome", "macos", "Macintosh; Intel Mac OS X 10_15_7", "Google Chrome"),
    _chromium("chrome", "linux", "X11; Linux x86_64", "Google Chrome"),
    _chromium("edge", "windows", "Windows NT 10.0; Win64; x64", "Microsoft Edge", edge=True),
    BrowserEntry(
        "firefox-windows",
        "firefox",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
        (("Accept-Language", "en-US,en;q=0.5"),),
    ),
    BrowserEntry(
        "firefox-linux",
        "firefox",
        "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
        (("Accept-Language", "en-US,en;q=0.5"),),
    ),
    BrowserEntry(
        "safari-macos",
        "safari",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.5 Safari/605.1.15",
        (("Accept-Language", "en-US,en;q=0.9"),),
    ),
)

POOLS: dict[str, tuple[BrowserEntry, ...]] = {BROWSER_POOL_V1: _POOL_V1}


_Version = Annotated[int, Field(ge=1, le=10000, strict=True)]


class DeclaredIdentity(_Strict):
    """A fixed, self-identifying ``User-Agent``. This is the default."""

    mode: Literal["declared"] = "declared"
    id: Annotated[str, Field(pattern=_PROFILE_ID)] = DEFAULT_PROFILE_ID
    version: _Version = 1
    user_agent: Annotated[str, Field(min_length=1, max_length=200)] = DEFAULT_USER_AGENT

    @field_validator("user_agent")
    @classmethod
    def header_safe(cls, value):
        if not _PRINTABLE.fullmatch(value):
            raise ValueError("identity-user-agent-invalid")
        return value


class BrowserPoolIdentity(_Strict):
    """A browser-like identity chosen deterministically from a versioned pool.

    Pin one pool entry with ``entry``, or give a ``seed`` to select one reproducibly.
    With neither, the profile ``id`` is the seed.
    """

    mode: Literal["browser-pool"]
    id: Annotated[str, Field(pattern=_PROFILE_ID)]
    version: _Version = 1
    pool: Literal["browser-ua-pool/1"] = BROWSER_POOL_V1
    entry: Annotated[str, Field(pattern=_PROFILE_ID)] | None = None
    seed: Annotated[str, Field(min_length=1, max_length=128)] | None = None

    @model_validator(mode="after")
    def choice_valid(self):
        if self.entry is not None and self.seed is not None:
            raise ValueError("identity-entry-and-seed-exclusive")
        if self.seed is not None and not _PRINTABLE.fullmatch(self.seed):
            raise ValueError("identity-seed-invalid")
        if self.entry is not None and self.entry not in {e.id for e in POOLS[self.pool]}:
            raise ValueError("identity-pool-entry-unknown")
        return self


IdentityProfile = Annotated[DeclaredIdentity | BrowserPoolIdentity, Field(discriminator="mode")]


@dataclass(frozen=True)
class ResolvedIdentity:
    """The headers to add to a target request and the record of what they were."""

    headers: dict[str, str]
    record: dict

    @property
    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(_canonical(self.record)).hexdigest()


def _canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()


def _select(profile: BrowserPoolIdentity) -> BrowserEntry:
    pool = POOLS[profile.pool]
    if profile.entry is not None:
        return next(e for e in pool if e.id == profile.entry)
    seed = f"{profile.pool}\0{profile.seed if profile.seed is not None else profile.id}"
    index = int.from_bytes(hashlib.sha256(seed.encode()).digest()[:8], "big")
    return pool[index % len(pool)]


def resolve_identity(
    profile: DeclaredIdentity | BrowserPoolIdentity | None = None,
) -> ResolvedIdentity:
    """Resolve a profile (``None`` means the default) to headers and a provenance record."""
    if profile is None:
        profile = DeclaredIdentity()
    if isinstance(profile, DeclaredIdentity):
        headers = {"User-Agent": profile.user_agent}
        pool = entry = None
    else:
        chosen = _select(profile)
        headers = {"User-Agent": chosen.user_agent, **dict(chosen.headers)}
        pool, entry = profile.pool, chosen.id
    if RESERVED_HEADERS & {name.lower() for name in headers}:
        raise ValueError("identity-reserved-header")
    record = {
        "profile": profile.id,
        "version": profile.version,
        "mode": profile.mode,
        "pool": pool,
        "entry": entry,
        "headers": headers,
    }
    return ResolvedIdentity(headers=dict(headers), record=record)
