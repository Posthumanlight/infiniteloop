from dataclasses import dataclass

@dataclass
class BaseEntity():
    id: int
    name: str
    current_hp: int
    max_hp: int
    entity_type : list
    owner : str

