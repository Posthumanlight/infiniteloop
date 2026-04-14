export interface SkillHit {
  target_type: string;
  damage_type: string | null;
}

export interface Skill {
  skill_id: string;
  name: string;
  energy_cost: number;
  hits: SkillHit[];
}

export interface Passive {
  skill_id: string;
  name: string;
  trigger: string;
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

export interface CharacterBootstrap {
  sheet: CharacterSheet;
  legacy_text: string;
}
