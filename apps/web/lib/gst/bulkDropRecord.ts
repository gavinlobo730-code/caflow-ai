/** What the panel says, below the table, about answered files the server did
 *  not record (POST-A-057). Names them when other files of the drop were
 *  recorded; speaks of the whole drop only when none was. */
export function notRecordedSentence(names: string[], anyRecorded: boolean): string | null {
  if (names.length === 0) return null;
  const tail = "will not be listed under Your recent drops after this page is closed. "
    + "The results in the table are the server's answers.";
  if (!anyRecorded) {
    return `What the server did with the files of this drop was not recorded, so they ${tail}`;
  }
  return names.length === 1
    ? `What the server did with ${names[0]} was not recorded, so it ${tail}`
    : `What the server did with ${names.join(", ")} was not recorded, so they ${tail}`;
}
