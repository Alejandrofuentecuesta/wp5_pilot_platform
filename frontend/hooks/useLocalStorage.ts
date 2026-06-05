import { useState, useEffect, useCallback } from "react"

type SetStateAction<T> = T | ((prev: T) => T)

export function useLocalStorage<T>(
  key: string,
  fallback: T,
): [T, (value: SetStateAction<T>) => void] {
  const [value, setValue] = useState<T>(fallback)

  useEffect(() => {
    try {
      const stored = localStorage.getItem(key)
      if (stored !== null) {
        setValue(JSON.parse(stored) as T)
      } else {
        setValue(fallback)
      }
    } catch {
      // ignore localStorage errors (SSR, private browsing, etc.)
    }
  }, [key])

  const set = useCallback(
    (action: SetStateAction<T>) => {
      setValue((prev) => {
        const next = typeof action === "function"
          ? (action as (prev: T) => T)(prev)
          : action
        try {
          if (next === null) {
            localStorage.removeItem(key)
          } else {
            localStorage.setItem(key, JSON.stringify(next))
          }
        } catch {
          // ignore
        }
        return next
      })
    },
    [key],
  )

  return [value, set]
}
