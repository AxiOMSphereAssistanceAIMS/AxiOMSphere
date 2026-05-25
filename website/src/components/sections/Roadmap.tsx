import { motion } from "framer-motion"
import { cn } from "@/lib/utils"

type MilestoneStatus = "current" | "active" | "planned" | "future"

interface Milestone {
  id: string
  title: string
  status: MilestoneStatus
  statusLabel: string
  description: string
}

const MILESTONES: Milestone[] = [
  {
    id: "M1",
    title: "Applied AIMS Work-Product Workflows",
    status: "current",
    statusLabel: "Current Applied Stage / Internal Validation",
    description: "Develop, review, align and trace connected AIMS work products.",
  },
  {
    id: "M2",
    title: "Controlled Knowledge and Self-Learning",
    status: "active",
    statusLabel: "In Development / Validation Required",
    description: "Build governed knowledge and validated improvement foundations.",
  },
  {
    id: "M3",
    title: "Self-Repair and Recovery",
    status: "planned",
    statusLabel: "Planned / Internal Architecture in Development",
    description:
      "Prepare controlled failure detection, correction and recovery capability.",
  },
  {
    id: "M4",
    title: "Self-Management and Orchestration",
    status: "planned",
    statusLabel: "Planned",
    description:
      "Develop coordination, execution control, feedback and resilience mechanisms.",
  },
  {
    id: "M5",
    title: "Client-Facing Industrial Assistant",
    status: "future",
    statusLabel: "Future Development",
    description:
      "Extend validated capabilities into context-aware specialist support.",
  },
  {
    id: "M6",
    title: "AIMS-Guided Project Development Support",
    status: "future",
    statusLabel: "Long-Term Vision",
    description:
      "Support structured project-startup and production-organisation development only after preceding layers are mature.",
  },
]

const statusStyles: Record<MilestoneStatus, string> = {
  current:
    "border-[rgba(14,165,233,0.35)] bg-[rgba(14,165,233,0.1)] text-site-accent",
  active:
    "border-[rgba(16,185,129,0.3)] bg-[rgba(16,185,129,0.08)] text-site-green",
  planned:
    "border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.07)] text-site-amber",
  future:
    "border-[rgba(100,130,200,0.2)] bg-[rgba(100,130,200,0.05)] text-site-subtle",
}

const rowVariants = {
  hidden: { opacity: 0, x: -12 },
  show: (i: number) => ({
    opacity: 1,
    x: 0,
    transition: { duration: 0.45, delay: i * 0.07 },
  }),
}

export function Roadmap() {
  return (
    <section
      id="roadmap"
      className="border-y border-[rgba(100,130,200,0.1)] bg-site-surface py-20"
    >
      <div className="container mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6 }}
          className="mb-8"
        >
          <p className="mb-2 text-xs font-bold uppercase tracking-widest text-site-accent">
            Development Roadmap
          </p>
          <h2 className="mb-3 text-2xl font-bold leading-tight tracking-tight text-site-text md:text-3xl">
            Controlled development through staged milestones.
          </h2>
          <p className="max-w-2xl text-base leading-relaxed text-site-muted">
            AxiOMSphere is being developed through controlled stages. The current applied document
            layer creates the evidence base required before broader capability can be responsibly
            pursued.
          </p>
        </motion.div>

        {/* Milestone rows */}
        <div className="overflow-hidden rounded-2xl border border-[rgba(100,130,200,0.12)]">
          {MILESTONES.map((ms, i) => (
            <motion.div
              key={ms.id}
              custom={i}
              variants={rowVariants}
              initial="hidden"
              whileInView="show"
              viewport={{ once: true, margin: "-40px" }}
              className={cn(
                "flex flex-col gap-3 border-b border-[rgba(100,130,200,0.08)] p-5 last:border-0 sm:flex-row sm:items-start sm:gap-5",
                ms.status === "current" && "bg-[rgba(14,165,233,0.03)]",
              )}
            >
              {/* ID badge */}
              <div className="shrink-0">
                <span
                  className={cn(
                    "inline-flex h-8 w-10 items-center justify-center rounded-lg text-xs font-bold",
                    ms.status === "current"
                      ? "bg-[rgba(14,165,233,0.15)] text-site-accent"
                      : "bg-[rgba(100,130,200,0.08)] text-site-muted",
                  )}
                >
                  {ms.id}
                </span>
              </div>

              {/* Content */}
              <div className="flex flex-1 flex-col gap-2 sm:flex-row sm:items-start sm:gap-4">
                <div className="flex-1">
                  <p className="text-sm font-semibold text-site-text">{ms.title}</p>
                  <p className="mt-1 text-sm leading-relaxed text-site-muted">{ms.description}</p>
                </div>
                <div className="shrink-0">
                  <span
                    className={cn(
                      "inline-block rounded-full border px-2.5 py-0.5 text-xs font-medium",
                      statusStyles[ms.status],
                    )}
                  >
                    {ms.statusLabel}
                  </span>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
