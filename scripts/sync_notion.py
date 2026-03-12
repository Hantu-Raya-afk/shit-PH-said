"""
Sync Notion 'Shit PH Said' database to Hugo markdown posts.
Pulls all entries (or only those marked for publishing) and
generates markdown files with front matter.
"""

import os
import re
import json
import requests
from datetime import datetime
from pathlib import Path

# ── Config ──────────────────────────────────────────────
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
OUTPUT_DIR = Path("site/content/posts")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# ── Notion API helpers ──────────────────────────────────

def query_database():
    """Query all published entries from the database."""
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    
    # Only pull entries marked as "Substack And Bear" (your published ones)
    # Remove the filter block to pull ALL entries instead
    payload = {
        "filter": {
            "or": [
                {
                    "property": "Posted",
                    "select": {"equals": "Substack And Bear"}
                }
            ]
        },
        "sorts": [
            {"property": "Date", "direction": "descending"}
        ]
    }
    
    all_results = []
    has_more = True
    start_cursor = None
    
    while has_more:
        if start_cursor:
            payload["start_cursor"] = start_cursor
        
        resp = requests.post(url, headers=HEADERS, json=payload)
        resp.raise_for_status()
        data = resp.json()
        
        all_results.extend(data["results"])
        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")
    
    return all_results


def get_page_content(page_id):
    """Get the block children (content) of a page."""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.json().get("results", [])


def extract_rich_text(rich_text_list):
    """Extract plain text from Notion rich text array."""
    return "".join(rt.get("plain_text", "") for rt in rich_text_list)


def extract_property(page, prop_name, prop_type):
    """Extract a property value from a Notion page object."""
    prop = page["properties"].get(prop_name, {})
    
    if prop_type == "title":
        return extract_rich_text(prop.get("title", []))
    elif prop_type == "rich_text":
        return extract_rich_text(prop.get("rich_text", []))
    elif prop_type == "select":
        sel = prop.get("select")
        return sel["name"] if sel else ""
    elif prop_type == "date":
        date_obj = prop.get("date")
        return date_obj["start"] if date_obj else ""
    
    return ""


# ── Block → Markdown conversion ────────────────────────

def blocks_to_markdown(blocks):
    """Convert Notion blocks to markdown string."""
    lines = []
    
    for block in blocks:
        btype = block["type"]
        
        if btype == "paragraph":
            text = extract_rich_text(block["paragraph"].get("rich_text", []))
            lines.append(text + "\n")
        
        elif btype == "heading_1":
            text = extract_rich_text(block["heading_1"].get("rich_text", []))
            lines.append(f"# {text}\n")
        
        elif btype == "heading_2":
            text = extract_rich_text(block["heading_2"].get("rich_text", []))
            lines.append(f"## {text}\n")
        
        elif btype == "heading_3":
            text = extract_rich_text(block["heading_3"].get("rich_text", []))
            lines.append(f"### {text}\n")
        
        elif btype == "bulleted_list_item":
            text = extract_rich_text(block["bulleted_list_item"].get("rich_text", []))
            lines.append(f"- {text}")
        
        elif btype == "numbered_list_item":
            text = extract_rich_text(block["numbered_list_item"].get("rich_text", []))
            lines.append(f"1. {text}")
        
        elif btype == "quote":
            text = extract_rich_text(block["quote"].get("rich_text", []))
            lines.append(f"> {text}\n")
        
        elif btype == "callout":
            text = extract_rich_text(block["callout"].get("rich_text", []))
            lines.append(f"> **Note:** {text}\n")
        
        elif btype == "divider":
            lines.append("---\n")
        
        elif btype == "code":
            text = extract_rich_text(block["code"].get("rich_text", []))
            lang = block["code"].get("language", "")
            lines.append(f"```{lang}\n{text}\n```\n")
        
        else:
            # Fallback: try to extract any rich_text
            if btype in block and "rich_text" in block.get(btype, {}):
                text = extract_rich_text(block[btype]["rich_text"])
                lines.append(text + "\n")
    
    return "\n".join(lines)


# ── Generate markdown files ────────────────────────────

def slugify(text):
    """Convert title to URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text[:80].strip('-')


def generate_posts(pages):
    """Generate Hugo markdown posts from Notion pages."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Clean existing posts
    for f in OUTPUT_DIR.glob("*.md"):
        f.unlink()
    
    for page in pages:
        title = extract_property(page, "Statement", "title")
        date = extract_property(page, "Date", "date")
        category = extract_property(page, "Category", "select")
        said_by = extract_property(page, "Said By", "rich_text")
        notes = extract_property(page, "Notes", "rich_text")
        
        if not title or not date:
            continue
        
        # Get page content
        page_id = page["id"]
        blocks = get_page_content(page_id)
        content_md = blocks_to_markdown(blocks)
        
        # If no block content, use Notes as content
        if not content_md.strip() and notes:
            content_md = notes
        
        slug = slugify(title)
        
        # Hugo front matter
        front_matter = f"""---
title: "{title.replace('"', "'")}"
date: {date}
categories: ["{category}"]
tags: ["{category}"]
said_by: "{said_by.replace('"', "'")}"
draft: false
---

**Said by:** {said_by}

**Category:** {category}

**Date:** {date}

---

{content_md}
"""
        
        filepath = OUTPUT_DIR / f"{date}-{slug}.md"
        filepath.write_text(front_matter, encoding="utf-8")
        print(f"Generated: {filepath.name}")
    
    print(f"\nTotal posts generated: {len(list(OUTPUT_DIR.glob('*.md')))}")


# ── Main ───────────────────────────────────────────────

if __name__ == "__main__":
    print("Querying Notion database...")
    pages = query_database()
    print(f"Found {len(pages)} entries")
    
    print("Generating markdown posts...")
    generate_posts(pages)
    
    print("Done!")