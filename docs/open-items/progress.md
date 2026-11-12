# Progress: the day by day numbers

Two lists are counted here, and the owner asked on 7 November 2026 for them to be kept apart (see `new-findings.md`): **the backlog** (everything on the ledger on the evening of 5 November 2026, 487 open) and **the new findings** (everything found from 6 November on). Days are Indian days (IST). The numbers are the ledger's own: they are read from the counts in the README at the last change of each day, and each change that closes or adds a line adds or updates its day's row in the same commit.

| day (IST) | backlog open | closed from the backlog (or parked) | added to the backlog | new findings open | new findings found | new findings fixed |
|---|---|---|---|---|---|---|
| 1 Nov | 494 | — | — | — | — | — |
| 2 Nov | 492 | 5 | 3 | — | — | — |
| 3 Nov | 488 | 8 | 4 | — | — | — |
| 4 Nov | 486 | 4 | 2 | — | — | — |
| 5 Nov | 487 | 0 | 1 | — | — | — |
| 6 Nov | 486 | 1 | 0 | 18 | 29 | 11 |
| 7 Nov | 482 | 4 | 0 | 26 | 16 | 8 |
| 12 Nov | 481 | 1 | 0 | 27 | 6 | 5 |

How to read it.
- Before 6 November a finding was added to the backlog (the "added" column); from 6 November it goes to the new findings. The two columns do not overlap.
- "Closed" counts a line that left the open files that day, closed or parked. A large item closes on the day its last slice merges, so a day with a big closure is not comparable with a day without one: 5 and 6 November were the end of the date-box sweep (PRE-A-015), which closed as one line after eighteen slices.
- 6 November's 29 new findings are the lines `POST-A-381` to `POST-A-409`: 11 were fixed the same day, 18 were still open at its end. "Fixed" counts any new finding closed that day, whenever it was found.
- The backlog's Claude-alone items that can be built now are counted in the README ("so N can be built now"); that is the number that says how much of the backlog is Claude's to finish.
