export function cn(...classes) {
  return classes.filter(Boolean).join(' ')
}

export function cx(...classes) {
  return cn(...classes)
}