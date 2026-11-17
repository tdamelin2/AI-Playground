"""Sense-report wording: appearance names and at least three templates per kind of event.

A template is chosen with a stable hashlib digest of (seed, player, tick, kind, subject), so the
same run always words things the same way and no random numbers are drawn. Texts use what a
person would see (spotted red berries), never internal kinds such as mild_poison.
"""

from __future__ import annotations

from ai_island.rules.senses.common import stable_index

# What each plant looks like. The two poisons are dressed as ordinary things on purpose.
APPEARANCE: dict[str, str] = {
    "berries": "red berries on a low bush",
    "mushrooms": "brown mushrooms",
    "roots": "a pale root plant",
    "herbs": "leafy green herbs",
    "healing_herbs": "silvery-leaved herbs",
    "mild_poison": "spotted red berries",
    "strong_poison": "white umbrella mushrooms",
}

ANIMAL_NAMES: dict[str, str] = {
    "rabbit": "a rabbit",
    "deer": "a deer",
    "boar": "a boar",
    "fish": "a fish",
    "bird": "a bird",
    "nest_eggs": "a nest of eggs",
    "goat": "a goat",
    "chicken": "a chicken",
}

STRUCTURE_NAMES: dict[str, str] = {
    "house": "a house",
    "hearth": "a hearth",
    "field": "a planted field",
    "storehouse": "a storehouse",
    "workshop": "a workshop",
    "pen": "an animal pen",
    "granary": "a granary",
    "bridge": "a bridge",
    "monument": "a monument",
    "shrine": "a shrine",
    "campfire": "a campfire",
}

TERRAIN_NAMES: dict[str, str] = {
    "spring": "a freshwater spring",
    "lake": "open lake water",
    "coast": "the sea shore",
    "tree": "a tree",
    "rocky": "a rocky patch with loose stone",
    "quarry": "the stone quarry",
}

ITEM_NAMES: dict[str, str] = {
    "wood": "wood",
    "stone": "stone",
    "water": "water",
    "berries": "berries",
    "mushrooms": "mushrooms",
    "roots": "roots",
    "herbs": "herbs",
    "healing_herbs": "silvery herbs",
    "mild_poison": "spotted red berries",
    "strong_poison": "white umbrella mushrooms",
    "raw_meat": "raw meat",
    "cooked_meat": "cooked meat",
    "spoiled_meat": "rotten meat",
    "fish": "fish",
    "eggs": "eggs",
    "milk": "milk",
    "crops": "crops",
    "stake": "boundary stakes",
}

TEMPLATES: dict[str, tuple[str, ...]] = {
    "plant": (
        "You spot {what} at {where}.",
        "You notice {what} close to {where}.",
        "Your eye catches {what} at {where}.",
    ),
    "animal": (
        "{what} moves at {where}.",
        "You see {what} at {where}.",
        "There is {what} near {where}.",
    ),
    "dog": (
        "A wild dog prowls at {where}.",
        "You see a wild dog near {where}.",
        "A lean dog watches from {where}.",
    ),
    "player": (
        "{what} stands at {where}.",
        "You see {what} near {where}.",
        "{what} is in view at {where}.",
    ),
    "villager": (
        "A villager works near {where}.",
        "You see a villager at {where}.",
        "A villager walks by {where}.",
    ),
    "structure": (
        "You see {what} at {where}.",
        "{what} stands at {where}.",
        "There is {what} at {where}.",
    ),
    "terrain": (
        "You can see {what} at {where}.",
        "{what} lies at {where}.",
        "Over at {where} there is {what}.",
    ),
    "drop": (
        "Some things lie on the ground at {where}.",
        "Items are scattered at {where}.",
        "You notice something dropped at {where}.",
    ),
    "weather": (
        "The weather is {what}.",
        "Outside it is {what}.",
        "The sky is {what}.",
    ),
    "sound": (
        'You hear {who} say: "{text}"',
        '{who} says: "{text}"',
        'From nearby, {who} calls: "{text}"',
    ),
    "body": (
        "{text}",
        "You notice that {text_lower}",
        "Your body tells you: {text_lower}",
    ),
    "feeling": (
        "{text}.",
        "Overall, {text_lower}.",
        "All things considered, {text_lower}.",
    ),
}

WEATHER_WORDS: dict[str, str] = {
    "clear": "clear",
    "rain": "rainy",
    "storm": "stormy and dangerous",
    "drought": "dry and hot",
}

FEELING_WORDS: tuple[str, ...] = (
    "You feel strong and hopeful",
    "You feel all right",
    "You feel uneasy and worn",
    "You are suffering",
    "You feel miserable and broken",
)

LEVEL_WORDS: dict[str, tuple[str, ...]] = {
    "hunger": (
        "Your stomach is quiet.",
        "You are getting hungry.",
        "You are very hungry.",
        "You are starving.",
    ),
    "thirst": (
        "Your throat is fine.",
        "You are getting thirsty.",
        "You are very thirsty.",
        "You are parched and dizzy.",
    ),
    "cold": (
        "You are warm enough.",
        "You feel a chill.",
        "You are cold and shivering.",
        "You are freezing.",
    ),
    "fatigue": (
        "You feel rested.",
        "You are getting tired.",
        "You are very tired.",
        "You can barely keep your eyes open.",
    ),
    "pain": (
        "",
        "You have a dull ache.",
        "You are in pain.",
        "You are in terrible pain.",
    ),
}


def pick(seed: int, pid: str, tick: int, kind: str, subject: str) -> str:
    """The template for this event, the same every time for the same arguments."""
    options = TEMPLATES[kind]
    return options[stable_index(len(options), seed, pid, tick, kind, subject)]


def render(
    seed: int,
    pid: str,
    tick: int,
    kind: str,
    subject: str,
    what: str = "",
    where: str = "",
    who: str = "",
    text: str = "",
) -> str:
    template = pick(seed, pid, tick, kind, subject)
    return template.format(
        what=what,
        where=where,
        who=who,
        text=text,
        text_lower=(text[:1].lower() + text[1:]) if text else "",
    )
