import { KNOWLEDGE_SOURCES } from '../api/endpoints/knowledge.js'

export { KNOWLEDGE_SOURCES }

export const sourceLabels = {
  policy: 'Policy',
  procedure: 'Procedure',
  incident_report: 'Incident report',
  troubleshooting: 'Troubleshooting',
  internal_knowledge: 'Internal knowledge',
  solution: 'Solution',
}

/**
 * Badge tone for each knowledge source type.
 *
 * All neutral, deliberately. These are document TAXONOMY, not status, and
 * the previous mapping borrowed the status palette: an incident report
 * rendered in danger red and a troubleshooting note in warning amber, so a
 * perfectly healthy knowledge base looked like a page full of alarms. The
 * colour-named Badge API hid this — "red" asserts nothing, "danger" does.
 *
 * The label already names the type, so nothing is lost. If scanning a large
 * library proves harder without a colour channel, PR-3 owns Company Brain
 * presentation and can introduce a categorical palette that is distinct
 * from the status one.
 */
export const sourceVariants = {
  policy: 'neutral',
  procedure: 'neutral',
  incident_report: 'neutral',
  troubleshooting: 'neutral',
  internal_knowledge: 'neutral',
  solution: 'neutral',
}

export function isKnowledgeSource(value) {
  return KNOWLEDGE_SOURCES.includes(value)
}