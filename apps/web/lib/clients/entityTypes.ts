// The legal forms a client, or the firm itself, may be recorded as: the values `clients.entity_type` may hold
// (migration 453 added the last three).
//
// ONE LIST FOR THE FORMS THAT ASK THE QUESTION. It lived inside the client form; the sign-up's firm profile asks the same
// question of the firm itself (POST-A-533) and reads it from here, so that asking it in a second place did not make a
// second copy. It is pinned from the Python side against models/client.EntityType
// (tests/test_a_huf_aop_and_boi_have_their_own_tax_basis.py), because a list asserted against its own copy passes
// whenever both drift together.
export const ENTITY_TYPES = [
  "Proprietorship", "Partnership", "LLP", "Private Limited",
  "Public Limited", "Trust", "Society", "Individual",
  "HUF", "AOP", "BOI",
];
