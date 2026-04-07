"""
Manual vision quality test script.
Place sample pin photos in sample_data/ directory, then run:
    python scripts/test_vision_quality.py

Outputs structured results for each image to stdout.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline.vision import extract_pin_metadata

async def main():
    sample_dir = Path("sample_data")
    if not sample_dir.exists():
        print("Create a sample_data/ directory with pin photos first.")
        return
    image_files = sorted(
        p for p in sample_dir.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    if not image_files:
        print("No image files found in sample_data/")
        return
    print(f"Testing {len(image_files)} images...\n")
    results = []
    for img_path in image_files:
        print(f"Processing: {img_path.name}")
        try:
            result = await extract_pin_metadata([str(img_path)])
            result["_file"] = img_path.name
            results.append(result)
            print(f"  Characters: {result.get('characters', [])}")
            print(f"  Franchise: {result.get('franchise')}")
            print(f"  Pin Type: {result.get('pin_type')}")
            print(f"  Edition: {result.get('edition_size')}")
            print(f"  Confidence: {result.get('confidence_score')}")
            print(f"  Search Terms: {result.get('suggested_search_terms', [])}")
            print()
        except Exception as e:
            print(f"  ERROR: {e}\n")
            results.append({"_file": img_path.name, "_error": str(e)})
    output_path = Path("sample_data/vision_results.json")
    output_path.write_text(json.dumps(results, indent=2))
    print(f"\nResults saved to {output_path}")

if __name__ == "__main__":
    asyncio.run(main())
