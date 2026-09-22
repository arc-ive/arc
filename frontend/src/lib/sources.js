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

export const sourceVariants = {
  policy: 'indigo',
  procedure: 'cyan',
  incident_report: 'red',
  troubleshooting: 'amber',
  internal_knowledge: 'neutral',
  solution: 'green',
}

export function isKnowledgeSource(value) {
  return KNOWLEDGE_SOURCES.includes(value)
}