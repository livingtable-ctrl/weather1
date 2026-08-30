#!/usr/bin/env node
/**
 * Verify that a handoff prompt's factual claims are still true.
 *
 *   node audit/reproductions/verify_handoff_prompt.mjs [path/to/prompt.md] [check]
 *
 * Defaults to audit/handoff_prompts/option5-forward-validation-2026-08-29.md
 * and the "all" check. Exits non-zero and names every claim that no longer
 * holds; prints "PROMPT-CHECK <NAME> PASSED" only when every one does.
 *
 * WHY THIS EXISTS. A handoff prompt is a set of assertions about a repo and a
 * live database, written once and pasted later. Re-reading it cannot catch a
 * number that has since moved. Authoring this checker caught two real defects
 * in the prompt it was written for: every slope figure was stale within hours
 * (the population grew 646 -> 670 while the prompt was being written), and the
 * claim "no individual cell is significant alone" was false -- two cells clear
 * |z| >= 1.96 and one survives Bonferroni. The second was also wrong in
 * docs/calibration-and-edge-research-2026-08-29.md and was fixed there.
 *
 * HOW IT AVOIDS SELF-CERTIFYING. Every numeric claim is PARSED OUT OF the
 * prompt and compared against a value measured independently -- the slopes are
 * re-fitted from analysis_attempts here, not read from any document. A
 * mis-transcribed number therefore fails instead of proving itself. Claim
 * matching runs against a whitespace-collapsed copy of the prompt, because a
 * regex coupled to hard-wrapped line breaks fails on rewrapping, and the
 * tempting fix for that is to weaken the assertion rather than the parser.
 *
 * EXEMPTION FROM audit/reproductions/README.md's isolate() RULE, stated rather
 * than taken silently: that rule exists because a Python script importing repo
 * modules binds to the real data/ and can write to it. This script is Node, it
 * imports no repo code, and it opens the database with the sqlite readOnly
 * flag, so there is no write path to sandbox. It resolves the main clone via
 * `git rev-parse --git-common-dir` rather than __dirname, because in a worktree
 * the code lives under .claude/worktrees/<name>/ while data/ stays in the main
 * clone -- the same hazard paths.py handles for the Python scripts here.
 */
import { readFileSync, existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { DatabaseSync } from "node:sqlite";
import path from "node:path";

const git = (...a) => execFileSync("git", a, { encoding: "utf8" }).trim();
const REPO = git("rev-parse", "--show-toplevel");
// In a worktree, data/ lives in the MAIN clone, which is the parent of the
// common git dir. In a normal clone this resolves to the same place.
const MAIN = path.dirname(git("rev-parse", "--path-format=absolute", "--git-common-dir"));
const DB = path.join(MAIN, "data", "predictions.db");
const DOC = path.join(REPO, "docs", "calibration-and-edge-research-2026-08-29.md");
const DEFAULT_PROMPT = path.join(
  REPO, "audit", "handoff_prompts", "option5-forward-validation-2026-08-29.md");

const promptPath = process.argv[2] && !process.argv[2].startsWith("-")
  ? path.resolve(process.argv[2]) : DEFAULT_PROMPT;
const which = process.argv[3] || (process.argv[2]?.startsWith("-") ? process.argv[2].slice(2) : "all");

for (const [label, f] of [["prompt", promptPath], ["database", DB], ["research doc", DOC]]) {
  if (!existsSync(f)) { console.error(`missing ${label}: ${f}`); process.exit(2); }
}
const PROMPT = readFileSync(promptPath, "utf8").replace(/\s+/g, " ");

const fails = [], notes = [];
const ok = (m) => notes.push("  ok   " + m);
const bad = (m) => { fails.push(m); notes.push("  FAIL " + m); };
const near = (a, b, tol) => Math.abs(a - b) <= tol;
function claim(re, label) {
  const m = PROMPT.match(re);
  if (!m) { bad(`prompt does not contain a parseable claim for ${label}`); return null; }
  return m;
}

function rows() {
  const db = new DatabaseSync(DB, { readOnly: true });
  const r = db.prepare(
    `SELECT condition, days_out, market_prob, outcome
       FROM analysis_attempts
      WHERE outcome IS NOT NULL AND market_prob IS NOT NULL
        AND forecast_prob IS NOT NULL`).all();
  db.close();
  return r;
}
const ctype = (c) => { const m = /'type':\s*'([a-z_]+)'/.exec(c || ""); return m ? m[1] : "?"; };
const EPS = 1e-6;
const logit = (p) => { const q = Math.min(Math.max(p, EPS), 1 - EPS); return Math.log(q / (1 - q)); };

/** 2-parameter logistic MLE by Newton-Raphson; SE from the observed information. */
function fit(ys, zs) {
  let a = 0, b = 1;
  for (let it = 0; it < 200; it++) {
    let g0 = 0, g1 = 0, h00 = 0, h01 = 0, h11 = 0;
    for (let i = 0; i < ys.length; i++) {
      const eta = Math.max(-30, Math.min(30, a + b * zs[i]));
      const mu = 1 / (1 + Math.exp(-eta)), w = mu * (1 - mu), r = ys[i] - mu;
      g0 += r; g1 += r * zs[i]; h00 += w; h01 += w * zs[i]; h11 += w * zs[i] * zs[i];
    }
    const det = h00 * h11 - h01 * h01;
    if (!isFinite(det) || Math.abs(det) < 1e-12) break;
    const da = (h11 * g0 - h01 * g1) / det, db = (h00 * g1 - h01 * g0) / det;
    a += da; b += db;
    if (Math.abs(da) < 1e-10 && Math.abs(db) < 1e-10) break;
  }
  let h00 = 0, h01 = 0, h11 = 0;
  for (let i = 0; i < ys.length; i++) {
    const eta = Math.max(-30, Math.min(30, a + b * zs[i]));
    const mu = 1 / (1 + Math.exp(-eta)), w = mu * (1 - mu);
    h00 += w; h01 += w * zs[i]; h11 += w * zs[i] * zs[i];
  }
  const det = h00 * h11 - h01 * h01;
  return { a, b, se: Math.sqrt(h00 / det), n: ys.length };
}
const fitOf = (s) => fit(s.map((r) => Number(r.outcome)), s.map((r) => logit(r.market_prob)));

const CHECKS = {
  /** Files, branch, doc sections and backlog titles the prompt tells a reader to open. */
  refs() {
    // The prompt names the ref the work lives on. Verify that ref EXISTS and
    // CONTAINS the research doc -- not that it happens to be checked out. The
    // earlier "== HEAD" form failed the moment the branch merged to master,
    // which is a property of the checkout, not of the prompt being wrong.
    const cb = claim(/committed on ([A-Za-z0-9._\-\/]+)\)?:/, "the ref the work is on");
    if (cb) {
      const ref = cb[1];
      let contains = false;
      try {
        git("-C", REPO, "rev-parse", "--verify", `${ref}^{commit}`);
        contains = git("-C", REPO, "log", "--format=%H", "-1", ref, "--",
          "docs/calibration-and-edge-research-2026-08-29.md").length > 0;
      } catch { bad(`prompt names ref "${ref}"; it does not exist in this repo`); }
      if (contains) ok(`ref ${ref} contains the research doc`);
      else if (git("-C", REPO, "rev-parse", "--verify", "--quiet", `${ref}^{commit}`) !== "")
        bad(`ref "${ref}" exists but does not contain the research doc`);
    }

    for (const f of ["docs/calibration-and-edge-research-2026-08-29.md", "backlog.txt", "cron.py"])
      existsSync(path.join(REPO, f)) ? ok(`exists ${f}`) : bad(`missing ${f}`);

    const doc = readFileSync(DOC, "utf8");
    const secs = [...new Set((PROMPT.match(/§\d/g) || []).map((s) => s.slice(1)))];
    if (!secs.length) bad("prompt cites no doc sections");
    for (const s of secs)
      new RegExp(`^## ${s}\\.`, "m").test(doc) ? ok(`doc has section ${s}`)
        : bad(`prompt cites doc §${s}, no "## ${s}." heading in the doc`);

    const bl = readFileSync(path.join(REPO, "backlog.txt"), "utf8");
    for (const t of ["TWO WAYS OUT OF THE NO-EDGE RESULT", "PROJECT DIRECTION AFTER THE NO-EDGE RESULT"]) {
      if (!PROMPT.includes(t)) { bad(`prompt no longer quotes backlog title "${t}"`); continue; }
      bl.includes(t) ? ok(`backlog has "${t}"`) : bad(`backlog no longer contains "${t}"`);
    }
    readFileSync(path.join(REPO, "cron.py"), "utf8").includes("exit_rule_shadow_log")
      ? ok("cron.py references exit_rule_shadow_log")
      : bad("prompt attributes exit_rule_shadow_log to cron.py; it is not there");
  },

  /** Re-fit every slope the prompt quotes. Nothing here is read from a document. */
  slopes() {
    const all = rows();
    const TEMP = new Set(["above", "below", "between"]);
    const core = all.filter((r) => TEMP.has(ctype(r.condition)));

    const nTot = claim(/(\d{3,}) rows total/, "total row count");
    if (nTot) Number(nTot[1]) === all.length ? ok(`population ${all.length}`)
      : bad(`population: prompt says ${nTot[1]}, measured ${all.length}`);

    for (const [re, sub, label] of [
      [/core\s+temperature.*?b=\+([\d.]+), SE ([\d.]+), z=\+([\d.]+), n=(\d+)/, core, "core"],
      [/same-day \+([\d.]+)\s+\(z=\+([\d.]+), n=(\d+)\)/, core.filter((r) => r.days_out === 0), "same-day"],
      [/multi-day \+([\d.]+)\s+\(z=\+([\d.]+), n=(\d+)\)/, core.filter((r) => r.days_out >= 1), "multi-day"],
    ]) {
      const m = claim(re, `${label} slope`); if (!m) continue;
      const g = m.slice(1).map(Number), hasSE = g.length === 4;
      const [cb, cse, cz, cn] = hasSE ? g : [g[0], null, g[1], g[2]];
      const f = fitOf(sub), z = (f.b - 1) / f.se;
      cn === f.n ? ok(`${label} n=${f.n}`) : bad(`${label} n: prompt ${cn}, measured ${f.n}`);
      near(cb, f.b, 0.002) ? ok(`${label} b=${f.b.toFixed(3)}`)
        : bad(`${label} b: prompt ${cb}, measured ${f.b.toFixed(3)}`);
      near(cz, z, 0.02) ? ok(`${label} z=${z.toFixed(2)}`)
        : bad(`${label} z: prompt ${cz}, measured ${z.toFixed(2)}`);
      if (hasSE) near(cse, f.se, 0.002) ? ok(`${label} SE=${f.se.toFixed(3)}`)
        : bad(`${label} SE: prompt ${cse}, measured ${f.se.toFixed(3)}`);
    }

    const cells = [["core", core],
      ["d0", core.filter((r) => r.days_out === 0)],
      ["d1+", core.filter((r) => r.days_out >= 1)]];
    for (const t of ["above", "below", "between"])
      cells.push([t, core.filter((r) => ctype(r.condition) === t)]);
    for (const t of ["above", "below"]) {
      cells.push([`${t}/d0`, core.filter((r) => ctype(r.condition) === t && r.days_out === 0)]);
      cells.push([`${t}/d1+`, core.filter((r) => ctype(r.condition) === t && r.days_out >= 1)]);
    }
    const WORDS = { nine: 9, ten: 10, eleven: 11, twelve: 12 };
    const cm = claim(/All (\w+) sub-cells sit above 1/, "sub-cell count");
    if (cm) {
      const c = WORDS[cm[1]] ?? Number(cm[1]);
      c === cells.length ? ok(`sub-cell count ${cells.length}`)
        : bad(`sub-cells: prompt says ${cm[1]} (${c}), the table builds ${cells.length}`);
    }
    const below = cells.filter(([, s]) => fitOf(s).b <= 1).map(([l]) => l);
    below.length === 0 ? ok(`all ${cells.length} sub-cells have b>1`)
      : bad(`sub-cells at or below 1: ${below.join(", ")}`);

    // Whatever the prompt asserts about significance must match measurement.
    // An earlier prompt denied any cell was significant; two are.
    const sig = cells.filter(([l, s]) => l !== "core" && (fitOf(s).b - 1) / fitOf(s).se >= 1.96)
      .map(([l]) => l);
    const denies = /no individual cell is significant alone/i.test(PROMPT);
    const admits = /Two cells DO reach conventional significance alone/i.test(PROMPT);
    if (denies && sig.length)
      bad(`prompt denies any cell is significant; these are: ${sig.join(", ")}`);
    else if (admits && sig.length !== 2)
      bad(`prompt says exactly two cells are significant; measured ${sig.length}: ${sig.join(", ")}`);
    else if (!denies && !admits)
      bad("prompt makes no checkable significance statement about the sub-cells");
    else ok(`significance statement matches measurement (${sig.join(", ") || "none"})`);
    if (admits) ["d0", "above"].every((c) => sig.includes(c))
      ? ok("the cells the prompt names are the cells that measure significant")
      : bad(`prompt names same-day/'above'; measurement says ${sig.join(", ")}`);
  },

  /** The prompt's claims about exit_rule_shadow_log's size and shape. */
  shadowlog() {
    const db = new DatabaseSync(DB, { readOnly: true });
    const n = db.prepare("SELECT COUNT(*) c FROM exit_rule_shadow_log").get().c;
    const cols = db.prepare("PRAGMA table_info(exit_rule_shadow_log)").all().map((r) => r.name);
    db.close();
    const cn = claim(/exit_rule_shadow_log \(cron\.py, (\d+) rows\)/, "shadow-log row count");
    if (cn) Number(cn[1]) === n ? ok(`shadow log ${n} rows`)
      : bad(`shadow log: prompt says ${cn[1]} rows, measured ${n}`);
    for (const c of ["entry_price", "cost", "peak_profit_pct"]) {
      if (!PROMPT.includes(c)) { bad(`prompt no longer cites column ${c}`); continue; }
      cols.includes(c) ? ok(`column ${c}`) : bad(`prompt cites column ${c}; not in the table`);
    }
    const pickish = cols.filter((c) => /prob|forecast|pick|side_favou?red/.test(c));
    pickish.length === 0 ? ok("no probability/pick column (positions-shaped, as claimed)")
      : bad(`prompt calls the table positions-shaped; it has pick-like columns: ${pickish}`);
  },

  /**
   * Figures the prompt attributes to the research must match the committed doc,
   * whose appendices hold the verified findings verbatim. This deliberately
   * checks prompt-against-doc rather than against the workflow's temp output,
   * which does not survive the session.
   */
  research() {
    const doc = readFileSync(DOC, "utf8");
    const bl = readFileSync(path.join(REPO, "backlog.txt"), "utf8");
    // Each figure is checked against the source that actually carries it. The
    // original in-sample slope is quoted to 4dp from backlog option I; the doc
    // rounds it to 1.487, so requiring the doc for that one is a false failure.
    for (const [needle, label, src, srcName] of [
      ["2602.19520", "arXiv id", doc, "research doc"],
      ["0.691", "isotonic value at price 0.75", doc, "research doc"],
      ["0.74-0.86", "pick price band", doc, "research doc"],
      ["0.69", "weather slope floor", doc, "research doc"],
      ["0.97", "weather slope ceiling", doc, "research doc"],
      ["1.4871", "original in-sample b", bl, "backlog option I"]]) {
      if (!PROMPT.includes(needle)) { bad(`prompt no longer states ${label} (${needle})`); continue; }
      src.includes(needle) ? ok(`${label} matches ${srcName}`)
        : bad(`prompt states ${label}=${needle}; not found in ${srcName}`);
    }
    // The discovery thresholds must be the ones the backlog records, not invented.
    for (const t of ["0.05", "0.08"])
      PROMPT.includes(t) ? ok(`discovery threshold ${t} cited`)
        : bad(`prompt omits discovery threshold ${t}; a session will invent one`);
    /0\.07\*(?:C\*)?p\*\(1-p\)[^—]*—\s*UNVERIFIED/.test(PROMPT)
      ? ok("fee formula carries its UNVERIFIED marking")
      : bad("prompt no longer marks the fee formula UNVERIFIED; both passes failed to confirm it");
  },
};

const names = which === "all" ? Object.keys(CHECKS) : [which];
for (const n of names) {
  if (!CHECKS[n]) {
    console.error(`unknown check: ${n} (have: ${Object.keys(CHECKS).join(", ")}, all)`);
    process.exit(2);
  }
  notes.push(`[${n}]`);
  try { CHECKS[n](); } catch (e) { bad(`${n} threw: ${e.message}`); }
}
console.log(`prompt: ${path.relative(REPO, promptPath) || promptPath}`);
console.log(notes.join("\n"));
if (fails.length) { console.log(`\n${fails.length} CLAIM(S) FAILED`); process.exit(1); }
console.log(`\nPROMPT-CHECK ${which.toUpperCase()} PASSED`);
