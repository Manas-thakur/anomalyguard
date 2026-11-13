import { existsSync, openSync, readSync, closeSync } from 'node:fs';
import { join } from 'node:path';

const BASE = import.meta.env.BASE_URL.replace(/\/$/, '');

export interface ShotInfo {
	src: string;
	exists: boolean;
	width: number;
	height: number;
}

/**
 * Screenshots are copied from ../docs/screenshots into public/screenshots by
 * scripts/sync-assets.mjs before every build. Some may not exist yet, so the
 * page checks at build time and reads the real PNG size (no layout shift).
 */
export function shot(name: string, fallback: [number, number] = [1440, 900]): ShotInfo {
	const file = join(process.cwd(), 'public', 'screenshots', name);
	const src = `${BASE}/screenshots/${name}`;
	if (!existsSync(file)) return { src, exists: false, width: fallback[0], height: fallback[1] };
	const buf = Buffer.alloc(24);
	const fd = openSync(file, 'r');
	try {
		readSync(fd, buf, 0, 24, 0);
	} finally {
		closeSync(fd);
	}
	const isPng = buf.readUInt32BE(0) === 0x89504e47;
	return {
		src,
		exists: true,
		width: isPng ? buf.readUInt32BE(16) : fallback[0],
		height: isPng ? buf.readUInt32BE(20) : fallback[1],
	};
}

/** Prefix an internal path with the site base. */
export function href(path: string): string {
	return `${BASE}/${path.replace(/^\//, '')}`;
}
