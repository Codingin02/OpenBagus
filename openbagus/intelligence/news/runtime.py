"""News, macro, and crypto intelligence runtime for OpenBagus."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from openbagus.intelligence.news.ranker import (
    deterministic_summary,
    duplicate_group_id,
    infer_scopes,
    parse_datetime,
    dedup_and_rank,
)
from openbagus.intelligence.news.registry import NewsSourceRegistry


ENGINE_VERSION = "openbagus.intelligence.news.runtime.v1"
NEWS_DIR = Path("reports/runtime/news")
DEFAULT_LIMIT = 100
HARD_CAP = 1000
USER_AGENT = "OpenBagusResearchBot/1.0 (+local research-only runtime)"


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _strip_html(text: Any) -> str:
    raw = str(text or "")
    if raw.startswith("<") and raw.endswith(">"):
        try:
            return " ".join(ET.fromstring(f"<root>{raw}</root>").itertext())
        except ET.ParseError:
            return re.sub(r"<[^>]+>", " ", raw).strip()
    return re.sub(r"<[^>]+>", " ", raw).strip()


def _jsonl_write(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")


class NewsIntelligenceRuntime:
    """Fetch or reuse verified public news intelligence for dashboard and reports."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.registry = NewsSourceRegistry(repo_root)
        self.news_dir = repo_root / NEWS_DIR

    def run(
        self,
        *,
        refresh_live: bool = False,
        limit: int = DEFAULT_LIMIT,
        allow_degraded: bool = False,
        purpose: str = "dashboard",
    ) -> dict[str, Any]:
        self.news_dir.mkdir(parents=True, exist_ok=True)
        registry = self.registry.load()
        source_status = self.registry.write_status(registry)
        effective_limit = max(1, min(int(limit or DEFAULT_LIMIT), HARD_CAP))

        if not refresh_live:
            cached = self._load_cached()
            status = "NEWS_REFRESH_SKIPPED_OFFLINE"
            reason = "Live news fetch disabled; uses latest cache or empty deterministic fallback."
            items = cached.get("items", [])
            payload = self._payload(
                status=status,
                reason=reason,
                registry=registry,
                source_status=source_status,
                items=items,
                errors=[],
                refresh_live=False,
                effective_limit=effective_limit,
                active_source_count_this_run=0,
                fetched_source_count=0,
                purpose=purpose,
            )
            self._write_outputs(payload)
            return payload

        sources = [source for source in registry.get("sources", []) if source.get("verified") and source.get("fetch_enabled", True)]
        items: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        fetched_source_count = 0
        active_sources = sources[:effective_limit]
        for source in active_sources:
            try:
                fetched = self._fetch_source(source, per_source_limit=8)
                items.extend(fetched)
                fetched_source_count += 1
            except Exception as exc:
                errors.append(
                    {
                        "source_id": source.get("id"),
                        "source_name": source.get("source_name"),
                        "status": "FETCH_FAILED",
                        "error": str(exc)[:220],
                    }
                )
            time.sleep(min(1.5, float(source.get("rate_limit_seconds", 0.2) or 0.2)))

        ranked = dedup_and_rank(items, limit=effective_limit)
        if ranked and errors:
            status = "NEWS_REFRESH_PARTIAL"
        elif ranked:
            status = "NEWS_REFRESH_OK"
        elif errors:
            status = "NEWS_REFRESH_FAILED_NETWORK"
        else:
            status = "NEWS_REFRESH_PARTIAL" if allow_degraded else "NEWS_REFRESH_FAILED_NETWORK"

        payload = self._payload(
            status=status,
            reason="Fetched verified sources only; no paywall/login/full-article copy.",
            registry=registry,
            source_status=source_status,
            items=ranked,
            errors=errors,
            refresh_live=True,
            effective_limit=effective_limit,
            active_source_count_this_run=len(active_sources),
            fetched_source_count=fetched_source_count,
            purpose=purpose,
        )
        self._write_outputs(payload)
        return payload

    def _load_cached(self) -> dict[str, Any]:
        latest = _read_json(self.news_dir / "openbagus_news_intelligence_latest.json")
        if latest:
            return latest
        return {"items": []}

    def _fetch_source(self, source: Mapping[str, Any], *, per_source_limit: int) -> list[dict[str, Any]]:
        url = str(source.get("feed_url") or source.get("source_url") or "")
        if not url:
            return []
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, text/html;q=0.8"},
        )
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(1_500_000)
        text = raw.decode("utf-8", errors="replace")
        return self._parse_feed_stdlib(text, source, per_source_limit)

    def _parse_feed_stdlib(self, text: str, source: Mapping[str, Any], limit: int) -> list[dict[str, Any]]:
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return []
        rows: list[dict[str, Any]] = []
        for item in root.findall(".//item")[:limit]:
            title = item.findtext("title") or ""
            link = item.findtext("link") or str(source.get("source_url", ""))
            description = item.findtext("description") or ""
            published = item.findtext("pubDate") or item.findtext("published") or ""
            rows.append(self._build_item(source, title=title, article_url=link, snippet=description, published_at=published, image_url=None))
        if rows:
            return rows
        for item in root.findall(".//{http://www.w3.org/2005/Atom}entry")[:limit]:
            title = item.findtext("{http://www.w3.org/2005/Atom}title") or ""
            link_node = item.find("{http://www.w3.org/2005/Atom}link")
            link = link_node.attrib.get("href", "") if link_node is not None else str(source.get("source_url", ""))
            summary = item.findtext("{http://www.w3.org/2005/Atom}summary") or ""
            published = item.findtext("{http://www.w3.org/2005/Atom}published") or ""
            rows.append(self._build_item(source, title=title, article_url=link, snippet=summary, published_at=published, image_url=None))
        return rows

    def _build_item(
        self,
        source: Mapping[str, Any],
        *,
        title: str,
        article_url: str,
        snippet: str,
        published_at: Any,
        image_url: str | None,
    ) -> dict[str, Any]:
        dt = parse_datetime(published_at)
        iso_pub = dt.isoformat().replace("+00:00", "Z") if dt else _iso_now()
        source_scopes = list(source.get("asset_scope", []) or [])
        clean_title = re.sub(r"\s+", " ", title or "").strip()
        summary = deterministic_summary(clean_title, _strip_html(snippet))
        return {
            "title": clean_title or "Untitled",
            "article_url": article_url or str(source.get("source_url", "")),
            "source_name": str(source.get("source_name", "Unknown")),
            "source_id": str(source.get("id", "")),
            "published_at": iso_pub,
            "summary_short": summary,
            "asset_scope": infer_scopes(clean_title, summary, source_scopes),
            "credibility_score": float(source.get("credibility_score", 0.5) or 0.5),
            "image_url": image_url,
            "duplicate_group_id": duplicate_group_id(clean_title, str(source.get("source_name", ""))),
        }

    def _payload(
        self,
        *,
        status: str,
        reason: str,
        registry: Mapping[str, Any],
        source_status: Mapping[str, Any],
        items: list[dict[str, Any]],
        errors: list[dict[str, Any]],
        refresh_live: bool,
        effective_limit: int,
        active_source_count_this_run: int,
        fetched_source_count: int,
        purpose: str,
    ) -> dict[str, Any]:
        return {
            "engine_version": ENGINE_VERSION,
            "generated_at_utc": _iso_now(),
            "status": status,
            "reason": reason,
            "refresh_live": refresh_live,
            "purpose": purpose,
            "requested_limit": effective_limit,
            "item_count": len(items),
            "error_count": len(errors),
            "active_source_count_this_run": active_source_count_this_run,
            "fetched_source_count": fetched_source_count,
            "source_universe_capacity": registry.get("source_universe_capacity", 10000),
            "source_status_path": source_status.get("status_path"),
            "items": items,
            "errors": errors,
        }

    def _write_outputs(self, payload: Mapping[str, Any]) -> None:
        (self.news_dir / "openbagus_news_intelligence_latest.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )
        _jsonl_write(self.news_dir / "openbagus_news_items_latest.jsonl", payload.get("items", []))
        errors = payload.get("errors", [])
        if errors:
            (self.news_dir / "openbagus_news_errors_latest.json").write_text(
                json.dumps({"generated_at_utc": _iso_now(), "errors": errors}, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
        md_lines = [
            "# OpenBagus News Intelligence Latest",
            "",
            f"- Status: `{payload.get('status')}`",
            f"- Generated at UTC: `{payload.get('generated_at_utc')}`",
            f"- Item count: {payload.get('item_count')}",
            "",
            "## Selected Headings",
        ]
        for item in payload.get("items", [])[:15]:
            md_lines.append(f"- **{item.get('title')}** ({item.get('source_name')}) - [Link]({item.get('article_url')})")
        (self.news_dir / "openbagus_news_intelligence_latest.md").write_text(
            "\n".join(md_lines) + "\n", encoding="utf-8"
        )

    def fetch_gdelt_discovery(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Discover multi-publisher articles using the public GDELT DOC 2.0 API."""
        import urllib.parse
        encoded = urllib.parse.quote(query)
        url = f"https://api.gdeltproject.org/api/v2/doc/doc?query={encoded}&mode=ArtList&maxrecords={max(1, min(limit, 20))}&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            articles = payload.get("articles") or []
            results: list[dict[str, Any]] = []
            for art in articles[:limit]:
                art_url = str(art.get("url") or "").strip()
                title = str(art.get("title") or "").strip()
                domain = str(art.get("domain") or "GDELT Discovery").strip()
                seendate = str(art.get("seendate") or "")
                # Format seendate (e.g. 20261010T120000Z -> ISO)
                dt_iso = _iso_now()
                if len(seendate) >= 8:
                    try:
                        dt = datetime.strptime(seendate[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
                        dt_iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    except Exception:
                        pass
                if art_url and title:
                    results.append({
                        "title": title,
                        "article_url": art_url,
                        "source_name": domain,
                        "source_id": f"gdelt_{domain.replace('.', '_')}",
                        "published_at": dt_iso,
                        "summary_short": deterministic_summary(title),
                        "asset_scope": infer_scopes(title, "", []),
                        "credibility_score": 0.85,
                        "duplicate_group_id": duplicate_group_id(title, domain),
                    })
            return results
        except Exception:
            return []

    def get_relevant_news_with_citations(self, topic_or_asset: str, limit: int = 4) -> dict[str, Any]:
        """Retrieves verified news matching a topic/asset and assigns deterministic [1], [2] citations."""
        query_lower = topic_or_asset.lower().strip()
        cached = self._load_cached().get("items", [])
        if not cached:
            try:
                res = self.run(refresh_live=True, limit=12)
                cached = res.get("items", [])
            except Exception:
                pass

        matched: list[dict[str, Any]] = []

        # Search synonyms and asset scopes
        synonyms = {query_lower}
        if query_lower in {"btc", "bitcoin"}:
            synonyms.update({"btc", "bitcoin", "crypto"})
        elif query_lower in {"eth", "ethereum"}:
            synonyms.update({"eth", "ether", "ethereum", "crypto"})
        elif query_lower in {"sol", "solana"}:
            synonyms.update({"sol", "solana", "crypto"})
        elif query_lower in {"bbca", "bbri", "bmri", "bbni"}:
            synonyms.update({query_lower, "bank", "ihsg", "saham", "id_equity"})

        # 1. Filter local cached verified articles
        for item in cached:
            title = str(item.get("title", "")).lower()
            summary = str(item.get("summary_short", "")).lower()
            scopes = [str(s).lower() for s in item.get("asset_scope", [])]
            if any(syn in title or syn in summary or syn in scopes for syn in synonyms):
                matched.append(dict(item))

        # 2. If insufficient matched items and network permitted, try GDELT discovery
        if len(matched) < limit:
            gdelt_items = self.fetch_gdelt_discovery(query_lower, limit=limit - len(matched))
            matched.extend(gdelt_items)

        # 3. If still empty, fall back to top general verified news
        if not matched:
            matched = [dict(it) for it in cached[:limit]]

        # Assign deterministic citation IDs
        deduped = dedup_and_rank(matched, limit=limit)
        citations_text_lines: list[str] = []
        final_items: list[dict[str, Any]] = []

        for idx, item in enumerate(deduped, 1):
            cit_id = f"[{idx}]"
            item["citation_id"] = cit_id
            pub_date = str(item.get("published_at", "")).split("T")[0] or "N/A"
            source_name = item.get("source_name", "Unknown Source")
            url = item.get("article_url", "")
            title = item.get("title", "Untitled")

            citations_text_lines.append(f"{cit_id} \"{title}\" - {source_name} ({pub_date}) <{url}>")
            final_items.append(item)

        return {
            "query": topic_or_asset,
            "count": len(final_items),
            "items": final_items,
            "citations_text": "\n".join(citations_text_lines),
        }
