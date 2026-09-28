"""What the system understood about a line's delivery (V0.2 §14.10 执行指令查看).

§14.10 names a gap that is NOT a missing parameter: an author's delivery
instruction goes into the pipeline invisibly and comes back out as a generated
take — "AI 自动执行后用户不知道改了什么". The fix is one canonical Chinese
rendering per line, defined once here, shown both in the API response and in
the panel's chip, with three exits for the author (accept / modify / cancel).

The parameters are the §14.3 delivery dimensions, carried on a dialogue line as
numbers relative to the engine's own defaults::

    {"text": "你终于来了。", "speech_rate_percent": -15,
     "pause_after_seconds": 0.4, "emotion_intensity": 1}
    -> "语速 -15%、停顿 +0.4s、情绪强度 +1"

Decisions worth stating, because a test locks each of them:

- A parameter AT its default contributes NOTHING, so a default line returns the
  EMPTY STRING (not None): the caller concatenates the description into a
  sentence, and "nothing deviates" is already the empty sentence. Silence is
  the compliment.
- Fragment order is FIXED (语速 → 停顿 → 情绪强度) — the order §14.3 lists the
  dimensions in — so the same line reads the same way every time.
- Values render with an EXPLICIT SIGN and no trailing zeros (-15%, +0.4s, +1):
  the sign IS the deviation, which is the only thing the author needs to read.
- This function never raises. A value that cannot be read as a number is
  treated as "not authored"; the lip-sync service is the one that rejects such
  input with a named error, so a description can never break the panel that
  shows it.
- The line's written ``emotion`` string (压低/克制) is NOT an intensity and is
  NOT read here: it is a different dimension and already has its own control in
  the panel.

Still open + reason: nothing in this tree EXECUTES the three numbers yet.
``speech_orchestration.build_timeline_from_script`` reads only character/text/
start_time/end_time/emotion/word_timings, and the TTS engine that would honour
a rate/pause/intensity lives outside this tree. So the service echoes them in
``summary["execution_instructions"]`` rather than claiming they moved the
timeline — visible and named, never silent.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Canonical line keys — the JSON the panel POSTs and the API echoes back.
SPEECH_RATE_PERCENT_KEY = "speech_rate_percent"
PAUSE_AFTER_SECONDS_KEY = "pause_after_seconds"
EMOTION_INTENSITY_KEY = "emotion_intensity"

#: Defaults: the engine's own reading of the line. A parameter equal to its
#: default is not a deviation and produces no fragment.
DEFAULT_SPEECH_RATE_PERCENT = 0.0
DEFAULT_PAUSE_AFTER_SECONDS = 0.0
DEFAULT_EMOTION_INTENSITY = 0.0

#: Fragment order is part of the contract (语速 → 停顿 → 情绪强度).
FRAGMENT_ORDER: tuple[str, ...] = (
    SPEECH_RATE_PERCENT_KEY,
    PAUSE_AFTER_SECONDS_KEY,
    EMOTION_INTENSITY_KEY,
)

#: How the fragments are joined into one sentence.
FRAGMENT_SEPARATOR = "、"

#: Other spellings the same three parameters arrive under (a dialogue take or an
#: alignment handoff may name them tempo / pause_delta / emotion_delta).
#: Reading only one spelling would make the chip miss a deviation that WAS
#: authored; the canonical key wins when several are present.
PARAMETER_ALIASES: dict[str, tuple[str, ...]] = {
    SPEECH_RATE_PERCENT_KEY: (SPEECH_RATE_PERCENT_KEY, "tempo", "tempo_delta"),
    PAUSE_AFTER_SECONDS_KEY: (PAUSE_AFTER_SECONDS_KEY, "pause", "pause_delta"),
    EMOTION_INTENSITY_KEY: (EMOTION_INTENSITY_KEY, "emotion_delta"),
}


def read_parameter(line: Mapping[str, Any] | None, key: str) -> float | None:
    """The authored value of one performance parameter (None when absent).

    Tolerant by design: a string number ("-15") is accepted because JSON
    round-trips lose the type, while a bool, NaN, ±inf, or a non-numeric string
    reads as "not authored" — the caller names the problem before it gets here.
    """

    if not isinstance(line, Mapping):
        return None
    for alias in PARAMETER_ALIASES.get(key, (key,)):
        if alias not in line:
            continue
        value = line[alias]
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            number = float(value)
        elif isinstance(value, str):
            try:
                number = float(value.strip())
            except ValueError:
                continue
        else:
            continue
        # NaN is never equal to itself; inf has no readable deviation.
        if number != number or number in (float("inf"), float("-inf")):
            continue
        return number
    return None


def _signed(value: float) -> str:
    """``-15.0`` -> ``-15``; ``0.4`` -> ``+0.4`` — the sign IS the deviation."""

    rounded = round(value, 1)
    if rounded.is_integer():
        return f"{int(rounded):+d}"
    return f"{rounded:+.1f}"


def describe_speech_rate(value: float | None) -> str:
    """``语速 -15%`` — tempo deviation in percent (negative = slower)."""

    if value is None or value == DEFAULT_SPEECH_RATE_PERCENT:
        return ""
    return f"语速 {_signed(value)}%"


def describe_pause(value: float | None) -> str:
    """``停顿 +0.4s`` — silence added after the line, in seconds."""

    if value is None or value == DEFAULT_PAUSE_AFTER_SECONDS:
        return ""
    return f"停顿 {_signed(value)}s"


def describe_emotion_intensity(value: float | None) -> str:
    """``情绪强度 +1`` — intensity steps relative to the written tone."""

    if value is None or value == DEFAULT_EMOTION_INTENSITY:
        return ""
    return f"情绪强度 {_signed(value)}"


def describe_dialogue_line_performance(line: Mapping[str, Any] | None) -> str:
    """One line's final execution parameters as a canonical Chinese sentence.

    Returns ``""`` when nothing deviates from the default — the caller shows no
    chip, because "understood as written" is not news.
    """

    fragments = (
        describe_speech_rate(read_parameter(line, SPEECH_RATE_PERCENT_KEY)),
        describe_pause(read_parameter(line, PAUSE_AFTER_SECONDS_KEY)),
        describe_emotion_intensity(read_parameter(line, EMOTION_INTENSITY_KEY)),
    )
    return FRAGMENT_SEPARATOR.join(fragment for fragment in fragments if fragment)


def performance_parameters(line: Mapping[str, Any] | None) -> dict[str, float]:
    """The readable parameters the lip-sync service carries (defaults dropped).

    Keeps a line's authored delivery instructions next to it, so the summary can
    echo exactly what was understood instead of re-deriving it.
    """

    readable: dict[str, float] = {}
    defaults = {
        SPEECH_RATE_PERCENT_KEY: DEFAULT_SPEECH_RATE_PERCENT,
        PAUSE_AFTER_SECONDS_KEY: DEFAULT_PAUSE_AFTER_SECONDS,
        EMOTION_INTENSITY_KEY: DEFAULT_EMOTION_INTENSITY,
    }
    for key, default in defaults.items():
        value = read_parameter(line, key)
        if value is not None and value != default:
            readable[key] = round(value, 3)
    return readable
