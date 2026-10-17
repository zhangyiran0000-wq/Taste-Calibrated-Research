"""Taste profiles: a short Markdown file that says what one reader finds worth reading.

A profile only ranks the reading list. It decides which works with a stated but unverified reason
are "treasure candidates". The gate questions never see it, so taste cannot change how the evidence
is judged.

Where profiles come from, in order:
  1. a path to a file             --taste my_taste.md
  2. a profile in ./taste.json    --taste mine      (your own profiles, kept in one JSON file; the page writes it)
  3. ./profiles/<name>.md         --taste mine      (older Markdown profiles)
  4. a preset shipped with the tool --taste practitioner | theorist | newcomer
With no --taste, the default profile in ./taste.json is used, else ./taste.md when it exists.

taste.json:
  {"default": "mine",
   "profiles": {"mine": {"title": "Mine", "taste": "what I find worth reading, free text",
                         "papers": [{"ref": "Deep Residual Learning", "score": 0.9, "comment": "one clear idea"}]}}}
  score is your own rating of a paper's contribution, 0 to 1 (or null).

Format (all sections optional):
  # Name                    the first heading names the profile in the report
  one line on who this reader is
  ## Problems I care about
  ## Ideas I like
  ## Ideas I usually skip
  ## Papers I liked          "Title (year): why". Examples steer the scorer more than descriptions do.
  ## Papers I disliked       patterns work as well as named papers
"""
from __future__ import annotations

import os
import re
from typing import List, Tuple

PRESETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets")
USER_DIR = "profiles"
STORE = "taste.json"


def build_profile(name: str, text: str, papers: List[dict]) -> str:
    """Markdown the taste scorer reads: free text, then the rated papers as liked / disliked anchors."""
    liked, disliked, noted = [], [], []
    for p in papers or []:
        ref = " ".join(str(p.get("ref") or "").split())
        if not ref:
            continue
        score = p.get("score")
        comment = " ".join(str(p.get("comment") or "").split())
        line = f"- {ref}" + (f" (my score {score:.2f})" if isinstance(score, (int, float)) else "") + (f": {comment}" if comment else "")
        (noted if not isinstance(score, (int, float)) else liked if score >= 0.5 else disliked).append(line)
    out = [f"# {name.strip() or 'This report'}", ""]
    if (text or "").strip():
        out += [text.strip(), ""]
    if liked or disliked or noted:
        out += ["Scores are my own rating of a paper's contribution, from 0 (none) to 1 (major).", ""]
    for head, rows in (("## Papers I liked", liked), ("## Papers I disliked", disliked), ("## Papers I noted", noted)):
        if rows:
            out += [head] + rows + [""]
    return "\n".join(out).rstrip() + "\n"


def load_store(base: str = ".") -> dict:
    """The taste.json store; an empty one when the file is missing or broken."""
    import json
    path = os.path.join(base, STORE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"default": "", "profiles": {}}
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
        return {"default": "", "profiles": {}}
    data.setdefault("default", "")
    return data


def save_store(data: dict, base: str = ".") -> None:
    import json
    path = os.path.join(base, STORE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def put_profile(name: str, taste: str, papers: List[dict], base: str = ".", make_default: bool = False) -> str:
    """Add or replace a profile in taste.json. Returns its key."""
    key = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", name.lower()).strip("-")[:40] or "mine"
    data = load_store(base)
    data["profiles"][key] = {"title": name.strip(), "taste": (taste or "").strip(),
                             "papers": [{"ref": p.get("ref"), "score": p.get("score"), "comment": p.get("comment") or ""}
                                        for p in papers or [] if p.get("ref")]}
    if make_default or not data.get("default"):
        data["default"] = key
    save_store(data, base)
    return key


def _name(text: str, path: str) -> str:
    m = re.search(r"^#\s+(.+?)\s*$", text, re.M)
    if m and not m.group(1).lower().startswith("what i find worth reading"):
        return m.group(1).strip()
    return os.path.splitext(os.path.basename(path))[0]


def find_profile(spec: str) -> str:
    """Path of the profile named or given by `spec`. Raises FileNotFoundError with the choices."""
    if os.path.isfile(spec):
        return spec
    stem = spec[:-3] if spec.endswith(".md") else spec
    for d in (USER_DIR, PRESETS_DIR):
        p = os.path.join(d, stem + ".md")
        if os.path.isfile(p):
            return p
    names = ", ".join([n for n, _, _ in list_profiles()] + list(load_store().get("profiles", {}))) or "none"
    raise FileNotFoundError(f"no taste profile '{spec}'. Give a file path or one of: {names}")


def load_profile(spec: str) -> Tuple[str, str, str]:
    """(name, text, path). Empty strings when `spec` is empty."""
    if not spec:
        return "", "", ""
    if not os.path.isfile(spec):
        entry = load_store().get("profiles", {}).get(spec[:-3] if spec.endswith(".md") else spec)
        if isinstance(entry, dict):
            title = entry.get("title") or spec
            return title, build_profile(title, entry.get("taste") or "", entry.get("papers") or []).strip(), f"{STORE}#{spec}"
    path = find_profile(spec)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    return _name(text, path), text, path


def default_spec() -> str:
    d = load_store().get("default")
    if d and d in load_store().get("profiles", {}):
        return d
    return "taste.md" if os.path.isfile("taste.md") else ""


def list_profiles(user_dir: str = USER_DIR) -> List[Tuple[str, str, str]]:
    """(name to pass to --taste, path, 'yours' | 'preset')."""
    out = []
    for d, kind in ((user_dir, "yours"), (PRESETS_DIR, "preset")):
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith(".md") and not f.startswith(("_", ".")) and f.lower() != "readme.md":
                    out.append((f[:-3], os.path.join(d, f), kind))
    return out


def rated_papers(profile_text: str) -> List[dict]:
    """The papers you rated in a profile ("## Papers I liked / disliked" lines with "(my score 0.85)"), as
    [{"ref", "score", "comment"}]. Only lines with your own score count; pattern lines in brackets are skipped."""
    out, section = [], False
    for line in (profile_text or "").splitlines():
        low = line.strip().lower()
        if low.startswith("## "):
            section = low in ("## papers i liked", "## papers i disliked", "## papers i noted")
            continue
        m = re.match(r"^-\s+(?P<ref>.+?)\s+\(my score (?P<score>[0-9.]+)\)(?::\s+(?P<why>.*))?$", line.strip()) if section else None
        if m and not m.group("ref").startswith("("):
            try:
                score = max(0.0, min(1.0, float(m.group("score"))))
            except ValueError:
                continue
            out.append({"ref": m.group("ref").strip(), "score": score, "comment": (m.group("why") or "").strip()})
    return out


def _norm_ref(s: str) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", (s or "").lower())


def profile_key(name: str) -> str:
    """The key a profile name gets in taste.json (as put_profile makes it)."""
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", (name or "").lower()).strip("-")[:40] or "mine"


def rated_profile(prefer: str = "", base: str = ".") -> str:
    """Which taste.json profile your ratings go to: `prefer` when it exists, else the default, else "mine"."""
    data = load_store(base)
    for k in (prefer, profile_key(prefer) if prefer else "", data.get("default") or ""):
        if k and k in data["profiles"]:
            return k
    return "mine"


def rate_paper(ref: str, score, comment: str = "", profile: str = "", base: str = ".") -> dict:
    """Add, change or (score None) remove your rating of one paper in a taste.json profile.
    Returns {"profile", "title", "rated", "papers"}. The profile is created (as the default) when there is none."""
    data = load_store(base)
    key = rated_profile(profile, base)
    prof = data["profiles"].setdefault(key, {"title": "Mine" if key == "mine" else key, "taste": "", "papers": []})
    papers = [p for p in prof.get("papers") or [] if isinstance(p, dict) and p.get("ref")]
    hit = next((p for p in papers if _norm_ref(p["ref"]) == _norm_ref(ref)), None)
    if score is None:
        papers = [p for p in papers if p is not hit]
    else:
        score = round(max(0.0, min(1.0, float(score))), 2)
        if hit:
            hit["score"] = score
            if comment:
                hit["comment"] = comment
        else:
            papers.append({"ref": " ".join(str(ref).split()), "score": score, "comment": comment or ""})
    prof["papers"] = papers
    if not data.get("default") or data["default"] not in data["profiles"]:
        data["default"] = key
    save_store(data, base)
    return {"profile": key, "title": prof.get("title") or key, "papers": papers,
            "rated": sum(1 for p in papers if isinstance(p.get("score"), (int, float)))}


def drop_rated(profile_text: str, refs) -> str:
    """The profile without the rated-paper lines for `refs` (to score those papers without their own rating)."""
    gone = {_norm_ref(r) for r in refs}
    out = []
    for line in (profile_text or "").splitlines():
        m = re.match(r"^-\s+(.+?)(?:\s+\(my score [0-9.]+\))?(?::\s+.*)?$", line.strip())
        if m and _norm_ref(m.group(1)) in gone:
            continue
        out.append(line)
    return "\n".join(out)

