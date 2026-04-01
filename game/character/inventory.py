from dataclasses import dataclass, field

@dataclass
class Inventory:
    max_slots: int = 6
    content: dict = field(default_factory=dict)

    def add_item(self, item):
        if self.content[item]:
            self.content[item] += 1
        else:
            self.content[item] = 1
    def remove_item(self, item):
        if self.content[item] > 0:
            self.content[item] -= 1
        else:
            del self.content[item]

