export function formatLine(line: string): string {
  if (/^[+-]?0+(\.0+)?$/.test(line)) return 'Pick’em'
  const trimmed = line.replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '')
  return trimmed.startsWith('-') || trimmed.startsWith('+') ? trimmed : `+${trimmed}`
}
