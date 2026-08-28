import re

# Lotin -> Kirill juftliklari
LAT_TO_CYR_RULES = [
    # Maxsus harflar (har xil apostroflar bilan)
    ("o'", "ў"), ("O'", "Ў"), ("o‘", "ў"), ("O‘", "Ў"), ("o`", "ў"), ("O`", "Ў"), ("o’", "ў"), ("O’", "Ў"),
    ("g'", "ғ"), ("G'", "Ғ"), ("g‘", "ғ"), ("G‘", "Ғ"), ("g`", "ғ"), ("G`", "Ғ"), ("g’", "ғ"), ("G’", "Ғ"),
    
    # 2 ta belgili birikmalar
    ("sh", "ш"), ("Sh", "Ш"), ("SH", "Ш"),
    ("ch", "ч"), ("Ch", "Ч"), ("CH", "Ч"),
    ("yo", "ё"), ("Yo", "Ё"), ("YO", "Ё"),
    ("yu", "ю"), ("Yu", "Ю"), ("YU", "Ю"),
    ("ya", "я"), ("Ya", "Я"), ("YA", "Я"),
    ("ye", "е"), ("Ye", "Е"), ("YE", "Е"),
    ("ts", "ц"), ("Ts", "Ц"), ("TS", "Ц"),
    
    # 1 ta belgili harflar
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
    ("'", "ъ"), ("‘", "ъ"), ("`", "ъ"), ("’", "ъ")
]

# Kirill -> Lotin juftliklari
CYR_TO_LAT_RULES = [
    ("Щ", "Ch"), ("щ", "ch"),
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
    ("Ь", ""),   ("ь", "")
]


def fix_word_case(word: str) -> str:
    """Agar so'z to'liq katta harflarda bo'lsa, 'YaNGI' -> 'YANGI' qiladi."""
    letters = [c for c in word if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        return word.upper()
    return word


def to_latin(text: str) -> str:
    """Kirill matnini toza Lotin yozuviga o'tkazadi."""
    if not text:
        return ""

    result = text

    # 'Е' harfini so'z boshida yoki unlilardan keyin 'Ye' qilib to'g'rilash
    result = re.sub(r'(^|[\s\(\[\{\"\'])Е', r'\1Ye', result)
    result = re.sub(r'(^|[\s\(\[\{\"\'])е', r'\1ye', result)
    result = re.sub(r'([АЕЁИОУЎЭЮЯаеёиоуўэюя])Е', r'\1Ye', result)
    result = re.sub(r'([АЕЁИОУЎЭЮЯаеёиоуўэюя])е', r'\1ye', result)

    for cyr, lat in CYR_TO_LAT_RULES:
        result = result.replace(cyr, lat)

    # Katta harflar aralashib qolmasligi uchun so'zma-so'z tekshiramiz
    words = result.split(" ")
    fixed_words = [fix_word_case(w) for w in words]
    return " ".join(fixed_words)


def to_cyrillic(text: str) -> str:
    """Lotin matnini toza Kirill yozuviga o'tkazadi."""
    if not text:
        return ""

    result = text

    # Standartlashtirish: turli noodatiy apostroflarni bitta qolipga keltiramiz
    result = result.replace("‘", "'").replace("’", "'").replace("`", "'")

    for lat, cyr in LAT_TO_CYR_RULES:
        result = result.replace(lat, cyr)

    return result
