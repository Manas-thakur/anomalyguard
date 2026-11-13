// @ts-check
import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';
import starlightLinksValidator from 'starlight-links-validator';

const REPO = 'https://github.com/Manas-thakur/anomalyguard';

export default defineConfig({
	site: 'https://manas-thakur.github.io',
	base: '/anomalyguard',
	// /docs/ itself has no page; send it to the first docs page.
	redirects: { '/docs': '/anomalyguard/docs/introduction/' },
	trailingSlash: 'always',
	integrations: [
		starlight({
			title: 'AnomalyGuard',
			description:
				'Open-source data anomaly detection and remediation for Python: validate, detect, fix, alert and monitor, with a local web app.',
			logo: { src: './src/assets/logo.svg', alt: 'AnomalyGuard' },
			favicon: '/favicon.svg',
			social: [{ icon: 'github', label: 'GitHub', href: REPO }],
			editLink: { baseUrl: `${REPO}/edit/main/site/` },
			lastUpdated: false,
			customCss: [
				'@fontsource-variable/inter',
				'@fontsource-variable/jetbrains-mono',
				'@fontsource-variable/space-grotesk',
				'./src/styles/docs.css',
			],
			// The landing page is a custom Astro page, not a docs entry; scripts/check-links.mjs
			// validates links to it (and every other link in dist/) after the build.
			plugins: [starlightLinksValidator({ errorOnInvalidHashes: true, exclude: ['/anomalyguard/'] })],
			sidebar: [
				{
					label: 'Getting started',
					items: [
						{ label: 'Introduction', slug: 'docs/introduction' },
						{ label: 'Installation', slug: 'docs/installation' },
						{ label: 'Quickstart', slug: 'docs/quickstart' },
					],
				},
				{
					label: 'Concepts',
					items: [
						{ label: 'Sources', slug: 'docs/concepts/sources' },
						{ label: 'Schema and quality score', slug: 'docs/concepts/schema-and-quality' },
						{ label: 'Detectors', slug: 'docs/concepts/detectors' },
						{ label: 'Incidents', slug: 'docs/concepts/incidents' },
						{ label: 'Remediation', slug: 'docs/concepts/remediation' },
						{ label: 'Review and feedback loop', slug: 'docs/concepts/review-and-feedback' },
						{ label: 'Alerts', slug: 'docs/concepts/alerts' },
						{ label: 'Pipelines', slug: 'docs/concepts/pipelines' },
					],
				},
				{
					label: 'Guides',
					items: [
						{ label: 'Web app', slug: 'docs/guides/web-app' },
						{ label: 'Alerts and notifiers', slug: 'docs/guides/alerts' },
						{ label: 'LLM-assisted remediation', slug: 'docs/guides/llm-remediation' },
						{ label: 'Deployment', slug: 'docs/guides/deployment' },
						{ label: 'Troubleshooting and FAQ', slug: 'docs/guides/troubleshooting' },
					],
				},
				{
					label: 'Reference',
					items: [
						{ label: 'CLI', slug: 'docs/reference/cli' },
						{ label: 'Pipeline YAML', slug: 'docs/reference/pipeline-yaml' },
						{ label: 'Detectors', slug: 'docs/reference/detectors' },
						{ label: 'HTTP API', slug: 'docs/reference/http-api' },
						{ label: 'Python API', slug: 'docs/reference/python-api' },
						{ label: 'Configuration', slug: 'docs/reference/configuration' },
					],
				},
				{
					label: 'Project',
					items: [
						{ label: 'Benchmarks', slug: 'docs/benchmarks' },
						{ label: 'Changelog', slug: 'docs/changelog' },
						{ label: 'Contributing', slug: 'docs/contributing' },
					],
				},
			],
		}),
	],
});
