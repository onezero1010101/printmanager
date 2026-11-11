"""Free-form tags on items. Matching ignores upper/lower case."""
import re

MAX_TAGS = 20
MAX_TAG_LENGTH = 30


def parse_tags(raw):
    """Turn "gift, Functional,  #gift" into (["gift", "Functional"], error or None).

    Tags are separated by commas. Spaces inside a tag are kept (single spaces),
    a leading # is dropped, and repeats (any case) are removed, keeping the
    first spelling.
    """
    tags, seen = [], set()
    for part in (raw or "").split(","):
        tag = re.sub(r"\s+", " ", part).strip().lstrip("#").strip()
        if not tag:
            continue
        if len(tag) > MAX_TAG_LENGTH:
            return [], f"Tags must be {MAX_TAG_LENGTH} characters or fewer (“{tag[:20]}…” is too long)."
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            tags.append(tag)
    if len(tags) > MAX_TAGS:
        return [], f"An item can have at most {MAX_TAGS} tags."
    return tags, None


def set_tags(db, item_id, tags):
    db.execute("DELETE FROM item_tags WHERE item_id = ?", (item_id,))
    db.executemany(
        "INSERT INTO item_tags (item_id, tag) VALUES (?, ?)", [(item_id, t) for t in tags]
    )


def tags_by_item(db):
    """{item id: [tags sorted without regard to case]}"""
    result = {}
    for row in db.execute("SELECT item_id, tag FROM item_tags"):
        result.setdefault(row["item_id"], []).append(row["tag"])
    for tags in result.values():
        tags.sort(key=str.casefold)
    return result


def all_tags(db):
    """Every tag in use (first spelling found), sorted without regard to case."""
    found = {}
    for row in db.execute("SELECT tag FROM item_tags ORDER BY tag"):
        found.setdefault(row["tag"].casefold(), row["tag"])
    return [found[k] for k in sorted(found)]
