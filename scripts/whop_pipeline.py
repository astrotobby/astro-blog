"""Reliable Whop clipping pipeline core.

This module is intentionally provider-agnostic: discovery, rendering, and publishing
are adapters. It provides the deterministic safety layer around them: normalization,
scoring, clip validation, idempotency, and a manual-submission packet.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from urllib.request import Request, urlopen
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


ALLOWED_PLATFORMS = {"youtube", "instagram", "tiktok", "facebook", "x"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_https(value: str, field_name: str) -> str:
    if not isinstance(value, str) or urlparse(value).scheme != "https":
        raise ValueError(f"{field_name} must be an HTTPS URL")
    return value


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


@dataclass(frozen=True)
class Campaign:
    campaign_id: str
    title: str
    campaign_url: str
    campaign_type: str
    owner: str = ""
    allowed_platforms: tuple[str, ...] = ()
    allowed_country_codes: tuple[str, ...] = ()
    reward_per_1000_views: float = 0.0
    min_payout: float = 0.0
    max_payout: float = 0.0
    remaining_budget: float = 0.0
    source_material_urls: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()
    prohibited_content: tuple[str, ...] = ()
    disclosures: tuple[str, ...] = ()
    approval_required_before_publish: bool = False
    retrieved_at: str = ""
    raw_source_url: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Campaign":
        if not isinstance(raw, dict):
            raise ValueError("campaign must be an object")
        campaign_id = str(raw.get("campaign_id", "")).strip()
        title = str(raw.get("title", "")).strip()
        if not campaign_id or not title:
            raise ValueError("campaign_id and title are required")
        url = require_https(str(raw.get("campaign_url", "")), "campaign_url")
        platforms = tuple(sorted(set(as_list(raw.get("allowed_platforms")))))
        unknown = set(platforms) - ALLOWED_PLATFORMS
        if unknown:
            raise ValueError(f"unsupported platforms: {sorted(unknown)}")
        material_urls = tuple(require_https(url, "source_material_url") for url in as_list(raw.get("source_material_urls")))
        raw_source = str(raw.get("raw_source_url", "")).strip()
        if raw_source:
            require_https(raw_source, "raw_source_url")
        return cls(
            campaign_id=campaign_id,
            title=title,
            campaign_url=url,
            campaign_type=str(raw.get("campaign_type", "clipping")).strip().lower(),
            owner=str(raw.get("owner", "")).strip(),
            allowed_platforms=platforms,
            allowed_country_codes=tuple(sorted(set(x.upper() for x in as_list(raw.get("allowed_country_codes"))))),
            reward_per_1000_views=max(0.0, as_float(raw.get("reward_per_1000_views"))),
            min_payout=max(0.0, as_float(raw.get("min_payout"))),
            max_payout=max(0.0, as_float(raw.get("max_payout"))),
            remaining_budget=max(0.0, as_float(raw.get("remaining_budget"))),
            source_material_urls=material_urls,
            requirements=tuple(as_list(raw.get("requirements"))),
            prohibited_content=tuple(as_list(raw.get("prohibited_content"))),
            disclosures=tuple(as_list(raw.get("disclosures"))),
            approval_required_before_publish=bool(raw.get("approval_required_before_publish", False)),
            retrieved_at=str(raw.get("retrieved_at", "")) or now_iso(),
            raw_source_url=raw_source,
        )


@dataclass(frozen=True)
class ClipSpec:
    start_time: float
    end_time: float
    platform: str
    caption: str = ""
    hook: str = ""
    source_asset_hash: str = ""
    output_url: str = ""
    post_url: str = ""
    status: str = "planned"

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def key(self) -> str:
        payload = f"{self.source_asset_hash}|{self.start_time:.3f}|{self.end_time:.3f}|{self.platform}"
        return hashlib.sha256(payload.encode()).hexdigest()[:24]


def validate_clips(clips: Iterable[dict[str, Any] | ClipSpec], source_duration: float,
                   campaign: Campaign, min_seconds: float = 15, max_seconds: float = 90) -> list[ClipSpec]:
    """Validate and normalize clip plans; rejects overlap, bad ranges, and bad platforms."""
    if source_duration <= 0 or not math.isfinite(source_duration):
        raise ValueError("source_duration must be positive")
    normalized: list[ClipSpec] = []
    for raw in clips:
        item = raw if isinstance(raw, ClipSpec) else ClipSpec(
            start_time=as_float(raw.get("start_time")),
            end_time=as_float(raw.get("end_time")),
            platform=str(raw.get("platform", "")).lower().strip(),
            caption=str(raw.get("caption", "")).strip(),
            hook=str(raw.get("hook", "")).strip(),
            source_asset_hash=str(raw.get("source_asset_hash", "")).strip(),
            output_url=str(raw.get("output_url", "")).strip(),
            post_url=str(raw.get("post_url", "")).strip(),
            status=str(raw.get("status", "planned")).strip(),
        )
        if item.platform not in set(campaign.allowed_platforms):
            raise ValueError(f"clip platform {item.platform!r} is not allowed by campaign")
        if item.start_time < 0 or item.end_time > source_duration or item.end_time <= item.start_time:
            raise ValueError(f"invalid clip range {item.start_time}-{item.end_time} for source duration {source_duration}")
        if item.duration < min_seconds or item.duration > max_seconds:
            raise ValueError(f"clip duration {item.duration:.2f}s outside {min_seconds}-{max_seconds}s")
        if not item.caption:
            raise ValueError("each clip requires a caption")
        normalized.append(item)
    normalized.sort(key=lambda x: x.start_time)
    for previous, current in zip(normalized, normalized[1:]):
        if current.start_time < previous.end_time:
            raise ValueError("clip ranges overlap")
    return normalized


def score_campaign(campaign: Campaign, authorized_platforms: set[str], preferred_platform: str | None = None,
                   creator_terms: Iterable[str] = ()) -> dict[str, Any]:
    """Deterministic, explainable campaign score in [0, 100]."""
    terms = {str(t).lower() for t in creator_terms}
    title_terms = set(campaign.title.lower().split())
    fit = min(1.0, len(terms & title_terms) / max(1, min(3, len(terms)))) if terms else 0.5
    platform_fit = len(set(campaign.allowed_platforms) & authorized_platforms) / max(1, len(campaign.allowed_platforms))
    if preferred_platform and preferred_platform in campaign.allowed_platforms:
        platform_fit = min(1.0, platform_fit + 0.15)
    payout = min(1.0, campaign.reward_per_1000_views / 5.0)
    budget = min(1.0, campaign.remaining_budget / 5000.0)
    clarity = min(1.0, (len(campaign.requirements) + len(campaign.source_material_urls)) / 8.0)
    score = round(100 * (0.25 * platform_fit + 0.20 * fit + 0.20 * payout + 0.15 * budget + 0.20 * clarity), 2)
    return {"campaign_id": campaign.campaign_id, "score": score, "components": {
        "platform_fit": round(platform_fit, 4), "creator_fit": round(fit, 4),
        "payout": round(payout, 4), "budget": round(budget, 4), "clarity": round(clarity, 4)},
        "reasons": ["authorized platform overlap" if platform_fit else "no authorized platform overlap",
                    "campaign has structured requirements/materials" if clarity >= 0.5 else "campaign rules/materials are incomplete"]}


class StateStore:
    """Atomic JSON state store for idempotent clip and publish operations."""
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"items": {}}
        except (FileNotFoundError, json.JSONDecodeError):
            return {"items": {}}

    def put_once(self, key: str, value: dict[str, Any]) -> bool:
        data = self.load()
        items = data.setdefault("items", {})
        if key in items:
            return False
        items[key] = {**value, "created_at": now_iso()}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)
        return True


def build_submission_packet(campaign: Campaign, clips: Iterable[ClipSpec], selected_score: dict[str, Any] | None = None) -> dict[str, Any]:
    clip_list = [asdict(c) | {"duration": round(c.duration, 3), "clip_key": c.key} for c in clips]
    return {"status": "ready_for_manual_posting", "generated_at": now_iso(),
            "posting_mode": "manual",
            "campaign": asdict(campaign), "selection": selected_score or {}, "clips": clip_list,
            "checklist": {"campaign_rules_captured": bool(campaign.requirements),
                          "source_materials_captured": bool(campaign.source_material_urls),
                          "public_post_urls_present": all(bool(c["post_url"]) for c in clip_list) if clip_list else False,
                          "manual_posting_required": True,
                          "manual_whop_submission_required": True}}


def notification_text(packet: dict[str, Any], packet_url: str = "") -> str:
    campaign = packet["campaign"]
    lines = [
        "🎬 Clip packet ready for manual posting",
        f"Campaign: {campaign['title']}",
        f"Clips: {len(packet['clips'])}",
        f"Campaign link: {campaign['campaign_url']}",
        "Posting: MANUAL — no social platform was published to",
        "Whop submission: MANUAL after you post",
    ]
    if packet_url:
        lines.append(f"Packet: {packet_url}")
    return "\n".join(lines)


def notify_packet(packet: dict[str, Any], provider: str, webhook_url: str = "",
                  packet_url: str = "", dry_run: bool = False) -> dict[str, Any]:
    """Send an explicit opt-in alert; never runs unless --notify-provider is supplied."""
    provider = provider.lower().strip()
    text = notification_text(packet, packet_url)
    if dry_run:
        return {"ok": True, "provider": provider, "dry_run": True, "text": text}
    if provider == "discord":
        url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL", "")
        payload = {"content": text}
    elif provider == "telegram":
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        url = webhook_url or (f"https://api.telegram.org/bot{token}/sendMessage" if token and chat_id else "")
        payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    else:
        raise ValueError("notify provider must be telegram or discord")
    if not url:
        raise ValueError(f"missing {provider} notification credentials or webhook URL")
    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
        return {"ok": True, "provider": provider, "response": body[:500]}
    except Exception as exc:
        return {"ok": False, "provider": provider, "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a campaign and clip plan; emit a submission packet.")
    parser.add_argument("campaign_json", type=Path)
    parser.add_argument("clips_json", type=Path)
    parser.add_argument("--source-duration", type=float, required=True)
    parser.add_argument("--state", type=Path, default=Path(".pipeline/state/whop.json"))
    parser.add_argument("--output", type=Path, default=Path(".pipeline/whop-submission.json"))
    parser.add_argument("--notify-provider", choices=["telegram", "discord"], help="send an alert after packet creation")
    parser.add_argument("--notify-webhook-url", default="", help="optional provider webhook URL; otherwise use environment credentials")
    parser.add_argument("--notify-dry-run", action="store_true", help="render notification payload without network access")
    args = parser.parse_args()
    campaign = Campaign.from_dict(json.loads(args.campaign_json.read_text(encoding="utf-8")))
    clips_raw = json.loads(args.clips_json.read_text(encoding="utf-8"))
    clips = validate_clips(clips_raw["clips"] if isinstance(clips_raw, dict) else clips_raw, args.source_duration, campaign)
    store = StateStore(args.state)
    for clip in clips:
        store.put_once(f"{campaign.campaign_id}:{clip.key}", {"campaign_id": campaign.campaign_id, "clip": asdict(clip)})
    packet = build_submission_packet(campaign, clips)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(packet, indent=2, ensure_ascii=False), encoding="utf-8")
    notification = None
    if args.notify_provider:
        notification = notify_packet(packet, args.notify_provider, args.notify_webhook_url,
                                      str(args.output), args.notify_dry_run)
        if not notification.get("ok"):
            raise RuntimeError(f"notification failed: {notification.get('error', 'unknown error')}")
    print(json.dumps({"ok": True, "clips": len(clips), "output": str(args.output), "notification": notification}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
