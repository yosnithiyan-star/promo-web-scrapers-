"""Output formatting and file saving utilities."""

import csv
import hashlib
import json
import os
from datetime import datetime

from .common import THAILAND_TZ

PROMO_FIELDNAMES = [
    "id", "site", "post_id", "category", "category_slugs", "title",
    "date_range", "date_start", "date_end", "link", "image", "scraped_at",
    "published_at", "modified_at", "terms",
]

# Canonical site codes, locked once. Every scraper registers its prefix here
# so namespaced ids (e.g. "tmn_236401") stay unique across sites.
SITE_CODES = {
    "truemoney": "tmn",
    "seven_eleven": "7el",
    "aeon": "aeon",
    "umayplus": "uma",
    "firstchoice": "fcb",
    "kbj": "kbj",
}


def post_id_from_link(link: str) -> str:
    """Stable synthetic post_id for sites with no native id (AEON, FirstChoice, KBJ).

    Returns a short md5 hash of the promo link, matching the fallback branch of
    make_site_id so the namespaced id and synthesized post_id stay consistent
    (e.g. post_id "e564eb" under id "aeon_e564eb").
    """
    digest = hashlib.md5(link.encode("utf-8")).hexdigest()
    return digest[:6]


def make_site_id(site_code: str, post_id, link: str = "") -> str | None:
    """Build the namespaced, cross-site-unique id for a promo.

    Namespaces the native post_id when present (e.g. "tmn_236401"). When the
    site has no native id, falls back to namespacing a stable short hash of the
    promo link so the id stays unique across sites.
    """
    if post_id is not None:
        return f"{site_code}_{post_id}"
    if link:
        return f"{site_code}_{post_id_from_link(link)}"
    return None


# Content-block types for the uniform `terms` block list. Stable taxonomy,
# documented in docs/glossary.md. Order in a promo's `terms` is meaningful.
BLOCK_TYPES = ("short_detail", "conditions", "conditions_table", "reward_tiers", "meta")


def content_block(section_title: str | None, content: str | None, block_type: str) -> dict:
    """Build one {section_title, content, type} content block for `terms`.

    `content` is the caller's clean single-line text (use clean_terms_text
    first). `block_type` must be in BLOCK_TYPES. Returns a dict; content may be
    None for a block that carries no text. The `term_detail` field is stamped by
    number_blocks(), not here.
    """
    if block_type not in BLOCK_TYPES:
        raise ValueError(f"unknown block type: {block_type!r} (allowed: {BLOCK_TYPES})")
    return {"section_title": section_title, "content": content, "type": block_type}


def number_blocks(blocks: list[dict]) -> dict[str, dict]:
    """Group a list of blocks into an object keyed by term_detail_N.

    Returns {term_detail_1: {section_title, content, type}, ...} so consumers
    can address each section by its numbered key (terms["term_detail_2"]).
    Keys are stable 1-based positions; the order of the input list is preserved.
    """
    return {f"term_detail_{i}": dict(block) for i, block in enumerate(blocks, start=1)}


def normalize_terms(value):
    """Coerce any legacy `terms` shape into a uniform list of content blocks.

    Accepts: None -> []; a plain string -> one `conditions` block; a list of
    {label, text} objects -> blocks keyed on label; already-block-list -> as-is.
    Returns an object keyed by term_detail_N; each value is {section_title,
    content, type}. Migration shim so consumers and tests have one entry point
    regardless of which site produced the data.
    """
    if value is None:
        return {}
    if isinstance(value, str):
        return number_blocks([content_block(None, value, "conditions")]) if value else {}
    if isinstance(value, list):
        blocks = []
        for item in value:
            if not isinstance(item, dict):
                continue
            if "content" in item and "type" in item:
                blocks.append(item)  # already a block
            elif "text" in item:  # legacy {label, text}
                label = item.get("label")
                # Legacy firstchoice emitted {label: "tables"} for reward tables.
                block_type = "reward_tiers" if label == "tables" else (
                    label if label in BLOCK_TYPES else "conditions"
                )
                blocks.append(content_block(label, item.get("text"), block_type))
        return number_blocks(blocks)
    return {}


def validate_promos(promos: list[dict]) -> list[str]:
    """Validate a scrape's output against the shared schema; return problems.

    Each problem is a human-readable string. An empty list means the output is
    well-formed. Called at the end of every scrape so a site structure change
    that starts producing malformed output fails loudly instead of silently
    writing bad data. This is a drift check on the *shape* of the output, not a
    content-quality check.
    """
    problems: list[str] = []
    required = set(PROMO_FIELDNAMES)
    seen_ids: set[str] = set()

    for i, promo in enumerate(promos):
        label = f"promo[{i}]"
        if not isinstance(promo, dict):
            problems.append(f"{label}: not an object ({type(promo).__name__})")
            continue
        missing = required - set(promo.keys())
        if missing:
            problems.append(f"{label}: missing fields {sorted(missing)}")

        pid = promo.get("id")
        if pid is None or not str(pid).strip():
            problems.append(f"{label}: missing id")
        elif pid in seen_ids:
            problems.append(f"{label}: duplicate id {pid!r}")
        else:
            seen_ids.add(str(pid))

        for field in ("post_id", "title"):
            value = promo.get(field)
            if value is None or not str(value).strip():
                problems.append(f"{label}: empty {field}")

        site = promo.get("site")
        if site not in SITE_CODES:
            problems.append(f"{label}: unknown site {site!r} (expected one of {sorted(SITE_CODES)})")

        for field in ("date_start", "date_end"):
            value = promo.get(field)
            if value is None:
                continue
            if not (isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-"):
                problems.append(f"{label}: {field} not YYYY-MM-DD: {value!r}")
        ds, de = promo.get("date_start"), promo.get("date_end")
        if ds and de and ds > de:
            problems.append(f"{label}: date_start {ds!r} after date_end {de!r}")

        terms = promo.get("terms")
        if terms:
            if not isinstance(terms, dict):
                problems.append(f"{label}: terms is {type(terms).__name__}, expected dict keyed by term_detail_N")
            else:
                for key, block in terms.items():
                    if not (isinstance(key, str) and key.startswith("term_detail_")):
                        problems.append(f"{label}: terms key {key!r} not term_detail_N")
                    if not isinstance(block, dict):
                        problems.append(f"{label}: terms[{key}] not an object")
                        continue
                    if set(block) - {"section_title", "content", "type"}:
                        problems.append(f"{label}: terms[{key}] unexpected keys {sorted(set(block) - {'section_title','content','type'})}")
                    if block.get("type") not in BLOCK_TYPES:
                        problems.append(f"{label}: terms[{key}] type {block.get('type')!r} not in {BLOCK_TYPES}")

    return problems


def _ensure_output_dir(path):
    """Ensure parent directory of path exists."""
    out_dir = os.path.dirname(path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)


def save_json(promos, path):
    """Save promos as JSON."""
    _ensure_output_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(promos, f, ensure_ascii=False, indent=2)


def save_csv(promos, path):
    """Save promos as CSV."""
    _ensure_output_dir(path)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=PROMO_FIELDNAMES)
        writer.writeheader()
        for p in promos:
            row = dict(p)
            # Serialize list/dict-valued columns (category_slugs, terms) as
            # semicolon-joined strings; CSV has no list/object type. For the
            # `terms` content-block object (keyed term_detail_N), join just each
            # block's content.
            for k, v in row.items():
                if isinstance(v, dict):
                    parts = [b.get("content", b.get("text", "")) for b in v.values() if isinstance(b, dict)]
                    row[k] = ";".join(str(x) for x in parts if x)
                elif isinstance(v, list):
                    parts = []
                    for x in v:
                        if isinstance(x, dict):
                            parts.append(x.get("content", x.get("text", "")))
                        else:
                            parts.append(x)
                    row[k] = ";".join(str(x) for x in parts)
            writer.writerow(row)
