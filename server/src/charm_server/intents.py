"""Rule-based intents on the final transcript (EN + ES). No model call.

`parse(text, reading)` returns one of the intents below, or None for an ordinary question.

- `EnterReading`: "I'm reading Superforecasting by Philip Tetlock, chapter 3" /
  "Estoy leyendo Cien años de soledad, capítulo 3".
- `SetChapter`: "I'm on chapter 4" / "Voy en el capítulo 4" (reading mode only).
- `LeaveReading`: "Stop reading" / "Deja de leer".
- `SaveThought`: "Save this: …" / "Guarda esto: …". The text is the owner's words after the
  trigger, **verbatim**: only the trigger words (and the separator after them) are removed.
- `SetSpeech`: "Voice on" / "Be quiet" / "Activa la voz" / "Silencio".

The rules are deliberately narrow: whole-utterance commands only. A transcript that asks
something ("I'm reading X, what does Y mean?") stays a question, because a wrong intent costs
more than a question Dex can answer anyway.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

TITLE_MAX = 80
AUTHOR_MAX = 60
CHAPTER_MAX = 30
TITLE_MAX_WORDS = 14


@dataclass(frozen=True)
class EnterReading:
    title: str
    author: str | None = None
    chapter: str | None = None


@dataclass(frozen=True)
class SetChapter:
    chapter: str


@dataclass(frozen=True)
class LeaveReading:
    pass


@dataclass(frozen=True)
class SaveThought:
    text: str  # verbatim; may be empty ("save this" with nothing after it)


@dataclass(frozen=True)
class SetSpeech:
    value: str  # "on" | "off"


Intent = EnterReading | SetChapter | LeaveReading | SaveThought | SetSpeech


# --- normalizing ------------------------------------------------------------------------------

_WAKE = r"(?:(?:hey|hi|ok|okay|oye|ey|so|and|y|bueno|vale)\s+)*(?:dex\s+)?"
_POLITE = r"(?:please|por favor|dex)"


def normalize(text: str) -> str:
    """Lowercase, no accents, words only: "¿Terminé de leer, Dex?" -> "termine de leer dex"."""
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[^\w' ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _command(text: str) -> str:
    """The normalized utterance minus a wake word in front and "please" around it."""
    norm = normalize(text)
    norm = re.sub(rf"^{_WAKE}(?:{_POLITE}\s+)*", "", norm)
    norm = re.sub(rf"(?:\s+{_POLITE})+$", "", norm)
    return norm.strip()


# --- numbers in chapter names ---------------------------------------------------------------

_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "uno": 1, "una": 1, "un": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13,
    "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18,
    "diecinueve": 19, "veinte": 20,
    "first": 1, "second": 2, "third": 3, "primero": 1, "primer": 1, "segundo": 2, "tercero": 3,
}  # fmt: skip
_ROMAN = re.compile(r"^(?=[ivxl]+$)l?x{0,3}(?:ix|iv|v?i{0,3})$")


def chapter_name(word: str) -> str | None:
    """ "3" / "three" / "tres" / "IV" -> a chapter name, or None if it isn't one."""
    word = normalize(word)
    if re.fullmatch(r"\d{1,4}", word):
        return str(int(word))
    if word in _NUMBERS:
        return str(_NUMBERS[word])
    if word and _ROMAN.match(word):
        return word.upper()
    return None


# --- save this ------------------------------------------------------------------------------

_SAVE = re.compile(
    r"^[\s\"'\u201c¿¡]*"
    r"(?:(?:hey|ok|okay|oye|so|and|y)[\s,]+)*(?:dex[\s,.:]+)?(?:(?:please|por\s+favor)[\s,]+)?"
    r"(?:"
    # EN
    r"save\s+(?:this|that)(?:\s+(?:thought|note|quote|idea|line|one))?"
    r"|save\s+(?:a|the|my)\s+(?:note|thought|quote|idea)"
    r"|note\s+this(?:\s+(?:down|thought))?"
    r"|take\s+(?:a\s+)?note(?:\s+of\s+this)?"
    # ES
    r"|guarda(?:me)?\s+(?:esto|eso|est[ae]\s+(?:idea|nota|frase|cita|pensamiento))"
    r"|guarda\s+(?:una|la)\s+(?:nota|idea|frase|cita)"
    r"|(?:anota|apunta)(?:me)?\s+(?:esto|eso)"
    r")"
    r"(?:[\s,]+(?:please|por\s+favor))?"
    r"(?=[\s:,.;!\-\u2013\u2014\"'\u201c\u201d]|$)[\s:,.;!\-\u2013\u2014]*"
    r"(?P<text>.*)$",
    re.IGNORECASE | re.DOTALL,
)


def parse_save(text: str) -> SaveThought | None:
    match = _SAVE.match(text)
    if match is None:
        return None
    return SaveThought(match.group("text").strip())


# --- speech on / off ------------------------------------------------------------------------

_SOUND = r"(?:the\s+)?(?:speech|voice|sound|audio|talking)"
_SPEECH_OFF = re.compile(
    r"(?:speech|voice|sound|audio) off"
    rf"|turn off {_SOUND}|turn {_SOUND} off|mute(?: yourself| the voice)?"
    r"|be quiet|(?:go )?quiet(?: mode)?|silent(?: mode)?|stop talking|text only|no voice"
    r"|don't talk|dont talk|don't speak|dont speak|just text"
    r"|silencio|modo silencio(?:so)?|(?:apaga|desactiva|quita) la voz|sin voz|solo texto"
    r"|callate|no hables|voz apagada|modo texto"
)
_SPEECH_ON = re.compile(
    r"(?:speech|voice|sound|audio) on"
    rf"|turn on {_SOUND}|turn {_SOUND} on|unmute(?: yourself)?|voice mode"
    r"|talk to me|speak (?:out loud|aloud|up)"
    r"|read (?:it|them|answers|your answers) (?:out loud|aloud)"
    r"|(?:activa|enciende|prende|pon|vuelve a poner) la voz|con voz|voz encendida|habla(?:me)?"
    r"|lee en voz alta|en voz alta"
)


def parse_speech(text: str) -> SetSpeech | None:
    cmd = _command(text)
    if _SPEECH_OFF.fullmatch(cmd):
        return SetSpeech("off")
    if _SPEECH_ON.fullmatch(cmd):
        return SetSpeech("on")
    return None


# --- leave reading --------------------------------------------------------------------------

_LEAVE = re.compile(
    r"stop reading(?: mode)?(?: for (?:now|today|tonight))?"
    r"|(?:i'm |i am |im )?(?:done|finished) reading(?: for (?:now|today|tonight))?"
    r"|(?:exit|leave|end|quit|close) reading(?: mode)?|reading mode off|close the book"
    r"|turn off reading(?: mode)?|no more reading(?: for (?:now|today|tonight))?"
    r"|(?:deja|dejar|dejemos) de leer(?: por (?:hoy|ahora))?"
    r"|(?:ya )?(?:termine|acabe) de leer(?: por (?:hoy|ahora))?"
    r"|(?:sal|salir|salgamos|salgo) del modo (?:de )?lectura|ya no estoy leyendo"
    r"|cierra el libro|modo (?:de )?lectura apagado|apaga el modo (?:de )?lectura"
)


def parse_leave(text: str) -> LeaveReading | None:
    return LeaveReading() if _LEAVE.fullmatch(_command(text)) else None


# --- chapter updates ------------------------------------------------------------------------

_CHAPTER_WORD = r"(?:chapter|ch|capitulo|cap)"
_CHAPTER_UPDATE = re.compile(
    r"(?:"
    r"(?:(?:i'm|i am|im|we're|we are) (?:now )?(?:on|in|at|starting|reading|onto|on to)"
    r"|now (?:on |in |reading )?|moving (?:on )?to|on to|onto|starting|next|update(?: the)?"
    r"|(?:ya |ahora )?(?:voy|estoy|vamos) (?:en|por|leyendo)|paso a|pase a|empiezo|empece"
    r"|ahora|ya en|ahora en|seguimos en|sigo en|vamos con"
    r") )?"
    rf"(?:(?:the|el) )?{_CHAPTER_WORD} (?P<ch>\w+)(?: now| ya| ahora)?"
)


def parse_chapter(text: str) -> SetChapter | None:
    match = _CHAPTER_UPDATE.fullmatch(_command(text))
    if match is None:
        return None
    chapter = chapter_name(match.group("ch"))
    return SetChapter(chapter) if chapter else None


# --- enter reading --------------------------------------------------------------------------

_ENTER_PREFIX = re.compile(
    r"^[\s\"'\u201c¿¡]*(?:(?:hey|ok|okay|oye|so|and|y|bueno)[\s,]+)*(?:dex[\s,.:]+)?"
    r"(?:"
    # EN
    r"(?:i['\u2019]?m|i\s+am)\s+(?:now\s+|currently\s+|just\s+)?(?:re-?reading|reading|starting)"
    r"|i(?:['\u2019]ve)?\s+(?:just\s+)?(?:started|begun|began)(?:\s+reading)?"
    r"|(?:let['\u2019]?s|let\s+us)\s+read|start(?:ing)?\s+reading|now\s+reading"
    r"|reading\s+mode(?:\s+for)?"
    # ES
    r"|(?:estoy|ando)\s+(?:ahora\s+)?(?:leyendo|releyendo|empezando)"
    r"|(?:empec[ée]|comenc[ée]|acabo\s+de\s+empezar)(?:\s+a\s+leer)?"
    r"|(?:voy|vamos)\s+a\s+leer|ahora\s+leo|modo\s+lectura(?:\s+con|\s+para)?"
    r")"
    r"[\s:,]+(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)
# Things one "reads" that aren't a book: "I'm reading about inflation", "estoy leyendo sobre…".
_NOT_A_TITLE = re.compile(
    r"^(?:about|up\s+on|on|that|this|it|some|something|a\s+lot|lots|the\s+news|news|an?\s+article"
    r"|articles|your|my\s+(?:email|emails|messages|notes)|what|how|why|when|chapter|ch\b"
    r"|sobre|acerca|que|esto|eso|algo|mucho|un\s+poco|las\s+noticias|noticias|un\s+art[ií]culo"
    r"|mis\s+(?:correos|mensajes|notas)|cap[ií]tulo)\b",
    re.IGNORECASE,
)
_TRAILING_CHAPTER = re.compile(
    r"[\s,.;:\-\u2013\u2014]*(?:(?:and\s+)?(?:i['\u2019]?m\s+|i\s+am\s+)?(?:on|in|at)\s+|(?:y\s+)?(?:voy|estoy)\s+"
    r"(?:en|por)\s+|en\s+)?(?:the\s+|el\s+)?(?:chapter|ch\.?|cap[ií]tulo|cap\.)\s+(?P<ch>[\w]+)"
    r"[\s.!]*$",
    re.IGNORECASE,
)
_BOOK_WORDS = re.compile(
    r"^(?:the\s+book|a\s+book\s+called|a\s+book|the\s+novel|a\s+novel\s+called"
    r"|el\s+libro|un\s+libro\s+llamado|un\s+libro|la\s+novela)\s+",
    re.IGNORECASE,
)
_QUOTES = "\"'\u201c\u201d\u2018\u2019\u00ab\u00bb*_"
_NAME_PARTICLES = {"de", "del", "la", "las", "los", "y", "van", "von", "der", "da", "di", "le"}


def _looks_like_name(text: str) -> bool:
    words = text.split()
    if not 1 <= len(words) <= 5:
        return False
    return all(w[:1].isupper() or w.lower() in _NAME_PARTICLES for w in words) and (
        words[0][:1].isupper() and words[-1][:1].isupper()
    )


def _split_author(rest: str) -> tuple[str, str | None]:
    """ "Title by Author" / "Título de Autor Apellido" / "Título por Autor"."""
    for pattern in (r"\s+by\s+", r"\s+por\s+", r"\s+del\s+autor\s+", r"\s+de\s+la\s+autora\s+"):
        found = list(re.finditer(pattern, rest, flags=re.IGNORECASE))
        if found:
            last = found[-1]
            title, author = rest[: last.start()].strip(), rest[last.end() :].strip(" ,.;")
            if title and author:
                return title, author
    # Spanish "de": "Cien años de soledad de Gabriel García Márquez". Titles use "de" too, so
    # only the last "de" counts, and only when what follows looks like a person's name.
    match = re.match(r"^(?P<title>.+)\s+de\s+(?P<author>[^,]+)$", rest)
    if match and len(match.group("author").split()) >= 2 and _looks_like_name(match["author"]):
        return match.group("title").strip(), match.group("author").strip()
    return rest, None


def _clean(text: str) -> str:
    text = text.strip().strip(_QUOTES).strip(" ,.;:!-\u2013\u2014").strip(_QUOTES).strip()
    return re.sub(r"\s+", " ", text)


def parse_enter(text: str) -> EnterReading | None:
    if "?" in text or "¿" in text:
        return None  # a question about reading, not a statement of what's being read
    match = _ENTER_PREFIX.match(text.strip())
    if match is None:
        return None
    rest = match.group("rest").strip()
    if _NOT_A_TITLE.match(rest):
        return None
    chapter: str | None = None
    ch = _TRAILING_CHAPTER.search(rest)
    if ch is not None:
        chapter = chapter_name(ch.group("ch"))
        if chapter is None:
            return None
        rest = rest[: ch.start()]
    rest = _clean(rest)
    rest = _BOOK_WORDS.sub("", rest)
    title, author = _split_author(rest)
    title, author = _clean(title), _clean(author) if author else None
    if not title or len(title) > TITLE_MAX or len(title.split()) > TITLE_MAX_WORDS:
        return None
    if re.search(r"[.!;]\s", title):
        return None  # more than one sentence: not just a title
    if author is not None and (not author or len(author) > AUTHOR_MAX):
        author = None
    return EnterReading(title=title[0].upper() + title[1:], author=author, chapter=chapter)


# --- all together ---------------------------------------------------------------------------


def parse(text: str, reading: bool) -> Intent | None:
    """The intent of a final transcript, or None for an ordinary question.

    Save comes first (anything after the trigger is the thought, even words that look like a
    command). Chapter updates only mean something in reading mode.
    """
    if not text.strip():
        return None
    for rule in (parse_save, parse_speech, parse_leave):
        intent = rule(text)
        if intent is not None:
            return intent
    if reading:
        chapter = parse_chapter(text)
        if chapter is not None:
            return chapter
    return parse_enter(text)
