// cn(): joins class names and lets a later Tailwind class win over an earlier one of the same kind
// (the shadcn/ui helper: clsx + tailwind-merge).
import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
