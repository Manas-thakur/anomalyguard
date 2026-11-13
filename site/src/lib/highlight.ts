// A tiny highlighter for the landing page's two code samples (shell and YAML).
// The output uses the same classes (and colour tokens) as the hero terminal.

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** Split a line into code and a trailing `# comment` that is not inside quotes. */
function splitComment(line: string): [string, string] {
	let quote: string | null = null;
	for (let i = 0; i < line.length; i++) {
		const ch = line[i];
		if (quote) {
			if (ch === quote) quote = null;
		} else if (ch === '"' || ch === "'") {
			quote = ch;
		} else if (ch === '#' && (i === 0 || /\s/.test(line[i - 1]))) {
			return [line.slice(0, i), line.slice(i)];
		}
	}
	return [line, ''];
}

const strings = (s: string) => esc(s).replace(/(&quot;|")([^"]*)("|&quot;)/g, '<span class="s">"$2"</span>');

export function highlightShell(code: string): string {
	return code
		.split('\n')
		.map((line) => {
			const [body, comment] = splitComment(line);
			let html = '';
			const m = /^(\s*)(\S+)(.*)$/.exec(body);
			if (m) {
				html = `${m[1]}<span class="c">${esc(m[2])}</span>${strings(m[3]).replace(/(\s)(--?[a-z][\w-]*)/g, '$1<span class="k">$2</span>')}`;
			} else {
				html = esc(body);
			}
			return html + (comment ? `<span class="m">${esc(comment)}</span>` : '');
		})
		.join('\n');
}

export function highlightYaml(code: string): string {
	return code
		.split('\n')
		.map((line) => {
			const [body, comment] = splitComment(line);
			const m = /^(\s*(?:-\s+)?)([\w.-]+)(:)(.*)$/.exec(body);
			let html: string;
			if (m) {
				html = `${esc(m[1])}<span class="k">${esc(m[2])}</span><span class="m">${m[3]}</span>${strings(m[4])}`;
			} else {
				html = strings(body);
			}
			return html + (comment ? `<span class="m">${esc(comment)}</span>` : '');
		})
		.join('\n');
}
