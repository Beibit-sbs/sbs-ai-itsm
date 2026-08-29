import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const sourceRoot = join(root, 'src')

function filesUnder(directory) {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name)
    return statSync(path).isDirectory() ? filesUnder(path) : [path]
  })
}

const sourceFiles = filesUnder(sourceRoot).filter((path) =>
  /\.(tsx|ts|css)$/.test(path),
)
const contents = new Map(
  sourceFiles.map((path) => [path, readFileSync(path, 'utf8')]),
)
const failures = []
const warnings = []

function requireText(path, pattern, message) {
  const content = readFileSync(path, 'utf8')
  if (!pattern.test(content)) failures.push(message)
}

const appShell = join(sourceRoot, 'components', 'AppShell.tsx')
const styles = join(sourceRoot, 'styles.css')
const indexHtml = join(root, 'index.html')
const searchPalette = join(
  sourceRoot,
  'components',
  'GlobalSearchPalette.tsx',
)
const ticketsPage = join(sourceRoot, 'pages', 'TicketsPage.tsx')
const catalogPage = join(sourceRoot, 'pages', 'CatalogPage.tsx')
const experienceContext = join(
  sourceRoot,
  'experience',
  'TenantExperienceContext.tsx',
)
const experiencePanel = join(
  sourceRoot,
  'components',
  'TenantExperiencePanel.tsx',
)
const localizedContentPanel = join(
  sourceRoot,
  'components',
  'LocalizedContentPanel.tsx',
)
const configurationCenterPanel = join(
  sourceRoot,
  'components',
  'ConfigurationCenterPanel.tsx',
)

requireText(indexHtml, /<html\s+lang="ru">/, 'Document language must be ru.')
requireText(
  appShell,
  /className="skip-link"[\s\S]*href="#main-content"/,
  'App shell must provide a skip link.',
)
requireText(
  appShell,
  /id="main-content"/,
  'App shell main landmark must have the skip-link target.',
)
requireText(
  appShell,
  /aria-live="polite"/,
  'Route changes must have a polite live announcement.',
)
requireText(
  appShell,
  /aria-expanded=\{mobileNavOpen\}/,
  'Mobile navigation toggle must expose its expanded state.',
)
requireText(
  styles,
  /:focus-visible/,
  'A global visible focus treatment is required.',
)
requireText(
  styles,
  /prefers-reduced-motion:\s*reduce/,
  'Reduced-motion behavior is required.',
)
requireText(
  styles,
  /forced-colors:\s*active/,
  'Forced-colors behavior is required.',
)
requireText(
  searchPalette,
  /useDialogFocusTrap/,
  'Global search must use the shared focus trap.',
)
requireText(
  ticketsPage,
  /ticket-bulk-dialog-title/,
  'Guarded bulk dialog must have an accessible name.',
)
requireText(
  ticketsPage,
  /bulkDialogRef/,
  'Guarded bulk dialog must trap and restore focus.',
)
requireText(
  ticketsPage,
  /<caption className="sr-only">Список заявок<\/caption>/,
  'The core ticket table must have an accessible name.',
)
requireText(
  ticketsPage,
  /ticketsQuery\.isError[\s\S]{0,160}role="alert"/,
  'Ticket loading failures must be announced.',
)
requireText(
  catalogPage,
  /detailDialogRef/,
  'Requester catalog dialog must trap and restore focus.',
)
requireText(
  experienceContext,
  /--brand-primary[\s\S]*--brand-accent[\s\S]*--brand-surface[\s\S]*--brand-text/,
  'Tenant experience must apply only bounded brand tokens.',
)
requireText(
  experienceContext,
  /data:image\/png;base64,/,
  'Cached tenant logos must remain validated PNG data URLs.',
)
requireText(
  experiencePanel,
  /snapshot_sha256[\s\S]*integrity_valid/,
  'Tenant experience history must expose hash and integrity evidence.',
)
requireText(
  localizedContentPanel,
  /source_current[\s\S]*integrity_valid[\s\S]*payload_sha256/,
  'Localized content history must expose source, integrity, and payload evidence.',
)
requireText(
  localizedContentPanel,
  /created_by_id[\s\S]*updated_by_id[\s\S]*ownReview/,
  'Localized content publication UI must enforce independent review.',
)
requireText(
  localizedContentPanel,
  /role=\{feedback\.kind === 'error' \? 'alert' : 'status'\}/,
  'Localized content workflow feedback must be announced.',
)
requireText(
  configurationCenterPanel,
  /aria-pressed=\{guidanceFilter === value\}/,
  'Administration guidance filters must expose their pressed state.',
)
requireText(
  configurationCenterPanel,
  /safe_default[\s\S]*required_permission[\s\S]*evidence_sha256/,
  'Administration guidance must expose safe defaults, ownership, and evidence.',
)
requireText(
  styles,
  /var\(--brand-primary\)[\s\S]*var\(--brand-accent\)/,
  'The shared stylesheet must consume tenant brand tokens.',
)

let dialogs = 0
let unnamedDialogFiles = 0
let unfocusedDialogs = 0
let images = 0
let imagesWithoutAlt = 0
let clickDivs = 0
let alertRegions = 0
let modalBackdropsWithoutPresentationRole = 0

for (const [path, content] of contents) {
  if (!path.endsWith('.tsx')) continue
  const relativePath = relative(root, path)
  const dialogMatches = content.matchAll(/role="dialog"/g)
  for (const match of dialogMatches) {
    dialogs += 1
    const start = Math.max(0, (match.index ?? 0) - 250)
    const end = Math.min(content.length, (match.index ?? 0) + 450)
    const fragment = content.slice(start, end)
    if (!/aria-(?:label|labelledby)=/.test(fragment)) {
      warnings.push(`${relativePath}: dialog may be missing an accessible name`)
      unnamedDialogFiles += 1
    }
    if (!/\bref=/.test(fragment)) {
      warnings.push(`${relativePath}: dialog may be missing focus management`)
      unfocusedDialogs += 1
    }
  }
  for (const match of content.matchAll(/<img\b[^>]*>/g)) {
    images += 1
    if (!/\balt=/.test(match[0])) {
      imagesWithoutAlt += 1
      warnings.push(`${relativePath}: image is missing alt`)
    }
  }
  clickDivs += (content.match(/<div\b[^>]*\bonClick=/g) ?? []).length
  alertRegions += (content.match(/\brole="(?:alert|status)"/g) ?? []).length
  for (const match of content.matchAll(
    /<div\b[^>]*className="modal-backdrop"[^>]*>/g,
  )) {
    if (!/role="presentation"/.test(match[0])) {
      modalBackdropsWithoutPresentationRole += 1
      warnings.push(
        `${relativePath}: modal backdrop must be presentational`,
      )
    }
  }
}

if (imagesWithoutAlt > 0) {
  failures.push(`${imagesWithoutAlt} image(s) are missing alt text.`)
}
if (unnamedDialogFiles > 0) {
  failures.push(`${unnamedDialogFiles} dialog(s) lack an accessible name.`)
}
if (unfocusedDialogs > 0) {
  failures.push(`${unfocusedDialogs} dialog(s) lack focus management.`)
}
if (modalBackdropsWithoutPresentationRole > 0) {
  failures.push(
    `${modalBackdropsWithoutPresentationRole} modal backdrop(s) expose false semantics.`,
  )
}

function channel(value) {
  const normalized = value / 255
  return normalized <= 0.03928
    ? normalized / 12.92
    : ((normalized + 0.055) / 1.055) ** 2.4
}

function luminance(hex) {
  const channels = hex
    .slice(1)
    .match(/../g)
    .map((value) => channel(Number.parseInt(value, 16)))
  return (
    0.2126 * channels[0]
    + 0.7152 * channels[1]
    + 0.0722 * channels[2]
  )
}

function contrastRatio(foreground, background) {
  const first = luminance(foreground)
  const second = luminance(background)
  return (
    (Math.max(first, second) + 0.05)
    / (Math.min(first, second) + 0.05)
  )
}

const contrastPairs = [
  ['primary text', '#e8f0fa', '#07111f'],
  ['muted text', '#8fa6bb', '#07111f'],
  ['navigation section', '#67859f', '#07111f'],
  ['context label', '#7f9ab0', '#0f1f30'],
  ['accent text', '#6dd5ff', '#07111f'],
  ['success badge', '#91ffd0', '#0f5d49'],
  ['error banner', '#ffd4d4', '#5e2020'],
  ['palette metadata', '#7896aa', '#0d1c2b'],
]
for (const [name, foreground, background] of contrastPairs) {
  const ratio = contrastRatio(foreground, background)
  if (ratio < 4.5) {
    failures.push(
      `${name} contrast is ${ratio.toFixed(2)}:1; expected at least 4.5:1.`,
    )
  }
}

console.log('Accessibility baseline')
console.log(`- source files: ${sourceFiles.length}`)
console.log(`- dialogs: ${dialogs}`)
console.log(`- potentially unnamed dialogs: ${unnamedDialogFiles}`)
console.log(`- dialogs without focus management: ${unfocusedDialogs}`)
console.log(`- images: ${images}`)
console.log(`- non-semantic clickable divs: ${clickDivs}`)
console.log(`- explicit alert/status regions: ${alertRegions}`)
console.log(`- audited text contrast pairs: ${contrastPairs.length}`)

for (const warning of warnings) console.warn(`WARN: ${warning}`)
for (const failure of failures) console.error(`FAIL: ${failure}`)

if (failures.length > 0) process.exit(1)
console.log('Accessibility baseline checks passed.')
