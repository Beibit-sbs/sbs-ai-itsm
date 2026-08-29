import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const sourceRoot = path.join(frontendRoot, 'src')
const catalogPath = path.join(sourceRoot, 'i18n', 'catalog.ts')
const visibleAllowlistPath = path.join(frontendRoot, 'scripts', 'i18n-visible-allowlist.json')
const externalSourceMessageModules = [
  {
    filename: 'adminPageSourceMessages.ts',
    exportName: 'adminPageSourceMessages',
    catalogSpreadName: 'adminPageMessages',
  },
  {
    filename: 'executionPageSourceMessages.ts',
    exportName: 'executionPageSourceMessages',
    catalogSpreadName: 'executionPageMessages',
  },
  {
    filename: 'insightPageSourceMessages.ts',
    exportName: 'insightPageSourceMessages',
    catalogSpreadName: 'insightPageMessages',
  },
  {
    filename: 'operationsPanelSourceMessages.ts',
    exportName: 'operationsPanelSourceMessages',
    catalogSpreadName: 'operationsPanelMessages',
  },
  {
    filename: 'operationsPageSourceMessages.ts',
    exportName: 'operationsPageSourceMessages',
    catalogSpreadName: 'operationsPageMessages',
  },
]
const externalEnglishSourceMessageModules = [
  {
    filename: 'sharedEnglishSourceMessages.ts',
    exportName: 'sharedEnglishSourceMessages',
    catalogSpreadName: 'sharedEnglishMessages',
  },
  {
    filename: 'adminEnglishSourceMessages.ts',
    exportName: 'adminEnglishSourceMessages',
    catalogSpreadName: 'adminEnglishMessages',
  },
  {
    filename: 'operationsEnglishSourceMessages.ts',
    exportName: 'operationsEnglishSourceMessages',
    catalogSpreadName: 'operationsEnglishMessages',
  },
]
const expectedLocales = ['ru-RU', 'kk-KZ', 'en-US']
const detailFilter = process.argv
  .find((argument) => argument.startsWith('--details='))
  ?.slice('--details='.length)
const detailLanguage = process.argv
  .find((argument) => argument.startsWith('--language='))
  ?.slice('--language='.length)
const detailOffset = Number(
  process.argv.find((argument) => argument.startsWith('--offset='))?.slice('--offset='.length)
  ?? 0,
)
const criticalFiles = new Set([
  'auth/RequireAuth.tsx',
  'components/AiActionsPanel.tsx',
  'components/AiGovernancePanel.tsx',
  'components/AiRuntimeControlsPanel.tsx',
  'components/AppShell.tsx',
  'components/AssetDiscoveryPanel.tsx',
  'components/CMDBImpactPanel.tsx',
  'components/CMDBQualityPanel.tsx',
  'components/CMDBReconciliationPanel.tsx',
  'components/CatalogFormDesigner.tsx',
  'components/CatalogFormFields.tsx',
  'components/CatalogKnowledgeDeflection.tsx',
  'components/CatalogRequestForm.tsx',
  'components/ConfigurationCenterPanel.tsx',
  'components/EntityCustomFieldsPanel.tsx',
  'components/IntegrationPlatformPanel.tsx',
  'components/LocalizedContentPanel.tsx',
  'components/MfaEnrollmentPanel.tsx',
  'components/RagAssistantPanel.tsx',
  'components/TenantExperiencePanel.tsx',
  'components/WorkflowEnginePanel.tsx',
  'components/WorkflowVisualDesigner.tsx',
  'pages/AccountPage.tsx',
  'pages/CatalogPage.tsx',
  'pages/KnowledgePage.tsx',
  'pages/RequestsPage.tsx',
  'pages/TicketsPage.tsx',
])
const cyrillicPattern = /[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]/
const latinPattern = /[A-Za-z]/
const allowlistCategories = new Set(['proper-noun', 'technical-id', 'non-ui'])
const translationFunctionNames = new Set([
  't',
  'translate',
  'translateMessage',
  'useLocalizedDefaultState',
])
const localizableFieldNames = new Set([
  'caption',
  'description',
  'hint',
  'label',
  'message',
  'placeholder',
  'summary',
  'text',
  'title',
])
const localizableBindingNamePattern = /(?:caption|description|hint|label|message|option|summary|tab|template|title)s?$/i
const localizableFunctionNamePattern = /(?:caption|displayName|humanize|label|localize|title)|^ru[A-Z]/i
const ambiguousLocalBindingNames = new Set([
  'action',
  'data',
  'entry',
  'field',
  'item',
  'key',
  'label',
  'option',
  'result',
  'selected',
  'source',
  'status',
  'tab',
  'target',
  'template',
  'type',
  'value',
])
const collectionMethodNames = new Set([
  'at',
  'entries',
  'every',
  'filter',
  'find',
  'findIndex',
  'flat',
  'flatMap',
  'forEach',
  'includes',
  'indexOf',
  'join',
  'keys',
  'length',
  'map',
  'reduce',
  'slice',
  'some',
  'sort',
  'values',
])

function unwrap(node) {
  while (
    ts.isAsExpression(node)
    || ts.isSatisfiesExpression(node)
    || ts.isParenthesizedExpression(node)
  ) node = node.expression
  return node
}

function propertyName(node) {
  if (!node?.name) return null
  if (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name) || ts.isNumericLiteral(node.name)) {
    return node.name.text
  }
  return null
}

function literalValue(node) {
  const value = unwrap(node)
  return ts.isStringLiteral(value) || ts.isNoSubstitutionTemplateLiteral(value)
    ? value.text
    : null
}

function findObjectVariable(sourceFile, name) {
  let result = null
  sourceFile.forEachChild((node) => {
    if (!ts.isVariableStatement(node)) return
    for (const declaration of node.declarationList.declarations) {
      if (ts.isIdentifier(declaration.name) && declaration.name.text === name && declaration.initializer) {
        const initializer = unwrap(declaration.initializer)
        if (ts.isObjectLiteralExpression(initializer)) result = initializer
      }
    }
  })
  return result
}

function placeholders(value) {
  return [...value.matchAll(/\{([A-Za-z_][A-Za-z0-9_.-]*)\}/g)]
    .map((match) => match[1])
    .sort()
}

function hasMalformedInterpolation(value) {
  const withoutValidPlaceholders = value.replace(/\{[A-Za-z_][A-Za-z0-9_.-]*\}/g, '')
  if (!/[{}]/.test(withoutValidPlaceholders)) return false
  try {
    const parsed = JSON.parse(value)
    return parsed === null || typeof parsed !== 'object'
  } catch {
    return true
  }
}

function normalizedVisible(value) {
  return value.replace(/\s+/g, ' ').trim()
}

function listSourceFiles(directory) {
  const result = []
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const absolute = path.join(directory, entry.name)
    if (entry.isDirectory()) result.push(...listSourceFiles(absolute))
    else if (/\.[cm]?[jt]sx?$/.test(entry.name)) result.push(absolute)
  }
  return result
}

const failures = []
const warnings = []
const allowlistUsage = new Map()
const allowlistedVisible = []
let visibleAllowlistEntries = []
try {
  const parsed = JSON.parse(fs.readFileSync(visibleAllowlistPath, 'utf8'))
  if (parsed.version !== 1 || !Array.isArray(parsed.entries)) {
    failures.push('i18n-visible-allowlist.json: expected version 1 and an entries array')
  } else {
    visibleAllowlistEntries = parsed.entries
    const seenValues = new Set()
    for (const [index, entry] of visibleAllowlistEntries.entries()) {
      const prefix = `i18n-visible-allowlist.json: entries[${index}]`
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
        failures.push(`${prefix} must be an object`)
        continue
      }
      const keys = Object.keys(entry).sort()
      if (keys.join(',') !== 'category,reason,value') {
        failures.push(`${prefix} must contain exactly value, category, and reason`)
      }
      if (typeof entry.value !== 'string' || normalizedVisible(entry.value) !== entry.value || !entry.value) {
        failures.push(`${prefix}.value must be a non-empty normalized exact string`)
      }
      if (!allowlistCategories.has(entry.category)) {
        failures.push(`${prefix}.category must be proper-noun, technical-id, or non-ui`)
      }
      if (typeof entry.reason !== 'string' || entry.reason.trim().length < 20) {
        failures.push(`${prefix}.reason must document the exception in at least 20 characters`)
      }
      if (seenValues.has(entry.value)) failures.push(`${prefix}: duplicate exact value ${JSON.stringify(entry.value)}`)
      seenValues.add(entry.value)
      allowlistUsage.set(entry.value, 0)
    }
  }
} catch (error) {
  failures.push(`i18n-visible-allowlist.json: cannot parse allowlist (${error instanceof Error ? error.message : String(error)})`)
}
const visibleAllowlist = new Map(visibleAllowlistEntries.map((entry) => [entry.value, entry]))
const catalogText = fs.readFileSync(catalogPath, 'utf8')
const catalogSource = ts.createSourceFile(
  catalogPath,
  catalogText,
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TS,
)
const messagesObject = findObjectVariable(catalogSource, 'messages')
const sourceKeysObject = findObjectVariable(catalogSource, 'sourceKeys')
const sourceMessagesObject = findObjectVariable(catalogSource, 'sourceMessages')
const englishSourceMessagesObject = findObjectVariable(catalogSource, 'englishSourceMessages')
const externalSourceObjects = externalSourceMessageModules.map((module) => {
  const modulePath = path.join(sourceRoot, 'i18n', module.filename)
  const moduleText = fs.existsSync(modulePath) ? fs.readFileSync(modulePath, 'utf8') : ''
  const moduleSource = ts.createSourceFile(
    modulePath,
    moduleText,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TS,
  )
  return {
    ...module,
    object: findObjectVariable(moduleSource, module.exportName),
  }
})
const externalEnglishSourceObjects = externalEnglishSourceMessageModules.map((module) => {
  const modulePath = path.join(sourceRoot, 'i18n', module.filename)
  const moduleText = fs.existsSync(modulePath) ? fs.readFileSync(modulePath, 'utf8') : ''
  const moduleSource = ts.createSourceFile(
    modulePath,
    moduleText,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TS,
  )
  return {
    ...module,
    object: findObjectVariable(moduleSource, module.exportName),
  }
})

if (!messagesObject) failures.push('catalog.ts: messages object was not found')
if (!sourceKeysObject) failures.push('catalog.ts: sourceKeys object was not found')
if (!sourceMessagesObject) failures.push('catalog.ts: sourceMessages object was not found')
if (!englishSourceMessagesObject) failures.push('catalog.ts: englishSourceMessages object was not found')
for (const module of externalSourceObjects) {
  if (!module.object) {
    failures.push(`${module.filename}: ${module.exportName} object was not found`)
  }
  if (
    sourceMessagesObject
    && !sourceMessagesObject.properties.some(
      (property) => ts.isSpreadAssignment(property)
        && ts.isIdentifier(property.expression)
        && property.expression.text === module.catalogSpreadName,
    )
  ) {
    failures.push(`catalog.ts: sourceMessages must include ...${module.catalogSpreadName}`)
  }
}
for (const module of externalEnglishSourceObjects) {
  if (!module.object) {
    failures.push(`${module.filename}: ${module.exportName} object was not found`)
  }
  if (
    englishSourceMessagesObject
    && !englishSourceMessagesObject.properties.some(
      (property) => ts.isSpreadAssignment(property)
        && ts.isIdentifier(property.expression)
        && property.expression.text === module.catalogSpreadName,
    )
  ) {
    failures.push(`catalog.ts: englishSourceMessages must include ...${module.catalogSpreadName}`)
  }
}

const messages = new Map()
const russianSources = new Map()
if (messagesObject) {
  for (const property of messagesObject.properties) {
    if (!ts.isPropertyAssignment(property)) continue
    const key = propertyName(property)
    if (!key) {
      failures.push(`catalog.ts:${catalogSource.getLineAndCharacterOfPosition(property.getStart()).line + 1}: unsupported message key`)
      continue
    }
    if (messages.has(key)) failures.push(`catalog.ts: duplicate message key "${key}"`)
    const initializer = unwrap(property.initializer)
    if (!ts.isCallExpression(initializer) || !ts.isIdentifier(initializer.expression) || initializer.expression.text !== 'message') {
      failures.push(`catalog.ts: "${key}" must use message(ru, kk, en)`)
      continue
    }
    if (initializer.arguments.length !== expectedLocales.length) {
      failures.push(`catalog.ts: "${key}" has ${initializer.arguments.length} locales; expected ${expectedLocales.length}`)
      continue
    }
    const values = initializer.arguments.map(literalValue)
    if (values.some((value) => value === null || value.trim() === '')) {
      failures.push(`catalog.ts: "${key}" contains a missing or non-literal locale value`)
      continue
    }
    const localized = Object.fromEntries(expectedLocales.map((locale, index) => [locale, values[index]]))
    messages.set(key, localized)
    const expectedPlaceholders = placeholders(localized['ru-RU'])
    for (const locale of expectedLocales) {
      const actual = placeholders(localized[locale])
      if (actual.join('\0') !== expectedPlaceholders.join('\0')) {
        failures.push(`catalog.ts: placeholder mismatch for "${key}" (${locale}: ${actual.join(', ') || 'none'}; ru-RU: ${expectedPlaceholders.join(', ') || 'none'})`)
      }
      if (hasMalformedInterpolation(localized[locale])) {
        failures.push(`catalog.ts: unresolved or malformed interpolation in "${key}" (${locale})`)
      }
    }
    const ru = normalizedVisible(localized['ru-RU'])
    if (!russianSources.has(ru)) russianSources.set(ru, [])
    russianSources.get(ru).push(key)
  }
}

for (const [source, keys] of russianSources) {
  if (keys.length < 2) continue
  const variants = keys.map((key) => messages.get(key))
  for (const locale of expectedLocales.slice(1)) {
    if (new Set(variants.map((value) => value[locale])).size > 1) {
      warnings.push(`ambiguous RU source "${source}" has different ${locale} translations: ${keys.join(', ')}`)
    }
  }
}

const explicitSources = new Map()
if (sourceKeysObject) {
  for (const property of sourceKeysObject.properties) {
    if (!ts.isPropertyAssignment(property)) continue
    const source = propertyName(property)
    const key = literalValue(property.initializer)
    if (!source || !key) {
      failures.push('catalog.ts: sourceKeys entries must be literal source/key pairs')
      continue
    }
    if (explicitSources.has(source)) failures.push(`catalog.ts: duplicate sourceKeys entry "${source}"`)
    explicitSources.set(normalizedVisible(source), key)
    if (!messages.has(key)) failures.push(`catalog.ts: sourceKeys "${source}" references missing key "${key}"`)
  }
}

const directSources = new Map()
if (sourceMessagesObject) {
  for (const property of sourceMessagesObject.properties) {
    if (!ts.isPropertyAssignment(property)) continue
    const source = propertyName(property)
    if (!source) {
      failures.push('catalog.ts: sourceMessages entries must use literal source keys')
      continue
    }
    const initializer = unwrap(property.initializer)
    if (!ts.isCallExpression(initializer) || !ts.isIdentifier(initializer.expression) || initializer.expression.text !== 'sourceMessage') {
      failures.push(`catalog.ts: sourceMessages "${source}" must use sourceMessage(kk, en)`)
      continue
    }
    if (initializer.arguments.length !== expectedLocales.length - 1) {
      failures.push(`catalog.ts: sourceMessages "${source}" has ${initializer.arguments.length + 1} locales including its RU key; expected ${expectedLocales.length}`)
      continue
    }
    const values = initializer.arguments.map(literalValue)
    if (values.some((value) => value === null || value.trim() === '')) {
      failures.push(`catalog.ts: sourceMessages "${source}" contains a missing or non-literal locale value`)
      continue
    }
    const normalizedSource = normalizedVisible(source)
    if (directSources.has(normalizedSource)) failures.push(`catalog.ts: duplicate sourceMessages entry "${source}"`)
    const localized = {
      'ru-RU': source,
      'kk-KZ': values[0],
      'en-US': values[1],
    }
    directSources.set(normalizedSource, localized)
    const expectedPlaceholders = placeholders(localized['ru-RU'])
    for (const locale of expectedLocales) {
      const actual = placeholders(localized[locale])
      if (actual.join('\0') !== expectedPlaceholders.join('\0')) {
        failures.push(`catalog.ts: sourceMessages placeholder mismatch for "${source}" (${locale})`)
      }
      if (hasMalformedInterpolation(localized[locale])) {
        failures.push(`catalog.ts: unresolved or malformed sourceMessages interpolation in "${source}" (${locale})`)
      }
    }
  }
}

for (const module of externalSourceObjects) {
  if (!module.object) continue
  for (const property of module.object.properties) {
    if (!ts.isPropertyAssignment(property)) {
      failures.push(`${module.filename}: entries must be literal source/object pairs`)
      continue
    }
    const source = propertyName(property)
    const initializer = unwrap(property.initializer)
    if (!source || !ts.isObjectLiteralExpression(initializer)) {
      failures.push(`${module.filename}: entries must use a literal RU key and { kk, en } object`)
      continue
    }
    const values = new Map()
    for (const localizedProperty of initializer.properties) {
      if (!ts.isPropertyAssignment(localizedProperty)) continue
      const locale = propertyName(localizedProperty)
      const value = literalValue(localizedProperty.initializer)
      if (locale && value !== null) values.set(locale, value)
    }
    if (values.size !== 2 || !values.has('kk') || !values.has('en')) {
      failures.push(`${module.filename}: "${source}" must contain literal kk and en values only`)
      continue
    }
    const normalizedSource = normalizedVisible(source)
    if (directSources.has(normalizedSource)) {
      failures.push(`duplicate direct source message across catalog/modules: "${source}"`)
      continue
    }
    const localized = {
      'ru-RU': source,
      'kk-KZ': values.get('kk'),
      'en-US': values.get('en'),
    }
    directSources.set(normalizedSource, localized)
    const expectedPlaceholders = placeholders(localized['ru-RU'])
    for (const locale of expectedLocales) {
      const actual = placeholders(localized[locale])
      if (actual.join('\0') !== expectedPlaceholders.join('\0')) {
        failures.push(`${module.filename}: placeholder mismatch for "${source}" (${locale})`)
      }
      if (hasMalformedInterpolation(localized[locale])) {
        failures.push(`${module.filename}: unresolved or malformed interpolation in "${source}" (${locale})`)
      }
    }
  }
}

const englishDirectSources = new Map()
for (const module of externalEnglishSourceObjects) {
  if (!module.object) continue
  for (const property of module.object.properties) {
    if (!ts.isPropertyAssignment(property)) {
      failures.push(`${module.filename}: entries must be literal source/object pairs`)
      continue
    }
    const source = propertyName(property)
    const initializer = unwrap(property.initializer)
    if (!source || !ts.isObjectLiteralExpression(initializer)) {
      failures.push(`${module.filename}: entries must use a literal EN key and { ru, kk } object`)
      continue
    }
    const values = new Map()
    for (const localizedProperty of initializer.properties) {
      if (!ts.isPropertyAssignment(localizedProperty)) continue
      const locale = propertyName(localizedProperty)
      const value = literalValue(localizedProperty.initializer)
      if (locale && value !== null) values.set(locale, value)
    }
    if (values.size !== 2 || !values.has('ru') || !values.has('kk')) {
      failures.push(`${module.filename}: "${source}" must contain literal ru and kk values only`)
      continue
    }
    const normalizedSource = normalizedVisible(source)
    if (englishDirectSources.has(normalizedSource)) {
      failures.push(`duplicate EN source message across modules: "${source}"`)
      continue
    }
    if (directSources.has(normalizedSource) || explicitSources.has(normalizedSource) || russianSources.has(normalizedSource)) {
      failures.push(`ambiguous RU/EN source message across catalogs: "${source}"`)
      continue
    }
    const localized = {
      'ru-RU': values.get('ru'),
      'kk-KZ': values.get('kk'),
      'en-US': source,
    }
    englishDirectSources.set(normalizedSource, localized)
    const expectedPlaceholders = placeholders(source)
    for (const locale of expectedLocales) {
      const actual = placeholders(localized[locale])
      if (actual.join('\0') !== expectedPlaceholders.join('\0')) {
        failures.push(`${module.filename}: placeholder mismatch for "${source}" (${locale})`)
      }
      if (hasMalformedInterpolation(localized[locale])) {
        failures.push(`${module.filename}: unresolved or malformed interpolation in "${source}" (${locale})`)
      }
    }
  }
}

const sourceFiles = listSourceFiles(sourceRoot)
const literalKeyUsages = []
const literalSourceUsages = []
const visibleCandidates = []
const dynamicLabelViolations = []
const localizedStateDefaultViolations = []
const staleLocalizedStateDefaultViolations = []
let dynamicLabelExpressionsChecked = 0
let localizableProducerCount = 0
for (const filename of sourceFiles) {
  const relative = path.relative(sourceRoot, filename).replaceAll('\\', '/')
  const text = fs.readFileSync(filename, 'utf8')
  const kind = filename.endsWith('.tsx') ? ts.ScriptKind.TSX : filename.endsWith('.jsx') ? ts.ScriptKind.JSX : ts.ScriptKind.TS
  const sourceFile = ts.createSourceFile(filename, text, ts.ScriptTarget.Latest, true, kind)
  const supportsExactSourceLocalization = (
    text.includes('<LocalizedContent')
    || text.includes('localizeTree(')
    || text.includes('<AppShell')
    || text.includes('<SectionPage')
  )

  const isExplicitTranslationCall = (node) => {
    const expression = unwrap(node)
    return ts.isCallExpression(expression)
      && ts.isIdentifier(expression.expression)
      && translationFunctionNames.has(expression.expression.text)
  }

  const isKnownLocalizableText = (value) => {
    const normalized = normalizedVisible(value)
    if (
      !normalized
      || visibleAllowlist.has(normalized)
      || (!cyrillicPattern.test(normalized) && !latinPattern.test(normalized))
    ) return false
    return cyrillicPattern.test(normalized)
      ? explicitSources.has(normalized) || russianSources.has(normalized) || directSources.has(normalized)
      : englishDirectSources.has(normalized) || explicitSources.has(normalized)
  }

  const isLikelyHumanLabelText = (value) => {
    const normalized = normalizedVisible(value)
    if (!isKnownLocalizableText(normalized)) return false
    if (cyrillicPattern.test(normalized)) return true
    if (/^[A-Z][a-z]/.test(normalized)) return true
    return /[\s.,:;!?()…]/.test(normalized)
  }

  const allVariableDeclarations = []
  const variableDeclarations = []
  const functionDefinitions = []
  const localizableContainers = new Set()
  const localizableScalars = new Set()
  const localizableFunctions = new Set()

  const visitDefinition = (node) => {
    if (ts.isVariableDeclaration(node) && node.initializer) {
      allVariableDeclarations.push(node)
      if (ts.isIdentifier(node.name)) {
        variableDeclarations.push(node)
        const initializer = unwrap(node.initializer)
        if (ts.isArrowFunction(initializer) || ts.isFunctionExpression(initializer)) {
          functionDefinitions.push({ name: node.name.text, node: initializer })
        }
      }
    }
    if (ts.isFunctionDeclaration(node) && node.name) {
      functionDefinitions.push({ name: node.name.text, node })
    }
    ts.forEachChild(node, visitDefinition)
  }
  visitDefinition(sourceFile)

  const containsKnownLocalizableLiteral = (node) => {
    let found = false
    const inspect = (child) => {
      if (found) return
      if (ts.isStringLiteral(child) || ts.isNoSubstitutionTemplateLiteral(child)) {
        found = isLikelyHumanLabelText(child.text)
        return
      }
      ts.forEachChild(child, inspect)
    }
    inspect(node)
    return found
  }

  const hasLocalizableFieldLiteral = (node) => {
    let found = false
    const inspect = (child) => {
      if (found) return
      if (ts.isPropertyAssignment(child)) {
        const name = propertyName(child)?.toLowerCase()
        const value = literalValue(child.initializer)
        if (name && localizableFieldNames.has(name) && value !== null && isKnownLocalizableText(value)) {
          found = true
          return
        }
      }
      ts.forEachChild(child, inspect)
    }
    inspect(node)
    return found
  }

  for (const declaration of variableDeclarations) {
    const initializer = unwrap(declaration.initializer)
    if (!ts.isObjectLiteralExpression(initializer) && !ts.isArrayLiteralExpression(initializer)) continue
    const name = declaration.name.text
    if (
      hasLocalizableFieldLiteral(initializer)
      || (localizableBindingNamePattern.test(name) && containsKnownLocalizableLiteral(initializer))
    ) localizableContainers.add(name)
  }

  const referencesBinding = (node, bindings) => {
    let found = false
    const inspect = (child) => {
      if (found) return
      if (ts.isIdentifier(child) && bindings.has(child.text)) {
        found = true
        return
      }
      if (isExplicitTranslationCall(child)) return
      ts.forEachChild(child, inspect)
    }
    inspect(node)
    return found
  }

  const bindingContainsName = (binding, name) => {
    if (ts.isIdentifier(binding)) return binding.text === name
    return binding.elements.some((element) => {
      if (ts.isOmittedExpression(element)) return false
      return bindingContainsName(element.name, name)
    })
  }

  const functionReturnExpressions = (definition) => {
    if (ts.isArrowFunction(definition) && !ts.isBlock(definition.body)) return [definition.body]
    const result = []
    const inspect = (node) => {
      if (node !== definition && ts.isFunctionLike(node)) return
      if (ts.isReturnStatement(node) && node.expression) {
        result.push(node.expression)
        return
      }
      ts.forEachChild(node, inspect)
    }
    inspect(definition.body)
    return result
  }

  const outputContainsLocalizableLiteral = (node) => {
    const expression = unwrap(node)
    if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) {
      return isKnownLocalizableText(expression.text)
    }
    if (ts.isConditionalExpression(expression)) {
      return outputContainsLocalizableLiteral(expression.whenTrue)
        || outputContainsLocalizableLiteral(expression.whenFalse)
    }
    if (ts.isObjectLiteralExpression(expression)) return hasLocalizableFieldLiteral(expression)
    return false
  }

  for (const definition of functionDefinitions) {
    if (
      localizableFunctionNamePattern.test(definition.name)
      && functionReturnExpressions(definition.node).some(outputContainsLocalizableLiteral)
    ) {
      localizableFunctions.add(definition.name)
    }
  }

  const rootIdentifier = (node) => {
    let expression = unwrap(node)
    while (true) {
      if (ts.isIdentifier(expression)) return expression.text
      if (ts.isPropertyAccessExpression(expression) || ts.isElementAccessExpression(expression)) {
        expression = unwrap(expression.expression)
        continue
      }
      if (ts.isCallExpression(expression)) {
        expression = unwrap(expression.expression)
        continue
      }
      return null
    }
  }

  const isLocalizableAccess = (node) => {
    if (ts.isElementAccessExpression(node)) {
      const root = rootIdentifier(node.expression)
      return Boolean(root && (localizableContainers.has(root) || localizableScalars.has(root)))
    }
    if (!ts.isPropertyAccessExpression(node)) return false
    const member = node.name.text
    if (collectionMethodNames.has(member)) return false
    const root = rootIdentifier(node.expression)
    if (!root || (!localizableContainers.has(root) && !localizableScalars.has(root))) return false
    return localizableContainers.has(root) || localizableFieldNames.has(member.toLowerCase())
  }

  const expressionHasLocalizableProducer = (node) => {
    const expression = unwrap(node)
    if (isExplicitTranslationCall(expression)) return false
    if (ts.isIdentifier(expression)) return localizableScalars.has(expression.text)
    if (isLocalizableAccess(expression)) return true
    if (ts.isConditionalExpression(expression)) {
      return expressionHasLocalizableProducer(expression.whenTrue)
        || expressionHasLocalizableProducer(expression.whenFalse)
    }
    if (ts.isBinaryExpression(expression)) {
      return expressionHasLocalizableProducer(expression.left)
        || expressionHasLocalizableProducer(expression.right)
    }
    if (!ts.isCallExpression(expression)) return false
    if (ts.isIdentifier(expression.expression)) {
      if (localizableFunctions.has(expression.expression.text)) return true
      if (
        ['useMemo', 'useCallback'].includes(expression.expression.text)
        && expression.arguments[0]
        && (ts.isArrowFunction(expression.arguments[0]) || ts.isFunctionExpression(expression.arguments[0]))
      ) {
        return functionReturnExpressions(expression.arguments[0]).some(expressionHasLocalizableProducer)
      }
      return false
    }
    if (ts.isPropertyAccessExpression(expression.expression)) {
      const method = expression.expression.name.text
      if (
        ['at', 'find'].includes(method)
        && referencesBinding(expression.expression.expression, localizableContainers)
      ) return true
      if (method === 'join') {
        const receiver = unwrap(expression.expression.expression)
        if (
          ts.isCallExpression(receiver)
          && ts.isPropertyAccessExpression(receiver.expression)
          && receiver.expression.name.text === 'map'
        ) {
          const callback = receiver.arguments.find(
            (argument) => ts.isArrowFunction(argument) || ts.isFunctionExpression(argument),
          )
          if (callback) {
            const returns = functionReturnExpressions(callback)
            if (returns.some(expressionHasLocalizableProducer)) return true
            const sourceIsLocalizable = referencesBinding(receiver.expression.expression, localizableContainers)
            if (
              sourceIsLocalizable
              && returns.some((returned) => {
                const value = unwrap(returned)
                return ts.isIdentifier(value)
                  && localizableFieldNames.has(value.text.toLowerCase())
                  && callback.parameters.some((parameter) => bindingContainsName(parameter.name, value.text))
              })
            ) return true
            return false
          }
        }
        return referencesBinding(receiver, localizableContainers)
      }
    }
    return false
  }

  const collectionMethod = (node) => {
    let found = null
    const inspect = (child) => {
      if (found) return
      if (
        ts.isCallExpression(child)
        && ts.isPropertyAccessExpression(child.expression)
        && ['filter', 'flatMap', 'map', 'slice', 'sort'].includes(child.expression.name.text)
        && referencesBinding(child.expression.expression, localizableContainers)
      ) {
        found = child.expression.name.text
        return
      }
      ts.forEachChild(child, inspect)
    }
    inspect(node)
    return found
  }

  // Propagate local label sources through derived option collections, helpers,
  // useMemo/find results, and scalar aliases. This remains file-local on purpose:
  // API/user/server values are never considered translation producers.
  for (let iteration = 0; iteration < variableDeclarations.length + functionDefinitions.length + 1; iteration += 1) {
    let changed = false
    for (const definition of functionDefinitions) {
      if (localizableFunctions.has(definition.name)) continue
      const returns = functionReturnExpressions(definition.node)
      const returnsLocalizableAccess = returns.some(expressionHasLocalizableProducer)
      const returnsLabelMember = returns.some((expression) => {
        let found = false
        const inspect = (child) => {
          if (found) return
          if (isExplicitTranslationCall(child)) return
          if (
            ts.isPropertyAccessExpression(child)
            && localizableFieldNames.has(child.name.text.toLowerCase())
          ) {
            found = true
            return
          }
          ts.forEachChild(child, inspect)
        }
        inspect(expression)
        return found
      })
      if (
        localizableFunctionNamePattern.test(definition.name)
        && (
        returnsLocalizableAccess
        || (returnsLabelMember && referencesBinding(definition.node.body, localizableContainers))
        )
      ) {
        localizableFunctions.add(definition.name)
        changed = true
      }
    }
    for (const declaration of variableDeclarations) {
      const name = declaration.name.text
      if (localizableContainers.has(name) || localizableScalars.has(name)) continue
      const initializer = unwrap(declaration.initializer)
      const method = collectionMethod(initializer)
      if (method || (localizableBindingNamePattern.test(name) && referencesBinding(initializer, localizableContainers))) {
        localizableContainers.add(name)
        changed = true
        continue
      }
      if (
        !ambiguousLocalBindingNames.has(name)
        && expressionHasLocalizableProducer(initializer)
      ) {
        localizableScalars.add(name)
        changed = true
      }
    }
    if (!changed) break
  }
  localizableProducerCount += localizableContainers.size + localizableScalars.size + localizableFunctions.size

  const callbackSource = (callback) => {
    if (!ts.isCallExpression(callback.parent) || !callback.parent.arguments.includes(callback)) return null
    const call = callback.parent
    if (!ts.isPropertyAccessExpression(call.expression) || call.expression.name.text !== 'map') return null
    return call.expression.expression
  }

  const isLocalizableCallbackBinding = (name, node) => {
    let current = node.parent
    while (current && current !== sourceFile) {
      if (ts.isArrowFunction(current) || ts.isFunctionExpression(current)) {
        const source = callbackSource(current)
        if (
          source
          && current.parameters.some((parameter) => bindingContainsName(parameter.name, name))
          && referencesBinding(source, localizableContainers)
        ) return true
      }
      current = current.parent
    }
    return false
  }

  const dynamicViolationReason = (node) => {
    let reason = null
    const inspect = (child) => {
      if (reason) return
      if (isExplicitTranslationCall(child)) return
      if (child !== node && (ts.isJsxElement(child) || ts.isJsxFragment(child) || ts.isJsxSelfClosingElement(child))) return
      if (child !== node && ts.isFunctionLike(child)) return
      if (ts.isConditionalExpression(child)) {
        inspect(child.whenTrue)
        inspect(child.whenFalse)
        return
      }
      if (
        ts.isCallExpression(child)
        && ts.isIdentifier(child.expression)
        && localizableFunctions.has(child.expression.text)
      ) {
        reason = `helper ${child.expression.text}() returns a localized label`
        return
      }
      if (
        ts.isCallExpression(child)
        && ts.isPropertyAccessExpression(child.expression)
        && child.expression.name.text === 'join'
        && expressionHasLocalizableProducer(child)
      ) {
        reason = `joined local labels ${child.getText(sourceFile)}`
        return
      }
      if (isLocalizableAccess(child)) {
        reason = `local label source ${child.getText(sourceFile)}`
        return
      }
      if (
        ts.isPropertyAccessExpression(child)
        && localizableFieldNames.has(child.name.text.toLowerCase())
        && ts.isIdentifier(child.expression)
        && isLocalizableCallbackBinding(child.expression.text, child)
      ) {
        reason = `map label ${child.getText(sourceFile)}`
        return
      }
      if (
        ts.isIdentifier(child)
        && !ts.isPropertyAccessExpression(child.parent)
        && !ts.isElementAccessExpression(child.parent)
        && (
          localizableScalars.has(child.text)
          || (
            localizableFieldNames.has(child.text.toLowerCase())
            && isLocalizableCallbackBinding(child.text, child)
          )
        )
      ) {
        reason = `local label binding ${child.text}`
        return
      }
      ts.forEachChild(child, inspect)
    }
    inspect(node)
    return reason
  }

  const recordDynamicLabelViolation = (expression, context) => {
    dynamicLabelExpressionsChecked += 1
    const reason = dynamicViolationReason(expression)
    if (!reason) return
    dynamicLabelViolations.push({
      relative,
      line: sourceFile.getLineAndCharacterOfPosition(expression.getStart(sourceFile)).line + 1,
      context,
      expression: expression.getText(sourceFile).replace(/\s+/g, ' ').slice(0, 180),
      reason,
    })
  }

  const stateDefaults = new Map()
  for (const declaration of allVariableDeclarations) {
    if (!ts.isArrayBindingPattern(declaration.name) || !declaration.initializer) continue
    const stateBinding = declaration.name.elements[0]
    if (!stateBinding || ts.isOmittedExpression(stateBinding) || !ts.isIdentifier(stateBinding.name)) continue
    const initializer = unwrap(declaration.initializer)
    if (
      !ts.isCallExpression(initializer)
      || !ts.isIdentifier(initializer.expression)
      || initializer.expression.text !== 'useState'
      || !initializer.arguments[0]
    ) continue
    let dependsOnTranslate = false
    const inspectLegacyLocalizedDefault = (node) => {
      if (ts.isIdentifier(node) && node.text === 'translate') {
        dependsOnTranslate = true
        return
      }
      ts.forEachChild(node, inspectLegacyLocalizedDefault)
    }
    inspectLegacyLocalizedDefault(initializer.arguments[0])
    if (dependsOnTranslate) {
      staleLocalizedStateDefaultViolations.push({
        relative,
        line: sourceFile.getLineAndCharacterOfPosition(initializer.getStart(sourceFile)).line + 1,
        stateName: stateBinding.name.text,
        expression: initializer.getText(sourceFile).replace(/\s+/g, ' ').slice(0, 220),
      })
    }
    const defaultValue = literalValue(initializer.arguments[0])
    if (
      defaultValue !== null
      && cyrillicPattern.test(defaultValue)
      && !visibleAllowlist.has(normalizedVisible(defaultValue))
    ) {
      stateDefaults.set(stateBinding.name.text, {
        value: normalizedVisible(defaultValue),
        line: sourceFile.getLineAndCharacterOfPosition(initializer.arguments[0].getStart(sourceFile)).line + 1,
      })
    }
  }

  function recordVisible(value, node, context, requiresExplicitTranslation = false) {
    const normalized = normalizedVisible(value)
    if (!normalized || (!cyrillicPattern.test(normalized) && !latinPattern.test(normalized))) return
    const line = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1
    const allowlistEntry = visibleAllowlist.get(normalized)
    if (allowlistEntry) {
      allowlistUsage.set(normalized, (allowlistUsage.get(normalized) ?? 0) + 1)
      allowlistedVisible.push({ relative, line, value: normalized, context, category: allowlistEntry.category })
      return
    }
    visibleCandidates.push({
      relative,
      line,
      value: normalized,
      context,
      language: cyrillicPattern.test(normalized) ? 'cyrillic-or-mixed' : 'latin-only',
      critical: criticalFiles.has(relative),
      requiresExplicitTranslation,
      supportsExactSourceLocalization,
    })
  }

  function collectRenderedExpressionStrings(node, context, requiresExplicitTranslation = false) {
    const expression = unwrap(node)
    if (
      ts.isCallExpression(expression)
      && ts.isIdentifier(expression.expression)
      && ['t', 'translate', 'translateMessage'].includes(expression.expression.text)
    ) return
    if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) {
      recordVisible(expression.text, expression, context, requiresExplicitTranslation)
      return
    }
    if (ts.isTemplateExpression(expression)) {
      recordVisible(expression.head.text, expression.head, context, true)
      for (const span of expression.templateSpans) {
        recordVisible(span.literal.text, span.literal, context, true)
        collectRenderedExpressionStrings(span.expression, context, true)
      }
      return
    }
    if (ts.isConditionalExpression(expression)) {
      collectRenderedExpressionStrings(expression.whenTrue, context)
      collectRenderedExpressionStrings(expression.whenFalse, context)
      return
    }
    if (ts.isBinaryExpression(expression)) {
      if (expression.operatorToken.kind === ts.SyntaxKind.PlusToken) {
        collectRenderedExpressionStrings(expression.left, context, true)
        collectRenderedExpressionStrings(expression.right, context, true)
      } else if (
        expression.operatorToken.kind === ts.SyntaxKind.BarBarToken
        || expression.operatorToken.kind === ts.SyntaxKind.QuestionQuestionToken
      ) {
        collectRenderedExpressionStrings(expression.right, context)
      }
    }
  }

  function visit(node) {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
      const name = node.expression.text
      const keyArgument = name === 'translateMessage' ? node.arguments[1] : name === 't' ? node.arguments[0] : null
      if (keyArgument) {
        const key = literalValue(keyArgument)
        if (key) literalKeyUsages.push({ relative, line: sourceFile.getLineAndCharacterOfPosition(keyArgument.getStart()).line + 1, key })
      }
      const interpolationArgument = name === 't'
        ? node.arguments[1]
        : name === 'translateMessage'
          ? node.arguments[2]
          : null
      if (interpolationArgument && ts.isObjectLiteralExpression(unwrap(interpolationArgument))) {
        for (const property of unwrap(interpolationArgument).properties) {
          if (ts.isPropertyAssignment(property)) {
            recordDynamicLabelViolation(property.initializer, 'translation-interpolation')
          }
        }
      }
      if (['translate', 'useLocalizedDefaultState'].includes(name) && node.arguments[0]) {
        const source = literalValue(node.arguments[0])
        if (source) {
          literalSourceUsages.push({
            relative,
            line: sourceFile.getLineAndCharacterOfPosition(node.arguments[0].getStart()).line + 1,
            source: normalizedVisible(source),
          })
        }
        if (name === 'useLocalizedDefaultState') {
          const factory = unwrap(node.arguments[0])
          const parameter = (
            (ts.isArrowFunction(factory) || ts.isFunctionExpression(factory))
            && factory.parameters[0]
            && ts.isIdentifier(factory.parameters[0].name)
          ) ? factory.parameters[0].name.text : null
          if (parameter) {
            const collectFactorySources = (child) => {
              if (
                ts.isCallExpression(child)
                && ts.isIdentifier(child.expression)
                && child.expression.text === parameter
                && child.arguments[0]
              ) {
                const factorySource = literalValue(child.arguments[0])
                if (factorySource) {
                  literalSourceUsages.push({
                    relative,
                    line: sourceFile.getLineAndCharacterOfPosition(child.arguments[0].getStart()).line + 1,
                    source: normalizedVisible(factorySource),
                  })
                }
              }
              ts.forEachChild(child, collectFactorySources)
            }
            collectFactorySources(factory.body)
          }
        }
      }
    }
    if (ts.isCallExpression(node)) {
      const calleeName = ts.isIdentifier(node.expression)
        ? node.expression.text
        : ts.isPropertyAccessExpression(node.expression)
          ? node.expression.name.text
          : ''
      if (['alert', 'confirm', 'prompt'].includes(calleeName) && node.arguments[0]) {
        const collectDialogStrings = (child) => {
          if (
            ts.isCallExpression(child)
            && ts.isIdentifier(child.expression)
            && ['t', 'translate', 'translateMessage'].includes(child.expression.text)
          ) return
          if (ts.isStringLiteral(child) || ts.isNoSubstitutionTemplateLiteral(child)) {
            recordVisible(child.text, child, 'browser-dialog', true)
            return
          }
          if (ts.isTemplateExpression(child)) {
            recordVisible(child.head.text, child.head, 'browser-dialog', true)
            for (const span of child.templateSpans) {
              recordVisible(span.literal.text, span.literal, 'browser-dialog', true)
              collectDialogStrings(span.expression)
            }
            return
          }
          ts.forEachChild(child, collectDialogStrings)
        }
        collectDialogStrings(node.arguments[0])
      }
    }
    if (
      ts.isNewExpression(node)
      && ts.isIdentifier(node.expression)
      && node.expression.text === 'Error'
      && node.arguments?.[0]
    ) {
      const value = literalValue(node.arguments[0])
      if (value) recordVisible(value, node.arguments[0], 'error-message')
    }
    if (ts.isJsxText(node)) recordVisible(node.text, node, 'jsx-text')
    if (ts.isJsxAttribute(node) && node.initializer) {
      const name = node.name.getText(sourceFile)
      if (['aria-label', 'aria-description', 'placeholder', 'title'].includes(name)) {
        if (ts.isStringLiteral(node.initializer)) {
          recordVisible(node.initializer.text, node.initializer, `jsx-${name}`)
        } else if (ts.isJsxExpression(node.initializer) && node.initializer.expression) {
          collectRenderedExpressionStrings(node.initializer.expression, `jsx-${name}`)
          recordDynamicLabelViolation(node.initializer.expression, `jsx-${name}`)
        }
      }
      if (
        ['value', 'defaultValue'].includes(name)
        && ts.isJsxExpression(node.initializer)
        && node.initializer.expression
        && ts.isIdentifier(unwrap(node.initializer.expression))
      ) {
        const stateName = unwrap(node.initializer.expression).text
        const stateDefault = stateDefaults.get(stateName)
        const opening = node.parent?.parent
        const tagName = opening && (ts.isJsxOpeningElement(opening) || ts.isJsxSelfClosingElement(opening))
          ? opening.tagName.getText(sourceFile).toLowerCase()
          : ''
        const hidden = opening && (ts.isJsxOpeningElement(opening) || ts.isJsxSelfClosingElement(opening))
          ? opening.attributes.properties.some(
            (attribute) => ts.isJsxAttribute(attribute)
              && attribute.name.getText(sourceFile) === 'type'
              && ts.isStringLiteral(attribute.initializer)
              && attribute.initializer.text.toLowerCase() === 'hidden',
          )
          : false
        if (stateDefault && ['input', 'textarea', 'select'].includes(tagName) && !hidden) {
          localizedStateDefaultViolations.push({
            relative,
            line: stateDefault.line,
            usageLine: sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1,
            stateName,
            value: stateDefault.value,
            tagName,
          })
        }
      }
    }
    if (ts.isJsxExpression(node) && node.expression) {
      if (!ts.isJsxAttribute(node.parent)) {
        collectRenderedExpressionStrings(node.expression, 'jsx-expression')
        recordDynamicLabelViolation(node.expression, 'jsx-expression')
      }
    }
    if (ts.isPropertyAssignment(node)) {
      const name = propertyName(node)
      if (['label', 'title', 'description', 'summary', 'placeholder', 'message', 'hint'].includes(name ?? '')) {
        const value = literalValue(node.initializer)
        if (value && !messages.has(value)) recordVisible(value, node.initializer, `object-${name}`)
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
}

const uniqueDynamicLabelViolations = [
  ...new Map(
    dynamicLabelViolations.map((item) => [
      `${item.relative}\0${item.line}\0${item.context}\0${item.expression}`,
      item,
    ]),
  ).values(),
]
const uniqueLocalizedStateDefaultViolations = [
  ...new Map(
    localizedStateDefaultViolations.map((item) => [
      `${item.relative}\0${item.line}\0${item.stateName}\0${item.usageLine}`,
      item,
    ]),
  ).values(),
]
if (uniqueDynamicLabelViolations.length) {
  failures.push(`blocking dynamic-label translation violations: ${uniqueDynamicLabelViolations.length}`)
}
if (uniqueLocalizedStateDefaultViolations.length) {
  failures.push(`blocking localized useState defaults rendered in form controls: ${uniqueLocalizedStateDefaultViolations.length}`)
}
if (staleLocalizedStateDefaultViolations.length) {
  failures.push(`blocking locale-stale useState defaults: ${staleLocalizedStateDefaultViolations.length}`)
}

for (const usage of literalKeyUsages) {
  if (!messages.has(usage.key)) failures.push(`${usage.relative}:${usage.line}: missing message key "${usage.key}"`)
}
for (const usage of literalSourceUsages) {
  const isCyrillicSource = cyrillicPattern.test(usage.source)
  const mapped = isCyrillicSource
    ? explicitSources.has(usage.source) || russianSources.has(usage.source) || directSources.has(usage.source)
    : englishDirectSources.has(usage.source) || explicitSources.has(usage.source) || visibleAllowlist.has(usage.source)
  if (!mapped) {
    failures.push(`${usage.relative}:${usage.line}: translate() source has no explicit locale mapping ${JSON.stringify(usage.source)}`)
  }
}

const uniqueCandidates = new Map()
for (const candidate of visibleCandidates) {
  const id = `${candidate.relative}\0${candidate.value}\0${candidate.requiresExplicitTranslation ? 'explicit' : 'mapped'}`
  if (!uniqueCandidates.has(id)) uniqueCandidates.set(id, candidate)
}
const candidates = [...uniqueCandidates.values()]
const isMapped = (candidate) => (
  !candidate.requiresExplicitTranslation
  && (!candidate.context.startsWith('jsx-') || candidate.supportsExactSourceLocalization)
  && (candidate.language === 'latin-only'
    ? englishDirectSources.has(candidate.value) || explicitSources.has(candidate.value)
    : (
      explicitSources.has(candidate.value)
      || russianSources.has(candidate.value)
      || directSources.has(candidate.value)
    ))
)
const mappedCandidates = candidates.filter(isMapped)
const unresolvedCritical = candidates.filter((candidate) => candidate.critical && !isMapped(candidate))
const unresolvedOther = candidates.filter((candidate) => !candidate.critical && !isMapped(candidate))
const unresolvedVisible = [...unresolvedCritical, ...unresolvedOther]
const cyrillicCandidates = candidates.filter((candidate) => candidate.language === 'cyrillic-or-mixed')
const latinCandidates = candidates.filter((candidate) => candidate.language === 'latin-only')
const unresolvedCyrillic = unresolvedVisible.filter((candidate) => candidate.language === 'cyrillic-or-mixed')
const unresolvedLatin = unresolvedVisible.filter((candidate) => candidate.language === 'latin-only')
if (unresolvedVisible.length) {
  failures.push(`blocking visible-string violations: ${unresolvedVisible.length}`)
}

console.log('SBS AI ITSM i18n audit')
console.log(`locales: ${expectedLocales.join(', ')}`)
console.log(`messages: ${messages.size}`)
console.log(`explicit source aliases: ${explicitSources.size}`)
console.log(`direct source messages: ${directSources.size}`)
console.log(`English source messages: ${englishDirectSources.size}`)
console.log(`literal key usages: ${literalKeyUsages.length}`)
console.log(`literal translate source usages: ${literalSourceUsages.length}`)
console.log(`dynamic label guard: ${localizableProducerCount} file-local producers; ${dynamicLabelExpressionsChecked} JSX expressions checked; ${uniqueDynamicLabelViolations.length} unresolved`)
console.log(`localized form-state defaults: ${uniqueLocalizedStateDefaultViolations.length} unresolved`)
console.log(`locale-reactive default guard: ${staleLocalizedStateDefaultViolations.length} stale useState initializers`)
console.log(`visible Cyrillic/Latin candidates: ${candidates.length}; mapped: ${mappedCandidates.length}; allowlisted: ${allowlistedVisible.length}; unresolved: ${candidates.length - mappedCandidates.length}`)
console.log(`Cyrillic/mixed candidates: ${cyrillicCandidates.length}; unresolved: ${unresolvedCyrillic.length}`)
console.log(`Latin-only candidates: ${latinCandidates.length}; unresolved: ${unresolvedLatin.length}`)
console.log(`critical unresolved: ${unresolvedCritical.length}; other unresolved: ${unresolvedOther.length}`)
const unusedAllowlistEntries = [...allowlistUsage].filter(([, count]) => count === 0).map(([value]) => value)
if (unusedAllowlistEntries.length) {
  warnings.push(`unused visible allowlist entries: ${unusedAllowlistEntries.map((value) => JSON.stringify(value)).join(', ')}`)
}
if (allowlistedVisible.length) {
  const allowlistByCategory = new Map()
  for (const item of allowlistedVisible) {
    allowlistByCategory.set(item.category, (allowlistByCategory.get(item.category) ?? 0) + 1)
  }
  console.log(`allowlisted visible occurrences: ${[...allowlistByCategory].map(([category, count]) => `${category}=${count}`).join(', ')}`)
}
if (unresolvedCritical.length) {
  const byFile = new Map()
  for (const item of unresolvedCritical) byFile.set(item.relative, (byFile.get(item.relative) ?? 0) + 1)
  console.log('critical unresolved by file:')
  for (const [filename, count] of [...byFile].sort((left, right) => right[1] - left[1])) {
    console.log(`  ${filename}: ${count}`)
  }
}
if (unresolvedOther.length) {
  const byFile = new Map()
  for (const item of unresolvedOther) byFile.set(item.relative, (byFile.get(item.relative) ?? 0) + 1)
  console.log('other unresolved by file (top 40):')
  for (const [filename, count] of [...byFile].sort((left, right) => right[1] - left[1]).slice(0, 40)) {
    console.log(`  ${filename}: ${count}`)
  }
}

if (warnings.length) {
  console.log(`\nWarnings (${warnings.length}):`)
  for (const warning of warnings.slice(0, 30)) console.log(`- ${warning}`)
  if (warnings.length > 30) console.log(`- ... ${warnings.length - 30} more`)
}
if (unresolvedVisible.length) {
  const detailedVisible = detailFilter
    ? unresolvedVisible.filter((item) => item.relative.includes(detailFilter))
    : unresolvedVisible
  const languageFilteredVisible = detailLanguage
    ? detailedVisible.filter((item) => item.language === detailLanguage)
    : detailedVisible
  console.log(`\nUnresolved blocking visible strings (${unresolvedVisible.length}):`)
  for (const item of languageFilteredVisible.slice(detailOffset, detailOffset + 120)) {
    console.log(`- ${item.relative}:${item.line} [${item.context}] ${JSON.stringify(item.value)}`)
  }
  if (languageFilteredVisible.length > detailOffset + 120) {
    console.log(`- ... ${languageFilteredVisible.length - detailOffset - 120} more`)
  }
}
if (unresolvedOther.length) {
  console.log(`\nUnresolved non-critical strings (${unresolvedOther.length}; first 30):`)
  for (const item of unresolvedOther.slice(0, 30)) {
    console.log(`- ${item.relative}:${item.line} [${item.context}] ${JSON.stringify(item.value)}`)
  }
}
if (uniqueDynamicLabelViolations.length) {
  console.log(`\nUntranslated dynamic labels (${uniqueDynamicLabelViolations.length}):`)
  for (const item of uniqueDynamicLabelViolations.slice(0, 160)) {
    console.log(`- ${item.relative}:${item.line} [${item.context}] ${item.reason}: ${item.expression}`)
  }
  if (uniqueDynamicLabelViolations.length > 160) {
    console.log(`- ... ${uniqueDynamicLabelViolations.length - 160} more`)
  }
}
if (uniqueLocalizedStateDefaultViolations.length) {
  console.log(`\nLocalized useState defaults rendered in form controls (${uniqueLocalizedStateDefaultViolations.length}):`)
  for (const item of uniqueLocalizedStateDefaultViolations) {
    console.log(`- ${item.relative}:${item.line} ${item.stateName}=${JSON.stringify(item.value)} -> <${item.tagName}> value at line ${item.usageLine}`)
  }
}
if (staleLocalizedStateDefaultViolations.length) {
  console.log(`\nLocale-stale useState defaults (${staleLocalizedStateDefaultViolations.length}):`)
  for (const item of staleLocalizedStateDefaultViolations) {
    console.log(`- ${item.relative}:${item.line} ${item.stateName}: ${item.expression}`)
  }
}
if (failures.length) {
  console.error(`\nFailures (${failures.length}):`)
  for (const failure of failures) console.error(`- ${failure}`)
  process.exitCode = 1
} else {
  console.log('\nStructural catalog checks: PASS')
}
