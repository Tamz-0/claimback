"""
Scoring claimant answers against hidden details.

Answers are compared after normalisation, and allowed to be slightly
different ("nasa sticker" vs "NASA logo sticker"), because real owners rarely
type the exact same words as the finder.

Per-question score (0..1):
    similarity >= 0.80              -> 1.0  (correct)
    0.50 <= similarity < 0.80       -> similarity (partial credit)
    similarity < 0.50               -> 0.0  (wrong)
"""

import re
import unicodedata
from difflib import SequenceMatcher

STOPWORDS = {"a", "an", "the", "of", "on", "in", "with", "and", "it", "is", "its", "my", "there", "some", "has", "was"}
SYNONYMS = {
    "grey": "gray", "colour": "color", "sticker": "sticker", "stickers": "sticker",
    "pic": "picture", "photo": "picture", "wallpaper": "picture", "pink": "pink",
}
CORRECT = 0.80
PARTIAL = 0.50


def normalise(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    tokens = re.findall(r"[a-z0-9]+", text)
    return [SYNONYMS.get(t, t) for t in tokens if t not in STOPWORDS]


def similarity(expected: str, given: str) -> float:
    exp, got = normalise(expected), normalise(given)
    if not exp or not got:
        return 0.0
    if exp == got:
        return 1.0
    seq = SequenceMatcher(None, " ".join(exp), " ".join(got)).ratio()
    exp_set, got_set = set(exp), set(got)
    # Fraction of expected key words the claimant mentioned (fuzzy per word)
    hits = 0
    for word in exp_set:
        if word in got_set or any(SequenceMatcher(None, word, g).ratio() >= 0.85 for g in got_set):
            hits += 1
    recall = hits / len(exp_set)
    # Penalise "shotgun" answers listing many extra words
    precision = hits / max(len(got_set), 1)
    token_score = recall if precision >= 0.3 else recall * 0.6
    return round(max(seq, token_score), 3)


def question_score(expected: str, given: str) -> float:
    s = similarity(expected, given)
    if s >= CORRECT:
        return 1.0
    if s >= PARTIAL:
        return s
    return 0.0


def score_answers(expected: dict, given: dict) -> tuple[float, dict]:
    """expected/given: {detail_id: text}. Returns (overall 0..1, per-question)."""
    per = {str(k): question_score(v, given.get(str(k), "") or given.get(k, "") or "") for k, v in expected.items()}
    overall = sum(per.values()) / len(per) if per else 0.0
    return round(overall, 3), per
