// Relationship Intelligence — types and interfaces only (Phase 0 stub)
// Graph computation is Phase 1

export type EntityKind =
  | "individual" | "company" | "llp" | "partnership"
  | "trust" | "huf" | "other";

export type RelationshipKind =
  | "director" | "shareholder" | "partner" | "trustee" | "beneficiary"
  | "proprietor" | "guarantor" | "authorized_signatory"
  | "related_party" | "group_company";

export interface RiEntity {
  id: string;
  firm_id: string;
  kind: EntityKind;
  display_name: string;
  pan: string | null;
  gstin: string | null;
  din: string | null;
  aadhaar_last4: string | null;
  email: string | null;
  phone: string | null;
  is_verified: boolean;
  merged_into: string | null;
  created_at: string;
  updated_at: string;
}

export interface ClientEntityLink {
  id: string;
  firm_id: string;
  client_id: string;
  entity_id: string;
  relationship: RelationshipKind;
  ownership_pct: number | null;
  effective_from: string | null;
  effective_to: string | null;
  source: string | null;
  notes: string | null;
  created_at: string;
  entity?: RiEntity;
}

export interface EntityRelationship {
  id: string;
  firm_id: string;
  from_entity_id: string;
  to_entity_id: string;
  relationship: RelationshipKind;
  effective_from: string | null;
  effective_to: string | null;
  source: string | null;
  notes: string | null;
  created_at: string;
}

export interface CrossClientSignal {
  id: string;
  firm_id: string;
  entity_id: string;
  client_ids: string[];
  signal_type: string;
  detected_at: string;
  dismissed_at: string | null;
  dismissed_by: string | null;
  entity?: RiEntity;
}
