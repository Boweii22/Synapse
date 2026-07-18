"""Synthetic multi-session conversation generator (CLAUDE.md section 5, build
order step 9). Builds a realistic ~44-simulated-day, 150-300+ turn conversation
for a fictional persona ("Alex"), with planted preferences, an ongoing project
mentioned repeatedly (to exercise consolidation clustering), a steady stream of
low-importance trivia (to exercise decay/pruning), and two deliberate
contradictions (to exercise supersession / "timely forgetting").

This content is a scripted *test fixture* -- authored input data for the
benchmark, not a canned agent response -- so hardcoding it here is correct and
matches what section 5 asks for ("a synthetic but realistic conversation log").
The trivia/project filler lines are drawn from small fixed pools and rotated
deterministically (not randomly) so the benchmark is reproducible run to run.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class Turn:
    day: int
    index: int
    user_message: str


@dataclass
class Probe:
    """A recall question asked at intervals. `answers_by_day` is a list of
    (effective_from_day, correct_answer) sorted ascending -- the correct answer
    for a given simulated day is whichever entry's effective_from_day is the
    latest one <= that day. This lets contradiction probes have a "before" and
    "after" correct answer for the same question."""
    question: str
    category: str
    answers_by_day: list[tuple[int, str]]

    def answer_at(self, day: int) -> str:
        applicable = [a for from_day, a in self.answers_by_day if from_day <= day]
        return applicable[-1] if applicable else self.answers_by_day[0][1]


BENCHMARK_START = datetime(2026, 4, 1, tzinfo=timezone.utc)


def turn_datetime(day: int) -> datetime:
    return BENCHMARK_START + timedelta(days=day, hours=9)


# Anchor days: hand-authored narrative beats -- facts, contradictions, the
# unresolved task, and explicit project-status mentions.
_ANCHOR_DAY_SCRIPTS: list[tuple[int, list[str]]] = [
    (0, [
        "Hey, I'm Alex. I'm a solo indie developer, mostly work in Python.",
        "Just so you know, I'm vegetarian -- please keep that in mind for any food suggestions.",
        "I'm allergic to shellfish too, that one's actually serious so please remember it.",
    ]),
    (1, [
        "I currently live in Berlin, been here about two years.",
    ]),
    (2, [
        "I'm kicking off a new side project called Synapse for a hackathon -- a memory agent for AI assistants.",
        "The core idea is decay and consolidation of memories instead of just dumping everything in a vector DB.",
    ]),
    (4, [
        "Quick coffee order note: I always get a flat white, no sugar, if that ever comes up.",
        "Made some progress on Synapse today -- got the Postgres + pgvector schema working.",
    ]),
    (6, [
        "Synapse update: wired up the Qwen embeddings client today, real API calls working end to end.",
    ]),
    (8, [
        "The hackathon deadline for Synapse is 20 Jul 2026, 10pm GMT+1 -- want to make sure I don't miss that.",
    ]),
    (10, [
        "Synapse progress: got the salience decay formula implemented, half-life differs for episodic vs semantic memories.",
    ]),
    (12, [
        "Still chugging along on Synapse -- today was the consolidation job, clustering repeated episodic memories.",
    ]),
    (14, [
        "I have an unresolved task: I still need to write the architecture diagram doc for Synapse before submission.",
    ]),
    (16, [
        "Synapse status: benchmark script is next on my list, comparing against a naive baseline agent.",
    ]),
    (18, [
        "Big update: I just moved to Lisbon. Berlin didn't work out long term, new city now.",
        "It's a big change but I'm excited, the weather alone is worth it.",
    ]),
    (19, [
        "Getting settled in Lisbon, still unpacking boxes.",
    ]),
    (20, [
        "Synapse update: frontend chat view is coming together, plain React with Vite.",
        "Also I switched my day job stack from Python to Rust a few weeks ago, still adjusting.",
    ]),
    (22, [
        "Reminder to self out loud: the Synapse deadline is still 20 Jul 2026, 10pm GMT+1, unchanged.",
    ]),
    (24, [
        "Synapse progress: memory timeline UI now shows live salience per memory, looking pretty good.",
    ]),
    (26, [
        "Still need to finish that architecture doc for Synapse, keep putting it off.",
    ]),
    (28, [
        "Synapse update: deployed the backend to Alibaba Cloud ECS today, real deployment not just localhost.",
        "Also for the record my food allergy to shellfish is unchanged, just double-checking you'd still know that.",
    ]),
    (30, [
        "Getting close to done on Synapse -- just the demo video and docs left.",
    ]),
    (32, [
        "Finished the architecture doc for Synapse finally, that unresolved task is done.",
    ]),
    (34, [
        "Synapse benchmark chart came out well -- decay and consolidation clearly beat the naive baseline.",
    ]),
    (36, [
        "Last check-in before submission: still living in Lisbon, still working mostly in Rust for the day job now.",
        "Thanks for keeping track of all this over the past month, by the way.",
    ]),
]

MAX_DAY = 43
FILLER_PER_NONANCHOR_DAY = 4
EXTRA_FILLER_PER_ANCHOR_DAY = 2

_TRIVIA_POOL = [
    "Ugh, it's been raining nonstop here this week.",
    "Watched a pretty forgettable action movie last night, wouldn't recommend it.",
    "Random one: my neighbor's cat keeps getting into my building's hallway, kind of funny.",
    "Had ramen for lunch, nothing special.",
    "Thinking about repainting my apartment, low priority though.",
    "Found a decent coffee place near the new apartment already.",
    "Grabbed groceries, nothing noteworthy.",
    "Random trivia: I finally beat that video game I've been stuck on for weeks.",
    "Lisbon traffic is way better than Berlin's, small win.",
    "Made a flat white at home today instead of buying one, tasted about the same honestly.",
    "Nothing else new today, pretty quiet.",
    "Slept in a bit later than usual this morning.",
    "Tried a new recipe for dinner, turned out okay.",
    "My phone battery has been draining fast lately, mildly annoying.",
    "Went for a long walk around the neighborhood after work.",
    "Caught up on a podcast episode I'd been meaning to listen to.",
    "Rearranged my desk setup a bit, feels a little more organized now.",
    "It was unusually warm out today, nice change of pace.",
    "Spent a chunk of the evening just reading, nothing productive.",
    "Ran into an old friend unexpectedly at the store.",
    "My internet connection was flaky for about an hour this morning.",
    "Tried a new bakery down the street, the bread was solid.",
    "Did some laundry and cleaned up the apartment a bit.",
    "Nothing much to report today, pretty low-key.",
]

_PROJECT_FILLER_POOL = [
    "Small Synapse update: refactored the retrieval re-ranking logic today.",
    "Synapse note: fixed a bug in how importance scores were being parsed.",
    "Spent a bit more time on Synapse -- cleaning up the config module.",
    "Synapse status: added logging around the consolidation job for debugging.",
    "Another small Synapse update: tuned the decay half-life defaults a bit.",
    "Synapse note: wrote a few more tests around the salience formula.",
    "Put some time into Synapse's frontend memory timeline view today.",
    "Synapse update: double-checked the Alibaba Cloud deployment is still healthy.",
    "Quick Synapse note: reviewed the benchmark conversation log for realism.",
    "Synapse status: nothing major today, just minor cleanup and docs.",
]


def _filler_lines_for_day(day: int, count: int) -> list[str]:
    lines = []
    for i in range(count):
        use_project = (day * 3 + i) % 5 == 0
        pool = _PROJECT_FILLER_POOL if use_project else _TRIVIA_POOL
        line = pool[(day * 7 + i * 5) % len(pool)]
        lines.append(line)
    return lines


def build_turns() -> list[Turn]:
    anchor_days = {day: messages for day, messages in _ANCHOR_DAY_SCRIPTS}
    turns: list[Turn] = []
    idx = 0
    for day in range(0, MAX_DAY + 1):
        day_messages: list[str] = []
        if day in anchor_days:
            day_messages.extend(anchor_days[day])
            day_messages.extend(_filler_lines_for_day(day, EXTRA_FILLER_PER_ANCHOR_DAY))
        else:
            day_messages.extend(_filler_lines_for_day(day, FILLER_PER_NONANCHOR_DAY))

        for msg in day_messages:
            turns.append(Turn(day=day, index=idx, user_message=msg))
            idx += 1
    return turns


def build_probes() -> list[Probe]:
    return [
        Probe(
            question="Where do I currently live?",
            category="contradiction",
            answers_by_day=[(0, "Berlin"), (18, "Lisbon")],
        ),
        Probe(
            question="What language do I mainly use for my day job right now?",
            category="contradiction",
            answers_by_day=[(0, "Python"), (20, "Rust")],
        ),
        Probe(
            question="Do I have any food allergies?",
            category="stable_semantic",
            answers_by_day=[(0, "Yes, allergic to shellfish")],
        ),
        Probe(
            question="What have I been working on as a side project lately?",
            category="consolidation",
            answers_by_day=[(0, "Synapse, a memory agent for an AI hackathon that focuses on memory decay and consolidation")],
        ),
        Probe(
            question="What's my usual coffee order?",
            category="low_importance_trivia",
            answers_by_day=[(0, "A flat white, no sugar")],
        ),
        Probe(
            question="What's the deadline for my hackathon project?",
            category="stable_semantic",
            answers_by_day=[(0, "20 Jul 2026, 10pm GMT+1")],
        ),
        Probe(
            question="Am I vegetarian?",
            category="stable_semantic",
            answers_by_day=[(0, "Yes, vegetarian")],
        ),
    ]


PROBE_CHECKPOINT_DAYS = [4, 16, 24, 36, 42]
