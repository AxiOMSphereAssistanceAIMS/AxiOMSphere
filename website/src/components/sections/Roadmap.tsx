import { createContext, useContext, useState } from "react"
import { motion, useReducedMotion } from "framer-motion"
import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  roadmapSectionTitle,
  roadmapMilestones,
  type MilestoneStatusType,
  type RoadmapMilestone,
} from "@/data/public-content"

const statusStyles: Record<MilestoneStatusType, string> = {
  current:
    "border-[rgba(14,165,233,0.35)] bg-[rgba(14,165,233,0.1)] text-site-accent",
  "in-development":
    "border-[rgba(16,185,129,0.3)] bg-[rgba(16,185,129,0.08)] text-site-green",
  planned:
    "border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.07)] text-site-amber",
  "long-term":
    "border-[rgba(100,130,200,0.2)] bg-[rgba(100,130,200,0.05)] text-site-subtle",
}

interface RoadmapCtxType {
  openId: string | null
  setOpenId: (id: string | null) => void
  prefersReducedMotion: boolean
}

const RoadmapCtx = createContext<RoadmapCtxType>({
  openId: null,
  setOpenId: () => {},
  prefersReducedMotion: false,
})

export function Roadmap() {
  const [openId, setOpenId] = useState<string | null>(null)
  const prefersReducedMotion = useReducedMotion() ?? false

  return (
    <section
      id="roadmap"
      className="border-b border-[rgba(100,130,200,0.1)] bg-site-bg py-20"
    >
      <div className="container mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6, delay: 0.1 }}
          className="mb-8"
        >
          <h2 className="max-w-3xl text-2xl font-bold leading-tight tracking-tight text-site-text md:text-3xl">
            {roadmapSectionTitle}
          </h2>
        </motion.div>

        <RoadmapCtx.Provider value={{ openId, setOpenId, prefersReducedMotion }}>
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-60px" }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="overflow-hidden rounded-2xl border border-[rgba(100,130,200,0.12)]"
          >
            {roadmapMilestones.map((ms) => (
              <MilestoneRow key={ms.id} milestone={ms} />
            ))}
          </motion.div>
        </RoadmapCtx.Provider>
      </div>
    </section>
  )
}

function MilestoneRow({ milestone }: { milestone: RoadmapMilestone }) {
  const { openId, setOpenId, prefersReducedMotion } = useContext(RoadmapCtx)
  const isOpen = openId === milestone.id
  const toggle = () => setOpenId(isOpen ? null : milestone.id)

  return (
    <div
      className={cn(
        "border-b border-[rgba(100,130,200,0.08)] last:border-0",
        milestone.statusType === "current" && "bg-[rgba(14,165,233,0.025)]",
      )}
    >
      {/* Trigger */}
      <button
        type="button"
        aria-expanded={isOpen}
        aria-controls={`${milestone.id}-desc`}
        id={`${milestone.id}-trigger`}
        onClick={toggle}
        className={cn(
          "flex w-full items-start gap-3 px-5 py-4 text-left",
          "transition-colors duration-150 hover:bg-[rgba(255,255,255,0.02)]",
          "focus-visible:rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-site-accent",
        )}
      >
        {/* Milestone ID badge */}
        <span
          className={cn(
            "mt-0.5 flex h-7 w-9 shrink-0 items-center justify-center rounded-md text-xs font-bold",
            milestone.statusType === "current"
              ? "bg-[rgba(14,165,233,0.15)] text-site-accent"
              : "bg-[rgba(100,130,200,0.08)] text-site-muted",
          )}
          aria-hidden="true"
        >
          {milestone.id}
        </span>

        {/* Title + status badge — stacked, always visible */}
        <span className="flex min-w-0 flex-1 flex-col gap-1.5">
          <span className="text-sm font-semibold leading-snug text-site-text sm:text-base">
            {milestone.title}
          </span>
          <span
            className={cn(
              "self-start rounded-full border px-2.5 py-0.5 text-xs font-medium",
              statusStyles[milestone.statusType],
            )}
          >
            {milestone.statusLabel}
          </span>
        </span>

        {/* Expand chevron */}
        <ChevronDown
          size={18}
          className={cn(
            "mt-1 shrink-0 text-site-subtle transition-transform duration-300",
            isOpen && "rotate-180",
          )}
          aria-hidden="true"
        />
      </button>

      {/* Collapsible description */}
      <motion.div
        id={`${milestone.id}-desc`}
        role="region"
        aria-labelledby={`${milestone.id}-trigger`}
        aria-hidden={!isOpen}
        initial={{ height: 0, opacity: 0 }}
        animate={isOpen ? { height: "auto", opacity: 1 } : { height: 0, opacity: 0 }}
        transition={
          prefersReducedMotion
            ? { duration: 0 }
            : { duration: 0.28, ease: [0.4, 0, 0.2, 1] }
        }
        style={{ overflow: "hidden" }}
      >
        <p className="border-t border-[rgba(100,130,200,0.08)] px-5 pb-5 pt-4 pl-[4.25rem] text-sm leading-relaxed text-site-muted">
          {milestone.description}
        </p>
      </motion.div>
    </div>
  )
}
