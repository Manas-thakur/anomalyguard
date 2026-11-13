// Post-build link check over dist/ (runs after `astro build`).
//
// starlight-links-validator already checks links inside the docs content. This
// script checks every built HTML page, including the custom landing page:
//   - every root-relative href/src must live under the site base (/anomalyguard/)
//   - every internal link must resolve to a file in dist/
//   - same-page #anchors must exist on the page
// Screenshots that are not in docs/screenshots yet only produce a warning.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const BASE = '/anomalyguard';
const siteDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dist = join(siteDir, 'dist');

if (!existsSync(dist)) {
	console.error('[links] dist/ not found; run astro build first');
	process.exit(1);
}

function walk(dir) {
	const out = [];
	for (const name of readdirSync(dir)) {
		const p = join(dir, name);
		if (statSync(p).isDirectory()) out.push(...walk(p));
		else if (name.endsWith('.html')) out.push(p);
	}
	return out;
}

function resolvesInDist(pathname) {
	let p = decodeURIComponent(pathname.slice(BASE.length)) || '/';
	if (!p.startsWith('/')) p = '/' + p;
	const target = join(dist, p);
	if (p.endsWith('/')) return existsSync(join(target, 'index.html'));
	return (
		(existsSync(target) && statSync(target).isFile()) ||
		existsSync(join(target, 'index.html')) ||
		existsSync(target + '.html')
	);
}

const attr = /\s(?:href|src)=(?:"([^"]*)"|'([^']*)')/g;
const srcset = /\ssrcset=(?:"([^"]*)"|'([^']*)')/g;
const errors = [];
const warnings = [];
let checked = 0;

const pages = walk(dist);
for (const file of pages) {
	const html = readFileSync(file, 'utf8');
	const page = '/' + relative(dist, file).replace(/\\/g, '/');
	const ids = new Set([...html.matchAll(/\sid=(?:"([^"]+)"|'([^']+)')/g)].map((m) => m[1] ?? m[2]));
	const urls = [...html.matchAll(attr)].map((m) => m[1] ?? m[2]);
	for (const m of html.matchAll(srcset)) {
		for (const part of (m[1] ?? m[2]).split(',')) urls.push(part.trim().split(/\s+/)[0]);
	}
	for (const raw of urls) {
		const url = raw.replace(/&amp;/g, '&');
		if (!url || /^(https?:|mailto:|tel:|data:|javascript:|blob:)/i.test(url) || url.startsWith('//')) continue;
		checked++;
		if (url.startsWith('#')) {
			const id = decodeURIComponent(url.slice(1));
			if (id && !ids.has(id)) errors.push(`${page}: anchor ${url} has no matching id`);
			continue;
		}
		if (!url.startsWith('/')) {
			// relative URL: resolve against the page's folder
			const abs = new URL(url, 'https://x' + BASE + page.replace(/[^/]*$/, '')).pathname;
			if (!resolvesInDist(abs)) errors.push(`${page}: relative link ${url} -> ${abs} does not exist`);
			continue;
		}
		const pathname = url.split(/[?#]/)[0];
		if (pathname !== BASE && !pathname.startsWith(BASE + '/')) {
			errors.push(`${page}: ${url} is not under the site base ${BASE}/`);
			continue;
		}
		if (!resolvesInDist(pathname)) {
			if (pathname.startsWith(BASE + '/screenshots/')) {
				warnings.push(`${page}: ${url} (screenshot not in docs/screenshots yet)`);
			} else {
				errors.push(`${page}: ${url} does not exist in dist/`);
			}
		}
	}
}

for (const w of [...new Set(warnings)]) console.warn('[links] warning: ' + w);
if (errors.length) {
	for (const e of [...new Set(errors)]) console.error('[links] error: ' + e);
	console.error(`[links] ${errors.length} broken link(s) in ${pages.length} pages`);
	process.exit(1);
}
console.log(`[links] ${checked} internal links in ${pages.length} pages: all OK`);
