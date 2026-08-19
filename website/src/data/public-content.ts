export const audienceStatement =
  "For industrial project teams and engineers establishing Asset Integrity Management Systems (AIMS) before production begins."

// ---- Demo Showcase ----

export const demoShowcase = {
  statusLabel: "Current Applied Capability",
  title: "See the Applied Foundation in Practice",
  belowVideoText:
    "AxiOMSphere begins with a practical working layer: supporting specialists in the structured preparation and review of AIMS governing documents and related work products. This demonstration shows how the assistant helps an engineer develop clearer, more complete and more controlled deliverables as part of the wider preparation of the future operating organisation for start-up and operation.",
}

// ---- Strategic Roadmap ----

export const roadmapSectionTitle =
  "From On-Demand AIMS Document Support to a Scalable Industrial Project Development Product"

export type MilestoneStatusType = "current" | "in-development" | "planned" | "long-term"

export interface RoadmapMilestone {
  id: string
  title: string
  statusLabel: string
  statusType: MilestoneStatusType
  description: string
}

export const roadmapMilestones: RoadmapMilestone[] = [
  {
    id: "M1",
    title: "On-Demand AIMS Document Preparation and Review",
    statusLabel: "Current Applied Capability",
    statusType: "current",
    description:
      "AxiOMSphere currently begins with on-demand support for specialists preparing and reviewing AIMS governing documents and related work products. This applied layer helps structure documents against applicable documentation requirements and organisational rules, improve clarity and completeness, and support professional review while technical content and approval remain with the accountable specialist.",
  },
  {
    id: "M2",
    title: "Learning from Validated Engineering Work",
    statusLabel: "In Development",
    statusType: "in-development",
    description:
      "AxiOMSphere is being developed to learn from engineering work that has been reviewed, corrected and validated by accountable specialists. Approved deliverables, accepted corrections, rejected recommendations and identified gaps can become structured evidence for improving future document preparation, review quality and alignment with the organisation's AIMS approach. This capability is intended to help the system become more useful over time while ensuring that learning is grounded in confirmed engineering decisions rather than unverified outputs.",
  },
  {
    id: "M3",
    title: "Controlled Issue Correction and Autonomous Operational Recovery",
    statusLabel: "Certified foundation",
    statusType: "current",
    description: "The current foundation is certified for governed development use.",
  },
  {
    id: "M4",
    title: "Coordinated Execution across Connected AxiOMSphere Workflows",
    statusLabel: "Planned Capability",
    statusType: "planned",
    description:
      "AxiOMSphere is planned to coordinate connected execution workflows across its document preparation, review, learning, correction and autonomous operational recovery capabilities. Each task must be formed with a complete and sufficient input package, directed to the appropriate execution path, acknowledged on receipt and at the start of work, processed with traceable status and evidence, and returned with a result that can be evaluated against defined completion criteria. Where required information is missing, criteria are not met or execution fails, the workflow must request clarification, route the issue for correction or initiate approved recovery actions. This capability is intended to provide reliable end-to-end operation of the AxiOMSphere platform while preserving validated results, failures and lessons for continued improvement.",
  },
  {
    id: "M5",
    title: "Engineer and Client Support during AIMS Development and Project Readiness",
    statusLabel: "Planned Capability",
    statusType: "planned",
    description:
      "AxiOMSphere is planned to develop into an engineer- and client-facing support capability during AIMS establishment and preparation for start-up and operation. Building on connected work products, validated learning, system-level review and coordinated platform workflows, it is intended to provide responsible specialists with a clear view of relevant status, changing dependencies, identified gaps, interface concerns, outstanding inputs and recommended next actions within their discipline scope. The platform is intended to work with authorised project information, relevant developments across interfacing departments and the organisation's previously validated engineering experience, helping specialists understand how current decisions relate to wider project activity and established company practice. This capability is also intended to support daily, weekly and monthly work priorities, targeted retrieval and analysis of authorised information, and clear communication of readiness-related issues to the relevant client team. AxiOMSphere supports engineering awareness, coordination and decision preparation, while technical decisions and acceptance of client-project outputs remain with accountable specialists.",
  },
  {
    id: "M6",
    title: "Scalable Industrial Project Development Management Product",
    statusLabel: "Long-Term Product Direction",
    statusType: "long-term",
    description:
      "The long-term product direction is a scalable AxiOMSphere deployment for industrial clients developing Asset Integrity Management Systems and preparing future operating organisations for start-up and operation. At this level, the platform is intended to combine authorised project knowledge, previously validated company experience, connected AIMS functions and deliverables, interface dependencies, readiness findings, decision support and coordinated specialist workflows in one controlled working environment. The product may be configured and scaled to the required number of users, disciplines and project needs, whether deployed on client-owned infrastructure or, for an authorised pilot, on appropriately selected hosted computing resources. Where external model services are used, only authorised anonymised material without client or project attribution should pass through that external evaluation path; the connection to the client, company and project remains within the controlled internal environment.",
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
    title: "Integrating Discipline Deliverables within an Evolving Project",
    status: "Current Applied Foundation · In Development Expansion",
    support:
      "During early-stage industrial project development and preparation for start-up and operation, each discipline develops its own functions and deliverables within the organisation's AIMS philosophy and stakeholder expectations, while interfacing departments continually update their functions, interfaces, status and governing documents. AxiOMSphere begins by helping specialists create, review and connect structured discipline deliverables within the developing AIMS. Building on this applied foundation, the platform is being developed to analyse changes in interfacing departments, assess their impact on a discipline's own scope, and highlight where deliverables require coordination, review or adjustment.",
    covers: [
      "developing structured discipline deliverables as connected parts of the AIMS rather than isolated documents;",
      "reviewing deliverables against the organisation's AIMS philosophy, stakeholder expectations and relevant governing requirements;",
      "tracing how changing functions, interfaces, status and governing documents in interfacing departments may affect a discipline's own scope;",
      "identifying potential missing links, duplication or inconsistencies requiring engineering attention;",
      "supporting specialists in determining where coordination, review or adjustment of their deliverables is required.",
    ],
  },
  {
    id: "card-2",
    title: "System-Level Review of Hidden Gaps in the Developing AIMS",
    status: "In Development · Built on Current Applied Foundation",
    support:
      "As functions, responsibilities, interfaces and governing documents are developed across multiple disciplines, hidden inconsistencies may arise within the AIMS as a whole, even when individual deliverables appear complete. AxiOMSphere is designed to extend its applied work-product review foundation into system-level analysis of connected functions, responsibilities, interfaces and governing documents across disciplines. This capability is being developed to identify logical gaps, duplicated or missing responsibilities, conflicting interfaces and deviations from the organisation's AIMS philosophy or stakeholder expectations, and to present the responsible engineer with clear findings and recommended points for review and action before these issues affect start-up readiness or future operation.",
    covers: [
      "reviewing connected AIMS functions, responsibilities, interfaces and governing documents across multiple disciplines as one developing system;",
      "identifying logical gaps, missing responsibilities, duplicated functions and conflicting or insufficiently defined interfaces;",
      "detecting deviations from the organisation's AIMS philosophy and stakeholder expectations;",
      "relating detected inconsistencies to affected discipline scopes, deliverables and potential start-up readiness consequences;",
      "providing the responsible engineer with clear notifications and recommended points for review, coordination or corrective action;",
      "supporting early intervention before hidden system gaps result in costly rework, readiness delays or avoidable operational risk.",
    ],
  },
  {
    id: "card-3",
    title: "Designing Governing Documents with Accountable Functions and Valid Interfaces",
    status: "Current Applied Capability · Expanding Functional and Interface Assurance",
    support:
      "A governing document must be designed as an operational management instrument owned by the department accountable for the function it defines. It must clearly establish that department's responsibilities, controls and interfaces. Any interface responsibility assigned to another department must correspond to that department's approved function and accountable scope, and must be formally agreed through the relevant interface agreement. A document that is formally structured but avoids its own obligations, assigns unsupported or unagreed responsibilities elsewhere, or creates unmatched interfaces will not operate effectively within the AIMS and may lead to interface conflict, readiness gaps and later operational risk. AxiOMSphere supports specialists in developing and reviewing structured governing documents for clarity, completeness and requirements alignment, while expanding towards assessment of accountable functions, formally agreed interface responsibilities and interface validity across the developing AIMS.",
    covers: [
      "verifying that a governing document is structured for its intended purpose and clearly defines the function owned by the issuing department;",
      "reviewing whether the document establishes the department's own responsibilities, controls, required activities and decision points rather than obscuring or avoiding them;",
      "checking that stated interfaces with other departments are clear, necessary and connected to the function being governed;",
      "assessing whether any contribution or interface responsibility required from another department corresponds to that department's approved function and accountable scope;",
      "confirming whether cross-department interface responsibilities are formally agreed through the relevant interface agreement, rather than imposed unilaterally within one department's document;",
      "identifying unsupported, duplicated, missing or conflicting responsibilities that may prevent the document from operating effectively within the AIMS;",
      "reviewing document clarity, completeness, structure and alignment with applicable requirements, organisational documentation conventions and the organisation's AIMS philosophy;",
      "highlighting potential interface conflicts, accountability gaps and readiness risks for engineering review before they affect start-up or future operation.",
    ],
  },
  {
    id: "card-4",
    title: "Supporting Standards-Aligned Document Preparation While Preserving Engineering Focus",
    status: "Current Applied Capability · Expanding Document Quality and Compliance Support",
    support:
      "Engineering specialists must produce AIMS work products that are technically meaningful and also prepared in accordance with the applicable documentation framework: relevant international documentation standards and recognised practices, local regulatory and supervisory authority requirements, industry document-control and document-management requirements, and the organisation's own templates, terminology, branding and colour specifications. These requirements are essential for governing documents that can be consistently reviewed, approved, issued and used in practice. However, the repetitive effort required to select the correct document structure, apply mandatory sections and formatting rules, verify completeness, maintain controlled presentation and update revisions should not consume the specialist capacity required for engineering content, risk assessment, functional decisions and interface management. AxiOMSphere supports specialists in preparing and reviewing structured AIMS work products against the applicable documentation and organisational requirements, reducing routine preparation effort while keeping the engineer responsible for technical content and approval.",
    covers: [
      "selecting the appropriate document type and applying the required structure for philosophies, procedures, provisions, guidelines, regulations, instructions, job descriptions and other AIMS work products;",
      "applying relevant international documentation standards and recognised practices for document structure, clarity, mandatory content and usability;",
      "checking applicable local regulatory and supervisory authority requirements that affect the content, form or issue-readiness of the document;",
      "supporting industry document-control and document-management requirements, including controlled fields, document identification, revision status, review and approval attributes, and issue-readiness checks;",
      "applying the organisation's approved templates, terminology conventions, branding requirements, logos, headers, footers, typography and colour specifications;",
      "checking that mandatory sections, responsibilities, references, interfaces, controls and required supporting information are present and clearly expressed;",
      "improving clarity, consistency and professional readability without changing the accountable engineer's technical intent or approval responsibility;",
      "supporting controlled updates through document revisions while maintaining consistency of structure, terminology, presentation and traceability;",
      "reducing repetitive preparation and checking effort so specialists can focus on engineering content, risk assessment, functional decisions and interface management.",
    ],
  },
  {
    id: "card-5",
    title: "Turning Evolving AIMS Status into Actionable Discipline Priorities",
    status: "In Development · Built on Connected Work Products and System-Level Review",
    support:
      "During early-stage industrial project development and preparation for start-up and operation, engineering specialists must continuously understand what has changed across the developing AIMS, what remains outstanding, which dependencies affect their own discipline scope and where their attention is required next. AxiOMSphere is designed to consolidate connected work products, status updates, identified gaps, interface findings and required deliverables into a clear working view for the responsible specialist. Building on its applied document foundation and system-level review capability, the platform is being developed to highlight relevant changes, outstanding inputs, required reviews and recommended next actions, and to support the preparation of daily, weekly and monthly discipline work priorities. This helps engineers manage readiness activities without manually reconstructing the evolving project picture each day, while responsibility for technical decisions and approved actions remains with the accountable specialist.",
    covers: [
      "consolidating relevant status updates, work products, identified gaps, interface findings and outstanding inputs affecting a specialist's discipline scope;",
      "showing which changes in interfacing departments may require attention, coordination or adjustment within the specialist's own deliverables;",
      "identifying required reviews, missing information, unresolved dependencies and actions that could affect discipline readiness;",
      "presenting the engineer with a clear view of what is complete, what is outstanding, what has changed and what should be addressed next;",
      "supporting the preparation of daily, weekly and monthly discipline work priorities for deliverables, reviews, coordination actions, required inputs and follow-up;",
      "linking proposed priorities and recommended next actions to identified findings, affected interfaces, required deliverables and responsible engineering review;",
      "helping reduce time spent searching, cross-checking and manually reconstructing the current AIMS development status from dispersed information;",
      "supporting the engineer as an informed working assistant, while responsibility for technical decisions and approved actions remains with the accountable specialist.",
    ],
  },
]
