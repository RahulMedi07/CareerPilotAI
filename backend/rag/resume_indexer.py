"""Resume RAG system: parse, chunk, embed, store and semantically search.

The heavy ML dependencies (`chromadb`, `sentence_transformers`) are imported
lazily inside the accessor methods so that importing this module — and running
the test suite — never pays the cost of loading torch or downloading a model.

Typical use::

    indexer = ResumeIndexer()
    indexer.index_resume("data/uploads/resume.pdf")
    indexer.index_projects([{"name": "CareerPilot", "technologies": ["FastAPI"]}])
    indexer.index_achievements("- Cut build times by 40%")
    hits = indexer.search_skills("vector databases")
    prompt_context = indexer.get_full_context()
"""

import hashlib
import re
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union
from xml.etree import ElementTree

from config import settings
from models.career_models import ResumeProfile, SearchResult
from utils.error_handling import RAGIndexingError
from utils.logger import get_logger
from utils.performance_monitor import monitor_performance
from utils.skills import find_skills

logger = get_logger(__name__)

#: Extensions this module knows how to read text out of.
SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}")
_YEARS_RE = re.compile(r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)\b", re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*(?:[-*\u2022\u25cf\u25aa]|\d+[.)])\s*")


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class IndexerError(RAGIndexingError):
    """Base class for every error raised by the indexer."""


class FileValidationError(IndexerError):
    """The supplied file is missing, empty, too large or an unsupported type."""


class DocumentParseError(IndexerError):
    """The file exists but its text could not be read."""


# --------------------------------------------------------------------------- #
# Taxonomy
# --------------------------------------------------------------------------- #
class ContentType(str, Enum):
    RESUME = "resume"
    PROJECT = "project"
    ACHIEVEMENT = "achievement"
    PROFILE = "profile"


class Section(str, Enum):
    SUMMARY = "summary"
    SKILLS = "skills"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    PROJECTS = "projects"
    ACHIEVEMENTS = "achievements"
    OTHER = "other"


#: Sections consulted by :meth:`ResumeIndexer.search_skills`.
SKILL_SECTIONS = [Section.SKILLS.value, Section.PROJECTS.value, Section.SUMMARY.value]
#: Sections consulted by :meth:`ResumeIndexer.search_experience`.
EXPERIENCE_SECTIONS = [
    Section.EXPERIENCE.value,
    Section.PROJECTS.value,
    Section.ACHIEVEMENTS.value,
    Section.SUMMARY.value,
]

_SECTION_HEADINGS: Sequence[Tuple[Section, str]] = (
    (
        Section.SKILLS,
        r"^(technical\s+|core\s+|key\s+)?(skills|technologies|tech\s+stack|competencies|expertise)\b",
    ),
    (
        Section.EXPERIENCE,
        r"^(work\s+|professional\s+|employment\s+|relevant\s+)?(experience|history)\b",
    ),
    (Section.EDUCATION, r"^(education|academic|qualifications)\b"),
    (Section.PROJECTS, r"^(projects|portfolio|selected\s+work)\b"),
    (Section.ACHIEVEMENTS, r"^(achievements|accomplishments|awards|honors|certifications)\b"),
    (Section.SUMMARY, r"^(summary|profile|objective|about\s+me|about)\b"),
)


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #
#: Word wraps every run of text in ``<w:t>`` and every paragraph in ``<w:p>``,
#: both in this namespace. Matching on the tag name alone would also pick up
#: identically-named elements from other parts of the document.
_DOCX_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

#: A .docx is a zip. An archive that expands to far more than a resume ever
#: could is a zip bomb, and unpacking it would be the whole attack. Ten
#: megabytes of uncompressed XML is already an implausibly large CV.
_DOCX_MAX_UNCOMPRESSED = 10 * 1024 * 1024

_DOCTYPE_RE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)


def _extract_docx(path: Path) -> str:
    """Read the visible text out of a .docx.

    Done with the standard library rather than ``python-docx``. The library
    would be one more dependency to pin, and this project has already had one
    SDK break nine tests by dragging in an incompatible httpx; reading the
    zip directly is about thirty lines and cannot conflict with anything.

    Only ``word/document.xml`` is read, so headers, footers, comments and
    tracked-change history are ignored. That is deliberate: a recruiter reads
    the body of the document, and a resume whose skills are hidden in a
    comment is not one this app should pretend to have understood.
    """
    import zipfile

    try:
        with zipfile.ZipFile(path) as archive:
            try:
                info = archive.getinfo("word/document.xml")
            except KeyError:
                raise DocumentParseError(
                    "%s is a zip file but not a Word document." % path.name
                ) from None
            if info.file_size > _DOCX_MAX_UNCOMPRESSED:
                raise DocumentParseError(
                    "%s expands to %d MB, which is too large to be a resume."
                    % (path.name, info.file_size // (1024 * 1024))
                )
            raw = archive.read("word/document.xml")
    except DocumentParseError:
        raise
    except zipfile.BadZipFile as exc:
        # The usual cause is a .doc renamed to .docx. Saying so is more use
        # than "could not parse".
        raise DocumentParseError(
            "%s is not a valid .docx. If it is an older .doc file, open it in "
            "Word and save it as .docx or PDF." % path.name
        ) from exc
    except OSError as exc:
        raise DocumentParseError("Could not read %s: %s" % (path.name, exc)) from exc

    # Same reasoning as the feed parser: ElementTree expands internal
    # entities, so a document declaring a DTD can take the process down with
    # a few hundred bytes. Word never emits one.
    if _DOCTYPE_RE.search(raw[:4096]):
        raise DocumentParseError(
            "%s declares a DTD, which Word does not produce. Refusing to parse it."
            % path.name
        )

    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise DocumentParseError(
            "%s contains malformed XML: %s" % (path.name, exc)
        ) from exc

    # One line per paragraph. The section splitter and the bullet splitter
    # both work on line boundaries, so joining everything into one blob would
    # cost every downstream heading and bullet.
    lines: List[str] = []
    for paragraph in root.iter(_DOCX_NS + "p"):
        parts = [node.text or "" for node in paragraph.iter(_DOCX_NS + "t")]
        lines.append("".join(parts).strip())

    text = "\n".join(lines)
    if not text.strip():
        raise DocumentParseError(
            "%s has no readable text. If the content is inside images, export "
            "it as a PDF with selectable text." % path.name
        )
    return text


def extract_text(file_path: Union[str, Path]) -> str:
    """Read text out of a PDF, Word, Markdown or plain-text file.

    Raises:
        DocumentParseError: the file could not be decoded or the PDF is broken.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".docx":
        return _extract_docx(path)

    if suffix != ".pdf":
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            raise DocumentParseError(f"Could not read {path.name}: {exc}") from exc

    from PyPDF2 import PdfReader
    from PyPDF2.errors import PdfReadError

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            # An empty password unlocks many "protected" PDFs. If it does not,
            # decrypt() returns 0 and page access would fail further down.
            try:
                unlocked = reader.decrypt("")
            except Exception:  # noqa: BLE001 - PyPDF2 raises assorted types here
                unlocked = 0
            if not unlocked:
                raise DocumentParseError(f"{path.name} is password protected.")
        pages = [(page.extract_text() or "") for page in reader.pages]
    except DocumentParseError:
        raise
    except PdfReadError as exc:
        raise DocumentParseError(f"{path.name} is not a readable PDF: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - PyPDF2 is loose about exception types
        raise DocumentParseError(f"Failed to parse {path.name}: {exc}") from exc

    return "\n".join(pages)


#: Sentence enders, and newlines -- resumes are bullet lists far more often
#: than they are prose, so a line break is as real a boundary as a full stop.
_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")


def _hard_split(word: str, limit: int, overlap: int) -> Iterator[str]:
    """Last resort for a single token longer than a whole chunk, e.g. a URL.

    There is no boundary left to respect here, so this is the original
    character-window behaviour, overlap included -- text with no sentences or
    spaces still benefits from windows that share their edges.
    """
    step = max(limit - overlap, 1)
    for start in range(0, len(word), step):
        yield word[start : start + limit]


def _atoms(text: str, limit: int, overlap: int) -> Iterator[str]:
    """Break `text` into the largest pieces that never exceed `limit`.

    Sentences first; a sentence too long for a chunk falls back to word
    boundaries, and a single word too long for a chunk is cut by character
    because at that point there is no boundary left to respect.
    """
    for piece in _BOUNDARY.split(text):
        piece = piece.strip()
        if not piece:
            continue
        if len(piece) <= limit:
            yield piece
            continue

        current = ""
        for word in piece.split():
            if len(word) > limit:
                if current:
                    yield current
                    current = ""
                yield from _hard_split(word, limit, overlap)
                continue
            candidate = f"{current} {word}" if current else word
            if len(candidate) > limit:
                yield current
                current = word
            else:
                current = candidate
        if current:
            yield current


def _carry(atoms: List[str], overlap: int) -> List[str]:
    """The trailing atoms of a finished chunk that fit inside `overlap`."""
    if overlap <= 0:
        return []
    carried: List[str] = []
    length = 0
    for atom in reversed(atoms):
        addition = len(atom) + (1 if carried else 0)
        if length + addition > overlap:
            break
        carried.insert(0, atom)
        length += addition
    return carried


def chunk_text(
    text: str,
    chunk_size: Optional[int] = None,
    overlap: Optional[int] = None,
) -> List[str]:
    """Split `text` into overlapping chunks that end on a real boundary.

    Chunking on a fixed character count used to cut words in half, so
    "LangChain implementation" could be indexed as "LangCha" + "in
    implementation" -- neither of which embeds anywhere near the meaning of the
    original, and neither of which a search for "LangChain" can find.

    Sentences are packed until the next one would overflow `chunk_size`; the
    tail of each chunk is repeated at the head of the next, up to `overlap`
    characters, so a fact spanning a boundary survives in one piece somewhere.
    """
    chunk_size = settings.CHUNK_SIZE if chunk_size is None else chunk_size
    overlap = settings.CHUNK_OVERLAP if overlap is None else overlap
    chunk_size = max(int(chunk_size), 1)
    overlap = min(max(int(overlap), 0), chunk_size - 1)

    if not text or not text.strip():
        return []

    chunks: List[str] = []
    current: List[str] = []
    length = 0

    for atom in _atoms(text, chunk_size, overlap):
        addition = len(atom) + (1 if current else 0)
        if current and length + addition > chunk_size:
            chunks.append(" ".join(current))
            current = _carry(current, overlap)
            length = len(" ".join(current))
            # The carried tail must not crowd out the atom it exists to
            # precede, so it is dropped rather than allowed to overflow.
            if current and length + len(atom) + 1 > chunk_size:
                current = []
                length = 0
            addition = len(atom) + (1 if current else 0)
        current.append(atom)
        length += addition

    if current:
        chunks.append(" ".join(current))
    return chunks


def detect_section(line: str) -> Optional[Section]:
    """Return the section a heading line introduces, or None if it is body text.

    ``=`` is stripped along with the other decoration because banner headings
    (``=== EXPERIENCE ===``) are common in plain-text resumes -- and because
    :meth:`ResumeIndexer.get_full_context` writes them itself. Without this the
    reconstructed resume parsed as one undifferentiated block, and every agent
    that works section by section quietly returned nothing.
    """
    candidate = line.strip().strip(":#*-=\u2013\u2014 ").lower()
    if not candidate or len(candidate) > 45:
        return None
    for section, pattern in _SECTION_HEADINGS:
        if re.match(pattern, candidate):
            return section
    return None


def split_into_sections(text: str) -> List[Tuple[Section, str]]:
    """Group resume lines under the heading that precedes them.

    Lines appearing before any recognised heading are filed under
    ``Section.OTHER`` so nothing is silently dropped.
    """
    buckets: Dict[Section, List[str]] = {}
    order: List[Section] = []
    current = Section.OTHER

    for line in text.splitlines():
        section = detect_section(line)
        if section is not None:
            current = section
            continue
        if not line.strip():
            continue
        if current not in buckets:
            buckets[current] = []
            order.append(current)
        buckets[current].append(line.rstrip())

    return [(section, "\n".join(buckets[section])) for section in order if buckets.get(section)]


def extract_profile(text: str) -> ResumeProfile:
    """Pull name, contact details, years of experience and skills out of a resume."""
    email_match = _EMAIL_RE.search(text)
    phone_match = _PHONE_RE.search(text)

    years = [float(value) for value in _YEARS_RE.findall(text)]
    experience_years = max(years) if years else None

    name = None
    for line in text.splitlines()[:8]:
        candidate = line.strip()
        if not candidate or len(candidate) > 60:
            continue
        if any(ch.isdigit() for ch in candidate) or "@" in candidate:
            continue
        words = candidate.split()
        # A name is 2-4 capitalised words. Requiring every word to be
        # capitalised keeps sentence fragments like "Built things" out.
        if 2 <= len(words) <= 4 and all(word[0].isupper() for word in words):
            name = candidate
            break

    return ResumeProfile(
        name=name,
        email=email_match.group(0) if email_match else None,
        phone=phone_match.group(0).strip() if phone_match else None,
        experience_years=experience_years,
        skills=find_skills(text),
    )


def split_bullets(text: str) -> List[str]:
    """Split a block of achievements into one entry per bullet or line."""
    entries: List[str] = []
    for raw_line in text.splitlines():
        line = _BULLET_RE.sub("", raw_line).strip()
        if len(line) >= 3:
            entries.append(line)
    return entries


def new_resume_id() -> str:
    """Return a random 32-character hex identifier."""
    return uuid.uuid4().hex


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Chroma only accepts str/int/float/bool values, and rejects None."""
    cleaned: Dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
        elif isinstance(value, (list, tuple, set)):
            joined = ", ".join(str(item) for item in value)
            if joined:
                cleaned[key] = joined
        else:
            cleaned[key] = str(value)
    return cleaned


# --------------------------------------------------------------------------- #
# Embeddings
# --------------------------------------------------------------------------- #
class SentenceTransformerEmbedder:
    """Thin wrapper around sentence-transformers with lazy model loading.

    Anything exposing ``encode(texts) -> sequence of vectors`` can be swapped in,
    which is what the test suite does to avoid downloading a model.
    """

    def __init__(self, model_name: Optional[str] = None) -> None:
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    logger.info("Loading embedding model '%s'", self.model_name)
                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(self.model_name)
                    logger.info("Embedding model ready")
        return self._model

    def encode(self, texts: Sequence[str]) -> List[List[float]]:
        vectors = self._load().encode(
            list(texts),
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [[float(value) for value in vector] for vector in vectors]


# --------------------------------------------------------------------------- #
# Indexer
# --------------------------------------------------------------------------- #
class ResumeIndexer:
    """Stores resume, project and achievement text in a Chroma vector index.

    Args:
        collection_name: Chroma collection to use. Defaults to the configured one.
        persist_path: Directory for the on-disk database.
        embedding_model: Name of the sentence-transformers model.
        embedder: Pre-built embedder to inject instead of the default one.
        persist: Set to ``False`` for an ephemeral, in-memory index.
    """

    def __init__(
        self,
        collection_name: Optional[str] = None,
        persist_path: Optional[Union[str, Path]] = None,
        embedding_model: Optional[str] = None,
        embedder: Optional[Any] = None,
        persist: bool = True,
    ) -> None:
        self.collection_name = collection_name or settings.CHROMA_COLLECTION_NAME
        self._persist_path = Path(persist_path) if persist_path else None
        self._persist = persist
        self._embedder = embedder or SentenceTransformerEmbedder(embedding_model)
        self._client = None
        self._collection = None
        self._lock = threading.Lock()

    # -- lazy resources ----------------------------------------------------
    @property
    def _db_path(self) -> Path:
        return self._persist_path or settings.CHROMA_DB_PATH

    def _get_collection(self):
        if self._collection is None:
            with self._lock:
                if self._collection is None:
                    import chromadb
                    from chromadb.config import Settings as ChromaSettings

                    # Telemetry off: it ships usage data off the machine, and
                    # chromadb 0.4.24 logs an error on every call against
                    # modern posthog releases.
                    chroma_settings = ChromaSettings(anonymized_telemetry=False)

                    if self._persist:
                        path = self._db_path
                        path.mkdir(parents=True, exist_ok=True)
                        logger.info("Opening Chroma index at %s", path)
                        self._client = chromadb.PersistentClient(
                            path=str(path), settings=chroma_settings
                        )
                    else:
                        logger.info("Opening in-memory Chroma index")
                        self._client = chromadb.EphemeralClient(settings=chroma_settings)

                    self._collection = self._client.get_or_create_collection(
                        name=self.collection_name,
                        metadata={"hnsw:space": settings.CHROMA_DISTANCE},
                    )
        return self._collection

    def _embed(self, texts: Sequence[str]) -> List[List[float]]:
        """Embed every text in one call.

        The single call is the optimisation: sentence-transformers batches
        internally (default batch size 32) and the per-call overhead dominates
        for short chunks. Measured on 64 resume-sized chunks: one call per chunk
        550.3 ms, one call for the list 28.6 ms - **19.2x**. Passing
        ``batch_size=32`` explicitly would change nothing, since that is already
        the default; the win is in not looping out here.
        """
        return [list(vector) for vector in self._embedder.encode(list(texts))]

    @staticmethod
    def _content_sha(text: str) -> str:
        """A stable fingerprint of a chunk's text.

        Deliberately not the builtin ``hash()``: string hashing is randomised
        per process (PEP 456), so fingerprints recorded by one run never match
        the next one's. A dedup built on ``hash()`` silently does nothing after
        a restart, which is the failure mode that let the duplicates below
        accumulate in the first place.
        """
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _existing_by_sha(self, shas: Sequence[str]) -> Dict[str, str]:
        """Map content fingerprint -> the chunk id already holding that text."""
        if not shas:
            return {}
        try:
            raw = self._get_collection().get(
                where={"content_sha": {"$in": list(dict.fromkeys(shas))}},
                include=["metadatas"],
            )
        except Exception as exc:  # older Chroma, or no such metadata field yet
            logger.debug("Duplicate lookup unavailable (%s); indexing all chunks", exc)
            return {}
        found: Dict[str, str] = {}
        for identifier, metadata in zip(raw.get("ids") or [], raw.get("metadatas") or []):
            sha = (metadata or {}).get("content_sha")
            if sha and sha not in found:
                found[sha] = identifier
        return found

    # -- writes ------------------------------------------------------------
    def _add_chunks(
        self,
        chunks: Sequence[str],
        content_type: ContentType,
        section: Section,
        source: str,
        document_id: str,
        extra_metadata: Optional[Dict[str, Any]] = None,
        start_index: int = 0,
    ) -> List[str]:
        """Embed and store `chunks`, returning the chunk id backing each one.

        Text already present in the collection is **not** stored again. Before
        this, uploading the same resume three times stored it three times: the
        collection held 27 rows of which only 9 were distinct, because each
        upload gets a fresh generated filename and nothing compared content.

        The cost was not only space. Every duplicate is embedded again on the
        way in, and scanned and ranked again on the way out - and because
        duplicates score identically, they crowd the result list. A `top_k=5`
        search on that collection returned 5 rows carrying **2** distinct facts,
        measured identically across three unrelated queries. The match
        calculator asked for five pieces of evidence and could only ever see
        two.

        Chunks that already exist are reported at their existing id, so the
        returned list still has one entry per input chunk and callers counting
        chunks see the same numbers as before.
        """
        if not chunks:
            return []

        shas = [self._content_sha(chunk) for chunk in chunks]
        existing = self._existing_by_sha(shas)

        chunk_ids: List[str] = []
        new_chunks: List[str] = []
        new_ids: List[str] = []
        new_metadatas: List[Dict[str, Any]] = []

        for offset, chunk in enumerate(chunks):
            sha = shas[offset]
            already = existing.get(sha)
            if already is not None:
                chunk_ids.append(already)
                continue
            identifier = f"{document_id}:{start_index + offset}"
            metadata = {
                "source": source,
                "chunk_id": identifier,
                "type": content_type.value,
                "section": section.value,
                "chunk_index": start_index + offset,
                "document_id": document_id,
                "content_sha": sha,
                "indexed_at": _now(),
            }
            metadata.update(extra_metadata or {})
            chunk_ids.append(identifier)
            new_ids.append(identifier)
            new_chunks.append(chunk)
            new_metadatas.append(_clean_metadata(metadata))
            # Guards against a chunk repeated inside this same batch.
            existing[sha] = identifier

        if new_chunks:
            self._get_collection().add(
                ids=new_ids,
                documents=new_chunks,
                embeddings=self._embed(new_chunks),
                metadatas=new_metadatas,
            )
        reused = len(chunks) - len(new_chunks)
        if reused:
            logger.info(
                "Reused %d already-indexed chunk(s); embedded %d new",
                reused,
                len(new_chunks),
            )
        return chunk_ids

    def _validate_file(self, file_path: Union[str, Path]) -> Path:
        path = Path(file_path).expanduser()

        if not path.exists():
            raise FileValidationError(f"File not found: {path}")
        if not path.is_file():
            raise FileValidationError(f"Not a file: {path}")

        extension = path.suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise FileValidationError(
                "Unsupported file type '{}'. Supported: {}".format(
                    extension or "none", sorted(SUPPORTED_EXTENSIONS)
                )
            )

        size = path.stat().st_size
        if size == 0:
            raise FileValidationError(f"File is empty: {path.name}")
        if size > settings.max_upload_size_bytes:
            raise FileValidationError(
                f"{path.name} is {size / 1_048_576:.1f} MB, over the "
                f"{settings.MAX_UPLOAD_SIZE_MB} MB limit."
            )
        return path

    @monitor_performance("rag.index_resume")
    def index_resume(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """Parse, chunk and index a resume file.

        Returns:
            A summary dict with the document id, chunk counts per section and
            the profile metadata that was extracted.

        Raises:
            FileValidationError: file is missing, empty, too big or unsupported.
            DocumentParseError: the file could not be parsed.
        """
        path = self._validate_file(file_path)
        logger.info("Indexing resume %s", path.name)

        text = extract_text(path)
        if not text.strip():
            logger.warning("No extractable text in %s (scanned image PDF?)", path.name)
            return {
                "status": "empty",
                "type": ContentType.RESUME.value,
                "source": path.name,
                "document_id": None,
                "chunks_indexed": 0,
                "documents_indexed": 0,
                "profile_indexed": False,
                "characters": 0,
                "sections": {},
                "profile": ResumeProfile().model_dump(),
                "indexed_at": _now(),
                "message": "No text could be extracted from the document.",
            }

        document_id = f"resume-{new_resume_id()[:12]}"
        profile = extract_profile(text)
        sections = split_into_sections(text)

        section_counts: Dict[str, int] = {}
        written = 0
        newly_stored = 0
        for section, section_text in sections:
            chunks = chunk_text(section_text)
            if not chunks:
                continue
            ids = self._add_chunks(
                chunks=chunks,
                content_type=ContentType.RESUME,
                section=section,
                source=path.name,
                document_id=document_id,
                extra_metadata={"name": profile.name},
                start_index=written,
            )
            # Reused chunks come back under the id of the document that already
            # held that text, so anything carrying this document's prefix is new.
            newly_stored += sum(1 for i in ids if i.startswith(document_id + ":"))
            section_counts[section.value] = section_counts.get(section.value, 0) + len(chunks)
            written += len(chunks)

        profile_records = 1 if self._add_profile_record(document_id, path.name, profile) else 0

        logger.info(
            "Indexed %s: %d chunks across %d sections (%d characters)",
            path.name,
            written,
            len(section_counts),
            len(text),
        )
        return {
            "status": "indexed",
            "type": ContentType.RESUME.value,
            "source": path.name,
            "document_id": document_id,
            "chunks_indexed": written,
            # How many of those chunks were actually embedded and stored. The
            # rest were already present, byte for byte, under another upload.
            # Reporting only `chunks_indexed` after adding de-duplication would
            # claim seven chunks were written when nothing was - the same kind
            # of unreconcilable number that `documents_indexed` below exists to
            # avoid.
            "chunks_written": newly_stored,
            "chunks_reused": written - newly_stored,
            # The profile summary is a record in the collection but not a chunk
            # of the resume, so the two counts legitimately differ. Both are
            # reported because `chunks_indexed` alone did not reconcile with
            # `count()`, which looked like an off-by-one error and prompted a
            # hunt for a bug that was not there.
            "documents_indexed": written + profile_records,
            "profile_indexed": bool(profile_records),
            "characters": len(text),
            "sections": section_counts,
            "profile": profile.model_dump(),
            "indexed_at": _now(),
        }

    def _add_profile_record(self, document_id: str, source: str, profile: ResumeProfile) -> bool:
        """Store the extracted profile as its own retrievable document.

        Returns whether a record was written, so the caller can report a count
        that reconciles with the size of the collection.
        """
        lines = []
        if profile.name:
            lines.append(f"Name: {profile.name}")
        if profile.email:
            lines.append(f"Email: {profile.email}")
        if profile.experience_years is not None:
            lines.append(f"Years of experience: {profile.experience_years:g}")
        if profile.skills:
            lines.append(f"Skills: {', '.join(profile.skills)}")

        if not lines:
            logger.info("No profile details found in %s; skipping profile record", source)
            return False

        self._add_chunks(
            chunks=["\n".join(lines)],
            content_type=ContentType.PROFILE,
            section=Section.SUMMARY,
            source=source,
            document_id=f"{document_id}-profile",
            extra_metadata={
                "name": profile.name,
                "email": profile.email,
                "phone": profile.phone,
                "experience_years": profile.experience_years,
                "skills": profile.skills,
            },
        )
        return True

    def index_projects(self, projects_list: Sequence[Any]) -> Dict[str, Any]:
        """Index a list of projects.

        Each entry may be a plain string, or a dict with any of the keys
        ``name``, ``description``, ``technologies``, ``role``, ``impact``, ``url``.
        """
        if not projects_list:
            logger.warning("index_projects called with an empty list")
            return {
                "status": "empty",
                "type": ContentType.PROJECT.value,
                "projects_indexed": 0,
                "project_names": [],
                "chunks_indexed": 0,
                "indexed_at": _now(),
                "message": "No projects supplied.",
            }

        total_chunks = 0
        indexed_names: List[str] = []

        for position, entry in enumerate(projects_list):
            name, body, technologies = _normalise_project(entry, position)
            if not body.strip():
                logger.warning("Skipping project '%s': no description text", name)
                continue

            document_id = f"project-{new_resume_id()[:12]}"
            chunks = chunk_text(body)
            self._add_chunks(
                chunks=chunks,
                content_type=ContentType.PROJECT,
                section=Section.PROJECTS,
                source=name,
                document_id=document_id,
                extra_metadata={"project_name": name, "technologies": technologies},
            )
            total_chunks += len(chunks)
            indexed_names.append(name)

        logger.info("Indexed %d projects into %d chunks", len(indexed_names), total_chunks)
        return {
            "status": "indexed" if indexed_names else "empty",
            "type": ContentType.PROJECT.value,
            "projects_indexed": len(indexed_names),
            "project_names": indexed_names,
            "chunks_indexed": total_chunks,
            "indexed_at": _now(),
        }

    def index_achievements(self, achievements_text: str) -> Dict[str, Any]:
        """Index a block of achievements, one document per bullet or line."""
        entries = split_bullets(achievements_text) if achievements_text else []
        if not entries:
            logger.warning("index_achievements found nothing to index")
            return {
                "status": "empty",
                "type": ContentType.ACHIEVEMENT.value,
                "achievements_indexed": 0,
                "chunks_indexed": 0,
                "indexed_at": _now(),
                "message": "No achievement entries could be parsed.",
            }

        total_chunks = 0
        for entry in entries:
            document_id = f"achievement-{new_resume_id()[:12]}"
            chunks = chunk_text(entry)
            self._add_chunks(
                chunks=chunks,
                content_type=ContentType.ACHIEVEMENT,
                section=Section.ACHIEVEMENTS,
                source="achievements",
                document_id=document_id,
                extra_metadata={"skills": find_skills(entry)},
            )
            total_chunks += len(chunks)

        logger.info("Indexed %d achievements into %d chunks", len(entries), total_chunks)
        return {
            "status": "indexed",
            "type": ContentType.ACHIEVEMENT.value,
            "achievements_indexed": len(entries),
            "chunks_indexed": total_chunks,
            "indexed_at": _now(),
        }

    # -- reads -------------------------------------------------------------
    def count(self) -> int:
        """Number of chunks currently stored."""
        try:
            return self._get_collection().count()
        except Exception:  # noqa: BLE001 - a broken index should not crash callers
            logger.exception("Could not count collection '%s'", self.collection_name)
            return 0

    def is_empty(self) -> bool:
        """True when nothing is indexed, so callers can say so rather than guess."""
        return self.count() == 0

    @monitor_performance("rag.search")
    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        content_types: Optional[Iterable[str]] = None,
        sections: Optional[Iterable[str]] = None,
        technology: Optional[str] = None,
        fallback_to_all: bool = True,
    ) -> List[SearchResult]:
        """Semantic search over the index.

        Args:
            query: Natural-language question.
            top_k: Maximum hits to return. Defaults to ``settings.TOP_K_RESULTS``.
            content_types: Restrict to these ``ContentType`` values.
            sections: Restrict to these ``Section`` values.
            technology: Keep only hits mentioning this technology.
            fallback_to_all: Retry without filters when the filtered search is empty.
                Resumes without recognisable headings land in ``other``, so
                without this a section-filtered search would return nothing.

        Returns:
            Hits ordered best-first, each carrying a 0-1 similarity score.
            An empty list if the index is empty or nothing matched.
        """
        if not query or not query.strip():
            logger.warning("Empty search query; returning no results")
            return []

        top_k = settings.TOP_K_RESULTS if top_k is None else top_k
        if top_k <= 0:
            return []

        if self.is_empty():
            logger.warning("Search for %r ran against an empty index", query)
            return []

        where = _build_where(content_types, sections)
        results = self._query(query, top_k, where)

        if not results and where and fallback_to_all:
            logger.info("Filtered search for %r found nothing; retrying unfiltered", query)
            results = self._query(query, top_k, None)

        if technology:
            needle = technology.lower()
            results = [hit for hit in results if _mentions(hit, needle)]

        logger.info("Search %r returned %d hits", query, len(results))
        return results

    def _query(
        self, query: str, top_k: int, where: Optional[Dict[str, Any]]
    ) -> List[SearchResult]:
        try:
            raw = self._get_collection().query(
                query_embeddings=self._embed([query]),
                n_results=top_k,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:  # noqa: BLE001 - a store error must not become a 500
            logger.exception("Chroma query failed for %r", query)
            return []
        return _to_search_results(raw)

    def search_skills(self, query: str, top_k: int = 5) -> List[SearchResult]:
        """Find evidence of skills and technologies across the indexed data."""
        return self.search(query, top_k=top_k, sections=SKILL_SECTIONS)

    def search_experience(self, query: str, top_k: int = 5) -> List[SearchResult]:
        """Find work history, project and achievement evidence for a query."""
        return self.search(query, top_k=top_k, sections=EXPERIENCE_SECTIONS)

    def search_by_technology(self, technology: str, top_k: int = 5) -> List[SearchResult]:
        """Find chunks that explicitly mention a specific technology."""
        return self.search(technology, top_k=top_k, technology=technology)

    def get_profile(self) -> ResumeProfile:
        """Return the most recently indexed profile record, if there is one."""
        records = self._get_all(where={"type": ContentType.PROFILE.value})
        if not records:
            logger.info("No profile record in the index")
            return ResumeProfile()

        metadata = max(records, key=lambda item: str(item[1].get("indexed_at", "")))[1]
        skills = [s.strip() for s in str(metadata.get("skills", "")).split(",") if s.strip()]
        years = metadata.get("experience_years")
        return ResumeProfile(
            name=metadata.get("name"),
            email=metadata.get("email"),
            phone=metadata.get("phone"),
            experience_years=float(years) if years is not None else None,
            skills=skills,
        )

    def _get_all(
        self, where: Optional[Dict[str, Any]] = None
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """Return every (document, metadata) pair, optionally filtered."""
        try:
            raw = self._get_collection().get(where=where, include=["documents", "metadatas"])
        except Exception:  # noqa: BLE001
            logger.exception("Could not read collection '%s'", self.collection_name)
            return []

        documents = raw.get("documents") or []
        metadatas = raw.get("metadatas") or []
        return [
            (documents[i], dict(metadatas[i] or {}))
            for i in range(min(len(documents), len(metadatas)))
        ]

    def get_full_context(self) -> str:
        """Render everything in the index as a readable block of text.

        Intended to be dropped straight into an LLM prompt.
        """
        records = self._get_all()
        if not records:
            logger.warning("get_full_context called on an empty index")
            return "No resume data has been indexed yet."

        profile_blocks: List[str] = []
        grouped: Dict[str, List[Tuple[int, str]]] = {}

        for document, metadata in records:
            content_type = str(metadata.get("type", ContentType.RESUME.value))
            if content_type == ContentType.PROFILE.value:
                profile_blocks.append(document)
                continue
            heading = _context_heading(content_type, metadata)
            grouped.setdefault(heading, []).append(
                (int(metadata.get("chunk_index", 0)), document)
            )

        blocks: List[str] = []
        if profile_blocks:
            blocks.append("=== CANDIDATE PROFILE ===\n" + "\n".join(sorted(profile_blocks)))
        for heading in sorted(grouped):
            body = "\n".join(text for _, text in sorted(grouped[heading], key=lambda p: p[0]))
            blocks.append(f"=== {heading.upper()} ===\n{body}")

        context = "\n\n".join(blocks)
        logger.info("Built context of %d characters from %d chunks", len(context), len(records))
        return context

    # -- maintenance -------------------------------------------------------
    def clear_index(self) -> None:
        """Delete every stored chunk. Safe to call on an empty or absent index."""
        removed = 0
        try:
            collection = self._get_collection()
            removed = collection.count()
            self._client.delete_collection(name=self.collection_name)
        except Exception:  # noqa: BLE001 - deleting a missing collection is fine
            logger.exception("Could not delete collection '%s'", self.collection_name)

        with self._lock:
            self._collection = None
        logger.info("Cleared index '%s' (%d chunks removed)", self.collection_name, removed)

    def stats(self) -> Dict[str, Any]:
        """Counts per content type and section, for health checks and debugging."""
        records = self._get_all()
        by_type: Dict[str, int] = {}
        by_section: Dict[str, int] = {}
        sources = set()

        for _, metadata in records:
            content_type = str(metadata.get("type", "unknown"))
            section = str(metadata.get("section", "unknown"))
            by_type[content_type] = by_type.get(content_type, 0) + 1
            by_section[section] = by_section.get(section, 0) + 1
            if metadata.get("source"):
                sources.add(str(metadata["source"]))

        return {
            "collection": self.collection_name,
            "total_chunks": len(records),
            "by_type": by_type,
            "by_section": by_section,
            "sources": sorted(sources),
            "empty": not records,
        }


# --------------------------------------------------------------------------- #
# Module-level helpers
# --------------------------------------------------------------------------- #
def _normalise_project(entry: Any, position: int) -> Tuple[str, str, List[str]]:
    """Turn a project entry (string or dict) into (name, text, technologies)."""
    if isinstance(entry, dict):
        name = str(entry.get("name") or entry.get("title") or f"Project {position + 1}")
        technologies = entry.get("technologies") or entry.get("tech") or []
        if isinstance(technologies, str):
            technologies = [t.strip() for t in technologies.split(",") if t.strip()]
        technologies = [str(t) for t in technologies]

        parts = [f"Project: {name}"]
        for key in ("role", "description", "impact", "url"):
            value = entry.get(key)
            if value:
                parts.append(f"{key.capitalize()}: {value}")
        if technologies:
            parts.append(f"Technologies: {', '.join(technologies)}")
        return name, "\n".join(parts), technologies

    text = str(entry).strip()
    name = text.split("\n", 1)[0][:60] or f"Project {position + 1}"
    return name, text, find_skills(text)


def _build_where(
    content_types: Optional[Iterable[str]], sections: Optional[Iterable[str]]
) -> Optional[Dict[str, Any]]:
    """Build a Chroma `where` filter from the optional type/section restrictions."""
    clauses: List[Dict[str, Any]] = []
    if content_types:
        values = list(content_types)
        clauses.append({"type": values[0] if len(values) == 1 else {"$in": values}})
    if sections:
        values = list(sections)
        clauses.append({"section": values[0] if len(values) == 1 else {"$in": values}})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _mentions(hit: SearchResult, needle: str) -> bool:
    return (
        needle in hit.text.lower()
        or needle in str(hit.metadata.get("technologies", "")).lower()
        or needle in str(hit.metadata.get("skills", "")).lower()
    )


def _to_similarity(distance: Optional[float]) -> float:
    """Convert a Chroma cosine distance (0 best, 2 worst) into a 0-1 score."""
    if distance is None:
        return 0.0
    return round(max(0.0, min(1.0, 1.0 - float(distance))), 4)


def _to_search_results(raw: Dict[str, Any]) -> List[SearchResult]:
    ids = (raw.get("ids") or [[]])[0]
    documents = (raw.get("documents") or [[]])[0]
    metadatas = (raw.get("metadatas") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]

    results: List[SearchResult] = []
    for i, chunk_id in enumerate(ids):
        metadata = dict(metadatas[i] or {}) if i < len(metadatas) else {}
        results.append(
            SearchResult(
                chunk_id=str(chunk_id),
                text=documents[i] if i < len(documents) else "",
                score=_to_similarity(distances[i] if i < len(distances) else None),
                content_type=str(metadata.get("type", ContentType.RESUME.value)),
                section=str(metadata.get("section", Section.OTHER.value)),
                source=str(metadata.get("source", "")),
                metadata=metadata,
            )
        )
    return results


def _context_heading(content_type: str, metadata: Dict[str, Any]) -> str:
    if content_type == ContentType.PROJECT.value:
        return "project: {}".format(
            metadata.get("project_name") or metadata.get("source") or "unnamed"
        )
    if content_type == ContentType.ACHIEVEMENT.value:
        return "achievements"
    return str(metadata.get("section", Section.OTHER.value))


def format_as_context(results: Sequence[SearchResult]) -> str:
    """Render search hits as a readable block for an LLM prompt."""
    if not results:
        return "No relevant information found in the indexed resume."
    return "\n".join(hit.as_context() for hit in results)


#: One embedding model for the whole process. Each signed-in account gets its
#: own Chroma collection, but they all embed through this: the model is around
#: 90 MB resident and embedding is stateless, so a copy per user would multiply
#: the memory for no behavioural difference.
shared_embedder = SentenceTransformerEmbedder()

#: Shared instance used by the API layer.
resume_indexer = ResumeIndexer(embedder=shared_embedder)
