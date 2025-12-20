from dataclasses import dataclass

@dataclass
class cls_2:
    b: int

@dataclass
class cls_1:
    a: cls_2

from .utils.CsvHandler import CsvHandler

