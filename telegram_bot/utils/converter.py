import re

# ============================================================
# Lotin ⇄ Kirill To'liq Harflar Xaritasi
# ============================================================

LAT_TO_CYR_RULES = [
    # O' va G' turli xil apostroflar bilan
    ("o'", "ў"), ("O'", "Ў"), ("o‘", "ў"), ("O‘", "Ў"), ("o`", "ў"), ("O`", "Ў"), ("o’", "ў"), ("O’", "Ў"),
    ("g'", "ғ"), ("G'", "Ғ"), ("g‘", "ғ"), ("G‘", "Ғ"), ("g`", "ғ"), ("G`", "Ғ"), ("g’", "ғ"), ("G’", "Ғ"),
    # Birikmalar (2 harfli)
    ("sh", "ш"), ("Sh", "Ш"), ("SH", "Ш"), ("sH", "ш"),
    ("ch", "ч"), ("Ch", "Ч"), ("CH", "Ч"), ("cH", "ч"),
    ("yo", "ё"), ("Yo", "Ё"), ("YO", "Ё"), ("yO", "ё"),
    ("yu", "ю"), ("Yu", "Ю"), ("YU", "Ю"), ("yU", "ю"),
    ("ya", "я"), ("Ya", "Я"), ("YA", "Я"), ("yA", "я"),
    ("ye", "е"), ("Ye", "Е"), ("YE", "Е"), ("yE", "е"),
    ("ts", "ц"), ("Ts", "Ц"), ("TS", "Ц"), ("tS", "ц"),
    # Yakka harflar
    ("a", "а"), ("A", "А"),
    ("b", "б"), ("B", "Б"),
    ("d", "д"), ("D", "Д"),
    ("e", "е"), ("E", "Е"),
    ("f", "ф"), ("F", "Ф"),
    ("g", "г"), ("G", "Г"),
    ("h", "ҳ"), ("H", "Ҳ"),
    ("i", "и"), ("I", "И"),
    ("j", "ж"), ("J", "Ж"),
    ("k", "к"), ("K", "К"),
    ("l", "л"), ("L", "Л"),
    ("m", "м"), ("M", "М"),
    ("n", "н"), ("N", "Н"),
    ("o", "о"), ("O", "О"),
    ("p", "п"), ("P", "П"),
    ("q", "қ"), ("Q", "Қ"),
    ("r", "р"), ("R", "Р"),
    ("s", "с"), ("S", "С"),
    ("t", "т"), ("T", "Т"),
    ("u", "у"), ("U", "У"),
    ("v", "в"), ("V", "В"),
    ("x", "х"), ("X", "Х"),
    ("y", "й"), ("Y", "Й"),
    ("z", "з"), ("Z", "З"),
    # Tutuq belgisi (ъ)
    ("'", "ъ"), ("‘", "ъ"), ("`", "ъ"), ("’", "ъ"),
]

CYR_TO_LAT_RULES = [
    # Щ/щ — o'zbek lotin alifbosida "Sh/sh" bilan beriladi (avval xato "Ch" edi)
    ("Щ", "Sh"), ("щ", "sh"),
    ("Ц", "Ts"), ("ц", "ts"),
    ("Ч", "Ch"), ("ч", "ch"),
    ("Ш", "Sh"), ("ш", "sh"),
    ("Ё", "Yo"), ("ё", "yo"),
    ("Ю", "Yu"), ("ю", "yu"),
    ("Я", "Ya"), ("я", "ya"),
    ("Ў", "O'"), ("ў", "o'"),
    ("Ғ", "G'"), ("ғ", "g'"),
    ("Қ", "Q"),  ("қ", "q"),
    ("Ҳ", "H"),  ("ҳ", "h"),
    ("Х", "X"),  ("х", "x"),
    ("А", "A"),  ("а", "a"),
    ("Б", "B"),  ("б", "b"),
    ("В", "V"),  ("в", "v"),
    ("Г", "G"),  ("г", "g"),
    ("Д", "D"),  ("д", "d"),
    ("Ж", "J"),  ("ж", "j"),
    ("З", "Z"),  ("з", "z"),
    ("И", "I"),  ("и", "i"),
    ("Й", "Y"),  ("й", "y"),
    ("К", "K"),  ("к", "k"),
    ("Л", "L"),  ("л", "l"),
    ("М", "M"),  ("м", "m"),
    ("Н", "N"),  ("н", "n"),
    ("О", "O"),  ("о", "o"),
    ("П", "P"),  ("п", "p"),
    ("Р", "R"),  ("р", "r"),
    ("С", "S"),  ("с", "s"),
    ("Т", "T"),  ("т", "t"),
    ("У", "U"),  ("у", "u"),
    ("Ф", "F"),  ("ф", "f"),
    ("Э", "E"),  ("э", "e"),
    ("Е", "E"),  ("е", "e"),
    ("Ъ", "'"),  ("ъ", "'"),
    ("Ь", ""),   ("ь", ""),
]


def fix_word_case(word: str) -> str:
    letters = [c for c in word if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        return word.upper()
    return word


def to_latin(text: str) -> str:
    """Kirill yozuvidagi matnni Lotin yozuviga o'giradi."""
    if not text:
        return ""
    result = text
    # So'z boshida yoki unlidan keyin kelgan 'E/e' -> 'Ye/ye'
    result = re.sub(r'(^|[\s\(\[\{\"\'])Е', r'\1Ye', result)
    result = re.sub(r'(^|[\s\(\[\{\"\'])е', r'\1ye', result)
    result = re.sub(r'([АЕЁИОУЎЭЮЯаеёиоуўэюя])Е', r'\1Ye', result)
    result = re.sub(r'([АЕЁИОУЎЭЮЯаеёиоуўэюя])е', r'\1ye', result)

    for cyr, lat in CYR_TO_LAT_RULES:
        result = result.replace(cyr, lat)

    words = result.split(" ")
    return " ".join([fix_word_case(w) for w in words])


def to_cyrillic(text: str) -> str:
    """Lotin yozuvidagi matnni Kirill yozuviga o'giradi."""
    if not text:
        return ""
    result = text.replace("‘", "'").replace("’", "'").replace("`", "'")
    for lat, cyr in LAT_TO_CYR_RULES:
        result = result.replace(lat, cyr)
    return result
