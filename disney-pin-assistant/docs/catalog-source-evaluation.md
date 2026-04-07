# Catalog Source Evaluation

## Purpose

Evaluate community Disney pin databases for initial catalog seeding. The catalog needs: pin names, characters, franchise, event, edition size, release year, pin type, and reference images.

## Sources Evaluated

### 1. PinPics (pinpics.com)

**What it is:** The largest community Disney pin database with tens of thousands of entries. Includes pin names, images, edition sizes, release dates, and community ratings.

**Data availability:**
- No official API
- Website is scrapeable (standard HTML pages with consistent structure)
- Each pin has a unique numeric ID
- Fields available: name, image, edition size, release date, park/event, characters, pin type
- Search by character, year, event, or keyword

**Coverage:** Estimated 50,000+ pin entries. Strong coverage for official Disney Parks pins, weaker for international or unofficial releases.

**Quality:** Generally good for identification. Names can be inconsistent (community-contributed). Images are usually front-only.

**Legal/TOS:** Standard web TOS. Scraping at reasonable rates for personal/non-commercial use is common practice in the pin community. No explicit API means no formal data use agreement.

**Recommendation:** Primary seed source. Scrape at respectful rate (1-2 requests/second). Store with source attribution. Plan for name normalization.

### 2. Disney Pin Trading Database (various community sites)

**What it is:** Several smaller community-maintained databases and wikis focused on specific pin categories (Hidden Mickeys, limited editions, park exclusives).

**Data availability:** Varies by site. Most are simple HTML pages or wiki format. No APIs.

**Coverage:** Narrower than PinPics but sometimes deeper for specific categories (e.g., Hidden Mickey pins across all years).

**Quality:** Variable. Some are meticulously maintained, others are outdated.

**Recommendation:** Supplementary source. Use to fill gaps in PinPics data for specific categories.

### 3. PinCollector.com

**What it is:** Another community catalog, smaller than PinPics.

**Data availability:** Web-based, no API. Less structured than PinPics.

**Coverage:** Smaller catalog, significant overlap with PinPics.

**Recommendation:** Low priority. Only use if specific pins are missing from PinPics.

### 4. eBay Sold Listings (marketplace evidence)

**What it is:** Not a catalog per se, but a rich source of pin naming conventions, variant identification, and real-world pricing.

**Data availability:** eBay Browse API provides structured access to sold and active listings. Already planned for comp search.

**Coverage:** Very broad — any pin that's been sold on eBay. But data is seller-generated and inconsistent.

**Quality:** Highly variable. Sellers use different naming conventions, abbreviations, and levels of detail.

**Recommendation:** Use as Tier 3 evidence source. When a pin is identified, store the eBay listing title as an alternate name to improve future matching.

### 5. Your Own Accepted Data (internal)

**What it is:** Every time a seller confirms a pin identification, that becomes a validated data point.

**Data availability:** Grows organically from tool usage.

**Coverage:** Starts at zero, grows with use.

**Quality:** Highest confidence — human-verified.

**Recommendation:** Tier 1 source over time. Every confirmed match should enrich or create catalog entries.

## Recommended Seeding Strategy

### Phase 1: Initial Seed (before MVP launch)
1. Scrape PinPics for the most common/popular pin categories:
   - Limited Edition pins (last 5 years)
   - Hidden Mickey pins (last 3 years)
   - Common rack pins (currently in parks)
   - Event-specific pins (Food & Wine, Halloween, etc.)
2. Target: 5,000-10,000 entries as initial seed
3. Normalize names, extract structured fields
4. Store with `source: "pinpics"` and `evidence_strength: "medium"`

### Phase 2: Enrichment (during MVP usage)
1. Every confirmed match adds `evidence_strength: "high"` 
2. Rejected matches inform alternate name mapping
3. eBay listing titles stored as alternate names on matched entries
4. New pins not in catalog get entries created from seller input

### Phase 3: Expansion (post-MVP)
1. Scrape additional PinPics categories
2. Add community database entries for gaps
3. Consider automated periodic re-scrape for new releases

## Data Cleanup Expectations

PinPics data will need:
- Name normalization (inconsistent capitalization, abbreviations)
- Character name standardization ("Mickey" vs "Mickey Mouse")
- Edition size parsing (sometimes in name, sometimes in separate field)
- Year extraction from release date fields
- Pin type classification from free-text descriptions

Estimated cleanup effort: moderate. A one-time normalization script + ongoing manual corrections as issues are found during matching.

## Next Steps

1. Create a PinPics scraper script (respectful rate limiting)
2. Design the normalization pipeline
3. Run initial scrape on a test category (e.g., "2024 Limited Edition")
4. Evaluate data quality and coverage
5. Expand scrape to full target categories
