/**
 * Whether a workspace's tile is offered by the rbac pairs it names (POST-A-447): `requires` must admit the caller, and
 * where `requiresAnyOf` is set at least one of its pairs must. The product role rule (`canAccessWorkspace`) is asked
 * by the caller beside this. Nothing is withheld while the permission map is still being read, so a tile does not
 * flash in and then out on the first frame; the server still refuses whatever the caller cannot do.
 *
 * Kept apart from `workspaceConfig.ts` so it can be tested without the icons that file imports.
 */
export function workspaceTileOffered(
  ws: {
    requires?: readonly [resource: string, action: string];
    requiresAnyOf?: ReadonlyArray<readonly [resource: string, action: string]>;
  },
  can: (resource: string, action: string) => boolean,
  resolved: boolean,
): boolean {
  if (!resolved) return true;
  if (ws.requires && !can(ws.requires[0], ws.requires[1])) return false;
  if (ws.requiresAnyOf && !ws.requiresAnyOf.some(([r, a]) => can(r, a))) return false;
  return true;
}
