import re


DEFAULT_TARGET_SIZE = 700
DEFAULT_MAX_SIZE = 1000


def split_sentences(text: str) -> list[str]:
    """
    Split text into sentences while preserving punctuation.
    """

    text = text.strip()

    if not text:
        return []

    # Normalize excessive horizontal whitespace without
    # destroying paragraph breaks.
    text = re.sub(r"[ \t]+", " ", text)

    # Split after normal sentence-ending punctuation.
    parts = re.split(
        r"(?<=[.!?])\s+",
        text
    )

    return [
        part.strip()
        for part in parts
        if part.strip()
    ]


def split_oversized_sentence(
    sentence: str,
    max_size: int
) -> list[str]:
    """
    Last-resort splitter for unusually long sentences.

    Prefer commas/semicolons before falling back to
    whitespace boundaries.
    """

    if len(sentence) <= max_size:
        return [sentence]

    pieces = []
    remaining = sentence.strip()

    while len(remaining) > max_size:

        window = remaining[:max_size + 1]

        # Prefer natural punctuation.
        candidates = [
            window.rfind(", "),
            window.rfind("; "),
            window.rfind(": "),
            window.rfind(" — "),
            window.rfind(" - "),
        ]

        split_at = max(candidates)

        # If there is no useful punctuation,
        # fall back to the last space.
        if split_at < max_size // 2:
            split_at = window.rfind(" ")

        # Extremely unusual case: one enormous token.
        if split_at <= 0:
            split_at = max_size

        piece = remaining[:split_at].strip()

        if piece:
            pieces.append(piece)

        remaining = remaining[split_at:].strip()

    if remaining:
        pieces.append(remaining)

    return pieces


def chunk_text(
    text: str,
    target_size: int = DEFAULT_TARGET_SIZE,
    max_size: int = DEFAULT_MAX_SIZE
) -> list[str]:
    """
    Convert long text into TTS-friendly chunks.

    Goals:
    - preserve complete sentences where possible
    - keep chunks near target_size
    - never exceed max_size except where unavoidable
    """

    if target_size <= 0:
        raise ValueError(
            "target_size must be greater than zero"
        )

    if max_size < target_size:
        raise ValueError(
            "max_size must be >= target_size"
        )

    sentences = split_sentences(text)

    if not sentences:
        return []

    expanded_sentences = []

    for sentence in sentences:
        expanded_sentences.extend(
            split_oversized_sentence(
                sentence,
                max_size
            )
        )

    chunks = []
    current = ""

    for sentence in expanded_sentences:

        if not current:
            current = sentence
            continue

        candidate = f"{current} {sentence}"

        if len(candidate) <= target_size:
            current = candidate
            continue

        chunks.append(current)
        current = sentence

    if current:
        chunks.append(current)

    return chunks
