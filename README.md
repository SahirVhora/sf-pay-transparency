# SF Pay Transparency Directive Readiness Checker

A static web application that helps employers assess their readiness for compliance with the San Francisco Pay Transparency Directive.

## Overview

This tool provides an interactive checklist and readiness score to help employers understand what's required under the SF Pay Transparency Directive and whether their current practices meet compliance standards.

## Features

- **Interactive readiness assessment** — Answer questions about your pay practices and get an instant compliance score
- **Category-based evaluation** — Organized checks across multiple compliance categories
- **Visual scorecard** — Ring-style score display with color-coded status indicators
- **Actionable feedback** — See exactly which areas need attention before the directive takes effect
- **Countdown timer** — Tracks time remaining until the compliance deadline
- **Print / export** — Export your readiness report for internal review

## How to Use

### Option 1: Use the live version (recommended)

Open the hosted version in your browser:

**https://sahirvhora.github.io/sf-pay-transparency/**

### Option 2: Run locally

```bash
# Clone the repository
git clone https://github.com/SahirVhora/sf-pay-transparency.git

# Open the HTML file directly in your browser
open sf-pay-transparency/index.html          # macOS
xdg-open sf-pay-transparency/index.html      # Linux
start sf-pay-transparency/index.html         # Windows
```

No server or build step is required — just open `index.html` in any modern browser.

## Tech Stack

- **Single-file application** — Everything (HTML, CSS, JavaScript) lives in one `index.html` file
- **No dependencies** — No frameworks, no build tools, no package installs
- **Responsive design** — Works on desktop and mobile browsers
- **Zero backend** — Runs entirely client-side

## Compliance Note

This tool is designed to help employers self-assess their readiness. It does not constitute legal advice. Always consult with qualified legal counsel for compliance guidance.

## License

MIT
