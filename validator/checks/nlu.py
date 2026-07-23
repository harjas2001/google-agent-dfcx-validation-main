"""
nlu.py — Training phrase quality analysis and checks.

Ports the objective half of VOICEBOT_INTENT_ANALYSIS_PLAYBOOK.md (§3 Step 2)
to Dialogflow CX. Everything here is deterministic — the judgement calls the
playbook describes in Step 3 belong to the journey narrative pass, not to a
check that runs in CI.

The module has two layers:

  Analysis   Pure functions returning structured records — collisions, ASR
             hits, phrase stats. Used by both the checks below and the Excel
             workbook, so the two can never disagree.
  Checks     check_nlu() turns those records into Findings.

Rules:
  → Empty training phrases.
  → Within-intent duplicate phrases (wasted, and skew the model).
  → Exact cross-intent duplicates — the same phrase training two intents is a
    direct contradiction in the training data.
  → Near-duplicate cross-intent pairs by token Jaccard similarity.
  → Head intents with too few training phrases to train reliably.
  → Class imbalance between the largest and smallest head intent.
  → numTrainingPhrases metadata drifting from the actual phrase count.
  → Known ASR mistranscriptions kept as training data.

Normalisation: lowercase, strip punctuation, collapse whitespace. Two phrases
that differ only in casing or punctuation are the same phrase to the NLU model.
"""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations

from validator.loader import AgentIndex
from validator.config import (
    NEAR_DUPLICATE_THRESHOLD,
    MIN_TOKENS_FOR_COMPARISON,
    MIN_PHRASES_PER_HEAD_INTENT,
    ASR_HOMOPHONES,
)
from validator.checks.models import Finding

_CHECK = "NLU / Training Phrases"

# Cap on reported near-duplicate intent pairs. The report becomes unreadable
# long before this.
_MAX_NEAR_DUPLICATE_FINDINGS = 150

# A token shared by more than this many phrases ("the", "my") carries no signal
# and would dominate the comparison budget.
_MAX_BUCKET_SIZE = 400

_PUNCT = re.compile(r"[^a-z0-9\s]")
_SPACE = re.compile(r"\s+")


# ── Normalisation ─────────────────────────────────────────────────────────────

def normalise(phrase: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    return _SPACE.sub(" ", _PUNCT.sub("", phrase.lower())).strip()


def _tokens(phrase: str) -> frozenset[str]:
    return frozenset(normalise(phrase).split())


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


# ── Structured analysis records ───────────────────────────────────────────────

@dataclass
class ExactCollision:
    """One normalised phrase training two or more different intents."""

    phrase: str
    intents: list[str]


@dataclass
class NearDuplicatePair:
    """Two intents sharing phrases above the similarity threshold."""

    intent_a: str
    intent_b: str
    pair_count: int
    top_score: float
    example_a: str = ""
    example_b: str = ""


@dataclass
class AsrHit:
    """A known ASR mistranscription found as a standalone token."""

    intent: str
    token: str
    likely_word: str
    phrase_count: int
    example: str = ""


@dataclass
class PhraseStats:
    """Per-intent phrase counts and hygiene flags."""

    intent: str
    is_head: bool
    total: int
    unique: int
    empty: int
    within_duplicates: int
    declared: int
    labels: list[str] = field(default_factory=list)

    @property
    def drifted(self) -> bool:
        return bool(self.declared) and self.declared != self.total

    @property
    def health(self) -> str:
        if self.empty or self.drifted:
            return "Major issue"
        if self.is_head and self.total < MIN_PHRASES_PER_HEAD_INTENT:
            return "Major issue"
        if self.within_duplicates:
            return "Needs attention"
        return "Good"


def exact_collisions(agent: AgentIndex) -> list[ExactCollision]:
    """Every normalised phrase that trains more than one intent."""
    owners: dict[str, set[str]] = defaultdict(set)
    for intent in agent.intents:
        for phrase in intent.training_phrases:
            key = normalise(phrase)
            if key:
                owners[key].add(intent.display_name)

    return [
        ExactCollision(phrase=phrase, intents=sorted(intents))
        for phrase, intents in sorted(
            owners.items(), key=lambda kv: (-len(kv[1]), kv[0])
        )
        if len(intents) > 1
    ]


def near_duplicate_pairs(agent: AgentIndex) -> list[NearDuplicatePair]:
    """
    Cross-intent phrase pairs above the Jaccard threshold, rolled up to the
    intent-pair level — the actionable unit.

    Phrases are bucketed by token so only pairs sharing at least one token are
    compared; a full pairwise comparison of ~10k phrases is not viable.
    """
    entries: list[tuple[str, str, frozenset[str]]] = []
    for intent in agent.intents:
        seen: set[str] = set()
        for phrase in intent.training_phrases:
            key = normalise(phrase)
            if not key or key in seen:
                continue
            seen.add(key)
            tokens = _tokens(phrase)
            if len(tokens) >= MIN_TOKENS_FOR_COMPARISON:
                entries.append((intent.display_name, key, tokens))

    buckets: dict[str, list[int]] = defaultdict(list)
    for idx, (_, _, tokens) in enumerate(entries):
        for token in tokens:
            buckets[token].append(idx)

    scored: dict[tuple[int, int], float] = {}
    for indices in buckets.values():
        if len(indices) > _MAX_BUCKET_SIZE:
            continue
        for i, j in combinations(indices, 2):
            pair = (i, j) if i < j else (j, i)
            if pair in scored:
                continue
            if entries[pair[0]][0] == entries[pair[1]][0]:
                continue  # Same intent — not a cross-intent collision
            score = _jaccard(entries[pair[0]][2], entries[pair[1]][2])
            if score >= NEAR_DUPLICATE_THRESHOLD:
                scored[pair] = score

    rolled: dict[tuple[str, str], NearDuplicatePair] = {}
    for (i, j), score in sorted(scored.items(), key=lambda kv: -kv[1]):
        a, b = sorted((entries[i][0], entries[j][0]))
        existing = rolled.get((a, b))
        if existing is None:
            # First pair seen for this intent pair is the highest scoring,
            # because the loop is sorted by score descending.
            rolled[(a, b)] = NearDuplicatePair(
                intent_a=a,
                intent_b=b,
                pair_count=1,
                top_score=score,
                example_a=entries[i][1],
                example_b=entries[j][1],
            )
        else:
            existing.pair_count += 1

    return sorted(rolled.values(), key=lambda p: (-p.pair_count, p.intent_a))


def asr_hits(agent: AgentIndex) -> list[AsrHit]:
    """
    Known ASR mistranscriptions that are themselves valid words.

    Only matched as standalone tokens — 'car' as a whole word is suspicious in
    a telco bot, but 'car' inside 'carrier' is not.
    """
    out: list[AsrHit] = []
    for intent in agent.intents:
        hits: dict[str, list[str]] = defaultdict(list)
        for phrase in intent.training_phrases:
            tokens = set(normalise(phrase).split())
            for token in tokens & ASR_HOMOPHONES.keys():
                hits[token].append(phrase.strip())

        for token, phrases in sorted(hits.items()):
            out.append(AsrHit(
                intent=intent.display_name,
                token=token,
                likely_word=ASR_HOMOPHONES[token],
                phrase_count=len(phrases),
                example=phrases[0],
            ))
    return out


def phrase_stats(agent: AgentIndex) -> list[PhraseStats]:
    """Per-intent phrase counts, duplicates and metadata drift."""
    out: list[PhraseStats] = []
    for intent in agent.intents:
        normalised = [normalise(p) for p in intent.training_phrases if p.strip()]
        counts = Counter(normalised)
        out.append(PhraseStats(
            intent=intent.display_name,
            is_head=intent.is_head,
            total=len(intent.training_phrases),
            unique=len(counts),
            empty=sum(1 for p in intent.training_phrases if not p.strip()),
            within_duplicates=sum(1 for n in counts.values() if n > 1),
            declared=intent.declared_phrase_count,
            labels=list(intent.labels),
        ))
    return sorted(out, key=lambda s: s.intent)


# ── Checks ────────────────────────────────────────────────────────────────────

def check_nlu(agent: AgentIndex) -> list[Finding]:
    """
    Run every training phrase quality check across all intents.

    Args:
        agent: Populated AgentIndex from loader.load_agent().

    Returns:
        List of Finding objects.
    """
    if not agent.intents:
        return []

    findings: list[Finding] = []
    stats = phrase_stats(agent)

    _check_phrase_hygiene(agent, stats, findings)
    _check_cross_intent_duplicates(agent, findings)
    _check_near_duplicates(agent, findings)
    _check_phrase_volume(agent, findings)
    _check_metadata_drift(stats, findings)
    _check_asr_noise(agent, findings)

    return findings


def _check_phrase_hygiene(
    agent: AgentIndex,
    stats: list[PhraseStats],
    findings: list[Finding],
) -> None:
    """Empty phrases and within-intent duplicates."""
    by_name = {s.intent: s for s in stats}

    for intent in agent.intents:
        stat = by_name[intent.display_name]

        if stat.empty:
            findings.append(Finding(
                severity="error",
                file_path=intent.relative_display,
                flow_name="intents",
                check=_CHECK,
                message=f"Intent '{intent.display_name}' has {stat.empty} empty training phrase(s)",
                detail="Empty phrases contribute nothing and should be deleted.",
            ))

        counts = Counter(normalise(p) for p in intent.training_phrases if p.strip())
        for phrase, n in sorted((p, n) for p, n in counts.items() if n > 1):
            findings.append(Finding(
                severity="warning",
                file_path=intent.relative_display,
                flow_name="intents",
                check=_CHECK,
                message=(
                    f"Intent '{intent.display_name}' repeats the phrase "
                    f"\"{phrase}\" {n} times"
                ),
                detail="Duplicate phrases within one intent skew the model without adding signal.",
            ))


def _check_cross_intent_duplicates(agent: AgentIndex, findings: list[Finding]) -> None:
    for collision in exact_collisions(agent):
        findings.append(Finding(
            severity="error",
            file_path=f"intents/{collision.intents[0]}",
            flow_name="intents",
            check=_CHECK,
            message=(
                f"Phrase \"{collision.phrase}\" trains {len(collision.intents)} "
                f"different intents: {', '.join(collision.intents)}"
            ),
            detail=(
                "Identical training data for competing intents — the match becomes "
                "arbitrary. Assign the phrase to one intent and delete the others."
            ),
        ))


def _check_near_duplicates(agent: AgentIndex, findings: list[Finding]) -> None:
    for pair in near_duplicate_pairs(agent)[:_MAX_NEAR_DUPLICATE_FINDINGS]:
        findings.append(Finding(
            severity="warning",
            file_path=f"intents/{pair.intent_a}",
            flow_name="intents",
            check=_CHECK,
            message=(
                f"Intents '{pair.intent_a}' and '{pair.intent_b}' share "
                f"{pair.pair_count} near-duplicate phrase pair(s) "
                f"(Jaccard ≥ {NEAR_DUPLICATE_THRESHOLD})"
            ),
            detail=f"Example: \"{pair.example_a}\"  vs  \"{pair.example_b}\"",
        ))


def _check_phrase_volume(agent: AgentIndex, findings: list[Finding]) -> None:
    """Thin training data on head intents, and overall class imbalance."""
    heads = agent.head_intents
    if not heads:
        return

    for intent in heads:
        count = len(intent.training_phrases)
        if count < MIN_PHRASES_PER_HEAD_INTENT:
            findings.append(Finding(
                severity="warning",
                file_path=intent.relative_display,
                flow_name="intents",
                check=_CHECK,
                message=(
                    f"Head intent '{intent.display_name}' has only {count} training "
                    f"phrase(s) — below the minimum of {MIN_PHRASES_PER_HEAD_INTENT}"
                ),
                detail="Head intents carry main journeys and need enough phrases to match reliably.",
            ))
        else:
            findings.append(Finding(
                severity="pass",
                file_path=intent.relative_display,
                flow_name="intents",
                check=_CHECK,
                message=f"Head intent '{intent.display_name}' has {count} training phrases",
                detail="",
            ))

    counts = sorted((len(i.training_phrases), i.display_name) for i in heads)
    smallest, largest = counts[0], counts[-1]
    if smallest[0] > 0 and largest[0] / smallest[0] >= 20:
        findings.append(Finding(
            severity="warning",
            file_path="intents/",
            flow_name="intents",
            check=_CHECK,
            message=(
                f"Large class imbalance across head intents: '{largest[1]}' has "
                f"{largest[0]} phrases, '{smallest[1]}' has {smallest[0]}"
            ),
            detail=(
                f"Ratio {largest[0] / smallest[0]:.0f}:1. Heavily imbalanced classes bias "
                f"the classifier toward the largest intent."
            ),
        ))


def _check_metadata_drift(stats: list[PhraseStats], findings: list[Finding]) -> None:
    """numTrainingPhrases in the intent file vs the phrases actually exported."""
    for stat in stats:
        if stat.drifted:
            findings.append(Finding(
                severity="warning",
                file_path=f"intents/{stat.intent}",
                flow_name="intents",
                check=_CHECK,
                message=(
                    f"Intent '{stat.intent}' declares {stat.declared} training "
                    f"phrases but {stat.total} were exported"
                ),
                detail="Metadata drift usually means an incomplete or stale export.",
            ))


def _check_asr_noise(agent: AgentIndex, findings: list[Finding]) -> None:
    for hit in asr_hits(agent):
        findings.append(Finding(
            severity="warning",
            file_path=f"intents/{hit.intent}",
            flow_name="intents",
            check=_CHECK,
            message=(
                f"Intent '{hit.intent}' contains '{hit.token}' in "
                f"{hit.phrase_count} phrase(s) — likely ASR noise for "
                f"'{hit.likely_word}'"
            ),
            detail=f"e.g. \"{hit.example[:120]}\"",
        ))
