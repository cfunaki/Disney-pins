from pydantic import BaseModel


class PinUploadResponse(BaseModel):
    id: int
    batch_id: str
    status: str
    photo_type: str | None
    image_paths: list[str]


class VisionExtractionResponse(BaseModel):
    characters: list[str]
    franchise: str | None
    collection_or_series: str | None
    text_on_pin: str | None
    visible_dates: str | None
    event_clues: str | None
    pin_type: str | None
    edition_size: int | None
    condition_observations: str | None
    suggested_search_terms: list[str]
    confidence_score: float


class CatalogEntryResponse(BaseModel):
    id: int
    canonical_name: str
    characters: list[str]
    franchise: str | None
    series_or_collection: str | None
    event: str | None
    edition_size: int | None
    release_year: int | None
    pin_type: str | None
    evidence_strength: str


class CatalogMatchResponse(BaseModel):
    catalog_entry: CatalogEntryResponse
    match_confidence: float
    match_reasoning: str | None
    rank: int
    status: str


class CompResponse(BaseModel):
    ebay_listing_id: str | None
    title: str
    price: float
    sale_date: str | None
    listing_type: str
    condition: str | None
    match_type: str
    excluded: bool
    exclusion_reason: str | None


class ListingDraftResponse(BaseModel):
    title: str
    description: str | None
    item_specifics: dict | None
    suggested_price: float | None
    quick_sale_price: float | None
    price_confidence: str
    pricing_reasoning: str | None
    tags_keywords: list[str]
    export_status: str


class PinDetailResponse(BaseModel):
    id: int
    batch_id: str
    status: str
    photo_type: str | None
    seller_notes: str | None
    image_paths: list[str]
    extraction: VisionExtractionResponse | None
    catalog_matches: list[CatalogMatchResponse]
    comps: list[CompResponse]
    listing_draft: ListingDraftResponse | None


class PinUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    suggested_price: float | None = None
    tags_keywords: list[str] | None = None
    seller_notes: str | None = None


class BatchProcessRequest(BaseModel):
    batch_id: str


class BatchProgressResponse(BaseModel):
    batch_id: str
    total: int
    processed: int
    status_counts: dict[str, int]


class MatchSelectRequest(BaseModel):
    catalog_entry_id: int


class ExtractionPatchRequest(BaseModel):
    characters: list[str] | None = None
    franchise: str | None = None
    pin_type: str | None = None
    edition_size: int | None = None
    visible_dates: str | None = None
    event_clues: str | None = None
