export interface SkillHit {
  target_type: string;
  damage_type: string | null;
}

export type WebAppView = 'character' | 'inventory';

export interface Skill {
  skill_id: string;
  name: string;
  energy_cost: number;
  hits: SkillHit[];
  temporary: boolean;
}

export interface Passive {
  skill_id: string;
  name: string;
  triggers: string[];
  action: string;
}

export interface Modifier {
  modifier_id: string;
  name: string;
  stack_count: number;
}

export interface ActiveEffect {
  effect_id: string;
  name: string;
  remaining_duration: number;
  stack_count: number;
  is_buff: boolean;
  granted_skills: string[];
  blocked_skills: string[];
}

export interface CharacterSheet {
  entity_id: string;
  display_name: string;
  class_id: string;
  class_name: string;
  level: number;
  xp: number;
  current_hp: number;
  max_hp: number;
  current_energy: number;
  max_energy: number;
  major_stats: Record<string, number>;
  minor_stats: Record<string, number>;
  skills: Skill[];
  passives: Passive[];
  modifiers: Modifier[];
  active_effects: ActiveEffect[];
  in_combat: boolean;
}

export interface ItemEffect {
  effect_type: string;
  stat: string | null;
  value: number | null;
  skill_id: string | null;
  passive_id: string | null;
}

export interface Item {
  instance_id: string;
  blueprint_id: string;
  name: string;
  item_type: string;
  quality: number;
  equipped_slot: string | null;
  equipped_index: number | null;
  effects: ItemEffect[];
}

export interface EquipmentSlot {
  slot_type: 'weapon' | 'armor' | 'relic';
  slot_index: number | null;
  label: string;
  accepts_item_type: 'weapon' | 'armor' | 'relic';
  item: Item | null;
}

export interface InventorySnapshot {
  items: Item[];
  unequipped_items: Item[];
  equipment_slots: EquipmentSlot[];
  can_manage_equipment: boolean;
  equipment_lock_reason: string | null;
}

export interface WebAppBootstrap {
  initial_view: WebAppView;
  sheet: CharacterSheet;
  inventory: InventorySnapshot;
  legacy_text: string;
}

export interface InventoryMoveResponse {
  sheet: CharacterSheet;
  inventory: InventorySnapshot;
}
