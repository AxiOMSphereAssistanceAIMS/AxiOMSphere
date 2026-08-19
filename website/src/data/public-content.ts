export const productDescriptor =
  "A human-governed AI platform for corporate documentation, engineering knowledge and operational readiness."

export const audienceStatement =
  "For project, operations, engineering, asset integrity and information-management teams working in complex, document-intensive environments."

export const projectStatus = {
  label: "Current applied capability · development-stage product",
  detail:
    "AxiOMSphere is validating privacy-first workflows that help specialists develop, review and coordinate connected AIMS work products and supporting documents.",
  roadmapNote:
    "The current product foundation is being extended through a staged, evidence-led roadmap.",
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
    id: "card-evidence-governed-repair",
    title: "Recover work with evidence-governed repair",
    status: "Certified control capability",
    support:
      "Evaluate the exact repair proposal, independent review, tests and risk before authorizing a fresh permit for a controlled restart of the existing repair lineage.",
    covers: ["Auditor attestation", "current-policy authorization", "duplicate-safe restart", "verified recovery"],
  },
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
  description: string
}

export const roadmapSectionTitle =
  "A focused product today, with a governed path toward broader organisational capability"

export const roadmapMilestones: RoadmapMilestone[] = [
  {
    id: "M1",
    title: "Current applied capability",
    statusLabel: "Available foundation",
    statusType: "current",
    description:
      "AIMS work-product drafting, review, registration and evidence retention, validated in internal development scenarios with source information kept within a private infrastructure boundary.",
  },
  {
    id: "M2",
    title: "Coordinated knowledge layer",
    statusLabel: "In development",
    statusType: "in-development",
    description:
      "Learning from validated outputs, framework-aligned evaluation and coordinated task contracts to improve the consistency and usefulness of future document work.",
  },
  {
    id: "M3",
    title: "Infrastructure resilience",
    statusLabel: "In development",
    statusType: "in-development",
    description:
      "Monitoring, evidence-governed repair and recovery with bounded behaviour, traceable outcomes and human oversight. Controlled restart is certified in a non-production canary; policy evolution remains separately governed.",
  },
  {
    id: "M4",
    title: "Orchestration at scale",
    statusLabel: "Planned direction",
    statusType: "planned",
    description:
      "Connected AIMS work products and change-impact tracing across the workflows that support complex projects.",
  },
  {
    id: "M5",
    title: "Controlled external pilot",
    statusLabel: "Future milestone",
    statusType: "planned",
    description:
      "A scoped, time-bounded pilot with a qualified industrial partner, subject to readiness evidence from the earlier milestones.",
  },
  {
    id: "M6",
    title: "Long-term platform vision",
    statusLabel: "Vision",
    statusType: "long-term",
    description:
      "Multi-project orchestration and a governed knowledge layer supporting specialised delivery with qualified human oversight.",
  },
]
