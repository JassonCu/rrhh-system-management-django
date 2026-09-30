"""Formatos localizados para Guatemala.

Django trae el catálogo genérico ``es`` con la convención de España: coma
decimal y espacio duro como separador de millares (``1 500,00``). En Guatemala
es al revés: punto decimal y coma de millares (``1,500.00``). Sin este módulo,
todo importe salarial se mostraría con la coma en el lugar equivocado — el error
de localización más caro y más silencioso que puede tener un sistema de nómina.

Ver docs/architecture/14-internacionalizacion.md §O.2.2. Hay una prueba que fija
este comportamiento: apps/core/tests/test_formats.py
"""

DECIMAL_SEPARATOR = "."
THOUSAND_SEPARATOR = ","
NUMBER_GROUPING = 3

DATE_FORMAT = "d/m/Y"
SHORT_DATE_FORMAT = "d/m/Y"
DATETIME_FORMAT = "d/m/Y H:i"
SHORT_DATETIME_FORMAT = "d/m/Y H:i"
TIME_FORMAT = "H:i"
YEAR_MONTH_FORMAT = "F Y"
MONTH_DAY_FORMAT = r"j \d\e F"

FIRST_DAY_OF_WEEK = 1  # lunes

DATE_INPUT_FORMATS = [
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y-%m-%d",  # ISO, para el input type=date de los navegadores
]
DATETIME_INPUT_FORMATS = [
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
]
TIME_INPUT_FORMATS = ["%H:%M", "%H:%M:%S"]
