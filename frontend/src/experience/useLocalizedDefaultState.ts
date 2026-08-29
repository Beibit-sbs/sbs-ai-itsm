import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type DependencyList,
  type Dispatch,
  type SetStateAction,
} from 'react'
import { useTenantExperience } from './TenantExperienceContext'

type Translate = (source: string) => string
type LocalizedDefaultFactory<T> = (translate: Translate) => T

export function useLocalizedDefaultState<T = string>(
  sourceOrFactory: string | LocalizedDefaultFactory<T>,
  dependencies: DependencyList = [],
): [T, Dispatch<SetStateAction<T>>] {
  const { translate, uiLocale } = useTenantExperience()
  const localizedDefault = useMemo<T>(
    () => typeof sourceOrFactory === 'string'
      ? translate(sourceOrFactory) as T
      : sourceOrFactory(translate),
    // Factories are intentionally keyed by locale plus their explicit dependencies.
    // This keeps an inline factory stable between ordinary component renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    typeof sourceOrFactory === 'string'
      ? [uiLocale, sourceOrFactory]
      : [uiLocale, ...dependencies],
  )
  const previousDefault = useRef(localizedDefault)
  const [value, setValue] = useState<T>(localizedDefault)

  useEffect(() => {
    const staleDefault = previousDefault.current
    setValue((current) => Object.is(current, staleDefault) ? localizedDefault : current)
    previousDefault.current = localizedDefault
  }, [localizedDefault])

  return [value, setValue]
}
