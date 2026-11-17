"""The AI player: routes each moment to a thinking tier and runs it as a generator pipeline.

``pipeline(ctx)`` yields ``LLMRequest`` objects and receives ``LLMResult`` objects (the CallBroker
drives it); it returns the ``ActionRequest`` to start, or None. Nothing here opens a database or
calls a provider. Records for the database are collected and handed over by ``drain_records``;
events go out through ``world.emit`` (minds/events.py).
"""

from __future__ import annotations

import json
import random
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from ai_island.llm.types import LLMRequest, LLMResult, request_key
from ai_island.minds import choice, memory, outcomes
from ai_island.minds.dummy import FIRE_RETRY, DummyController
from ai_island.minds.events import emit_event
from ai_island.minds.prompts import (
    bootstrap_layers,
    current_layer,
    fixed_digest,
    fixed_layer,
    make_layers,
    reflection_layer,
    scrub,
    slow_layer,
)
from ai_island.minds.reflex import reflex_action
from ai_island.minds.router import route, trigger_of
from ai_island.minds.runtime import MindsRuntime
from ai_island.minds.schemas import (
    AdvisorReply,
    FastReply,
    NoticerReply,
    RankingReply,
    ReflectionReply,
    SlowReply,
    check_reply,
)
from ai_island.minds.settings import DEFAULT_SETTINGS, MindSettings
from ai_island.minds.values import (
    VALUE_IDS,
    core_ids,
    invented_id,
    reflect,
    repair_initial_weights,
    validate_invented,
)
from ai_island.rules import wellbeing
from ai_island.rules.actions import social
from ai_island.rules.actions.request import ActionRequest
from ai_island.storage.records import (
    ChoiceInsight,
    ChoiceOutcome,
    ChoicePointRecord,
    ValueHistoryRow,
)

STATE_VERSION = 1
Pipeline = Generator[LLMRequest, LLMResult, Any]

_TRIGGER_TEXT = {
    "finished": "you just finished what you were doing",
    "spoken_to": "someone spoke to you",
    "interrupt": "something happened",
    "check": "time for a check-in",
}
_INTERRUPT_TEXT = {
    "spoken_to": "{who} said something to you.",
    "attacked": "You were attacked{by}.",
    "hurt": "You were hurt.",
    "player_in_sight": "{who} came into view.",
    "dog_in_sight": "A wild dog came into view.",
    "storm_started": "A storm has begun.",
    "loss_noticed": "You noticed that something of yours is missing.",
    "band_changed": "Your mood shifted.",
}


@dataclass
class Decision:
    """What a pipeline decided, before it is committed (events, records, memory)."""

    tier: str
    action: ActionRequest
    source: str = "model"  # model | code | fallback
    failure: str | None = None  # None | format | refusal
    thought: str = ""
    label: Any = None  # SelfLabel
    expected_feel: float | None = None
    options: list[dict[str, Any]] = field(default_factory=list)
    choice_index: int | None = None
    trade_off: str = ""
    noticer: str | None = None
    advisor: str | None = None
    advisor_kind: str | None = None
    ai_call_id: int | None = None


def _js(data: Any) -> str:
    """Compact, sorted JSON text (the decision_made payload carries action and label as text)."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _last_call(res: LLMResult) -> int | None:
    return res.ai_call_ids[-1] if res.ai_call_ids else None


class AiController:
    """One AI seat. Pure with respect to I/O: see the module note."""

    def __init__(self, pid: str, world: Any, rng: random.Random | None = None) -> None:
        self.pid = pid
        self.world = world
        self.dummy = DummyController(pid, rng if rng is not None else random.Random(0))
        self.runtime: MindsRuntime | None = None
        self.settings: MindSettings = DEFAULT_SETTINGS
        self.embedder: Any = None
        self.ai_cfg: Any = None
        self.cheap = False
        self._roles: dict[str, Any] = {}
        # persisted state
        self.weights: dict[str, float] = {}
        self.invented: dict[str, str] = {}
        self.identity = ""
        self.rolling_summary = ""
        self.stream: list[memory.MemoryItem] = []
        self.next_mem = 1
        self.recent_main: list[dict[str, str]] = []
        self.pending: list[outcomes.Pending] = []
        self.week_mistakes: list[str] = []
        self.week_choices: list[dict[str, str]] = []
        self.ordinals: dict[str, int] = {}
        self.ord_tick = -1
        self.day0_done = False
        self.last_reflected_week = 0
        self.last_reflection_tick = 0
        self.villager_names: list[str] | None = None
        self.last_sight = ""
        self.last_body = ""
        # not persisted
        self.records: list[Any] = []
        self._fixed: dict[str, str] = {}

    # ---------------------------------------------------------------- binding
    def bind(self, runtime: MindsRuntime) -> None:
        self.runtime = runtime
        self.settings = runtime.settings()
        self.embedder = runtime.embedder
        self.ai_cfg = runtime.ai_cfg
        self.cheap = bool(runtime.cheap)
        roles = getattr(runtime.models, "roles", None)
        self._roles = dict(roles) if roles else {}

    def decide(self, ctx: Any) -> Any:
        raise RuntimeError("AI seats decide through the call broker (use pipeline)")

    def drain_records(self) -> list[Any]:
        out, self.records = self.records, []
        return out

    def fixed_digest(self, family: str) -> str:
        """Fingerprint of this player's layer 1 for ``family`` (player, noticer, advisor)."""
        return fixed_digest(self._fixed_text(family))

    def reflection_due(self, week: int) -> bool:
        return week > self.last_reflected_week

    # ---------------------------------------------------------------- helpers
    def _alive(self) -> bool:
        p = self.world.players.get(self.pid)
        return p is not None and p.alive

    def _setup(self) -> None:
        if self.villager_names is None:
            mates = [v for v in self.world.villagers.values() if v.leader == self.pid]
            self.villager_names = [v.name for v in sorted(mates, key=lambda v: v.id)]

    def _fixed_text(self, family: str) -> str:
        self._setup()
        if family not in self._fixed:
            name = self.world.players[self.pid].name
            self._fixed[family] = fixed_layer(family, name, self.villager_names or [])  # type: ignore[arg-type]
        return self._fixed[family]

    def _role(self, kind: str) -> str:
        if kind == "main" and not self.cheap:
            return f"{self.pid}_main"
        return f"{self.pid}_helper"

    def _max_tokens(self, role: str) -> int:
        cfg = self._roles.get(role)
        return int(cfg.max_output_tokens) if cfg is not None else 2048

    def _next_key(self, tick: int, purpose: str) -> str:
        if tick != self.ord_tick:
            self.ordinals, self.ord_tick = {}, tick
        n = self.ordinals.get(purpose, 0)
        self.ordinals[purpose] = n + 1
        return request_key(tick, self.pid, purpose, n)

    def _request(
        self,
        tick: int,
        purpose: str,
        role: str,
        layers: Any,
        schema: type[BaseModel],
        family: str,
        fallback: dict[str, Any],
    ) -> LLMRequest:
        return LLMRequest(
            key=self._next_key(tick, purpose),
            tick=tick,
            player_id=self.pid,
            role=role,
            purpose=purpose,  # type: ignore[arg-type]
            layers=layers,
            schema=schema,
            max_output_tokens=self._max_tokens(role),
            meta={"family": family, "fallback": fallback},
        )

    def _accept(self, res: LLMResult, schema: type[BaseModel]) -> tuple[Any, str | None]:
        """(reply, None) when usable, else (None, "format" | "refusal")."""
        if res.status == "ok" and isinstance(res.parsed, schema):
            if not check_reply(res.parsed, set(self.weights), self.settings):
                return res.parsed, None
            return None, "format"
        return None, "refusal" if res.status == "refusal" else "format"

    def _rest(self) -> ActionRequest:
        minutes = int(getattr(self.ai_cfg, "fallback_rest_minutes", 5))
        return ActionRequest(kind="rest", minutes=minutes)

    def _failed(self, tier: str, failure: str | None) -> Decision:
        return Decision(tier, self._rest(), source="fallback", failure=failure or "format")

    def _day(self, tick: int) -> int:
        return tick // self.world.cfg.world.clock.ticks_per_day

    # ---------------------------------------------------------------- memory
    def _remember(self, tick: int, kind: str, text: str, importance: float) -> None:
        text = scrub(text, self.settings)[: self.settings.text_max_chars]
        item = memory.MemoryItem(self.next_mem, tick, kind, text, float(importance))
        self.next_mem += 1
        memory.append(self.stream, item, self.settings)

    def _importance(self, kind: str) -> float:
        table = self.settings.importance
        return float(table.get(kind, table.get("default", 0.3)))

    def _memory_texts(self, items: list[memory.MemoryItem]) -> list[str]:
        return [f"day {self._day(m.tick)}: {m.text}" for m in items]

    def _interrupt_text(self, item: Any) -> str:
        who = "Someone"
        src = getattr(item, "source", None)
        if src in self.world.players:
            who = self.world.players[src].name
        by = f" by {who}" if src in self.world.players else ""
        template = _INTERRUPT_TEXT.get(item.kind, "Something happened.")
        return template.format(who=who, by=by)

    def _capture(self, ctx: Any) -> None:
        """Remember what this decision's report shows (never hidden truth)."""
        tick, report = ctx.tick, ctx.report
        for item in ctx.interrupts:
            self._remember(tick, item.kind, self._interrupt_text(item), self._importance(item.kind))
        for sound in report.sounds:
            self._remember(tick, "sound", f"You heard: {sound}", self._importance("sound"))
        names = sorted({s.look for s in report.seen if s.kind == "player"})
        villagers = sum(1 for s in report.seen if s.kind == "villager")
        dogs = sum(1 for s in report.seen if s.kind == "dog")
        structs = sorted({s.look for s in report.seen if s.kind == "structure"})
        bits = [*names]
        if villagers:
            bits.append(f"{villagers} villager{'s' if villagers != 1 else ''}")
        if dogs:
            bits.append("a wild dog" if dogs == 1 else f"{dogs} wild dogs")
        bits += structs[:3]
        sight = ", ".join(bits)
        if sight and sight != self.last_sight:
            self._remember(tick, "sight", f"You saw {sight}.", self._importance("sight"))
        self.last_sight = sight
        body = f"You feel {report.feeling}. " + " ".join(report.body)
        if body != self.last_body:
            self._remember(tick, "body", body.strip(), self._importance("default"))
        self.last_body = body

    # ---------------------------------------------------------------- prompts
    def _situation(self, ctx: Any, trigger: str) -> str:
        parts = [_TRIGGER_TEXT.get(trigger, trigger)]
        parts += [self._interrupt_text(i) for i in ctx.interrupts]
        words = list(getattr(ctx.own, "body_words", []))
        if words:
            parts.append(", ".join(words))
        parts.append(f"feeling {ctx.report.feeling}")
        return scrub("; ".join(parts), self.settings)[: self.settings.situation_max_chars]

    def _names(self, ids: Any) -> str:
        w = self.world
        out = []
        for i in ids:
            who = w.players.get(i) or w.villagers.get(i)
            out.append(who.name if who is not None else str(i))
        return ", ".join(out)

    def _extra(self, ctx: Any, trigger: str) -> str:
        w, pid, rep = self.world, self.pid, ctx.report
        lines = [f"Why you are deciding now: {_TRIGGER_TEXT.get(trigger, trigger)}."]
        for item in ctx.interrupts:
            lines.append(self._interrupt_text(item))
        lines.append(f"You stand at ({rep.position[0]}, {rep.position[1]}); home is at {rep.home}.")
        carried = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in sorted(rep.carried.items()))
        lines.append(f"You carry: {carried or 'nothing'}.")
        stored = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in sorted(rep.stored.items()))
        lines.append(f"In your home store: {stored or 'nothing'}.")
        mates = getattr(ctx.own, "villagers", [])
        lines.append(f"Your villagers: {self._names(mates) or 'none'}.")
        tasks = list(getattr(ctx.own, "own_tasks", []))
        if tasks:
            lines.append("Your goals: " + " ".join(tasks))
        for offer in sorted(w.offers.values(), key=lambda o: o.id):
            if offer.target == pid:
                lines.append(
                    f"{self._names([offer.maker])} offers (offer {offer.id}): gives {offer.give}, "
                    f"wants {offer.want}."
                )
        for prom in sorted(w.promises.values(), key=lambda q: q.id):
            if prom.to == pid and prom.status == "open":
                lines.append(f"{self._names([prom.maker])} promised you: {prom.text}")
        return scrub("\n".join(lines), self.settings)

    def _slow_text(self) -> str:
        w, pid, s = self.world, self.pid, self.settings
        p = w.players[pid]
        rels = [
            (w.players[o].name, p.trust.get(o, 50.0), p.anger.get(o, 0.0))
            for o in sorted(w.players)
            if o != pid
        ]
        know = sorted(p.knowledge, key=lambda k: (-k.learned_tick, -k.id))[: s.retrieval_limit]
        book = [(scrub(k.subject, s), scrub(k.claim, s), k.confidence) for k in know]
        return slow_layer(
            scrub(self.identity, s),
            self.weights,
            rels,
            book,
            scrub(self.rolling_summary, s),
            self.invented,
            s,
        )

    def _layers(
        self,
        family: str,
        purpose: str,
        ctx: Any,
        memories: list[memory.MemoryItem],
        extra: str,
        history: Any = (),
    ) -> Any:
        current = current_layer(
            purpose,  # type: ignore[arg-type]
            scrub(ctx.report.text, self.settings),
            self._memory_texts(memories),
            history,
            extra,
        )
        return make_layers(self._fixed_text(family), self._slow_text(), current, self.settings)

    def _fallback_dict(self, ctx: Any) -> dict[str, Any]:
        act = self.dummy.decide(ctx)
        return choice.action_dict(act) if act is not None else {"kind": "rest", "minutes": 5}

    # ---------------------------------------------------------------- the pipeline
    def pipeline(self, ctx: Any) -> Pipeline:
        """Decide what ``ctx.player_id`` does now. A generator for the CallBroker."""
        self._setup()
        tick = ctx.tick
        if not self.day0_done:
            yield from self._day0(tick)
        trigger = trigger_of(ctx)
        hooked = self._hooked(ctx)
        x = self._x(ctx)
        self._settle_open(tick, x)
        self._capture(ctx)
        situation = self._situation(ctx, trigger)
        reflex_fn = lambda c, r: reflex_action(c, r, self.settings, self.dummy.fire_after)  # noqa: E731
        tier = route(ctx, ctx.report, self.world, self.settings, hooked, reflex_fn)
        if tier == "reflex":
            act = reflex_fn(ctx, ctx.report)
            if act.kind == "make_fire":
                self.dummy.fire_after = tick + FIRE_RETRY
            dec = Decision("reflex", act, source="code")
        elif tier == "fast":
            dec = yield from self._fast(ctx, trigger, hooked)
        else:
            dec = yield from self._main(ctx, tier, trigger)
        return self._commit(ctx, dec, trigger, situation, x)

    def _x(self, ctx: Any) -> float:
        v = getattr(ctx, "x", None)
        return float(v) if v is not None else float(wellbeing.x_of(self.world, self.pid, ctx.tick))

    def _hooked(self, ctx: Any) -> bool:
        v = getattr(ctx, "hooked", None)
        return bool(v) if v is not None else wellbeing.is_hooked(self.world, self.pid)

    def _feeling(self, ctx: Any) -> str:
        return str(getattr(ctx, "feeling", None) or ctx.report.feeling)

    def _fast(self, ctx: Any, trigger: str, hooked: bool) -> Pipeline:
        tick = ctx.tick
        mems = memory.recent(self.stream, self.settings.hooked_memory_size)
        fb = self._fallback_dict(ctx)
        layers = self._layers("player", "fast", ctx, mems, self._extra(ctx, trigger))
        res = yield self._request(
            tick, "fast", self._role("helper"), layers, FastReply, "player", fb
        )
        reply, failure = self._accept(res, FastReply)
        if reply is None:
            return self._failed("fast", failure)
        if reply.needs_more_thought:
            return (yield from self._main(ctx, "hooked" if hooked else "slow", trigger, fb))
        return Decision(
            "fast",
            reply.action,
            thought=reply.thought,
            label=reply.self_label,
            expected_feel=float(reply.expected_feel),
            ai_call_id=_last_call(res),
        )

    def _main(
        self, ctx: Any, tier: str, trigger: str, fallback: dict[str, Any] | None = None
    ) -> Pipeline:
        tick, s = ctx.tick, self.settings
        fb = fallback if fallback is not None else self._fallback_dict(ctx)
        extra = self._extra(ctx, trigger)
        notice = advice = advice_kind = None
        if tier == "hooked":
            mems = memory.recent(self.stream, s.hooked_memory_size)
        else:
            query = scrub(ctx.report.text, s) + " " + self._situation(ctx, trigger)
            mems = memory.retrieve(
                self.stream, query, tick, s.retrieval_limit, self.embedder or _default_embedder(), s
            )
            helper = self._role("helper")
            layers = self._layers("noticer", "noticer", ctx, mems, extra)
            res = yield self._request(tick, "noticer", helper, layers, NoticerReply, "noticer", {})
            nr, failure = self._accept(res, NoticerReply)
            if nr is None:
                return self._failed(tier, failure)
            notice = "; ".join(
                f"{r.person}: seems {r.feeling}, wants {r.intent} ({r.uncertainty} certainty)"
                for r in nr.reads
            )
            extra += f"\n\nWhat you notice about the people around you: {notice or 'nothing'}."
            hist = list(self.recent_main[-s.advisor_history_size :])
            layers = self._layers("advisor", "advisor", ctx, mems, extra, hist)
            adv_fb = {"recommended_kind": fb.get("kind", "rest")}
            res = yield self._request(
                tick, "advisor", helper, layers, AdvisorReply, "advisor", adv_fb
            )
            ar, failure = self._accept(res, AdvisorReply)
            if ar is None:
                return self._failed(tier, failure)
            advice, advice_kind = ar.advice, ar.recommended_kind
            extra += f"\n\nYour own advice to yourself: {advice} (you lean toward: {advice_kind})."
        layers = self._layers("player", "main", ctx, mems, scrub(extra, s))
        res = yield self._request(tick, "main", self._role("main"), layers, SlowReply, "player", fb)
        reply, failure = self._accept(res, SlowReply)
        if reply is None:
            return self._failed(tier, failure)
        chosen = reply.options[reply.choice_index]
        return Decision(
            tier,
            chosen.action,
            thought=reply.thought,
            label=reply.self_label,
            expected_feel=float(chosen.feel_now),
            options=[o.model_dump(mode="json", exclude_none=True) for o in reply.options],
            choice_index=reply.choice_index,
            trade_off=reply.trade_off,
            noticer=notice,
            advisor=advice,
            advisor_kind=advice_kind,
            ai_call_id=_last_call(res),
        )

    # ---------------------------------------------------------------- day-0 ranking
    def _ranking_fallback(self) -> dict[str, Any]:
        idx = int(self.pid.rsplit("_", 1)[-1]) - 1
        start = (idx * 3) % len(VALUE_IDS)
        order = [VALUE_IDS[(start + i) % len(VALUE_IDS)] for i in range(len(VALUE_IDS))]
        core_w = [20.0, 18.0, 16.0, 14.0, 12.0]
        rest = (100.0 - sum(core_w)) / (len(VALUE_IDS) - len(core_w))
        weights = {v: (core_w[i] if i < 5 else rest) for i, v in enumerate(order)}
        return {"entries": [{"value_id": v, "weight": weights[v]} for v in VALUE_IDS]}

    def _day0(self, tick: int) -> Pipeline:
        name = self.world.players[self.pid].name
        fixed, slow, current = bootstrap_layers(name, self.villager_names or [])
        layers = make_layers(fixed, slow, current, self.settings)
        req = self._request(
            tick, "ranking", self._role("main"), layers, RankingReply, "player",
            self._ranking_fallback(),
        )  # fmt: skip
        res = yield req
        entries = res.parsed.entries if res.status == "ok" and res.parsed is not None else []
        weights, problems = repair_initial_weights(entries, self.settings)
        if problems:
            emit_event(self.world, "value_repaired", tick, player=self.pid, problems=problems)
        self.weights = dict(weights)
        self.day0_done = True
        self._value_rows(tick, 0, {}, self.weights, [], req.key)

    def _value_rows(
        self,
        tick: int,
        week: int,
        old: dict[str, float],
        new: dict[str, float],
        causes: list[int],
        key: str,
        cause_items: list[dict[str, Any]] | None = None,
    ) -> None:
        for vid, w in new.items():
            self.records.append(
                ValueHistoryRow(
                    tick, self.pid, week, vid, old.get(vid), float(w), list(causes), key,
                    [dict(c) for c in cause_items or []],
                )
            )  # fmt: skip

    # ---------------------------------------------------------------- commit a decision
    def _commit(self, ctx: Any, d: Decision, trigger: str, situation: str, x: float) -> Any:
        tick, pid, s = ctx.tick, self.pid, self.settings
        key = f"{tick}/{pid}"
        act = d.action
        label = d.label.model_dump(mode="json") if d.label is not None else None
        direction = label["direction"] if label else None
        has_cp = d.tier in ("slow", "hooked") or (
            d.source == "model"
            and d.tier == "fast"
            and choice.wants_choice_point(d.tier, act.kind, direction)
        )
        emit_event(
            self.world, "decision_made", tick,
            player=pid, decision_key=key, tier=d.tier, trigger=trigger, situation=situation,
            action=_js(choice.action_dict(act)), self_label=_js(label) if label else None,
            source=d.source,
            failure=d.failure, choice_point=has_cp,
        )  # fmt: skip
        core = core_ids(self.weights, s.core_count)
        violation = False
        if label is not None and d.source == "model":
            violation = choice.is_violation(direction, label["violated"], core)
            if violation:
                emit_event(
                    self.world, "value_violation", tick,
                    player=pid, decision_key=key, violated=list(label["violated"]),
                    direction=direction,
                )  # fmt: skip
        expected = None
        if d.source == "model" and d.expected_feel is not None:
            expected = d.expected_feel * s.x_per_feel_point
            self.pending.append(outcomes.Pending(key, tick, act.kind, expected, x, d.tier, has_cp))
        text = choice.describe_action(act)
        if d.source == "fallback":
            self._remember(tick, "decision", "You hesitated and rested a little.", 0.3)
        else:
            self._remember(tick, "decision", f"You chose to {text}.", self._importance("default"))
        if d.tier in ("slow", "hooked") and d.source == "model":
            self.recent_main.append(
                {"decision_key": key, "choice": text, "trade_off": d.trade_off,
                 "outcome": "not yet known"}
            )  # fmt: skip
            del self.recent_main[: -s.advisor_history_size]
        if has_cp:
            self.week_choices.append(
                {"decision_key": key, "text": f"{text} (outcome not yet known)"}
            )
            self.records.append(
                self._record(ctx, d, key, trigger, situation, x, label, expected, violation)
            )
        return act

    def _record(
        self, ctx: Any, d: Decision, key: str, trigger: str, situation: str, x: float,
        label: dict[str, Any] | None, expected: float | None, violation: bool,
    ) -> ChoicePointRecord:  # fmt: skip
        fallback = d.source == "fallback"
        followed = None
        if d.tier == "slow" and d.advisor_kind is not None:
            followed = d.action.kind == d.advisor_kind
        details = {
            "decision_key": key,
            "options": d.options,
            "choice_index": d.choice_index,
            "trade_off": d.trade_off,
            "trigger": trigger,
            "expected_delta": expected,
            "value_violation": violation,
            "label_source": "fallback" if fallback else "model",
            "interrupt_kinds": sorted({str(i.kind) for i in getattr(ctx, "interrupts", ())}),
        }
        return ChoicePointRecord(
            decision_key=key,
            tick=ctx.tick,
            player_id=self.pid,
            situation=situation,
            x=round(x, 3),
            feeling=self._feeling(ctx),
            tier=d.tier,
            thought=d.thought,
            action=choice.action_dict(d.action),
            self_label=label or {"served": [], "violated": [], "direction": "toward"},
            noticer_read=d.noticer,
            advisor_said=d.advisor,
            advisor_followed=followed,
            ai_call_id=d.ai_call_id,
            details=details,
        )

    # ---------------------------------------------------------------- outcomes
    def _settle(self, pend: outcomes.Pending, result: str, tick: int, x_after: float) -> None:
        s = self.settings
        out = outcomes.outcome_dict(result, pend.x_before, x_after)
        delta = x_after - pend.x_before
        if pend.choice_point:
            self.records.append(ChoiceOutcome(pend.decision_key, out))
        word = outcomes.word_for_delta(delta, s)
        short = result.split(":")[0]
        self._remember(
            tick, "outcome", f"Your attempt to {pend.kind.replace('_', ' ')} ended ({short}); "
            f"afterwards you {word}.", self._importance("outcome"),
        )  # fmt: skip
        for row in self.recent_main:
            if row["decision_key"] == pend.decision_key:
                row["outcome"] = f"{short}; you {word}"
        for row in self.week_choices:
            if row["decision_key"] == pend.decision_key:
                row["text"] = row["text"].replace("outcome not yet known", f"{short}; you {word}")
        if outcomes.is_mistake(pend.expected_delta, delta, s):
            emit_event(
                self.world, "mistake_flagged", tick,
                player=self.pid, decision_key=pend.decision_key,
                expected_delta=round(pend.expected_delta, 3), actual_delta=round(delta, 3),
            )  # fmt: skip
            what = pend.kind.replace("_", " ")
            note = f"You tried to {what} hoping it would help, but afterwards you {word}."
            self._remember(tick, "mistake", note, self._importance("mistake"))
            self.week_mistakes.append(f"{pend.decision_key}: {note}")

    def _settle_open(self, tick: int, x: float) -> None:
        """A new decision ends whatever the earlier ones were waiting on."""
        for pend in self.pending:
            self._settle(pend, "interrupted" if pend.started else "not_started", tick, x)
        self.pending = []

    def after_tick(self, world: Any, tick: int) -> None:
        """Settle outcomes from this tick's events. No calls, no randomness."""
        if not self.pending:
            return
        evs: list[Any] = []
        for e in reversed(world.events):
            if e.tick < tick:
                break
            evs.append(e)
        evs.reverse()
        keep = []
        x_now = float(wellbeing.x_of(world, self.pid, tick))
        for pend in self.pending:
            result = outcomes.result_from_events(pend, evs, self.pid)
            if result is None and tick - pend.tick >= self.settings.outcome_window_ticks:
                result = "window"
            if result is None:
                keep.append(pend)
            else:
                self._settle(pend, result, tick, x_now)
        self.pending = keep

    # ---------------------------------------------------------------- weekly reflection
    def _happenings(self) -> list[tuple[int, str]]:
        bar = self._importance("hurt")
        items = [
            m for m in self.stream if m.tick > self.last_reflection_tick and m.importance >= bar
        ]
        return [(m.id, m.text) for m in items[-self.settings.retrieval_limit :]]

    def reflect_pipeline(self, week: int, tick: int) -> Generator[LLMRequest, LLMResult, bool]:
        """The weekly look back: one main-role call. Returns True when it was applied; on any
        failure nothing changes and the reflection stays due."""
        if not self._alive() or not self.reflection_due(week):
            return False
        self._setup()
        s = self.settings
        happenings = self._happenings()
        last = s.retrieval_limit
        choices = [(c["decision_key"], c["text"]) for c in self.week_choices[-last:]]
        seen = [(n, scrub(t, s)) for n, t in happenings]
        current = reflection_layer(week, seen, self.week_mistakes[-last:], choices, s)
        layers = make_layers(self._fixed_text("player"), self._slow_text(), current, s)
        fb = self._reflection_fallback(week)
        req = self._request(
            tick, "reflection", self._role("main"), layers, ReflectionReply, "player", fb
        )
        res = yield req
        reply, _ = self._accept(res, ReflectionReply)
        if reply is None:
            return False
        self._apply_reflection(week, tick, req.key, reply, {n for n, _ in happenings})
        return True

    def _reflection_fallback(self, week: int) -> dict[str, Any]:
        name = self.world.players[self.pid].name
        line = (
            f"Week {week}: {len(self.week_choices)} careful choices, "
            f"{len(self.week_mistakes)} mistakes."
        )
        summary = f"{self.rolling_summary} {line}".strip()[
            -(self.settings.summary_max_chars - 100) :
        ]
        return {
            "identity": self.identity or f"I am {name}, leader of my small village.",
            "rolling_summary": summary,
        }

    def _apply_reflection(
        self, week: int, tick: int, key: str, reply: ReflectionReply, valid_causes: set[int]
    ) -> None:
        s, pid, w = self.settings, self.pid, self.world
        old = dict(self.weights)
        requested = {k: v for k, v in reply.requested_changes.items() if k in old}
        known = dict(old)
        accepted = []
        for inv in reply.invented_values:
            reason = validate_invented(inv, known, s, len(accepted))
            if reason is not None:
                emit_event(
                    w, "invention_rejected", tick, player=pid, week=week, name=inv.name[:80],
                    reason=reason,
                )  # fmt: skip
                continue
            accepted.append(inv)
            known[invented_id(inv.name)] = 0.0
        new = dict(old)
        names: list[str] = []
        pending = requested
        for inv in accepted or [None]:
            new, _clipped, status = reflect(new, pending, inv, s)
            pending = {}
            if inv is not None and status is not None:
                self.invented[status] = scrub(f"{inv.name}: {inv.definition}", s)[
                    : s.text_max_chars
                ]
                names.append(inv.name)
        changes = {
            v: [round(old.get(v, 0.0), 4), round(nw, 4)]
            for v, nw in new.items()
            if abs(nw - old.get(v, 0.0)) > 1e-9
        }
        causes = sorted({c for c in reply.cause_event_ids if c in valid_causes})
        self.weights = new
        by_id = {m.id: m for m in self.stream}
        cause_items = [
            {
                "memory_id": c,
                "tick": by_id[c].tick,
                "kind": by_id[c].kind,
                "text": scrub(by_id[c].text, s)[: s.text_max_chars],
            }
            for c in causes
            if c in by_id
        ]
        self._value_rows(tick, week, old, new, causes, key, cause_items)
        if reply.identity.strip():
            self.identity = scrub(reply.identity, s)[: s.text_max_chars]
        self.rolling_summary = scrub(reply.rolling_summary, s)[: s.summary_max_chars]
        player = w.players[pid]
        for ku in reply.knowledge_updates:
            social.add_knowledge(
                w,
                player,
                scrub(ku.subject, s),
                scrub(ku.claim, s),
                ku.confidence,
                "self",
                tick,
                None,
            )
        keys = {c["decision_key"] for c in self.week_choices}
        for ins in reply.insights:
            if ins.decision_key in keys:
                self.records.append(ChoiceInsight(ins.decision_key, scrub(ins.insight, s)))
        emit_event(
            w, "reflection_completed", tick, player=pid, week=week, changes=changes,
            invented=names[0] if names else None,
        )  # fmt: skip
        self._remember(tick, "reflection", f"At the end of week {week} you looked back.", 0.5)
        self.week_mistakes, self.week_choices = [], []
        self.last_reflected_week, self.last_reflection_tick = week, tick

    # ---------------------------------------------------------------- persistence
    def to_state(self) -> dict[str, Any]:
        return {
            "kind": "ai",
            "state_version": STATE_VERSION,
            "weights": [[v, w] for v, w in self.weights.items()],
            "invented": dict(self.invented),
            "identity": self.identity,
            "rolling_summary": self.rolling_summary,
            "memory": [m.to_state() for m in self.stream],
            "next_mem": self.next_mem,
            "recent_main": [dict(r) for r in self.recent_main],
            "pending": [p.to_state() for p in self.pending],
            "week_mistakes": list(self.week_mistakes),
            "week_choices": [dict(c) for c in self.week_choices],
            "ordinals": dict(self.ordinals),
            "ord_tick": self.ord_tick,
            "day0_done": self.day0_done,
            "last_reflected_week": self.last_reflected_week,
            "last_reflection_tick": self.last_reflection_tick,
            "villager_names": self.villager_names,
            "last_sight": self.last_sight,
            "last_body": self.last_body,
            "dummy": self.dummy.to_state(),
        }

    def from_state(self, state: dict[str, Any]) -> None:
        version = state.get("state_version")
        if version != STATE_VERSION:
            raise ValueError(
                f"saved AI player state has version {version!r}; this program reads "
                f"version {STATE_VERSION}. Start a new run with 'new'."
            )
        self.weights = {str(v): float(w) for v, w in state["weights"]}
        self.invented = {str(k): str(v) for k, v in state["invented"].items()}
        self.identity = str(state["identity"])
        self.rolling_summary = str(state["rolling_summary"])
        self.stream = [memory.MemoryItem.from_state(m) for m in state["memory"]]
        self.next_mem = int(state["next_mem"])
        self.recent_main = [dict(r) for r in state["recent_main"]]
        self.pending = [outcomes.Pending.from_state(p) for p in state["pending"]]
        self.week_mistakes = [str(m) for m in state["week_mistakes"]]
        self.week_choices = [dict(c) for c in state["week_choices"]]
        self.ordinals = {str(k): int(v) for k, v in state["ordinals"].items()}
        self.ord_tick = int(state["ord_tick"])
        self.day0_done = bool(state["day0_done"])
        self.last_reflected_week = int(state["last_reflected_week"])
        self.last_reflection_tick = int(state["last_reflection_tick"])
        names = state["villager_names"]
        self.villager_names = None if names is None else [str(n) for n in names]
        self.last_sight = str(state["last_sight"])
        self.last_body = str(state["last_body"])
        self.dummy.from_state(state["dummy"])
        self._fixed = {}
        self.records = []


def _default_embedder() -> Any:
    from ai_island.llm.fake import FakeEmbedder

    return FakeEmbedder()
