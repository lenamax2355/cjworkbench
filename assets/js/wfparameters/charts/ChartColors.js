export const defaultColors = [
  '#E24F4A',
  '#FBAA6D',
  '#48C8D7',
  '#2DAAA8',
  '#769BB0',
  '#A2A2A2'
]

export function getColor (idx) {
  return defaultColors[idx % defaultColors.length]
}
