export const productDescriptor =
  "A human-governed AI platform for corporate documentation, engineering knowledge and operational readiness."

export const audienceStatement =
  "For project, operations, engineering, asset integrity and information-management teams working in complex, document-intensive environments."

export const projectStatus = {
  label: "Current project status · development-stage product",
  detail:
    "AxiOMSphere is advancing a human-governed platform for corporate documentation, engineering knowledge and operational readiness.",
  roadmapNote:
    "Published project stages are shown with their current status only.",
} as const

export const demoShowcase = {
  statusLabel: "A practical starting point",
  title: "From scattered requirements to a clearer working document",
  belowVideoText:
    "AxiOMSphere starts with a focused, useful workflow: helping a specialist turn an approved knowledge basis into a structured work-product draft, review it against the intended framework and keep the accountable professional in control of the result.",
} as const

export interface PlatformFlowStep {
  number: string
  title: string
  description: string
}

export const platformFlow: PlatformFlowStep[] = [
  {
    number: "01",
    title: "Understand approved knowledge",
    description: "Bring together the authorised requirements, standards and project context that should inform the work.",
  },
  {
    number: "02",
    title: "Structure requirements and evidence",
    description: "Make expected coverage, relationships and open questions easier for the team to see.",
  },
  {
    number: "03",
    title: "Develop governed content",
    description: "Create reusable structures and document drafts that support consistent professional work.",
  },
  {
    number: "04",
    title: "Review with accountable specialists",
    description: "Keep technical judgement, approval and intended use with the people responsible for the outcome.",
  },
  {
    number: "05",
    title: "Maintain and reuse what was learned",
    description: "Carry validated terminology, structures and lessons forward into future work where authorised.",
  },
]

export interface CapabilityCard {
  id: string
  title: string
  status: string
  support: string
  covers: string[]
}

export const capabilityCards: CapabilityCard[] = [
  {
    id: "card-1",
    title: "Build stronger corporate documents",
    status: "Current applied foundation",
    support:
      "Support specialists as they prepare and review structured AIMS work products, so the document is clearer, more complete and easier to govern.",
    covers: ["approved source understanding", "reusable structures", "controlled revisions", "professional review"],
  },
  {
    id: "card-2",
    title: "Connect requirements to content",
    status: "Current foundation · expanding",
    support:
      "Make the relationship between requirements, evidence and document content more visible during development and review.",
    covers: ["requirement coverage", "traceable rationale", "visible gaps", "consistent terminology"],
  },
  {
    id: "card-3",
    title: "Reuse organisational knowledge",
    status: "Developing capability",
    support:
      "Turn validated structures, language and lessons into a more repeatable way of working across connected teams and work products.",
    covers: ["common structures", "knowledge continuity", "controlled change", "reusable patterns"],
  },
  {
    id: "card-4",
    title: "Prepare for operations earlier",
    status: "Capability direction",
    support:
      "Help teams connect design, construction, commissioning, handover and operations thinking before readiness gaps become harder to address.",
    covers: ["readiness frameworks", "roles and dependencies", "handover continuity", "management review support"],
  },
  {
    id: "card-5",
    title: "Keep experts in control",
    status: "Core design principle",
    support:
      "Use AI to support preparation and coordination while accountable specialists retain judgement, approval and responsibility for decisions.",
    covers: ["human approval", "authorised sources", "traceable basis", "private information boundary"],
  },
]

export interface CopilotDirection {
  title: string
  audience: string
  support: string
}

export const copilotDirections: CopilotDirection[] = [
  {
    title: "Operations Readiness Copilot",
    audience: "Readiness, commissioning and operations leaders",
    support: "Surface dependencies, open questions and evidence that support a clearer path from project delivery into operations.",
  },
  {
    title: "Corporate Documentation Copilot",
    audience: "Document control, quality and technical teams",
    support: "Support consistent structures, terminology, review preparation and controlled updates across corporate work products.",
  },
  {
    title: "Asset Integrity Copilot",
    audience: "Asset integrity, reliability and maintenance teams",
    support: "Help organise the knowledge and work products that underpin dependable asset-management practices.",
  },
  {
    title: "Engineering Assurance Copilot",
    audience: "Engineering authorities and discipline specialists",
    support: "Prepare evidence, interfaces and review questions while leaving engineering acceptance with the accountable authority.",
  },
  {
    title: "Project-to-Operations Transition Copilot",
    audience: "Project directors and transition teams",
    support: "Maintain continuity of knowledge, responsibilities and outstanding actions across the handover into operations.",
  },
]

export type MilestoneStatusType = "current" | "in-development" | "planned" | "long-term"

export interface RoadmapMilestone {
  id: string
  title: string
  statusLabel: string
  statusType: MilestoneStatusType
  result?: string
}

export const roadmapSectionTitle =
  "Project stages — current status"

export const roadmapMilestones: RoadmapMilestone[] = [
  {
    id: "M1",
    title: "Current applied capability",
    statusLabel: "Available foundation",
    statusType: "current",
  },
  {
    id: "M2",
    title: "Coordinated knowledge layer",
    statusLabel: "In development",
    statusType: "in-development",
  },
  {
    id: "M3",
    title: "Infrastructure resilience",
    statusLabel: "Certified foundation",
    statusType: "current",
    result: "The current foundation is certified for governed development use.",
  },
  {
    id: "M4",
    title: "Orchestration at scale",
    statusLabel: "Planned direction",
    statusType: "planned",
  },
  {
    id: "M5",
    title: "Controlled external pilot",
    statusLabel: "Future milestone",
    statusType: "planned",
  },
  {
    id: "M6",
    title: "Long-term platform vision",
    statusLabel: "Vision",
    statusType: "long-term",
  },
]
