#!/usr/bin/env python3
"""
Design-time advisor: analyze a site's stage-1 (listing) and stage-2 (detail)
HTML and print a recommended selector -> block-type mapping, so a human (or
agent) decides how to build a scraper before writing code.

This is a *heuristic* tool over the DOM — it does not call an LLM. It flags the
structure the scraper must extract:

  Stage 1 (listing card): title, date_range, optional short_detail.
  Stage 2 (detail page):  conditions, reward_tiers, and any see-more/CSS-clip
                          wrapper whose full text is already in the DOM.

Usage:
    python tools/analyze_site.py <stage1.html> [stage2.html]
    python tools/analyze_site.py --url <detail-or-listing-url>   # fetches live

Exit code 0. Pure stdlib (BeautifulSoup), no network unless --url is used.
"""

import argparse
import re
import sys
import os

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.common import session_get

# Class-name hints -> block type. Substring match, lowest wins per element.
# Ordered so specific hints win over generic ones.
TYPE_HINTS = [
    # reward / benefit tables
    (re.compile(r"reward|benefit|prize|รางวัล", re.I), "reward_tiers"),
    # conditions / terms
    (re.compile(r"condition|terms|เงื่อนไข|ข้อกำหนด", re.I), "conditions"),
    # short card summary
    (re.compile(r"short|subtitle|summary|excerpt|สรุป", re.I), "short_detail"),
]

# Wrapper names that indicate a see-more / CSS-clip expander.
CLIP_HINTS = re.compile(r"show.?more|more.?content|expand|read.?more|overflow|max.?height", re.I)


def _block_type_for(class_str: str) -> str | None:
    # `class_str` is the whitespace-joined class attribute value (as BeautifulSoup
    # passes it to a class_= callable filter), e.g. "promotionDetailConditionSection".
    for rx, block_type in TYPE_HINTS:
        if rx.search(class_str):
            return block_type
    return None


def _has_clip_style(el) -> bool:
    style = (el.get("style") or "").lower().replace(" ", "")
    return "max-height" in style or "overflow:hidden" in style


def analyze_stage1(soup: BeautifulSoup, card_selector: str = None) -> dict:
    """Find candidate listing-card containers and their fields."""
    candidates = []
    hint_re = re.compile(r"card|promotion|promo|item", re.I)
    for el in soup.find_all(class_=lambda c: isinstance(c, str) and bool(hint_re.search(c))):
        text = el.get_text(" ", strip=True)
        if len(text) < 20:
            continue
        heading = el.find(["h1", "h2", "h3", "h4"])
        candidates.append({
            "classes": (el.get("class") or []),
            "has_title": heading is not None,
            "has_image": bool(el.find("img")),
            "has_link": bool(el.find("a", href=True)),
            "text_len": len(text),
        })
    # Dedup by class-signature, keep the most complete.
    by_sig = {}
    for c in candidates:
        sig = ".".join(c["classes"])
        if sig not in by_sig or c["text_len"] > by_sig[sig]["text_len"]:
            by_sig[sig] = c
    return {
        "card_candidates": sorted(
            by_sig.values(),
            key=lambda c: (not c["has_title"], not c["has_link"], not c["has_image"]),
        ),
        "card_selector": card_selector,
    }


def analyze_stage2(soup: BeautifulSoup) -> dict:
    """Analyze a detail page for extractable content blocks."""
    blocks = []
    clip_detected = False
    # First pass: typed containers (element whose own class hints a block type).
    for el in soup.find_all(class_=lambda c: isinstance(c, str) and bool(_block_type_for(c))):
        classes = el.get("class", [])
        block_type = _block_type_for(" ".join(classes))
        # Skip a typed element nested inside a typed parent of the same type
        # (the parent is the fuller container).
        parent = el.find_parent(
            class_=lambda c: isinstance(c, str) and bool(_block_type_for(c)))
        if parent is not None and parent is not el and _block_type_for(" ".join(parent.get("class", []))) == block_type:
            continue
        has_clip = bool(
            el.find(style=lambda s: isinstance(s, str) and bool(CLIP_HINTS.search(s)))
            or _has_clip_style(el)
        )
        text = clean(el.get_text(" ", strip=True))
        blocks.append({
            "selector": "." + (classes[0] if classes else ""),
            "type": block_type,
            "has_table": bool(el.find("table")),
            "has_clip": has_clip,
            "text_len": len(text or ""),
        })
        if has_clip:
            clip_detected = True
    # Second pass: see-more/CSS-clip signals — either an element whose class
    # names a toggle/expander, or one with a clip style attribute. Either means
    # the full text is present and CSS-hidden (no headless browser needed).
    clip_els = list(soup.find_all(class_=lambda c: isinstance(c, str) and bool(CLIP_HINTS.search(c))))
    clip_els += list(soup.find_all(style=lambda s: isinstance(s, str) and bool(CLIP_HINTS.search(s))))
    seen_selectors = {b["selector"] for b in blocks}
    for el in clip_els:
        clip_detected = True
        classes = el.get("class") or []
        selector = "." + ".".join(classes) if classes else el.name or "?"
        text = clean(el.get_text(" ", strip=True))
        has_table = bool(el.find("table"))
        if text and selector not in seen_selectors and len(text) >= 5:
            blocks.append({
                "selector": selector,
                "type": "conditions",
                "has_table": has_table,
                "has_clip": True,
                "text_len": len(text),
            })
            seen_selectors.add(selector)
        # A table inside the clip/typed area is a reward_tiers block.
        table = el.find("table")
        if table and not any(b["type"] == "reward_tiers" for b in blocks):
            blocks.append({
                "selector": "table",
                "type": "reward_tiers",
                "has_table": True,
                "has_clip": True,
                "text_len": len(table.find_all("tr")),
            })
    # Also record a standalone table not already covered.
    if not any(b["has_table"] for b in blocks):
        for t in soup.find_all("table")[:1]:
            blocks.append({
                "selector": "table", "type": "reward_tiers", "has_table": True,
                "has_clip": False, "text_len": len(t.find_all("tr")),
            })
    return {"content_blocks": blocks, "see_more_detected": clip_detected}


def clean(text: str) -> str:
    return " ".join(text.split())


def report(stage1: dict, stage2: dict | None) -> str:
    lines = ["# Design-time analysis", ""]
    lines.append("## Stage 1 (listing card)")
    if stage1["card_candidates"]:
        lines.append("Recommended card container (most complete candidate):")
        c = stage1["card_candidates"][0]
        lines.append(f"  selector .{'.'.join(c['classes'])}")
        lines.append(f"  has_title={c['has_title']} has_link={c['has_link']} has_image={c['has_image']}")
        lines.append("Suggested mapping:")
        lines.append("  - title            -> <h1-4> inside the card")
        lines.append("  - date_range       -> a <span>/<p> with date tokens")
        lines.append("  - short_detail     -> a <p> summary (optional; map to block type 'short_detail')")
    else:
        lines.append("  No obvious card container found — inspect the listing HTML manually.")
    if stage2:
        lines.append("")
        lines.append("## Stage 2 (detail page)")
        if stage2["see_more_detected"]:
            lines.append("  NOTE: see-more/CSS-clip wrapper detected — full text is already in the HTML;")
            lines.append("        extract the whole wrapper, no headless browser needed.")
        if stage2["content_blocks"]:
            lines.append("Content blocks (recommended selector -> type):")
            for b in stage2["content_blocks"]:
                lines.append(
                    f"  {b['selector']:28} -> {b['type']:14} "
                    f"table={b['has_table']} clip={b['has_clip']} len={b['text_len']}"
                )
        else:
            lines.append("  No typed content blocks found by heuristics — check for conditions/terms text.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze stage-1/stage-2 HTML for scraper design")
    parser.add_argument("html", nargs="*", help="stage1.html [stage2.html]")
    parser.add_argument("--url", help="Fetch a live page and analyze it as stage 2 (or stage 1 if it is a listing)")
    parser.add_argument("--card", default=None, help="Force a card selector (stage 1)")
    args = parser.parse_args()

    stage2 = None
    stage1 = None
    if args.url:
        resp = session_get(args.url, timeout=25)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "lxml")
        # Heuristic: a page is a listing if it has repeated card-ish containers.
        stage2 = analyze_stage2(soup)
        stage1 = analyze_stage1(soup, args.card)
        print(report(stage1, stage2))
        return 0

    if len(args.html) == 1:
        with open(args.html[0], encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "lxml")
        print(report(analyze_stage1(soup, args.card), None))
        return 0

    if len(args.html) >= 2:
        with open(args.html[0], encoding="utf-8") as f:
            s1 = BeautifulSoup(f.read(), "lxml")
        with open(args.html[1], encoding="utf-8") as f:
            s2 = BeautifulSoup(f.read(), "lxml")
        print(report(analyze_stage1(s1, args.card), analyze_stage2(s2)))
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
