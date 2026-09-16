"""Fetch real job adverts from sources that publish them for the purpose.

Ethics first, because this module is the only part of the project that touches
somebody else's server.

**Nothing here scrapes HTML.** Every source is either a documented public API
or an RSS feed - formats whose entire purpose is machine consumption. Parsing a
job board's markup would be a different act: it evades the interface the site
chose to offer, breaks the moment they restyle a div, and on most large boards
it violates the terms of service. The line taken is that a feed is an
invitation and a web page is not.

Four obligations are enforced in code rather than left to the caller:

* **robots.txt is honoured** before any fetch, via the standard library
  parser, with the result cached per host. The sole exception is an API host
  we hold an issued key for; see ``CREDENTIALLED_API_HOSTS`` for why that is
  not the loophole it first looks like.
* **One request per host per second**, and fetched sources are cached for six
  hours. Remotive's API response asks in plain words that callers poll "max. 4
  times a day"; a six-hour cache is the machine-readable version of agreeing.
* **Attribution is preserved.** Every job carries its ``source`` and its
  original ``url``, and Remotive's terms require both. A job whose provenance
  has been stripped is not usable, so the fields are mandatory.
* **We identify ourselves** with a contact URL in the User-Agent, so an
  operator who objects to the traffic can say so.

Two sources named in the brief are absent, and one is refused:

* **GitHub Jobs** was retired in 2021 - the host does not resolve. The method
  is kept so callers do not break, but it returns nothing and says why.
* **Dev.to** discontinued its job board; ``dev.to/feed`` is articles.
* **LinkedIn** is refused. There is no public jobs feed, and their user
  agreement prohibits automated collection. "The endpoint exists" is not
  consent.

Security. This module makes outbound requests to URLs that could, if the
caller were careless, come from a user. That is a server-side request forgery
primitive, so: hosts are checked against an allow-list, DNS results are
rejected if they resolve to private, loopback or link-local space (which is
what stops ``169.254.169.254`` reading cloud credentials), redirects are not
followed blindly, responses are size-capped, and XML is refused outright if it
declares a DTD - stdlib ElementTree expands entities, and a 400-byte file can
become gigabytes.
"""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import re
import socket
import threading
import time
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from config import settings
from utils.error_handling import JobScrapingError
from utils.logger import get_logger, observed
from utils.retry_handler import retry_with_backoff
from utils.validation import as_int, as_list

logger = get_logger(__name__)

__all__ = [
    "JobScraper",
    "job_scraper",
    "ScraperError",
    "UnsafeURLError",
    "ALLOWED_HOSTS",
    "DEFAULT_RSS_FEEDS",
    "SOURCE_TERMS",
    "INDIA_BOARDS",
    "CLOSED_JOB_BOARDS",
]


class ScraperError(JobScrapingError):
    """A source could not be read. Never fatal - the caller drops that source."""


class UnsafeURLError(ScraperError):
    """A URL was refused before any connection was attempted."""


class _TransientHTTPError(ScraperError):
    """A 429 or 5xx: the server said "not now", so the fetch is retried.

    Private because it never escapes :class:`HttpFetcher` - by the time the
    retries are exhausted the caller sees it as the ``ScraperError`` it is.
    """


# --- Sources ---------------------------------------------------------------

#: The only hosts this module will connect to.
#:
#: An allow-list rather than a block-list, because the failure modes are not
#: symmetric: forgetting to block a host is a security bug, whereas forgetting
#: to allow one is an obvious missing feature that shows up immediately.
ALLOWED_HOSTS: Set[str] = {
    "hn.algolia.com",
    "hacker-news.firebaseio.com",
    "weworkremotely.com",
    "remotive.com",
    "arbeitnow.com",
    # The apex host answers 301 to www. Content fetches deliberately do not
    # follow redirects, so the canonical host has to be named here.
    "www.arbeitnow.com",
    # Applicant tracking systems. These publish a company's own vacancies as
    # JSON for the company's own careers page to render, which is why no key
    # is needed and why reading them is not scraping.
    "boards-api.greenhouse.io",
    "api.lever.co",
    "api.ashbyhq.com",
    # Licensed aggregator. Adzuna sells access to listings it has the right
    # to redistribute, which is why a key exists to be issued at all.
    "api.adzuna.com",
}

#: Feeds fetched when the caller does not name any. All verified live.
DEFAULT_RSS_FEEDS: Tuple[str, ...] = (
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
)

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"
HN_SEARCH_BY_DATE_URL = "https://hn.algolia.com/api/v1/search_by_date"
HN_ITEM_URL = "https://news.ycombinator.com/item?id={id}"
REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"

#: ``content=true`` is not decoration. Without it Greenhouse returns the list
#: of vacancies with the description field absent, and an advert with no text
#: cannot be scored against a resume or turned into interview questions -- the
#: two things this application exists to do. Ashby and Lever send the body
#: unasked; Greenhouse has to be told.
GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
LEVER_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"

#: ``in`` is India. Adzuna keys its country endpoints by ISO code, and the
#: India endpoint returns Indian vacancies only -- the location filter is the
#: URL, not a parameter that can be forgotten.
ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/in/search/1"

#: Companies hiring in India, and the applicant tracking system each publishes
#: through. ``(company, ats, slug)``.
#:
#: This is a curated list rather than a search, because there is no open search
#: API that covers the Indian market. LinkedIn, Indeed, Naukri and Foundit were
#: all considered and none can be used: Indeed retired its public jobs API,
#: LinkedIn publishes none and forbids automated collection, and Naukri and
#: Foundit both prohibit it in their terms. Reading a company's own ATS feed
#: has none of those problems -- it is the same JSON that company's careers
#: page fetches to render itself.
#:
#: Every entry below was verified live before being added, and the India counts
#: at the time were: paytm 173, highradius 59, meesho 46, sigmoid 28, zenoti 22,
#: netradyne 17, druva 15, cred 13, epifi 11, observeai 9, airbnb 8, groww 7,
#: atlan 6, postman 4, clarisights 2.
#: A board that goes away returns nothing and costs only itself; see
#: :meth:`JobScraper.fetch_jobs_india_boards`.
#:
#: Two boards that pass every other test are deliberately absent, because the
#: cost of reading them is paid on every search and the return does not justify
#: it: Zscaler publishes 372 vacancies in a 4.7 MB response and exactly *one*
#: of them is in India, and Airbnb's 2.3 MB is near the limit for its eight.
#: Airbnb is kept and Zscaler is not. If a board's India count ever falls to
#: nothing, drop it rather than leaving the request in.
INDIA_BOARDS: Tuple[Tuple[str, str, str], ...] = (
    ("Paytm", "lever", "paytm"),
    ("Meesho", "lever", "meesho"),
    ("CRED", "lever", "cred"),
    ("Epifi", "lever", "epifi"),
    ("Sigmoid", "greenhouse", "sigmoid"),
    ("Zenoti", "greenhouse", "zenoti"),
    ("Netradyne", "greenhouse", "netradyne"),
    ("Druva", "greenhouse", "druva"),
    ("Observe.AI", "greenhouse", "observeai"),
    ("Groww", "greenhouse", "groww"),
    ("Postman", "greenhouse", "postman"),
    ("HighRadius", "greenhouse", "highradius"),
    ("Airbnb", "greenhouse", "airbnb"),
    ("Atlan", "ashby", "atlan"),
    ("Sarvam AI", "ashby", "sarvam"),
    ("SpotDraft", "ashby", "spotdraft"),
    ("Clarisights", "ashby", "clarisights"),
)

#: Conditions each source attaches to its data, recorded so the obligation
#: travels with the code rather than living in someone's memory.
SOURCE_TERMS: Dict[str, str] = {
    "HackerNews": (
        "Public API provided by Algolia for the Hacker News archive. Comments "
        "are user-submitted; attribution is to the posting author."
    ),
    "Remotive": (
        "Free API. Their terms require linking back to the Remotive URL and "
        "naming Remotive as the source, and ask that callers fetch no more "
        "than about four times a day. Both are enforced here."
    ),
    "WeWorkRemotely": (
        "Public RSS feed published for syndication. Link back to the original "
        "posting."
    ),
    "Arbeitnow": (
        "Free public job-board API, published for third-party use, no key "
        "required."
    ),
    "IndiaBoards": (
        "Each company's own applicant tracking system feed (Greenhouse, Lever "
        "or Ashby), public and keyless because the company's careers page is "
        "itself a client of it. Adverts are attributed to the employer and "
        "link to the employer's own posting, which is where an application "
        "should be made. Requests are throttled per host like every other "
        "source."
    ),
}

#: Hosts whose robots.txt disallows everything because they are API endpoints
#: rather than websites, reached only with a credential their publisher issued
#: for that exact endpoint.
#:
#: This is a deliberate exemption and it deserves the scrutiny. robots.txt
#: governs *crawling* -- a program discovering content by following links --
#: and RFC 9309 is written throughout in those terms. An API host publishes
#: ``Disallow: /`` to keep search engines from indexing JSON responses, which
#: is why ``api.github.com`` says exactly the same thing. Obeying it against a
#: request we were given a key to make would mean refusing an invitation on
#: the grounds that the door has a "no hawkers" sign.
#:
#: The exemption is kept to a hardcoded set, one host at a time, each named
#: with the credential that justifies it. It is not a switch, and there is no
#: setting that widens it, because "ignore robots.txt when convenient" is
#: precisely the behaviour the rest of this module exists to avoid.
CREDENTIALLED_API_HOSTS: Dict[str, str] = {
    "api.adzuna.com": (
        "Called only with an application ID and key that Adzuna issues at "
        "developer.adzuna.com for this endpoint. Without them the source does "
        "not fire at all, so no unauthenticated request is ever made here."
    ),
}

#: The job boards that cannot be used, and why -- recorded here so the question
#: is answered in the code rather than re-litigated every time someone asks.
#:
#: This is not a technical limitation that a better parser would solve. Three
#: of the four forbid automated collection outright, and the fourth withdrew
#: the API that used to permit it.
CLOSED_JOB_BOARDS: Dict[str, str] = {
    "LinkedIn": (
        "No public jobs API, and section 8.2 of the User Agreement prohibits "
        "automated collection. Not usable at any level of effort."
    ),
    "Indeed": (
        "The Publisher Jobs API was withdrawn to existing partners only; new "
        "keys are not issued, and their robots.txt disallows /jobs."
    ),
    "Naukri": (
        "No public API. Their terms of use prohibit automated extraction."
    ),
    "Foundit": (
        "Formerly Monster India. No public API, and the same prohibition on "
        "automated extraction."
    ),
    "Wellfound": (
        "Formerly AngelList Talent. No public jobs API, and their terms "
        "prohibit automated access to listings."
    ),
    "SmartRecruiters": (
        "Keyless and well-formed, and refused anyway. Their robots.txt "
        "allows /v1/companies/ to LinkedInBot by name and answers every "
        "other agent with Disallow: /. One named crawler admitted and the "
        "rest turned away is a decision, not an oversight, and we hold no "
        "credential that would make this the issued-key case in "
        "CREDENTIALLED_API_HOSTS. Cost of obeying it: Swiggy alone, 73 "
        "vacancies in India with 30 posted inside a week."
    ),
}


#: GitHub retired their jobs API on 2021-08-19 and the host no longer resolves.
GITHUB_JOBS_RETIRED = (
    "GitHub Jobs was retired on 2021-08-19 and the API host no longer "
    "resolves. Use fetch_jobs_remotive() or fetch_jobs_arbeitnow() instead."
)

#: Roughly how much text is worth keeping from one advert.
MAX_DESCRIPTION_CHARS = 8000


# --- URL safety ------------------------------------------------------------
#: The well-known prefix a DNS64/NAT64 network uses to express an IPv4 address
#: as IPv6 (RFC 6052). macOS on such a network - and CI runners on IPv6-only
#: networks - hand these back from ``getaddrinfo``.
_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")


def _unwrap_nat64(address):
    """Return the IPv4 address embedded in a NAT64 address, or the input.

    Without this the safety check has a false positive that breaks the
    scraper outright: ``ipaddress`` does not consider ``64:ff9b::/96``
    globally routable, so on a DNS64 network every allowed host resolves to
    what looks like a reserved address and every fetch is refused. Observed
    on the development machine, where ``hn.algolia.com`` resolved to
    ``64:ff9b::22a0:a8b5``.

    Unwrapping is also the safer reading, not merely the convenient one: the
    embedded 32 bits are the real destination, so checking them is what
    actually decides whether the request leaves for a public address. A NAT64
    address wrapping ``127.0.0.1`` still fails, as it should.
    """
    if address.version == 6 and address in _NAT64_PREFIX:
        return ipaddress.ip_address(int(address) & 0xFFFFFFFF)
    return address

def _is_public_address(host: str) -> bool:
    """Does this hostname resolve only to routable, public addresses?

    Every address the name resolves to must be public. Checking only the first
    would leave a hostname that returns both a public and a private record
    able to slip past, and DNS ordering is not ours to control.

    This is the control that stops a URL like
    ``http://169.254.169.254/latest/meta-data/iam/security-credentials/`` -
    the cloud metadata service - being fetched on behalf of a caller.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return False

    seen = False
    for info in infos:
        address = info[4][0]
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return False
        parsed = _unwrap_nat64(parsed)
        if (
            parsed.is_private
            or parsed.is_loopback
            or parsed.is_link_local
            or parsed.is_reserved
            or parsed.is_multicast
            or parsed.is_unspecified
        ):
            logger.warning("Refusing %s: resolves to non-public %s", host, address)
            return False
        seen = True
    return seen


def _validate_url(url: str, allowed_hosts: Optional[Set[str]] = None,
                  validate_dns: bool = True) -> str:
    """Refuse anything we are not certain is safe to fetch.

    Raises rather than returning a flag: a URL that fails any of these checks
    is a bug or an attack, and neither should proceed quietly.

    ``validate_dns`` can be set to ``False`` by test helpers that inject a
    stub fetcher; the DNS lookup is unnecessary there and fails in sandboxed
    CI environments.
    """
    allowed = ALLOWED_HOSTS if allowed_hosts is None else allowed_hosts

    if not isinstance(url, str) or not url.strip():
        raise UnsafeURLError("empty URL")

    parsed = urlparse(url.strip())
    if parsed.scheme != "https":
        # Plain HTTP would let anyone on the path read or rewrite the response.
        raise UnsafeURLError("only https is allowed, got %r" % (parsed.scheme or "",))

    host = (parsed.hostname or "").lower()
    if not host:
        raise UnsafeURLError("no host in URL")
    if host not in allowed:
        raise UnsafeURLError("host %r is not in the allow-list" % host)
    if parsed.port is not None and parsed.port != 443:
        raise UnsafeURLError("non-standard port %s" % parsed.port)
    if validate_dns and not _is_public_address(host):
        raise UnsafeURLError("host %r does not resolve to a public address" % host)

    return url.strip()


# --- Text handling ---------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\x0b\f\r]+")
_BLANKS_RE = re.compile(r"\n{3,}")

#: Sentinel: the host answered, but published no restrictions.
#: Distinct from ``None``, which means we could not read the file at all and
#: therefore must not fetch. Conflating the two is what makes a scraper
#: either impolite or useless, depending on which way you conflate them.
_ROBOTS_ABSENT = object()


def _strip_html(raw: Any) -> str:
    """Turn feed HTML into plain text.

    Job feeds put markup in their description fields. Everything downstream -
    skill extraction, the LLM prompt, the API response - wants prose, and
    passing tags through would also mean an advert could inject markup into
    any client that renders our output. Tags are removed rather than escaped
    because none of them carry meaning we need.
    """
    if not raw:
        return ""
    text = str(raw)
    # Unescape *before* stripping, not only after. Greenhouse publishes its
    # advert body entity-encoded ("&lt;p&gt;"), so tag removal on the raw
    # string matches nothing and the unescape at the end then turns the
    # survivors back into visible "<p>" and "<strong>" litter -- which flows
    # into skill extraction and the LLM prompt, not just the screen.
    #
    # Doing it first is also the safer order: "&lt;script&gt;alert(1)&lt;/
    # script&gt;" becomes a real script element and is removed with its
    # contents, rather than surviving as text that reads like prose.
    text = html.unescape(text)
    # Drop these elements *including their contents*. Stripping only the tags
    # would leave the script body sitting in the description as though it were
    # prose, which then flows into skill extraction, the LLM prompt and the API
    # response. Verified: without this, "<script>alert(1)</script>" yields the
    # text "alert(1)".
    text = re.sub(
        r"(?is)<(script|style|noscript|iframe|template)\b[^>]*>.*?</\1\s*>", " ", text
    )
    # Block-level tags mark real breaks; losing them would run paragraphs
    # together into an unreadable wall.
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|h[1-6]|tr)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "\n- ", text)
    text = _TAG_RE.sub(" ", text)
    # `html.unescape` rather than a table of the entities we happened to think
    # of. A hand-written table missed numeric references, so a live Hacker
    # News advert came back reading "https:&#x2F;&#x2F;govstar.us". The
    # standard library knows the whole set.
    text = html.unescape(text)
    # `&nbsp;` decodes to U+00A0, which is not an ordinary space and is not
    # collapsed by the whitespace pass below. Left alone it travels into
    # skill matching, where "Node.js\u00a0developer" fails to match a query
    # for "node.js developer" for reasons nobody can see on screen.
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = _WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANKS_RE.sub("\n\n", text).strip()


def _clip(text: str, limit: int = MAX_DESCRIPTION_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[truncated]"


# --- XML safety ------------------------------------------------------------

_DOCTYPE_RE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


def _parse_xml(raw: bytes) -> ElementTree.Element:
    """Parse a feed, refusing documents that declare a DTD.

    This is not theoretical. ``xml.etree.ElementTree`` expands internal
    entities, so the classic "billion laughs" document - under 400 bytes -
    expands without limit and takes the process with it. It was measured
    against this Python before the check was written, not assumed.

    Legitimate RSS and Atom never need a DTD, so refusing outright costs
    nothing and removes the entire class of attack. The alternative is a third
    party dependency (``defusedxml``); the check is three lines and this way
    the reasoning stays next to the parse.
    """
    if _DOCTYPE_RE.search(raw[:4096]):
        raise ScraperError("feed declares a DTD or entity; refusing to parse")
    try:
        return ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise ScraperError("malformed XML: %s" % exc) from exc


# --- Transport -------------------------------------------------------------


class HttpFetcher:
    """The default way bytes are obtained. Replaceable, which is the point.

    Every network detail lives behind this one callable so that tests, which
    must stay offline and deterministic, can hand :class:`JobScraper` a plain
    function instead. No test in this project touches a real job board.
    """

    def __init__(
        self,
        timeout: Optional[float] = None,
        max_bytes: Optional[int] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        self.timeout = timeout if timeout is not None else settings.JOB_FETCH_TIMEOUT_SECONDS
        self.max_bytes = max_bytes if max_bytes is not None else settings.JOB_FETCH_MAX_BYTES
        self.user_agent = user_agent or settings.JOB_SCRAPER_USER_AGENT
        self._session: Any = None

    def _get_session(self) -> Any:
        if self._session is None:
            import requests  # imported late: the module must import without it

            self._session = requests.Session()
            self._session.headers.update(
                {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}
            )
        return self._session

    def __call__(self, url: str) -> bytes:
        """Fetch ``url``, retrying only failures that a retry can fix.

        The split below is the point. A connection reset, a timeout, a 429 or a
        5xx are conditions of the moment, and the same request a second later
        may well succeed. A 404, a 403 or a redirect we refuse to follow are
        properties of the request itself: retrying spends the caller's time to
        arrive at an identical answer. So the deterministic cases are raised as
        :class:`ScraperError`, which is not in ``retry_on`` and therefore
        leaves on the first attempt.
        """
        attempt_fetch = retry_with_backoff(
            max_attempts=settings.JOB_FETCH_MAX_ATTEMPTS,
            backoff_factor=settings.JOB_FETCH_BACKOFF_FACTOR,
            retry_on=self._transient_errors(),
        )(self._fetch_once)
        return attempt_fetch(url)

    @staticmethod
    def _transient_errors() -> Tuple[type, ...]:
        """Exception types worth a second attempt, resolved late.

        ``requests`` is imported lazily by this class, so the types cannot be
        named at module import time.
        """
        try:
            import requests
        except ImportError:  # pragma: no cover - requests is a hard dependency
            return (OSError,)
        return (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            _TransientHTTPError,
        )

    def _fetch_once(self, url: str) -> bytes:
        session = self._get_session()
        # Redirects are not followed. A 302 to an internal address would walk
        # straight around the allow-list check that was done on this URL.
        response = session.get(
            url, timeout=self.timeout, allow_redirects=False, stream=True
        )
        if response.status_code in (301, 302, 303, 307, 308):
            raise ScraperError(
                "%s redirected to %r; not followed"
                % (url, response.headers.get("Location", "?"))
            )
        # 429 and 5xx are the server saying "not now" rather than "no".
        if response.status_code == 429 or response.status_code >= 500:
            raise _TransientHTTPError(
                "%s returned %d" % (url, response.status_code)
            )
        if response.status_code >= 400:
            raise ScraperError("%s returned %d" % (url, response.status_code))

        # Read in chunks against the cap. Trusting Content-Length would be
        # trusting the server not to lie about how much it is about to send.
        chunks: List[bytes] = []
        total = 0
        for chunk in response.iter_content(8192):
            total += len(chunk)
            if total > self.max_bytes:
                raise ScraperError("response from %s exceeded %d bytes" % (url, self.max_bytes))
            chunks.append(chunk)
        return b"".join(chunks)


# --- Politeness ------------------------------------------------------------


class _Throttle:
    """One request per host per interval, and a short-lived response cache.

    Both exist to keep a promise made to the sources rather than to make this
    module faster, though it does that too.
    """

    def __init__(self, min_interval: float, ttl: int) -> None:
        self.min_interval = min_interval
        self.ttl = ttl
        self._last: Dict[str, float] = {}
        self._cache: Dict[str, Tuple[float, bytes]] = {}
        self._lock = threading.Lock()

    def cached(self, url: str) -> Optional[bytes]:
        """Return the stored response body for ``url`` if it is still fresh."""
        with self._lock:
            entry = self._cache.get(url)
            if entry is None:
                return None
            stored_at, payload = entry
            if time.time() - stored_at > self.ttl:
                self._cache.pop(url, None)
                return None
            return payload

    def store(self, url: str, payload: bytes) -> None:
        """Remember a response body against its URL."""
        with self._lock:
            self._cache[url] = (time.time(), payload)

    def wait(self, host: str) -> None:
        """Block until this host may be called again.

        Sources such as Remotive make a request rate part of their terms of
        use, so the pause is a condition of access rather than politeness.
        Tracked per host: being slow to one site is no reason to be slow to
        another.
        """
        with self._lock:
            last = self._last.get(host)
            now = time.time()
            if last is not None:
                remaining = self.min_interval - (now - last)
                if remaining > 0:
                    time.sleep(remaining)
                    now = time.time()
            self._last[host] = now

    def clear(self) -> None:
        """Forget both the cached bodies and the per-host timings."""
        with self._lock:
            self._last.clear()
            self._cache.clear()


# --- The scraper -----------------------------------------------------------


class JobScraper:
    """Reads job adverts from public APIs and feeds.

    Args:
        fetcher: Anything callable as ``fetcher(url) -> bytes``. Defaults to
            :class:`HttpFetcher`. Tests pass a function.
        respect_robots: Check robots.txt before fetching. Only turned off in
            tests, which never reach a network anyway.
        allowed_hosts: Overrides the module allow-list. Widening it is a
            security decision, so it is explicit rather than a config value.
    """

    label = "Job Scraper"

    def __init__(
        self,
        fetcher: Optional[Callable[[str], bytes]] = None,
        respect_robots: Optional[bool] = None,
        allowed_hosts: Optional[Set[str]] = None,
        min_interval: Optional[float] = None,
        cache_ttl: Optional[int] = None,
    ) -> None:
        _custom_fetcher = fetcher is not None
        self.fetcher = fetcher or HttpFetcher()
        # When a caller injects their own fetcher (always a test stub), the DNS
        # check in _validate_url is both unnecessary and unreliable: the stub
        # never touches the network, so whether the host resolves is irrelevant,
        # and in CI / sandbox environments DNS for the test hostnames is blocked.
        # The allow-list and scheme checks still run; only the socket call is
        # skipped. Production always uses HttpFetcher, so validate_urls=True.
        self._validate_urls: bool = not _custom_fetcher
        self.respect_robots = (
            settings.JOB_RESPECT_ROBOTS if respect_robots is None else respect_robots
        )
        self.allowed_hosts = ALLOWED_HOSTS if allowed_hosts is None else set(allowed_hosts)
        self._throttle = _Throttle(
            min_interval if min_interval is not None
            else settings.JOB_FETCH_MIN_INTERVAL_SECONDS,
            cache_ttl if cache_ttl is not None else settings.JOB_CACHE_TTL_SECONDS,
        )
        self._robots: Dict[str, Optional[RobotFileParser]] = {}
        self._robots_lock = threading.Lock()

        #: Tried in order by :meth:`search`. Each is ``(name, callable)`` so a
        #: failure can be logged against a name a human recognises.
        self.sources: List[Tuple[str, Callable[[str, str, int], List[Dict[str, Any]]]]] = [
            ("IndiaBoards", self._fetch_india_boards),
            ("Adzuna", self._fetch_adzuna),
            ("HackerNews", self._fetch_hackernews),
            ("RSS", self._fetch_rss),
            ("Remotive", self._fetch_remotive),
            ("Arbeitnow", self._fetch_arbeitnow),
        ]

    @property
    def session(self) -> Any:
        """The underlying :class:`requests.Session`, or ``None``.

        The session belongs to the fetcher rather than to this class, which
        is what lets every test run without a network: a test passes its own
        callable as ``fetcher`` and no socket is ever opened. This property
        exists so callers that want connection-pool details (headers, adapter
        configuration) can still reach them, and returns ``None`` when the
        fetcher is a stub or has not yet made its first request.
        """
        get_session = getattr(self.fetcher, "_get_session", None)
        if get_session is None:
            return None
        return get_session()

    # -- Fetch plumbing --------------------------------------------------

    def _allowed_by_robots(self, url: str) -> bool:
        """Ask the host's robots.txt whether we may fetch this path.

        The status codes follow RFC 9309 section 2.3.1, which is worth
        spelling out because the intuitive reading is wrong in both
        directions:

        * 200 - parse the rules and obey them.
        * 4xx - "unavailable". The standard says a crawler MAY then access
          any part of the site. Refusing here is not the cautious choice, it
          is a broken one: several of these hosts sit behind a CDN that
          answers 403 to any unattended request for robots.txt, so treating
          4xx as "forbidden" silently disabled sources that had in fact
          published no restrictions at all.
        * 5xx or a network failure - "unreachable". The standard says assume
          complete disallow, and that is what we do. A host having a bad day
          is not permission.

        ``RobotFileParser.read()`` is deliberately not used. It fetches with
        urllib's own User-Agent, which at least one of these hosts answers
        with 403, and the parser then records that as *disallow all*. That is
        how a site whose robots.txt reads ``Allow: /`` came to be skipped.
        Fetching it ourselves, under our own honest User-Agent, is what makes
        the answer reflect the published rules.
        """
        if not self.respect_robots:
            return True

        parsed = urlparse(url)
        # See CREDENTIALLED_API_HOSTS: an API we hold a key for is not a site
        # we are crawling, and its blanket Disallow is aimed at search engines.
        if parsed.netloc in CREDENTIALLED_API_HOSTS:
            return True

        origin = "%s://%s" % (parsed.scheme, parsed.netloc)

        with self._robots_lock:
            if origin not in self._robots:
                self._robots[origin] = self._read_robots(origin)
            parser = self._robots[origin]

        if parser is None:  # unreadable: assume disallowed
            return False
        if parser is _ROBOTS_ABSENT:  # published nothing: assume allowed
            return True
        try:
            return bool(parser.can_fetch(settings.JOB_SCRAPER_USER_AGENT, url))
        except Exception:  # noqa: BLE001 - a malformed rule must not block us
            return True

    def _read_robots(self, origin: str) -> Any:
        """Fetch and parse one robots.txt.

        Returns a parser, ``_ROBOTS_ABSENT`` when the host published none, or
        ``None`` when it could not be read at all.
        """
        import requests

        try:
            response = requests.get(
                origin + "/robots.txt",
                timeout=settings.JOB_FETCH_TIMEOUT_SECONDS,
                headers={"User-Agent": settings.JOB_SCRAPER_USER_AGENT},
                # Redirects are followed here, unlike for content: a host
                # redirecting example.com to www.example.com is ordinary, and
                # requests caps the chain itself.
                allow_redirects=True,
            )
        except Exception as exc:  # noqa: BLE001 - unreachable means disallow
            logger.warning("robots.txt at %s unreachable (%s); skipping host", origin, exc)
            return None

        if response.status_code >= 500:
            logger.warning("robots.txt at %s returned %s; skipping host", origin, response.status_code)
            return None
        if response.status_code >= 400:
            logger.debug("robots.txt at %s returned %s; treating as unrestricted",
                         origin, response.status_code)
            return _ROBOTS_ABSENT

        parser = RobotFileParser()
        try:
            parser.parse(response.text.splitlines())
        except Exception:  # noqa: BLE001 - unparseable rules are not a licence
            logger.warning("robots.txt at %s could not be parsed", origin)
            return None
        return parser

    def _fetch(self, url: str) -> bytes:
        """Validate, throttle, cache and fetch. Every request goes through here."""
        # Skip the DNS portion of validation when a test stub is injected;
        # the allow-list and scheme checks still happen inside _validate_url
        # via the validate_dns flag.
        url = _validate_url(url, self.allowed_hosts, validate_dns=self._validate_urls)

        cached = self._throttle.cached(url)
        if cached is not None:
            logger.debug("Cache hit for %s", url)
            return cached

        if not self._allowed_by_robots(url):
            raise ScraperError("robots.txt at %s disallows this path" % urlparse(url).netloc)

        self._throttle.wait(urlparse(url).hostname or "")
        payload = self.fetcher(url)
        if not isinstance(payload, (bytes, bytearray)):
            raise ScraperError("fetcher returned %s, expected bytes" % type(payload).__name__)
        payload = bytes(payload)
        self._throttle.store(url, payload)
        return payload

    def _fetch_json(self, url: str) -> Any:
        raw = self._fetch(url)
        try:
            return json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError as exc:
            raise ScraperError("%s did not return JSON: %s" % (url, exc)) from exc

    # -- Hacker News -----------------------------------------------------

    def fetch_jobs_hacker_news(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Job adverts from the current "Ask HN: Who is hiring?" thread.

        Hacker News runs one hiring thread a month, and each top-level comment
        is one advert. Replies to those comments are discussion, not jobs, so
        only top-level comments are kept - the check is ``parent_id ==
        story_id``. Without it roughly a third of the results are people
        arguing about salaries.
        """
        query = (query or "").strip()
        limit = max(1, as_int(limit, 5))

        story = self._latest_hiring_story()
        if story is None:
            logger.info("No Hacker News hiring thread found")
            return []

        story_id, story_title = story
        url = (
            "%s?tags=comment,story_%s&hitsPerPage=%d&query=%s"
            % (HN_SEARCH_URL, story_id, min(limit * 4, 100), _quote(query))
        )
        payload = self._fetch_json(url)

        jobs: List[Dict[str, Any]] = []
        for hit in as_list((payload or {}).get("hits"))[: limit * 4]:
            if not isinstance(hit, dict):
                continue
            # Top-level comments only: a reply is conversation about a job,
            # not a job.
            if str(hit.get("parent_id") or "") != str(story_id):
                continue
            text = _strip_html(hit.get("comment_text"))
            if len(text) < 120:
                # Too short to be an advert; usually "same as last month".
                continue
            title, company = _split_hn_headline(text)
            thread_url = HN_ITEM_URL.format(id=hit.get("objectID"))
            jobs.append(
                _job(
                    title=title,
                    company=company,
                    description=text,
                    source="HackerNews",
                    # The advert's own link where it gives one, so the button
                    # opens somewhere you can apply rather than a discussion.
                    url=_hn_apply_url(text) or thread_url,
                    posted_date=_date(hit.get("created_at")),
                    extra={
                        "thread": story_title,
                        "author": hit.get("author"),
                        "location": _hn_location(text),
                        "discussion_url": thread_url,
                    },
                )
            )
            if len(jobs) >= limit:
                break

        logger.info("Hacker News: %d advert(s) from %s", len(jobs), story_title)
        return jobs

    def _latest_hiring_story(self) -> Optional[Tuple[str, str]]:
        """Find the most recent monthly hiring thread."""
        url = (
            "%s?tags=story,author_whoishiring&query=hiring&hitsPerPage=5"
            % HN_SEARCH_BY_DATE_URL
        )
        payload = self._fetch_json(url)
        for hit in as_list((payload or {}).get("hits")):
            if not isinstance(hit, dict):
                continue
            title = str(hit.get("title") or "")
            if "who is hiring" in title.lower():
                return str(hit.get("objectID")), title
        return None

    # -- RSS -------------------------------------------------------------

    def fetch_jobs_rss(self, rss_feeds: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """Read one or more RSS feeds.

        Feed URLs still go through the allow-list. This method is reachable
        from a request handler, and a parameter naming a URL to fetch is a
        server-side request forgery primitive unless something constrains it.
        """
        feeds = list(rss_feeds) if rss_feeds else list(DEFAULT_RSS_FEEDS)
        jobs: List[Dict[str, Any]] = []

        for feed_url in feeds:
            try:
                raw = self._fetch(feed_url)
                root = _parse_xml(raw)
            except (ScraperError, Exception) as exc:  # noqa: BLE001
                logger.warning("RSS feed %s failed: %s", feed_url, exc)
                continue

            source = _source_name(feed_url)
            for item in _rss_items(root):
                job = _rss_item_to_job(item, source)
                if job is not None:
                    jobs.append(job)

        logger.info("RSS: %d advert(s) from %d feed(s)", len(jobs), len(feeds))
        return jobs

    # -- Remotive --------------------------------------------------------

    def fetch_jobs_adzuna(
        self, query: str = "", limit: int = 20, max_age_days: int = 7
    ) -> List[Dict[str, Any]]:
        """Adzuna's India endpoint, if a key has been configured.

        This is the one source that reaches listings which also appear on the
        big job boards, and it reaches them the permitted way: Adzuna licenses
        what it redistributes and issues keys for this purpose. ``redirect_url``
        is a direct link to the advert, so the Apply button still opens
        somewhere an application can actually be made.

        Returns nothing at all when no key is set. An optional source that is
        not configured is not an error, and raising here would break discovery
        for everyone who never asked for it.
        """
        app_id = (settings.ADZUNA_APP_ID or "").strip()
        app_key = (settings.ADZUNA_APP_KEY or "").strip()
        if not app_id or not app_key:
            return []

        limit = max(1, as_int(limit, 20))
        url = (
            "%s?app_id=%s&app_key=%s&results_per_page=%d&content-type=application/json"
            % (ADZUNA_URL, _quote(app_id), _quote(app_key), min(limit * 3, 50))
        )
        # Asked for at the source rather than filtered afterwards, so the
        # seven-day rule costs one request instead of a page of discards.
        age = max(1, as_int(max_age_days, 7))
        url += "&max_days_old=%d" % age
        if query.strip():
            url += "&what=%s" % _quote(query)

        payload = self._fetch_json(url)
        jobs: List[Dict[str, Any]] = []
        for entry in as_list((payload or {}).get("results"))[: limit * 3]:
            if not isinstance(entry, dict):
                continue
            company = entry.get("company")
            location = entry.get("location")
            jobs.append(
                _job(
                    title=entry.get("title"),
                    company=(company or {}).get("display_name")
                    if isinstance(company, dict)
                    else company,
                    description=_strip_html(entry.get("description")),
                    source="Adzuna",
                    url=entry.get("redirect_url"),
                    posted_date=_date(entry.get("created")),
                    extra={
                        "location": (location or {}).get("display_name")
                        if isinstance(location, dict)
                        else location,
                        "attribution": "Job listing courtesy of Adzuna (adzuna.in)",
                    },
                )
            )
            if len(jobs) >= limit:
                break

        logger.info("Adzuna: %d advert(s)", len(jobs))
        return jobs

    def fetch_jobs_remotive(self, query: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        """Remotive's free API.

        Their response carries a legal notice requiring that we link back to
        the Remotive URL and name Remotive as the source, and asking for no
        more than about four calls a day. The link and the name are in every
        record; the call budget is kept by the six-hour cache.
        """
        limit = max(1, as_int(limit, 20))
        url = "%s?limit=%d" % (REMOTIVE_URL, min(limit * 3, 100))
        if query.strip():
            url += "&search=%s" % _quote(query)

        payload = self._fetch_json(url)
        jobs: List[Dict[str, Any]] = []
        for entry in as_list((payload or {}).get("jobs"))[: limit * 3]:
            if not isinstance(entry, dict):
                continue
            jobs.append(
                _job(
                    title=entry.get("title"),
                    company=entry.get("company_name"),
                    description=_strip_html(entry.get("description")),
                    source="Remotive",
                    url=entry.get("url"),
                    posted_date=_date(entry.get("publication_date")),
                    extra={
                        "location": entry.get("candidate_required_location"),
                        "salary": entry.get("salary"),
                        "job_type": entry.get("job_type"),
                        "tags": as_list(entry.get("tags")),
                        "attribution": "Job listing courtesy of Remotive (remotive.com)",
                    },
                )
            )
            if len(jobs) >= limit:
                break

        logger.info("Remotive: %d advert(s)", len(jobs))
        return jobs

    # -- Arbeitnow -------------------------------------------------------

    def fetch_jobs_arbeitnow(self, query: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        """Arbeitnow's free, keyless job-board API."""
        limit = max(1, as_int(limit, 20))
        payload = self._fetch_json(ARBEITNOW_URL)
        wanted = (query or "").strip().lower()

        jobs: List[Dict[str, Any]] = []
        for entry in as_list((payload or {}).get("data")):
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title") or "")
            description = _strip_html(entry.get("description"))
            if wanted and wanted not in (title + " " + description).lower():
                continue
            jobs.append(
                _job(
                    title=title,
                    company=entry.get("company_name"),
                    description=description,
                    source="Arbeitnow",
                    url=entry.get("url"),
                    posted_date=_date(entry.get("created_at")),
                    extra={
                        "location": entry.get("location"),
                        "remote": bool(entry.get("remote")),
                        "tags": as_list(entry.get("tags")),
                    },
                )
            )
            if len(jobs) >= limit:
                break

        logger.info("Arbeitnow: %d advert(s)", len(jobs))
        return jobs

    # -- India ------------------------------------------------------------

    def _greenhouse(self, slug: str) -> List[Dict[str, Any]]:
        payload = self._fetch_json(GREENHOUSE_URL.format(slug=slug))
        out = []
        for entry in as_list((payload or {}).get("jobs")):
            if isinstance(entry, dict):
                out.append(
                    (
                        entry.get("title"),
                        _clean_line((entry.get("location") or {}).get("name")),
                        _strip_html(entry.get("content")),
                        entry.get("absolute_url"),
                        _date(entry.get("updated_at") or entry.get("created_at")),
                    )
                )
        return out

    def _lever(self, slug: str) -> List[Dict[str, Any]]:
        payload = self._fetch_json(LEVER_URL.format(slug=slug))
        out = []
        for entry in as_list(payload):
            if isinstance(entry, dict):
                categories = entry.get("categories") or {}
                out.append(
                    (
                        entry.get("text"),
                        _clean_line(categories.get("location")),
                        _strip_html(
                            entry.get("descriptionPlain") or entry.get("description")
                        ),
                        entry.get("hostedUrl"),
                        # Lever publishes epoch milliseconds, which `_date`
                        # has no reason to understand; seconds are what every
                        # other source sends.
                        _date(_epoch_seconds(entry.get("createdAt"))),
                    )
                )
        return out

    def _ashby(self, slug: str) -> List[Dict[str, Any]]:
        payload = self._fetch_json(ASHBY_URL.format(slug=slug))
        out = []
        for entry in as_list((payload or {}).get("jobs")):
            if isinstance(entry, dict):
                out.append(
                    (
                        entry.get("title"),
                        _clean_line(entry.get("location")),
                        _strip_html(
                            entry.get("descriptionPlain") or entry.get("descriptionHtml")
                        ),
                        entry.get("jobUrl") or entry.get("applyUrl"),
                        _date(entry.get("publishedAt")),
                    )
                )
        return out

    def fetch_jobs_india_boards(
        self, query: str = "", limit: int = 20, boards: Optional[Sequence[Tuple[str, str, str]]] = None
    ) -> List[Dict[str, Any]]:
        """Vacancies published by companies hiring in India, from their own ATS.

        There is no open search API for the Indian job market -- see
        :data:`CLOSED_JOB_BOARDS` for the four that get asked about and why
        each is unavailable. What *is* open is the feed behind each company's
        careers page, so this reads a curated list of them directly.

        One board failing costs that board only. A company can rename its
        board, move between ATS vendors or simply stop publishing, and any of
        those is a 404 that must not take the other eleven down with it.
        """
        limit = max(1, as_int(limit, 20))
        wanted = [
            w for w in re.split(r"[^a-z0-9+#.]+", (query or "").strip().lower()) if w
        ]
        readers = {
            "greenhouse": self._greenhouse,
            "lever": self._lever,
            "ashby": self._ashby,
        }

        jobs: List[Dict[str, Any]] = []
        missing: List[str] = []
        for company, ats, slug in boards if boards is not None else INDIA_BOARDS:
            reader = readers.get(ats)
            if reader is None:
                continue
            try:
                rows = reader(slug)
            except Exception as exc:  # noqa: BLE001 - one dead board is survivable
                logger.debug("India board %s (%s) unavailable: %s", company, ats, exc)
                missing.append(company)
                continue
            for title, location, description, url, posted in rows:
                title = str(title or "")
                if wanted and not all(
                    word in (title + " " + description + " " + location).lower()
                    for word in wanted
                ):
                    continue
                jobs.append(
                    _job(
                        title=title,
                        company=company,
                        description=description,
                        source="%s careers" % company,
                        url=url,
                        posted_date=posted,
                        extra={"location": location, "ats": ats},
                    )
                )

        if missing:
            logger.info(
                "India boards: %d advert(s); %d board(s) unavailable (%s)",
                len(jobs), len(missing), ", ".join(missing),
            )
        else:
            logger.info("India boards: %d advert(s)", len(jobs))
        return jobs[:limit] if limit < len(jobs) else jobs

    # -- Retired ---------------------------------------------------------

    def fetch_jobs_github(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Retired upstream. Returns nothing, and says why.

        Kept so that callers written against the original interface do not
        break. It does not quietly substitute a different job board: a method
        named after GitHub returning adverts from elsewhere would be a lie
        that is very hard to notice.
        """
        del query, limit  # accepted for interface compatibility only
        logger.warning("fetch_jobs_github: %s", GITHUB_JOBS_RETIRED)
        return []

    # -- Aggregation -----------------------------------------------------

    def _fetch_adzuna(self, query: str, location: str, limit: int) -> List[Dict[str, Any]]:
        # The endpoint is India-only, so a location filter here could only
        # ever narrow it further -- which is the caller's business, not this
        # method's. Applied for consistency with every other source.
        found = self.fetch_jobs_adzuna(query, limit)
        return _filter_jobs(found, "", location)[:limit]

    def _fetch_hackernews(self, query: str, location: str, limit: int) -> List[Dict[str, Any]]:
        # Algolia has no location field, so the filter is applied here instead.
        # Without this, asking for "remote" returned onsite roles from this one
        # source while every other source honoured it.
        found = self.fetch_jobs_hacker_news(query, limit)
        return _filter_jobs(found, "", location)[:limit]

    def _fetch_rss(self, query: str, location: str, limit: int) -> List[Dict[str, Any]]:
        jobs = self.fetch_jobs_rss()
        return _filter_jobs(jobs, query, location)[:limit]

    def _fetch_remotive(self, query: str, location: str, limit: int) -> List[Dict[str, Any]]:
        return _filter_jobs(self.fetch_jobs_remotive(query, limit), "", location)[:limit]

    def _fetch_arbeitnow(self, query: str, location: str, limit: int) -> List[Dict[str, Any]]:
        return _filter_jobs(self.fetch_jobs_arbeitnow(query, limit), "", location)[:limit]

    def _fetch_india_boards(
        self, query: str, location: str, limit: int
    ) -> List[Dict[str, Any]]:
        # Fetched without a limit and cut after filtering. Truncating first
        # would take whichever adverts happened to come back before the India
        # ones -- these boards are curated for India but not exclusively India.
        found = self.fetch_jobs_india_boards(query, limit=10_000)
        kept = _filter_jobs(found, "", location or "india")

        # Round-robin by employer for the same reason `search` does it by
        # source: Paytm alone publishes 173 India vacancies against Atlan's 6,
        # so taking the first ten in order returns ten Paytm adverts and the
        # other eleven companies might as well not have been fetched.
        by_company: Dict[str, List[Dict[str, Any]]] = {}
        for job in kept:
            by_company.setdefault(str(job.get("company") or ""), []).append(job)
        return _interleave(list(by_company.values()))[:limit]

    @observed("search_jobs")
    def search(
        self, query: str, location: str = "remote", limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Every source, best effort, de-duplicated, interleaved.

        One source failing must not lose the others - job boards go down, rate
        limit, and change their JSON without warning. Each is tried inside its
        own guard and a failure costs that source's results only.

        Results are taken round-robin rather than by concatenating each
        source's list and slicing. Concatenating looks equivalent and is not:
        a live search for ten jobs returned twenty-nine adverts across three
        boards and handed back ten Hacker News comments, because Hacker News
        happened to be first in the list. The other two boards might as well
        not have been queried.

        They are then ordered newest first, **before** the limit is applied.
        Sorting afterwards would be pointless: it would only reorder whichever
        arbitrary ten adverts survived the cut, so the freshest advert on the
        eleventh row would never be seen.
        """
        query = (query or "").strip()
        location = (location or "").strip()
        limit = max(1, as_int(limit, 10))

        per_source: List[List[Dict[str, Any]]] = []
        failures: List[str] = []

        for name, source in self.sources:
            try:
                found = source(query, location, limit)
            except Exception as exc:  # noqa: BLE001 - one bad source is survivable
                logger.warning("Source %s failed: %s", name, exc)
                failures.append(name)
                continue
            if found:
                per_source.append(list(found))

        results = _interleave(per_source)
        deduped = _by_recency(_dedupe(results))
        if failures:
            logger.info(
                "Search '%s': %d advert(s); %d source(s) unavailable (%s)",
                query, len(deduped), len(failures), ", ".join(failures),
            )
        else:
            logger.info("Search '%s': %d advert(s) from %d source(s)",
                        query, len(deduped), len(self.sources))
        return deduped[:limit]

    def search_multiple_sources(
        self, query: str, location: str = "remote", limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Alias of :meth:`search`, kept for the documented interface."""
        return self.search(query, location, limit)

    def clear_cache(self) -> None:
        """Forget cached responses and per-host timings.

        Mainly for tests. In production the throttle state is what keeps us
        inside the sources' rate limits, so clearing it in a running process
        allows a burst that those terms do not.
        """
        self._throttle.clear()


# --- Record shaping --------------------------------------------------------


def _interleave(groups: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Take one advert from each group in turn until all are exhausted.

    Keeps every result - nothing is dropped here, only reordered - so that a
    later truncation to the caller's limit spreads across the sources instead
    of emptying the first one.
    """
    merged: List[Dict[str, Any]] = []
    for index in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if index < len(group):
                merged.append(group[index])
    return merged


def _job(
    title: Any,
    company: Any,
    description: str,
    source: str,
    url: Any,
    posted_date: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One advert in the shape every downstream stage expects.

    ``source`` and ``url`` are never dropped: attribution is a condition of
    use for at least one source, and a job the user cannot open is useless.
    """
    record = {
        "title": _clean_line(title) or "Untitled role",
        "company": _clean_line(company) or "Not stated",
        "description": _clip(description or ""),
        "source": source,
        "url": str(url or ""),
        "posted_date": posted_date,
        # None when the source gave no date. Kept as None all the way to the
        # browser so the card can say "Not stated" instead of "0 days ago".
        "days_old": _age_in_days(posted_date),
    }
    # A stable id, derived from the advert itself rather than a counter or a
    # random value. Searching twice must yield the same id for the same
    # advert, otherwise the saved-jobs store would fill with duplicates and
    # a job id handed to a client would stop resolving after the next search.
    # The URL identifies it where there is one; Hacker News comments have no
    # URL of their own, so those fall back to source, title and company.
    fingerprint = record["url"] or "%s|%s|%s" % (
        source,
        record["title"].lower(),
        record["company"].lower(),
    )
    record["job_id"] = "job_%s" % hashlib.sha256(
        fingerprint.encode("utf-8")
    ).hexdigest()[:12]
    if extra:
        record.update({k: v for k, v in extra.items() if v not in (None, "", [])})
    return record


def _clean_line(value: Any) -> str:
    if not value:
        return ""
    return _WS_RE.sub(" ", str(value).replace("\n", " ")).strip()


def _date(value: Any) -> str:
    """Normalise whatever the source calls a date into ``YYYY-MM-DD``.

    An absent date returns an empty string, **not** today. Substituting today
    is what this used to do, and it is the worst possible default once adverts
    are filtered and sorted by age: an advert with no date would sort to the
    top and be labelled "posted today", which is a claim the source never
    made. Unknown has to stay distinguishable from fresh.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text[:10]


def _epoch_seconds(value: Any) -> str:
    """Turn Lever's epoch milliseconds into something :func:`_date` reads.

    Returns "" rather than a guess when the value is missing or not a number,
    so an undated advert stays undated instead of arriving stamped 1970.
    """
    try:
        millis = float(value)
    except (TypeError, ValueError):
        return ""
    if millis <= 0:
        return ""
    return datetime.fromtimestamp(millis / 1000.0, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _age_in_days(posted_date: Any) -> Optional[int]:
    """How many days ago an advert was posted, or ``None`` if it never said.

    ``None`` is a real answer here and callers must carry it through rather
    than coercing it to 0, which would read as "posted today".
    """
    text = str(posted_date or "").strip()[:10]
    if not text:
        return None
    try:
        posted = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    age = (datetime.now(timezone.utc) - posted).days
    # A source in a timezone ahead of UTC can date an advert "tomorrow".
    # That is still today's news, not a negative age.
    return max(0, age)


def _by_recency(jobs: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Newest first. Adverts with no date go last, in their original order.

    They are not dropped - an undated advert can still be the right job - but
    they cannot be allowed to displace one that is provably recent.
    """
    dated = [j for j in jobs if j.get("days_old") is not None]
    undated = [j for j in jobs if j.get("days_old") is None]
    dated.sort(key=lambda j: j["days_old"])
    return dated + undated


def fresh_jobs(
    jobs: Sequence[Dict[str, Any]], max_age_days: Optional[int]
) -> List[Dict[str, Any]]:
    """Adverts posted within ``max_age_days``. Undated adverts are excluded.

    Excluding the undated ones is deliberate: the caller asked for adverts of
    a known age, and "we don't know" is not "recent enough". The caller is
    expected to notice when this leaves too little and widen the window
    rather than present a thin list as though it were the whole market.
    """
    if max_age_days is None:
        return list(jobs)
    cap = max(0, as_int(max_age_days, 0))
    return [
        job
        for job in jobs
        if job.get("days_old") is not None and job["days_old"] <= cap
    ]


_HN_HEADLINE = re.compile(r"^\s*(?P<company>[^|(\n]{2,60}?)\s*(?:\||\u2013|\u2014|-)\s*(?P<rest>.+)")


def _split_hn_headline(text: str) -> Tuple[str, str]:
    """Pull a company and a role out of a Hacker News hiring comment.

    The thread's convention is ``Company | Role | Location | ...`` on the
    first line, but it is a convention rather than a format, so this fails
    softly: an unparseable line yields the line itself as the title and no
    company, which is still more useful than dropping the advert.
    """
    first = (text.split("\n", 1)[0] or "").strip()
    match = _HN_HEADLINE.match(first)
    if not match:
        return (first[:120] or "Untitled role"), ""
    company = match.group("company").strip()
    rest = match.group("rest")
    role = re.split(r"\s*(?:\||\u2013|\u2014)\s*", rest)[0].strip()
    return (role[:120] or "Untitled role"), company[:80]


#: Bare URLs as they appear in a Hacker News comment. Only http(s), so a
#: ``javascript:`` payload in a comment can never reach an ``href``.
_HN_URL = re.compile(r"https?://[^\s<>\"')\]]+")


def _hn_apply_url(text: str) -> str:
    """The advert's own application link, not the comment it was posted in.

    A Hacker News advert's ``url`` is the comment permalink, which is a
    discussion to read rather than a job to apply for. The permalink is kept
    as ``discussion_url``, but the button needs the careers page, and the
    thread convention puts that on the headline:

        ``Supero | Cloud / Platform Engineer | REMOTE (...) | Full-time |
        https://www.supero.dev/careers/cloud-platform-engineer``

    The first line is searched before the body because a comment often links
    its product or blog further down, and the headline link is the one that
    was offered as the way in. An advert that gives only an email address
    yields nothing here and keeps the permalink, which at least shows the
    address.
    """
    first, _, rest = (text or "").partition("\n")
    for chunk in (first, rest):
        for match in _HN_URL.finditer(chunk):
            url = match.group(0).rstrip(".,;)")
            if "ycombinator.com" in url.lower():
                continue
            return url
    return ""


def _hn_location(text: str) -> str:
    """The place written on a Hacker News hiring headline.

    Hacker News has no location field, so without this an advert arrives at
    the card with the place blank even though its own first line says
    ``Bengaluru, KA, India``.

    Only a segment naming a place this search understands is accepted, which
    is deliberately narrow. ``_location_haystack`` prefers this field over
    the headline, so returning a segment with no place in it would hide the
    place from the country filter and drop an advert that belongs in the
    results. Anything unrecognised is left blank, exactly as before.
    """
    first = (text.split("\n", 1)[0] or "").strip()
    # Segments 0 and 1 are the company and the role by convention.
    segments = re.split(r"\s*(?:\||\u2013|\u2014)\s*", first)[2:]
    known = [name for names in _LOCATION_ALIASES.values() for name in names]
    for segment in segments:
        if any(
            re.search(r"(?<!\w)%s(?!\w)" % re.escape(name), segment, re.IGNORECASE)
            for name in known
        ):
            return _clean_line(segment)[:120]
    return ""


def _source_name(feed_url: str) -> str:
    host = (urlparse(feed_url).hostname or "").lower()
    if "weworkremotely" in host:
        return "WeWorkRemotely"
    if "remotive" in host:
        return "Remotive"
    return host or "RSS"


def _rss_items(root: ElementTree.Element) -> List[ElementTree.Element]:
    """Items from RSS 2.0 or Atom, whichever this feed turned out to be."""
    items = root.findall("./channel/item")
    if items:
        return items
    return root.findall("{http://www.w3.org/2005/Atom}entry")


def _text_of(item: ElementTree.Element, *names: str) -> str:
    for name in names:
        found = item.find(name)
        if found is not None:
            if found.text:
                return found.text
            # Atom puts the link in an attribute rather than the body.
            href = found.get("href")
            if href:
                return href
    return ""


def _rss_item_to_job(item: ElementTree.Element, source: str) -> Optional[Dict[str, Any]]:
    title = _strip_html(_text_of(item, "title", "{http://www.w3.org/2005/Atom}title"))
    if not title:
        return None
    description = _strip_html(
        _text_of(
            item, "description", "content:encoded",
            "{http://www.w3.org/2005/Atom}summary",
            "{http://www.w3.org/2005/Atom}content",
        )
    )
    link = _text_of(item, "link", "{http://www.w3.org/2005/Atom}link").strip()
    published = _text_of(item, "pubDate", "{http://www.w3.org/2005/Atom}published")

    # WeWorkRemotely writes "Company: Role"; the region element holds location.
    company = ""
    if ":" in title and source == "WeWorkRemotely":
        company, _, title = title.partition(":")
        company, title = company.strip(), title.strip()

    return _job(
        title=title,
        company=company,
        description=description,
        source=source,
        url=link,
        posted_date=_date(published),
        extra={"location": _clean_line(_text_of(item, "region"))},
    )


# A country is not always written on the advert. A role in "Bengaluru,
# Karnataka" is in India and says so nowhere, so a whole-word match on
# "india" alone misses most of the Indian market. These are the places a
# search for India should also accept. Cities only - no states, because
# several Indian state names collide with words used elsewhere.
_LOCATION_ALIASES: Dict[str, Tuple[str, ...]] = {
    "india": (
        "india", "bharat", "bengaluru", "bangalore", "hyderabad", "pune",
        "mumbai", "chennai", "delhi", "gurugram", "gurgaon", "noida",
        "kolkata", "ahmedabad", "jaipur", "kochi", "cochin", "coimbatore",
        "trivandrum", "thiruvananthapuram", "indore", "chandigarh",
        "nagpur", "mysuru", "mysore", "visakhapatnam", "bhubaneswar",
        "vadodara", "surat", "lucknow", "mohali",
    ),
}


def _place_patterns(place: str) -> List[str]:
    """Every spelling of a place that should count as a match.

    Whole-word lookarounds rather than ``\\b``: a place can end in
    punctuation, and ``\\b`` after the full stop in "D.C." demands a word
    character that is not there, so the match fails on a location that reads
    exactly right. ``(?!\\w)`` is satisfied by the end of the string.
    """
    names = _LOCATION_ALIASES.get(place.strip().lower(), (place,))
    return [r"(?<!\w)%s(?!\w)" % re.escape(name) for name in names]


def _location_haystack(job: Dict[str, Any]) -> str:
    """Where a job's location is actually written down.

    Prefer the source's own location field. Hacker News has none -- its thread
    convention puts the place on the headline, ``Company | Role | Location`` --
    so fall back to the first line of the title and body.

    The rest of the description is deliberately *not* searched. Adverts list
    the countries a company has offices in, the US states it can employ in and
    the timezones it overlaps with, and matching on any of those returns roles
    that are somewhere else entirely.
    """
    field = _clean_line(job.get("location"))
    if field:
        return field
    headline = str(job.get("description") or "").split("\n", 1)[0]
    return "%s %s" % (job.get("title") or "", headline)


def _filter_jobs(
    jobs: Sequence[Dict[str, Any]], query: str, location: str
) -> List[Dict[str, Any]]:
    """Keep adverts that mention the query, and that fit the location.

    "remote" and "anywhere" are treated as "no location constraint" rather
    than as keywords, because a remote role in an advert that never uses the
    word is still remote, and excluding it would be worse than including a
    few extras.

    Any other place is matched as a **whole word** against the advert's
    **location only**. Both halves of that were bugs, and a live search for
    ``india`` returned exactly two adverts that demonstrated each:

    * ``Senior Staff Data Engineer`` at Faire, located "Anywhere in the World",
      matched because its description lists the US states the company can hire
      in -- and one of them is **Indiana**. Substring matching cannot tell a
      country from the first six letters of a state.
    * ``Software Engineer (.NET C#)`` at TransPerfect, located "London, Greater
      London, United Kingdom", matched because the company mentions having an
      office in India.

    Neither job was in India, and a location filter that returns jobs on other
    continents is worse than no filter, because it looks like it worked.

    The query is matched as **every word present**, not as an exact phrase.
    Phrase matching was the reason discovery reported nothing: a live search
    for ``fullstack developer`` fetched 45 adverts across four boards and kept
    zero, because no advert contains that exact string. They say "Full Stack
    Developer", "Full-Stack Engineer", "Fullstack Web Developer". Requiring
    the words in that order, with that spacing, discards all three. Requiring
    only that each word appears keeps them, and an advert containing both
    "full stack" and "developer" is what was being asked for regardless of
    where the words sit.
    """
    wanted = [w for w in re.split(r"[^a-z0-9+#.]+", (query or "").strip().lower()) if w]
    place = (location or "").strip()

    out: List[Dict[str, Any]] = []
    for job in jobs:
        haystack = " ".join(
            str(job.get(k, "")) for k in ("title", "company", "description", "location")
        ).lower()
        if wanted and not all(word in haystack for word in wanted):
            continue
        if place and place.lower() not in ("remote", "anywhere", "any"):
            # A country is often implied by a city rather than written down,
            # so "india" also accepts the major Indian cities. See
            # _place_patterns for why these are lookarounds and not \b.
            haystack_place = _location_haystack(job)
            if not any(
                re.search(pattern, haystack_place, re.IGNORECASE)
                for pattern in _place_patterns(place)
            ):
                continue
        out.append(job)
    return out


def _dedupe(jobs: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop repeats. The same advert is often syndicated to several boards.

    Two keys are checked, not one. Matching on URL alone was not enough: an
    aggregator can carry the same vacancy under two of its own advert IDs, so
    the URLs differ while the job does not, and it appeared twice on the page.
    Identity is therefore also matched on employer, title and location.

    Location is part of that key deliberately. A company advertising the same
    title in Bangalore and in Pune is hiring twice, and collapsing those would
    hide a real opening from someone in the other city -- a worse failure than
    the duplicate this is fixing.
    """
    seen: Set[str] = set()
    out: List[Dict[str, Any]] = []
    for job in jobs:
        url = str(job.get("url") or "").strip().lower()
        identity = "%s|%s|%s" % (
            str(job.get("title", "")).lower().strip(),
            str(job.get("company", "")).lower().strip(),
            str(job.get("location", "")).lower().strip(),
        )
        keys = {identity}
        if url:
            keys.add(url)
        if keys & seen:
            continue
        seen |= keys
        out.append(job)
    return out


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value or "", safe="")


#: Shared instance for callers that do not need their own.
job_scraper = JobScraper()
