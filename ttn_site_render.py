"""Site renderer (website Phase 2): turns site.sqlite into the static dist/
tree. ttn_site.py builds the substrate (site.sqlite + slug registry); this
module renders it. Reached as `ttn_data.py site` (render stage).

This module currently holds the pure core only: the URL authority
(url_for), the dist-path mapping (dist_path), and the write-if-changed file
writer. Template rendering and the Jinja2 Environment land in a later task.
"""
import os


def url_for(kind: str, key: str) -> str:
    """The single URL authority — every template link goes through this, no
    hand-built hrefs anywhere.

    kind in {"work", "composer", "episode", "recording", "browse"}; ValueError
    on anything else.

    - "work": split on the FIRST ':' -> /work/{composer_part}/{work_part}/.
      A colon-less slug (the hash-fallback class, e.g. 'wbd926ff4') ->
      /work/{slug}/. A collision suffix ('abel:trio-in-f-major-for-2') flows
      through the same first-colon split.
    - "episode": key is an ISO date 'YYYY-MM-DD' -> /episode/YYYY/MM/DD/.
    - "composer" / "recording": key is used verbatim -> /{kind}/{key}/.
    - "browse": key is the URL name (hyphenated) -> /browse/{key}/. Callers
      holding a payload name (underscore-separated, e.g. 'house_recordings')
      must map it first via browse_url_name.
    """
    if kind == "work":
        composer_part, sep, work_part = key.partition(":")
        if sep:
            return f"/work/{composer_part}/{work_part}/"
        return f"/work/{key}/"
    if kind == "episode":
        year, month, day = key.split("-")
        return f"/episode/{year}/{month}/{day}/"
    if kind == "composer":
        return f"/composer/{key}/"
    if kind == "recording":
        return f"/recording/{key}/"
    if kind == "browse":
        return f"/browse/{key}/"
    raise ValueError(f"url_for: unknown kind {kind!r}")


def browse_url_name(payload_name: str) -> str:
    """Map a browse payload name (underscore-separated, as stored in
    browse.name) to the URL segment (hyphenated) that url_for("browse", ...)
    expects. 'house_recordings' -> 'house-recordings'; 'works' -> 'works'."""
    return payload_name.replace("_", "-")


def dist_path(url: str, dist_dir: str) -> str:
    """Map a url_for()-produced URL to its dist/ file path: strip leading/
    trailing slashes, join under dist_dir, append index.html. Root '/' ->
    '{dist_dir}/index.html'."""
    trimmed = url.strip("/")
    if trimmed:
        return os.path.join(dist_dir, trimmed, "index.html")
    return os.path.join(dist_dir, "index.html")


def write_if_changed(path: str, content: str) -> bool:
    """Write content (str, UTF-8, verbatim — no trailing newline appended) to
    path, creating parent directories as needed. Skips the write (mtime
    untouched) when the existing file's bytes already match; returns True iff
    it wrote."""
    new_bytes = content.encode("utf-8")
    if os.path.exists(path):
        with open(path, "rb") as f:
            if f.read() == new_bytes:
                return False
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as f:
        f.write(new_bytes)
    return True
