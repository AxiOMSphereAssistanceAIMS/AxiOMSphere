import { motion } from "framer-motion"
import { FileText, Search, Link, Lock } from "lucide-react"
import { cn } from "@/lib/utils"

const STAGE_CARDS = [
  {
    icon: <FileText size={20} />,
    title: "Develop",
    desc: "Prepare structured AIMS work products and supporting document drafts for specialist review.",
  },
  {
    icon: <Search size={20} />,
    title: "Review",
    desc: "Support framework-alignment review using approved references and qualified human judgement.",
  },
  {
    icon: <Link size={20} />,
    title: "Connect",
    desc: "Improve traceability and consistency across related work products and supporting records.",
  },
  {
    icon: <Lock size={20} />,
    title: "Protect",
    desc: "Keep project source documents on private infrastructure and control any authorised external evaluation context.",
  },
]

const WORK_PRODUCTS = [
  "Philosophies",
  "Procedures",
  "Provisions",
  "Guidelines",
  "Regulations",
  "Instructions",
  "Job Descriptions",
  "Registers",
  "Plans",
  "Other connected AIMS work products",
]

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08 } },
}
const item = {
  hidden: { opacity: 0, y: 18 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45 } },
}

export function CurrentStage() {
  return (
    <section id="current-stage" className="py-20">
      <div className="container mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6 }}
          className="mb-8"
        >
          <p className="mb-2 text-xs font-bold uppercase tracking-widest text-site-accent">
            Current Applied Stage
          </p>
          <p className="max-w-2xl text-base leading-relaxed text-site-muted">
            Today, AxiOMSphere is validating AI-assisted workflows for developing, reviewing and
            coordinating connected AIMS work products and supporting documents in a controlled,
            privacy-first environment.
          </p>
        </motion.div>

        {/* 2×2 cards */}
        <motion.div
          variants={container}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: "-60px" }}
          className="mb-10 grid grid-cols-1 gap-4 sm:grid-cols-2"
        >
          {STAGE_CARDS.map((card) => (
            <motion.article
              key={card.title}
              variants={item}
              className={cn(
                "flex flex-col gap-3 rounded-2xl border border-[rgba(100,130,200,0.12)] bg-site-card p-6",
                "transition-all duration-300 hover:border-[rgba(14,165,233,0.28)] hover:shadow-[0_0_24px_rgba(14,165,233,0.07)]",
              )}
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[rgba(14,165,233,0.1)] text-site-accent">
                {card.icon}
              </div>
              <div>
                <h3 className="mb-1 text-sm font-semibold text-site-text">{card.title}</h3>
                <p className="text-sm leading-relaxed text-site-muted">{card.desc}</p>
              </div>
            </motion.article>
          ))}
        </motion.div>

        {/* Work product types */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
        >
          <p className="mb-3 text-sm font-bold text-site-text">
            Representative AIMS Work-Product Types
          </p>
          <div className="flex flex-wrap gap-2">
            {WORK_PRODUCTS.map((wp) => (
              <span
                key={wp}
                className="rounded-md border border-[rgba(100,130,200,0.15)] bg-[rgba(255,255,255,0.03)] px-3 py-1 text-xs text-site-muted"
              >
                {wp}
              </span>
            ))}
          </div>
          <p className="mt-3 text-xs italic text-site-subtle">
            Illustrative categories only. The applicable work-product set depends on project scope,
            company requirements and the approved AIMS framework.
          </p>
        </motion.div>
      </div>
    </section>
  )
}
