import { motion } from "framer-motion"

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
            Current Applied Capability
          </p>
          <h2 className="mb-4 text-2xl font-bold leading-tight tracking-tight text-site-text md:text-3xl">
            On-Demand AIMS Document Preparation and Review
          </h2>
          <p className="max-w-2xl text-base leading-relaxed text-site-muted">
            AxiOMSphere currently begins with on-demand support for specialists preparing and
            reviewing AIMS governing documents and related work products. This applied layer helps
            structure documents against applicable documentation requirements and organisational
            rules, improve clarity and completeness, and support professional review while technical
            content and approval remain with the accountable specialist.
          </p>
        </motion.div>

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
