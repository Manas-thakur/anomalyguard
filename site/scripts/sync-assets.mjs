// Runs before `pnpm dev` and `pnpm build`.
//
// 1. Copies the web app screenshots from ../docs/screenshots/*.png into
//    public/screenshots/ (gitignored), so the site always shows the latest ones.
//    Missing files are skipped: pages check for each image at build time.
// 2. Generates the Changelog page from ../CHANGELOG.md into
//    src/content/docs/docs/changelog.md (gitignored), so it never drifts.
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const siteDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repoDir = resolve(siteDir, '..');
const REPO_URL = 'https://github.com/Manas-thakur/anomalyguard';

// ---------------------------------------------------------------- screenshots
const srcShots = join(repoDir, 'docs', 'screenshots');
const outShots = join(siteDir, 'public', 'screenshots');
rmSync(outShots, { recursive: true, force: true });
mkdirSync(outShots, { recursive: true });
let copied = 0;
if (existsSync(srcShots)) {
	for (const name of readdirSync(srcShots)) {
		if (!name.toLowerCase().endsWith('.png')) continue;
		copyFileSync(join(srcShots, name), join(outShots, name));
		copied++;
	}
	console.log(`[sync] copied ${copied} screenshot(s) from docs/screenshots`);
} else {
	console.warn('[sync] docs/screenshots not found; pages will show screenshot placeholders');
}

// ---------------------------------------------------------------- changelog
const changelogSrc = join(repoDir, 'CHANGELOG.md');
const changelogOut = join(siteDir, 'src', 'content', 'docs', 'docs', 'changelog.md');
let body = existsSync(changelogSrc)
	? readFileSync(changelogSrc, 'utf8').replace(/\r\n/g, '\n')
	: 'The changelog is maintained in CHANGELOG.md in the repository.\n';

// Drop the top-level "# Changelog" heading (Starlight renders the title).
body = body.replace(/^\s*#\s+Changelog\s*\n/, '');

// Relative links in CHANGELOG.md point into the repository; make them absolute
// so they work on the site. Leaves http(s), mailto and #anchors alone.
body = body.replace(/\]\((?!https?:|mailto:|#)([^)\s]+)\)/g, (_m, target) => {
	const clean = String(target).replace(/^\.\//, '');
	return `](${REPO_URL}/blob/main/${clean})`;
});
body = body.replace(/^(\[[^\]]+\]:\s*)(?!https?:)(\S+)/gm, (_m, label, target) => {
	return `${label}${REPO_URL}/blob/main/${String(target).replace(/^\.\//, '')}`;
});

const frontmatter = [
	'---',
	'title: Changelog',
	'description: Every notable change to AnomalyGuard, generated from CHANGELOG.md in the repository.',
	'editUrl: ' + `${REPO_URL}/edit/main/CHANGELOG.md`,
	'---',
	'',
	':::note',
	`This page is generated from [CHANGELOG.md](${REPO_URL}/blob/main/CHANGELOG.md) at build time. Release artifacts are on the [GitHub Releases](${REPO_URL}/releases) page.`,
	':::',
	'',
	'',
].join('\n');

mkdirSync(dirname(changelogOut), { recursive: true });
writeFileSync(changelogOut, frontmatter + body.trimStart(), 'utf8');
console.log('[sync] wrote src/content/docs/docs/changelog.md from CHANGELOG.md');
