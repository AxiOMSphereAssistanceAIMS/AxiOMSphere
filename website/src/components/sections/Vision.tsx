import { motion } from "framer-motion"

export function Vision() {
  return (
    <section
      id="vision"
      className="border-y border-[rgba(100,130,200,0.1)] bg-site-surface py-20"
    >
      <div className="container mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6 }}
          className="max-w-3xl"
        >
          <p className="mb-2 text-xs font-bold uppercase tracking-widest text-site-accent">
            Long-Term Platform Vision
          </p>

          <div className="rounded-2xl border border-[rgba(100,130,200,0.12)] bg-site-card p-6">
            <p className="text-base leading-relaxed text-site-muted">
              The long-term objective is an industrial knowledge and coordination environment able
              to help specialists work with project history, approved company knowledge, connected
              departmental processes, interfaces and large information sets required for functional
              development, cost assessment and resource optimisation. Only after the supporting
              capabilities are validated and responsibly governed is AxiOMSphere intended to
              support broader AIMS-guided project-development workflows.
            </p>
          </div>
        </motion.div>
      </div>
    </section>
  )
}
