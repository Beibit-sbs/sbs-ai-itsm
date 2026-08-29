import fs from 'node:fs'
import path from 'node:path'
import ts from 'typescript'

const sourceRoot = path.resolve('src')

function sourceFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const absolute = path.join(directory, entry.name)
    if (entry.isDirectory()) return sourceFiles(absolute)
    return entry.name.endsWith('.tsx') ? [absolute] : []
  })
}

function attributes(node) {
  return new Map(node.attributes.properties.flatMap((attribute) => {
    if (!ts.isJsxAttribute(attribute)) return []
    return [[attribute.name.text, attribute.initializer]]
  }))
}

function stringAttribute(initializer) {
  if (!initializer) return true
  if (ts.isStringLiteral(initializer)) return initializer.text
  if (
    ts.isJsxExpression(initializer)
    && initializer.expression
    && ts.isStringLiteral(initializer.expression)
  ) return initializer.expression.text
  return null
}

function governedByForm(node) {
  let parent = node.parent
  while (parent) {
    if (ts.isJsxElement(parent) && parent.openingElement.tagName.getText() === 'form') {
      return attributes(parent.openingElement).has('onSubmit')
    }
    parent = parent.parent
  }
  return false
}

let buttonCount = 0
const inertButtons = []
let linkCount = 0
const inertLinks = []

for (const filename of sourceFiles(sourceRoot)) {
  const source = fs.readFileSync(filename, 'utf8')
  const sourceFile = ts.createSourceFile(
    filename,
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  )
  const visit = (node) => {
    if (
      (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node))
      && node.tagName.getText() === 'button'
    ) {
      buttonCount += 1
      const props = attributes(node)
      const type = stringAttribute(props.get('type'))
      const directlyHandled = [
        'onClick',
        'onPointerDown',
        'onMouseDown',
        'formAction',
      ].some((name) => props.has(name))
      const submitsGovernedForm = type !== 'button' && governedByForm(node)
      if (!directlyHandled && !submitsGovernedForm) {
        const position = sourceFile.getLineAndCharacterOfPosition(node.getStart())
        inertButtons.push(
          `${path.relative(process.cwd(), filename)}:${position.line + 1}`,
        )
      }
    }
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tagName = node.tagName.getText()
      if (['a', 'Link', 'NavLink'].includes(tagName)) {
        linkCount += 1
        const props = attributes(node)
        const destination = tagName === 'a' ? 'href' : 'to'
        if (!props.has(destination) && !props.has('onClick')) {
          const position = sourceFile.getLineAndCharacterOfPosition(node.getStart())
          inertLinks.push(
            `${path.relative(process.cwd(), filename)}:${position.line + 1}`,
          )
        }
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
}

console.log(
  `Interactive controls: ${buttonCount} buttons and ${linkCount} links audited`,
)
if (inertButtons.length || inertLinks.length) {
  if (inertButtons.length) {
  console.error('Buttons without an action or governed form submission:')
  inertButtons.forEach((item) => console.error(`- ${item}`))
  }
  if (inertLinks.length) {
    console.error('Links without a destination or action:')
    inertLinks.forEach((item) => console.error(`- ${item}`))
  }
  process.exit(1)
}
console.log('Interactive control checks passed.')
