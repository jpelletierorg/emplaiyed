"""CV and motivation letter generation for job applications."""

from emplaiyed.generation.cv_generator import GeneratedCV, generate_cv
from emplaiyed.generation.letter_generator import GeneratedLetter, generate_letter

__all__ = [
    "GeneratedCV",
    "GeneratedLetter",
    "generate_cv",
    "generate_letter",
]
