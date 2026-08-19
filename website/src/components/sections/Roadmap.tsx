import { motion } from "framer-motion"
import { cn } from "@/lib/utils"
import {
  roadmapSectionTitle,
  roadmapMilestones,
  type MilestoneStatusType,
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

export function Roadmap() {
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

        <motion.div
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-60px" }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="overflow-hidden rounded-2xl border border-[rgba(100,130,200,0.12)]"
          >
            {roadmapMilestones.map((ms) => (
              <div key={ms.id} className={cn("flex items-center gap-3 border-b border-[rgba(100,130,200,0.08)] px-5 py-4 last:border-0", ms.statusType === "current" && "bg-[rgba(14,165,233,0.025)]")}>
                <span className="flex h-7 w-9 shrink-0 items-center justify-center rounded-md bg-[rgba(100,130,200,0.08)] text-xs font-bold text-site-muted">{ms.id}</span>
                <span className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="text-sm font-semibold text-site-text sm:text-base">{ms.title}</span>
                  {ms.result && <span className="text-xs text-site-muted">{ms.result}</span>}
                </span>
                <span className={cn("shrink-0 rounded-full border px-2.5 py-0.5 text-xs font-medium", statusStyles[ms.statusType])}>{ms.statusLabel}</span>
              </div>
            ))}
          </motion.div>
      </div>
    </section>
  )
}
