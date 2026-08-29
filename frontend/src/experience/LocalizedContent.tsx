import {
  cloneElement,
  isValidElement,
  type ReactElement,
  type ReactNode,
} from 'react'
import { useTenantExperience } from './TenantExperienceContext'

const translatablePropNames = [
  'alt',
  'aria-description',
  'aria-label',
  'placeholder',
  'title',
] as const

function localizeString(source: string, translate: (value: string) => string) {
  const match = source.match(/^(\s*)(.*?)(\s*)$/s)
  if (!match || !match[2]) return source
  const lookup = match[2].replace(/\s+/g, ' ').trim()
  const localized = translate(lookup)
  if (localized === lookup) return source
  return `${match[1]}${localized}${match[3]}`
}

export function localizeTree(
  node: ReactNode,
  translate: (value: string) => string,
): ReactNode {
  if (typeof node === 'string') return localizeString(node, translate)
  if (Array.isArray(node)) {
    return node.map((child, index) => {
      const localizedChild = localizeTree(child, translate)
      if (isValidElement(localizedChild) && localizedChild.key == null) {
        return cloneElement(localizedChild, { key: `localized-${index}` })
      }
      return localizedChild
    })
  }
  if (!isValidElement(node)) return node

  const element = node as ReactElement<Record<string, unknown>>
  const localizedProps: Record<string, unknown> = {}
  for (const propName of translatablePropNames) {
    const value = element.props[propName]
    if (typeof value === 'string') {
      localizedProps[propName] = localizeString(value, translate)
    }
  }
  if ('children' in element.props) {
    localizedProps.children = localizeTree(
      element.props.children as ReactNode,
      translate,
    )
  }
  return cloneElement(element, localizedProps)
}

export default function LocalizedContent({ children }: { children: ReactNode }) {
  const { translate } = useTenantExperience()
  return <>{localizeTree(children, translate)}</>
}
