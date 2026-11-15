export function formatLine(line: string): string {
  if (/^[+-]?0+(\.0+)?$/.test(line)) return 'Pick’em'
  const trimmed = line.replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '')
  return trimmed.startsWith('-') || trimmed.startsWith('+') ? trimmed : `+${trimmed}`
}

/** Shift the decimal point only; ROI is a server-calculated ratio, not money. */
export function formatRatio(ratio: string | null): string {
  if (ratio === null) return '—'
  const match = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(ratio)
  if (!match) return '—'
  const [, sign, whole, fraction = ''] = match
  const digits = fraction.padEnd(2, '0')
  const integer = `${whole}${digits.slice(0, 2)}`.replace(/^0+(?=\d)/, '')
  const decimal = digits.slice(2).replace(/0+$/, '')
  const prefix = sign === '-' && /[1-9]/.test(integer + decimal) ? '-' : ''
  return `${prefix}${integer}${decimal ? `.${decimal}` : ''}%`
}
