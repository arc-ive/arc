import { describe, it, expect } from 'vitest'
import { RISK_LEVELS, riskLabel, riskTone } from './skills.js'

describe('RISK_LEVELS', () => {
  it('matches the closed enum the API accepts', () => {
    // `SkillRiskLevel` in domain/models.py is exactly low | medium | high,
    // and the API 422s on anything else. Verified against the running API:
    // {"risk": "High"} and {"risk": "critical"} both return
    // "Input should be 'low', 'medium' or 'high'".
    //
    // The form shipped a free-text input, so the capitalised spelling a
    // person would naturally type was a server-side validation failure.
    expect(RISK_LEVELS.map((r) => r.value)).toEqual(['low', 'medium', 'high'])
  })

  it('orders the levels by severity, not alphabetically', () => {
    const values = RISK_LEVELS.map((r) => r.value)
    expect(values.indexOf('low')).toBeLessThan(values.indexOf('medium'))
    expect(values.indexOf('medium')).toBeLessThan(values.indexOf('high'))
  })
})

describe('riskLabel', () => {
  it('capitalises a stored value for display', () => {
    expect(riskLabel('high')).toBe('High')
    expect(riskLabel('medium')).toBe('Medium')
  })

  it('shows an unrecognised value rather than hiding it', () => {
    // A skill created before the enum was enforced could hold anything.
    // Dropping it would silently under-report the skill's risk.
    expect(riskLabel('critical')).toBe('critical')
  })

  it('returns null when a skill is unclassified', () => {
    expect(riskLabel(null)).toBeNull()
    expect(riskLabel('')).toBeNull()
  })
})

describe('riskTone', () => {
  it('escalates the tone with the level', () => {
    expect(riskTone('high')).toBe('danger')
    expect(riskTone('medium')).toBe('warning')
    expect(riskTone('low')).toBe('neutral')
  })

  it('does not guess at an unknown level', () => {
    // Colouring an unrecognised value red would assert a severity the
    // record does not carry.
    expect(riskTone('critical')).toBe('neutral')
    expect(riskTone(undefined)).toBe('neutral')
  })
})
