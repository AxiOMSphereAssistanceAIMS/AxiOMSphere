import { motion } from "framer-motion"

export function Opportunity() {
  return (
    <section id="opportunity" className="py-20">
      <div className="container mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6 }}
        >
          <p className="mb-2 text-xs font-bold uppercase tracking-widest text-site-accent">
            The Industrial Problem
          </p>
          <div className="max-w-3xl space-y-4">
            <p className="text-base leading-relaxed text-site-muted">
              Industrial projects cannot operate reliably without an AIMS operating framework
              connecting processes, procedures, plans, registers, controls, responsibilities and
              functional interfaces. During early development and before full-field investment
              decisions, lean teams must make decisions that shape the future operating system while
              specialist capacity, information maturity and resources are still constrained.
              Inconsistent early decisions can propagate across connected work products and
              departmental interfaces, later becoming costly to identify and correct.
            </p>
            <p className="text-base leading-relaxed text-site-muted">
              Building this framework is multidisciplinary, information-intensive and sensitive.
              Specialists must work with applicable standards, regulatory requirements, company
              procedures, asset information, calculated and empirical indicators, functional
              responsibilities and cross-department interfaces. As requirements change, the impact
              can spread across multiple connected work products and generate repeated revision
              cycles, inconsistent assumptions and avoidable rework.
            </p>
          </div>
        </motion.div>
      </div>
    </section>
  )
}
