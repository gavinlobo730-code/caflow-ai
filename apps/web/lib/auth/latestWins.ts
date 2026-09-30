// Only the most recently STARTED request may settle a piece of state.
//
// AuthContext resolves the permissions map from four places — getSession,
// every onAuthStateChange event, refreshUserContext, and (since enrolment
// became reachable) the security page after a factor is verified — and none
// of them waited for the one before. An aal1 request that 403'd and landed
// AFTER the aal2 one that succeeded wrote `null` over the good map, and every
// action control vanished again until the next event happened to fire. Order
// of arrival is the network's; order of asking is ours.
//
// Dependency-free, for `node --experimental-strip-types --test`.

export interface LatestWins {
  /** Start a request; the returned setter applies only while it is the latest. */
  begin<T>(apply: (value: T) => void): (value: T) => void;
}

export function latestWins(): LatestWins {
  let generation = 0;
  return {
    begin<T>(apply: (value: T) => void) {
      const mine = ++generation;
      return (value: T) => {
        if (mine === generation) apply(value);
      };
    },
  };
}

/**
 * Wrap a setter so that `null` — a resolver's "that failed" — is applied only
 * when `replaceWithNull` is true. AuthContext passes `newUser`: for a different
 * identity the old answer is wrong and must go, while for the SAME identity a
 * failed hourly TOKEN_REFRESHED fetch is not news about them, and applying it
 * hid every action control until the next refresh.
 */
export function keepLastGood<T>(apply: (value: T | null) => void, replaceWithNull: boolean) {
  return (value: T | null) => {
    if (value !== null || replaceWithNull) apply(value);
  };
}
