"""End-to-end automation service (M11).

Connects the stages the worker already runs and adds the publish-time
decision logic: daily targets, stock levels, pause/resume. Publishing
never fabricates content — an empty stock publishes nothing and says
so; a met daily target waits for the next slot; a paused channel is
skipped entirely. Operational summaries land in the append-only audit
trail so the studio's day is reconstructable.

Start/Stop era: the service also owns the per-channel automation state
machine (stopped/running/paused/error), the stock-target-aware
horizontal refill, channel-scoped job cancellation on Stop, and the
followed-character associations used by the channel settings modal.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import (
    Channel,
    ChannelCharacter,
    Character,
    ClipCandidate,
    Job,
    MediaAsset,
    PublishedVideo,
    PublishingProfile,
    RenderedClip,
    SourceChannel,
    SourceVideo,
)
from app.services.channel_service import record_event
from app.services.publishing_service import PublishingService
from app.services.publishing_schedule import ScheduleError
from app.services.source_rules import age_exclusion


class AutomationError(Exception):
    """Automation failure with a user-facing Turkish message."""


# Yeni is baslatilmasina izin veren durumlar: 'paused' yayinlamayi
# bekletir ama uretim (indirme/render) surer; 'stopped' ve 'error'
# tamamen durur.
WORK_STATES = ("running", "paused")


class AutomationService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._publishing = PublishingService(sessionmaker, settings)

    async def profile(self, channel_id: int) -> PublishingProfile:
        """Get-or-create the channel's publishing profile."""
        async with self._sessionmaker() as session:
            row = (
                (
                    await session.execute(
                        sa.select(PublishingProfile).where(
                            PublishingProfile.channel_id == channel_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if row is None:
                # Ilk olusumda stok hedefi site ayarindaki varsayilandan
                # baslar (genellikle 3).
                from app.services.settings_service import SettingsService

                effective = await SettingsService(
                    self._sessionmaker, self._settings
                ).effective_settings()
                row = PublishingProfile(
                    channel_id=channel_id,
                    horizontal_stock_target=(
                        effective.horizontal_stock_target_default
                    ),
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)
            return row

    # --- Start/Stop durum makinesi ---

    async def set_automation_state(
        self, channel_id: int, state: str
    ) -> PublishingProfile:
        if state not in ("stopped", "running", "paused", "error"):
            raise AutomationError("Gecersiz otomasyon durumu.")
        profile = await self.profile(channel_id)
        async with self._sessionmaker() as session:
            row = await session.get(PublishingProfile, profile.id)
            row.automation_state = state
            await session.commit()
            await session.refresh(row)
            return row

    async def start(self, channel_id: int) -> dict[str, Any]:
        """Baslat: durumu 'running' yap, siradaki yatay kaynagi hemen
        kuyruga ekle (feed araligini beklemeden)."""
        profile = await self.set_automation_state(channel_id, "running")
        await self._audit(channel_id, "automation.started", {})
        refill = await refill_channel_stock(
            self._sessionmaker, self._settings, channel_id
        )
        return {
            "channel_id": channel_id,
            "automation_state": profile.automation_state,
            "refill": refill,
        }

    async def stop(self, channel_id: int) -> dict[str, Any]:
        """Durdur: yeni isler baslamaz. Bu kanala ait SIRADAKI isler
        iptal edilir; suruyen isler guvenli sekilde tamamlanir (yarim
        cikti asla hazir olarak isaretlenmez)."""
        profile = await self.set_automation_state(channel_id, "stopped")
        cancelled = await self.cancel_channel_jobs(channel_id)
        await self._audit(
            channel_id, "automation.stopped", {"cancelled_jobs": cancelled}
        )
        return {
            "channel_id": channel_id,
            "automation_state": profile.automation_state,
            "cancelled_jobs": cancelled,
        }

    async def pause(self, channel_id: int) -> dict[str, Any]:
        """Duraklat: yayinlama bekler, uretim surer."""
        profile = await self.set_automation_state(channel_id, "paused")
        await self._audit(channel_id, "automation.paused", {})
        return {"channel_id": channel_id, "automation_state": profile.automation_state}

    async def mark_error(self, channel_id: int, reason: str) -> None:
        """Kalici is hatasi: kanali mudahale bekleyen 'error' durumuna
        al (kullanici tekrar Baslatabilir)."""
        profile = await self.profile(channel_id)
        if profile.automation_state == "running":
            await self.set_automation_state(channel_id, "error")
            await self._audit(
                channel_id, "automation.error", {"reason": reason[:500]}
            )

    async def cancel_channel_jobs(self, channel_id: int) -> int:
        """Bu kanala ait siradaki (queued) isleri kontrollu iptal et.
        Calisan islere dokunulmaz; iptal edilen islerin veritabani
        durumu tutarli kalir (jobs.cancel)."""
        from app.services.job_service import JobService
        from app.services.status_service import StatusService

        status = StatusService(self._sessionmaker, self._settings)
        jobs = await status._channel_jobs(channel_id, statuses=("queued",))
        service = JobService(self._sessionmaker, self._settings)
        cancelled = 0
        for job in jobs:
            try:
                await service.cancel(job.id)
                cancelled += 1
            except Exception:  # noqa: BLE001 - iptal best-effort
                continue
        return cancelled

    # --- takip edilen karakterler (kanal ayarlari) ---

    async def followed_characters(self, channel_id: int) -> list[dict]:
        """Kanalin takip ettigi karakterler; karakter basina platform
        hesabi sayisi da doner (kaynaklar kaynak kanallarinda yasar)."""
        async with self._sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        sa.select(Character, ChannelCharacter)
                        .join(
                            ChannelCharacter,
                            ChannelCharacter.character_id == Character.id,
                        )
                        .where(ChannelCharacter.channel_id == channel_id)
                        .order_by(Character.name)
                    )
                )
                .all()
            )
            result = []
            for character, follow in rows:
                source_count = int(
                    (
                        await session.execute(
                            sa.select(sa.func.count())
                            .select_from(SourceChannel)
                            .where(
                                SourceChannel.channel_id == channel_id,
                                SourceChannel.character_id == character.id,
                            )
                        )
                    ).scalar()
                    or 0
                )
                result.append(
                    {
                        "character_id": character.id,
                        "name": character.name,
                        "source_count": source_count,
                        "followed_at": (
                            follow.created_at.isoformat()
                            if follow.created_at
                            else None
                        ),
                    }
                )
            return result

    async def set_followed_characters(
        self, channel_id: int, character_ids: list[int]
    ) -> list[dict]:
        """Takip listesini degistir: eksikleri ekle, kaldirilanlari sil.
        Kaynak kanallar silinmez; yalnizca takip iliskisi degisir."""
        if len(set(character_ids)) != len(character_ids):
            raise AutomationError("Karakter listesinde tekrar var.")
        async with self._sessionmaker() as session:
            existing_chars = set(
                (
                    await session.execute(sa.select(Character.id))
                )
                .scalars()
                .all()
            )
            for cid in character_ids:
                if cid not in existing_chars:
                    raise AutomationError(f"Karakter bulunamadi: {cid}")
            current = set(
                (
                    await session.execute(
                        sa.select(ChannelCharacter.character_id).where(
                            ChannelCharacter.channel_id == channel_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            wanted = set(character_ids)
            for cid in sorted(wanted - current):
                session.add(
                    ChannelCharacter(channel_id=channel_id, character_id=cid)
                )
            if current - wanted:
                await session.execute(
                    sa.delete(ChannelCharacter).where(
                        ChannelCharacter.channel_id == channel_id,
                        ChannelCharacter.character_id.in_(
                            sorted(current - wanted)
                        ),
                    )
                )
            record_event(
                session,
                channel_id,
                "automation.characters",
                {"followed": sorted(wanted)},
            )
            await session.commit()
        return await self.followed_characters(channel_id)

    # --- kanal ayarlari (modal) ---

    async def update_channel_settings(
        self,
        channel_id: int,
        *,
        horizontal_stock_target: int | None = None,
        daily_vertical_limit: int | None = None,
        daily_horizontal_limit: int | None = None,
        publish_times: list[str] | None = None,
        publish_times_vertical: list[str] | None = None,
        title_mode: str | None = None,
        description_mode: str | None = None,
        tags_mode: str | None = None,
        content_warning_mode: str | None = None,
        ai_disclosure_mode: str | None = None,
        channel_system_prompt: str | None = None,
    ) -> PublishingProfile:
        from app.services.publishing_schedule import (
            ScheduleError,
            parse_publish_times,
        )

        profile = await self.profile(channel_id)
        modes = {
            "title_mode": title_mode,
            "description_mode": description_mode,
            "tags_mode": tags_mode,
            "content_warning_mode": content_warning_mode,
            "ai_disclosure_mode": ai_disclosure_mode,
        }
        for field, value in modes.items():
            if value is not None and value not in ("auto", "on", "off"):
                raise AutomationError(
                    f"{field} 'auto', 'on' veya 'off' olmali."
                )
        if horizontal_stock_target is not None and not (
            1 <= horizontal_stock_target <= 50
        ):
            raise AutomationError(
                "Yatay stok hedefi 1..50 arasinda olmali."
            )
        for label, value in (
            ("Gunluk dikey limiti", daily_vertical_limit),
            ("Gunluk yatay limiti", daily_horizontal_limit),
        ):
            if value is not None and not (0 <= value <= 50):
                raise AutomationError(f"{label} 0..50 arasinda olmali.")
        # Yayin saatleri: 'HH:MM' listeleri, yon bazli ayri.
        for field, value in (
            ("publish_times", publish_times),
            ("publish_times_vertical", publish_times_vertical),
        ):
            if value is not None:
                try:
                    parse_publish_times(value)
                except ScheduleError as exc:
                    raise AutomationError(
                        f"Yayin saatleri gecersiz: {exc}"
                    ) from exc
        async with self._sessionmaker() as session:
            row = await session.get(PublishingProfile, profile.id)
            if horizontal_stock_target is not None:
                row.horizontal_stock_target = horizontal_stock_target
            if daily_vertical_limit is not None:
                row.daily_clip_target = daily_vertical_limit
            if daily_horizontal_limit is not None:
                row.daily_horizontal_limit = daily_horizontal_limit
            settings = dict(row.settings or {})
            if publish_times is not None:
                settings["publish_times"] = publish_times
            if publish_times_vertical is not None:
                settings["publish_times_vertical"] = publish_times_vertical
            row.settings = settings
            for field, value in modes.items():
                if value is not None:
                    setattr(row, field, value)
            if channel_system_prompt is not None:
                if len(channel_system_prompt) > 8000:
                    raise AutomationError(
                        "Kanal sistem promptu en fazla 8000 karakter olabilir."
                    )
                row.channel_system_prompt = (
                    channel_system_prompt.strip() or None
                )
            await session.commit()
            await session.refresh(row)
            return row

    async def today_published_counts(self, channel_id: int) -> dict:
        """Bugun herkese acik yapilan videolar: yon bazli sayilar
        (Overview'in kotali kartlari bunu okur)."""
        return await self._publishing.today_published_counts(channel_id)

    async def stock_level(self, channel_id: int) -> int:
        """Ready unpublished clips: rendered, rights-authorized, not
        published. Empty stock must never trigger unsafe publication."""
        return (
            await self._count(
                sa.select(sa.func.count())
                .select_from(ClipCandidate)
                .join(
                    SourceVideo,
                    ClipCandidate.source_video_id == SourceVideo.id,
                )
                .join(
                    SourceChannel,
                    SourceVideo.source_channel_id == SourceChannel.id,
                )
                .join(
                    RenderedClip,
                    RenderedClip.clip_candidate_id == ClipCandidate.id,
                )
                .outerjoin(
                    PublishedVideo,
                    PublishedVideo.clip_candidate_id == ClipCandidate.id,
                )
                .where(
                    SourceChannel.channel_id == channel_id,
                    SourceChannel.permission_status == "authorized",
                    RenderedClip.status == "rendered",
                    PublishedVideo.id.is_(None),
                )
            )
        )

    async def daily_published_count(self, channel_id: int) -> int:
        """Publications since local midnight (profile timezone)."""
        profile = await self.profile(channel_id)
        tz_name = profile.timezone or "UTC"
        try:
            from zoneinfo import ZoneInfo

            local_now = datetime.now(ZoneInfo(tz_name))
        except Exception:  # noqa: BLE001 - bilinmeyen saat dilimi: UTC
            local_now = datetime.now(UTC)
        midnight_utc = local_now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ).astimezone(UTC)
        return (
            await self._count(
                sa.select(sa.func.count())
                .select_from(PublishedVideo)
                .where(
                    PublishedVideo.channel_id == channel_id,
                    PublishedVideo.status == "verified",
                    PublishedVideo.published_at >= midnight_utc,
                )
            )
        )

    async def publish_for_channel(
        self, channel_id: int, orientation: str | None = None
    ) -> dict:
        """Scheduled-public publish decision: this step only flips an
        already-uploaded (verified, private) video to public — uploads
        happen when metadata is approved. Daily limits are per
        orientation (vertical: daily_clip_target, horizontal:
        daily_horizontal_limit). Orientation parametresi verilirse
        yalnızca o yön denenir (worker yön bazlı due hesaplar)."""
        profile = await self.profile(channel_id)
        settings = profile.settings or {}
        if profile.automation_state == "stopped":
            return {
                "channel_id": channel_id,
                "published": 0,
                "reason": "otomasyon durduruldu",
            }
        if profile.automation_state == "error":
            return {
                "channel_id": channel_id,
                "published": 0,
                "reason": "kanal hata durumunda; tekrar baslatilmali",
            }
        if profile.automation_state == "paused" or settings.get("paused"):
            return {
                "channel_id": channel_id,
                "published": 0,
                "reason": "kanal duraklatildi",
            }
        if orientation is not None and orientation not in (
            "vertical",
            "horizontal",
        ):
            raise AutomationError("Gecersiz yon: 'vertical' ya da 'horizontal'.")
        orientations = (
            (orientation,) if orientation else ("vertical", "horizontal")
        )
        # 1) Elle planlanmış ve saati gelmiş videolar once: kullanicinin
        # takvimde yerlestirdigi saat, gunluk limit ve slot oncelikli.
        for item in orientations:
            row_id = await self._publishing.next_manual_due(
                channel_id, item
            )
            if row_id is not None:
                result = await self._publishing.make_public(row_id)
                return {
                    "channel_id": channel_id,
                    "published": 1,
                    "manual": True,
                    **result,
                }
        # 2) Slot mantigi: yon bazli saatler ve gunluk limitler.
        counts = await self._publishing.today_published_counts(channel_id)
        for item in orientations:
            limit = (
                profile.daily_clip_target
                if item == "vertical"
                else profile.daily_horizontal_limit
            )
            if limit and counts[item] >= max(0, limit):
                continue
            row_id = await self._publishing.next_ready_public(
                channel_id, item
            )
            if row_id is None:
                continue
            result = await self._publishing.make_public(row_id)
            return {"channel_id": channel_id, "published": 1, **result}
        await self._audit_no_ready(channel_id, counts)
        return {
            "channel_id": channel_id,
            "published": 0,
            "reason": "yayina hazir video yok veya gunluk limitler dolu",
            "today": counts,
        }

    async def _audit_no_ready(self, channel_id: int, counts: dict) -> None:
        """'Yayina hazir video yok' durumu saatte bir kez loglanir.

        Bu olay her yayin denetiminde (yaklasik 10 dakikada bir)
        tekrarlaniyordu ve gunde 100+ kayitla gercek hatalari
        gomuyordu (2026-10-23 kullanci sikayeti). Ayni durum icin son
        kayittan bir saat gecmeden yenisi yazilmaz.

        Dikey ve yatay yayin denetimleri eszamanli publish_due isleri
        olarak calisir; ikisi de ayni anda "son kayit yok" gorup ayni
        olayi iki kez yaziyordu (2026-10-26 canli olay: 2 ms arayla iki
        satir, panelde cift bildirim). Kanal satiri kilitlenip kontrol
        ve yazma tek islemde yapilir."""
        from datetime import UTC, datetime

        from app.models import AuditEvent, Channel

        async with self._sessionmaker() as session:
            await session.execute(
                sa.select(Channel.id)
                .where(Channel.id == channel_id)
                .with_for_update()
            )
            last = (
                await session.execute(
                    sa.select(AuditEvent.created_at)
                    .where(
                        AuditEvent.channel_id == channel_id,
                        AuditEvent.event_type == "publish.no_ready",
                    )
                    .order_by(AuditEvent.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if last is not None:
                age = (datetime.now(UTC) - last).total_seconds()
                if age < 3600:
                    return
            record_event(
                session, channel_id, "publish.no_ready", {"today": counts}
            )
            await session.commit()

    async def operational_summary(self, channel_id: int) -> dict:
        """Stage counts + today's publishing state; audited."""
        profile = await self.profile(channel_id)
        summary = {
            "channel_id": channel_id,
            "discovered": await self._count(
                sa.select(sa.func.count())
                .select_from(SourceVideo)
                .join(
                    SourceChannel,
                    SourceVideo.source_channel_id == SourceChannel.id,
                )
                .where(SourceChannel.channel_id == channel_id)
            ),
            "planned": await self._count(
                sa.select(sa.func.count())
                .select_from(SourceVideo)
                .join(
                    SourceChannel,
                    SourceVideo.source_channel_id == SourceChannel.id,
                )
                .where(
                    SourceChannel.channel_id == channel_id,
                    SourceVideo.status == "planned",
                )
            ),
            "processed": await self._count(
                sa.select(sa.func.count())
                .select_from(SourceVideo)
                .join(
                    SourceChannel,
                    SourceVideo.source_channel_id == SourceChannel.id,
                )
                .where(
                    SourceChannel.channel_id == channel_id,
                    SourceVideo.status == "processed",
                )
            ),
            "candidates": await self._count(
                sa.select(sa.func.count())
                .select_from(ClipCandidate)
                .join(
                    SourceVideo,
                    ClipCandidate.source_video_id == SourceVideo.id,
                )
                .join(
                    SourceChannel,
                    SourceVideo.source_channel_id == SourceChannel.id,
                )
                .where(SourceChannel.channel_id == channel_id)
            ),
            "rendered": await self._count(
                sa.select(sa.func.count())
                .select_from(RenderedClip)
                .join(
                    ClipCandidate,
                    RenderedClip.clip_candidate_id == ClipCandidate.id,
                )
                .join(
                    SourceVideo,
                    ClipCandidate.source_video_id == SourceVideo.id,
                )
                .join(
                    SourceChannel,
                    SourceVideo.source_channel_id == SourceChannel.id,
                )
                .where(
                    SourceChannel.channel_id == channel_id,
                    RenderedClip.status == "rendered",
                )
            ),
            "published_total": await self._count(
                sa.select(sa.func.count())
                .select_from(PublishedVideo)
                .where(
                    PublishedVideo.channel_id == channel_id,
                    PublishedVideo.status == "verified",
                )
            ),
            "published_today": await self.daily_published_count(channel_id),
            "stock": await self.stock_level(channel_id),
            "daily_target": profile.daily_clip_target,
            "paused": bool((profile.settings or {}).get("paused")),
        }
        await self._audit(channel_id, "ops.summary", summary)
        return summary

    async def _audit(self, channel_id: int, event_type: str, detail: dict):
        async with self._sessionmaker() as session:
            record_event(session, channel_id, event_type, detail)
            await session.commit()

    async def _count(self, query) -> int:
        async with self._sessionmaker() as session:
            return int((await session.execute(query)).scalar() or 0)


async def refill_channel_stock(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    channel_id: int,
) -> dict[str, Any]:
    """Ready-clip-stock-aware horizontal refill for one channel (Görev 2).

    The production gate counts READY UNPUBLISHED CLIPS (rendered vertical
    shorts + horizontal full cuts with no PublishedVideo row). While that
    stock is at or above the channel target no new source is downloaded;
    as clips get shared the stock depletes and production resumes. The
    global single-source rule still keeps at most one horizontal source
    in the pipeline at any time. Sources bound to unfollowed characters
    are skipped when the channel has a follow list.
    """
    from app.services.job_service import JobService
    from app.services.status_service import StatusService

    status = StatusService(sessionmaker, settings)
    jobs = JobService(sessionmaker, settings)
    service = AutomationService(sessionmaker, settings)

    profile = await service.profile(channel_id)
    if profile.automation_state not in WORK_STATES:
        return {
            "channel_id": channel_id,
            "enqueued": False,
            "reason": "otomasyon calismiyor",
            "stock": await status.ready_clip_stock(channel_id),
            "target": profile.horizontal_stock_target,
        }

    stock = await status.ready_clip_stock(channel_id)
    target = profile.horizontal_stock_target
    if stock >= target:
        return {
            "channel_id": channel_id,
            "enqueued": False,
            "reason": "stok hedefte",
            "stock": stock,
            "target": target,
        }

    # Global tek kaynak kurali: aktif bir yatay islem varsa yeni
    # indirme baslamaz (kanal fark etmeksizin).
    async with sessionmaker() as session:
        active = int(
            (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(Job)
                    .where(
                        Job.job_type == "media_process",
                        Job.status.in_(("queued", "running", "cancelling")),
                    )
                )
            ).scalar()
            or 0
        )
    if active >= 1:
        return {
            "channel_id": channel_id,
            "enqueued": False,
            "reason": "baska bir yatay kaynak isleniyor",
            "stock": stock,
            "target": target,
        }

    followed = await status.followed_character_ids(channel_id)
    next_video_id: int | None = None
    async with sessionmaker() as session:
        query = (
            sa.select(
                SourceVideo.id,
                SourceVideo.published_at,
                SourceChannel.filter_rules,
            )
            .join(SourceChannel, SourceVideo.source_channel_id == SourceChannel.id)
            .where(
                SourceChannel.channel_id == channel_id,
                SourceChannel.permission_status == "authorized",
                SourceVideo.status == "planned",
                # Kalici basarisiz videolar tekrar tekrar secilmesin:
                # 'failed' varligi olan video kuyrukta atlanir, motor
                # siradaki videoyla devam eder (kullanici istegi
                # 2026-10-19 — kanal durdurulmaz).
                ~sa.exists(
                    sa.select(MediaAsset.id).where(
                        MediaAsset.source_video_id == SourceVideo.id,
                        MediaAsset.status == "failed",
                    )
                ),
            )
            .order_by(SourceVideo.id)
        )
        if followed:
            query = query.where(SourceChannel.character_id.in_(followed))
        # Yaş penceresi zamanla kayar: keşifte uygun olan bir video kuyrukta
        # beklerken eskiyebilir. Yaş denetimini geçemeyen adaylar atlanır
        # (hariç yazılmaz — pencere genişletilirse reapply geri getirir).
        for row in (await session.execute(query.limit(25))).all():
            if age_exclusion(row.filter_rules, published_at=row.published_at):
                continue
            next_video_id = row.id
            break

    if next_video_id is None:
        return {
            "channel_id": channel_id,
            "enqueued": False,
            "reason": "islenecek uygun kaynak yok",
            "stock": stock,
            "target": target,
        }

    job = await jobs.enqueue(
        "media_process", {"source_video_id": next_video_id}, priority=8
    )
    enqueued = job.status == "queued" and job.attempts == 0
    return {
        "channel_id": channel_id,
        "enqueued": enqueued,
        "source_video_id": next_video_id,
        "stock": stock,
        "target": target,
    }


async def auto_plan_channel(
    sessionmaker: async_sessionmaker[AsyncSession], channel_id: int
) -> dict:
    """Monitoring -> planning connection: plan a channel's discovered
    videos right after discovery (M11 task 1)."""
    from app.services.planning_service import PlanningService

    planning = PlanningService(sessionmaker)
    return await planning.plan_for_channel(channel_id)


def today_key(timezone_name: str | None = None) -> str:
    """Local date key for daily dedupe (ops summaries)."""
    try:
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo(timezone_name or "UTC"))
    except Exception:  # noqa: BLE001
        now = datetime.now(UTC)
    return now.date().isoformat()
