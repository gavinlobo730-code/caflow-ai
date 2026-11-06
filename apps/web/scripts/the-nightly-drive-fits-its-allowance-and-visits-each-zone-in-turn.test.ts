// THE NIGHTLY DRIVE FITS ITS ALLOWANCE, STOPS ITSELF BEFORE IT, AND EVERY ZONE AND EVERY DATE SCENARIO IS VISITED IN TURN (POST-A-397). Run with:
//   node --experimental-strip-types --test scripts/the-nightly-drive-fits-its-allowance-and-visits-each-zone-in-turn.test.ts
//
// THE DEFECT. The nightly money-editor drive outgrew its 45-minute allowance one slice of the date group at a time, and nothing measured it. The run that began its drive at 06:48 IST on 6 November
// 2026 was cancelled at the limit, 28 minutes into the drive, and left no drive report. (The browser install alone took 8 min 46 s that night, against 19 s on the night before.) The report
// was written at the end, and the first idea for saving it, writing it as the drive goes, would not have helped: GitHub's own record of that run shows the drive step still `in_progress` and the step
// that uploads the report still `pending` when the job ended, 55 minutes after it began, against an allowance of 45. A job that times out is cancelled, and its later steps never run.
//
// THE FIX, AND WHAT IT DOES NOT DO. The allowance is the OWNER'S MONEY and is not raised; the drive was cut to fit it, and it now stops ITSELF before the allowance. A night drives ONE zone of the matrix's
// three and ONE half of the date group (`--zone rotate`), taken in turn by the INDIAN day, so that over any six consecutive nights every zone sees every date scenario once. The other groups run in full
// every night. The runner is given a DEADLINE (`--stop-after`): after it, it starts no more scenarios, writes its report with the runs it did not drive named, and exits 1, so the job goes red, uploads the
// report and ends inside its allowance. A person can still ask for everything (about 77 minutes of drive, a cap of 120, only on request).
//
// WHY THE INDIAN DAY. The nightly is scheduled for 02:00 IST (20:30 UTC), but GitHub starts it hours late: the drive step began at 05:43, 05:34, 05:10, 05:23, 08:08, 06:23, 06:37 and 06:48 IST
// in the eight nights before this was written, which straddles UTC midnight (05:30 IST). Keyed on the UTC day, those eight nights drove America/Los_Angeles on two nights running (31 October
// and 1 November) and left Pacific/Kiritimati undriven for the five nights between its two visits, where a rotation of three promises every zone at least every third night. A job that belongs
// to the Indian day is read by the Indian day (the repo's own rule), and no run has started more than ten hours after its schedule. The real instants are in this file, so the rule is held
// against what actually happens and not against a tidy 20:30 every night.
//
// HOW THE RUNNER'S OWN WIRING IS HELD. The rotation's functions live in `drive/kit.mjs` and are tried directly, but a first review found that deleting the runner's USE of them (the shard filter, the zone
// filter, the clock it reads the rotation at, `complete &&` in a report's `ok`) left every test green. So the runner has `--list` (print the runs it would drive, and exit before any build or browser is
// needed) and `--now` (read the rotation at a given instant), and the tests below spawn the real runner and compare what it lists with what the rule says, night by night.
//
// WHAT THIS CANNOT SEE. How long a real runner takes tonight: the per-run seconds below are read off two real nights (the step times of the runs of 4 and 5 November) and the budget keeps a margin. If the
// drive grows past the budget this fails ONE run and says what to do; it never fails because a night was slow. And the deadline itself: stopping, the final report and the exit code are read as text
// and through the pure functions (`deadlinePassed`, `reportOf`), because driving the runner needs a build and a browser; the pull request that introduced the deadline ran it against a real export.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import {
  FLAGS, MAX_STOP_AFTER_MINUTES, SHARDS, TZ_MATRIX, contextsFor, deadlinePassed, inShard, indianDayNumber, parseArgs, partOfTheNight, reportOf, resolveNow, resolveShard,
  resolveStopAfter, resolveZone, shardOf, zoneOfTheDay,
} from "./drive/kit.mjs";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const REPO = join(WEB, "..", "..");
const SCENARIO_DIR = join(WEB, "scripts", "drive", "scenarios");
const WORKFLOW = readFileSync(join(REPO, ".github", "workflows", "smoke-walk.yml"), "utf8");
const RUNNER_PATH = join(WEB, "scripts", "driveMoneyEditors.mjs");
const RUNNER = readFileSync(RUNNER_PATH, "utf8");

const DAY = 86_400_000;
const IST = 19_800_000;
const ZONES = TZ_MATRIX.map((c) => c.timezoneId);

// What the runner's own step times gave (smoke-walk runs 41749300419 and 41945303205, 4 and 5 November 2026): 216 runs (59 of them date runs) took 9 min 18 s and 342 (185 date runs) took
// 19 min 38 s, which is 4.92 s a date run and 1.71 s any other run. A date run is slower because most of them type, leave, wait for the network to go quiet and assert twice.
const SECONDS_PER_DATE_RUN = 4.92;
const SECONDS_PER_OTHER_RUN = 1.71;
/** The most a night has cost between the job's start and the drive's start (checkout, install, the browser, the build and the walk): 16 min 26 s on 6 November (run 42141029562: the job began at 01:02:02Z and the drive
 *  step at 01:18:28Z; the browser install took 8 min 46 s), 8 min 8 s on the 5th (run 41945303205). 17 is used. */
const WORST_SETUP_MINUTES = 17;
/** What the steps after the drive take (the report upload, the screenshots upload and the post steps): 4 seconds on 5 November. A minute is kept. */
const FINISH_MINUTES = 1;
/** What is kept back for a runner that is slower than the nights above were. */
const MARGIN_MINUTES = 3;
const NIGHT_CAP_MINUTES = 45;
const MATRIX_CAP_MINUTES = 120;

/** When the drive step of the last eight scheduled runs began, in IST (smoke-walk runs 40977407446, 41147393838, 41252918100, 41363586508, 41566658422, 41749300419, 41945303205, 42141029562). */
const REAL_STARTS_IST: Array<[number, number, number, number, number]> = [
  [2026, 10, 30, 5, 43], [2026, 10, 31, 5, 34], [2026, 11, 1, 5, 10], [2026, 11, 2, 5, 23], [2026, 11, 3, 8, 8], [2026, 11, 4, 6, 23], [2026, 11, 5, 6, 37], [2026, 11, 6, 6, 48],
];
const realStarts = REAL_STARTS_IST.map(([y, m, d, h, min]) => Date.UTC(y, m - 1, d, h, min) - IST);

// ── the rotation, as a rule over any implementation of it, so the test's own strength can be tried ───────────────────────────────────────

type Part = { zone: string; shard: number };
type Rotation = (epochMs: number) => Part;

/** What is wrong with a rotation over the given consecutive nights (one instant each): a zone repeated on the next night, a window of three nights that misses a zone, a window of six that
 *  misses a (zone, shard) pair, or a pair visited more often than the others. Empty when it is sound. */
function problemsWith(rotation: Rotation, nights: number[]): string[] {
  const parts = nights.map(rotation);
  const out: string[] = [];
  for (let i = 0; i + 1 < parts.length; i++) {
    if (parts[i].zone === parts[i + 1].zone) { out.push(`night ${i} and ${i + 1} drive the same zone (${parts[i].zone})`); break; }
  }
  for (let i = 0; i + 3 <= parts.length; i++) {
    if (new Set(parts.slice(i, i + 3).map((p) => p.zone)).size !== ZONES.length) { out.push(`nights ${i}-${i + 2} miss a zone`); break; }
  }
  for (let i = 0; i + 6 <= parts.length; i++) {
    if (new Set(parts.slice(i, i + 6).map((p) => `${p.zone}#${p.shard}`)).size !== ZONES.length * SHARDS) { out.push(`nights ${i}-${i + 5} miss a (zone, shard) pair`); break; }
  }
  const seen: Record<string, number> = {};
  for (const p of parts) seen[`${p.zone}#${p.shard}`] = (seen[`${p.zone}#${p.shard}`] ?? 0) + 1;
  const counts = Object.values(seen);
  if (Math.max(...counts) - Math.min(...counts) > 1) out.push(`a pair is visited more often than another (${JSON.stringify(seen)})`);
  return out;
}

/** Consecutive nights, each started at the given hour of the Indian day, for the given number of days from the given Indian date. */
function nightsFrom(year: number, month: number, day: number, count: number, istHour = 5.75): number[] {
  const first = Date.UTC(year, month - 1, day) - IST + istHour * 3_600_000;
  return Array.from({ length: count }, (_, i) => first + i * DAY);
}

const real: Rotation = (t) => partOfTheNight(t);
// Three plausible rotations that are wrong, each of which a window inside one month or one year does not show.
const byDayOfMonth: Rotation = (t) => {
  const d = new Date(t + IST);
  return { zone: ZONES[(d.getUTCDate() - 1) % 3], shard: Math.floor((d.getUTCDate() - 1) / 3) % SHARDS };
};
const byDayOfYear: Rotation = (t) => {
  const d = new Date(t + IST);
  const doy = Math.floor((Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()) - Date.UTC(d.getUTCFullYear(), 0, 0)) / DAY);
  return { zone: ZONES[doy % 3], shard: Math.floor(doy / 3) % SHARDS };
};
const byUtcDay: Rotation = (t) => {
  const day = Math.floor(t / DAY);
  return { zone: ZONES[day % 3], shard: Math.floor(day / 3) % SHARDS };
};

/** The most nights in a row any one zone goes undriven. A rotation of three zones leaves a zone out for two nights at most. */
function longestAbsence(zones: string[]): number {
  let longest = 0;
  for (const z of ZONES) {
    let run = 0;
    for (const x of zones) { run = x === z ? 0 : run + 1; longest = Math.max(longest, run); }
  }
  return longest;
}

test("the rotation visits every zone and every (zone, shard) pair in turn, over three years and across month ends, year ends and 29 February 2028", () => {
  const nights = nightsFrom(2026, 11, 6, 3 * 366);
  assert.deepEqual(problemsWith(real, nights), [], "the rotation is not sound over three years");
  const covered = nights.map((t) => new Date(t + IST).toISOString().slice(0, 10));
  for (const edge of ["2026-12-31", "2027-01-01", "2027-02-28", "2027-03-01", "2028-02-29", "2028-03-01"]) {
    assert.ok(covered.includes(edge), `the window does not cross ${edge}`);
  }
});

test("a rotation keyed on the day of the month or the day of the year fails the same rule, so the rule is strong enough to catch the mistake", () => {
  const nights = nightsFrom(2026, 11, 6, 3 * 366);
  assert.notDeepEqual(problemsWith(byDayOfMonth, nights), [], "the rule passes a rotation by the day of the month");
  assert.notDeepEqual(problemsWith(byDayOfYear, nights), [], "the rule passes a rotation by the day of the year");
  // ...and a window inside one month does not show it, which is why the window above is three years.
  assert.deepEqual(problemsWith(byDayOfMonth, nightsFrom(2026, 11, 6, 20)), [], "the short window already showed it: the strength comes from the long one");
});

test("the real start instants of the last eight nights drive eight consecutive Indian days, and the same instants keyed on the UTC day do not", () => {
  const days = realStarts.map(indianDayNumber);
  assert.deepEqual(days.map((d, i) => d - days[0] - i), Array(8).fill(0), "the eight scheduled runs are not eight consecutive Indian days");
  const parts = realStarts.map(partOfTheNight);
  for (let i = 0; i + 1 < parts.length; i++) assert.notEqual(parts[i].zone, parts[i + 1].zone, `night ${i} and ${i + 1} drive the same zone`);
  for (let i = 0; i + 3 <= parts.length; i++) assert.equal(new Set(parts.slice(i, i + 3).map((p) => p.zone)).size, 3, `nights ${i}-${i + 2} miss a zone`);
  assert.ok(longestAbsence(parts.map((p) => p.zone)) <= 2, "a zone went undriven for more than two nights running on the Indian day");
  // The mistake this replaced: the same instants, read as UTC days, repeat a zone and leave another undriven for five nights.
  const utcZones = realStarts.map((t) => byUtcDay(t).zone);
  assert.ok(utcZones.some((z, i) => i > 0 && z === utcZones[i - 1]), `the UTC day happens to be fine on these eight, so they no longer show why the Indian day is used: ${utcZones.join(", ")}`);
  assert.ok(longestAbsence(utcZones) > 2, `the UTC day leaves no zone undriven for more than two nights on these eight, so they no longer show why the Indian day is used: ${utcZones.join(", ")}`);
});

test("every instant from 02:00 to 12:00 IST of a night is the same part of the drive: a late start does not change what is driven", () => {
  const first = Date.UTC(2026, 10, 7) - IST;
  for (let h = 2; h <= 12; h += 0.25) {
    for (let d = 0; d < 6; d++) {
      const at = partOfTheNight(first + d * DAY + h * 3_600_000);
      const base = partOfTheNight(first + d * DAY + 2 * 3_600_000);
      assert.deepEqual(at, base, `a start at ${h} h IST drives another part from one at 02:00 on day ${d}`);
    }
  }
  assert.equal(zoneOfTheDay(first + 5 * 3_600_000), partOfTheNight(first + 5 * 3_600_000).zone);
});

// ── the flags ──────────────────────────────────────────────────────────────────────────────────────────

const NIGHT = Date.UTC(2026, 10, 7, 0, 30);   // 06:00 IST on 7 November 2026

test("a zone is `all`, `rotate` or one of the matrix's, and anything else is refused", () => {
  assert.equal(resolveZone("all", NIGHT), "all");
  assert.equal(resolveZone("rotate", NIGHT), partOfTheNight(NIGHT).zone);
  for (const c of TZ_MATRIX) assert.equal(resolveZone(c.timezoneId, NIGHT), c.timezoneId);
  for (const bad of ["", "kolkata", "Asia/Calcutta", "Europe/London", "ALL", "rotating"]) {
    assert.throws(() => resolveZone(bad, NIGHT), /not a zone of the matrix/, `${JSON.stringify(bad)} was accepted as a zone`);
  }
});

test("a shard is `all`, `rotate` or a number below the count, a rotating zone rotates the part too, and an empty value is not 'no flag'", () => {
  assert.equal(resolveShard("all", "rotate", NIGHT), "all");
  assert.equal(resolveShard("rotate", "all", NIGHT), partOfTheNight(NIGHT).shard);
  assert.equal(resolveShard(undefined, "rotate", NIGHT), partOfTheNight(NIGHT).shard, "--zone rotate must rotate the part as well");
  assert.equal(resolveShard(undefined, "Asia/Kolkata", NIGHT), "all", "a named zone drives the whole date group");
  assert.equal(resolveShard(undefined, "all", NIGHT), "all");
  for (let k = 0; k < SHARDS; k++) assert.equal(resolveShard(String(k), "all", NIGHT), k);
  for (const bad of ["", "2", "-1", "1.5", "x", "ALL"]) assert.throws(() => resolveShard(bad, "all", NIGHT), /not a part of the date group/, `${JSON.stringify(bad)} was accepted as a shard`);
});

type Flags = Record<string, string | true>;
const parse = (...argv: string[]) => parseArgs(argv) as { flags: Flags; problem: string | null };

test("the runner's arguments: both spellings are read, and nothing it cannot use is ignored", () => {
  assert.deepEqual(parse("--zone", "rotate", "--stop-after=24", "--list", "--only", "dates/a", "--shots").flags,
    { "--zone": "rotate", "--stop-after": "24", "--list": true, "--only": "dates/a", "--shots": true });
  assert.equal(parse("--zone=rotate").flags["--zone"], "rotate");
  assert.equal(parse().problem, null);
  const refused: Array<[string[], RegExp]> = [
    [["--zones", "rotate"], /not a flag of this runner/],
    [["--zone=rotate", "--wat"], /not a flag of this runner/],
    [["--shots=1"], /--shots takes no value/],
    [["--no-headers=1"], /--no-headers takes no value/],
    [["--no-tz-matrix=true"], /--no-tz-matrix takes no value/],
    [["--list=yes"], /--list takes no value/],
    [["--shard="], /--shard needs/],
    [["--shard"], /--shard needs/],
    [["--zone", "--report", "x"], /--zone needs/],
    [["--stop-after"], /--stop-after needs/],
    [["--now="], /--now needs/],
    [["--zone", "all", "--zone", "rotate"], /--zone is given twice/],
    [["--list", "--list"], /--list is given twice/],
    [["dates"], /takes flags only/],
  ];
  for (const [argv, re] of refused) assert.match(parse(...argv).problem ?? "", re, `${argv.join(" ")} was not refused as ${re}`);
  // The two flags that existed before keep the words they always had.
  assert.equal(parse("--only").problem, "--only needs a group or scenario id, e.g. --only dates");
  assert.equal(parse("--report").problem, "--report needs a file path, e.g. --report .smoke/drive-report.json");
  // Every flag the runner knows has its own line in the runner's header (a mention in passing is not documentation).
  const header = RUNNER.slice(0, RUNNER.indexOf("import fs"));
  for (const flag of Object.keys(FLAGS)) assert.match(header, new RegExp(`^ \\* ${flag}\\b`, "m"), `the runner's header does not document ${flag} on a line of its own`);
});

test("a deadline is a number of minutes, an instant carries its zone, and the deadline passes at the minute and not before", () => {
  assert.equal(resolveStopAfter(undefined), null);
  assert.equal(resolveStopAfter("24"), 24);
  assert.equal(resolveStopAfter("0.5"), 0.5);
  assert.equal(resolveStopAfter(String(MAX_STOP_AFTER_MINUTES)), MAX_STOP_AFTER_MINUTES);
  for (const bad of ["", "0", "-1", "abc", "1e3", "24 ", String(MAX_STOP_AFTER_MINUTES + 1), "0x10"]) {
    assert.throws(() => resolveStopAfter(bad), /not a number of minutes/, `${JSON.stringify(bad)} was accepted as a deadline`);
  }
  assert.equal(resolveNow(undefined, 123), 123);
  assert.equal(resolveNow("2026-11-07T00:30:00Z", 0), Date.UTC(2026, 10, 7, 0, 30));
  assert.equal(resolveNow("2026-11-07T06:00:00+05:30", 0), Date.UTC(2026, 10, 7, 0, 30));
  for (const bad of ["", "2026-11-07", "2026-11-07T00:30:00", "yesterday", "2026-13-40T00:30:00Z"]) {
    assert.throws(() => resolveNow(bad, 0), /not an instant with its zone/, `${JSON.stringify(bad)} was accepted as an instant`);
  }
  assert.equal(deadlinePassed(1000, 1000 + 24 * 60_000 - 1, 24), false);
  assert.equal(deadlinePassed(1000, 1000 + 24 * 60_000, 24), true);
  assert.equal(deadlinePassed(1000, 1000 + 10 ** 9, null), false, "no deadline never passes");
});

// ── the runner, spawned: what it lists is what the rule says ──────────────────────────────────────────────

type Scenario = { id: string; contexts?: Array<{ locale: string; timezoneId: string }> };
type Sc = Scenario & { group: string };
async function everyScenario(): Promise<Sc[]> {
  const out: Sc[] = [];
  for (const file of readdirSync(SCENARIO_DIR).filter((f) => f.endsWith(".mjs")).sort()) {
    const mod = await import(pathToFileURL(join(SCENARIO_DIR, file)).href);
    for (const s of mod.scenarios as Scenario[]) out.push({ ...s, group: mod.group });
  }
  return out;
}
/** The runs the rule asks for under a zone and a shard, in the runner's order and spelling. */
function expectedIds(scenarios: Sc[], zone: string, shard: number | "all", noTzMatrix = false): string[] {
  const out: string[] = [];
  for (const s of scenarios) {
    if (!inShard(s.group, s.id, shard)) continue;
    if (!s.contexts) { out.push(`${s.group}/${s.id}`); continue; }
    const cs = contextsFor(s.contexts, zone);
    for (const c of noTzMatrix ? cs.slice(0, 1) : cs) out.push(`${s.group}/${s.id} [${c.locale} ${c.timezoneId}]`);
  }
  return out;
}
function list(...argv: string[]) {
  const r = spawnSync("node", [RUNNER_PATH, "--list", ...argv], { encoding: "utf8" });
  const lines = r.stdout.split("\n").filter(Boolean);
  const count = Number(/^(\d+) run\(s\) selected\.$/.exec(lines[lines.length - 1] ?? "")?.[1] ?? NaN);
  return { status: r.status, stderr: r.stderr, header: lines[0] ?? "", ids: lines.slice(1, -1), count };
}

test("the runner lists, without a build, the runs the rule asks for: the whole drive, a zone, a part, and a night", async () => {
  const scenarios = await everyScenario();
  const whole = list("--zone", "all");
  assert.equal(whole.status, 0, whole.stderr);
  assert.deepEqual(whole.ids, expectedIds(scenarios, "all", "all"), "the whole drive is not the runs the scenarios ask for");
  assert.equal(whole.count, whole.ids.length);
  for (const zone of ZONES) {
    const one = list(`--zone=${zone}`);
    assert.deepEqual(one.ids, expectedIds(scenarios, zone, "all"), `--zone ${zone} does not list the runs of that zone`);
    assert.ok(one.ids.length < whole.ids.length, `--zone ${zone} listed no fewer runs than the whole matrix`);
  }
  for (let k = 0; k < SHARDS; k++) {
    const part = list("--zone", "all", "--shard", String(k));
    assert.deepEqual(part.ids, expectedIds(scenarios, "all", k), `--shard ${k} does not list that part`);
  }
  // a night, at fixed instants: the six nights from 7 November 2026
  for (let i = 0; i < 6; i++) {
    const at = new Date(NIGHT + i * DAY).toISOString().replace(".000Z", "Z");
    const part = partOfTheNight(NIGHT + i * DAY);
    const night = list("--zone", "rotate", "--now", at);
    assert.equal(night.status, 0, night.stderr);
    assert.deepEqual(night.ids, expectedIds(scenarios, part.zone, part.shard), `the night at ${at} does not list ${part.zone}, part ${part.shard + 1}`);
    assert.match(night.header, new RegExp(`${part.zone} only, part ${part.shard + 1} of ${SHARDS} \\(the Indian day ${part.day}, by --zone rotate, read at ${at}\\)`), `the header does not name the part of ${at}`);
  }
  // --no-tz-matrix and --only still narrow what is listed
  assert.deepEqual(list("--zone", "all", "--no-tz-matrix").ids, expectedIds(scenarios, "all", "all", true));
  const only = list("--zone", "all", "--only", "dates/itc04");
  assert.deepEqual(only.ids, expectedIds(scenarios, "all", "all").filter((id) => id.startsWith("dates/itc04")));
  assert.equal(list("--only", "no-such-scenario").status, 2, "an --only that matches nothing must be refused, not listed as empty");
});

test("the list reaches a reader that is slow to take it: the exit waits for the write (a thousand lines were once 218 short through a pipe)", { skip: process.platform === "win32" }, () => {
  // `process.exit` straight after a large `console.log` to a pipe drops what the pipe has not yet taken, and a reader inside this process (a paused stream) cannot show it, because Node buffers the
  // pipe for it. A reader that does not read at all for a moment can: the shell holds the runner's output in the pipe while `sleep` runs, then `cat` reads what is left.
  const r = spawnSync("sh", ["-c", 'node "$0" --list --zone all | (sleep 0.4; cat)', RUNNER_PATH], { encoding: "utf8", maxBuffer: 16 * 1024 * 1024 });
  const lines = r.stdout.split("\n").filter(Boolean);
  const last = lines[lines.length - 1] ?? "";
  assert.match(last, /^\d+ run\(s\) selected\.$/, `the list was cut short: ${lines.length} lines, ending at ${JSON.stringify(last)}`);
  assert.equal(lines.length - 2, Number(/^(\d+)/.exec(last)![1]), "the list has not as many runs as it says it has");
});

test("over six nights the runner lists every run of the drive: each date run once, each unzoned date run on the nights of its part, and the other groups every night", async () => {
  const scenarios = await everyScenario();
  const whole = expectedIds(scenarios, "all", "all");
  const nights = Array.from({ length: 6 }, (_, i) => list("--zone", "rotate", "--now", new Date(NIGHT + i * DAY).toISOString().replace(".000Z", "Z")).ids);
  const tally = new Map<string, number>();
  for (const ids of nights) for (const id of ids) tally.set(id, (tally.get(id) ?? 0) + 1);
  assert.deepEqual([...tally.keys()].sort(), [...whole].sort(), "six nights do not list exactly the runs of the whole drive");
  for (const s of scenarios) {
    const ids = s.contexts ? s.contexts.map((c) => `${s.group}/${s.id} [${c.locale} ${c.timezoneId}]`) : [`${s.group}/${s.id}`];
    for (const id of ids) {
      const want = s.group !== "dates" ? 6 : s.contexts ? 1 : 3;
      assert.equal(tally.get(id), want, `${id} is listed ${tally.get(id)} times in six nights, not ${want}`);
    }
  }
});

test("without --now the runner reads the rotation at the real clock, not at a frozen one", () => {
  const before = indianDayNumber(Date.now());
  const r = list("--zone", "rotate");
  const after = indianDayNumber(Date.now());
  const day = Number(/the Indian day (\d+)/.exec(r.header)?.[1] ?? NaN);
  assert.ok(day >= before && day <= after, `the runner read the Indian day ${day} and the clock said ${before}..${after}: ${r.header}`);
});

// ── nothing is dropped by a choice, and the parts add up ────────────────────────────────────────────────

/** The runs a zone and a shard ask for. */
function runsUnder(scenarios: Sc[], zone: string, shard: number | "all"): number {
  return scenarios.reduce((n, s) => (!inShard(s.group, s.id, shard) ? n : n + (s.contexts ? contextsFor(s.contexts, zone).length : 1)), 0);
}
function minutesOf(scenarios: Sc[], zone: string, shard: number | "all"): number {
  const date = scenarios.filter((s) => s.group === "dates");
  const other = scenarios.filter((s) => s.group !== "dates");
  return (runsUnder(date, zone, shard) * SECONDS_PER_DATE_RUN + runsUnder(other, zone, shard) * SECONDS_PER_OTHER_RUN) / 60;
}

test("choosing a zone or a part never removes a scenario from the drive: across the parts every scenario runs under every zone, once", async () => {
  const scenarios = await everyScenario();
  assert.ok(scenarios.length > 200, `only ${scenarios.length} scenarios found: the scan is not reading the drive`);
  assert.equal(contextsFor(TZ_MATRIX, "all"), TZ_MATRIX, "`all` changed the contexts");
  assert.deepEqual(contextsFor(TZ_MATRIX, "Asia/Kolkata"), [{ locale: "en-IN", timezoneId: "Asia/Kolkata" }]);
  const onlyLosAngeles = [{ locale: "en-US", timezoneId: "America/Los_Angeles" }];
  assert.deepEqual(contextsFor(onlyLosAngeles, "Asia/Kolkata"), onlyLosAngeles, "a scenario with no context in the chosen zone must run all of its own");
  // The fallback above is a safety net and no scenario relies on it: a scenario that asks for contexts asks for EVERY zone of the matrix, so a zone choice cuts it to one run and never to none or to a copy.
  for (const s of scenarios.filter((x) => x.contexts)) {
    for (const zone of ZONES) assert.equal(s.contexts!.filter((c) => c.timezoneId === zone).length, 1, `${s.group}/${s.id} has ${s.contexts!.filter((c) => c.timezoneId === zone).length} contexts in ${zone}, not one`);
    assert.equal(s.contexts!.length, ZONES.length, `${s.group}/${s.id} asks for contexts outside the matrix`);
  }
  for (const zone of ZONES) {
    // Each date scenario is in exactly one shard; every other scenario runs in every part.
    for (const s of scenarios) {
      const inWhich = Array.from({ length: SHARDS }, (_, k) => k).filter((k) => inShard(s.group, s.id, k));
      if (s.group === "dates") assert.equal(inWhich.length, 1, `${s.id} is in ${inWhich.length} shards`);
      else assert.equal(inWhich.length, SHARDS, `${s.id} (not a date scenario) must run in every part`);
    }
    // The parts of one zone add up to the zone's whole date group (the other groups run in every part, so they are counted once).
    const date = scenarios.filter((s) => s.group === "dates");
    const sum = Array.from({ length: SHARDS }, (_, k) => runsUnder(date, zone, k)).reduce((a, b) => a + b, 0);
    assert.equal(sum, runsUnder(date, zone, "all"), `the parts of ${zone} do not add up to its date group`);
  }
  // The zones are the same length.
  const perZone = ZONES.map((z) => runsUnder(scenarios, z, "all"));
  assert.equal(new Set(perZone).size, 1, `the zones are not the same length: ${perZone.join(", ")}`);
});

test("a scenario's part is a stable function of its id, so adding or removing a scenario moves no other", () => {
  // FNV-1a over the id, modulo the count, pinned on ids so a change of the hash is a change of every part, on purpose.
  assert.equal(SHARDS, 2, "the count of parts changed: the pins below are for two");
  assert.deepEqual(["shipping-bill", "vendor-no-pe-declaration", "bank-account-opening-date", "a", "scenario-1"].map(shardOf), [1, 0, 1, 0, 1]);
  const ids = Array.from({ length: 200 }, (_, i) => `scenario-${i}`);
  const counts = Array(SHARDS).fill(0);
  for (const id of ids) counts[shardOf(id)] += 1;
  assert.ok(Math.min(...counts) > 60, `the hash cuts 200 ids unevenly: ${counts.join(" / ")}`);
});

// ── the report ─────────────────────────────────────────────────────────────────────────────────────────

test("a report written part-way is never ok, names what was not driven, and says when the deadline stopped the run", () => {
  const selected = ["a", "b", "c"].map((id) => ({ id }));
  const build = reportOf as unknown as (input: Record<string, unknown>) => Record<string, any>;
  const base = { only: null, tzMatrix: true, zone: "Asia/Kolkata", shard: 1, stopAfter: 24, chosenAtMs: Date.UTC(2026, 10, 7), csp: "REPORT-ONLY", pinnedClock: "2026-10-08T08:00:00Z", selected, escaped: [], startedMs: 0, nowMs: 5000 };
  const driven = (ids: string[], ok = true) => ids.map((id) => ({ id, ok, error: ok ? null : "boom", problems: [] }));
  const partial = build({ ...base, complete: false, results: driven(["a"]) });
  assert.equal(partial.ok, false, "a report written part-way says ok");
  assert.equal(partial.complete, false);
  assert.deepEqual(partial.not_driven, ["b", "c"]);
  assert.equal(partial.scenarios_selected, 3);
  assert.equal(partial.scenarios_driven, 1);
  assert.equal(partial.stopped_at_deadline, false);
  const stopped = build({ ...base, complete: false, stoppedAtDeadline: true, results: driven(["a", "b"]) });
  assert.equal(stopped.stopped_at_deadline, true);
  assert.equal(stopped.ok, false);
  assert.deepEqual(stopped.not_driven, ["c"]);
  const whole = build({ ...base, complete: true, results: driven(["a", "b", "c"]) });
  assert.equal(whole.ok, true);
  assert.deepEqual(whole.not_driven, []);
  assert.equal(build({ ...base, complete: true, results: driven(["a", "b", "c"], false) }).ok, false, "a failed scenario leaves a complete report ok");
  assert.equal(build({ ...base, complete: true, escaped: ["example.com"], results: driven(["a", "b", "c"]) }).ok, false, "a blocked host leaves a complete report ok");
  assert.deepEqual(whole.mode, { only: null, tz_matrix: true, zone: "Asia/Kolkata", shard: 1, stop_after_minutes: 24, chosen_at: "2026-11-07T00:00:00.000Z" }, "the report does not name what was driven, how long it was given and when the part was chosen");
});

test("the runner stops itself at its deadline, and what it leaves is a final report and a red exit", () => {
  // The browser is not here, so the loop is read as text: the deadline is asked BEFORE a scenario is started (and before its context is made), the stop is remembered, the final report
  // is written once more without the 20-second throttle and says it is not complete, and the exit is 1.
  const loopHead = /for \(const run of selected\) \{([\s\S]*?)const t0 = Date\.now\(\);/.exec(RUNNER)?.[1] ?? "";
  assert.match(loopHead, /if \(deadlinePassed\(started, Date\.now\(\), stopAfter\)\) \{ stoppedAtDeadline = true; break; \}/, "no scenario is held back by the deadline");
  assert.match(RUNNER, /function writeReport\(complete, final = false\) \{\s*if \(!reportPath\) return;\s*if \(!final && Date\.now\(\) - reportWrittenAt < 20_000\) return;/, "the final report is throttled like the others");
  assert.match(RUNNER, /writeReport\(!stoppedAtDeadline, true\);/, "the final report does not say it was stopped");
  assert.match(RUNNER, /process\.exit\(failed\.length \|\| escaped\.size \|\| stoppedAtDeadline \? 1 : 0\);/, "a run stopped at its deadline exits 0");
  assert.match(RUNNER, /writeReport\(false\);\s*\}\s*\n\s*await browser\.close\(\);/, "the report is not written after each scenario");
  assert.match(RUNNER, /reportOf\(\{\s*complete, stoppedAtDeadline, only, tzMatrix: !noTzMatrix, zone, shard, stopAfter, chosenAtMs: chosenAt,/,
    "the runner builds its report some other way than the one the test tries, or does not hand it whether the run was complete, whether it was stopped, what it drove and when the part was chosen");
  assert.match(RUNNER, /parseArgs\(process\.argv\.slice\(2\)\)/, "the runner reads its arguments some other way than the one the test tries");
  assert.match(RUNNER, /const SCENARIO_TIMEOUT_MS = 90_000;/, "a scenario in flight is bounded by another time than the arithmetic below assumes");
});

// ── the allowance ──────────────────────────────────────────────────────────────────────────────────────

/** The numbers the workflow gives a night and the whole matrix: the job's allowance and the drive's deadline. */
function workflowNumbers(): { caps: [number, number]; stops: [number, number] } {
  const cap = /timeout-minutes: \$\{\{ \(github\.event_name == 'workflow_dispatch' && inputs\.zones == 'all'\) && (\d+) \|\| (\d+) \}\}/.exec(WORKFLOW);
  const stop = /DRIVE_STOP_AFTER: \$\{\{ \(github\.event_name == 'workflow_dispatch' && inputs\.zones == 'all'\) && (\d+) \|\| (\d+) \}\}/.exec(WORKFLOW);
  assert.ok(cap, "the job's allowance is not 'the matrix's cap if the whole matrix was asked for by name, otherwise the night's'");
  assert.ok(stop, "the drive's deadline is not 'the matrix's if the whole matrix was asked for by name, otherwise the night's'");
  return { caps: [Number(cap![1]), Number(cap![2])], stops: [Number(stop![1]), Number(stop![2])] };
}

test("the allowance is not raised for a night: 45 minutes, and more only for the whole matrix on request", () => {
  const { caps } = workflowNumbers();
  assert.equal(caps[1], NIGHT_CAP_MINUTES, "a night's allowance is no longer 45 minutes");
  assert.equal(caps[0], MATRIX_CAP_MINUTES, "the whole matrix's allowance is not the 120 minutes this test was written for");
  assert.doesNotMatch(WORKFLOW, /timeout-minutes: (?!\$\{\{)(?:[5-9]\d|\d{3,})\b/, "a job in the workflow has been given a longer fixed allowance");
});

test("the deadline leaves the job room to end: the part before the drive, the deadline, a scenario in flight and the steps after all fit the allowance", () => {
  const { caps, stops } = workflowNumbers();
  const inFlight = Number(/const SCENARIO_TIMEOUT_MS = (\d[\d_]*);/.exec(RUNNER)?.[1].replace(/_/g, "") ?? NaN) / 60_000;
  assert.ok(inFlight > 0 && inFlight < 5, `a scenario in flight is read as ${inFlight} minutes`);
  for (const [name, cap, stop] of [["a night", caps[1], stops[1]], ["the whole matrix", caps[0], stops[0]]] as const) {
    const total = WORST_SETUP_MINUTES + stop + inFlight + FINISH_MINUTES;
    assert.ok(total <= cap, `${name}: ${WORST_SETUP_MINUTES} minutes before the drive + a deadline of ${stop} + ${inFlight} for a scenario in flight + ${FINISH_MINUTES} after is ${total}, over the ${cap}-minute allowance: the job would be cancelled and its report never uploaded`);
  }
  assert.ok(stops[1] < stops[0], "a night's deadline is not shorter than the whole matrix's");
});

test("the estimated drive of the worst night fits what its deadline leaves, and so does the whole matrix", async () => {
  const scenarios = await everyScenario();
  const { stops } = workflowNumbers();
  let night = 0;
  for (const zone of ZONES) for (let k = 0; k < SHARDS; k++) night = Math.max(night, minutesOf(scenarios, zone, k));
  const matrix = minutesOf(scenarios, "all", "all");
  const budgetNight = stops[1] - MARGIN_MINUTES;
  const budgetMatrix = stops[0] - MARGIN_MINUTES;
  assert.ok(night <= budgetNight,
    `A NIGHT'S DRIVE IS NOW ESTIMATED AT ${night.toFixed(1)} MINUTES, over the ${budgetNight} that its ${stops[1]}-minute deadline leaves after a margin of ${MARGIN_MINUTES}: a night would be stopped at its deadline with scenarios undriven. `
    + "Cut the drive further (raise SHARDS in scripts/drive/kit.mjs: every scenario is then visited less often) or ask the owner for a longer allowance, which spends their GitHub Actions minutes and is theirs to decide. Do not delete a scenario to fit.");
  assert.ok(matrix <= budgetMatrix,
    `the whole matrix is estimated at ${matrix.toFixed(1)} minutes of drive, over the ${budgetMatrix} its ${stops[0]}-minute deadline leaves after a margin of ${MARGIN_MINUTES}: a run asked for by name would be stopped at its deadline`);
});

// ── the workflow ───────────────────────────────────────────────────────────────────────────────────────

test("the workflow asks the drive for the night's part with a deadline, lets a person name the night's part or everything, and defaults to the cheap choice", () => {
  const drive = /- name: Drive the money editors[\s\S]*?(?=\n      - name:|\n      - uses:|$)/.exec(WORKFLOW)?.[0] ?? "";
  assert.ok(drive, "the workflow no longer has the drive step");
  assert.match(drive, /run: node scripts\/driveMoneyEditors\.mjs --zone "\$DRIVE_ZONES" --stop-after "\$DRIVE_STOP_AFTER" --report \.smoke\/drive-report\.json/, "the drive step does not pass the zone choice and the deadline to the drive");
  assert.match(drive, /DRIVE_ZONES: \$\{\{ \(github\.event_name == 'workflow_dispatch' && inputs\.zones\) \|\| 'rotate' \}\}/, "a night, or a labelled pull request, is not given `rotate`");
  const options = /inputs:\s+zones:[\s\S]*?options: \[([^\]]*)\]\s+default: "([^"]*)"/.exec(WORKFLOW);
  assert.ok(options, "the workflow offers no choice of zones");
  const offered = options![1].split(",").map((x) => x.trim().replace(/^"|"$/g, ""));
  assert.deepEqual([...offered].sort(), ["all", "rotate"], "the on-demand choice is not the night's part or everything: a single zone cannot fit the 45-minute allowance (about 31 minutes of drive after the longest setup seen)");
  assert.equal(options![2], "rotate", "the default of the on-demand choice is not the cheap one (a person must ask for `all` by name)");
});

test("a run is cancelled by another only for a pull request: a nightly and an on-demand run are never cancelled by one another", () => {
  assert.match(WORKFLOW, /concurrency:\s+group: smoke-walk-\$\{\{ github\.ref \}\}[\s\S]*?cancel-in-progress: \$\{\{ github\.event_name == 'pull_request' \}\}/,
    "cancel-in-progress is not limited to a pull request: a nightly arriving hours after its schedule would cancel an on-demand run of the whole matrix (up to 95 minutes of the owner's Actions time)");
});

test("the workflow runs once a day, because the rotation is by the day", () => {
  const crons = [...WORKFLOW.matchAll(/- cron: "([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(crons, ["30 20 * * *"], "the schedule changed: a second run in a day would drive the same part twice and the rotation would drift");
});

test("the report is kept by a step that runs whatever happened to the drive, and it follows the drive step", () => {
  const drive = WORKFLOW.indexOf("- name: Drive the money editors");
  const keep = WORKFLOW.indexOf("- name: Keep the money-editor drive report");
  assert.ok(drive > 0 && keep > drive, "the step that keeps the drive's report does not follow the drive");
  const block = WORKFLOW.slice(keep, WORKFLOW.indexOf("\n      - name:", keep + 10));
  assert.match(block, /if: always\(\)/, "the drive's report is kept only when the drive passed");
  assert.match(block, /path: apps\/web\/\.smoke\/drive-report\.json/);
});
