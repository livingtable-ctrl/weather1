import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

// Source scans, not render tests: this repo has no component-render harness
// (frontend/ runs vitest over pure helpers only). What these guard is a
// specific, silent, high-consequence regression that no other test can see.
//
// handleRunCron's first parameter is `samedayOnly`. React passes the click
// SyntheticEvent as the first argument to an onClick handler, and an event
// object is truthy -- so `onClick={handleRunCron}` makes EVERY "Run scan"
// click a same-day scan. The scan still runs, the log still streams, the
// toast still says it completed. Nothing fails; the operator just silently
// stops getting multi-day scans, and `last_full_scan` stops advancing until
// the 48h staleness alarm eventually fires for an unrelated-looking reason.
const here = dirname(fileURLToPath(import.meta.url));
const settingsSrc = readFileSync(join(here, 'tabs', 'SettingsTab.jsx'), 'utf8');
const appSrc = readFileSync(join(here, 'App.jsx'), 'utf8');

// A SOURCE-SCAN SUITE CANNOT SEE A SYNTAX ERROR. These files are read as
// strings here and imported by nothing else in the suite, so App.jsx once sat
// syntactically broken (an unbalanced paren in a .catch) while all 338 tests
// passed and only `npm run build` caught it. esbuild is already present via
// vite; transforming each file is a real parse and costs milliseconds.
describe('the files these guards scan actually parse', () => {
  it.each(['App.jsx', 'tabs/SettingsTab.jsx'])('%s is valid JSX', async (rel) => {
    const { transform } = await import('esbuild');
    const code = readFileSync(join(here, rel), 'utf8');
    await expect(transform(code, { loader: 'jsx', sourcefile: rel })).resolves.toBeTruthy();
  });
});

describe('cron scan buttons pass an explicit mode', () => {
  it('never passes handleRunCron bare to onClick', () => {
    // The regression itself.
    expect(settingsSrc).not.toMatch(/onClick=\{\s*handleRunCron\s*\}/);
  });

  it('binds each mode to the button that claims it', () => {
    // Asserting only that both call shapes exist SOMEWHERE in the file is
    // vacuous: swapping true/false between the two buttons passes it. That
    // swap is the regression itself -- "Run scan" would silently run a
    // same-day scan. So resolve each <button> node by its visible label and
    // assert the argument inside THAT node.
    const buttons = settingsSrc.match(/<button[\s\S]*?<\/button>/g) || [];
    // Match the label TEXT, not a quoted literal: b.includes("'Run scan'")
    // makes a prettier/eslint quote-style change fail the positive control
    // rather than the assertion, which reads as a real regression for a
    // purely cosmetic edit. The two labels are unambiguous on their own.
    const full = buttons.find(b => /['">][^'"<]*Run scan/.test(b));
    const sameday = buttons.find(b => /['">][^'"<]*Same-day scan/.test(b));
    // These two also serve as the positive control for the negative above:
    // deleting the buttons makes them undefined and fails here.
    expect(full, 'no button renders "Run scan"').toBeDefined();
    expect(sameday, 'no button renders "Same-day scan"').toBeDefined();
    expect(full).toMatch(/handleRunCron\(false\)/);
    expect(full).not.toMatch(/handleRunCron\(true\)/);
    expect(sameday).toMatch(/handleRunCron\(true\)/);
    expect(sameday).not.toMatch(/handleRunCron\(false\)/);
  });

  it('sends the flag to the API as a real boolean', () => {
    // The server accepts only a JSON `true` (`is True`, not bool()), so a
    // client that stringified this would silently get full scans forever.
    expect(appSrc).toMatch(/sameday_only:\s*samedayOnly/);
    expect(appSrc).toMatch(/handleRunCron\s*=\s*useCallback\(\(samedayOnly\s*=\s*false\)/);
  });

  it('tracks the in-flight mode in a ref, not by reading it out of a setState updater', () => {
    // Reading prev state inside an updater to drive a side effect relied on
    // React's eager-state optimization, which only applies when the fiber has
    // no pending update -- the completion toast was intermittently mislabelled.
    expect(appSrc).toMatch(/samedayRef\s*=\s*useRef\(false\)/);
    expect(appSrc).toMatch(/samedayRef\.current\s*=\s*samedayOnly/);
    expect(appSrc).not.toMatch(/sameday\s*=\s*!!prev\.samedayOnly/);
  });
});
