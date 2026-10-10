from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Sequence

from pypdf import PdfReader


IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_CHUNK_SIZE = 1400
_HEADING_PATTERNS = (
    re.compile(r"^\d{1,2}\.\s+(.+?)\s*$"),
    re.compile(r"^Annexure\s+[A-Z0-9]+(?::\s*.*)?$", re.IGNORECASE),
    re.compile(r"^Scope\.\s*(.*)$", re.IGNORECASE),
    re.compile(r"^Q\.\s*(.+\?)$", re.IGNORECASE),
)
_EMBEDDING_CACHE: dict[tuple[str, str], list[list[float]]] = {}
_CANCELLATION_QUERY = re.compile(r"\b(?:cancel\w*|refund\w*)\b", re.I)


@dataclass(frozen=True)
class PolicyChunk:
    doc_name: str
    version: str
    section_title: str
    page: int
    effective_date: str | None
    text: str
    transcription_note: str | None = None

    def citation(self) -> dict[str, str | int | None]:
        citation = {
            "doc": self.doc_name,
            "version": self.version,
            "section": self.section_title,
            "page": self.page,
            "effective_date": self.effective_date,
        }
        if self.transcription_note:
            citation["transcription_note"] = self.transcription_note
        return citation


_SCANNED_PAGE_TRANSCRIPTS = {
    (
        "03_Cancellation_and_Refund_Policy_v2.pdf",
        2,
    ): (
        "Annexure 1: Approved refund schedule (signed copy)",
        "transcribed from scanned annexure",
        "Applies to bookings made on or after 1 July 2026, 00:00 IST.\n"
        "Cancellation before scheduled pickup | Refund of rental charge\n"
        "48 hours or more | 100%\n"
        "12 hours or more, but less than 48 hours | 75%\n"
        "2 hours or more, but less than 12 hours | 25%\n"
        "Less than 2 hours | No refund (0%)\n"
        "Cancelled by RideWise: 100% refund in all cases.\n"
        "No-show: no refund.",
    ),
    (
        "04_Late_Return_and_Damage_Penalty_Schedule.pdf",
        3,
    ): (
        "Annexure A: Tier benefits",
        "transcribed from scanned annexure",
        "Late return grace period by customer tier\n"
        "Customer tier | Grace period on late return\n"
        "STANDARD | None\n"
        "SILVER | None\n"
        "GOLD | 30 minutes (up to and including 30 min)\n"
        "A GOLD return up to 30 minutes late: no late fee.\n"
        "A GOLD return more than 30 minutes late: the full lateness "
        "is charged from the first minute, as for other tiers.\n"
        "Approved: RideWise Policy Committee, 15 December 2024.",
    ),
    (
        "05_EV_User_Guide_and_FAQ.pdf",
        2,
    ): (
        "Battery level at return (Figure 2)",
        "transcribed from scanned figure",
        "RED (below 10%): ₹150 low-battery charging fee applies.\n"
        "AMBER (10%-19%): no fee, but please charge before your next trip.\n"
        "GREEN (20% and above): ideal return level.\n"
        "Exactly 10% is not below 10%, so no fee is charged.",
    ),
}


def parse_effective_date(text: str) -> str | None:
    """Extract an effective date and optional India-local effective time."""
    match = re.search(
        r"\bEffective(?:\s+date)?\s+"
        r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})"
        r"(?:,\s*(\d{1,2}:\d{2})\s*(IST|UTC)?)?",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    parsed_date = datetime.strptime(match.group(1), "%d %B %Y").date()
    clock = match.group(2)
    if not clock:
        return parsed_date.isoformat()

    parsed_time = datetime.strptime(clock, "%H:%M").time()
    zone = timezone.utc if (match.group(3) or "").upper() == "UTC" else IST
    return datetime.combine(parsed_date, parsed_time, zone).isoformat()


def _version_from_text(text: str) -> str:
    match = re.search(
        r"\b(?:Document\s+[^·\n]+·\s*)?(?:Version|v)\s*([0-9]+(?:\.[0-9]+)*)",
        text,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError("Policy document has no parseable version.")
    return match.group(1)


def _document_title(lines: Sequence[str], fallback: str) -> str:
    for raw_line in lines:
        line = " ".join(raw_line.split())
        if (
            not line
            or re.match(r"^RW-POL-\d+\b", line)
            or line.startswith("RideWise Mobility")
            or re.match(r"^Page\s+\d+\s*$", line, re.IGNORECASE)
            or line.startswith("Document ")
        ):
            continue
        if not re.match(r"^\d{1,2}\.\s+", line):
            return line
    return fallback


def _heading(line: str) -> str | None:
    for pattern in _HEADING_PATTERNS:
        match = pattern.match(line)
        if match:
            if pattern is _HEADING_PATTERNS[0]:
                return match.group(1).strip()
            if pattern is _HEADING_PATTERNS[2]:
                return ("Scope. " + match.group(1)).strip()
            return line.strip()
    return None


def _split_long_text(text: str, limit: int) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for word in words:
        extra = len(word) + (1 if current else 0)
        if current and current_length + extra > limit:
            chunks.append(" ".join(current))
            current = []
            current_length = 0
        current.append(word)
        current_length += len(word) + (1 if len(current) > 1 else 0)
    if current:
        chunks.append(" ".join(current))
    return chunks


def _chunk_section(text: str, limit: int) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result: list[str] = []
    current: list[str] = []
    current_length = 0
    for line in lines:
        if len(line) > limit:
            if current:
                result.append("\n".join(current))
                current = []
                current_length = 0
            result.extend(_split_long_text(line, limit))
            continue

        extra = len(line) + (1 if current else 0)
        if current and current_length + extra > limit:
            result.append("\n".join(current))
            current = []
            current_length = 0
        current.append(line)
        current_length += extra
    if current:
        result.append("\n".join(current))
    return result


def _extract_document(path: Path, chunk_size: int) -> list[PolicyChunk]:
    reader = PdfReader(str(path))
    if not reader.pages:
        raise ValueError(f"Policy PDF is empty: {path.name}")

    page_texts = [page.extract_text() or "" for page in reader.pages]
    header_text = "\n".join(page_texts[:2])
    version = _version_from_text(header_text)
    effective_date = parse_effective_date(header_text)
    first_lines = page_texts[0].splitlines()
    current_section = _document_title(first_lines, path.stem)
    chunks: list[PolicyChunk] = []

    for page_number, page_text in enumerate(page_texts, start=1):
        grouped: dict[str, list[str]] = {}
        active_title = current_section
        for raw_line in page_text.splitlines():
            line = " ".join(raw_line.split())
            if (
                not line
                or re.match(r"^RW-POL-\d+\b", line)
                or line.startswith("RideWise Mobility")
                or re.match(r"^Page\s+\d+\s*$", line, re.IGNORECASE)
                or line.startswith("Document ")
            ):
                continue

            section_title = _heading(line)
            if section_title:
                active_title = section_title
            grouped.setdefault(active_title, []).append(line)
        current_section = active_title

        for section_title, lines in grouped.items():
            section_text = "\n".join(lines)
            for chunk_text in _chunk_section(section_text, chunk_size):
                chunks.append(
                    PolicyChunk(
                        doc_name=path.name,
                        version=version,
                        section_title=section_title,
                        page=page_number,
                        effective_date=effective_date,
                        text=chunk_text,
                    )
                )
    return chunks


def load_policy_chunks(
    data_dir: str | Path | None = None,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> list[PolicyChunk]:
    """Extract section/page-aware chunks from the five numbered policy PDFs."""
    if chunk_size < 100:
        raise ValueError("chunk_size must be at least 100 characters.")
    directory = (
        Path(data_dir)
        if data_dir is not None
        else Path(__file__).resolve().parents[2] / "data"
    )
    paths = sorted(directory.glob("0[1-5]_*.pdf"))
    if len(paths) != 5:
        raise FileNotFoundError(
            f"Expected exactly five numbered policy PDFs in {directory}, "
            f"found {len(paths)}."
        )
    chunks = [
        chunk
        for path in paths
        for chunk in _extract_document(path, chunk_size)
    ]
    for (doc_name, page), (
        section_title,
        transcription_note,
        text,
    ) in _SCANNED_PAGE_TRANSCRIPTS.items():
        source_chunk = next(
            chunk
            for chunk in chunks
            if chunk.doc_name == doc_name and chunk.page == page
        )
        chunks.append(
            PolicyChunk(
                doc_name=doc_name,
                version=source_chunk.version,
                section_title=section_title,
                page=page,
                effective_date=source_chunk.effective_date,
                text=f"[{transcription_note}]\n{text}",
                transcription_note=transcription_note,
            )
        )
    return chunks


def _effective_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return datetime.combine(parsed.date(), time.min, IST)
    return parsed.astimezone(IST)


def _booking_datetime(value: str | date | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min, IST)
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(IST)


def select_cancellation_version(
    chunks: Sequence[PolicyChunk], booking_date: str | date | datetime
) -> str:
    """Choose cancellation policy version effective when the booking was made."""
    candidates = [
        chunk
        for chunk in chunks
        if "cancellation_and_refund" in chunk.doc_name.casefold()
    ]
    if not candidates:
        raise ValueError("Cancellation policy chunks are not loaded.")

    booking_time = _booking_datetime(booking_date)
    versions = {
        chunk.version: _effective_datetime(chunk.effective_date)
        for chunk in candidates
        if chunk.effective_date is not None
    }
    if not versions:
        raise ValueError("Cancellation policy chunks have no effective dates.")
    applicable = [
        (effective_date, version)
        for version, effective_date in versions.items()
        if effective_date <= booking_time
    ]
    if not applicable:
        raise ValueError("No cancellation policy covers this booking date.")
    return max(applicable)[1]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)


def _bm25(
    query: str, chunks: Sequence[PolicyChunk]
) -> list[tuple[float, PolicyChunk]]:
    tokenized = [_tokens(chunk.text) for chunk in chunks]
    if not tokenized:
        return []
    average_length = sum(map(len, tokenized)) / len(tokenized) or 1.0
    document_frequencies: Counter[str] = Counter()
    counts = [Counter(words) for words in tokenized]
    for counter in counts:
        document_frequencies.update(counter.keys())

    query_terms = set(_tokens(query))
    scored: list[tuple[float, PolicyChunk]] = []
    total_documents = len(chunks)
    for chunk, words, term_counts in zip(chunks, tokenized, counts):
        score = 0.0
        for term in query_terms:
            frequency = term_counts[term]
            if not frequency:
                continue
            document_frequency = document_frequencies[term]
            inverse_frequency = math.log(
                1
                + (total_documents - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            denominator = frequency + 1.5 * (
                1 - 0.75 + 0.75 * len(words) / average_length
            )
            score += inverse_frequency * frequency * 2.5 / denominator
        if score > 0:
            scored.append((score, chunk))
    return sorted(scored, key=lambda item: item[0], reverse=True)


def _corpus_fingerprint(chunks: Sequence[PolicyChunk]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk.doc_name.encode("utf-8"))
        digest.update(chunk.version.encode("utf-8"))
        digest.update(chunk.section_title.encode("utf-8"))
        digest.update(chunk.text.encode("utf-8"))
    return digest.hexdigest()


def _embedding_vectors(
    query: str, chunks: Sequence[PolicyChunk], model: str
) -> list[list[float]]:
    from src.llm.client import create_client

    fingerprint = _corpus_fingerprint(chunks)
    cache_key = (model, fingerprint)
    if cache_key not in _EMBEDDING_CACHE:
        response = create_client().embeddings.create(
            model=model,
            input=[chunk.text for chunk in chunks],
        )
        _EMBEDDING_CACHE[cache_key] = [item.embedding for item in response.data]

    response = create_client().embeddings.create(model=model, input=[query])
    return [response.data[0].embedding, *_EMBEDDING_CACHE[cache_key]]


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def retrieve_policy(
    query: str,
    *,
    chunks: Sequence[PolicyChunk] | None = None,
    booking_date: str | date | datetime | None = None,
    top_k: int = 5,
) -> list[PolicyChunk]:
    """Retrieve policy chunks by embeddings when configured, otherwise BM25.

    Cancellation/refund retrieval requires the booking's creation time to
    select exactly one applicable cancellation-policy version.
    """
    if not query.strip():
        raise ValueError("A non-empty policy query is required.")
    if top_k < 1:
        raise ValueError("top_k must be at least one.")

    policy_chunks = list(chunks) if chunks is not None else load_policy_chunks()
    is_cancellation_question = bool(_CANCELLATION_QUERY.search(query))
    if is_cancellation_question:
        if booking_date is None:
            raise ValueError(
                "A booking date is required to select the cancellation policy version."
            )
        selected_version = select_cancellation_version(policy_chunks, booking_date)
        policy_chunks = [
            chunk
            for chunk in policy_chunks
            if "cancellation_and_refund" not in chunk.doc_name.casefold()
            or chunk.version == selected_version
        ]

    from src.llm.client import get_embedding_model

    embedding_model = get_embedding_model()
    if embedding_model:
        vectors = _embedding_vectors(query, policy_chunks, embedding_model)
        query_vector, document_vectors = vectors[0], vectors[1:]
        if len(document_vectors) != len(policy_chunks):
            raise RuntimeError("Embedding response count did not match policy chunks.")
        ranked = sorted(
            zip(
                (_cosine_similarity(query_vector, vector) for vector in document_vectors),
                policy_chunks,
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        return [chunk for score, chunk in ranked[:top_k] if score > 0]

    return [chunk for score, chunk in _bm25(query, policy_chunks)[:top_k]]
