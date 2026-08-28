import re

# O'zbek tili harflari uchun lug'at
LAT_TO_CYR = {
    "sh": "ш", "Sh": "Ш", "SH": "Ш",
    "ch": "ч", "Ch": "Ч", "CH": "Ч",
    "yo": "ё", "Yo": "Ё", "YO": "Ё",
    "yu": "ю", "Yu": "Ю", "YU": "Ю",
    "ya": "я", "Ya": "Я", "YA": "Я",
    "ye": "е", "Ye": "Е", "YE": "Е",
    "o'": "ў", "O'": "Ў", "o‘": "ў", "O‘": "Ў", "o`": "ў", "O`": "Ў",
    "g'": "ғ", "G'": "Ғ", "g‘": "ғ", "G‘": "Ғ", "g`": "ғ", "G`": "Ғ",
    "a": "а", "A": "А",
    "b": "б", "B": "Б",
    "d": "д", "D": "Д",
    "e": "е", "E": "Е",
    "f": "ф", "F": "Ф",
    "g": "г", "G": "Г",
    "h": "ҳ", "H": "Ҳ",
    "i": "и", "I": "И",
    "j": "ж", "J": "Ж",
    "k": "к", "K": "К",
    "l": "л", "L": "Л",
    "m": "м", "M": "М",
    "n": "н", "N": "Н",
    "o": "о", "O": "О",
    "p": "п", "P": "П",
    "q": "қ", "Q": "Қ",
    "r": "р", "R": "Р",
    "s": "с", "S": "С",
    "t": "т", "T": "Т",
    "u": "у", "U": "У",
    "v": "в", "V": "В",
    "x": "х", "X": "Х",
    "y": "й", "Y": "Й",
    "z": "з", "Z": "З",
    "'": "ъ", "‘": "ъ", "`": "ъ"
}

CYR_TO_LAT = {
    "ш": "sh", "Ш": "Sh",
    "ч": "ch", "Ч": "Ch",
    "ё": "yo", "Ё": "Yo",
    "ю": "yu", "Ю": "Yu",
    "я": "ya", "Я": "Ya",
    "ў": "o'", "Ў": "O'",
    "ғ": "g'", "Ғ": "G'",
    "қ": "q", "Қ": "Q",
    "ҳ": "h", "Ҳ": "H",
    "а": "a", "А": "A",
    "б": "b", "Б": "B",
    "в": "v", "В": "V",
    "г": "g", "Г": "G",
    "д": "d", "Д": "D",
    "е": "e", "Е": "E",
    "ж": "j", "Ж": "J",
    "з": "z", "З": "Z",
    "и": "i", "И": "I",
    "й": "y", "Й": "Y",
    "к": "k", "К": "K",
    "л": "l", "Л": "L",
    "м": "m", "М": "M",
    "н": "n", "Н": "N",
    "о": "o", "О": "O",
    "п": "p", "П": "P",
    "р": "r", "Р": "R",
    "с": "s", "С": "S",
    "т": "t", "Т": "T",
    "у": "u", "У": "U",
    "ф": "f", "Ф": "F",
    "х": "x", "Х": "X",
    "ц": "ts", "Ц": "Ts",
    "ъ": "'", "Ъ": "'",
    "ь": "", "Ь": "",
    "э": "e", "Э": "E"
}

def to_cyrillic(text: str) -> str:
    """Lotin yozuvidagi matnni Kirillga o'giradi."""
    if not text:
        return ""
    result = text
    # Avval 2 harfli birikmalarni o'giramiz
    for lat, cyr in LAT_TO_CYR.items():
        if len(lat) >= 2:
            result = result.replace(lat, cyr)
    # So'ngra 1 harflilarni
    for lat, cyr in LAT_TO_CYR.items():
        if len(lat) == 1:
            result = result.replace(lat, cyr)
    return result

def to_latin(text: str) -> str:
    """Kirill yozuvidagi matnni Lotinga o'giradi."""
    if not text:
        return ""
    result = text
    for cyr, lat in CYR_TO_LAT.items():
        result = result.replace(cyr, lat)
    return result
