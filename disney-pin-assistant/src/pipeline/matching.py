from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.models import CatalogEntry

async def find_catalog_matches(db: AsyncSession, extraction: dict, max_results: int = 3) -> list[dict]:
    result = await db.execute(select(CatalogEntry))
    all_entries = result.scalars().all()
    scored = []
    for entry in all_entries:
        score = _compute_match_score(entry, extraction)
        if score > 0:
            scored.append({
                "catalog_entry_id": entry.id,
                "canonical_name": entry.canonical_name,
                "characters": entry.characters,
                "franchise": entry.franchise,
                "event": entry.event,
                "edition_size": entry.edition_size,
                "release_year": entry.release_year,
                "pin_type": entry.pin_type,
                "evidence_strength": entry.evidence_strength,
                "confidence": score,
                "reasoning": _build_reasoning(entry, extraction),
            })
    scored.sort(key=lambda x: x["confidence"], reverse=True)
    return scored[:max_results]

def _compute_match_score(entry: CatalogEntry, extraction: dict) -> float:
    score = 0.0
    max_score = 0.0

    # Character overlap (weight: 3)
    max_score += 3
    extracted_chars = {c.lower() for c in (extraction.get("characters") or [])}
    entry_chars = {c.lower() for c in (entry.characters or [])}
    if extracted_chars and entry_chars:
        overlap = len(extracted_chars & entry_chars)
        total = len(extracted_chars | entry_chars)
        if total > 0:
            score += 3 * (overlap / total)

    # Franchise match (weight: 2)
    max_score += 2
    if extraction.get("franchise") and entry.franchise:
        if extraction["franchise"].lower() == entry.franchise.lower():
            score += 2

    # Event match (weight: 4 — high specificity)
    max_score += 4
    event_clues = extraction.get("event_clues") or ""
    if event_clues and entry.event:
        event_words = set(event_clues.lower().split())
        entry_event_words = set(entry.event.lower().split())
        common = event_words & entry_event_words
        if len(common) >= 2:
            score += 4
        elif len(common) == 1:
            score += 2

    # Edition size match (weight: 3 — very specific)
    max_score += 3
    if extraction.get("edition_size") and entry.edition_size:
        if extraction["edition_size"] == entry.edition_size:
            score += 3

    # Pin type match (weight: 1)
    max_score += 1
    if extraction.get("pin_type") and entry.pin_type:
        if extraction["pin_type"].lower() == entry.pin_type.lower():
            score += 1

    # Year match (weight: 2)
    max_score += 2
    visible_dates = extraction.get("visible_dates") or ""
    if visible_dates and entry.release_year:
        if str(entry.release_year) in visible_dates:
            score += 2

    if max_score == 0:
        return 0.0
    normalized = score / max_score
    if normalized < 0.2:
        return 0.0
    return round(normalized, 2)

async def find_catalog_matches_hybrid(
    db: AsyncSession,
    extraction: dict,
    query_embedding: list[float] | None = None,
    max_text_candidates: int = 30,
    max_results: int = 5,
) -> list[dict]:
    """Hybrid matching: text scoring → CLIP visual re-ranking."""
    from src.pipeline.image_matching import rank_by_visual_similarity

    # Step 1: Text-based scoring (reuse existing logic)
    result = await db.execute(select(CatalogEntry))
    all_entries = result.scalars().all()

    scored = []
    for entry in all_entries:
        score = _compute_match_score(entry, extraction)
        if score > 0:
            scored.append({
                "catalog_entry_id": entry.id,
                "canonical_name": entry.canonical_name,
                "characters": entry.characters,
                "franchise": entry.franchise,
                "event": entry.event,
                "edition_size": entry.edition_size,
                "release_year": entry.release_year,
                "pin_type": entry.pin_type,
                "evidence_strength": entry.evidence_strength,
                "source_reference_id": entry.source_reference_id,
                "image_path": entry.image_path,
                "clip_embedding": entry.clip_embedding,
                "confidence": score,
                "reasoning": _build_reasoning(entry, extraction),
            })

    scored.sort(key=lambda x: x["confidence"], reverse=True)
    text_candidates = scored[:max_text_candidates]

    # Step 2: Visual re-ranking (if embedding available)
    if query_embedding is not None and text_candidates:
        candidates_with_embeddings = [
            c for c in text_candidates if c.get("clip_embedding") is not None
        ]
        if candidates_with_embeddings:
            reranked = rank_by_visual_similarity(
                query_embedding, candidates_with_embeddings, top_k=max_results
            )
            without_embeddings = [
                c for c in text_candidates if c.get("clip_embedding") is None
            ]
            result_list = reranked + without_embeddings
            return result_list[:max_results]

    # Fallback: text-only
    return text_candidates[:max_results]


def _build_reasoning(entry: CatalogEntry, extraction: dict) -> str:
    reasons = []
    extracted_chars = {c.lower() for c in (extraction.get("characters") or [])}
    entry_chars = {c.lower() for c in (entry.characters or [])}
    if extracted_chars & entry_chars:
        reasons.append(f"Character match: {', '.join(extracted_chars & entry_chars)}")
    if extraction.get("franchise") and entry.franchise:
        if extraction["franchise"].lower() == entry.franchise.lower():
            reasons.append(f"Franchise match: {entry.franchise}")
    event_clues = extraction.get("event_clues") or ""
    if event_clues and entry.event:
        reasons.append(f"Event match: {entry.event}")
    if extraction.get("edition_size") and entry.edition_size:
        if extraction["edition_size"] == entry.edition_size:
            reasons.append(f"Edition size match: {entry.edition_size}")
    if extraction.get("pin_type") and entry.pin_type:
        if extraction["pin_type"].lower() == entry.pin_type.lower():
            reasons.append(f"Pin type match: {entry.pin_type}")
    return "; ".join(reasons) if reasons else "Weak match"
