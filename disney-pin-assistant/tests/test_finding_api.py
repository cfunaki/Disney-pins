"""Tests for Finding API client XML parsing."""

from scripts.ebay_import.finding_api import parse_finding_response


SAMPLE_RESPONSE_XML = """<?xml version='1.0' encoding='UTF-8'?>
<findCompletedItemsResponse xmlns="https://www.ebay.com/marketplace/search/v1/services">
  <ack>Success</ack>
  <paginationOutput>
    <totalPages>2</totalPages>
    <totalEntries>150</totalEntries>
  </paginationOutput>
  <searchResult count="2">
    <item>
      <itemId>123456789</itemId>
      <title>Disney Mickey Mouse LE 3000 Pin</title>
      <sellingStatus>
        <currentPrice currencyId="USD">25.99</currentPrice>
        <sellingState>EndedWithSales</sellingState>
      </sellingStatus>
      <listingInfo>
        <endTime>2024-12-15T10:30:00.000Z</endTime>
      </listingInfo>
      <galleryURL>https://i.ebayimg.com/thumbs/123.jpg</galleryURL>
      <condition>
        <conditionDisplayName>New</conditionDisplayName>
      </condition>
    </item>
    <item>
      <itemId>987654321</itemId>
      <title>Stitch LE 500 Trading Pin</title>
      <sellingStatus>
        <currentPrice currencyId="USD">42.00</currentPrice>
        <sellingState>EndedWithSales</sellingState>
      </sellingStatus>
      <listingInfo>
        <endTime>2024-11-20T15:00:00.000Z</endTime>
      </listingInfo>
      <galleryURL>https://i.ebayimg.com/thumbs/987.jpg</galleryURL>
    </item>
  </searchResult>
</findCompletedItemsResponse>"""


def test_parse_finding_response_extracts_items():
    """Parse XML response and extract item list."""
    items, total_pages = parse_finding_response(SAMPLE_RESPONSE_XML)
    assert len(items) == 2
    assert total_pages == 2


def test_parse_finding_response_item_fields():
    """Verify extracted fields from first item."""
    items, _ = parse_finding_response(SAMPLE_RESPONSE_XML)
    item = items[0]
    assert item["itemId"] == "123456789"
    assert item["title"] == "Disney Mickey Mouse LE 3000 Pin"
    assert item["price"] == {"value": "25.99", "currency": "USD"}
    assert item["image"] == {"imageUrl": "https://i.ebayimg.com/thumbs/123.jpg"}
    assert item["end_time"] == "2024-12-15T10:30:00.000Z"


def test_parse_finding_response_empty():
    """Handle response with no items."""
    xml = """<?xml version='1.0' encoding='UTF-8'?>
    <findCompletedItemsResponse xmlns="https://www.ebay.com/marketplace/search/v1/services">
      <ack>Success</ack>
      <paginationOutput><totalPages>0</totalPages><totalEntries>0</totalEntries></paginationOutput>
      <searchResult count="0"/>
    </findCompletedItemsResponse>"""
    items, total_pages = parse_finding_response(xml)
    assert items == []
    assert total_pages == 0
